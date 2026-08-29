#!/usr/bin/env python3
"""
Regenerate every raster brand asset from the vector mark in ``logo.svg``.

    python3 assets/brand/generate_assets.py

The mark is redrawn with Pillow using exactly the geometry described in
``logo.svg`` (4x supersampled, then downsampled) so the PNGs and the SVG always
agree.  Outputs:

* ``assets/brand/icon-*.png``     - square app icons
* ``assets/brand/preview.png``    - marketing preview card
* ``app/static/img/icon-*.png``   - icons served by the web UI
* ``android/app/src/main/res/mipmap-*/ic_launcher.png`` - Android launcher icons
"""

from __future__ import annotations

import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:                                   # pragma: no cover
    sys.exit("Pillow is required: pip install Pillow")

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(ROOT))

SUPERSAMPLE = 4
GRADIENT = ((0x63, 0x66, 0xF1), (0x4F, 0x46, 0xE5), (0x06, 0xB6, 0xD4))

ANDROID_DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


GRADIENT_SEED = 96          # small enough to compute pixel by pixel


def _gradient_tile(size: int) -> Image.Image:
    """Diagonal three-stop gradient, same stops as the SVG ``#brand``.

    Built once at a small resolution and then upscaled - a per-pixel Python
    loop over a 4096x4096 canvas would take minutes.
    """
    top, mid, bottom = GRADIENT
    seed = Image.new("RGB", (GRADIENT_SEED, GRADIENT_SEED))
    pixels = seed.load()
    span = 2 * (GRADIENT_SEED - 1) or 1
    for y in range(GRADIENT_SEED):
        for x in range(GRADIENT_SEED):
            t = (x + y) / span
            if t < 0.55:
                pixels[x, y] = _lerp(top, mid, t / 0.55)
            else:
                pixels[x, y] = _lerp(mid, bottom, (t - 0.55) / 0.45)
    if size == GRADIENT_SEED:
        return seed
    return seed.resize((size, size), Image.BICUBIC)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def render(size: int, corner_ratio: float = 112 / 512) -> Image.Image:
    """Render the launcher icon at ``size`` pixels."""
    big = size * SUPERSAMPLE
    tile = _gradient_tile(big).convert("RGBA")
    mask = _rounded_mask(big, int(big * corner_ratio))
    tile.putalpha(mask)

    draw = ImageDraw.Draw(tile)
    s = big / 512.0
    hexagon = [(424, 256), (340, 401.5), (172, 401.5), (88, 256),
               (172, 110.5), (340, 110.5)]
    draw.line([(x * s, y * s) for x, y in hexagon] + [(hexagon[0][0] * s,
                                                       hexagon[0][1] * s)],
              fill=(255, 255, 255, 242), width=max(1, int(26 * s)), joint="curve")

    stroke = max(1, int(26 * s))
    draw.line([(206 * s, 204 * s), (162 * s, 256 * s), (206 * s, 308 * s)],
              fill=(255, 255, 255, 255), width=stroke, joint="curve")
    draw.line([(306 * s, 204 * s), (350 * s, 256 * s), (306 * s, 308 * s)],
              fill=(255, 255, 255, 255), width=stroke, joint="curve")
    draw.line([(280 * s, 192 * s), (232 * s, 320 * s)],
              fill=(255, 255, 255, 255), width=stroke)

    return tile.resize((size, size), Image.LANCZOS)


def render_preview(width: int = 1200, height: int = 630) -> Image.Image:
    """Open-Graph style card: dark background, the mark, and the product name."""
    image = Image.new("RGB", (width, height), (11, 14, 26))
    glow = Image.new("RGB", (width, height), (11, 14, 26))
    draw_glow = ImageDraw.Draw(glow)
    draw_glow.ellipse([width * 0.55, -height * 0.55, width * 1.25, height * 0.75],
                      fill=(31, 34, 74))
    draw_glow.ellipse([-width * 0.25, height * 0.35, width * 0.35, height * 1.45],
                      fill=(9, 42, 58))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    image = Image.blend(image, glow, 0.85)

    icon = render(300)
    image.paste(icon, (86, (height - 300) // 2), icon)
    return image


def _write(image: Image.Image, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path, "PNG")
    print("  wrote %s (%dx%d)" % (os.path.relpath(path, REPO), image.width, image.height))


def main() -> None:
    print("Rendering brand assets...")
    for size in (16, 32, 48, 64, 128, 192, 256, 512, 1024):
        _write(render(size), os.path.join(ROOT, "icon-%d.png" % size))
    _write(render_preview(), os.path.join(ROOT, "preview.png"))

    for size in (32, 192, 512):
        _write(render(size),
               os.path.join(REPO, "app", "static", "img", "icon-%d.png" % size))
    _write(render(192),
           os.path.join(REPO, "android", "app", "src", "main", "res",
                        "drawable-nodpi", "ic_launcher_foreground.png"))
    for folder, size in ANDROID_DENSITIES.items():
        base = os.path.join(REPO, "android", "app", "src", "main", "res", folder)
        icon = render(size)
        _write(icon, os.path.join(base, "ic_launcher.png"))
        _write(icon, os.path.join(base, "ic_launcher_round.png"))
    print("Done.")


if __name__ == "__main__":
    main()
