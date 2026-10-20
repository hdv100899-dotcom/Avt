import os

DEFAULT_DATABASE_URL = "postgresql+psycopg://osint:osint@localhost:5432/osint"


def database_url() -> str:
    return os.environ.get("OSINT_DATABASE_URL", DEFAULT_DATABASE_URL)
