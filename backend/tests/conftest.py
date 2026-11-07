"""Test set-up.

Tests run against a real PostgreSQL database (with pgvector) and use the
mock language model, so they need no GPU and give the same result every
run. Celery runs tasks inline ("eager"), so an upload is fully processed
before the request returns.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORAGE = tempfile.mkdtemp(prefix="docintel-test-")
os.environ.update({
    "DOCINTEL_API_KEY": "test-key-0123456789",
    "DOCINTEL_DATABASE_URL": os.environ.get("TEST_DATABASE_URL",
                                            "postgresql+psycopg://docintel:docintel@localhost:5432/docintel_test"),
    "DOCINTEL_LLM_PROVIDER": "mock",
    "DOCINTEL_TASK_ALWAYS_EAGER": "true",
    "DOCINTEL_STORAGE_DIR": STORAGE,
    "DOCINTEL_RATE_LIMIT_UPLOAD": "1000/minute",
    "DOCINTEL_RATE_LIMIT_SEARCH": "1000/minute",
})
sys.path.insert(0, str(ROOT / "evaluation" / "dataset"))  # the invoice generator, for fixtures

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.pipeline import llm  # noqa: E402

API_KEY = os.environ["DOCINTEL_API_KEY"]
TABLES = "processing_events, processing_runs, corrections, validation_issues, line_items, invoices, " \
         "invoice_groups, pages, documents"


@pytest.fixture(scope="session", autouse=True)
def database():
    with engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DOCINTEL_DATABASE_URL"])
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean(database):
    with engine().begin() as c:
        c.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    llm.set_client(llm.MockClient())
    yield


@pytest.fixture
def db():
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        c.headers["X-API-Key"] = API_KEY
        yield c


@pytest.fixture(scope="session")
def files(tmp_path_factory):
    from tests.fixtures.make import build
    return build(tmp_path_factory.mktemp("files"))
