import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app
from config import TestingConfig
from models import Course, CourseObjective, Report, User, db
from services.auth_service import AuthService
from services.report_quality_service import ReportQualityService
from services.seed_service import DEFAULT_SEMESTER


class RuntimeDataConfig(TestingConfig):
    DATA_DIR = ""


class LoginEnabledConfig(TestingConfig):
    LOGIN_DISABLED = False
    DEFAULT_ADMIN_USERNAME = "admin"
    DEFAULT_ADMIN_PASSWORD = "admin123"
    DEFAULT_ADMIN_DISPLAY_NAME = "系统管理员"


class TeacherHardeningTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(LoginEnabledConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.admin = AuthService.ensure_default_user()
        self.operator_admin = self._create_user("operator_admin", "管理员", role="admin")
        self.teacher_a = self._create_user("teacher_a", "教师A")
        self.teacher_b = self._create_user("teacher_b", "教师B")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_user(self, username, display_name, role="teacher"):
        user = User(
            username=username,
            display_name=display_name,
            role=role,
            password_hash=generate_password_hash("teacher-pass"),
        )
        db.session.add(user)
        db.session.commit()
        return user

    def _login_as(self, user):
        with self.client.session_transaction() as session:
            session["user_id"] = user.id
            session["user_display_name"] = user.display_name

    def _create_course(self, owner_user_id=None, course_owner="任课教师"):
        course = Course(
            code="SEC001",
            name="权限测试课程",
            semester=DEFAULT_SEMESTER,
            course_owner=course_owner,
            expected_value=0.65,
            owner_user_id=owner_user_id,
        )
        db.session.add(course)
        db.session.commit()
        return course

    def test_teacher_cannot_access_another_teachers_course_workflow(self):
        course = self._create_course(owner_user_id=self.teacher_a.id)
        self._login_as(self.teacher_b)

        for path in (
            f"/courses/{course.id}",
            f"/courses/{course.id}/imports/",
            f"/courses/{course.id}/analysis/",
            f"/courses/{course.id}/insights/",
            f"/courses/{course.id}/reports/preview",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 403)

    def test_only_admin_can_open_backup_maintenance_pages(self):
        self._login_as(self.teacher_a)

        response = self.client.get("/admin/backups")

        self.assertEqual(response.status_code, 403)

    def test_initial_password_must_be_changed_before_using_system(self):
        login_response = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)

        blocked_response = self.client.get("/courses/", follow_redirects=False)

        self.assertEqual(blocked_response.status_code, 302)
        self.assertIn("/account/password", blocked_response.location)

    def test_restore_requires_typed_confirmation_before_reading_zip(self):
        self._login_as(self.operator_admin)

        response = self.client.post(
            "/admin/backups/restore",
            data={"backup_file": (BytesIO(b"not a zip"), "backup.zip")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("请输入“确认恢复”".encode("utf-8"), response.data)

    def test_strict_report_quality_blocks_placeholder_objectives(self):
        course = self._create_course(owner_user_id=self.teacher_a.id)
        db.session.add(
            CourseObjective(
                course_id=course.id,
                sequence=1,
                title="课程目标1",
                description="请根据课程教学大纲完善课程目标 1 描述。",
                weight=100,
            )
        )
        db.session.commit()

        result = ReportQualityService.check_course_report(course, DEFAULT_SEMESTER, "全部班级", strict=True)

        self.assertFalse(result["ready"])
        self.assertTrue(
            any(item["level"] == "error" and item["category"] == "课程目标" for item in result["items"])
        )

    def test_report_archive_is_blocked_when_strict_quality_fails(self):
        course = self._create_course(owner_user_id=self.teacher_a.id)
        report = Report(course_id=course.id, semester=DEFAULT_SEMESTER, class_scope="全部班级")
        db.session.add(report)
        db.session.commit()
        self._login_as(self.operator_admin)

        response = self.client.post(
            f"/courses/{course.id}/reports/{report.id}/archive",
            follow_redirects=True,
        )

        db.session.refresh(report)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(report.is_archived)
        self.assertIn("质量检查".encode("utf-8"), response.data)


class RuntimeDataDirectoryTest(unittest.TestCase):
    def test_runtime_folders_can_be_moved_out_of_source_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "teacher-data"

            class DataDirConfig(RuntimeDataConfig):
                DATA_DIR = str(data_dir)
                SQLALCHEMY_DATABASE_URI = f"sqlite:///{data_dir / 'instance' / 'attainment_system.db'}"
                SAMPLE_DATA_FOLDER = str(Path(temp_dir) / "sample_data")

            app = create_app(DataDirConfig)

            for key in ("UPLOAD_FOLDER", "EXPORT_FOLDER", "REPORT_FOLDER", "BACKUP_FOLDER"):
                configured = Path(app.config[key]).resolve()
                self.assertTrue(
                    configured == data_dir.resolve() or data_dir.resolve() in configured.parents,
                    f"{key} should live under {data_dir}, got {configured}",
                )
                self.assertTrue(configured.exists())


if __name__ == "__main__":
    unittest.main()
