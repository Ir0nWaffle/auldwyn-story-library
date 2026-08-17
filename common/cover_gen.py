"""Generates a story cover: either a template built around a player-posted
image, or a fully generated fallback when no image was posted. Both carry
the Auldwyn "A" watermark, title, and byline -- see the design discussion
this pipeline came out of."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
FONTS = ASSETS / "fonts"

W, H = 1600, 2400

_logo = Image.open(ASSETS / "auldwyn-logo.png").convert("RGBA")
_a_mark = Image.open(ASSETS / "auldwyn-A-mark.png").convert("RGBA")

_cinzel_decorative = ImageFont.truetype(str(FONTS / "CinzelDecorative-Bold.ttf"), 96)
_cinzel_title = ImageFont.truetype(str(FONTS / "Cinzel[wght].ttf"), 84)
_garamond_by = ImageFont.truetype(str(FONTS / "EBGaramond[wght].ttf"), 52)
_garamond_tag = ImageFont.truetype(str(FONTS / "EBGaramond[wght].ttf"), 40)

try:
    _cinzel_title.set_variation_by_axes([600])
    _garamond_by.set_variation_by_axes([500])
    _garamond_tag.set_variation_by_axes([450])
except Exception:
    pass


def _draw_wrapped(draw, text, font, center_x, top_y, max_width, fill, spacing=22):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    y = top_y
    for line in lines:
        lw = draw.textlength(line, font=font)
        draw.text((center_x - lw / 2, y), line, font=font, fill=fill)
        y += font.size + spacing
    return y


def _add_watermark(img: Image.Image, scale=0.14, margin=48, opacity=190) -> Image.Image:
    img = img.convert("RGBA")
    mark = _a_mark.copy()
    target_w = int(img.width * scale)
    ratio = target_w / mark.width
    mark = mark.resize((target_w, int(mark.height * ratio)), Image.LANCZOS)
    r, g, b, a = mark.split()
    a = a.point(lambda p: int(p * (opacity / 255)))
    mark.putalpha(a)
    pos = (img.width - mark.width - margin, img.height - mark.height - margin)
    img.alpha_composite(mark, pos)
    return img


def make_fallback_cover(title: str, author: str) -> bytes:
    """No player art posted -- fully generated cover."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    top, bottom = (18, 16, 28), (54, 40, 26)
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=(r, g, b, 255))

    draw = ImageDraw.Draw(img)
    lw = int(W * 0.62)
    logo = _logo.resize((lw, int(_logo.height * (lw / _logo.width))), Image.LANCZOS)
    img.alpha_composite(logo, ((W - lw) // 2, int(H * 0.10)))

    ty = _draw_wrapped(draw, title.upper(), _cinzel_title, W / 2, int(H * 0.42),
                        W * 0.8, fill=(232, 220, 198, 255))
    draw.text((W / 2, ty + 40), "an Auldwyn story", font=_garamond_tag,
               fill=(170, 150, 120, 255), anchor="ma")
    draw.text((W / 2, int(H * 0.86)), f"by {author}", font=_garamond_by,
               fill=(210, 195, 165, 255), anchor="ma")

    img = _add_watermark(img, scale=0.14, opacity=140)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def make_art_cover(title: str, author: str, image_bytes: bytes) -> bytes:
    """A player posted an image with their story -- use it as the base."""
    art = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    art = ImageOps.fit(art, (W, H), Image.LANCZOS, centering=(0.5, 0.4))
    img = art.convert("RGBA")

    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        t = y / H
        v = int(200 * (1 - t / 0.22)) if t < 0.22 else (
            int(230 * ((t - 0.68) / 0.32)) if t > 0.68 else 0)
        grad.putpixel((0, y), max(0, v))
    shade = Image.new("RGBA", (W, H), (10, 8, 6, 255))
    shade.putalpha(grad.resize((W, H)))
    img.alpha_composite(shade)

    draw = ImageDraw.Draw(img)
    ty = _draw_wrapped(draw, title.upper(), _cinzel_title, W / 2, int(H * 0.07),
                        W * 0.82, fill=(245, 238, 222, 255))
    draw.text((W / 2, ty + 10), "an Auldwyn story", font=_garamond_tag,
               fill=(225, 210, 180, 255), anchor="ma")
    draw.text((W / 2, int(H * 0.895)), f"by {author}", font=_garamond_by,
               fill=(245, 238, 222, 255), anchor="ma")

    img = _add_watermark(img, scale=0.13, opacity=210)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def make_cover(title: str, author: str, image_bytes: bytes | None) -> bytes:
    if image_bytes:
        try:
            return make_art_cover(title, author, image_bytes)
        except Exception:
            pass  # corrupt/unsupported image -- fall through to generated cover
    return make_fallback_cover(title, author)
