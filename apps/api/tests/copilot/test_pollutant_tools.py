"""The other-pollutant tools: gas statistics with attested units, satellite column summaries, adjudicated findings."""

from datetime import date
from types import SimpleNamespace as NS

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.test import TestModel

from app.services import satellite_copilot as scp
from app.services.aqi import multi
from app.services.copilot import agent as agent_mod
from app.services.copilot import station_queries as q
from app.services.copilot import tools
from app.services.copilot.context import CopilotSession
from tests.copilot.test_station_queries import FakeDB, Result
from tests.satellite.test_series import FakeBucket, _store_with_history


# ── US-EPA sub-indices for the gases ──────────────────────────────────────────

def test_sub_indices_need_an_attested_unit_and_convert_mass_units_to_the_epa_scales():
    assert round(multi.to_epa_units("no2", 94.0, "µg/m³"), 1) == 50.0            # 94 µg/m³ ≈ 50 ppb at 25 °C
    assert round(multi.to_epa_units("so2", 262.0, "ug/m3"), 0) == 100.0
    assert round(multi.to_epa_units("o3", 100.0, "µg/m³"), 4) == 0.0509          # ppm for the 8-hour table
    assert round(multi.to_epa_units("co", 1.0, "mg/m³"), 3) == 0.873
    assert multi.to_epa_units("co", 420.0, None) is None and multi.to_epa_units("pm10", 50.0, "ppb") is None
    s = multi.sub_index("no2", 94.0, "µg/m³")
    assert s["aqi"] == 46 and s["category"] == "Good" and s["scale_unit"] == "ppb" and "1-hour" in s["basis"]
    assert multi.sub_index("pm10", 193.0, "µg/m³")["aqi"] == 120
    assert multi.sub_index("co", 0.99, "mg/m³")["aqi"] == 9
    assert "did not attest" in multi.sub_index("so2", 20.0, None)["note"]
    assert multi.sub_index("no2", 5000.0, "ppb")["aqi"] is None and "above the top" in multi.sub_index("no2", 5000.0, "ppb")["note"]
    assert multi.sub_index("pm25", 10.0, "µg/m³")["aqi"] is None
    assert multi.sub_index("no2", None, "ppb")["note"] == "no value"


def test_the_punjab_router_still_uses_the_same_tables():
    from app.routers import punjab_epa
    assert punjab_epa.PM10_BPTS is multi.PM10_BPTS and punjab_epa._interp_aqi is multi.interp_aqi
    overall, main, sub = punjab_epa.compute_hourly_usaqi_iqair(50.0, 120.0, 60.0, 40.0, 5.0, 60.0)
    assert (overall, main) == (137, "PM2.5") and sub["NO2"] == 57 and sub["CO"] == 56


# ── period_stats for a gas ────────────────────────────────────────────────────

class GasDB(FakeDB):
    def __init__(self, units_rows, **kw):
        super().__init__(**kw)
        self.units_rows = units_rows

    async def close(self):
        pass

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "FROM units ORDER BY n_rows DESC" in sql:
            self.calls.append((sql, dict(params or {})))
            return Result(self.units_rows)
        return await super().execute(stmt, params)


async def test_period_stats_reads_the_gas_column_and_reports_the_providers_units():
    rows = [NS(b=date(2026, 11, 1), mean=94.0, median=90.0, max=140.0, min=40.0, n_station_days=12, n_sk=12, n_st_max=1, n_days=1)]
    db = GasDB([NS(source="punjab", unit="µg/m³", n_rows=250), NS(source="airvisual", unit=None, n_rows=900)], period_rows=rows)
    out = await q.period_stats(db, entity="city", name="Lahore", start="2026-11-01", end="2026-11-01", pollutant="NO2")
    sql, params = db.sql("FROM daily")
    assert "AVG(r.no2)" in sql and "r.no2 IS NOT NULL" in sql and "r.pm25" not in sql
    assert out["pollutant"] == "no2" and out["unit"] == "µg/m³ NO2 (as attested by the providers)"
    assert out["units_by_source"] == [{"source": "punjab", "unit": "µg/m³", "n_rows": 250}, {"source": "airvisual", "unit": None, "n_rows": 900}]
    usql, _ = db.sql("FROM units ORDER BY n_rows DESC")
    assert "r.units_no2 AS unit" in usql and "members AS" in usql and "r.no2 IS NOT NULL" in usql
    assert out["rows"][0]["mean"] == 94.0
    # a long range stays on the raw readings for a gas (the hourly city aggregate carries PM2.5 only)
    db2 = GasDB([NS(source="punjab", unit="µg/m³", n_rows=1)], period_rows=rows)
    await q.period_stats(db2, entity="city", name="Lahore", start="2026-01", end="2026-10", bucket="month", pollutant="so2")
    sql2, _ = db2.sql("FROM daily")
    assert "city_hourly_from_stations" not in sql2 and "AVG(r.so2)" in sql2
    assert "pollutant must be" in (await q.period_stats(FakeDB(), entity="city", name="Lahore", pollutant="nox"))["message"]
    # PM2.5 is untouched: no units query, the same unit line
    db3 = FakeDB(period_rows=rows)
    out3 = await q.period_stats(db3, entity="city", name="Lahore", start="2026-11-01", end="2026-11-01")
    assert out3["unit"] == "µg/m³ PM2.5" and "units_by_source" not in out3 and not any("FROM units" in s for s, _ in db3.calls)
    empty = await q.period_stats(GasDB([], period_rows=[]), entity="national", start="2026-10-01", end="2026-10-02", pollutant="co")
    assert "valid CO hours" in empty["message"] and empty["unit"].endswith("(unit not attested)")


# ── the tools ─────────────────────────────────────────────────────────────────

def _ctx(**kw):
    return NS(deps=CopilotSession(session_id="abcdefgh", current_date="2026-11-07", **kw))


async def test_aq_pollutant_stats_adds_sub_indices_only_from_one_attested_unit(monkeypatch):
    rows = [NS(b=date(2026, 11, 1), mean=94.0, median=90.0, max=140.0, min=40.0, n_station_days=12, n_sk=12, n_st_max=1, n_days=1)]
    dbs = iter([GasDB([NS(source="punjab", unit="µg/m³", n_rows=250)], period_rows=rows),
                GasDB([NS(source="punjab", unit="µg/m³", n_rows=250), NS(source="airvisual", unit=None, n_rows=900)], period_rows=rows)])

    async def fake_db():
        return next(dbs)
    monkeypatch.setattr(tools, "_get_db", fake_db)
    ctx = _ctx()
    out = await tools.aq_pollutant_stats(ctx, pollutant="no2", entity="city", name="Lahore", start_date="2026-11-01", end_date="2026-11-01")
    assert out["data"]["rows"][0]["sub_index"]["aqi"] == 46 and "attested unit µg/m³" in out["data"]["sub_index_basis"]
    assert ctx.deps.last_tool == "aq_pollutant_stats" and ctx.deps.focused_city == "Lahore"
    assert any("punjab: 250 hourly rows, unit µg/m³" in s for s in out["basis"]["sources"])
    out2 = await tools.aq_pollutant_stats(ctx, pollutant="no2", entity="city", name="Lahore", start_date="2026-11-01", end_date="2026-11-01")
    assert out2["data"]["rows"][0]["sub_index"]["aqi"] is None and "no sub-index" in out2["data"]["sub_index_basis"]
    refused = await tools.aq_pollutant_stats(_ctx(), pollutant="pm25")
    assert "aq_period_stats" in refused["data"]["message"]
    refused2 = await tools.aq_pollutant_stats(_ctx(pollutant="pm25"))
    assert "aq_period_stats" in refused2["data"]["message"]


def test_product_and_date_parsing():
    assert scp.parse_products("NO2, ozone and AOD") == ["no2", "o3", "aod550"]
    assert scp.parse_products("") == scp.DEFAULT_PRODUCTS and scp.parse_products("all") == list(scp.PRODUCTS)
    assert scp.parse_products("banana") == scp.DEFAULT_PRODUCTS
    assert scp.parse_day("2025-11") == date(2025, 11, 1) and scp.parse_day("2025-11", end=True) == date(2025, 11, 30)
    assert scp.parse_day("2024", end=True) == date(2024, 12, 31) and scp.parse_day("") is None
    with pytest.raises(ValueError):
        scp.parse_day("November 2025")


def test_columns_summary_reports_anomalies_coverage_and_comparisons():
    store = _store_with_history(FakeBucket())
    out = scp.columns_summary(store, place="Lahore", start=date(2025, 3, 1), end=date(2025, 3, 14), products=["no2", "aod550"],
                              compare_place="Karachi", compare_years=1, today=date(2026, 11, 7))
    assert out["region"]["id"] == "city:lahore:r25" and out["window"]["days"] == 14
    no2 = out["products"]["no2"]
    assert no2["assessable"] and no2["days_assessable"] == 14 and 115 < no2["percent_of_normal"] < 125 and no2["z_mean"] > 0
    assert no2["same_window_earlier_years"][0]["start"] == "2024-03-01" and 1.15 < no2["same_window_earlier_years"][0]["ratio"] < 1.25
    assert no2["compare"]["region"]["id"] == "city:karachi:r25" and no2["compare"]["ratio"] is None     # no Karachi rows in the fixture
    aod = out["products"]["aod550"]
    assert not aod["assessable"] and "no data" in aod["note"]
    assert "column" in out["definitions"] and out["archive"]["last_day"] == "2025-12-31"
    cloudy = scp.columns_summary(store, place="Lahore", start=date(2025, 12, 25), end=date(2025, 12, 31), products=["no2"])
    assert "coverage below 0.3" in cloudy["products"]["no2"]["note"]
    assert "no satellite region" in scp.columns_summary(store, place="Atlantis", start=None, end=None, products=["no2"])["message"]
    # defaults: the last 14 archive days when no dates are given
    dflt = scp.columns_summary(store, place="", start=None, end=None, products=["no2"])
    assert dflt["region"]["id"] == "pk_domain" and dflt["window"] == {"start": "2025-12-18", "end": "2025-12-31", "days": 14}


FINDINGS = [
    {"claim_type": "column_enhancement", "question": "Was the gas column above its seasonal normal?", "verdict": "not_supported",
     "statement": "no2_trop anomaly z = -0.74 over the window (coverage 0.75).", "region": "lahore",
     "window": ["2022-10-07T07:00:00+00:00", "2022-10-07T18:00:00+00:00"], "quantities": [{"name": "col_z", "value": -0.74, "units": "z", "coverage": 0.75}],
     "coverage": 0.75, "threshold_sensitive": False, "record_id": "c20221007T07"},
    {"claim_type": "smoke_transport_consistent", "question": "Is smoke transport consistent?", "verdict": "unresolved",
     "statement": "", "region": "lahore", "window": ["2022-11-05T00:00:00+00:00", "2022-11-08T00:00:00+00:00"], "threshold_sensitive": True},
    {"claim_type": "condition_contrast", "question": "Does a difference between places or years remain under matched weather and sampling?",
     "verdict": "supported", "statement": "lahore-vs-karachi-aod550: under matched meteorology the ratio is 1.65 (95 % interval 1.3 to 1.94).",
     "region": "lahore-vs-karachi-aod550", "window": ["2020-01-01", "2025-12-31"]},
    {"claim_type": "condition_contrast", "question": "Does a difference remain?", "verdict": "not_assessable",
     "statement": "peshawar-vs-quetta-no2: too few matched days.", "region": "peshawar-vs-quetta-no2", "window": ["2020-01-01", "2025-12-31"]},
]


def test_findings_are_filtered_by_place_period_and_claim_and_ordered_episodes_first():
    out = scp.findings_for(FINDINGS, place="Lahore")
    assert out["n_findings"] == 3 and [f["claim_type"] for f in out["settled"]] == ["column_enhancement", "condition_contrast"]
    assert out["open"][0]["claim_type"] == "smoke_transport_consistent" and out["open"][0]["flags"] == ["depends on the chosen thresholds"]
    assert out["settled"][0]["quantities"][0]["name"] == "col_z"
    nov = scp.findings_for(FINDINGS, place="Lahore", start=date(2022, 11, 1), end=date(2022, 11, 30))
    assert [f["claim_type"] for f in nov["open"]] == ["smoke_transport_consistent"] and nov["n_settled"] == 1   # the multi-year contrast overlaps
    assert scp.findings_for(FINDINGS, place="Karachi")["n_findings"] == 1
    assert scp.findings_for(FINDINGS, place="Islamabad")["n_findings"] == 0
    assert scp.findings_for(FINDINGS, claim_types="contrast")["n_findings"] == 2
    assert scp.findings_for(FINDINGS, place="Quetta", claim_types="contrast")["open"][0]["verdict"] == "not_assessable"
    assert "not how much any source contributed" in out["wording"]["rule"]


async def test_satellite_tools_read_the_store_and_degrade_without_data(monkeypatch):
    import app.services.satellite_series as sat
    store = _store_with_history(FakeBucket())
    monkeypatch.setattr(sat, "_STORE", store)
    ctx = _ctx()
    out = await tools.aq_satellite_columns(ctx, place="Lahore", start_date="2025-03-01", end_date="2025-03-14", products="NO2")
    assert out["data"]["products"]["no2"]["percent_of_normal"] > 100 and ctx.deps.last_tool == "aq_satellite_columns"
    assert any("TROPOMI" in s for s in out["basis"]["sources"]) and out["basis"]["limitations"]
    bad = await tools.aq_satellite_columns(ctx, place="Lahore", start_date="March")
    assert "Dates must be" in bad["data"]["message"]
    nothing = await tools.aq_observational_findings(ctx, place="Lahore")
    assert "not available" in nothing["data"]["message"]
    store._adjudicated = (1e12, FINDINGS)
    found = await tools.aq_observational_findings(ctx, place="Lahore", start_date="2022-11", end_date="2022-11")
    assert found["data"]["n_findings"] == 2 and ctx.deps.last_tool == "aq_observational_findings"
    assert "not how much any source contributed" in found["basis"]["limitations"][0]


async def test_new_tools_have_defaulted_schemas_are_registered_and_survive_a_db_failure(monkeypatch):
    async def broken_db():
        raise RuntimeError("no database in tests")
    monkeypatch.setattr(tools, "_get_db", broken_db)
    agent = Agent(TestModel(), deps_type=CopilotSession)
    for fn in (tools.aq_pollutant_stats, tools.aq_satellite_columns, tools.aq_observational_findings):
        agent.tool(agent_mod._safe_tool(fn))
    schemas = {n: t.function_schema.json_schema for n, t in agent._function_toolset.tools.items()}
    assert set(schemas["aq_pollutant_stats"]["properties"]) == {"pollutant", "entity", "name", "start_date", "end_date", "bucket"}
    assert set(schemas["aq_satellite_columns"]["properties"]) == {"place", "start_date", "end_date", "products", "compare_place", "compare_years"}
    assert set(schemas["aq_observational_findings"]["properties"]) == {"place", "start_date", "end_date", "claim_types"}
    assert all(s.get("required", []) == [] for s in schemas.values())
    result = await agent.run("hello", deps=CopilotSession(session_id="abcdefgh", current_date="2026-11-07", pollutant="no2"))
    returns = {p.tool_name: p.content for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)}
    assert "lookup failed (RuntimeError)" in returns["aq_pollutant_stats"]["data"]["message"]
    p = agent_mod.SYSTEM_PROMPT
    assert "aq_pollutant_stats" in p and "aq_satellite_columns" in p and "aq_observational_findings" in p
    assert "## Other pollutants and satellite columns" in p and "never surface concentrations" in p and "dust, ash or smoke" in p
