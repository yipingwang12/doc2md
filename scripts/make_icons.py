#!/usr/bin/env python3
"""Generate .icns icons for doc2md Reader and Global Geo Atlas."""

import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

PROJECTS = Path(__file__).resolve().parent

# ICNS type codes that accept raw PNG payloads (macOS 10.7+)
_ICNS_TYPES = [
    (16,   b"icp4"),
    (32,   b"icp5"),
    (64,   b"icp6"),
    (128,  b"ic07"),
    (256,  b"ic08"),
    (512,  b"ic09"),
    (1024, b"ic10"),
]


def _write_icns(img: Image.Image, path: Path) -> None:
    """Write ICNS directly — avoids iconutil sandbox restrictions."""
    chunks = []
    for size, code in _ICNS_TYPES:
        buf = io.BytesIO()
        img.resize((size, size), Image.LANCZOS).save(buf, format="PNG")
        data = buf.getvalue()
        chunks.append(code + struct.pack(">I", len(data) + 8) + data)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def _iconset_and_icns(img: Image.Image, name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    icns = out_dir / f"{name}.icns"
    _write_icns(img, icns)
    return icns


def draw_doc2md_icon(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background — deep navy
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=(22, 40, 74))

    # Document page with corner fold
    fold = int(size * 0.17)
    px1, py1 = int(size * 0.22), int(size * 0.14)
    px2, py2 = int(size * 0.78), int(size * 0.86)

    draw.polygon(
        [(px1, py1), (px2 - fold, py1), (px2, py1 + fold), (px2, py2), (px1, py2)],
        fill=(232, 238, 255),
    )
    draw.polygon(
        [(px2 - fold, py1), (px2, py1 + fold), (px2 - fold, py1 + fold)],
        fill=(185, 198, 228),
    )

    # Text lines
    lc = (160, 175, 210)
    lx1, lx2 = int(px1 + size * 0.09), int(px2 - size * 0.11)
    ly = int(py1 + size * 0.21)
    lh = int(size * 0.038)
    step = int(size * 0.095)
    for i in range(5):
        x2 = lx1 + int((lx2 - lx1) * (0.52 if i == 4 else 1.0))
        draw.rounded_rectangle([lx1, ly, x2, ly + lh], radius=lh // 2, fill=lc)
        ly += step

    # Teal arrow → at bottom of page
    ac = (72, 199, 168)
    ax = int(px1 + size * 0.09)
    ay = int(py2 - size * 0.135)
    aw, ah = int(size * 0.15), int(size * 0.058)
    shaft_h = int(ah * 0.38)
    draw.rectangle([ax, ay - shaft_h, ax + int(aw * 0.6), ay + shaft_h], fill=ac)
    draw.polygon(
        [(ax + int(aw * 0.54), ay - ah), (ax + aw, ay), (ax + int(aw * 0.54), ay + ah)],
        fill=ac,
    )

    return img


def draw_atlas_icon(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background — near-black matching splash screen
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=(13, 17, 23))

    cx, cy = size // 2, size // 2
    r = int(size * 0.38)
    blue = (88, 166, 255)  # #58a6ff — matches splash spinner
    lw = max(2, size // 100)

    # Draw lat/lon grid on separate layer, then mask to globe circle
    grid = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid)

    # Latitude lines — horizontal ellipses with perspective compression
    depth = 0.32
    for lat_deg in [-55, -28, 0, 28, 55]:
        lat = math.radians(lat_deg)
        rx = int(r * math.cos(lat))
        ry = int(rx * depth)
        y = int(cy + r * math.sin(lat))
        if rx > 4:
            gdraw.ellipse([cx - rx, y - ry, cx + rx, y + ry], outline=blue, width=lw)

    # Longitude lines — vertical ellipses
    for lon_deg in [-60, -30, 30, 60]:
        lon = math.radians(lon_deg)
        rx = int(r * abs(math.sin(lon)))
        if rx > 4:
            gdraw.ellipse([cx - rx, cy - r, cx + rx, cy + r], outline=blue, width=lw)
    # Prime meridian as straight line
    gdraw.line([cx, cy - r, cx, cy + r], fill=blue, width=lw)

    # Mask grid to globe circle
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    clipped.paste(grid, mask=mask)
    img.alpha_composite(clipped)

    # Globe outline — drawn last, on top
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=blue, width=lw * 2)

    return img


if __name__ == "__main__":
    doc2md_icns = _iconset_and_icns(
        draw_doc2md_icon(),
        "doc2md-reader",
        PROJECTS / "doc2md" / "assets",
    )
    print(f"Created {doc2md_icns}")

    atlas_icns = _iconset_and_icns(
        draw_atlas_icon(),
        "global-geo-atlas",
        PROJECTS / "global-geo-atlas" / "assets",
    )
    print(f"Created {atlas_icns}")
