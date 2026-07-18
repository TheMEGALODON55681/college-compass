"""Single source of truth for how every module in this app connects to its
database. Before this module existed, api/eligibility.py, models/ranker.py,
models/cutoff_regressor.py, models/similarity.py, models/counsellor_retrieval.py,
models/regressor_dataset.py, and data_pipeline/build_dataset.py each read
DATABASE_URL and called create_engine independently - seven separate copies of
the same fallback logic, which is exactly what makes a database swap risky.
Every one of them now routes through get_database_url()/get_engine() here.

DATABASE_URL selects the backend: unset, or pointing at the shipped SQLite
file, uses SQLite; a postgres:// or postgresql:// URL uses Postgres. Nothing
else in the app needs to know which backend is active - the same SQLAlchemy
models and the same queries run against either.
"""

import os
from urllib.parse import urlsplit

from sqlalchemy import create_engine

DEFAULT_DATABASE_URL = "sqlite:///./college_compass.db"

_engine_cache = {}


def get_database_url():
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_backend_name(database_url=None):
    """"sqlite" or "postgres" - never the host, credentials, or full URL.
    Used by startup logging and GET /meta.
    """
    database_url = database_url or get_database_url()
    scheme = urlsplit(database_url).scheme.split("+")[0]
    if scheme == "sqlite":
        return "sqlite"
    if scheme in ("postgres", "postgresql"):
        return "postgres"
    return scheme


def get_engine(database_url=None):
    """Cached per URL: every call site used to open its own fresh engine.
    Harmless for SQLite, but wasteful for Postgres, where an engine owns a
    real connection pool - one engine per URL, reused, is the right thing
    for either backend.
    """
    database_url = database_url or get_database_url()
    if database_url not in _engine_cache:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        _engine_cache[database_url] = create_engine(database_url, connect_args=connect_args)
    return _engine_cache[database_url]


def redact_database_url(database_url=None):
    """Safe to print/log: backend, host, port, and database name, never a
    password. SQLite URLs carry no credentials, so they're returned as-is.
    """
    database_url = database_url or get_database_url()
    parts = urlsplit(database_url)
    if parts.scheme.startswith("sqlite"):
        return database_url
    host = parts.hostname or "?"
    port = f":{parts.port}" if parts.port else ""
    db_name = parts.path.lstrip("/") or "?"
    user = parts.username or "?"
    return f"{parts.scheme}://{user}:***@{host}{port}/{db_name}"
