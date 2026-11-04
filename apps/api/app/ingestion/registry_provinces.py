"""
Registry province reconcile: stations.state_id / cities.state_id by one rule.

Why: a CSV import on 2025-11-24 registered 83 stations (provider "other") and 7 cities with
Punjab as their province regardless of where they are (Karachi, Islamabad, Peshawar, Haripur,
Skardu … ), and the Punjab EPA / BAM writers never set state_id at all. Every province-scoped
answer (meta, reports, analytics, copilot) read those links.

The rule lives in app.services.geo_utils (resolve_city_province / resolve_station_province):
city first, geography second, tolerant near borders. This module turns it into a reviewed,
idempotent task:

  plan(cities, stations)  -> Plan        pure: what would change and why, plus flags
  apply(db, plan, ...)    -> counts      one transaction; provenance stamped in metadata_json
  RegistryProvincesTask().run(dry_run=…) -> RunOutcome in ops.ingest_runs (details carry the plan)

Never touched: shadow rows (OpenAQ, ICIMOD: state_id/city_id NULL by design), rows outside
Pakistan, and a city whose old scope_key still has city-scope readings (the cities trigger
rewrites scope_key when state_id changes, which would detach them — flagged instead).

A duplicate city (same name already registered under the target province, e.g. Gilgit) is
merged: its stations move to the existing city and the orphan row is deactivated.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text

from app.ingestion.runs import RunOutcome, RunRecorder, new_run_id
from app.services.geo_utils import (BORDER_KM, haversine_km, pakistan_state_ids, province_for_point,
                                    resolve_city_province, resolve_station_province)

logger = logging.getLogger(__name__)

TASK = "registry-provinces"
SET_BY = "registry-provinces"
FAR_FROM_CITY_KM = 50.0


# ── inputs ────────────────────────────────────────────────────────────────────

@dataclass
class CityRow:
    id: int
    name: str
    state: Optional[str]              # states.name or None
    has_city_readings: bool = False   # readings with scope_type='city' under the current scope_key


@dataclass
class StationRow:
    station_id: str
    name: str
    provider: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    city_id: Optional[int]
    state: Optional[str]              # states.name or None
    shadow: bool = False


# ── outputs ───────────────────────────────────────────────────────────────────

@dataclass
class CityChange:
    city_id: int
    name: str
    from_state: Optional[str]
    to_state: str
    rule: str
    border_km: Optional[float] = None
    merge_into_city_id: Optional[int] = None   # set when a city with that name already exists under to_state
    stations: int = 0


@dataclass
class StationChange:
    station_id: str
    name: str
    provider: Optional[str]
    from_state: Optional[str]
    to_state: str
    rule: str
    geo_province: Optional[str]
    from_city_id: Optional[int] = None
    to_city_id: Optional[int] = None


@dataclass
class Flag:
    kind: str          # outside_polygons | far_from_city | geo_differs | city_has_readings | no_decision
    key: str           # station_id or city id
    name: str
    detail: str


@dataclass
class Plan:
    cities: List[CityChange] = field(default_factory=list)
    stations: List[StationChange] = field(default_factory=list)
    flags: List[Flag] = field(default_factory=list)
    examined_cities: int = 0
    examined_stations: int = 0

    def summary(self) -> Dict[str, Any]:
        by_kind: Dict[str, int] = {}
        for f in self.flags:
            by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        return {
            "examined": {"cities": self.examined_cities, "stations": self.examined_stations},
            "city_changes": len(self.cities),
            "city_merges": sum(1 for c in self.cities if c.merge_into_city_id is not None),
            "station_changes": len(self.stations),
            "station_fills": sum(1 for s in self.stations if s.from_state is None),
            "station_corrections": sum(1 for s in self.stations if s.from_state is not None),
            "by_provider": _count(s.provider or "?" for s in self.stations),
            "by_transition": _count(f"{s.from_state or 'NULL'} -> {s.to_state}" for s in self.stations),
            "flags": by_kind,
        }

    def to_details(self) -> Dict[str, Any]:
        return {"summary": self.summary(), "cities": [asdict(c) for c in self.cities],
                "stations": [asdict(s) for s in self.stations], "flags": [asdict(f) for f in self.flags]}


def _count(items: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for k in items:
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ── planner (pure) ────────────────────────────────────────────────────────────

def plan(cities: List[CityRow], stations: List[StationRow], *, border_km: float = BORDER_KM,
         far_km: float = FAR_FROM_CITY_KM) -> Plan:
    """What the rule would change. Running plan() on the rows it produced yields an empty plan."""
    out = Plan(examined_cities=len(cities), examined_stations=sum(1 for s in stations if not s.shadow))
    by_city: Dict[int, List[Tuple[float, float]]] = {}
    for s in stations:
        if not s.shadow and s.city_id is not None and s.lat is not None and s.lon is not None:
            by_city.setdefault(s.city_id, []).append((s.lat, s.lon))

    city_by_id = {c.id: c for c in cities}
    effective_state: Dict[int, Optional[str]] = {c.id: c.state for c in cities}
    redirect: Dict[int, int] = {}            # orphan city id -> surviving city id

    for c in cities:
        pts = by_city.get(c.id, [])
        d = resolve_city_province(stored_state=c.state, station_points=pts, border_km=border_km)
        if d.rule == "border_keep":
            out.flags.append(Flag("geo_differs", str(c.id), c.name,
                                  f"city median falls in {d.geo_province} {d.border_km} km from its border; kept {c.state}"))
            continue
        if d.rule != "geography" or d.province is None or d.province == c.state:
            continue
        if c.has_city_readings:
            out.flags.append(Flag("city_has_readings", str(c.id), c.name,
                                  f"would move {c.state} -> {d.province} but city-scope readings exist under the current scope_key"))
            continue
        twin = next((o for o in cities if o.id != c.id and o.name == c.name and o.state == d.province), None)
        out.cities.append(CityChange(c.id, c.name, c.state, d.province, d.rule, d.border_km,
                                     merge_into_city_id=twin.id if twin else None, stations=len(pts)))
        effective_state[c.id] = d.province
        if twin:
            redirect[c.id] = twin.id

    for s in stations:
        if s.shadow:
            continue
        city = city_by_id.get(s.city_id) if s.city_id is not None else None
        city_state = effective_state.get(s.city_id) if city else None
        d = resolve_station_province(lat=s.lat, lon=s.lon, city_state=city_state)
        if s.lat is not None and s.lon is not None and d.geo_province is None:
            out.flags.append(Flag("outside_polygons", s.station_id, s.name,
                                  f"{s.lat}, {s.lon} is outside every province polygon (coast or abroad); "
                                  f"province from its city: {city_state or 'none'}"))
        if city and s.lat is not None and s.lon is not None and by_city.get(s.city_id):
            pts = by_city[s.city_id]
            km = haversine_km(s.lat, s.lon, statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
            if km > far_km:
                out.flags.append(Flag("far_from_city", s.station_id, s.name,
                                      f"{km:.0f} km from the median of {city.name}'s stations; city link suspect"))
        if d.province is None:
            if s.state is None:
                out.flags.append(Flag("no_decision", s.station_id, s.name, "no city province and no polygon; state_id stays NULL"))
            continue
        if d.geo_province and d.geo_province != d.province and d.rule == "city":
            out.flags.append(Flag("geo_differs", s.station_id, s.name,
                                  f"coordinates fall in {d.geo_province}; province {d.province} from city {city.name}"))
        to_city = redirect.get(s.city_id) if s.city_id is not None else None
        if d.province != s.state or to_city is not None:
            out.stations.append(StationChange(s.station_id, s.name, s.provider, s.state, d.province, d.rule, d.geo_province,
                                              from_city_id=s.city_id if to_city is not None else None, to_city_id=to_city))
    return out


# ── database I/O ──────────────────────────────────────────────────────────────

CITIES_SQL = text("""
    SELECT c.id, c.name, st.name AS state,
           EXISTS (SELECT 1 FROM readings r WHERE r.scope_type = 'city' AND r.scope_key = c.scope_key) AS has_city_readings
    FROM cities c
    JOIN countries co ON co.id = c.country_id
    LEFT JOIN states st ON st.id = c.state_id
    WHERE co.name = 'Pakistan'
    ORDER BY c.id
""")

STATIONS_SQL = text("""
    SELECT s.station_id, s.name, p.code AS provider, s.lat, s.lon, s.city_id, st.name AS state,
           (COALESCE(s.metadata_json->>'ingest_mode', '') = 'shadow') AS shadow
    FROM stations s
    JOIN countries co ON co.id = s.country_id
    LEFT JOIN providers p ON p.id = s.provider_id
    LEFT JOIN states st ON st.id = s.state_id
    WHERE co.name = 'Pakistan'
    ORDER BY s.station_id
""")

UPDATE_CITY_SQL = text("UPDATE cities SET state_id = :sid, updated_at = NOW() WHERE id = :cid")
MOVE_STATIONS_SQL = text("UPDATE stations SET city_id = :to_cid, updated_at = NOW() WHERE city_id = :from_cid")
DEACTIVATE_CITY_SQL = text("UPDATE cities SET active = false, updated_at = NOW() WHERE id = :cid")
UPDATE_STATION_SQL = text("""
    UPDATE stations
       SET state_id = :sid,
           metadata_json = COALESCE(metadata_json, '{}'::jsonb)
               || jsonb_build_object('registry', COALESCE(metadata_json->'registry', '{}'::jsonb)
                                                 || jsonb_build_object('province', CAST(:stamp AS jsonb))),
           updated_at = NOW()
     WHERE station_id = :station_id
""")


async def load_rows(db) -> Tuple[List[CityRow], List[StationRow]]:
    cities = [CityRow(int(r.id), r.name, r.state, bool(r.has_city_readings)) for r in (await db.execute(CITIES_SQL)).fetchall()]
    stations = [StationRow(r.station_id.strip(), r.name, r.provider, r.lat, r.lon,
                           int(r.city_id) if r.city_id is not None else None, r.state, bool(r.shadow))
                for r in (await db.execute(STATIONS_SQL)).fetchall()]
    return cities, stations


async def apply(db, p: Plan, *, state_ids: Dict[str, int], run_id: str, since: Optional[str] = None) -> Dict[str, int]:
    """Write the plan on the given session (caller commits). Returns row counts per statement kind."""
    since = since or date.today().isoformat()
    counts = {"cities": 0, "merges": 0, "stations": 0}
    missing = sorted(({c.to_state for c in p.cities} | {s.to_state for s in p.stations}) - set(state_ids))
    if missing:
        raise RuntimeError(f"states rows missing for {missing}; nothing written")
    for c in p.cities:
        if c.merge_into_city_id is not None:
            await db.execute(MOVE_STATIONS_SQL, {"to_cid": c.merge_into_city_id, "from_cid": c.city_id})
            await db.execute(DEACTIVATE_CITY_SQL, {"cid": c.city_id})
            counts["merges"] += 1
        else:
            await db.execute(UPDATE_CITY_SQL, {"sid": state_ids[c.to_state], "cid": c.city_id})
            counts["cities"] += 1
    for s in p.stations:
        stamp = {"set_by": SET_BY, "run_id": run_id, "since": since, "rule": s.rule,
                 "previous_state": s.from_state, "geo_province": s.geo_province}
        await db.execute(UPDATE_STATION_SQL, {"sid": state_ids[s.to_state], "stamp": json.dumps(stamp),
                                              "station_id": s.station_id})
        counts["stations"] += 1
    return counts


# ── task ──────────────────────────────────────────────────────────────────────

class RegistryProvincesTask:
    """POST /tasks/registry/provinces?dry_run=… — plan (and apply) the province rule on the live registry."""

    def __init__(self, *, settings=None, session_factory=None, recorder: Optional[RunRecorder] = None):
        from app.core.config import settings as _default_settings
        from app.ingestion.db import AsyncSessionLocal
        self.settings = settings or _default_settings
        self.session_factory = session_factory or AsyncSessionLocal
        self.recorder = recorder or RunRecorder(self.session_factory, Path(self.settings.INGEST_OUT_DIR), required=False)

    async def run(self, *, dry_run: bool = True, trigger: str = "http") -> RunOutcome:
        run_id = new_run_id(TASK)
        outcome = RunOutcome(run_id=run_id, task=TASK, provider_code="registry", scope="Pakistan", trigger=trigger)
        outcome.details["dry_run"] = dry_run
        c = outcome.counts
        await self.recorder.start(outcome)
        try:
            async with self.session_factory() as db:
                cities, stations = await load_rows(db)
                p = plan(cities, stations)
                c.expected = c.attempted = c.completed = p.examined_stations
                c.rows_fetched = len(cities) + len(stations)
                outcome.details.update(p.to_details())
                if not dry_run and (p.cities or p.stations):
                    written = await apply(db, p, state_ids=await pakistan_state_ids(db), run_id=run_id)
                    await db.commit()
                    c.rows_written = sum(written.values())
                    outcome.details["written"] = written
                    # the rule must now be satisfied: re-plan on the fresh rows
                    cities2, stations2 = await load_rows(db)
                    rest = plan(cities2, stations2)
                    outcome.details["remaining_after_apply"] = {"cities": len(rest.cities), "stations": len(rest.stations)}
                    if rest.cities or rest.stations:
                        outcome.partial_reason = "not_converged"
                else:
                    c.rows_unchanged = len(p.cities) + len(p.stations)
            logger.info("%s %s: %s", TASK, "dry run" if dry_run else "applied", json.dumps(p.summary()))
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s run %s crashed", TASK, run_id)
            outcome.fail(type(exc).__name__, str(exc))
        finally:
            outcome.finish()
            await self.recorder.finish(outcome)
        return outcome


__all__ = ["CityRow", "StationRow", "CityChange", "StationChange", "Flag", "Plan", "plan", "apply", "load_rows",
           "RegistryProvincesTask", "province_for_point"]
