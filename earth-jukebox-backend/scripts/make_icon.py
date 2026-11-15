"""Eratone uygulama ikonunu uretir: assets/eratone.ico (16-256 px) + assets/eratone.png (512 px).

Calistir:  python scripts/make_icon.py
Tasarim Eratone arayuzunun paletinden: koyu uzay zemini (#03050a/#091326), camgobegi dunya
(#38bdf8), mercan ses dalgasi (#fb7185). Ikon degisecekse bu dosyayi duzenle, tekrar calistir,
sonra build_eratone.ps1 ile exe'yi yeniden derle.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024  # cizim buyuklugu; sonra kucultulur (kenar yumusatma icin)
OUT = Path(__file__).resolve().parent.parent / "assets"

BG_TOP, BG_BOTTOM = (9, 19, 38), (3, 5, 10)
CYAN = (56, 189, 248)
EMBER = (251, 113, 133)


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def build() -> Image.Image:
    # zemin: dikey gradyan
    bg = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / (S - 1)
        d.line([(0, y), (S, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    cx = cy = S // 2
    r = int(S * 0.33)

    # dunya: ic dolgu + enlem/boylam cizgileri
    g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(14, 42, 74, 255))
    line = (*CYAN, 110)
    w = max(2, S // 140)
    for k in (-0.5, 0.0, 0.5):  # enlemler
        yy = cy + k * r
        half = math.sqrt(max(r * r - (yy - cy) ** 2, 0))
        g.line([(cx - half, yy), (cx + half, yy)], fill=line, width=w)
    for rx in (r * 0.45, r * 0.85):  # boylamlar (elips)
        g.ellipse([cx - rx, cy - r, cx + rx, cy + r], outline=line, width=w)
    g.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*CYAN, 255), width=max(4, S // 48))

    # ses dalgasi: dunyanin ortasindan gecen, uclara dogru sonen sinus
    pts = []
    x0, x1 = int(S * 0.12), int(S * 0.88)
    for x in range(x0, x1 + 1):
        t = (x - x0) / (x1 - x0)
        env = math.sin(math.pi * t) ** 1.4
        pts.append((x, cy + math.sin(t * math.pi * 5) * r * 0.42 * env))

    def stroke(img: Image.Image, width: int, fill) -> None:
        # Kalin cizgiyi yogun dairelerle ciz: ImageDraw.line kalin egride tirtikli kose birakiyor
        dr, h = ImageDraw.Draw(img), width / 2
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(xb - xa, yb - ya)))
            for i in range(n):
                x, y = xa + (xb - xa) * i / n, ya + (yb - ya) * i / n
                dr.ellipse([x - h, y - h, x + h, y + h], fill=fill)

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    stroke(glow, S // 22, (*EMBER, 160))
    layer = Image.alpha_composite(layer, glow.filter(ImageFilter.GaussianBlur(S // 60)))
    stroke(layer, S // 36, (*EMBER, 255))

    img = Image.alpha_composite(bg.convert("RGBA"), layer)
    img.putalpha(rounded_mask(S, int(S * 0.22)))
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = build()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "eratone.png")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    big.resize((256, 256), Image.LANCZOS).save(OUT / "eratone.ico", sizes=sizes)
    print(f"[OK] {OUT / 'eratone.ico'}  {OUT / 'eratone.png'}")
