"""Point the SQLAlchemy engine at a throwaway SQLite file BEFORE the app (and
thus db_sql) is imported, so tests never touch a real/dev database. pytest
imports conftest.py before any test module, so setting the env var here wins.
"""
import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(prefix="applylens-test-", suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ.setdefault("JWT_SECRET", "test-secret")


def pytest_sessionfinish(session, exitstatus):
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
