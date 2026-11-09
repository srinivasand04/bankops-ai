"""Test fixtures. Tests run against a dedicated PostgreSQL database (TEST_DATABASE_URL), migrated
with Alembic - the same schema path used in every environment."""

import os
from pathlib import Path

import pytest

from app.core.config import get_settings

_test_url = get_settings().test_database_url
if not _test_url:
    pytest.exit("TEST_DATABASE_URL is not set (see .env.example)", returncode=2)
if not _test_url.rsplit("/", 1)[-1].endswith("_test"):
    pytest.exit("Refusing to run: TEST_DATABASE_URL must point at a database whose name ends with '_test'", returncode=2)

# Point the application at the test database *before* the engine is created, and pin AI settings so
# results never depend on the developer's own .env (tests never call a real model).
os.environ["DATABASE_URL"] = _test_url
os.environ.update({
    "AI_PROVIDER": "anthropic",
    "ANTHROPIC_API_KEY": "",
    "AI_MODEL": "claude-opus-5-5",
    "AI_EFFORT": "high",
    "AI_FALLBACKS_ENABLED": "true",
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "OLLAMA_MODEL": "qwen3:8b",
    "OLLAMA_NUM_CTX": "8192",
    "OLLAMA_COMPACT": "true",
    "OLLAMA_KEEP_ALIVE": "30m",
    "OLLAMA_THINK": "false",
    "GROQ_API_KEY": "",
    "AI_DAILY_LIMIT": "0",
    "AI_AGENT_DAILY_LIMIT": "0",
    "ML_BUNDLE_AUTOLOAD": "false",
    "DEMO_LARGE_DATA": "false",
})
get_settings.cache_clear()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Application  # noqa: E402
from app.ingestion.loader import load_dataset, reset_all  # noqa: E402
from app.ingestion.reader import read_dataset  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
# Tests use a frozen copy so their exact numbers never change when the demo dataset grows.
SYNTHETIC_DATASET = BACKEND_DIR / "tests" / "data" / "core"
DEMO_DATASET = BACKEND_DIR / "datasets" / "synthetic"


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", _test_url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(migrated_database):
    with SessionLocal() as db:
        reset_all(db)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def applications(db) -> dict[str, Application]:
    """The five synthetic banking applications, without incidents."""
    records = read_dataset(SYNTHETIC_DATASET).applications
    apps = {r.code: Application(**r.model_dump(), data_source="SYNTHETIC") for r in records}
    db.add_all(apps.values())
    db.commit()
    return apps


@pytest.fixture
def seeded(db):
    """Full synthetic dataset loaded through the ingestion pipeline (10 incidents + evidence)."""
    return load_dataset(db, read_dataset(SYNTHETIC_DATASET))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def headers(role: str = "INCIDENT_MANAGER", user: str = "test.manager") -> dict[str, str]:
    return {"X-User-Name": user, "X-User-Role": role}


@pytest.fixture
def create_incident(client, applications):
    def _create(**overrides) -> dict:
        payload = {
            "title": "Payment API returning HTTP 500 errors",
            "description": "HTTP 500 error rate on /payments/authorise above 15% for 10 minutes.",
            "application_id": applications["PAY"].id,
            "severity": "P1",
            "category": "API_INTEGRATION",
            "business_impact": "Customer payments failing",
        } | overrides
        response = client.post("/api/incidents", json=payload, headers=headers())
        assert response.status_code == 201, response.text
        return response.json()

    return _create
