"""Generate AIE app icons from the brand mark (build-time only; Pillow is NOT a runtime dep).

Outputs:
  web/assets/logo.png   256px mark (pywebview window / web brand)
  aife/assets/icon.ico  multi-res .ico (native window + PyInstaller exe icon)

Run: python scripts/make_icon.py
"""
import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C1 = (43, 108, 176, 255)   # #2b6cb0
C2 = (107, 70, 193, 255)   # #6b46c1


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))


def make_mark(size: int) -> Image.Image:
    s = size * 8  # supersample for smooth downscale
    radius = int(s * 0.23)

    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = (y / s) * 0.7 + 0.15
        gd.line([(0, y), (s, y)], fill=_lerp(C1, C2, t))

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=255)

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    cx = cy = s / 2
    R, rr = s * 0.30, s * 0.125
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = R if i % 2 == 0 else rr
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=(255, 255, 255, 242))
    cr = s * 0.055
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=C1)
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(os.path.join(ROOT, "web", "assets"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "aife", "assets"), exist_ok=True)
    make_mark(256).save(os.path.join(ROOT, "web", "assets", "logo.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    make_mark(256).save(
        os.path.join(ROOT, "aife", "assets", "icon.ico"),
        sizes=[(s, s) for s in sizes],
    )
    print("icons written: web/assets/logo.png, aife/assets/icon.ico")


if __name__ == "__main__":
    main()
