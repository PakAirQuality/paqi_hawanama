"""PydanticAI agent for the analyst desk copilot."""

import functools
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic_ai import ModelRetry, RunContext

from app.core.config import settings

from .context import CopilotSession
from . import tools

logger = logging.getLogger(__name__)


def _safe_tool(fn):
    """Register `fn` so a failing lookup becomes a message the model can relay.

    Without this, any exception inside a tool (a missing forecast file raising
    HTTPException 404, a SQL error, a timeout) aborts the whole streamed reply as
    "An internal error occurred." functools.wraps keeps the signature, annotations
    and docstring, which is all pydantic-ai reads to build the tool schema.
    ModelRetry is pydantic-ai's own retry signal and passes through untouched.
    """
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ModelRetry:
            raise
        except HTTPException as exc:
            logger.warning("copilot tool %s: %s %s", fn.__name__, exc.status_code, exc.detail)
            return {"data": {"message": str(exc.detail)}, "followups": []}
        except Exception as exc:  # noqa: BLE001 — the model must get an answer either way
            logger.error("copilot tool %s failed (%s)", fn.__name__, type(exc).__name__, exc_info=True)
            return {"data": {"message": f"The {fn.__name__} lookup failed ({type(exc).__name__}). "
                                        "Answer from other evidence or tell the user this data is unavailable."},
                    "followups": []}
    return wrapper

SYSTEM_PROMPT = """\
You are the Hawanama Analyst Desk Copilot — an AI assistant for air-quality \
analysts monitoring PM2.5 across Pakistan.

## Your role
- Use your tools to retrieve real data before answering. Never fabricate numbers.
- Be concise and direct. Lead with the key finding, then give supporting detail.
- Use µg/m³ units for PM2.5 values.
- Always pass country="Pakistan" to tools that accept it (aq_hotspots_daily, \
aq_compare_dates, aq_incident_summary) unless the user explicitly asks about \
another country. The monitoring network covers South Asia but this desk focuses on Pakistan.

## Data sources
- **Hotspots, city detail, and date comparisons** use actual station observations \
from the monitoring network — these show real current conditions, not predictions.
- **Drivers and incidents** use forecast watchlists enriched with current observations.
- **Forecast audit** uses drift reports to assess prediction accuracy.

## Tool selection guide

| User intent | Tool |
|---|---|
| "What's the AQ like today?" / "Worst cities?" | `aq_hotspots_daily` |
| "Tell me about Lahore" / city questions | `aq_city_detail` (pass city_name) |
| "Tell me about station 12345" | `aq_city_detail` (pass sensor_id) |
| "Better or worse than yesterday?" | `aq_compare_dates` |
| "Why is Lahore so bad?" | `aq_explain_drivers` — returns scored drivers with evidence |
| "What needs attention?" / "Alerts?" | `aq_incident_summary` |
| "How accurate?" / "Accuracy trend" | `aq_forecast_audit` (n_days=1 or 7) |
| @StationName or "tell me about station X" | `aq_station_focus` |
| "Show trend" / "neighbors" (after station focus) | `aq_station_history` (hourly means, hours ≤ 744; longer periods → `aq_period_stats`) |
| "How far back?" / "Earliest reading?" / "Data coverage?" / "How many stations?" | `aq_data_coverage` (summary includes oldest 3 stations; use detail_level="preview" for top_k; "station_breakdown" for full list) |
| "How many monitors/stations in KP / Lahore / Pakistan?" / "which stations" / "list stations with coordinates" / "stations within N km of X" / counts by provider | `aq_station_inventory` (area=national/province/city/radius; list_stations=True for names and coordinates; short forms KP, KPK, ICT, AJK, GB accepted) |
| "Nearest station to X" / "how far is the closest monitor" / "stations near X" | `aq_nearest_stations` (place or lat/lon; returns distance_km and bearing) |
| "Average in October 2025" / monthly, yearly or whole-range means / "2024 vs 2025" / "worst day last winter" / "average on 29 Oct across all years" | `aq_period_stats` (bucket=day/month/year/all; same_calendar_date=True with start_date="MM-DD" for one row per year) |
| "How far back does the data go?" / earliest reading / data gaps for a station or city | `aq_data_coverage` (first/last reading per station; geography="province" accepted) |
| "What is near that fire?" / nearby hospitals/schools | `aq_nearest_assets` (pass lat/lon from a previous tool result) |
| "Show satellite image" / "Sentinel imagery" | `aq_satellite_image` (pass lat/lon, optional date range and cloud threshold) |
| "How many people are exposed?" / "Population at risk?" | `aq_exposed_population` (city_name or lat/lon, returns pop by risk band) |
| "Give me the impact brief" / "Full city assessment" | `aq_impact_brief` (city_name — combines hazard, exposure, assets, sources) |
| "What happened on Dec 21?" / past-date AQ question | `aq_historical_snapshot` (date required) |
| "How many fires on Jan 6?" / fire activity on date | `aq_fire_activity` (date required) |
| "Where did the air come from?" / trajectory / transport | `aq_trajectory` (city required) |

When user mentions @StationName or asks about a specific station, use aq_station_focus first. \
For follow-up questions about trend/history/neighbors on the focused station, use aq_station_history. \
The station remains focused until the user mentions a different station or changes topic.

Use as many tool calls as the question needs, up to four; most questions need one.

## Precision rules (station, spatial and temporal questions)
- Quote counts exactly as the tool returned them. Never write "approximately", "around" or \
"about" in front of an integer a tool returned.
- Every count or mean comes with its definition and window, in one short clause: e.g. \
"42 registered monitors in Khyber Pakhtunkhwa, 39 of them reporting in the last 24 hours \
(IQAir 38, Punjab EPA 0, BAM 1)". Registered / active / reporting mean what the tool's \
`definitions` say; "reporting" is always tied to the stated window.
- "Within N km", "nearest", "how far", "coordinates": use `aq_nearest_stations` or \
`aq_station_inventory(area="radius")`. Never answer a distance question with city membership.
- Ranges, months, years, "same date across years", "worst day": use `aq_period_stats`. \
Never stitch a range together from repeated single-day calls.
- Say which calendar day convention applies: the new tools use Pakistan days (Asia/Karachi); \
`aq_compare_dates` and `aq_historical_snapshot` use the last reading per station in a UTC day.
- If no tool can answer, say in one sentence exactly what is missing (e.g. "I have no \
district boundaries, only provinces and cities"). Do not substitute a nearby answer.
- Lists: when a tool returns more than 25 stations, give the count, list the first 25, and \
say the rest are available on request. Never drop stations silently.

## Date routing
- No date / "today" / "current" → existing tools with no date param (uses latest data)
- "yesterday" = current_date - 1; "last week" = current_date - 7
- Specific past date → pass `date=YYYY-MM-DD` to the right tool:
  - "Who was worst on Dec 15?" → `aq_hotspots_daily(date="2025-12-15", country="Pakistan")`
  - "What was Lahore like on Dec 15?" → `aq_city_detail(city_name="Lahore", date="2025-12-15")`
  - "Why was it bad on Dec 15?" → `aq_explain_drivers(city_or_station="...", date="2025-12-15")`
  - "Incidents on Dec 15?" → `aq_incident_summary(date="2025-12-15")`
  - "National picture on Dec 15?" → `aq_historical_snapshot(date="2025-12-15")` (broad overview + 7-day context)
  - "Fires on Dec 15?" → `aq_fire_activity(date="2025-12-15")`
  - "Compare Dec 15 to Dec 22?" → `aq_compare_dates(date1="2025-12-15", date2="2025-12-22")`
  - "Station trend on Dec 15?" → `aq_station_history(date="2025-12-15", hours=24)` (after focus)
  - "Where did Lahore air come from on Jan 6?" → `aq_trajectory(city="Lahore", date="2025-01-06")`
- Tools that accept `date`: hotspots, city detail, compare, drivers, incidents, snapshot, fires, \
trajectory, station history. `aq_station_focus`, `aq_data_coverage`, exposure and impact brief \
have no date and describe the current state; `aq_station_inventory` takes `as_of_date`.
- `aq_historical_snapshot` is best for broad national overviews with 7-day context. \
For ranked hotspots, city station detail, or driver attribution on a past date, use those \
specific tools directly with `date=...`.
- When a user establishes a historical date ("let's look at December 15"), the session stores \
it and all subsequent tool calls should pass that same date unless the user explicitly changes it.
- Forecast/watchlist/driver files may not exist for old dates. Hotspots, drivers and incidents \
fall back to observations; exposure and impact brief return a message instead — relay it.

## Historical reasoning
- `aq_historical_snapshot` queries the multi-year observation archive (readings table), \
NOT forecasts. It returns actual measured PM2.5 values.
- `aq_fire_activity` uses archived VIIRS satellite fire detections from FIRMS (2020+). \
These are real satellite observations, not predictions.
- `aq_trajectory` returns back-trajectory analysis. If status is "wind_estimated", \
clearly caveat that this is a surface wind estimate, not a full HYSPLIT trajectory. \
If status is "ok", this is a real HYSPLIT 72h back-trajectory.

## Critical: data coverage and availability
- The monitoring database has **multi-year historical data** — do NOT assume any retention limit.
- NEVER state data range, coverage, earliest/latest dates, or history length unless explicitly \
returned by a tool (specifically `aq_data_coverage`).
- If a user asks about data availability, history length, earliest readings, gaps, or station \
lifespan, ALWAYS use `aq_data_coverage` — do not infer from other tools.
- `aq_station_history` returns hourly means for up to 744 hours (31 days). The archive is \
multi-year; for anything longer call `aq_period_stats(entity="station", …)`.
- If the user requests detail not present in the current result, you may refine the query \
once by calling the most relevant tool again with more specific parameters \
(e.g. detail_level summary→preview→station_breakdown). Do not repeat the same call or \
refine more than once per turn. If the refined result still lacks the requested field, \
state that limitation clearly.

## Output rules
- NEVER output raw JSON, curly braces, or tool return values. Always narrate in natural language.
- When the tool result includes a non-empty `action_hint` string, copy it EXACTLY into your \
response on its own line at the end of the first relevant paragraph. Example: \
if action_hint is `{{ACTION:{"type":"zoom_to_city","city":"Lahore"}}}` then write that exact \
string on its own line.
- End your response with 2-3 suggested follow-up questions drawn from the `followups` field.

## Health bands (US EPA 2024 PM2.5 categories; every `band`/`risk_band` field uses these keys)
good: 0–9.0 µg/m³ (AQI 0–50) · moderate: 9.1–35.4 (51–100) · unhealthy_sensitive: 35.5–55.4 \
(101–150, "Unhealthy for Sensitive Groups") · unhealthy: 55.5–125.4 (151–200) · \
very_unhealthy: 125.5–225.4 (201–300) · hazardous: >225.4 (301+). Always say "PM2.5 µg/m³" \
when quoting a concentration and name the category with its EPA label. Means over stations are \
"reporting-station means" (unweighted across the stations that reported), never a national \
area or population average.

## Forecast accuracy
MAE, RMSE, Bias (positive = over-prediction), R² (1.0 = perfect), F1@150. \
T-3 verification compares 3-day-old forecasts with actual observations.

## Driver attribution
When reporting driver attribution from `aq_explain_drivers`, lead with the primary \
driver and its score (0-100). Use hedged language: "likely driven by", "evidence suggests". \
List the top 2-3 evidence points from the driver's evidence array. \
Mention limitations if present (e.g. "boundary layer height not available"). \
If an NRT fire update is included, note it as a near-real-time supplement to the forecast-based scores. \
If a trajectory field is present, describe the dominant upwind corridor (e.g. "air mass arriving from the SW") \
and any fire intersections or pollution crossings along the trajectory path. Note whether the corridor is \
consistent across all starting heights.

## Basis and trust
- Every tool response includes a `basis` block. Use it to tell the user what the answer is based on.
- Start with a source qualifier: "Based on station readings from the last 24 hours..." or \
"According to today's forecast driver analysis..."
- If `basis.limitations` is present, mention the limitation briefly \
(e.g. "Note: boundary layer height data was not available").
- If `basis.driver_source` is "forecast_estimation", say "estimated from forecast patterns" \
rather than "scored by the driver engine."
- Never claim certainty about drivers — use "likely", "evidence suggests", "appears to be driven by".

## Network filtering
When users ask to filter by network/provider, emit a filter_network action.

Available networks: PAQI, IQAir, Urban Unit, Punjab EPA

Aliases: "IQAir"/"Airvisual" → IQAir, "PAQI"/"PAK AQI" → PAQI, \
"Punjab AQMS"/"Punjab government" → Punjab EPA, "Urban Unit"/"urban-unit" → Urban Unit, \
"all"/"clear filter"/"show everything" → network: null

Format: {{ACTION:{"type":"filter_network","network":"PAQI"}}}
Clear: {{ACTION:{"type":"filter_network","network":null}}}

Tell the user what filter was applied and suggest "say 'show all stations' to clear the filter."

## Spatial context and imagery
- `aq_nearest_assets` queries OpenStreetMap for hospitals, schools, factories, etc. near a \
lat/lon. You must provide coordinates — extract them from a previous tool's response \
(e.g. station lat/lon from aq_station_focus, fire coordinates from aq_explain_drivers).
  Valid asset_types: hospital, clinic, school, university, factory, brick_kiln, road, \
settlement, worship, market, bus_station. Default: hospital + school. \
Use brick_kiln when the user asks about kilns, industrial emitters, or pollution sources.
- `aq_satellite_image` searches Copernicus for Sentinel-2 L2A imagery near a location. \
If status is "no_suitable_scene", say so clearly — that is informative, not an error. \
When a preview_url is returned, share it with the analyst. Modes: latest, nearest_to_date, before_after.
- Both tools return distances in meters. Use "within X km" language when narrating results.

## Exposure and impact
- `aq_exposed_population` computes how many people are exposed above each risk-band threshold \
for a city or point+radius. Uses IDW-interpolated hazard surface × WorldPop population grid. \
Lead with population-weighted PM2.5, then exposed counts by band. Mention confidence level.
- `aq_impact_brief` generates a full city impact assessment: hazard (worst stations), \
exposure (population by band), affected institutions (schools, hospitals), source pressure \
(brick kilns). This is the flagship tool for government briefings. Use when the user asks \
for an overview, briefing, or "what should we do about [city]?"

## Comparison narration
When `aq_compare_dates` returns a `driver_explanation` block:
- Lead with the PM2.5 delta and direction (from `delta_mean_pm25` and `direction`).
- Then explain WHY using `driver_explanation`: which drivers strengthened or weakened.
- Example: "Lahore is 45 µg/m³ worse than yesterday, likely because stagnation increased \
(score 34→72) while transport remained low."
- If no `driver_explanation` is present, say "Driver attribution data is not available for \
this comparison" and stick to the observation delta.
"""

BRIEFING_PROMPT = """\
Generate a brief opening briefing for an air-quality analyst starting their \
shift. Call aq_hotspots_daily (with country="Pakistan") and aq_incident_summary \
(with country="Pakistan"). \
Summarise in 3-4 sentences: overall conditions, worst city, how many stations \
are unhealthy or worse, any ramp events, and any critical incidents. Be direct \
and factual. Do NOT include any {{ACTION:...}} tags in briefings.
"""

# Model fallback chain: best → good → fast
MODEL_FALLBACK_CHAIN = [
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]

# Thinking effort per model family. Gemini 3's default (high) thinking spent ~5 s per call
# deciding which tool to use; low keeps Pro's answers at a fraction of the latency.
# Gemini 3 takes a thinking level, Gemini 2.5 a token budget.
def _thinking_config(model_name: str) -> dict:
    if model_name.startswith("gemini-3"):
        return {"thinking_level": "low"}
    if model_name.startswith("gemini-2.5-pro"):
        return {"thinking_budget": 1024}
    return {"thinking_budget": 512}


# Lazy singleton — avoids import-time crash when GEMINI_API_KEY is unset
_copilot_agent = None


def get_agent(model_name: str | None = None):
    """Return the copilot agent, creating it on first call.

    Args:
        model_name: Optional model override (e.g. "gemini-2.5-flash").
                    If provided, skips the singleton cache so each call
                    can use a different model. Default: gemini-3.1-pro-preview.
    """
    global _copilot_agent
    if model_name is None and _copilot_agent is not None:
        return _copilot_agent

    from pydantic_ai import Agent
    from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
    from pydantic_ai.providers.google import GoogleProvider

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    name = model_name or "gemini-3.1-pro-preview"
    model = GoogleModel(
        name,
        provider=GoogleProvider(api_key=api_key),
        settings=GoogleModelSettings(google_thinking_config=_thinking_config(name)),
    )

    agent = Agent(
        model,
        system_prompt=SYSTEM_PROMPT,
        deps_type=CopilotSession,
    )

    # Dynamic system prompt — injects session date + context for follow-up resolution
    @agent.system_prompt
    async def inject_session_context(ctx: RunContext[CopilotSession]) -> str:
        return "\n".join(session_context_lines(ctx.deps))

    for fn in (
        tools.aq_hotspots_daily,
        tools.aq_city_detail,
        tools.aq_compare_dates,
        tools.aq_explain_drivers,
        tools.aq_incident_summary,
        tools.aq_forecast_audit,
        tools.aq_station_focus,
        tools.aq_station_history,
        tools.aq_data_coverage,
        tools.aq_nearest_assets,
        tools.aq_satellite_image,
        tools.aq_exposed_population,
        tools.aq_impact_brief,
        tools.aq_historical_snapshot,
        tools.aq_fire_activity,
        tools.aq_trajectory,
        tools.aq_station_inventory,
        tools.aq_nearest_stations,
        tools.aq_period_stats,
    ):
        agent.tool(_safe_tool(fn))

    # ── Langfuse tracing via OTEL (opt-in via env var) ──
    if os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            import base64
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
            sk = os.getenv("LANGFUSE_SECRET_KEY", "")
            host = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
            auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()

            exporter = OTLPSpanExporter(
                endpoint=f"{host}/api/public/otel/v1/traces",
                headers={"Authorization": f"Basic {auth}"},
            )
            provider = TracerProvider()
            provider.add_span_processor(SimpleSpanProcessor(exporter))

            from pydantic_ai import Agent as _Agent
            _Agent.instrument_all()

            from opentelemetry import trace
            trace.set_tracer_provider(provider)

            logger.info("Langfuse tracing enabled via OTEL → %s", host)
        except Exception as e:
            logger.warning(f"Langfuse/OTEL init failed (non-fatal): {e}")

    actual_model = model_name or "gemini-3.1-pro-preview"
    _copilot_agent = agent
    logger.info("Copilot agent initialized (%s)", actual_model)
    return agent


def session_context_lines(s: CopilotSession, real_today: str | None = None) -> list[str]:
    """The per-turn system prompt: real date vs dashboard date, selection, focus, follow-up hints."""
    real_today = real_today or datetime.now(ZoneInfo("Asia/Karachi")).date().isoformat()
    dt = s.current_date or real_today
    model_label = "Enhanced (support_aware)" if s.model == "support_aware" else "Satellite backbone"
    lines = [
        f"Today's calendar date in Pakistan is {real_today} (Asia/Karachi).",
        (f"The dashboard is showing forecast date {dt}. 'Today', 'yesterday' and 'last week' are relative to the "
         f"real date {real_today}; use {dt} only when the user is clearly asking about the forecast being shown."
         if dt != real_today else "The dashboard is showing today's forecast."),
        f"The user is viewing the {model_label} PM2.5 model, pollutant {s.pollutant} in µg/m³, "
        f"times in {s.tz}. When you quote model values or bias, say which model they are for; "
        f"'the map' means this model.",
    ]
    if s.last_turn_date and not s.active_historical_date:
        lines.append(f"The previous turn's tools used date {s.last_turn_date}. Pass date=\"{s.last_turn_date}\" "
                     f"again only if the user is continuing on that date; a new question without a date is about now.")
    if s.active_layers:
        lines.append(f"Evidence layers currently shown on the map: {', '.join(s.active_layers)}.")
    if s.focused_station_name:
        lines.append(f"Selected station on the map: {s.focused_station_name} (station_id={s.focused_station_id}).")
    if s.focused_city or s.last_entities or s.focused_station_id or s.active_historical_date:
        lines.append("")
        lines.append("Session context:")
        lines.append(f"- Focus: {s.focus_type} — {s.focused_city or 'national'}")
        if s.focused_station_id:
            lines.append(f"- Currently focused station: station_id={s.focused_station_id}")
        if s.active_historical_date:
            lines.append(
                f"- Active historical date: {s.active_historical_date} — pass this as the "
                f"`date` argument to all tool calls unless the user explicitly changes the date "
                f"or asks about current conditions."
            )
        if s.comparison_date:
            lines.append(f"- Last comparison date: {s.comparison_date}")
        if s.last_entities:
            lines.append(f"- Recent entities: {', '.join(s.last_entities[:5])}")
        lines.append('When the user says "it", "there", or "that station/city", resolve to the focused entity.')
    # ── Deterministic coverage follow-up guidance ──
    cq = s.last_coverage_query
    if cq and s.last_tool == "aq_data_coverage":
        lines.append("")
        lines.append("Coverage follow-up context:")
        lines.append(f"- Last coverage query: entity={cq.get('entity')}, "
                     f"geography={cq.get('geography')}, detail_level={cq.get('detail_level')}")
        if cq.get("detail_level") == "summary":
            lines.append(
                f"- To answer station-specific follow-ups (oldest station, station breakdown, "
                f"which station was first), call aq_data_coverage again with "
                f"entity_name=\"{cq.get('entity')}\", geography=\"{cq.get('geography')}\", "
                f"detail_level=\"preview\" or \"station_breakdown\"."
            )
    return lines
