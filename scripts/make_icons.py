"""Generate the PWA icons (concentric rings on near-black) with no third-party imaging library.

python scripts/make_icons.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "icons"
BG = (5, 5, 5)
FG = (236, 236, 236)


def png(size: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + pixels[y * size * 3 : (y + 1) * size * 3] for y in range(size))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def draw(size: int, scale: float) -> bytes:
    """Rings whose outer radius is ``scale`` of the half-size (smaller for maskable icons)."""
    half = size / 2
    rings = [(1.0, 0.045), (0.78, 0.035), (0.56, 0.03), (0.32, 0.09)]  # (radius, thickness)
    out = bytearray()
    for y in range(size):
        for x in range(size):
            distance = math.hypot(x + 0.5 - half, y + 0.5 - half) / (half * scale)
            coverage = 0.0
            for radius, thickness in rings:
                edge = abs(distance - radius) - thickness
                coverage = max(coverage, min(max(0.5 - edge * half * scale, 0.0), 1.0))
            out += bytes(round(BG[i] + (FG[i] - BG[i]) * coverage) for i in range(3))
    return png(size, bytes(out))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon-192.png").write_bytes(draw(192, 0.82))
    (OUT / "icon-512.png").write_bytes(draw(512, 0.82))
    (OUT / "icon-maskable-512.png").write_bytes(
        draw(512, 0.6)
    )  # keeps the art inside the safe zone
    (OUT / "apple-touch-icon.png").write_bytes(draw(180, 0.82))
    (OUT / "favicon-32.png").write_bytes(draw(32, 0.9))
    print("wrote icons to", OUT)


if __name__ == "__main__":
    main()
