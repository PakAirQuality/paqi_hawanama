"""The ingestion code path must be the canonical one, in the repo and in the image."""

import sys

from app.ingestion import provenance


def test_assert_canonical_passes_in_repo():
    provenance.assert_canonical()


def test_describe_points_at_canonical_package(api_root):
    d = provenance.describe()
    assert d["provenance"] == provenance.PROVENANCE
    for name in (
        "app.ingestion.tasks.data_ingestion",
        "app.ingestion.tasks.city_ingest",
        "app.ingestion.tasks.station_discovery",
        "app.ingestion.db",
        "app.ingestion.manifests",
    ):
        assert d[name].startswith(str(api_root / "app" / "ingestion")), (name, d[name])
    assert d["app.services.ingestion.iqair_service"].startswith(str(api_root / "app" / "services" / "ingestion"))


def test_no_legacy_alias_modules_after_importing_tasks():
    import app.ingestion.tasks  # noqa: F401
    import app.routers.tasks  # noqa: F401

    legacy = {"config", "config.settings", "services", "services.iqair_client", "services.database", "manifest_utils"}
    assert not (legacy & set(sys.modules)), legacy & set(sys.modules)


def test_legacy_paths_absent(api_root, repo_root):
    for rel in ("app/tasks", "app/worker_compat.py", "app/worker_services", "app/worker_config", "app/manifest_utils.py"):
        assert not (api_root / rel).exists(), rel
    for rel in ("apps/worker/tasks/data_ingestion.py", "apps/worker/services", "apps/worker/config", "apps/worker/manifest_utils.py"):
        assert not (repo_root / rel).exists(), rel


def test_dockerfile_has_no_worker_overlay_and_checks_provenance(api_root):
    text = (api_root / "Dockerfile").read_text()
    assert "COPY apps/worker/" not in text
    assert "assert_canonical" in text
    assert "HAWANAMA_GIT_SHA" in text
