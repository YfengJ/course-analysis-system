import argparse
import shutil
from datetime import datetime
from pathlib import Path

from app import create_app
from models import db
from services.seed_service import seed_all


def _sqlite_path(app):
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return None
    return Path(uri.replace("sqlite:///", ""))


def main():
    """初始化数据库表结构。默认不删除现有数据。"""
    parser = argparse.ArgumentParser(description="初始化课程达成度系统数据库")
    parser.add_argument("--reset-demo", action="store_true", help="备份并重置本地 SQLite，写入内置样例数据")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db_path = _sqlite_path(app)
        if args.reset_demo and db_path and db_path.exists():
            backup_path = db_path.with_name(f"{db_path.stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}.bak{db_path.suffix}")
            shutil.copy2(db_path, backup_path)
            db_path.unlink()
            print(f"已备份原数据库：{backup_path}")

        db.create_all()
        if args.reset_demo:
            seed_all(Path(app.root_path))
            print("数据库已重置，并写入内置样例数据。")
        else:
            print("数据库表结构初始化完成；未删除现有数据，也未写入样例课程。")


if __name__ == "__main__":
    main()
