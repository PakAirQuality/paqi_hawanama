"""Manifest sync downloads only when the GCS generation changed; falls back to local."""

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.ingestion import manifests as m


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.generation = None
        self.etag = None

    def exists(self):
        return self.name in self.store

    def reload(self):
        gen, _ = self.store[self.name]
        self.generation, self.etag = gen, f"etag-{gen}"

    def download_to_filename(self, path):
        self.store.setdefault("_downloads", 0)
        self.store["_downloads"] += 1
        Path(path).write_text(self.store[self.name][1])

    def upload_from_filename(self, path, content_type=None):
        gen = max([g for g, _ in self.store.values() if isinstance(g, int)] + [0]) + 1
        self.store[self.name] = (gen, Path(path).read_text())
        self.generation = gen


class FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, name):
        return FakeBlob(self.store, name)


class FakeClient:
    def __init__(self, store):
        self.store = store

    def bucket(self, name):
        return FakeBucket(self.store)


@pytest.fixture
def gcs(monkeypatch):
    store = {"manifests/station_manifests/latest.parquet": (7, "v7-bytes")}
    monkeypatch.setattr(m, "_gcs_client", lambda: FakeClient(store))
    monkeypatch.setattr(settings, "MANIFEST_GCS_BUCKET", "test-bucket")
    return store


def test_downloads_when_no_local_copy(tmp_path, gcs):
    ref = m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    assert ref.source == "gcs" and ref.generation == "7" and ref.path.read_text() == "v7-bytes"
    assert json.loads((tmp_path / "latest.parquet.meta.json").read_text())["generation"] == "7"
    assert gcs["_downloads"] == 1


def test_skips_download_when_generation_unchanged(tmp_path, gcs):
    m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    ref = m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    assert ref.source == "local" and ref.generation == "7"
    assert gcs["_downloads"] == 1


def test_downloads_again_when_generation_changes(tmp_path, gcs):
    m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    gcs["manifests/station_manifests/latest.parquet"] = (8, "v8-bytes")
    ref = m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    assert ref.source == "gcs" and ref.generation == "8" and ref.path.read_text() == "v8-bytes"
    assert gcs["_downloads"] == 2


def test_local_fallback_without_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MANIFEST_GCS_BUCKET", None)
    assert m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests") is None
    (tmp_path / "latest.jsonl").write_text("{}\n")
    ref = m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    assert ref.source == "local" and ref.path.name == "latest.jsonl" and ref.generation is None


def test_gcs_error_falls_back_to_local(tmp_path, monkeypatch):
    class Broken:
        def bucket(self, name):
            raise RuntimeError("gcs down")
    monkeypatch.setattr(m, "_gcs_client", lambda: Broken())
    monkeypatch.setattr(settings, "MANIFEST_GCS_BUCKET", "b")
    (tmp_path / "latest.parquet").write_bytes(b"x")
    ref = m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    assert ref is not None and ref.source == "local"


def test_upload_writes_sidecar_so_writer_does_not_redownload(tmp_path, gcs):
    local = tmp_path / "latest.parquet"
    local.write_text("fresh")
    assert m.upload_manifest_to_gcs(local, "manifests/station_manifests") is True
    meta = json.loads((tmp_path / "latest.parquet.meta.json").read_text())
    assert meta["generation"] == "8"
    ref = m.sync_latest_from_gcs(tmp_path, "manifests/station_manifests")
    assert ref.source == "local" and "_downloads" not in gcs


def test_ensure_latest_is_gcs_first(tmp_path, gcs):
    (tmp_path / "latest.parquet").write_text("stale-local")
    p = m.ensure_latest_from_gcs(tmp_path, "parquet", "manifests/station_manifests")
    assert p.read_text() == "v7-bytes"
