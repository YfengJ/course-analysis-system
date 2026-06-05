import inspect
import json
import unittest

from app import create_app
from config import TestingConfig
from models import (
    AnalysisSnapshot,
    Course,
    Report,
    Score,
    Student,
    db,
)
from services.analysis_revision_service import AnalysisRevisionService
from services.analysis_run_service import AnalysisRunService
from services.attainment_service import AttainmentService
from services.report_comparison_service import ReportComparisonService
from services.report_service import ReportService
from services.seed_service import DEFAULT_SEMESTER, create_generic_course_structure


class EvidenceChainFeatureTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_course_with_scores(self):
        course = Course(
            code="TEST001",
            name="证据链测试课程",
            semester=DEFAULT_SEMESTER,
            department="计算机科学与技术系",
            major="示例专业",
            course_owner="测试教师",
            instructors="测试教师",
            expected_value=0.65,
            class_names="测试班",
        )
        db.session.add(course)
        db.session.flush()
        create_generic_course_structure(course)
        db.session.flush()

        for index, rate in enumerate((0.92, 0.78, 0.58), start=1):
            student = Student(
                course_id=course.id,
                student_no=f"202600{index}",
                name=f"学生{index}",
                class_name="测试班",
                semester=DEFAULT_SEMESTER,
            )
            db.session.add(student)
            db.session.flush()
            for assessment in course.assessments:
                db.session.add(
                    Score(
                        student_id=student.id,
                        assessment_id=assessment.id,
                        score=round(assessment.total_score * rate, 2),
                        original_column=assessment.name,
                    )
                )

        course.student_count = 3
        db.session.commit()
        return course

    def test_analysis_runs_keep_versioned_snapshots(self):
        course = self._create_course_with_scores()
        summary = AttainmentService.calculate(course, DEFAULT_SEMESTER, "全部班级")

        AnalysisRunService.mark_complete(
            course.id,
            DEFAULT_SEMESTER,
            "全部班级",
            summary["student_count"],
            summary=summary,
            change_note="初次计算",
        )
        AnalysisRunService.mark_complete(
            course.id,
            DEFAULT_SEMESTER,
            "全部班级",
            summary["student_count"],
            summary=summary,
            change_note="重新计算",
        )

        snapshots = (
            AnalysisSnapshot.query.filter_by(course_id=course.id, semester=DEFAULT_SEMESTER, class_scope="全部班级")
            .order_by(AnalysisSnapshot.version_no.asc())
            .all()
        )
        self.assertEqual([item.version_no for item in snapshots], [1, 2])
        self.assertEqual(AnalysisRunService.latest_snapshot(course.id, DEFAULT_SEMESTER, "全部班级").version_no, 2)
        self.assertIn("objective_results", json.loads(snapshots[-1].summary_json))

    def test_manual_revision_is_applied_to_report_context(self):
        course = self._create_course_with_scores()
        summary = AttainmentService.calculate(course, DEFAULT_SEMESTER, "全部班级")
        objective_id = summary["objective_results"][0]["objective_id"]

        AnalysisRevisionService.save_revision(
            course.id,
            DEFAULT_SEMESTER,
            "全部班级",
            qualitative_overrides={
                str(objective_id): {
                    "excellent_count": 1,
                    "good_count": 1,
                    "medium_count": 1,
                    "poor_count": 0,
                }
            },
            analysis_note="教师确认课程目标1等级分布。",
            improvement_note="下一轮增加低分学生辅导。",
        )
        revised_summary, _ = AnalysisRevisionService.apply_active_revision(summary, course.id, DEFAULT_SEMESTER, "全部班级")
        AnalysisRunService.mark_complete(
            course.id,
            DEFAULT_SEMESTER,
            "全部班级",
            revised_summary["student_count"],
            summary=revised_summary,
            change_note="教师人工修订",
        )

        context = ReportService.build_report_context(course, DEFAULT_SEMESTER, "全部班级")
        first_row = context["summary"]["chapter_four"]["qualitative_rows"][0]
        self.assertEqual(first_row["excellent_count"], 1)
        self.assertEqual(first_row["poor_count"], 0)
        self.assertEqual(context["analysis_revision"]["analysis_note"], "教师确认课程目标1等级分布。")
        self.assertIn("下一轮增加低分学生辅导", context["analysis_revision"]["improvement_note"])

    def test_report_comparison_returns_core_deltas(self):
        course = self._create_course_with_scores()
        old_report = Report(
            course_id=course.id,
            semester=DEFAULT_SEMESTER,
            class_scope="全部班级",
            quantitative_attainment=0.75,
            qualitative_attainment=0.80,
            status="达成",
            html_snapshot=json.dumps(
                {
                    "total_quantitative_attainment": 0.75,
                    "total_qualitative_attainment": 0.80,
                    "objective_results": [
                        {"objective_title": "课程目标1", "quantitative_attainment": 0.70, "qualitative_attainment": 0.80}
                    ],
                },
                ensure_ascii=False,
            ),
        )
        new_report = Report(
            course_id=course.id,
            semester=DEFAULT_SEMESTER,
            class_scope="全部班级",
            quantitative_attainment=0.82,
            qualitative_attainment=0.84,
            status="达成",
            html_snapshot=json.dumps(
                {
                    "total_quantitative_attainment": 0.82,
                    "total_qualitative_attainment": 0.84,
                    "objective_results": [
                        {"objective_title": "课程目标1", "quantitative_attainment": 0.78, "qualitative_attainment": 0.85}
                    ],
                },
                ensure_ascii=False,
            ),
        )
        db.session.add_all([old_report, new_report])
        db.session.commit()

        comparison = ReportComparisonService.compare_reports(old_report, new_report)

        self.assertEqual(comparison["total_quantitative_delta"], 0.07)
        self.assertEqual(comparison["total_qualitative_delta"], 0.04)
        self.assertEqual(comparison["objective_deltas"][0]["objective_title"], "课程目标1")
        self.assertEqual(comparison["objective_deltas"][0]["quantitative_delta"], 0.08)

    def test_attainment_service_no_longer_reads_private_reference_report(self):
        source = inspect.getsource(AttainmentService)

        self.assertNotIn("REFERENCE_REPORT_PATH", source)
        self.assertNotIn("_load_reference_qualitative_rows", source)
        self.assertNotIn("_apply_reference_qualitative_rows", source)


if __name__ == "__main__":
    unittest.main()
