from pathlib import Path

import click
from flask import Flask, abort, redirect, request, url_for
from sqlalchemy.engine import make_url

from config import DevelopmentConfig
from models import Course, db
from routes.admin_routes import admin_bp
from routes.analysis_routes import analysis_bp
from routes.auth_routes import auth_bp
from routes.course_routes import course_bp
from routes.dashboard_routes import dashboard_bp
from routes.guide_routes import guide_bp
from routes.import_routes import import_bp
from routes.insight_routes import insight_bp
from routes.report_center_routes import report_center_bp
from routes.report_routes import report_bp
from services.auth_service import AuthService
from services.schema_migration_service import SchemaMigrationService
from services.seed_service import seed_all


def _explicit_config_keys(config_object) -> set[str]:
    explicit = set()
    for cls in getattr(config_object, "__mro__", ()):
        if cls.__name__ == "BaseConfig":
            break
        explicit.update(cls.__dict__.keys())
    return explicit


def configure_runtime_paths(app: Flask, config_object) -> None:
    data_dir = Path(app.config.get("DATA_DIR") or app.root_path).expanduser()
    app.config["DATA_DIR"] = str(data_dir)
    explicit = _explicit_config_keys(config_object)
    defaults = {
        "UPLOAD_FOLDER": data_dir / "uploads",
        "EXPORT_FOLDER": data_dir / "exports",
        "REPORT_FOLDER": data_dir / "exports" / "reports",
        "BACKUP_FOLDER": data_dir / "exports" / "backups",
    }
    for key, path in defaults.items():
        if key not in explicit:
            app.config[key] = str(path)
    if "SQLALCHEMY_DATABASE_URI" not in explicit:
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{data_dir / 'instance' / 'attainment_system.db'}"


def ensure_folders(app: Flask) -> None:
    for key in ("UPLOAD_FOLDER", "EXPORT_FOLDER", "REPORT_FOLDER", "BACKUP_FOLDER", "SAMPLE_DATA_FOLDER"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)
    url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
    if url.drivername == "sqlite" and url.database and url.database != ":memory:":
        database_path = Path(url.database)
        if not database_path.is_absolute():
            database_path = Path(app.root_path) / database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)


def create_app(config_object=DevelopmentConfig):
    app = Flask(__name__)
    app.config.from_object(config_object)
    configure_runtime_paths(app, config_object)

    ensure_folders(app)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        SchemaMigrationService.ensure_schema()
        AuthService.ensure_default_user()

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(report_center_bp)
    app.register_blueprint(guide_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(course_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(insight_bp)
    app.register_blueprint(report_bp)

    @app.before_request
    def require_login():
        if AuthService.login_disabled():
            return None
        allowed_endpoints = {"auth.login", "static", "favicon"}
        if request.endpoint in allowed_endpoints or (request.endpoint or "").startswith("static"):
            return None
        current_user = AuthService.current_user()
        if not current_user:
            return redirect(url_for("auth.login", next=request.full_path if request.query_string else request.path))
        if AuthService.uses_initial_password(current_user) and request.endpoint not in {"auth.change_password", "auth.logout"}:
            return redirect(url_for("auth.change_password", next=request.full_path if request.query_string else request.path))
        if (request.endpoint or "").startswith("admin.") and not AuthService.is_admin(current_user):
            abort(403)
        course_id = (request.view_args or {}).get("course_id")
        if course_id is not None:
            course = Course.query.get(course_id)
            if course and not AuthService.can_manage_course(course):
                abort(403)
        return None

    @app.context_processor
    def inject_globals():
        current_user = AuthService.current_user()
        return {
            "system_name": "课程目标达成度报告系统",
            "current_user": current_user,
            "login_disabled": AuthService.login_disabled(),
            "initial_password_active": AuthService.uses_initial_password(current_user),
        }

    @app.route("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="favicon.svg"), code=302)

    @app.cli.command("init-db")
    @click.option("--seed-demo", is_flag=True, help="写入内置样例课程数据")
    def init_db_command(seed_demo):
        """通过 Flask CLI 初始化数据库表结构。"""
        with app.app_context():
            db.create_all()
            if seed_demo:
                seed_all(Path(app.root_path))
                print("数据库初始化完成，已写入内置样例数据。")
            else:
                print("数据库表结构初始化完成；未写入样例课程。")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
