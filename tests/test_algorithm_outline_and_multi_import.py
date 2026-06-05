import unittest
import os
from pathlib import Path

from app import create_app
from config import TestingConfig
from models import Course, CourseObjective, Student, db
from services.import_service import ImportService
from services.seed_service import DEFAULT_SEMESTER, create_generic_course_structure
from services.template_adapters.outline_template_adapter import OutlineTemplateAdapter
from services.template_adapters.score_template_adapter import ScoreTemplateAdapter


DATA_DIR = Path(os.getenv("COURSE_SYSTEM_REAL_FIXTURE_DIR", ""))
OUTLINE_PATH = DATA_DIR / os.getenv("COURSE_SYSTEM_REAL_OUTLINE_FILE", "outline.docx")
CLASS_A_SCORE = DATA_DIR / os.getenv("COURSE_SYSTEM_REAL_CLASS_A_FILE", "class_a.xlsm")
CLASS_B_SCORE = DATA_DIR / os.getenv("COURSE_SYSTEM_REAL_CLASS_B_FILE", "class_b.xlsm")


@unittest.skipUnless(OUTLINE_PATH.exists(), "算法设计与分析教学大纲文件不存在")
class AlgorithmOutlineParsingTest(unittest.TestCase):
    def test_spaced_course_objectives_are_extracted_from_outline(self):
        payload = OutlineTemplateAdapter.extract(OUTLINE_PATH)["payload"]

        self.assertGreaterEqual(len(payload["objectives"]), 3)
        self.assertTrue(all(item["title"].startswith("课程目标") for item in payload["objectives"]))
        self.assertTrue(all(item["description"] for item in payload["objectives"][:3]))
        self.assertTrue(payload["assessment_support"])
        self.assertTrue(payload["category"])
        self.assertTrue(payload["hours"])
        self.assertTrue(payload["credits"])

    @unittest.skipUnless(CLASS_A_SCORE.exists(), "真实成绩样例文件不存在")
    def test_score_workbook_metadata_reads_cover_fields(self):
        payload = ScoreTemplateAdapter.load_score_payload(CLASS_A_SCORE, ImportService.normalize_columns)

        self.assertTrue(payload["metadata"]["course_code"])
        self.assertTrue(payload["metadata"]["course_name"])
        self.assertTrue(payload["metadata"]["class_names"])
        self.assertTrue(payload["metadata"]["assessment_method"])
        self.assertGreater(float(payload["metadata"]["hours"]), 0)
        self.assertGreater(float(payload["metadata"]["credits"]), 0)
        self.assertGreater(float(payload["metadata"]["expected_value"]), 0)


@unittest.skipUnless(
    OUTLINE_PATH.exists() and CLASS_A_SCORE.exists() and CLASS_B_SCORE.exists(),
    "真实教学大纲和成绩样例文件不存在",
)
class AlgorithmImportIntegrationTest(unittest.TestCase):
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

    def _create_placeholder_course(self):
        course = Course(
            code="TEMP",
            name="占位课程",
            course_owner="待完善",
            semester=DEFAULT_SEMESTER,
            expected_value=0.65,
        )
        db.session.add(course)
        db.session.flush()
        create_generic_course_structure(course)
        db.session.commit()
        return course

    def test_outline_import_replaces_default_objectives_and_spaced_support_refs(self):
        course = self._create_placeholder_course()

        ImportService.import_outline(OUTLINE_PATH, course)

        objectives = CourseObjective.query.filter_by(course_id=course.id).order_by(CourseObjective.sequence.asc()).all()
        self.assertGreaterEqual(len(objectives), 3)
        self.assertTrue(all(item.title.startswith("课程目标") for item in objectives[:3]))
        self.assertTrue(all(item.description for item in objectives[:3]))
        self.assertTrue(any(item.weight > 0 for item in objectives))
        self.assertTrue(any(item.requirement_maps for item in objectives))

    def test_multiple_score_files_are_imported_without_clearing_previous_class(self):
        course = self._create_placeholder_course()
        ImportService.import_outline(OUTLINE_PATH, course)

        result = ImportService.import_score_files([CLASS_A_SCORE, CLASS_B_SCORE], course, DEFAULT_SEMESTER)

        self.assertTrue(result["success"], result["issues"])
        self.assertGreater(result["imported"], 0)
        self.assertEqual(Student.query.filter_by(course_id=course.id, semester=DEFAULT_SEMESTER).count(), result["imported"])
        classes = {
            item.class_name
            for item in Student.query.with_entities(Student.class_name)
            .filter_by(course_id=course.id, semester=DEFAULT_SEMESTER)
            .distinct()
        }
        self.assertEqual(len(classes), 2)
        self.assertTrue(course.class_names)
        self.assertGreater(float(course.hours), 0)
        self.assertGreater(float(course.credits), 0)
        self.assertTrue(course.assessment_method)


if __name__ == "__main__":
    unittest.main()
