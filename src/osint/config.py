import os
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql+psycopg://osint:osint@localhost:5432/osint"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; AvtOSINT/0.1)"


def database_url() -> str:
    return os.environ.get("OSINT_DATABASE_URL", DEFAULT_DATABASE_URL)


def data_dir() -> Path:
    return Path(os.environ.get("OSINT_DATA_DIR", "data"))


def user_agent() -> str:
    return os.environ.get("OSINT_USER_AGENT", DEFAULT_USER_AGENT)
