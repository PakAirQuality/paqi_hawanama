"""
Fixtures for ingestion tests.

These tests never touch the network or a production database. Settings must be
constructible before anything under `app` is imported, so dummy POSTGRES_* values
are set here (setdefault: a real .env loaded by the root conftest wins, and no
test here opens a connection with them).
"""

import os

for _k, _v in {
    "POSTGRES_SERVER": "localhost",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_DB": "test",
    "POSTGRES_PORT": "5432",
    "IQAIR_API_KEY": "sk-test-SECRET-9f2a",
}.items():
    os.environ.setdefault(_k, _v)

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

# conftest.py -> ingestion -> tests -> api -> apps -> repo root
API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_DUMP = REPO_ROOT / "db_schema" / "initial_schema.sql"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def api_root() -> Path:
    return API_ROOT


@pytest.fixture(scope="session")
def schema_dump() -> Path:
    """Path to the authoritative pg_dump; skips when absent (it is gitignored)."""
    if not SCHEMA_DUMP.exists():
        pytest.skip(f"authoritative schema dump not present: {SCHEMA_DUMP}")
    return SCHEMA_DUMP
