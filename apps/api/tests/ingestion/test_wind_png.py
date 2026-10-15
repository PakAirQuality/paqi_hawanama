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
