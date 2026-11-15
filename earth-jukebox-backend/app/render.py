"""Pillow ile gorsel uretimi: API'nin dondurdugu her sey bir gorsel.

Sayfadaki ornekler: "Animated Web Map with WMS" (tarih yazili GIF kareleri),
"Overlaying" (Image.blend / alpha bindirme), "Visualize WMS Raster Data with a Legend".
"""
import io
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BG = (17, 22, 30)  # veri olmayan alanlarin rengi (koyu lacivert)
PANEL = (28, 35, 46)
TEXT = (235, 240, 245)
MUTED = (150, 162, 178)
ACCENT = (96, 165, 250)
ERROR = (248, 113, 113)

# Fark haritasi: mavi (azaldi) -> beyaz (degisim yok) -> kirmizi (artti)
DIFF_NEG = np.array([33, 102, 172], dtype=np.float32)
DIFF_ZERO = np.array([247, 247, 247], dtype=np.float32)
DIFF_POS = np.array([178, 24, 43], dtype=np.float32)


@lru_cache(maxsize=16)
def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # cok eski Pillow
        return ImageFont.load_default()


def font_size(f) -> int:
    return int(getattr(f, "size", 12))


def text_width(draw: ImageDraw.ImageDraw, text: str, f) -> int:
    return int(draw.textlength(text, font=f))


def fit_text(draw, text: str, f, max_w: int) -> str:
    if text_width(draw, text, f) <= max_w:
        return text
    while text and text_width(draw, text + "…", f) > max_w:
        text = text[:-1]
    return text + "…"


def open_rgba(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


def flatten(img: Image.Image, bg=BG) -> Image.Image:
    """Seffaf (veri yok) alanlari koyu zemine oturtur."""
    base = Image.new("RGBA", img.size, bg + (255,))
    base.alpha_composite(img.convert("RGBA"))
    return base.convert("RGB")


def overlay(img: Image.Image, top: Image.Image | None) -> Image.Image:
    """Kiyi cizgisi gibi seffaf bir katmani ustune bindirir."""
    if top is None:
        return img
    out = img.convert("RGBA")
    layer = top.convert("RGBA")
    if layer.size != out.size:
        layer = layer.resize(out.size, Image.BILINEAR)
    out.alpha_composite(layer)
    return out


def with_header(img: Image.Image, title: str, subtitle: str = "", right: str = "") -> Image.Image:
    w = img.width
    scale = max(0.6, min(1.4, w / 1024))
    tf, sf = font(round(22 * scale), True), font(round(14 * scale))
    h = round(62 * scale) if subtitle else round(40 * scale)
    out = Image.new("RGB", (w, img.height + h), PANEL)
    out.paste(img.convert("RGB"), (0, h))
    d = ImageDraw.Draw(out)
    pad = round(12 * scale)
    right_w = text_width(d, right, tf) + pad if right else 0
    d.text((pad, round(7 * scale)), fit_text(d, title, tf, w - 2 * pad - right_w), font=tf, fill=TEXT)
    if right:
        d.text((w - pad - text_width(d, right, tf), round(7 * scale)), right, font=tf, fill=ACCENT)
    if subtitle:
        d.text((pad, round(36 * scale)), fit_text(d, subtitle, sf, w - 2 * pad), font=sf, fill=MUTED)
    return out


def with_footer(img: Image.Image, legend=None, note: str = "") -> Image.Image:
    """Altina GIBS lejanti / renk cubugu (tek ya da liste) ve aciklama satiri ekler."""
    legends = [x for x in (legend if isinstance(legend, list) else [legend]) if x is not None]
    if not legends and not note:
        return img
    w = img.width
    parts = []
    for item in legends:
        leg = flatten(item, (255, 255, 255))
        max_w, max_h = w - 24, 90
        ratio = min(max_w / leg.width, max_h / leg.height, 1.5)
        leg = leg.resize((max(1, round(leg.width * ratio)), max(1, round(leg.height * ratio))), Image.LANCZOS)
        parts.append(leg)
    nf = font(max(11, round(13 * w / 1024)))
    note_h = (font_size(nf) + 12) if note else 0
    h = sum(p.height + 10 for p in parts) + note_h + 6
    out = Image.new("RGB", (w, img.height + h), PANEL)
    out.paste(img.convert("RGB"), (0, 0))
    y = img.height + 8
    for p in parts:
        bg = Image.new("RGB", (p.width + 12, p.height + 6), (255, 255, 255))
        bg.paste(p, (6, 3))
        out.paste(bg, ((w - bg.width) // 2, y))
        y += p.height + 10
    if note:
        d = ImageDraw.Draw(out)
        d.text((12, y), fit_text(d, note, nf, w - 24), font=nf, fill=MUTED)
    return out


def progress_bar(img: Image.Image, i: int, n: int) -> Image.Image:
    if n <= 1:
        return img
    d = ImageDraw.Draw(img)
    h = max(4, img.height // 120)
    d.rectangle([0, img.height - h, img.width, img.height], fill=(50, 60, 75))
    d.rectangle([0, img.height - h, round(img.width * (i + 1) / n), img.height], fill=ACCENT)
    return img


def diff_rgba(va: np.ndarray, valid_a: np.ndarray, vb: np.ndarray, valid_b: np.ndarray):
    """Iki deger matrisinin farki -> (RGBA goruntu, olcek, ortalama fark, gecerli oran)."""
    both = valid_a & valid_b
    d = np.where(both, vb - va, 0.0)
    if both.any():
        scale = float(np.percentile(np.abs(d[both]), 98))
        mean = float(d[both].mean())
    else:
        scale, mean = 0.0, 0.0
    scale = scale if scale > 1e-6 else 1e-6
    t = np.clip(d / scale, -1.0, 1.0)[..., None]
    rgb = np.where(t >= 0, DIFF_ZERO + (DIFF_POS - DIFF_ZERO) * t, DIFF_ZERO + (DIFF_NEG - DIFF_ZERO) * (-t))
    alpha = np.where(both, 255, 0)[..., None]
    arr = np.concatenate([rgb, alpha], axis=-1).astype(np.uint8)
    return Image.fromarray(arr, "RGBA"), scale, mean, float(both.mean())


def diff_colorbar(width: int, left: str, mid: str, right: str) -> Image.Image:
    bar_w, bar_h = min(520, width - 40), 16
    t = np.linspace(-1, 1, bar_w)[None, :, None]
    rgb = np.where(t >= 0, DIFF_ZERO + (DIFF_POS - DIFF_ZERO) * t, DIFF_ZERO + (DIFF_NEG - DIFF_ZERO) * (-t))
    bar = Image.fromarray(np.repeat(rgb, bar_h, axis=0).astype(np.uint8), "RGB")
    f = font(13)
    out = Image.new("RGB", (bar_w, bar_h + 22), (255, 255, 255))
    out.paste(bar, (0, 0))
    d = ImageDraw.Draw(out)
    d.text((0, bar_h + 3), left, font=f, fill=(40, 40, 40))
    d.text(((bar_w - text_width(d, mid, f)) // 2, bar_h + 3), mid, font=f, fill=(40, 40, 40))
    d.text((bar_w - text_width(d, right, f), bar_h + 3), right, font=f, fill=(40, 40, 40))
    return out.convert("RGBA")


def side_by_side(panels: list[Image.Image], gap: int = 8) -> Image.Image:
    h = max(p.height for p in panels)
    w = sum(p.width for p in panels) + gap * (len(panels) - 1)
    out = Image.new("RGB", (w, h), BG)
    x = 0
    for p in panels:
        out.paste(p.convert("RGB"), (x, 0))
        x += p.width + gap
    return out


def grid(panels: list[Image.Image], cols: int, gap: int = 8) -> Image.Image:
    cw = max(p.width for p in panels)
    ch = max(p.height for p in panels)
    rows = (len(panels) + cols - 1) // cols
    out = Image.new("RGB", (cols * cw + gap * (cols - 1), rows * ch + gap * (rows - 1)), BG)
    for i, p in enumerate(panels):
        r, c = divmod(i, cols)
        out.paste(p.convert("RGB"), (c * (cw + gap), r * (ch + gap)))
    return out


def resize_w(img: Image.Image, width: int) -> Image.Image:
    if img.width == width:
        return img
    return img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)


def message_panel(size: tuple[int, int], title: str, message: str, color=ERROR) -> Image.Image:
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)
    tf, mf = font(20, True), font(14)
    d.text((16, 16), title, font=tf, fill=color)
    y = 50
    for line in wrap(d, message, mf, size[0] - 32):
        d.text((16, y), line, font=mf, fill=TEXT)
        y += font_size(mf) + 6
        if y > size[1] - 20:
            break
    return img


def wrap(draw, text: str, f, max_w: int) -> list[str]:
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            test = f"{cur} {word}".strip()
            if text_width(draw, test, f) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def error_image(status: int, title: str, message: str) -> bytes:
    img = message_panel((900, 260), f"Hata {status}: {title}", message)
    return png_bytes(img)


def table_image(title: str, headers: list[str], rows: list[list[str]], widths: list[int]) -> Image.Image:
    hf, cf, tf = font(15, True), font(14), font(22, True)
    row_h = 30
    w = sum(widths) + 24
    h = 60 + row_h * (len(rows) + 1) + 12
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.text((12, 14), title, font=tf, fill=TEXT)
    y = 56
    d.rectangle([12, y, w - 12, y + row_h], fill=PANEL)
    x = 12
    for head, cw in zip(headers, widths):
        d.text((x + 8, y + 6), head, font=hf, fill=ACCENT)
        x += cw
    for i, row in enumerate(rows):
        y += row_h
        if i % 2:
            d.rectangle([12, y, w - 12, y + row_h], fill=(22, 28, 38))
        x = 12
        for cell, cw in zip(row, widths):
            color = ERROR if cell.startswith("YOK") or cell.startswith("HATA") else TEXT
            d.text((x + 8, y + 7), fit_text(d, cell, cf, cw - 14), font=cf, fill=color)
            x += cw
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def gif_bytes(frames: list[Image.Image], duration_ms: int = 900, hold_last_ms: int = 1800) -> bytes:
    """Sayfadaki 'Animated Web Map with WMS' ornegi gibi: kareler -> dongulu GIF."""
    pal = [f.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255) for f in frames]
    durations = [duration_ms] * len(pal)
    if durations:
        durations[-1] = hold_last_ms
    buf = io.BytesIO()
    pal[0].save(buf, format="GIF", save_all=True, append_images=pal[1:], duration=durations,
                loop=0, optimize=False, disposal=1)
    return buf.getvalue()
