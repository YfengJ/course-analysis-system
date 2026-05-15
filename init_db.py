from pathlib import Path

from app import create_app
from models import db
from services.seed_service import seed_all


def main():
    """初始化数据库表结构。公开版不会写入任何真实课程或成绩数据。"""
    app = create_app()
    with app.app_context():
        db_path = Path(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        if db_path.exists():
            db_path.unlink()
        db.create_all()
        seed_all(Path(app.root_path))
        print("数据库初始化完成。")


if __name__ == "__main__":
    main()
