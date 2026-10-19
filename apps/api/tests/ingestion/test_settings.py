"""Ingestion knobs come from one typed Settings object, not scattered os.getenv calls."""

from app.core.config import Settings, settings
from app.core.south_asia import DEFAULT_IQAIR_COUNTRIES, get_iqair_countries
from app.ingestion.tasks.data_ingestion import DataIngestionTask
from app.ingestion.tasks.city_ingest import CityIngestionTask
from app.ingestion.tasks.station_discovery import StationDiscoveryTask
from app.services.ingestion.iqair_service import IQAirClient


class _Fake:
    """Stands in for IQAirClient / DatabaseService so no network/DB is touched."""


def _settings(**overrides) -> Settings:
    base = dict(POSTGRES_SERVER="x", POSTGRES_USER="x", POSTGRES_PASSWORD="x", POSTGRES_DB="x", POSTGRES_PORT=5432)
    base.update(overrides)
    return Settings(**base)


def test_defaults_are_https_and_documented():
    s = _settings()
    assert s.IQAIR_BASE_URL.startswith("https://")
    assert s.OPENAQ_BASE_URL == "https://api.openaq.org/v3"
    assert s.OPENAQ_ENABLED is False
    assert s.OPS_TABLES_REQUIRED is True
    assert s.INGEST_LEASE_TTL_S < 3600


def test_rate_limit_reaches_task_and_client(monkeypatch, tmp_path):
    s = _settings(IQAIR_MAX_CALLS_PER_MIN=500, INGEST_CONCURRENCY=10, INGEST_OUT_DIR=str(tmp_path),
                  STATION_MANIFEST_DIR=str(tmp_path / "sm"), CITY_MANIFEST_DIR=str(tmp_path / "cm"),
                  ALLOW_DB_STATION_FALLBACK=True)
    t = DataIngestionTask(settings=s, iqair_client=_Fake(), db_service=_Fake())
    assert t._rate == 500 and t._concurrency == 10 and t._db_station_fallback is True
    c = CityIngestionTask(settings=s, iqair_client=_Fake(), db_service=_Fake())
    assert c._rate == 500 and c._concurrency == 10
    d = StationDiscoveryTask(settings=s, iqair_client=_Fake(), db_service=_Fake())
    assert d.manifest_root == tmp_path / "sm"

    # The client reads the same Settings object; previously the field was undeclared
    # and the client silently ran at 90/min while the task ran at 500/min.
    monkeypatch.setattr(settings, "IQAIR_MAX_CALLS_PER_MIN", 500)
    monkeypatch.setattr(settings, "IQAIR_API_KEY", "sk-test")
    client = IQAirClient()
    assert client.max_calls_per_min == 500
    assert client.base_url.startswith("https://api.airvisual.com")


def test_countries_parse_from_setting():
    assert get_iqair_countries("Pakistan, India ,,") == ["Pakistan", "India"]
    assert get_iqair_countries("") == list(DEFAULT_IQAIR_COUNTRIES)
    assert get_iqair_countries(None) == get_iqair_countries(settings.IQAIR_COUNTRIES)
