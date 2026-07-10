import inspect
import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docx import Document
from werkzeug.security import generate_password_hash

from app import create_app
from config import ProductionConfig, TestingConfig
from models import Course, Report, User, db
from services.llm_service import LLMService


class LoginEnabledConfig(TestingConfig):
    LOGIN_DISABLED = False
    DEFAULT_ADMIN_USERNAME = "admin"
    DEFAULT_ADMIN_PASSWORD = "admin-password"
    DEFAULT_ADMIN_DISPLAY_NAME = "系统管理员"


class CsrfEnabledConfig(TestingConfig):
    WTF_CSRF_ENABLED = True
    SECRET_KEY = "csrf-test-secret"


class SecurityDefaultsTest(unittest.TestCase):
    def test_default_application_factory_uses_production_config(self):
        default_config = inspect.signature(create_app).parameters["config_object"].default

        self.assertIs(default_config, ProductionConfig)

    def test_missing_secret_key_is_generated_once_in_runtime_data_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "runtime"

            class GeneratedSecretConfig(TestingConfig):
                DATA_DIR = str(data_dir)
                SECRET_KEY = ""
                SQLALCHEMY_DATABASE_URI = f"sqlite:///{data_dir / 'instance' / 'attainment_system.db'}"
                SAMPLE_DATA_FOLDER = str(Path(temp_dir) / "sample_data")

            first_app = create_app(GeneratedSecretConfig)
            second_app = create_app(GeneratedSecretConfig)
            secret_path = data_dir / "instance" / ".secret_key"

            self.assertTrue(secret_path.exists())
            self.assertGreaterEqual(len(first_app.config["SECRET_KEY"]), 40)
            self.assertEqual(first_app.config["SECRET_KEY"], second_app.config["SECRET_KEY"])
            self.assertEqual(secret_path.read_text(encoding="utf-8").strip(), first_app.config["SECRET_KEY"])

    def test_report_generation_endpoints_only_accept_post(self):
        app = create_app(TestingConfig)
        methods_by_endpoint = {rule.endpoint: rule.methods for rule in app.url_map.iter_rules()}

        for endpoint in ("report.export_word", "report.export_archive_package"):
            with self.subTest(endpoint=endpoint):
                self.assertIn("POST", methods_by_endpoint[endpoint])
                self.assertNotIn("GET", methods_by_endpoint[endpoint])

    def test_llm_api_base_rejects_non_http_protocols(self):
        class InvalidLlmConfig(TestingConfig):
            LLM_API_BASE = "file:///tmp/not-an-api"

        app = create_app(InvalidLlmConfig)
        with app.app_context(), self.assertRaises(ValueError):
            LLMService._validated_api_base()


class CsrfProtectionTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(CsrfEnabledConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_course(self, code):
        course = Course(code=code, name=f"课程{code}", course_owner="教师", expected_value=0.65)
        db.session.add(course)
        db.session.commit()
        return course

    def test_raw_post_route_rejects_request_without_csrf_token(self):
        course = self._create_course("CSRF001")

        response = self.client.post(f"/courses/{course.id}/delete")

        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(db.session.get(Course, course.id))

    def test_course_delete_form_supplies_valid_csrf_token(self):
        course = self._create_course("CSRF002")
        page = self.client.get("/courses/")
        token_match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', page.data)

        self.assertIsNotNone(token_match)
        response = self.client.post(
            f"/courses/{course.id}/delete",
            data={"csrf_token": token_match.group(1).decode("utf-8")},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.session.get(Course, course.id))


class TeacherDashboardPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(LoginEnabledConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.teacher_a = self._create_user("teacher_a", "教师A")
        self.teacher_b = self._create_user("teacher_b", "教师B")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_user(self, username, display_name):
        user = User(
            username=username,
            display_name=display_name,
            role="teacher",
            password_hash=generate_password_hash("teacher-password"),
        )
        db.session.add(user)
        db.session.commit()
        return user

    def _login_as(self, user):
        with self.client.session_transaction() as session:
            session["user_id"] = user.id

    def test_dashboard_only_shows_courses_and_reports_visible_to_teacher(self):
        private_course = Course(
            code="PRIVATE-A",
            name="教师A私有课程",
            owner_user_id=self.teacher_a.id,
            course_owner="教师A",
        )
        own_course = Course(
            code="OWN-B",
            name="教师B课程",
            owner_user_id=self.teacher_b.id,
            course_owner="教师B",
        )
        db.session.add_all([private_course, own_course])
        db.session.flush()
        db.session.add_all(
            [
                Report(course_id=private_course.id, semester="2025-2026-1", class_scope="全部班级"),
                Report(course_id=own_course.id, semester="2025-2026-1", class_scope="全部班级"),
            ]
        )
        db.session.commit()
        self._login_as(self.teacher_b)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("教师B课程".encode("utf-8"), response.data)
        self.assertNotIn("教师A私有课程".encode("utf-8"), response.data)

    def test_teacher_cannot_view_or_compare_orphan_reports(self):
        first = Report(
            course_id=9001,
            semester="2025-2026-1",
            class_scope="全部班级",
            word_path="/tmp/orphan-private-one.docx",
        )
        second = Report(
            course_id=9002,
            semester="2025-2026-1",
            class_scope="全部班级",
            word_path="/tmp/orphan-private-two.docx",
        )
        db.session.add_all([first, second])
        db.session.commit()
        self._login_as(self.teacher_b)

        index_response = self.client.get("/reports/")
        compare_response = self.client.get(f"/reports/compare?old_id={first.id}&new_id={second.id}")

        self.assertNotIn(b"orphan-private-one", index_response.data)
        self.assertEqual(compare_response.status_code, 403)


class PendingOutlineSessionTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.course = Course(code="OUTLINE001", name="大纲确认测试课程", course_owner="教师")
        db.session.add(self.course)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @staticmethod
    def _outline_upload():
        stream = BytesIO()
        document = Document()
        document.add_paragraph("脱敏教学大纲")
        document.save(stream)
        stream.seek(0)
        return stream

    def test_outline_preview_session_contains_only_safe_file_reference(self):
        parsed_payload = {
            "course_code": "OUTLINE001",
            "course_name": "大纲确认测试课程",
            "objectives": [{"title": "课程目标1", "description": "正式目标描述"}],
        }
        with patch(
            "routes.course_routes.OutlineTemplateAdapter.extract",
            return_value={"payload": parsed_payload, "raw_text": "脱敏文本", "summary": "脱敏摘要"},
        ):
            response = self.client.post(
                f"/courses/{self.course.id}/outline",
                data={"file": (self._outline_upload(), "outline.docx")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            pending = session["pending_outline_import"]
            self.assertEqual(pending["course_id"], self.course.id)
            self.assertIn("filename", pending)
            self.assertNotIn("file_path", pending)
            self.assertNotIn("parsed", pending)

    def test_confirming_outline_preview_calls_import_without_server_error(self):
        parsed_payload = {"course_code": "OUTLINE001", "course_name": "大纲确认测试课程"}
        with patch(
            "routes.course_routes.OutlineTemplateAdapter.extract",
            return_value={"payload": parsed_payload, "raw_text": "脱敏文本", "summary": "脱敏摘要"},
        ):
            self.client.post(
                f"/courses/{self.course.id}/outline",
                data={"file": (self._outline_upload(), "outline.docx")},
                content_type="multipart/form-data",
            )

        with patch(
            "routes.course_routes.ImportService.import_outline",
            return_value=(SimpleNamespace(filename="outline.docx"), {}),
        ) as import_mock:
            response = self.client.post(
                f"/courses/{self.course.id}/outline",
                data={"action": "confirm_pending"},
            )

        self.assertEqual(response.status_code, 302)
        import_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
