from sqlalchemy import inspect, text

from models import db


class SchemaMigrationService:
    """Small SQLite-friendly schema patcher for local deployments without Alembic."""

    IMPORT_BATCH_COLUMNS = {
        "import_version": "INTEGER DEFAULT 1",
        "file_hash": "VARCHAR(64)",
        "source_files_json": "TEXT",
        "pre_student_count": "INTEGER DEFAULT 0",
        "post_student_count": "INTEGER DEFAULT 0",
        "cleanup_count": "INTEGER DEFAULT 0",
        "status": "VARCHAR(32) DEFAULT '已完成'",
        "notes": "TEXT",
    }
    REPORT_COLUMNS = {
        "analysis_snapshot_id": "INTEGER",
        "report_version": "INTEGER DEFAULT 1",
        "comparison_base_report_id": "INTEGER",
        "source_import_ids_json": "TEXT",
        "change_note": "VARCHAR(255)",
        "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
        "archived_at": "DATETIME",
        "archive_note": "TEXT",
    }
    COURSE_COLUMNS = {
        "owner_user_id": "INTEGER",
    }

    @classmethod
    def ensure_schema(cls):
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        if "import_batches" in existing_tables:
            cls._ensure_columns("import_batches", cls.IMPORT_BATCH_COLUMNS)
        if "reports" in existing_tables:
            cls._ensure_columns("reports", cls.REPORT_COLUMNS)
        if "courses" in existing_tables:
            cls._ensure_columns("courses", cls.COURSE_COLUMNS)
        db.session.commit()

    @staticmethod
    def _ensure_columns(table_name, columns):
        inspector = inspect(db.engine)
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, definition in columns.items():
            if column_name in existing_columns:
                continue
            db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
