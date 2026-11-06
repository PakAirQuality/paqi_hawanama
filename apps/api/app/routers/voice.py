"""POST /voice/brief: the Tracker's spoken "air near you" brief (see app/services/voice_brief.py)."""

from __future__ import annotations

import math
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.services.voice_brief import VoiceUnavailable, as_payload, brief_audio, normalise

router = APIRouter()

# Station and city names may hold any letters and ordinary punctuation; markup, template and control
# characters have no place in one
_BAD_NAME = re.compile(r"[<>{}\[\]\\`$\x00-\x1f\x7f]")


class BriefRequest(BaseModel):
    lang: Literal["en", "ur"] = "en"
    station: str = Field(..., min_length=1, max_length=80)
    city: str = Field("", max_length=60)
    # allow_inf_nan=False: NaN passes no range test, so it is refused outright
    pm25: float = Field(..., ge=0, le=1000, allow_inf_nan=False)
    # The nowcast for the next few hours at the same monitor (both or neither)
    next_pm25: float | None = Field(None, ge=0, le=1000, allow_inf_nan=False)
    next_hours: float | None = Field(None, ge=1, le=24, allow_inf_nan=False)

    @field_validator("pm25", "next_pm25", "next_hours", mode="before")
    @classmethod
    def _finite(cls, v):
        # NaN or Infinity would be echoed back in the 422 body, which JSON cannot encode (a 500 instead):
        # swap them for text, which the float check then refuses cleanly
        if isinstance(v, float) and not math.isfinite(v):
            return "not a finite number"
        return v

    @field_validator("station", "city")
    @classmethod
    def _plain_name(cls, v: str) -> str:
        if v and _BAD_NAME.search(v):
            raise ValueError("unexpected characters in name")
        return v


class BriefResponse(BaseModel):
    lang: Literal["en", "ur"]
    text: str
    mime: str
    audio: str  # base64 WAV


@router.post("/voice/brief", response_model=BriefResponse, summary="Spoken air quality brief for the nearest station")
# The dashboard's hosting adds a trailing slash; answering it here saves a redirect that a proxied POST may not survive
@router.post("/voice/brief/", response_model=BriefResponse, include_in_schema=False)
async def voice_brief(req: BriefRequest) -> dict:
    has_next = req.next_pm25 is not None and req.next_hours is not None
    b = normalise(req.lang, req.station, req.city, req.pm25,
                  req.next_pm25 if has_next else None, req.next_hours if has_next else None)
    try:
        text, audio = await brief_audio(b)
    except VoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="The voice brief is unavailable right now.") from exc
    return as_payload(text, audio, b.lang)
