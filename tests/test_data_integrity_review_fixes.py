import json
import shutil
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
import pandas as pd
from werkzeug.datastructures import FileStorage

from app import create_app
from config import TestingConfig
from models import (
    AnalysisRevision,
    AnalysisRun,
    AnalysisSnapshot,
    Assessment,
    Course,
    CourseInsight,
    CourseObjective,
    ImportBatch,
    ObjectiveScore,
    QualitativeRecord,
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
from services.llm_service import LLMService
from services.report_quality_service import ReportQualityService
from services.report_service import ReportService
from services.seed_service import DEFAULT_SEMESTER, create_generic_course_structure
from services.template_adapters.outline_template_adapter import OutlineTemplateAdapter
from services.template_adapters.report_template_adapter import ReportTemplateAdapter
from services.template_adapters.score_template_adapter import ScoreTemplateAdapter


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

    def test_invalid_docx_does_not_crash_outline_driven_course_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.app.config["UPLOAD_FOLDER"] = temp_dir
            self.app.config["PROPAGATE_EXCEPTIONS"] = False
            response = self.client.post(
                "/courses/new/from-outline",
                data={"file": (BytesIO(b"not-a-valid-docx"), "outline.docx")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/courses/new"))

    def test_invalid_docx_does_not_crash_existing_course_outline_preview(self):
        course = self._create_course()
        with tempfile.TemporaryDirectory() as temp_dir:
            self.app.config["UPLOAD_FOLDER"] = temp_dir
            self.app.config["PROPAGATE_EXCEPTIONS"] = False
            response = self.client.post(
                f"/courses/{course.id}/outline",
                data={"file": (BytesIO(b"not-a-valid-docx"), "outline.docx")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith(f"/courses/{course.id}/outline"))

    def test_invalid_course_form_displays_validation_errors(self):
        response = self.client.post(
            "/courses/new",
            data={
                "code": "",
                "name": "",
                "course_owner": "",
                "hours": "-1",
                "credits": "-1",
                "expected_value": "2",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("请检查以下内容".encode("utf-8"), response.data)
        self.assertIn("课程编号".encode("utf-8"), response.data)

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

    def test_objective_split_preview_rejects_non_numeric_score_text(self):
        course = self._create_course()
        rows = [
            ["", "", "", "", "", ""],
            ["", "", "", "", "", ""],
            ["", "", "", "", "课程目标1", ""],
            ["序号", "学号", "姓名", "班级", "课后作业", "达成度"],
            ["", "", "", "", 5, 35],
            ["", "", "", "", 5, 100],
            [1, "2026001", "测试学生", "测试班", "不是数字", 0.8],
        ]
        adapter_result = ScoreTemplateAdapter._parse_teacher_sheet("成绩表", pd.DataFrame(rows))

        preview = ImportService._preview_objective_split_scores(
            adapter_result,
            Path("成绩表.xlsx"),
            course,
        )

        parsed_score = adapter_result["records"][0]["objective_scores"]["课程目标1"]["课后作业"]
        self.assertEqual(parsed_score, "不是数字")
        self.assertTrue(any("不是有效数字" in issue for issue in preview["issues"]))

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

    def test_reimporting_outline_removes_objectives_no_longer_in_source(self):
        course = self._create_course()
        removed_objectives = sorted(course.objectives, key=lambda item: item.sequence)[1:]
        removed_ids = [item.id for item in removed_objectives]
        db.session.add(
            QualitativeRecord(
                course_id=course.id,
                objective_id=removed_ids[0],
                semester=DEFAULT_SEMESTER,
            )
        )
        db.session.commit()
        adapter_result = {
            "raw_text": "更新后的教学大纲",
            "summary": "更新后的教学大纲",
            "payload": {
                "course_name": course.name,
                "course_code": course.code,
                "objectives": [
                    {
                        "title": "课程目标1",
                        "description": "更新后仅保留的课程目标描述",
                    }
                ],
                "requirements": [],
                "assessment_support": [],
                "confidence": 1.0,
            },
        }

        with patch.object(OutlineTemplateAdapter, "extract", return_value=adapter_result):
            ImportService.import_outline(Path("updated-outline.docx"), course)

        current_objectives = CourseObjective.query.filter_by(course_id=course.id).all()
        self.assertEqual(len(current_objectives), 1)
        self.assertEqual(current_objectives[0].description, "更新后仅保留的课程目标描述")
        self.assertEqual(QualitativeRecord.query.filter(QualitativeRecord.objective_id.in_(removed_ids)).count(), 0)

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

    def test_invalidated_modern_analysis_is_not_restored_by_historical_report(self):
        course = self._create_course()
        AnalysisRunService.mark_complete(
            course.id,
            DEFAULT_SEMESTER,
            "全部班级",
            1,
            summary={"student_count": 1, "total_status": "已达成"},
        )
        db.session.add(
            Report(
                course_id=course.id,
                semester=DEFAULT_SEMESTER,
                class_scope="全部班级",
                html_snapshot="{}",
            )
        )
        db.session.commit()

        AnalysisRunService.invalidate_for_input_change(course.id, DEFAULT_SEMESTER)
        db.session.commit()

        self.assertFalse(AnalysisRunService.is_ready(course.id, DEFAULT_SEMESTER, "全部班级"))
        progress = CourseProgressService.build_snapshot(course)
        self.assertFalse(progress["analysis_ready"])
        self.assertFalse(progress["report_ready"])
        response = self.client.get(f"/courses/{course.id}")
        self.assertIn("0/4 阶段已完成".encode("utf-8"), response.data)

    def test_invalidated_legacy_report_without_snapshot_is_not_considered_ready(self):
        course = self._create_course()
        db.session.add(
            AnalysisRun(
                course_id=course.id,
                semester=DEFAULT_SEMESTER,
                class_scope="全部班级",
                status="已计算",
            )
        )
        db.session.add(
            Report(
                course_id=course.id,
                semester=DEFAULT_SEMESTER,
                class_scope="全部班级",
                html_snapshot="{}",
            )
        )
        db.session.commit()

        AnalysisRunService.invalidate_for_input_change(course.id, DEFAULT_SEMESTER)
        db.session.commit()

        self.assertFalse(AnalysisRunService.is_ready(course.id, DEFAULT_SEMESTER, "全部班级"))
        snapshot = AnalysisRunService.latest_snapshot(course.id, DEFAULT_SEMESTER, "全部班级")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.status, "已失效")

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

    def test_course_progress_does_not_combine_analysis_and_report_from_different_scopes(self):
        course = self._create_course()
        db.session.add(
            AnalysisRun(
                course_id=course.id,
                semester="2025-2026学年第2学期",
                class_scope="二班",
                status="已计算",
            )
        )
        db.session.commit()
        db.session.add(
            Report(
                course_id=course.id,
                semester="2025-2026学年第1学期",
                class_scope="一班",
                html_snapshot="{}",
            )
        )
        db.session.commit()

        progress = CourseProgressService.build_snapshot(course)

        self.assertTrue(progress["analysis_ready"])
        self.assertFalse(progress["report_ready"])

    def test_total_qualitative_attainment_matches_weighted_objective_formula(self):
        course = self._create_course()
        objectives = sorted(course.objectives, key=lambda item: item.sequence)
        for objective, weight in zip(objectives, (50, 50, 0)):
            objective.weight = weight
        student = Student(
            course_id=course.id,
            student_no="QUAL001",
            name="定性口径测试学生",
            class_name="测试班",
            semester=DEFAULT_SEMESTER,
        )
        db.session.add(student)
        db.session.flush()
        for objective, rate in zip(objectives, (0.99, 0.61, 0.61)):
            for objective_weight in objective.assessment_weights:
                db.session.add(
                    ObjectiveScore(
                        student_id=student.id,
                        objective_weight_id=objective_weight.id,
                        score=objective_weight.weight_score * rate,
                    )
                )
        course.student_count = 1
        db.session.commit()

        summary = AttainmentService.calculate(course, DEFAULT_SEMESTER, "全部班级")

        self.assertEqual(summary["total_qualitative_attainment"], 0.75)
        self.assertTrue(summary["chapter_four"]["qualitative_formula"].endswith("=0.75。"))

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

    def test_report_quality_does_not_fall_back_to_other_classes_when_scope_is_empty(self):
        course = self._create_course()
        db.session.add(
            Student(
                course_id=course.id,
                student_no="ONLY-A",
                name="一班学生",
                class_name="一班",
                semester=DEFAULT_SEMESTER,
            )
        )
        db.session.commit()

        result = ReportQualityService.check_course_report(
            course,
            DEFAULT_SEMESTER,
            "二班",
            strict=True,
        )

        score_item = next(item for item in result["items"] if item["category"] == "成绩数据")
        self.assertEqual(score_item["level"], "error")
        self.assertIn("没有学生成绩", score_item["message"])

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

    def test_analysis_revision_request_rolls_back_all_evidence_on_snapshot_failure(self):
        course = self._create_course()
        student = Student(
            course_id=course.id,
            student_no="TX001",
            name="事务测试学生",
            class_name="测试班",
            semester=DEFAULT_SEMESTER,
        )
        db.session.add(student)
        db.session.commit()
        payload = {
            "semester": DEFAULT_SEMESTER,
            "class_scope": "全部班级",
            "action": "save_revision",
        }
        for objective in course.objectives:
            payload.update(
                {
                    f"excellent_count_{objective.id}": "0",
                    f"good_count_{objective.id}": "0",
                    f"medium_count_{objective.id}": "0",
                    f"poor_count_{objective.id}": "1",
                }
            )
        self.app.config["PROPAGATE_EXCEPTIONS"] = False

        with patch.object(AnalysisRunService, "mark_complete", side_effect=RuntimeError("snapshot failed")):
            response = self.client.post(f"/courses/{course.id}/analysis/", data=payload)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AnalysisRevision.query.filter_by(course_id=course.id).count(), 0)
        self.assertEqual(QualitativeRecord.query.filter_by(course_id=course.id).count(), 0)
        self.assertEqual(AnalysisSnapshot.query.filter_by(course_id=course.id).count(), 0)

    def test_analysis_snapshot_records_current_import_sources(self):
        course = self._create_course()
        db.session.add(
            Student(
                course_id=course.id,
                student_no="SOURCE001",
                name="来源测试学生",
                class_name="测试班",
                semester=DEFAULT_SEMESTER,
            )
        )
        batch = ImportBatch(
            course_id=course.id,
            semester=DEFAULT_SEMESTER,
            filename="source.xlsx",
            source_format="xlsx",
        )
        db.session.add(batch)
        db.session.commit()

        response = self.client.post(
            f"/courses/{course.id}/analysis/",
            data={
                "semester": DEFAULT_SEMESTER,
                "class_scope": "全部班级",
                "action": "recalculate",
            },
        )

        self.assertEqual(response.status_code, 302)
        snapshot = AnalysisRunService.latest_snapshot(course.id, DEFAULT_SEMESTER, "全部班级")
        self.assertEqual(json.loads(snapshot.source_import_ids_json), [batch.id])

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

    def test_insight_prompt_uses_active_revision_and_selected_semester_import(self):
        course = self._create_course()
        student = Student(
            course_id=course.id,
            student_no="AI001",
            name="智能分析测试学生",
            class_name="测试班",
            semester=DEFAULT_SEMESTER,
        )
        db.session.add(student)
        db.session.flush()
        overrides = {
            str(objective.id): {
                "excellent_count": 1,
                "good_count": 0,
                "medium_count": 0,
                "poor_count": 0,
            }
            for objective in course.objectives
        }
        AnalysisRevisionService.save_revision(
            course.id,
            DEFAULT_SEMESTER,
            "全部班级",
            qualitative_overrides=overrides,
        )
        db.session.add_all(
            [
                ImportBatch(
                    course_id=course.id,
                    semester=DEFAULT_SEMESTER,
                    filename="selected.xlsx",
                    source_format="xlsx",
                ),
                ImportBatch(
                    course_id=course.id,
                    semester="2025-2026学年第2学期",
                    filename="other-semester.xlsx",
                    source_format="xlsx",
                ),
            ]
        )
        db.session.commit()
        captured = {}

        def fail_after_capture(prompt):
            captured["prompt"] = prompt
            raise RuntimeError("model unavailable")

        with patch.object(LLMService, "is_configured", return_value=True), patch.object(
            LLMService,
            "build_course_insight",
            side_effect=fail_after_capture,
        ):
            CourseInsightService.generate_for_scope(course, DEFAULT_SEMESTER, "全部班级")

        prompt_payload = json.loads(captured["prompt"].split("以下是课程数据：\n", 1)[1])
        self.assertEqual(prompt_payload["course"]["latest_import_file"], "selected.xlsx")
        self.assertEqual(prompt_payload["objective_details"][0]["qualitative_attainment"], 0.9)

    def test_rule_fallback_does_not_claim_unreached_objective_is_achieved(self):
        text = CourseInsightService._fallback_objective_analysis(
            {
                "objective_title": "课程目标1",
                "status": "未达成",
                "assessment_details": [
                    {"assessment_name": "期末考试", "score_rate": 0.4}
                ],
            }
        )

        self.assertIn("未达到课程期望值", text)
        self.assertNotIn("整体已达到课程期望值", text)

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

    def test_all_classes_report_uses_classes_from_selected_semester(self):
        course = self._create_course()
        course.class_names = "二班"
        db.session.add_all(
            [
                Student(
                    course_id=course.id,
                    student_no="S1",
                    name="第一学期学生",
                    class_name="一班",
                    semester="2025-2026学年第1学期",
                ),
                Student(
                    course_id=course.id,
                    student_no="S2",
                    name="第二学期学生",
                    class_name="二班",
                    semester="2025-2026学年第2学期",
                ),
            ]
        )
        db.session.commit()
        summary = AttainmentService.calculate(course, "2025-2026学年第1学期", "全部班级")
        AnalysisRunService.mark_complete(
            course.id,
            "2025-2026学年第1学期",
            "全部班级",
            summary["student_count"],
            summary=summary,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            report, context = ReportService.generate_word_report(
                course,
                "2025-2026学年第1学期",
                "全部班级",
                temp_dir,
            )

        self.assertEqual(context.get("report_class_label"), "一班")
        self.assertIn("一班", Path(report.word_path).name)
        self.assertNotIn("二班", Path(report.word_path).name)

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

    def test_corrupt_attachment_does_not_partially_replace_live_database(self):
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
                course = Course(code="ATOMIC001", name="备份状态", course_owner="教师")
                db.session.add(course)
                db.session.commit()
                valid_backup = DataBackupService.create_backup(app)
                with zipfile.ZipFile(valid_backup) as package:
                    manifest_bytes = package.read("manifest.json")
                    database_bytes = package.read(DataBackupService.DATABASE_MEMBER)

                course = Course.query.filter_by(code="ATOMIC001").first()
                course.name = "当前状态"
                db.session.commit()

                payload = b"CORRUPT-UPLOAD-PAYLOAD"
                corrupt_backup = data_dir / "corrupt-attachment.zip"
                with zipfile.ZipFile(corrupt_backup, "w", compression=zipfile.ZIP_STORED) as package:
                    package.writestr("manifest.json", manifest_bytes)
                    package.writestr(DataBackupService.DATABASE_MEMBER, database_bytes)
                    package.writestr("uploads/evidence.bin", payload)
                archive_bytes = bytearray(corrupt_backup.read_bytes())
                payload_offset = archive_bytes.find(payload)
                self.assertGreaterEqual(payload_offset, 0)
                archive_bytes[payload_offset] ^= 0x01
                corrupt_backup.write_bytes(archive_bytes)

                with self.assertRaises(zipfile.BadZipFile):
                    DataBackupService.restore_backup(app, corrupt_backup)

                db.session.remove()
                db.engine.dispose()
                current = Course.query.filter_by(code="ATOMIC001").first()
                self.assertEqual(current.name, "当前状态")

    def test_restore_replaces_managed_folders_instead_of_merging_stale_files(self):
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
                upload_dir = Path(app.config["UPLOAD_FOLDER"])
                report_dir = Path(app.config["REPORT_FOLDER"])
                upload_dir.mkdir(parents=True, exist_ok=True)
                report_dir.mkdir(parents=True, exist_ok=True)
                (upload_dir / "kept.txt").write_text("backup upload", encoding="utf-8")
                (report_dir / "kept.txt").write_text("backup report", encoding="utf-8")
                backup_path = DataBackupService.create_backup(app)

                (upload_dir / "kept.txt").write_text("current upload", encoding="utf-8")
                (report_dir / "kept.txt").write_text("current report", encoding="utf-8")
                (upload_dir / "stale.txt").write_text("stale", encoding="utf-8")
                (report_dir / "stale.txt").write_text("stale", encoding="utf-8")

                DataBackupService.restore_backup(app, backup_path)

                self.assertEqual((upload_dir / "kept.txt").read_text(encoding="utf-8"), "backup upload")
                self.assertEqual((report_dir / "kept.txt").read_text(encoding="utf-8"), "backup report")
                self.assertFalse((upload_dir / "stale.txt").exists())
                self.assertFalse((report_dir / "stale.txt").exists())

    def test_restore_preparation_failure_removes_hidden_candidates(self):
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
                db.session.add(Course(code="PREP001", name="当前状态", course_owner="教师"))
                db.session.commit()
                backup_path = DataBackupService.create_backup(app)
                original_copytree = shutil.copytree
                copy_count = 0

                def fail_second_copytree(source, target):
                    nonlocal copy_count
                    copy_count += 1
                    if copy_count == 2:
                        raise OSError("simulated preparation failure")
                    return original_copytree(source, target)

                with patch("services.data_backup_service.shutil.copytree", side_effect=fail_second_copytree):
                    with self.assertRaises(OSError):
                        DataBackupService.restore_backup(app, backup_path)

                self.assertEqual(list(data_dir.rglob(".*_restore_*")), [])
                db.session.remove()
                self.assertIsNotNone(Course.query.filter_by(code="PREP001").first())


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
