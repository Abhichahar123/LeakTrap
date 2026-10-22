"""Database layer and migration tests that do not need a PostgreSQL server."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import backend.database as database
from backend.config import mask_database_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FAKE_URL = "postgresql+psycopg://someone:s3cret-pw@localhost:1/leaktrace"


def run_python(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )


def test_mask_database_url_hides_password() -> None:
    masked = mask_database_url(FAKE_URL)
    assert "s3cret-pw" not in masked
    assert "someone" in masked and "***" in masked
    assert mask_database_url(None) == "<not configured>"


def test_importing_app_and_models_does_not_create_engine() -> None:
    result = run_python(
        "import backend.main, backend.models\n"
        "from backend.database import get_engine\n"
        "assert get_engine.cache_info().currsize == 0\n",
        DATABASE_URL=FAKE_URL,
    )
    assert result.returncode == 0, result.stderr
    assert "s3cret-pw" not in result.stderr


def test_get_engine_fails_clearly_without_database_url() -> None:
    result = run_python(
        "from backend.database import get_engine, DatabaseNotConfiguredError\n"
        "try:\n"
        "    get_engine()\n"
        "except DatabaseNotConfiguredError as exc:\n"
        "    print(exc)\n",
        DATABASE_URL="",
    )
    assert result.returncode == 0, result.stderr
    assert "DATABASE_URL is not set" in result.stdout


@pytest.mark.parametrize("url", ["sqlite:///leaktrace.db", "postgresql://u:p@localhost/db"])
def test_non_psycopg_postgresql_urls_are_rejected(url: str) -> None:
    with pytest.raises(database.DatabaseNotConfiguredError):
        database.build_engine(url)


def test_build_engine_does_not_connect() -> None:
    engine = database.build_engine(FAKE_URL)
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


def test_check_database_connection_returns_false_when_unreachable(caplog) -> None:
    engine = database.build_engine(FAKE_URL)
    assert database.check_database_connection(engine) is False
    assert "s3cret-pw" not in caplog.text
    engine.dispose()


def test_get_db_closes_session(monkeypatch) -> None:
    class FakeSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    fake = FakeSession()
    monkeypatch.setattr(database, "get_session_factory", lambda: lambda: fake)

    dependency = database.get_db()
    assert next(dependency) is fake
    with pytest.raises(StopIteration):
        next(dependency)
    assert fake.closed


def test_get_db_can_be_overridden_in_tests() -> None:
    app = FastAPI()

    @app.get("/probe")
    def probe(db=Depends(database.get_db)) -> dict[str, str]:
        return {"session": db}

    app.dependency_overrides[database.get_db] = lambda: "test-session"
    assert TestClient(app).get("/probe").json() == {"session": "test-session"}


def test_alembic_offline_sql_creates_all_tables() -> None:
    """Render the migration as SQL without connecting to any database."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": FAKE_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    for name in (
        "users", "signups", "consent_receipts", "mail_log",
        "incidents", "complaint_drafts", "reports", "leak_edges",
    ):
        assert f"CREATE TABLE {name} (" in sql
    assert "JSONB" in sql
    assert "NULLS NOT DISTINCT" in sql
    assert "s3cret-pw" not in sql + result.stderr
