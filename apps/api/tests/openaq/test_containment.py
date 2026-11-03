"""Shadow data (OpenAQ, ICIMOD) never leaks through exports; scheduler jobs start paused; the secret is ingest-only."""

import re

import pytest

from app.ingestion.export_membership import SHADOW_PROVIDER_CODES
from app.routers import exports, exports_publish

SHADOW = list(SHADOW_PROVIDER_CODES)


def test_shadow_provider_set_is_exactly_the_two_pilots():
    assert SHADOW == ["openaq", "icimod"]


@pytest.mark.parametrize("code", SHADOW)
def test_station_list_query_excludes_shadow_provider_unless_requested(code):
    q, _ = exports._build_station_list_query(None, None, [], [])
    assert f"<> '{code}'" in str(q)
    q2, _ = exports._build_station_list_query(None, None, [], [code])
    assert f"<> '{code}'" not in str(q2) and "provider_codes" in str(q2)   # expanding bindparam renders as __[POSTCOMPILE_provider_codes]
    other = [c for c in SHADOW if c != code]
    assert all(f"<> '{o}'" in str(q2) for o in other)                      # asking for one shadow provider keeps the others out


@pytest.mark.parametrize("code", SHADOW)
def test_all_stations_hourly_publish_excludes_shadow_provider_unless_requested(code):
    q, params = exports_publish._build_all_stations_hourly_query(["AVG(r.pm25) AS pm25"], None, None, [], [])
    s = str(q)
    assert f"COALESCE(p.code, '') <> '{code}'" in s and f"r.source <> '{code}'" in s
    q2, _ = exports_publish._build_all_stations_hourly_query(["AVG(r.pm25) AS pm25"], None, None, [], [code])
    assert f"<> '{code}'" not in str(q2)


@pytest.mark.parametrize("code", SHADOW)
def test_city_csv_excludes_shadow_rows(api_root, code):
    src = (api_root / "app/routers/exports.py").read_text()
    i = src.index("async def export_station_readings_by_city_csv")
    assert f"AND r.source <> '{code}'" in src[i:i + 4000]


def test_icimod_scheduler_job_is_hourly_and_oidc(repo_root):
    tf = (repo_root / "infra/scheduler.tf").read_text()
    block = tf[tf.index('name             = "icimod-ingest-hourly"'):]
    block = block[:block.index("retry_config")]
    assert "/api/v1/tasks/icimod/ingest" in block and "oidc_token" in block
    assert re.search(r'schedule\s+=\s+"50 \* \* \* \*"', block) and "paused" not in block


def test_cloudbuild_enables_icimod_on_ingest_only(repo_root):
    import yaml
    cb = yaml.safe_load((repo_root / "cloudbuild.yaml").read_text())
    deploys = {}
    for step in cb["steps"]:
        args = step.get("args", [])
        if "deploy" in args:
            deploys[args[args.index("deploy") + 1]] = " ".join(args)
    assert "ICIMOD_ENABLED=true" in deploys["hawanama-ingest"]
    assert all("ICIMOD_ENABLED" not in deploys[name] for name in deploys if name != "hawanama-ingest")


def test_scheduler_jobs_exist_and_start_paused(repo_root):
    tf = (repo_root / "infra/scheduler.tf").read_text()
    for name, uri in (("openaq-discover-daily", "/api/v1/tasks/openaq/discover"),
                      ("openaq-ingest-hourly", "/api/v1/tasks/openaq/ingest"),
                      ("openaq-reconcile-daily", "/api/v1/tasks/openaq/reconcile")):
        block = tf[tf.index(f'name        = "{name}"'):]
        block = block[:block.index("retry_config")]
        assert uri in block and re.search(r"paused\s+=\s+true", block), name
        assert "oidc_token" in block


def test_cloudbuild_mounts_openaq_secret_on_ingest_only(repo_root):
    import yaml
    cb = yaml.safe_load((repo_root / "cloudbuild.yaml").read_text())
    deploys = {}
    for step in cb["steps"]:
        args = step.get("args", [])
        if "deploy" in args:
            deploys[args[args.index("deploy") + 1]] = " ".join(args)
    assert set(deploys) == {"hawanama", "hawanama-ingest", "hawanama-bam", "hawanama-punjab-push"}
    assert "OPENAQ_API_KEY=OPENAQ_API_KEY:latest" in deploys["hawanama-ingest"] and "OPENAQ_ENABLED=false" in deploys["hawanama-ingest"]
    assert all("OPENAQ_API_KEY" not in deploys[name] for name in ("hawanama", "hawanama-bam", "hawanama-punjab-push"))
