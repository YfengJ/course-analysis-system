import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from models import db


class DataBackupService:
    DATABASE_MEMBER = "database/attainment_system.db"

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

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            package.write(database_path, cls.DATABASE_MEMBER)
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
            names = set(package.namelist())
            if cls.DATABASE_MEMBER not in names:
                raise ValueError("备份包缺少数据库文件，无法恢复。")
            if "manifest.json" not in names:
                raise ValueError("备份包缺少清单文件，无法确认来源和版本。")
            manifest = json.loads(package.read("manifest.json").decode("utf-8"))
            if str(manifest.get("version") or "") != "1.0":
                raise ValueError("备份包版本不兼容，请使用当前系统创建的备份包。")

            db.session.remove()
            db.engine.dispose()
            if database_path.exists():
                shutil.copy2(database_path, restore_guard_path)

            with tempfile.TemporaryDirectory() as temp_dir:
                extracted_db = Path(temp_dir) / "attainment_system.db"
                with package.open(cls.DATABASE_MEMBER) as source, extracted_db.open("wb") as target:
                    shutil.copyfileobj(source, target)
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
