#!/usr/bin/env python3
"""
Regenerate every icon the *web studio* serves.

    python3 app/make_icons.py

The mark is the hexagon + ``</>`` glyph of ``assets/brand/logo.svg`` redrawn with
Pillow (4x supersampled, then downsampled) so the vector and the rasters always
agree.  Two optical sizes are produced: from 64 px up the full hexagon is drawn,
below that only the code glyph, which is the only part that still reads at
favicon size.

Outputs (all inside ``app/static/``):

* ``img/logo.svg``             - the vector mark used as the favicon + brand logo
* ``img/icon-{32,192,512}.png``- PWA / og:image icons
* ``img/apple-touch-icon.png`` - 180 px iOS home-screen icon
* ``img/favicon.ico``          - 16 / 32 / 48 px multi-resolution ICO
* ``site.webmanifest``         - installable-app manifest

Nothing outside ``app/`` is touched.
"""

from __future__ import annotations

import os

try:
    from PIL import Image, ImageDraw
except ImportError:                                   # pragma: no cover
    raise SystemExit("Pillow is required: pip install Pillow")

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "static", "img")
SUPERSAMPLE = 4
CORNER = 116 / 512.0

# Same three stops as assets/brand/logo.svg, with a lighter head for contrast.
STOPS = ((0x81, 0x8C, 0xF8), (0x4F, 0x46, 0xE5), (0x06, 0xB6, 0xD4))
SEED = 96


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(size: int) -> Image.Image:
    """Diagonal three-stop gradient, built small then upscaled."""
    head, mid, tail = STOPS
    seed = Image.new("RGB", (SEED, SEED))
    px = seed.load()
    span = 2 * (SEED - 1) or 1
    for y in range(SEED):
        for x in range(SEED):
            t = (x + y) / span
            px[x, y] = _lerp(head, mid, t / 0.45) if t < 0.45 \
                else _lerp(mid, tail, (t - 0.45) / 0.55)
    return seed if size == SEED else seed.resize((size, size), Image.BICUBIC)


def _mask(size: int, radius: int) -> Image.Image:
    out = Image.new("L", (size, size), 0)
    ImageDraw.Draw(out).rounded_rectangle([0, 0, size - 1, size - 1],
                                          radius=radius, fill=255)
    return out


def render(size: int, pad: float = 0.0, rounded: bool = True,
           circle: bool = False) -> Image.Image:
    """Render the app icon at ``size`` px.  ``pad`` shrinks the mark (maskable),
    ``rounded=False`` keeps the gradient full-bleed, ``circle=True`` makes a
    round launcher badge."""
    big = max(1, int(size * SUPERSAMPLE))
    tile = _gradient(big).convert("RGBA")
    if rounded or circle:
        radius = big // 2 if circle else int(big * CORNER)
        tile.putalpha(_mask(big, radius))
    draw = ImageDraw.Draw(tile)

    s = big / 512.0
    inset = 1.0 - pad
    cx = 256.0

    def p(x, y):
        return ((cx + (x - cx) * inset) * s, (256 + (y - 256) * inset) * s)

    if size >= 64:                       # full mark: hexagon + </>
        hexa = [(256, 92), (398, 174), (398, 338), (256, 420), (114, 338), (114, 174)]
        pts = [p(x, y) for x, y in hexa]
        draw.line(pts + [pts[0]], fill=(255, 255, 255, 235),
                  width=max(1, int(30 * inset * s)), joint="curve")
        w = max(1, int(34 * inset * s))
    else:                                # favicon size: glyph only, thicker
        w = max(2, int(58 * inset * s))

    glyph = [((214, 208), (162, 256), (214, 304)),
             ((298, 208), (350, 256), (298, 304))]
    for stroke in glyph:
        draw.line([p(x, y) for x, y in stroke], fill=(255, 255, 255, 255),
                  width=w, joint="curve")
    draw.line([p(278, 194), p(234, 318)], fill=(255, 255, 255, 255), width=w)
    return tile.resize((size, size), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" role="img" aria-label="IL2CPP Dumper Studio">
  <defs>
    <linearGradient id="g" x1="60" y1="40" x2="452" y2="472" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#818CF8"/><stop offset=".45" stop-color="#4F46E5"/><stop offset="1" stop-color="#06B6D4"/>
    </linearGradient>
    <linearGradient id="s" x1="0" y1="0" x2="0" y2="512" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="116" fill="url(#g)"/>
  <rect width="512" height="512" rx="116" fill="url(#s)"/>
  <path d="M256 92 398 174v164L256 420 114 338V174z" fill="none" stroke="#fff" stroke-opacity=".92" stroke-width="30" stroke-linejoin="round"/>
  <g fill="none" stroke="#fff" stroke-width="34" stroke-linecap="round" stroke-linejoin="round">
    <path d="M214 208 162 256l52 48"/><path d="M298 208 350 256l-52 48"/><path d="M278 194 234 318"/>
  </g>
</svg>
"""

MANIFEST = """{
  "name": "IL2CPP Dumper Studio",
  "short_name": "IL2CPP Studio",
  "description": "Turn a Unity Android APK into readable C# - 100% local.",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#070a14",
  "theme_color": "#070a14",
  "developer": "Mohamed Annati",
  "icons": [
    { "src": "/static/img/icon-32.png",  "sizes": "32x32",   "type": "image/png" },
    { "src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/static/img/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
"""


def _shrink(image: Image.Image, colors: int = 256) -> Image.Image:
    """Palette-quantise: the mark is a flat gradient, so this is near-lossless
    to the eye but cuts the 512 px icon from ~62 KB to ~11 KB."""
    return image.quantize(colors=colors, method=Image.FASTOCTREE,
                          dither=Image.FLOYDSTEINBERG)


def _write(image: Image.Image, name: str) -> int:
    os.makedirs(IMG, exist_ok=True)
    path = os.path.join(IMG, name)
    _shrink(image).save(path, optimize=True)
    print("  wrote app/static/img/%s (%dx%d, %d B)"
          % (name, image.width, image.height, os.path.getsize(path)))
    return os.path.getsize(path)


REPO = os.path.dirname(HERE)
ANDROID_RES = os.path.join(REPO, "android", "app", "src", "main", "res")
ANDROID_DENSITIES = {"mipmap-mdpi": 48, "mipmap-hdpi": 72, "mipmap-xhdpi": 96,
                     "mipmap-xxhdpi": 144, "mipmap-xxxhdpi": 192}

ANDROID_LOGO_XML = """<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="48dp"
    android:height="48dp"
    android:viewportWidth="512"
    android:viewportHeight="512">
    <path
        android:pathData="M256,92 L398,174 L398,338 L256,420 L114,338 L114,174 Z"
        android:strokeColor="#FFFFFF"
        android:strokeWidth="30"
        android:strokeLineJoin="round"
        android:fillColor="#00000000" />
    <path
        android:pathData="M214,208 L162,256 L214,304 M298,208 L350,256 L298,304 M278,194 L234,318"
        android:strokeColor="#FFFFFF"
        android:strokeWidth="34"
        android:strokeLineCap="round"
        android:strokeLineJoin="round"
        android:fillColor="#00000000" />
</vector>
"""


def android() -> int:
    """Regenerate the Android launcher icons with the same mark as the web."""
    total = 0
    for folder, size in ANDROID_DENSITIES.items():
        base = os.path.join(ANDROID_RES, folder)
        os.makedirs(base, exist_ok=True)
        for name, circle in (("ic_launcher.png", False),
                             ("ic_launcher_round.png", True)):
            path = os.path.join(base, name)
            _shrink(render(size, circle=circle)).save(path, optimize=True)
            total += os.path.getsize(path)
    fg = os.path.join(ANDROID_RES, "drawable-nodpi", "ic_launcher_foreground.png")
    os.makedirs(os.path.dirname(fg), exist_ok=True)
    _shrink(render(192)).save(fg, optimize=True)
    total += os.path.getsize(fg)
    logo = os.path.join(ANDROID_RES, "drawable", "ic_logo.xml")
    with open(logo, "w", encoding="utf-8") as handle:
        handle.write(ANDROID_LOGO_XML)
    total += os.path.getsize(logo)
    print("  regenerated Android launcher icons (%d B)" % total)
    return total


def main() -> None:
    print("Rendering web studio icons...")
    total = 0
    for size in (32, 192, 512):
        total += _write(render(size), "icon-%d.png" % size)
    total += _write(render(180), "apple-touch-icon.png")
    total += _write(render(512, pad=0.30, rounded=False), "maskable-512.png")

    # multi-resolution .ico (16 / 32 / 48) - Pillow resizes from the source
    ico = os.path.join(IMG, "favicon.ico")
    render(48).save(ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    total += os.path.getsize(ico)
    with Image.open(ico) as probe:
        print("  wrote app/static/img/favicon.ico (%d B, entries: %s)"
              % (os.path.getsize(ico), sorted(probe.info.get("sizes", ()))))

    for name, body in (("logo.svg", SVG), ):
        path = os.path.join(IMG, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        total += os.path.getsize(path)
        print("  wrote app/static/img/%s (%d B)" % (name, os.path.getsize(path)))

    manifest = os.path.join(HERE, "static", "site.webmanifest")
    with open(manifest, "w", encoding="utf-8") as handle:
        handle.write(MANIFEST)
    total += os.path.getsize(manifest)
    print("  wrote app/static/site.webmanifest (%d B)" % os.path.getsize(manifest))
    print("Done - app/static/img + manifest total: %d B" % total)
    android()


if __name__ == "__main__":
    main()
