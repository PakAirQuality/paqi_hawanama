"""A failing copilot tool returns a message the model can relay; it never aborts the run."""

import logging

import pytest
from fastapi import HTTPException
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.test import TestModel

from app.services.copilot.agent import _safe_tool


async def forecast_tool(ctx: RunContext[dict], city_name: str, horizon: int = 1) -> dict:
    """Impact brief for a city."""
    raise HTTPException(status_code=404, detail="Forecast data not found for the requested date.")


async def sql_tool(ctx: RunContext[dict], entity_name: str = "") -> dict:
    """Coverage lookup."""
    raise RuntimeError("column s.state does not exist")


async def retry_tool(ctx: RunContext[dict]) -> dict:
    raise ModelRetry("say which city")


async def fine_tool(ctx: RunContext[dict], n: int = 1) -> dict:
    return {"data": {"n": n}}


async def test_http_exception_becomes_the_detail_message(caplog):
    with caplog.at_level(logging.WARNING):
        out = await _safe_tool(forecast_tool)(None, "Lahore")
    assert out == {"data": {"message": "Forecast data not found for the requested date."}, "followups": []}
    assert "forecast_tool: 404" in caplog.text


async def test_other_exceptions_become_a_failure_message_with_traceback_logged(caplog):
    with caplog.at_level(logging.ERROR):
        out = await _safe_tool(sql_tool)(None, entity_name="KP")
    assert out["data"]["message"].startswith("The sql_tool lookup failed (RuntimeError)")
    assert out["followups"] == []
    assert "column s.state does not exist" in caplog.text     # exc_info=True keeps the cause


async def test_model_retry_passes_through():
    with pytest.raises(ModelRetry):
        await _safe_tool(retry_tool)(None)


async def test_success_is_untouched():
    assert await _safe_tool(fine_tool)(None, n=3) == {"data": {"n": 3}}


def test_wrapper_keeps_name_signature_and_docstring():
    import inspect
    w = _safe_tool(forecast_tool)
    assert w.__name__ == "forecast_tool" and w.__doc__ == "Impact brief for a city."
    assert list(inspect.signature(w).parameters) == ["ctx", "city_name", "horizon"]


async def test_pydantic_ai_builds_the_same_schema_and_relays_the_failure():
    """TestModel calls every registered tool with generated args; the run must complete."""
    agent = Agent(TestModel(), deps_type=dict)
    agent.tool(_safe_tool(forecast_tool))
    agent.tool(_safe_tool(fine_tool))
    result = await agent.run("hello", deps={})
    returns = [p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart)]
    by_name = {p.tool_name: p.content for p in returns}
    assert set(by_name) == {"forecast_tool", "fine_tool"}
    assert by_name["forecast_tool"]["data"]["message"] == "Forecast data not found for the requested date."
    assert by_name["fine_tool"] == {"data": {"n": by_name["fine_tool"]["data"]["n"]}}
    schema = agent._function_toolset.tools["forecast_tool"].function_schema.json_schema
    assert set(schema["properties"]) == {"city_name", "horizon"} and schema["required"] == ["city_name"]
