import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def load_local_env() -> None:
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


load_local_env()


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "graduation-design-demo-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'instance' / 'attainment_system.db'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = str(BASE_DIR / "uploads")
    EXPORT_FOLDER = str(BASE_DIR / "exports")
    REPORT_FOLDER = str(BASE_DIR / "exports" / "reports")
    REPORT_TEMPLATE_DOCX = os.getenv(
        "REPORT_TEMPLATE_DOCX",
        str(BASE_DIR / "sample_data" / "report_template.docx"),
    )
    SAMPLE_DATA_FOLDER = str(BASE_DIR / "sample_data")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"xls", "xlsx", "xlsm", "csv", "docx"}
    DEFAULT_EXPECTED_VALUE = 0.65
    DEFAULT_PAGE_SIZE = 20
    LLM_API_BASE = os.getenv("LLM_API_BASE", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
    LLM_VERIFY_SSL = os.getenv("LLM_VERIFY_SSL", "true").lower() not in {"0", "false", "no"}


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class ProductionConfig(BaseConfig):
    DEBUG = False
