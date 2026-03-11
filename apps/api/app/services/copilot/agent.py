"""PydanticAI agent for the analyst desk copilot."""

import logging

from app.core.config import settings

from .context import CopilotSession
from . import tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the Hawanama Analyst Desk Copilot — an AI assistant for air-quality \
analysts monitoring PM2.5 forecasts across Pakistan.

## Your role
- Answer questions about today's PM2.5 forecasts, city conditions, watchlists, \
  and multi-day trends.
- Use your tools to retrieve real data before answering. Never fabricate numbers.
- Be concise and direct. Lead with the key finding, then give supporting detail.
- Use µg/m³ units for PM2.5 values.

## Response guidelines
- When discussing a city, mention its risk band and whether conditions are \
  worsening or improving.
- When listing stations or cities, use a brief ranked format (top 5 max unless \
  the user asks for more).
- If the user asks about trends, use compare_dates or note the trend field \
  from city summaries.
- If asked about a specific station, provide all horizon forecasts.

## Map actions
When your answer references a specific city, emit an inline action tag so the \
frontend can move the map:
  {{ACTION:{"type":"zoom_to_city","city":"Lahore"}}}
When referencing a specific station, emit:
  {{ACTION:{"type":"zoom_to_station","sensor_id":12345,"lat":31.5,"lng":74.3}}}
When the user asks to change the forecast horizon, emit:
  {{ACTION:{"type":"set_horizon","horizon":1}}}
Only emit ONE action per response. Place it at the end of the relevant sentence.

## Risk bands (PM2.5 µg/m³)
- good: 0–35
- moderate: 35–75
- unhealthy: 75–150
- very_unhealthy: 150–250
- severe: >250
"""

BRIEFING_PROMPT = """\
Generate a brief opening briefing for an air-quality analyst starting their \
shift. Use the national overview and top polluted cities tools. \
Summarise in 3-4 sentences: overall conditions, worst city, how many stations \
are unhealthy or worse, and any ramp events. Be direct and factual.
"""

# Lazy singleton — avoids import-time crash when GEMINI_API_KEY is unset
_copilot_agent = None


def get_agent():
    """Return the copilot agent, creating it on first call."""
    global _copilot_agent
    if _copilot_agent is not None:
        return _copilot_agent

    from pydantic_ai import Agent
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    model = GoogleModel(
        "gemini-2.5-flash",
        provider=GoogleProvider(api_key=api_key),
    )

    agent = Agent(
        model,
        system_prompt=SYSTEM_PROMPT,
        deps_type=CopilotSession,
    )

    agent.tool(tools.get_national_overview)
    agent.tool(tools.get_top_polluted_cities)
    agent.tool(tools.get_city_detail)
    agent.tool(tools.get_station_forecast)
    agent.tool(tools.get_watchlist)
    agent.tool(tools.compare_dates)
    agent.tool(tools.search_stations)

    _copilot_agent = agent
    logger.info("Copilot agent initialized (gemini-2.5-flash)")
    return agent
