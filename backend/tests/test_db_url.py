"""The Postgres driver is named, not left to SQLAlchemy's default.

SQLAlchemy 2.1 switched bare postgresql:// from psycopg2 to psycopg 3; this app
installs psycopg2-binary, so a clean deploy crashed at import. The test builds a
real engine for each URL form, which imports the driver exactly as boot does."""
import importlib

import pytest
from sqlalchemy import create_engine

from src import db_sql


@pytest.mark.parametrize("given", [
    "postgres://u:p@host:5432/db",
    "postgresql://u:p@host:5432/db",
    "postgresql+psycopg2://u:p@host:5432/db",
])
def test_postgres_urls_use_the_installed_driver(monkeypatch, given):
    monkeypatch.setenv("DATABASE_URL", given)
    url = db_sql._database_url()
    assert url.startswith("postgresql+psycopg2://")
    create_engine(url)  # raises ModuleNotFoundError if the driver is not installed


def test_no_url_means_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db_sql._database_url().startswith("sqlite:///")
