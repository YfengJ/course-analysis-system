import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from werkzeug.datastructures import FileStorage

from app import create_app
from config import TestingConfig
from models import (
    AnalysisRun,
    Assessment,
    Course,
    CourseInsight,
    CourseObjective,
    ImportBatch,
    Report,
    Student,
    db,
)
from services.analysis_revision_service import AnalysisRevisionService
from services.analysis_run_service import AnalysisRunService
from services.attainment_service import AttainmentService
from services.course_insight_service import CourseInsightService
from services.course_archive_service import CourseArchiveService
from services.course_progress_service import CourseProgressService
from services.data_backup_service import DataBackupService
from services.import_service import ImportService
from services.report_quality_service import ReportQualityService
from services.report_service import ReportService
from services.seed_service import DEFAULT_SEMESTER, create_generic_course_structure
from services.template_adapters.report_template_adapter import ReportTemplateAdapter


class DataIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_course(self, code="DATA001"):
        course = Course(
            code=code,
            name="数据完整性测试课程",
            semester=DEFAULT_SEMESTER,
            course_owner="测试教师",
            expected_value=0.65,
        )
        db.session.add(course)
        db.session.flush()
        create_generic_course_structure(course)
        for objective in course.objectives:
            objective.description = f"{objective.title}正式目标描述"
        db.session.commit()
        return course

    @staticmethod
    def _build_score_file(path, student_no="2026001", class_name="测试班", homework_score=4):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "成绩明细"
        sheet.append(["学号", "姓名", "班级", "课后作业", "大作业", "随堂测试", "期末考试", "上机实践"])
        sheet.append([student_no, "测试学生", class_name, homework_score, 4, 8, 60, 8])
        workbook.save(path)

    def test_multi_file_preview_rejects_student_number_conflicts_across_files(self):
        course = self._create_course()
        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = Path(temp_dir) / "一班.xlsx"
            second_path = Path(temp_dir) / "二班.xlsx"
            self._build_score_file(first_path, student_no="2026001", class_name="一班")
            self._build_score_file(second_path, student_no="2026001", class_name="二班")

            preview = ImportService.preview_score_files([first_path, second_path], course, DEFAULT_SEMESTER)

        self.assertFalse(preview["success"])
        self.assertTrue(any("跨文件" in issue and "2026001" in issue for issue in preview["issues"]))

    def test_uploading_same_filename_twice_does_not_overwrite_first_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = FileStorage(stream=BytesIO(b"first"), filename="scores.xlsx")
            second = FileStorage(stream=BytesIO(b"second"), filename="scores.xlsx")

            first_path = ImportService.save_upload(first, temp_dir)
            second_path = ImportService.save_upload(second, temp_dir)

            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first_path.read_bytes(), b"first")
            self.assertEqual(second_path.read_bytes(), b"second")

    def test_chinese_upload_filename_preserves_supported_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            upload = FileStorage(stream=BytesIO(b"content"), filename="课程成绩表.xlsx")

            saved_path = ImportService.save_upload(upload, temp_dir)

            self.assertEqual(saved_path.suffix, ".xlsx")

    def test_pending_score_import_session_contains_only_safe_filenames(self):
        course = self._create_course()
        with tempfile.TemporaryDirectory() as temp_dir:
            score_path = Path(temp_dir) / "成绩.xlsx"
            self._build_score_file(score_path)
            response = self.client.post(
                f"/courses/{course.id}/imports/",
                data={
                    "semester": DEFAULT_SEMESTER,
                    "file": (BytesIO(score_path.read_bytes()), "scores.xlsx"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            pending = session["pending_score_import"]
            self.assertIn("filenames", pending)
            self.assertNotIn("file_paths", pending)

    def test_changing_expected_value_invalidates_current_analysis(self):
        course = self._create_course()
        db.session.add(
            AnalysisRun(
                course_id=course.id,
                semester=DEFAULT_SEMESTER,
                class_scope="全部班级",
                status="已计算",
            )
        )
        db.session.commit()

        response = self.client.post(
            f"/courses/{course.id}",
            data={
                "code": course.code,
                "name": course.name,
                "course_owner": course.course_owner,
                "semester": course.semester,
                "class_names": course.class_names or "",
                "hours": course.hours,
                "credits": course.credits,
                "assessment_method": course.assessment_method,
                "expected_value": 0.7,
                "department": course.department or "",
                "major": course.major or "",
                "description": course.description or "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AnalysisRun.query.filter_by(course_id=course.id).count(), 0)

    def test_adding_course_objective_invalidates_current_analysis(self):
        course = self._create_course()
        db.session.add(
            AnalysisRun(
                course_id=course.id,
                semester=DEFAULT_SEMESTER,
                class_scope="全部班级",
                status="已计算",
            )
        )
        db.session.commit()

        response = self.client.post(
            f"/courses/{course.id}/objectives",
            data={
                "title": "新增目标",
                "description": "新增目标的正式描述",
                "weight": 1,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AnalysisRun.query.filter_by(course_id=course.id).count(), 0)

    def test_multi_file_import_rolls_back_cleanup_and_partial_rows_on_failure(self):
        course = self._create_course()
        old_student = Student(
            course_id=course.id,
            student_no="OLD001",
            name="原学生",
            class_name="原班级",
            semester=DEFAULT_SEMESTER,
        )
        db.session.add(old_student)
        db.session.commit()
        call_count = 0

        def import_side_effect(path, target_course, semester, reset_semester=False, commit=True):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                db.session.add(
                    Student(
                        course_id=target_course.id,
                        student_no="NEW001",
                        name="新学生",
                        class_name="新班级",
                        semester=semester,
                    )
                )
                return {"success": True, "issues": [], "imported": 1, "batch": None}
            raise RuntimeError("第二个文件写入失败")

        preview = {
            "success": True,
            "issues": [],
            "files": [],
            "classes": [],
            "imported_estimate": 2,
            "semester": DEFAULT_SEMESTER,
        }
        with patch.object(ImportService, "preview_score_files", return_value=preview), patch.object(
            ImportService,
            "import_scores",
            side_effect=import_side_effect,
        ):
            with self.assertRaises(RuntimeError):
                ImportService.import_score_files([Path("first.xlsx"), Path("second.xlsx")], course, DEFAULT_SEMESTER)

        self.assertIsNotNone(Student.query.filter_by(course_id=course.id, student_no="OLD001").first())
        self.assertIsNone(Student.query.filter_by(course_id=course.id, student_no="NEW001").first())

    def test_new_score_import_invalidates_current_analysis_revision_and_insight(self):
        course = self._create_course()
        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = Path(temp_dir) / "第一版.xlsx"
            second_path = Path(temp_dir) / "第二版.xlsx"
            self._build_score_file(first_path, homework_score=4)
            self._build_score_file(second_path, homework_score=5)
            self.assertTrue(ImportService.import_score_files([first_path], course, DEFAULT_SEMESTER)["success"])

            summary = AttainmentService.calculate(course, DEFAULT_SEMESTER, "全部班级")
            AnalysisRunService.mark_complete(
                course.id,
                DEFAULT_SEMESTER,
                "全部班级",
                summary["student_count"],
                summary=summary,
            )
            AnalysisRevisionService.save_revision(
                course.id,
                DEFAULT_SEMESTER,
                "全部班级",
                qualitative_overrides={},
                analysis_note="旧分析说明",
            )
            CourseInsightService.save_manual_for_scope(
                course.id,
                DEFAULT_SEMESTER,
                "全部班级",
                "旧第五章分析",
                "旧改进措施",
            )
            report = Report(
                course_id=course.id,
                semester=DEFAULT_SEMESTER,
                class_scope="全部班级",
                html_snapshot="{}",
            )
            db.session.add(report)
            db.session.commit()

            self.assertTrue(ImportService.import_score_files([second_path], course, DEFAULT_SEMESTER)["success"])

        self.assertEqual(AnalysisRun.query.filter_by(course_id=course.id, semester=DEFAULT_SEMESTER).count(), 0)
        self.assertIsNone(AnalysisRevisionService.get_active_revision(course.id, DEFAULT_SEMESTER, "全部班级"))
        self.assertEqual(CourseInsight.query.filter_by(course_id=course.id, semester=DEFAULT_SEMESTER).count(), 0)
        self.assertIsNotNone(db.session.get(Report, report.id))
        self.assertFalse(AnalysisRunService.is_ready(course.id, DEFAULT_SEMESTER, "全部班级"))
        progress = CourseProgressService.build_snapshot(course)
        self.assertFalse(progress["analysis_ready"])
        self.assertFalse(progress["report_ready"])
        self.assertEqual(progress["status_group"], "pending")

    def test_chapter_five_change_marks_existing_report_as_stale(self):
        course = self._create_course()
        analysis = AnalysisRun(
            course_id=course.id,
            semester=DEFAULT_SEMESTER,
            class_scope="全部班级",
            status="已计算",
        )
        db.session.add(analysis)
        db.session.commit()
        report = Report(
            course_id=course.id,
            semester=DEFAULT_SEMESTER,
            class_scope="全部班级",
            html_snapshot="{}",
        )
        db.session.add(report)
        db.session.commit()
        self.assertTrue(CourseProgressService.build_snapshot(course)["report_ready"])

        CourseInsightService.save_manual_for_scope(
            course.id,
            DEFAULT_SEMESTER,
            "全部班级",
            "报告导出后更新的第五章分析",
            "报告导出后更新的改进措施",
        )

        self.assertFalse(CourseProgressService.build_snapshot(course)["report_ready"])

    def test_report_quality_rejects_objective_weights_not_equal_to_one_hundred(self):
        course = self._create_course()
        course.objectives[0].weight += 5
        db.session.commit()

        result = ReportQualityService.check_course_report(course, DEFAULT_SEMESTER, "全部班级", strict=True)

        self.assertTrue(
            any(item["level"] == "error" and item["category"] == "权重配置" for item in result["items"])
        )

    def test_report_quality_rejects_objective_without_assessment_mapping(self):
        course = self._create_course()
        db.session.add(
            CourseObjective(
                course_id=course.id,
                sequence=99,
                title="未绑定目标",
                description="正式但尚未绑定考核项的课程目标",
                weight=0,
            )
        )
        db.session.commit()

        result = ReportQualityService.check_course_report(course, DEFAULT_SEMESTER, "全部班级", strict=True)

        self.assertTrue(any("课程目标未绑定考核项" in item["message"] for item in result["items"]))

    def test_report_quality_rejects_assessment_weight_total_mismatch(self):
        course = self._create_course()
        assessment = Assessment.query.filter_by(course_id=course.id).first()
        assessment.total_score += 1
        db.session.commit()

        result = ReportQualityService.check_course_report(course, DEFAULT_SEMESTER, "全部班级", strict=True)

        self.assertTrue(any("目标分值分配" in item["message"] for item in result["items"]))

    def test_manual_qualitative_counts_must_match_student_count(self):
        summary = {
            "student_count": 3,
            "objective_results": [{"objective_id": 1, "objective_title": "课程目标1"}],
        }
        overrides = {
            "1": {
                "excellent_count": 1,
                "good_count": 1,
                "medium_count": 0,
                "poor_count": 0,
            }
        }

        errors = AnalysisRevisionService.validate_qualitative_overrides(summary, overrides)

        self.assertTrue(any("课程目标1" in error and "3" in error for error in errors))

    def test_report_context_uses_import_from_selected_semester(self):
        course = self._create_course()
        selected = ImportBatch(
            course_id=course.id,
            semester="2025-2026-1",
            filename="selected.xlsx",
            source_format="xlsx",
        )
        newer_other_semester = ImportBatch(
            course_id=course.id,
            semester="2025-2026-2",
            filename="other.xlsx",
            source_format="xlsx",
        )
        db.session.add_all([selected, newer_other_semester])
        db.session.commit()

        context = ReportService.build_report_context(course, "2025-2026-1", "全部班级")

        self.assertEqual(context["latest_import"].id, selected.id)

    def test_generated_report_records_source_import_ids(self):
        course = self._create_course()
        batch = ImportBatch(
            course_id=course.id,
            semester=DEFAULT_SEMESTER,
            filename="source.xlsx",
            source_format="xlsx",
        )
        db.session.add(batch)
        db.session.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            report, _ = ReportService.generate_word_report(
                course,
                DEFAULT_SEMESTER,
                "全部班级",
                temp_dir,
            )

        self.assertEqual(json.loads(report.source_import_ids_json), [batch.id])

    def test_report_download_rejects_file_outside_configured_report_folder(self):
        course = self._create_course()
        with tempfile.TemporaryDirectory() as temp_dir:
            outside_path = Path(temp_dir) / "outside.docx"
            outside_path.write_bytes(b"not-a-real-report")
            report = Report(
                course_id=course.id,
                semester=DEFAULT_SEMESTER,
                class_scope="全部班级",
                word_path=str(outside_path),
            )
            db.session.add(report)
            db.session.commit()

            response = self.client.get(f"/courses/{course.id}/reports/download/{report.id}")

        self.assertEqual(response.status_code, 404)

    def test_course_archive_does_not_package_report_outside_export_folder(self):
        course = self._create_course()
        with tempfile.TemporaryDirectory() as export_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside_path = Path(outside_dir) / "outside-private.docx"
            outside_path.write_bytes(b"private")
            db.session.add(
                Report(
                    course_id=course.id,
                    semester=DEFAULT_SEMESTER,
                    class_scope="全部班级",
                    word_path=str(outside_path),
                )
            )
            db.session.commit()

            archive_path = CourseArchiveService.build_archive(
                course,
                DEFAULT_SEMESTER,
                "全部班级",
                export_dir,
            )
            with zipfile.ZipFile(archive_path) as package:
                names = package.namelist()

        self.assertFalse(any(name.endswith("outside-private.docx") for name in names))


class BackupIntegrityTest(unittest.TestCase):
    def test_invalid_sqlite_backup_is_rejected_before_live_database_is_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            db_path = data_dir / "instance" / "attainment_system.db"

            class BackupConfig(TestingConfig):
                DATA_DIR = str(data_dir)
                SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
                BACKUP_FOLDER = str(data_dir / "backups")
                UPLOAD_FOLDER = str(data_dir / "uploads")
                EXPORT_FOLDER = str(data_dir / "exports")
                REPORT_FOLDER = str(data_dir / "exports" / "reports")
                SAMPLE_DATA_FOLDER = str(data_dir / "sample_data")

            app = create_app(BackupConfig)
            with app.app_context():
                db.drop_all()
                db.create_all()
                db.session.add(Course(code="SAFE001", name="保留课程", course_owner="教师"))
                db.session.commit()
                bad_backup = data_dir / "bad-backup.zip"
                with zipfile.ZipFile(bad_backup, "w") as package:
                    package.writestr("manifest.json", json.dumps({"version": "1.0"}))
                    package.writestr(DataBackupService.DATABASE_MEMBER, b"not-a-sqlite-database")

                with self.assertRaises(ValueError):
                    DataBackupService.restore_backup(app, bad_backup)

                self.assertIsNotNone(Course.query.filter_by(code="SAFE001").first())


class RuntimeArtifactPathTest(unittest.TestCase):
    def test_report_chart_cache_lives_under_runtime_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "runtime"

            class RuntimeConfig(TestingConfig):
                DATA_DIR = str(data_dir)
                SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
                SAMPLE_DATA_FOLDER = str(Path(temp_dir) / "sample_data")

            app = create_app(RuntimeConfig)
            with app.app_context():
                chart_dir = ReportTemplateAdapter._chart_output_dir().resolve()
                asset_dir = ReportTemplateAdapter._asset_output_dir().resolve()

            self.assertIn(data_dir.resolve(), [chart_dir, *chart_dir.parents])
            self.assertIn(data_dir.resolve(), [asset_dir, *asset_dir.parents])


if __name__ == "__main__":
    unittest.main()
