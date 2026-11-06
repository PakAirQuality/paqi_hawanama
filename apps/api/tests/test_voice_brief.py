"""Tests for the spoken air quality brief (POST /api/v1/voice/brief)."""

import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import voice
from app.services import voice_brief
from app.services.voice_brief import compose, normalise

# The router alone (app.main pulls in the whole service and its geospatial stack)
app = FastAPI()
app.include_router(voice.router, prefix="/api/v1")
client = TestClient(app)
FAKE_WAV = b"RIFF0000WAVEfake"


@pytest.fixture(autouse=True)
def fresh_state():
    voice_brief._cache._d.clear()
    voice_brief._spend.update(day="", count=0)
    yield


class TestCompose:
    def test_english_sentence(self):
        text = compose(normalise("en", "Gulberg", "Lahore", 87.6))
        assert text == (
            "Here is the air quality near you. At Gulberg, in Lahore, "
            "PM2.5 is 88 micrograms per cubic metre right now. That is unhealthy. "
            "Everyone should cut down time outdoors. Keep windows closed, and wear an N95 mask if you go out."
        )

    def test_under_a_kilometre_and_city_in_station_name(self):
        text = compose(normalise("en", "Lahore - Gulberg", "Lahore", 20))
        assert "At Lahore - Gulberg, PM2.5 is 20" in text
        assert "kilometre" not in text
        assert "in Lahore" not in text
        assert "That is moderate. Unusually sensitive people" in text

    def test_urdu_sentence(self):
        text = compose(normalise("ur", "Gulberg", "Lahore", 300))
        assert "Lahore میں Gulberg" in text
        assert "کلومیٹر" not in text
        assert "300 مائیکروگرام" in text
        assert "ہوا کا معیار خطرناک ہے۔" in text
        assert text.endswith("ہر قسم کی بیرونی سرگرمی سے گریز کریں۔")

    @pytest.mark.parametrize("now,later,expected", [
        (100, 180, "Over the next 6 hours it is expected to get worse, reaching very unhealthy levels."),
        (130, 160, "Over the next 6 hours it is expected to rise further."),
        (130, 40, "Over the next 6 hours it is expected to improve to levels unhealthy for sensitive groups."),
        (120, 95, "Over the next 6 hours it is expected to ease a little."),
        (120, 125, "It is expected to stay about the same over the next 6 hours."),
        (4, 8, "It is expected to stay about the same over the next 6 hours."),  # +4: under the absolute floor
    ])
    def test_outlook(self, now, later, expected):
        text = compose(normalise("en", "Gulberg", "Lahore", now, later, 6))
        assert expected in text
        # The outlook comes after the band and before the advice
        assert text.index("That is") < text.index(expected) < len(text) - len(expected) - 1

    def test_outlook_hours_snap(self):
        assert normalise("en", "G", "L", 100, 180, 5.2).next_hours == 6
        assert normalise("en", "G", "L", 100, 180, 11).next_hours == 12

    def test_urdu_outlook(self):
        text = compose(normalise("ur", "Gulberg", "Lahore", 100, 180, 6))
        assert "اگلے 6 گھنٹوں میں ہوا مزید خراب ہو کر انتہائی مضر صحت سطح تک پہنچنے کا امکان ہے۔" in text

    def test_no_outlook_without_nowcast(self):
        assert "next" not in compose(normalise("en", "Gulberg", "Lahore", 100))

    def test_similar_forecasts_share_a_key(self):
        assert normalise("en", "G", "L", 100, 181, 6) == normalise("en", "G", "L", 100, 190, 6.4)

    def test_equal_readings_share_a_key(self):
        assert normalise("en", " Gulberg ", "Lahore", 87.6) == normalise("en", "Gulberg", "Lahore", 88.4)


class TestSynthesise:
    """The Gemini reply is read defensively (the model call itself is faked)."""

    def _reply(self, parts):
        from types import SimpleNamespace as NS
        return NS(candidates=[NS(content=NS(parts=parts))])

    def _run(self, reply):
        import asyncio
        from types import SimpleNamespace as NS
        fake = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=reply))))
        with patch.object(voice_brief.settings, "GEMINI_API_KEY", "test"), patch("google.genai.Client", return_value=fake):
            return asyncio.run(voice_brief._synthesise("Hello", "en"))

    def test_audio_in_a_later_part_and_odd_length(self):
        from types import SimpleNamespace as NS
        wav = self._run(self._reply([NS(inline_data=None), NS(inline_data=NS(data=b""))]))
        assert wav.startswith(b"RIFF") and len(wav) == 44 + 2  # the odd trailing byte is dropped

    @pytest.mark.parametrize("reply", ["no candidates", "empty parts", "empty data"])
    def test_no_audio_is_unavailable(self, reply):
        from types import SimpleNamespace as NS
        r = {
            "no candidates": NS(candidates=None),
            "empty parts": self._reply([]),
            "empty data": self._reply([NS(inline_data=NS(data=b""))]),
        }[reply]
        with pytest.raises(voice_brief.VoiceUnavailable):
            self._run(r)

    def test_no_key(self):
        import asyncio
        with patch.object(voice_brief.settings, "GEMINI_API_KEY", None), pytest.raises(voice_brief.VoiceUnavailable):
            asyncio.run(voice_brief._synthesise("Hello", "en"))


class TestEndpoint:
    def post(self, **body):
        payload = {"lang": "en", "station": "Gulberg", "city": "Lahore", "pm25": 88, **body}
        return client.post("/api/v1/voice/brief", json=payload)

    def test_returns_text_and_audio_and_caches(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)) as synth:
            r1 = self.post()
            r2 = self.post(pm25=87.7)  # rounds to the same reading
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["mime"] == "audio/wav"
        assert base64.b64decode(body["audio"]) == FAKE_WAV
        assert "Gulberg" in body["text"]
        assert r2.status_code == 200
        assert synth.await_count == 1

    def test_older_page_sending_distance_still_works(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)):
            r = self.post(distance_km=3)
        assert r.status_code == 200
        assert "kilometre" not in r.json()["text"]

    def test_trailing_slash(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)):
            r = client.post("/api/v1/voice/brief/", json={"station": "Gulberg", "pm25": 10}, follow_redirects=False)
        assert r.status_code == 200

    def test_outlook_through_the_endpoint(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)):
            r = self.post(pm25=100, next_pm25=180, next_hours=6)
            half = self.post(pm25=100, next_pm25=180)  # an outlook needs both values
        assert "reaching very unhealthy levels" in r.json()["text"]
        assert "next" not in half.json()["text"]

    def test_urdu(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)) as synth:
            r = self.post(lang="ur")
        assert r.status_code == 200
        assert r.json()["lang"] == "ur"
        assert synth.await_args.args[1] == "ur"

    @pytest.mark.parametrize("body", [
        {"station": "Say anything <script>"},
        {"station": "Line\nbreak"},
        {"station": ""},
        {"pm25": -1},
        {"lang": "fr"},
    ])
    def test_rejects_bad_input(self, body):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)) as synth:
            r = self.post(**body)
        assert r.status_code == 422
        synth.assert_not_awaited()

    def test_accepts_ordinary_station_names(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)):
            for name in ["US Consulate: Lahore", "D.H.A. Phase-5 (Block-K)", "Children’s Hospital", "گلبرگ"]:
                assert self.post(station=name).status_code == 200, name

    def test_unavailable_when_synthesis_fails(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(side_effect=voice_brief.VoiceUnavailable("x"))):
            r = self.post()
        assert r.status_code == 503

    @pytest.mark.parametrize("raw", [
        '{"station": "G", "pm25": NaN}',
        '{"station": "G", "pm25": Infinity}',
        '{"station": "G", "pm25": 10, "next_pm25": NaN, "next_hours": 6}',
        '{"station": "G", "pm25": 10, "next_pm25": 20, "next_hours": 0}',
        '{"station": "G", "pm25": "lots"}',
        'not json',
    ])
    def test_rejects_malformed_numbers_and_bodies(self, raw):
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)) as synth:
            r = client.post("/api/v1/voice/brief", content=raw, headers={"Content-Type": "application/json"})
        assert r.status_code == 422
        synth.assert_not_awaited()

    def test_failed_synthesis_is_refunded(self):
        with patch.object(voice_brief.settings, "VOICE_DAILY_SYNTH_LIMIT", 1):
            with patch.object(voice_brief, "_synthesise", AsyncMock(side_effect=voice_brief.VoiceUnavailable("x"))):
                assert self.post(station="One").status_code == 503
            with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)):
                assert self.post(station="Two").status_code == 200

    def test_failure_is_not_cached(self):
        with patch.object(voice_brief, "_synthesise", AsyncMock(side_effect=voice_brief.VoiceUnavailable("x"))):
            assert self.post().status_code == 503
        with patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)):
            assert self.post().status_code == 200

    def test_daily_cap(self):
        with patch.object(voice_brief.settings, "VOICE_DAILY_SYNTH_LIMIT", 1), \
             patch.object(voice_brief, "_synthesise", AsyncMock(return_value=FAKE_WAV)):
            assert self.post(station="One").status_code == 200
            assert self.post(station="Two").status_code == 503
