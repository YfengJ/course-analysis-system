import argparse
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app import create_app
from config import ProductionConfig
from models import db
from services.seed_service import seed_all


def _sqlite_path(database_uri):
    url = make_url(database_uri)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        return None
    path = Path(url.database).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def _backup_and_remove_database(database_path: Path) -> Path | None:
    if not database_path.exists():
        return None
    backup_path = database_path.with_name(
        f"{database_path.stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}.bak{database_path.suffix}"
    )
    shutil.copy2(database_path, backup_path)
    database_path.unlink()
    return backup_path


def main():
    """初始化数据库表结构。默认不删除现有数据。"""
    parser = argparse.ArgumentParser(description="初始化课程达成度系统数据库")
    parser.add_argument("--reset-demo", action="store_true", help="备份并重置本地 SQLite，写入内置样例数据")
    args = parser.parse_args()

    if args.reset_demo:
        db_path = _sqlite_path(ProductionConfig.SQLALCHEMY_DATABASE_URI)
        if db_path:
            backup_path = _backup_and_remove_database(db_path)
            if backup_path:
                print(f"已备份原数据库：{backup_path}")

    app = create_app()
    with app.app_context():
        db.create_all()
        if args.reset_demo:
            seed_all(Path(app.root_path))
            print("数据库已重置，并写入内置样例数据。")
        else:
            print("数据库表结构初始化完成；未删除现有数据，也未写入样例课程。")


if __name__ == "__main__":
    main()
