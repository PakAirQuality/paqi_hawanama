"""A manifest that exists but cannot be parsed must fail the run, never fall back to the DB list."""

from pathlib import Path

import pytest

@pytest.mark.parametrize("module, cls", [
    ("app.ingestion.tasks.data_ingestion", "DataIngestionTask"),
    ("app.ingestion.tasks.city_ingest", "CityIngestionTask"),
])
def test_unreadable_parquet_sets_read_error(monkeypatch, tmp_path, module, cls):
    mod = __import__(module, fromlist=[cls])
    task = getattr(mod, cls).__new__(getattr(mod, cls))   # no __init__: avoid settings/clients
    task._manifest_read_error = None
    bad = tmp_path / "latest.parquet"
    bad.write_bytes(b"not a parquet file")
    monkeypatch.setattr(mod, "_HAVE_PANDAS", True, raising=False)
    rows = task._read_parquet(bad)
    assert rows == []
    assert task._manifest_read_error and "Parquet" in task._manifest_read_error


def test_run_source_has_manifest_unreadable_guard():
    import inspect
    from app.ingestion.tasks import data_ingestion, city_ingest
    for mod in (data_ingestion, city_ingest):
        src = inspect.getsource(mod)
        assert 'outcome.fail("manifest_unreadable"' in src
        # the guard must come before any DB fallback
        assert src.index('outcome.fail("manifest_unreadable"') < src.index('outcome.manifest_source = "db"')
