"""
Thumbnail designer — four styles, all 1280×720 (YouTube's recommended size).

  impact     Huge outlined block letters over a darkened photo. Classic, loud.
  cinematic  Full-bleed photo, film letterbox, wide-tracked title at the bottom.
  split      Bold colour panel with the text, photo slashed in on an angle.
  studio     The raunakpatil.com look: dark card, light type, spectrum bars.

Text uses *stars* to mark the highlighted word, e.g. "Time *stops* here".
Keep it to 2–5 words; the video title already carries the rest.
"""
import colorsys
import math
import os
import re
import threading

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from video import fonts

W, H = 1280, 720

STYLES = {
    "impact":    {"name": "Impact",    "desc": "Huge outlined text, classic YouTube"},
    "cinematic": {"name": "Cinematic", "desc": "Full-bleed photo, film letterbox"},
    "split":     {"name": "Split",     "desc": "Bold colour panel + angled photo"},
    "studio":    {"name": "Studio",    "desc": "Clean dark card, light type"},
}
DEFAULT_STYLE = "impact"

YELLOW = (255, 214, 10)
PINK = (255, 112, 243)
MINT = (56, 255, 179)
CYAN = (92, 200, 255)
ORANGE = (255, 138, 61)
SPECTRUM = [(245, 215, 66), (255, 154, 61), (255, 77, 109), (255, 112, 243),
            (169, 139, 255), (92, 200, 255), (56, 255, 179)]


# ══════════════════════════════════════════════════════════════
#  TEXT
# ══════════════════════════════════════════════════════════════

_FILLER = {"the", "a", "an", "of", "to", "in", "on", "and", "or", "is", "are", "was",
           "for", "with", "at", "by", "it", "this", "that", "your", "you", "why",
           "how", "what", "when", "if", "be", "can", "will", "from", "into", "just"}


def auto_text(title: str) -> str:
    """Short, punchy overlay from a long title, with one word highlighted."""
    t = re.sub(r"#\w+", "", title or "").strip(" -—:|")
    parts = [p.strip() for p in re.split(r"[:—|]|\s-\s", t) if p.strip()]
    if len(parts) > 1:
        # "Black Holes: Why Time Breaks Down" → the fullest part that still fits in 5 words
        fit = [p for p in parts if len(p.split()) <= 5]
        t = max(fit, key=lambda p: len(p.split())) if fit else min(parts, key=lambda p: len(p.split()))
    words = t.split()
    if len(words) > 5:
        words = words[:5]
    while words and words[-1].lower().strip("?!.,") in _FILLER:
        words.pop()
    if not words:
        return ""
    # highlight the strongest word: longest non-filler
    cands = [(len(w.strip("?!.,")), i) for i, w in enumerate(words) if w.lower().strip("?!.,") not in _FILLER]
    if cands and "*" not in " ".join(words):
        _, i = max(cands)
        core = words[i].rstrip("?!.,")
        words[i] = f"*{core}*" + words[i][len(core):]
    return " ".join(words)


def _tokens(text: str):
    """'Time *stops* here' → [('Time', False), ('stops', True), ('here', False)]"""
    out = []
    for m in re.finditer(r"\*([^*]+)\*|(\S+)", text or ""):
        if m.group(1):
            out += [(w, True) for w in m.group(1).split()]
        else:
            out.append((m.group(2), False))
    return out


def _measure(font, s: str, tracking: float = 0) -> int:
    w = font.getlength(s)
    return int(w + tracking * max(0, len(s) - 1))


def _layout(tokens, font_name, max_w, max_h, max_lines, start, minimum,
            upper=True, weight=None, leading=0.95, tracking=0.0):
    """Biggest font size whose wrapped lines fit the box. Returns (font, lines, line_h)."""
    size = start
    while True:
        font = fonts.get(font_name, size, weight)
        tr = tracking * size
        space = _measure(font, " ") + tr
        lines, cur, cur_w = [], [], 0
        for word, hi in tokens:
            w_txt = word.upper() if upper else word
            ww = _measure(font, w_txt, tr)
            add = ww if not cur else cur_w + space + ww
            if cur and add > max_w:
                lines.append(cur)
                cur, cur_w = [(w_txt, hi, ww)], ww
            else:
                cur.append((w_txt, hi, ww))
                cur_w = add
        if cur:
            lines.append(cur)
        line_h = int(size * leading)
        widest = max((sum(w for _, _, w in l) + space * (len(l) - 1) for l in lines), default=0)
        if (len(lines) <= max_lines and line_h * len(lines) <= max_h and widest <= max_w) or size <= minimum:
            return font, lines, line_h, space, tr
        size -= 4


def _line_w(line, space):
    return sum(w for _, _, w in line) + space * (len(line) - 1)


def _draw_word(draw, xy, word, font, fill, tracking=0.0, **kw):
    if not tracking:
        draw.text(xy, word, font=font, fill=fill, **kw)
        return
    x, y = xy
    for ch in word:
        draw.text((x, y), ch, font=font, fill=fill, **kw)
        x += font.getlength(ch) + tracking


# ══════════════════════════════════════════════════════════════
#  IMAGE HELPERS
# ══════════════════════════════════════════════════════════════

def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.42))


def _grade(img: Image.Image, contrast=1.18, color=1.28, sharp=1.25, bright=1.0) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Color(img).enhance(color)
    img = ImageEnhance.Brightness(img).enhance(bright)
    return ImageEnhance.Sharpness(img).enhance(sharp)


def _fallback_bg(w: int, h: int) -> Image.Image:
    """Spectrum glow on near-black — used when there is no photo."""
    small = Image.new("RGB", (64, 36), (14, 14, 18))
    px = small.load()
    for x in range(64):
        for y in range(36):
            c = SPECTRUM[int(x / 64 * (len(SPECTRUM) - 1))]
            d = math.hypot((x - 46) / 64, (y - 14) / 36)
            a = max(0.0, 1 - d * 2.2) * 0.55
            px[x, y] = tuple(int(14 + (c[i] - 14) * a) for i in range(3))
    return small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(20))


def _photo(bg_path, w=None, h=None) -> Image.Image:
    w, h = w or W, h or H
    if bg_path and os.path.exists(bg_path):
        try:
            return _cover(Image.open(bg_path), w, h)
        except Exception:
            pass
    return _fallback_bg(w, h)


def _hgrad(w, h, stops) -> Image.Image:
    """Horizontal alpha gradient mask from stops [(x_frac, alpha)]."""
    row = Image.new("L", (w, 1))
    px = row.load()
    for x in range(w):
        f = x / (w - 1)
        for (x0, a0), (x1, a1) in zip(stops, stops[1:]):
            if x0 <= f <= x1:
                t = (f - x0) / max(1e-6, x1 - x0)
                px[x, 0] = int(a0 + (a1 - a0) * t)
                break
    return row.resize((w, h))


def _vgrad(w, h, stops) -> Image.Image:
    return _hgrad(h, w, stops).rotate(90, expand=True).transpose(Image.FLIP_TOP_BOTTOM)


def _vignette(img: Image.Image, strength=0.55) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w // 8, h // 8), 0)
    px = mask.load()
    for x in range(w // 8):
        for y in range(h // 8):
            d = math.hypot((x / (w / 8) - .5) * 1.2, (y / (h / 8) - .5) * 1.4)
            px[x, y] = int(255 * min(1, max(0, (d - .35) * 1.6)) * strength)
    mask = mask.resize((w, h), Image.BICUBIC)
    return Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, mask)


def _shadow_layer(size, draw_fn, blur=14, offset=(0, 10), alpha=200) -> Image.Image:
    layer = Image.new("L", size, 0)
    draw_fn(ImageDraw.Draw(layer), offset)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return layer.point(lambda v: v * alpha // 255)


def _avg_hue(img: Image.Image) -> float:
    r, g, b = img.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0]


def _accent_for(img: Image.Image):
    """Accent colour that pops against the photo: the palette colour furthest in hue."""
    hue = _avg_hue(img)
    pal = [YELLOW, PINK, MINT, CYAN, ORANGE]
    def dist(c):
        h2 = colorsys.rgb_to_hsv(*(v / 255 for v in c))[0]
        d = abs(h2 - hue)
        return min(d, 1 - d)
    return max(pal, key=dist)


def _brand_pill(img: Image.Image, brand: str, xy, dark=False, center_y=None):
    """'▶ CHANNEL' pill at xy, or centred horizontally at center_y."""
    if not brand:
        return
    k = 1.45 if H > W else 1.0
    d = ImageDraw.Draw(img, "RGBA")
    f = fonts.get("inter", int(24 * k), 700)
    label = f"▶ {brand.upper()}"
    tw = _measure(f, label, 1.5 * k)
    pw, ph = tw + int(32 * k), int(42 * k)
    x, y = ((W - pw) // 2, center_y - ph // 2) if center_y is not None else xy
    fill = (17, 17, 17, 235) if dark else (255, 255, 255, 235)
    d.rounded_rectangle([x, y, x + pw, y + ph], radius=ph // 2, fill=fill)
    _draw_word(d, (x + int(16 * k), y + int(8 * k)), label, f,
               (255, 255, 255) if dark else (17, 17, 17), tracking=1.5 * k)


# ══════════════════════════════════════════════════════════════
#  STYLES
# ══════════════════════════════════════════════════════════════
#  Every style has a landscape (16:9, long videos) and a portrait
#  (9:16, Shorts) layout. W, H are set by render() for each call.

def _portrait() -> bool:
    return H > W


def _k() -> float:
    """Scale for small elements (labels, pills, bars): bigger on a phone-sized canvas."""
    return 1.45 if _portrait() else 1.0


def _x_for(line, space, align, x0, width):
    return x0 + (width - _line_w(line, space)) // 2 if align == "center" else x0


def _impact(bg, tokens, brand):
    P, k = _portrait(), _k()
    img = _grade(bg, contrast=1.22, color=1.35)
    img = _vignette(img, .5)
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    if P:
        img = Image.composite(dark, img, _vgrad(W, H, [(0, 60), (.12, 0), (.40, 0), (.66, 200), (1, 235)]))
        font, lines, lh, space, _ = _layout(tokens, "anton", int(W * .86), int(H * .34), 4, 260, 90, leading=1.0)
        x0, width, align = int(W * .07), int(W * .86), "center"
        y0 = int(H * .84) - lh * len(lines)
    else:
        img = Image.composite(dark, img, _hgrad(W, H, [(0, 225), (.45, 170), (.72, 0), (1, 0)]))
        font, lines, lh, space, _ = _layout(tokens, "anton", int(W * .60), int(H * .70), 3, 190, 70, leading=1.0)
        x0, width, align = 64, int(W * .60), "left"
        y0 = (H - lh * len(lines)) // 2 + 10

    def draw_text(d, off=(0, 0), solid=None):
        y = y0
        for line in lines:
            x = _x_for(line, space, align, x0, width)
            for word, hi, ww in line:
                fill = solid if solid is not None else (YELLOW if hi else (255, 255, 255))
                kw = {} if solid is not None else {"stroke_width": max(4, font.size // 26), "stroke_fill": (0, 0, 0)}
                d.text((x + off[0], y + off[1]), word, font=font, fill=fill, **kw)
                x += ww + space
            y += lh

    sh = _shadow_layer((W, H), lambda d, o: draw_text(d, o, solid=255), blur=12, offset=(10, 14), alpha=230)
    img.paste((0, 0, 0), (0, 0), sh)
    d = ImageDraw.Draw(img)
    bar_w = int(120 * k)
    bx = (W - bar_w) // 2 if P else x0
    d.rounded_rectangle([bx, y0 - int(34 * k), bx + bar_w, y0 - int(22 * k)], radius=6, fill=YELLOW)
    draw_text(d)
    if P:
        _brand_pill(img, brand, None, center_y=int(H * .07))
    else:
        _brand_pill(img, brand, (x0, H - 78))
    return img


def _cinematic(bg, tokens, brand):
    P, k = _portrait(), _k()
    img = _grade(bg, contrast=1.12, color=1.12, bright=.95)
    # teal shadows / warm highlights
    r, g, b = img.split()
    r = r.point(lambda v: min(255, int(v * 1.06 + 6)))
    b = b.point(lambda v: min(255, int(v * 0.92 + 18)))
    img = Image.merge("RGB", (r, g, b))
    img = _vignette(img, .65)
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img,
                          _vgrad(W, H, [(0, 0), (.45 if not P else .52, 0), (.78, 190), (1, 245)]))

    if P:
        font, lines, lh, space, tr = _layout(tokens, "bebas", int(W * .86), int(H * .30), 3, 250, 90,
                                             leading=.92, tracking=.04)
        y0 = H - int(150 * k) - lh * len(lines)
        bar = 56
    else:
        font, lines, lh, space, tr = _layout(tokens, "bebas", int(W * .86), int(H * .40), 2, 190, 70,
                                             leading=.92, tracking=.04)
        y0 = H - 70 - lh * len(lines)
        bar = 34

    def draw_text(dd, off=(0, 0), solid=None):
        y = y0
        for line in lines:
            x = (W - _line_w(line, space)) // 2
            for word, hi, ww in line:
                fill = solid if solid is not None else ((255, 186, 90) if hi else (250, 248, 242))
                _draw_word(dd, (x + off[0], y + off[1]), word, font, fill, tracking=tr)
                x += ww + space
            y += lh

    glow = _shadow_layer((W, H), lambda dd, o: draw_text(dd, o, solid=255), blur=18, offset=(0, 6), alpha=210)
    img.paste((0, 0, 0), (0, 0), glow)
    d = ImageDraw.Draw(img, "RGBA")
    draw_text(d)
    # film letterbox
    d.rectangle([0, 0, W, bar], fill=(0, 0, 0, 255))
    d.rectangle([0, H - bar, W, H], fill=(0, 0, 0, 255))
    if brand:
        f = fonts.get("inter", int(20 * k), 500)
        label = brand.upper()
        tw = _measure(f, label, 6 * k)
        y = y0 - int(46 * k)
        _draw_word(d, ((W - tw) // 2, y), label, f, (235, 235, 235, 230), tracking=6 * k)
        cy, gap, ln = y + int(12 * k), int(22 * k), int(48 * k)
        d.line([((W - tw) // 2 - gap - ln, cy), ((W - tw) // 2 - gap, cy)], fill=(235, 235, 235, 160), width=2)
        d.line([((W + tw) // 2 + gap, cy), ((W + tw) // 2 + gap + ln, cy)], fill=(235, 235, 235, 160), width=2)
    return img


def _split(bg, tokens, brand):
    P, k = _portrait(), _k()
    accent = _accent_for(bg)
    photo = _grade(bg, contrast=1.15, color=1.3)
    img = Image.new("RGB", (W, H), accent)
    mask = Image.new("L", (W, H), 0)
    if P:
        cut = int(H * .54)
        edge = [(W, cut - 70), (0, cut + 70)]
        ImageDraw.Draw(mask).polygon([(0, 0), (W, 0), edge[0], edge[1]], fill=255)
        box = (72, cut + 140, W - 144, H - cut - 300)        # x, y, w, h for text
    else:
        cut = int(W * .47)
        edge = [(cut + 70, 0), (cut - 50, H)]
        ImageDraw.Draw(mask).polygon([edge[0], (W, 0), (W, H), edge[1]], fill=255)
        box = (60, 0, cut - 120, H)
    img.paste(photo, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.line(edge, fill=(17, 17, 17), width=int(14 * k))

    bx, by, bw, bh = box
    font, lines, lh, space, _ = _layout(tokens, "archivo", bw, int(bh * (.95 if P else .70)), 4,
                                        200 if P else 150, 56, leading=1.08)
    y = by + (bh - lh * len(lines)) // 2
    for line in lines:
        x = bx
        for word, hi, ww in line:
            if hi:
                pad = int(font.size * .12)
                top = y + int(font.size * .12)
                d.rectangle([x - pad, top, x + ww + pad, top + int(font.size * .98)], fill=(17, 17, 17))
                d.text((x, y), word, font=font, fill=accent)
            else:
                d.text((x, y), word, font=font, fill=(17, 17, 17))
            x += ww + space
        y += lh
    if brand:
        f = fonts.get("inter", int(22 * k), 800)
        _draw_word(d, (bx, H - int(64 * k) - (40 if P else 0)), f"▶ {brand.upper()}", f, (17, 17, 17), tracking=1.5 * k)
    return img


def _studio(bg, tokens, brand):
    P, k = _portrait(), _k()
    img = Image.new("RGB", (W, H), (21, 21, 21))
    d = ImageDraw.Draw(img, "RGBA")
    step = int(24 * k)
    for x in range(0, W, step):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 7))
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 7))

    if P:
        m = 48
        px, py, pw, ph = m, 170, W - 2 * m, int(H * .50)
        tx, ty, tw, th = 72, py + ph + 70, W - 144, H - (py + ph + 70) - 200
        label_xy, bars_xy = (72, 84), (72, H - 110)
    else:
        m = 26
        pw, ph = int(W * .50), H - 2 * m
        px, py = W - pw - m, m
        tx, ty, tw, th = 58, 0, px - 58 - 40, H
        label_xy, bars_xy = (58, 56), (58, H - 56)

    photo = _grade(_cover(bg, pw, ph), contrast=1.12, color=1.2)
    pmask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(pmask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=int(22 * k), fill=255)
    img.paste(photo, (px, py), pmask)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([px, py, px + pw - 1, py + ph - 1], radius=int(22 * k), outline=(255, 255, 255, 40), width=2)

    if brand:
        f = fonts.get("mono", int(20 * k), 500)
        _draw_word(d, label_xy, f"▶ {brand.upper()}", f, (154, 154, 154), tracking=2 * k)

    font, lines, lh, space, _ = _layout(tokens, "inter", tw, int(th * (.9 if P else .62)), 4,
                                        170 if P else 128, 48, upper=False, weight=320, leading=1.0)
    hi_font = fonts.get("inter", font.size, 620)
    y = ty + (th - lh * len(lines)) // 2 - (0 if P else 10)
    for line in lines:
        x = tx
        for word, hi, ww in line:
            if hi:
                d.text((x, y), word, font=hi_font, fill=(255, 255, 255))
                hw = hi_font.getlength(word)
                ul = y + int(font.size * 1.02)
                d.rounded_rectangle([x, ul, x + hw, ul + int(8 * k)], radius=4, fill=PINK)
                x += hw + space
            else:
                d.text((x, y), word, font=font, fill=(140, 142, 144))
                x += ww + space
        y += lh

    # spectrum bars, like the site
    n = 30 if not P else 34
    bx, by = bars_xy
    bw, gap = int(9 * k), int(4 * k)
    for i in range(n):
        c = SPECTRUM[int(i / (n - 1) * (len(SPECTRUM) - 1))]
        h = int((10 + 34 * (0.5 + 0.5 * math.sin(i * 0.9) * math.cos(i * 0.37))) * k)
        d.rounded_rectangle([bx + i * (bw + gap), by - h, bx + i * (bw + gap) + bw, by], radius=2, fill=c + (230,))
    return img


_RENDERERS = {"impact": _impact, "cinematic": _cinematic, "split": _split, "studio": _studio}
_render_lock = threading.Lock()

LANDSCAPE = (1280, 720)    # long videos — YouTube's recommended thumbnail size
PORTRAIT = (1080, 1920)    # Shorts
MAX_BYTES = 2 * 1024 * 1024 - 64 * 1024   # YouTube rejects thumbnails over 2 MB


def render(style: str, out_path: str, text: str, bg_path: str | None = None,
           brand: str = "", size: tuple | None = None, portrait: bool = False) -> str:
    """
    Render one thumbnail: 1280×720 for long videos, 1080×1920 when `portrait`
    (Shorts). `size` downsizes the output (for previews).
    """
    global W, H
    fn = _RENDERERS.get(style) or _RENDERERS[DEFAULT_STYLE]
    tokens = _tokens(text) or [("NEW", False), ("VIDEO", True)]
    with _render_lock:                      # W/H are module state shared by the style functions
        W, H = PORTRAIT if portrait else LANDSCAPE
        img = fn(_photo(bg_path), tokens, brand).convert("RGB")
    if size:
        img = img.resize(size, Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    for quality in (92, 85, 78, 70):
        img.save(out_path, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(out_path) <= MAX_BYTES:
            break
    return out_path
