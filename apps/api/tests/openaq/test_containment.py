"""Shadow OpenAQ data never leaks through exports; scheduler jobs start paused; the secret is ingest-only."""

import re

from app.routers import exports, exports_publish


def test_station_list_query_excludes_openaq_unless_requested():
    q, _ = exports._build_station_list_query(None, None, [], [])
    assert "<> 'openaq'" in str(q)
    q2, _ = exports._build_station_list_query(None, None, [], ["openaq"])
    assert "<> 'openaq'" not in str(q2) and "provider_codes" in str(q2)   # expanding bindparam renders as __[POSTCOMPILE_provider_codes]


def test_all_stations_hourly_publish_excludes_openaq_unless_requested():
    q, params = exports_publish._build_all_stations_hourly_query(["AVG(r.pm25) AS pm25"], None, None, [], [])
    s = str(q)
    assert "COALESCE(p.code, '') <> 'openaq'" in s and "r.source <> 'openaq'" in s
    q2, _ = exports_publish._build_all_stations_hourly_query(["AVG(r.pm25) AS pm25"], None, None, [], ["openaq"])
    assert "<> 'openaq'" not in str(q2)


def test_city_csv_excludes_openaq_rows(api_root):
    src = (api_root / "app/routers/exports.py").read_text()
    i = src.index("async def export_station_readings_by_city_csv")
    assert "AND r.source <> 'openaq'" in src[i:i + 4000]


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
    assert set(deploys) == {"hawanama", "hawanama-ingest", "hawanama-bam"}
    assert "OPENAQ_API_KEY=OPENAQ_API_KEY:latest" in deploys["hawanama-ingest"] and "OPENAQ_ENABLED=false" in deploys["hawanama-ingest"]
    assert "OPENAQ_API_KEY" not in deploys["hawanama"] and "OPENAQ_API_KEY" not in deploys["hawanama-bam"]
