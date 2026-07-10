import json
import sqlite3
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from models import db


class DataBackupService:
    DATABASE_MEMBER = "database/attainment_system.db"
    MAX_ARCHIVE_MEMBERS = 5000
    MAX_MEMBER_BYTES = 256 * 1024 * 1024
    MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024

    @staticmethod
    def _timestamp():
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    @staticmethod
    def _backup_folder(app):
        folder = app.config.get("BACKUP_FOLDER") or str(Path(app.config["EXPORT_FOLDER"]) / "backups")
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _sqlite_database_path(app):
        url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
            raise ValueError("当前只支持本地 SQLite 数据库备份与恢复。")
        database_path = Path(url.database)
        if not database_path.is_absolute():
            database_path = Path(app.root_path) / database_path
        return database_path

    @staticmethod
    def _iter_existing_files(folder):
        path = Path(folder)
        if not path.exists() or not path.is_dir():
            return []
        return [item for item in path.rglob("*") if item.is_file()]

    @classmethod
    def _write_folder(cls, package, source_folder, prefix):
        source_path = Path(source_folder)
        for file_path in cls._iter_existing_files(source_path):
            package.write(file_path, f"{prefix}/{file_path.relative_to(source_path)}")

    @classmethod
    def create_backup(cls, app):
        database_path = cls._sqlite_database_path(app)
        if not database_path.exists():
            raise FileNotFoundError(f"数据库文件不存在：{database_path}")

        db.session.remove()
        backup_dir = cls._backup_folder(app)
        output_path = backup_dir / f"course_system_backup_{cls._timestamp()}.zip"
        manifest = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "database": database_path.name,
            "includes": ["database", "uploads", "reports"],
            "version": "1.0",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            database_snapshot = Path(temp_dir) / "attainment_system.db"
            with sqlite3.connect(database_path) as source, sqlite3.connect(database_snapshot) as target:
                source.backup(target)
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
                package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                package.write(database_snapshot, cls.DATABASE_MEMBER)
                cls._write_folder(package, app.config.get("UPLOAD_FOLDER", ""), "uploads")
                cls._write_folder(package, app.config.get("REPORT_FOLDER", ""), "reports")

        return output_path

    @classmethod
    def list_backups(cls, app):
        backup_dir = cls._backup_folder(app)
        backups = []
        for path in sorted(backup_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
            backups.append(
                {
                    "name": path.name,
                    "path": path,
                    "size": path.stat().st_size,
                    "created_at": datetime.fromtimestamp(path.stat().st_mtime),
                }
            )
        return backups

    @classmethod
    def restore_backup(cls, app, backup_path):
        backup_path = Path(backup_path)
        if not backup_path.exists():
            raise FileNotFoundError(f"备份文件不存在：{backup_path}")

        database_path = cls._sqlite_database_path(app)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        restore_guard_path = database_path.with_name(f"{database_path.stem}_before_restore_{cls._timestamp()}{database_path.suffix}")

        with zipfile.ZipFile(backup_path) as package:
            cls._validate_package(package)
            names = set(package.namelist())
            if cls.DATABASE_MEMBER not in names:
                raise ValueError("备份包缺少数据库文件，无法恢复。")
            if "manifest.json" not in names:
                raise ValueError("备份包缺少清单文件，无法确认来源和版本。")
            manifest = json.loads(package.read("manifest.json").decode("utf-8"))
            if str(manifest.get("version") or "") != "1.0":
                raise ValueError("备份包版本不兼容，请使用当前系统创建的备份包。")

            with tempfile.TemporaryDirectory() as temp_dir:
                extracted_db = Path(temp_dir) / "attainment_system.db"
                with package.open(cls.DATABASE_MEMBER) as source, extracted_db.open("wb") as target:
                    shutil.copyfileobj(source, target)
                cls._validate_sqlite_database(extracted_db)

                db.session.remove()
                db.engine.dispose()
                if database_path.exists():
                    shutil.copy2(database_path, restore_guard_path)
                shutil.copy2(extracted_db, database_path)

                cls._restore_folder_members(package, "uploads/", app.config.get("UPLOAD_FOLDER", ""))
                cls._restore_folder_members(package, "reports/", app.config.get("REPORT_FOLDER", ""))

        db.engine.dispose()
        db.session.remove()
        return {
            "backup_path": backup_path,
            "database_path": database_path,
            "pre_restore_copy": restore_guard_path if restore_guard_path.exists() else None,
            "manifest": manifest,
        }

    @classmethod
    def _validate_package(cls, package):
        members = package.infolist()
        if len(members) > cls.MAX_ARCHIVE_MEMBERS:
            raise ValueError("备份包文件数量过多，已拒绝恢复。")
        total_size = 0
        names = set()
        for member in members:
            if member.filename in names:
                raise ValueError("备份包包含重复文件名，已拒绝恢复。")
            names.add(member.filename)
            if member.file_size > cls.MAX_MEMBER_BYTES:
                raise ValueError(f"备份包中的文件过大：{member.filename}")
            total_size += member.file_size
        if total_size > cls.MAX_UNCOMPRESSED_BYTES:
            raise ValueError("备份包解压后体积过大，已拒绝恢复。")

    @staticmethod
    def _validate_sqlite_database(database_path):
        try:
            with sqlite3.connect(f"file:{Path(database_path)}?mode=ro", uri=True) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
        except sqlite3.DatabaseError as exc:
            raise ValueError("备份包中的数据库文件无效，未执行恢复。") from exc
        if not integrity or integrity[0] != "ok":
            raise ValueError("备份包中的数据库完整性检查未通过，未执行恢复。")
        if not {"courses", "users"}.issubset(tables):
            raise ValueError("备份包中的数据库缺少系统核心表，未执行恢复。")

    @staticmethod
    def _restore_folder_members(package, prefix, target_folder):
        if not target_folder:
            return
        target_path = Path(target_folder).resolve()
        target_path.mkdir(parents=True, exist_ok=True)
        for name in package.namelist():
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            relative = Path(name).relative_to(prefix.rstrip("/"))
            output_path = (target_path / relative).resolve()
            if target_path != output_path.parent and target_path not in output_path.parents:
                continue
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with package.open(name) as source, output_path.open("wb") as target:
                shutil.copyfileobj(source, target)
