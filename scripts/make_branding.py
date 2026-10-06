#!/usr/bin/env python3
"""Generates the Digital Village launcher icon and splash assets.

The mark is drawn from primitives rather than shipped as a binary blob so it can
be reviewed, tweaked and regenerated: a green field, a thick stem, two leaves and
a soil arc. The same master is resampled for every Android density.

Usage:
    python3 scripts/make_branding.py            # writes into mobile/flutter_app

Outputs (all under mobile/flutter_app/):
    android/app/src/main/res/mipmap-*/ic_launcher.png          legacy icon
    android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml adaptive icon
    android/app/src/main/res/drawable-nodpi/splash_logo.png    launch screen mark
    android/app/src/main/res/values/ic_launcher_background.xml adaptive background
    assets/branding/app_icon.png                               in-app logo (Flutter)

Android's adaptive icon wants the mark inside the middle 66% of the 108dp canvas
(the rest is masked away by the launcher), so the foreground is drawn with a
generous margin and the background is a flat colour layer.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "mobile" / "flutter_app"
RES = APP / "android" / "app" / "src" / "main" / "res"

FIELD = (46, 110, 63, 255)  # #2E6E3F — the Material seed colour used by the theme
WHITE = (255, 255, 255, 255)

MASTER = 1024
# Launcher densities: name -> (legacy px, adaptive foreground px)
DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}
ADAPTIVE_DP = 108  # foreground canvas is 108dp; mdpi scale is 1px per dp


def _leaf(size: int, length: float, width: float, angle_deg: float) -> Image.Image:
    """One leaf: an ellipse rotated about its base, so it grows from the stem."""
    pad = int(size * 0.5)
    tile = Image.new("RGBA", (pad * 2, pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    # Draw the leaf pointing up, its base at the centre of the tile.
    ellipse_w = int(width)
    ellipse_h = int(length)
    box = (
        pad - ellipse_w // 2,
        pad - ellipse_h,
        pad + ellipse_w // 2,
        pad,
    )
    draw.ellipse(box, fill=WHITE)
    return tile.rotate(angle_deg, resample=Image.BICUBIC, center=(pad, pad))


def draw_mark(size: int, *, scale: float = 1.0, background: tuple[int, int, int, int] | None = FIELD) -> Image.Image:
    """The seed-and-soil mark. `scale` shrinks the artwork inside the canvas."""
    image = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    unit = size * scale
    cx = size / 2
    # Baseline: the soil sits low, the leaves fill the upper two thirds.
    base_y = size * 0.5 + unit * 0.30
    stem_w = unit * 0.075
    stem_top = base_y - unit * 0.42

    # Stem: rounded, slightly tapered by drawing two overlapping rounded bars.
    draw.rounded_rectangle(
        (cx - stem_w / 2, stem_top, cx + stem_w / 2, base_y),
        radius=stem_w / 2,
        fill=WHITE,
    )

    # Leaves: length 0.34 * unit, width 0.21 * unit, angled away from the stem.
    leaf_len = unit * 0.34
    leaf_w = unit * 0.21
    for angle in (-52, 52):
        leaf = _leaf(size, leaf_len, leaf_w, angle)
        # Attach each leaf at the top of the stem.
        tile_half = leaf.width // 2
        image.alpha_composite(
            leaf,
            (int(cx - tile_half), int(stem_top - tile_half + leaf_len * 0.18)),
        )

    # Soil: a thick arc under the stem, from 200° to 340°.
    soil_w = unit * 0.085
    soil_r = unit * 0.26
    soil_cy = base_y + soil_r * 0.62
    draw.arc(
        (cx - soil_r, soil_cy - soil_r, cx + soil_r, soil_cy + soil_r),
        start=200,
        end=340,
        fill=WHITE,
        width=int(soil_w),
    )
    return image


def _rounded_field(size: int) -> Image.Image:
    """Legacy icon: a flat square. Launchers mask it themselves."""
    return Image.new("RGBA", (size, size), FIELD)


def write_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    print(f"  {path.relative_to(REPO)}  {image.width}x{image.height}")


def main() -> int:
    print("launcher icons")
    for folder, px in DENSITIES.items():
        legacy = _rounded_field(MASTER).copy()
        legacy.alpha_composite(draw_mark(MASTER, scale=0.62, background=None))
        write_png(legacy.resize((px, px), Image.LANCZOS), RES / folder / "ic_launcher.png")

        # Adaptive foreground: transparent, artwork inside the safe zone.
        fg_px = int(px * ADAPTIVE_DP / 48)
        foreground = draw_mark(MASTER, scale=0.44, background=None)
        write_png(
            foreground.resize((fg_px, fg_px), Image.LANCZOS),
            RES / folder / "ic_launcher_foreground.png",
        )

    write_png(draw_mark(MASTER, scale=0.62), APP / "assets" / "branding" / "app_icon.png")
    write_png(
        draw_mark(MASTER, scale=0.5, background=None),
        RES / "drawable-nodpi" / "splash_logo.png",
    )

    print("adaptive icon xml")
    xml_dir = RES / "mipmap-anydpi-v26"
    xml_dir.mkdir(parents=True, exist_ok=True)
    (xml_dir / "ic_launcher.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/ic_launcher_background"/>\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
        "</adaptive-icon>\n"
    )
    values = RES / "values" / "ic_launcher_background.xml"
    values.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<resources>\n"
        '    <color name="ic_launcher_background">#2E6E3F</color>\n'
        "</resources>\n"
    )
    print(f"  {xml_dir.relative_to(REPO)}/ic_launcher.xml")
    print(f"  {values.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
