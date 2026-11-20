"""
Draws Garbis's icons from the same parts as Face.tsx ( ⚆ _ ⚆ ), with icon-friendly proportions.  Run:  python3 scripts/make_icons.py
  resources/icon.png              1024px app icon (electron-builder makes .icns / .ico from it)
  resources/trayTemplate.png      macOS menu bar, black + alpha (macOS tints it for light/dark), 16px
  resources/trayTemplate@2x.png   same, 32px
  resources/tray.png              Windows/Linux tray, colored, 32px
Needs Pillow.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "resources"
BG = (30, 30, 47, 255)          # #1e1e2f
CYAN = (0, 204, 255, 255)       # #00ccff
SS = 4                          # supersampling for smooth edges


def render(size: int, draw_fn) -> Image.Image:
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(big), size * SS)
    return big.resize((size, size), Image.LANCZOS)


def ring_eye(d: ImageDraw.ImageDraw, cx, cy, r, stroke, color):
    """⚆: a ring with the pupil off to the right."""
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=round(stroke))
    pr = r * 0.32
    px = cx + r * 0.42
    d.ellipse((px - pr, cy - pr, px + pr, cy + pr), fill=color)


def app_icon(d: ImageDraw.ImageDraw, n: int):
    """Icons need chunkier proportions than the 500x130 window face: same parts, tighter and bolder."""
    pad = n * 0.09                                    # macOS-style margin around the rounded square
    d.rounded_rectangle((pad, pad, n - pad, n - pad), radius=n * 0.2, fill=BG)
    stroke = n * 0.034
    for x_tip, x_mid in ((0.25, 0.17), (0.75, 0.83)):  # ( and )
        pts = []
        for i in range(41):
            t = i / 40
            x = (1 - t) ** 2 * x_tip + 2 * (1 - t) * t * x_mid + t ** 2 * x_tip
            y = (1 - t) ** 2 * 0.34 + 2 * (1 - t) * t * 0.5 + t ** 2 * 0.66
            pts.append((x * n, y * n))
        d.line(pts, fill=CYAN, width=round(stroke * 1.3), joint="curve")
        for ex, ey in (pts[0], pts[-1]):
            r = stroke * 0.65
            d.ellipse((ex - r, ey - r, ex + r, ey + r), fill=CYAN)
    for cx in (0.385, 0.615):
        ring_eye(d, cx * n, 0.47 * n, 0.075 * n, stroke * 0.7, CYAN)
    d.line((0.455 * n, 0.6 * n, 0.545 * n, 0.6 * n), fill=CYAN, width=round(stroke))


def tray_icon(color):
    """Tray sizes are 16-32 px: just the eyes and the mouth, as big as they fit."""
    def draw(d: ImageDraw.ImageDraw, n: int):
        stroke = n * 0.1
        for cx in (0.27, 0.73):
            ring_eye(d, cx * n, 0.42 * n, 0.21 * n, stroke, color)
        d.line((0.36 * n, 0.84 * n, 0.64 * n, 0.84 * n), fill=color, width=round(stroke * 1.15))
    return draw


def main():
    OUT.mkdir(exist_ok=True)
    render(1024, app_icon).save(OUT / "icon.png")
    black = (0, 0, 0, 255)
    render(16, tray_icon(black)).save(OUT / "trayTemplate.png")
    render(32, tray_icon(black)).save(OUT / "trayTemplate@2x.png")
    render(32, tray_icon(CYAN)).save(OUT / "tray.png")
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
