"""The vectorised wind PNG encoder must be byte-identical to the original per-pixel encoder."""

import struct
import zlib

import numpy as np

from app.routers.data_sources import _encode_png


def _reference(width, height, r_data, g_data):
    def chunk(t, d):
        raw = t + d
        return struct.pack(">I", len(d)) + raw + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            i = y * width + x
            rows.append(r_data[i]); rows.append(g_data[i]); rows.append(128)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


def test_vectorised_png_matches_reference():
    rng = np.random.default_rng(7)
    w, h = 37, 11
    r = rng.integers(0, 256, w * h, dtype=np.uint8).tobytes()
    g = rng.integers(0, 256, w * h, dtype=np.uint8).tobytes()
    assert _encode_png(w, h, r, g) == _reference(w, h, r, g)


import asyncio

import pytest

from app.routers import data_sources as ds


async def test_cold_requests_queue_behind_a_running_refresh(monkeypatch):
    ds._cache.update({"png_bytes": None, "metadata": None, "generated_at": 0.0})
    calls = []

    def slow_refresh():
        calls.append(1)
        import time as _t; _t.sleep(0.2)
        ds._cache.update({"png_bytes": b"png", "metadata": {"ok": True}, "generated_at": __import__("time").time()})
    monkeypatch.setattr(ds, "_refresh_cache", slow_refresh)
    # warm-up and two concurrent requests: one refresh, every caller sees the bytes
    await asyncio.gather(ds.warm_wind_cache(), ds._ensure_cache(), ds._ensure_cache())
    assert calls == [1] and ds._cache["png_bytes"] == b"png"


async def test_cold_request_fails_loudly_when_refresh_fails(monkeypatch):
    ds._cache.update({"png_bytes": None, "metadata": None, "generated_at": 0.0})
    def boom():
        raise RuntimeError("s3 down")
    monkeypatch.setattr(ds, "_refresh_cache", boom)
    with pytest.raises(Exception):
        await ds._ensure_cache()
