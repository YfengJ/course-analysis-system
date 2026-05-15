from pathlib import Path

from flask import Flask, redirect, url_for

from config import DevelopmentConfig
from models import db
from routes.analysis_routes import analysis_bp
from routes.course_routes import course_bp
from routes.dashboard_routes import dashboard_bp
from routes.guide_routes import guide_bp
from routes.import_routes import import_bp
from routes.insight_routes import insight_bp
from routes.report_center_routes import report_center_bp
from routes.report_routes import report_bp
from services.seed_service import seed_all


def ensure_folders(app: Flask) -> None:
    for key in ("UPLOAD_FOLDER", "EXPORT_FOLDER", "REPORT_FOLDER", "SAMPLE_DATA_FOLDER"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)


def create_app(config_object=DevelopmentConfig):
    app = Flask(__name__)
    app.config.from_object(config_object)

    ensure_folders(app)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(report_center_bp)
    app.register_blueprint(guide_bp)
    app.register_blueprint(course_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(insight_bp)
    app.register_blueprint(report_bp)

    @app.context_processor
    def inject_globals():
        return {
            "system_name": "课程目标达成度报告系统",
        }

    @app.route("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="favicon.svg"), code=302)

    @app.cli.command("init-db")
    def init_db_command():
        """通过 Flask CLI 初始化数据库与演示数据。"""
        with app.app_context():
            db.create_all()
            seed_all(Path(app.root_path))
            print("数据库初始化完成。")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
