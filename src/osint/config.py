import os
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql+psycopg://osint:osint@localhost:5432/osint"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; AvtOSINT/0.1)"
# The product token sites address in robots.txt (not the full User-Agent string).
DEFAULT_ROBOTS_TOKEN = "AvtOSINT"


def database_url() -> str:
    return os.environ.get("OSINT_DATABASE_URL", DEFAULT_DATABASE_URL)


def data_dir() -> Path:
    return Path(os.environ.get("OSINT_DATA_DIR", "data"))


def user_agent() -> str:
    return os.environ.get("OSINT_USER_AGENT", DEFAULT_USER_AGENT)


def browser_cdp_url() -> str | None:
    """Attach to an already-running Chromium (CDP) instead of launching one."""
    return os.environ.get("OSINT_BROWSER_CDP_URL") or None


def respect_robots() -> bool:
    """Whether robots.txt can stop us fetching a page.

    Off by default (project decision). Set OSINT_RESPECT_ROBOTS=1 to turn it on, or
    ``respect_robots`` in a source's config to decide for one site.
    """
    return os.environ.get("OSINT_RESPECT_ROBOTS", "0").lower() in ("1", "true", "yes")


def robots_token() -> str:
    return os.environ.get("OSINT_ROBOTS_TOKEN", DEFAULT_ROBOTS_TOKEN)


DEFAULT_MAX_ITEM_AGE_DAYS = 7


def max_item_age_days() -> float:
    """Reports published longer ago than this are not collected (a first poll of a feed would
    otherwise pull in years of back catalogue). Override per source with ``max_age_days``."""
    return float(os.environ.get("OSINT_MAX_ITEM_AGE_DAYS", DEFAULT_MAX_ITEM_AGE_DAYS))
