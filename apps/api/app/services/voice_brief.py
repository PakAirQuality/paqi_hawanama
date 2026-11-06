"""Spoken air quality brief for the Tracker's "Listen" button.

The browser sends the reading it already shows in its "Near you" card (station, city, PM2.5, and
the nowcast a few hours ahead). The text is built here from a fixed template, so the endpoint can only ever say an air
quality sentence about a station, never arbitrary text. Gemini text-to-speech reads it in English
or Urdu.

Inputs are rounded (whole km, whole µg/m³) before anything else, so everyone near the same monitor
in the same hour gets the same sentence and the same cached audio: the paid synthesis runs once
per station reading, not once per visitor.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import wave
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from app.core.config import settings
from app.services.aqi.pm25 import band_key

logger = logging.getLogger(__name__)

Lang = Literal["en", "ur"]
Trend = Literal["up", "down", "steady"]

# Gemini TTS returns raw 16-bit mono PCM at 24 kHz
_PCM_RATE = 24_000
_PCM_WIDTH = 2

_BAND_EN = {
    "good": "good",
    "moderate": "moderate",
    "unhealthy_sensitive": "unhealthy for sensitive groups",
    "unhealthy": "unhealthy",
    "very_unhealthy": "very unhealthy",
    "hazardous": "hazardous",
}
_BAND_UR = {
    "good": "اچھا",
    "moderate": "درمیانہ",
    "unhealthy_sensitive": "حساس افراد کے لیے مضر صحت",
    "unhealthy": "مضر صحت",
    "very_unhealthy": "انتہائی مضر صحت",
    "hazardous": "خطرناک",
}


@dataclass(frozen=True)
class BriefInput:
    """A rounded reading: the cache key and the template's only inputs."""

    lang: Lang
    station: str
    city: str
    pm25: int
    # The next few hours (from the nowcast): which way it goes, the band it reaches, and over how long
    trend: Trend | None = None
    next_band: str | None = None
    next_hours: int | None = None



# Health advice for each band, after the US EPA's activity guidance
_ADVICE_EN = {
    "good": "It's a good time to be active outside.",
    "moderate": "Unusually sensitive people should consider cutting back on long or heavy outdoor exertion.",
    "unhealthy_sensitive": "Children, older adults and people with heart or lung disease should cut back on long or heavy outdoor exertion.",
    "unhealthy": "Everyone should cut down time outdoors. Keep windows closed, and wear an N95 mask if you go out.",
    "very_unhealthy": "Everyone should avoid outdoor exertion and stay indoors where possible. Wear an N95 mask if you must go out.",
    "hazardous": "Everyone should stay indoors with windows closed and avoid all outdoor activity.",
}
_ADVICE_UR = {
    "good": "باہر سرگرمیوں کے لیے اچھا وقت ہے۔",
    "moderate": "بہت حساس افراد طویل یا سخت بیرونی سرگرمی کم کریں۔",
    "unhealthy_sensitive": "بچے، بزرگ اور دل یا پھیپھڑوں کے مریض طویل یا سخت بیرونی سرگرمی کم کریں۔",
    "unhealthy": "سب لوگ باہر کم وقت گزاریں۔ کھڑکیاں بند رکھیں، اور باہر جائیں تو این پچانوے ماسک پہنیں۔",
    "very_unhealthy": "سب لوگ بیرونی سرگرمی سے گریز کریں اور جہاں تک ہو سکے گھر کے اندر رہیں۔ باہر جانا ضروری ہو تو این پچانوے ماسک پہنیں۔",
    "hazardous": "سب لوگ کھڑکیاں بند رکھ کر گھر کے اندر رہیں اور ہر قسم کی بیرونی سرگرمی سے گریز کریں۔",
}

# A band as the level the air reaches ("reaching unhealthy levels")
_LEVELS_EN = {
    "good": "good levels",
    "moderate": "moderate levels",
    "unhealthy_sensitive": "levels unhealthy for sensitive groups",
    "unhealthy": "unhealthy levels",
    "very_unhealthy": "very unhealthy levels",
    "hazardous": "hazardous levels",
}


def _trend(now: float, later: float) -> Trend:
    """Up or down when the change is both relative (15 %) and absolute (5 µg/m³); otherwise steady."""
    if later >= now * 1.15 and later - now >= 5:
        return "up"
    if later <= now * 0.85 and now - later >= 5:
        return "down"
    return "steady"


def normalise(lang: Lang, station: str, city: str, pm25: float,
              next_pm25: float | None = None, next_hours: float | None = None) -> BriefInput:
    """Round and tidy the reading so equal readings share one sentence and one recording.

    The outlook is kept only as a direction, the band it reaches and a whole number of hours (3, 6, 9 or 12),
    which is all the sentence says, so small changes in the forecast still share a recording.
    """
    station = " ".join(station.split())
    city = " ".join(city.split())
    pm = int(round(pm25))
    trend = next_band = hours = None
    if next_pm25 is not None and next_hours is not None:
        trend = _trend(pm25, next_pm25)
        next_band = band_key(next_pm25) if trend != "steady" else None
        hours = min((3, 6, 9, 12), key=lambda h: abs(h - next_hours))
    return BriefInput(
        lang=lang, station=station, city=city,
        pm25=pm,
        trend=trend, next_band=next_band, next_hours=hours,
    )


def _outlook(b: BriefInput, band: str) -> str:
    """The next-few-hours sentence, or nothing without a nowcast."""
    if not b.trend or not b.next_hours:
        return ""
    h = b.next_hours
    crosses = b.next_band is not None and b.next_band != band
    if b.lang == "ur":
        nb = _BAND_UR.get(b.next_band or "", "")
        if b.trend == "up":
            return f"اگلے {h} گھنٹوں میں ہوا مزید خراب ہو کر {nb} سطح تک پہنچنے کا امکان ہے۔" if crosses else f"اگلے {h} گھنٹوں میں آلودگی مزید بڑھنے کا امکان ہے۔"
        if b.trend == "down":
            return f"اگلے {h} گھنٹوں میں ہوا بہتر ہو کر {nb} سطح پر آنے کا امکان ہے۔" if crosses else f"اگلے {h} گھنٹوں میں آلودگی میں کچھ کمی کا امکان ہے۔"
        return f"اگلے {h} گھنٹوں میں ہوا کا معیار تقریباً ایسا ہی رہنے کا امکان ہے۔"
    levels = _LEVELS_EN.get(b.next_band or "", "")
    if b.trend == "up":
        return f"Over the next {h} hours it is expected to get worse, reaching {levels}." if crosses else f"Over the next {h} hours it is expected to rise further."
    if b.trend == "down":
        return f"Over the next {h} hours it is expected to improve to {levels}." if crosses else f"Over the next {h} hours it is expected to ease a little."
    return f"It is expected to stay about the same over the next {h} hours."


def compose(b: BriefInput) -> str:
    """The sentence the voice reads: the reading, its band, the next few hours, then what to do."""
    band = band_key(b.pm25)
    # A station called "Lahore - Gulberg" already names its city
    with_city = bool(b.city) and b.city.lower() not in b.station.lower()
    outlook = _outlook(b, band)
    if b.lang == "ur":
        where = f"{b.city} میں {b.station}" if with_city else b.station
        parts = [
            "آپ کے قریب ہوا کا معیار۔",
            f"{where} کے مقام پر "
            f"اس وقت پی ایم ٹو پوائنٹ فائیو کی سطح {b.pm25} مائیکروگرام فی مکعب میٹر ہے۔",
            f"ہوا کا معیار {_BAND_UR.get(band, 'نامعلوم')} ہے۔",
            outlook,
            _ADVICE_UR.get(band, ""),
        ]
        return " ".join(p for p in parts if p)
    where = f"{b.station}, in {b.city}" if with_city else b.station
    parts = [
        "Here is the air quality near you.",
        f"At {where}, PM2.5 is {b.pm25} micrograms per cubic metre right now.",
        f"That is {_BAND_EN.get(band, 'unknown')}.",
        outlook,
        _ADVICE_EN.get(band, ""),
    ]
    return " ".join(p for p in parts if p)


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(_PCM_WIDTH)
        w.setframerate(_PCM_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class VoiceUnavailable(RuntimeError):
    """Synthesis cannot run (no key, daily cap reached, or the model failed)."""


class _Cache:
    """A small LRU of finished recordings, by rounded reading."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._d: OrderedDict[BriefInput, tuple[float, bytes]] = OrderedDict()

    def get(self, k: BriefInput, ttl_s: float) -> bytes | None:
        hit = self._d.get(k)
        if not hit:
            return None
        made, audio = hit
        if time.monotonic() - made > ttl_s:
            del self._d[k]
            return None
        self._d.move_to_end(k)
        return audio

    def put(self, k: BriefInput, audio: bytes) -> None:
        self._d[k] = (time.monotonic(), audio)
        self._d.move_to_end(k)
        while len(self._d) > self.size:
            self._d.popitem(last=False)


_cache = _Cache(settings.VOICE_CACHE_SIZE)
_locks: dict[BriefInput, asyncio.Lock] = {}
_spend = {"day": "", "count": 0}


def _within_daily_cap() -> bool:
    """Count one paid synthesis against this instance's daily cap."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _spend["day"] != today:
        _spend.update(day=today, count=0)
    if _spend["count"] >= settings.VOICE_DAILY_SYNTH_LIMIT:
        return False
    _spend["count"] += 1
    return True


def _refund() -> None:
    _spend["count"] = max(0, _spend["count"] - 1)


async def _synthesise(text: str, lang: Lang) -> bytes:
    """Gemini text-to-speech: WAV bytes for `text`."""
    if not settings.GEMINI_API_KEY:
        raise VoiceUnavailable("GEMINI_API_KEY not configured")
    from google import genai
    from google.genai import types

    style = "in Urdu, with a natural Pakistani accent, " if lang == "ur" else ""
    prompt = f"Read this air quality update aloud {style}in a calm, clear and friendly voice:\n\n{text}"
    # Speech output (speech_config) exists only on v1beta; google-genai 3 defaults the Gemini API to v1
    client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options=types.HttpOptions(api_version="v1beta"))
    try:
        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=settings.VOICE_TTS_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.VOICE_TTS_VOICE),
                        ),
                    ),
                ),
            ),
            timeout=30,
        )
        # The audio is in whichever part carries inline data (normally the first)
        pcm = b""
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else None) or []:
                if part.inline_data is not None and part.inline_data.data:
                    pcm = part.inline_data.data
                    break
            if pcm:
                break
    except Exception as exc:  # noqa: BLE001 - any model failure means no audio this time
        logger.warning("voice brief synthesis failed: %s", exc)
        raise VoiceUnavailable("synthesis failed") from exc
    if not pcm:
        raise VoiceUnavailable("empty audio")
    if isinstance(pcm, str):  # some SDK versions hand back base64 text
        pcm = base64.b64decode(pcm)
    if len(pcm) % _PCM_WIDTH:
        pcm = pcm[: len(pcm) - len(pcm) % _PCM_WIDTH]
    return _wav(pcm)


async def brief_audio(b: BriefInput) -> tuple[str, bytes]:
    """The sentence and its recording, from the cache when this reading was read before."""
    text = compose(b)
    ttl = settings.VOICE_CACHE_TTL_S
    audio = _cache.get(b, ttl)
    if audio:
        return text, audio
    # Visitors asking for the same reading at once wait for one synthesis
    lock = _locks.setdefault(b, asyncio.Lock())
    try:
        async with lock:
            audio = _cache.get(b, ttl)
            if audio:
                return text, audio
            if not _within_daily_cap():
                raise VoiceUnavailable("daily limit reached")
            try:
                audio = await _synthesise(text, b.lang)
            except VoiceUnavailable:
                _refund()  # a failed synthesis does not use up the day's allowance
                raise
            _cache.put(b, audio)
            return text, audio
    finally:
        if not lock.locked():
            _locks.pop(b, None)


def as_payload(text: str, audio: bytes, lang: Lang) -> dict:
    return {"lang": lang, "text": text, "mime": "audio/wav", "audio": base64.b64encode(audio).decode("ascii")}
