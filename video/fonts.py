"""
Display fonts for thumbnails — free Google Fonts (SIL Open Font License),
downloaded once into assets/fonts/ on first use. Falls back to system fonts
when offline, so rendering never fails.
"""
import os
import threading

from PIL import ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "assets", "fonts")
_GF = "https://github.com/google/fonts/raw/main/"

# name → (Google Fonts path, local file name, system fallbacks)
FONTS = {
    "anton":   ("ofl/anton/Anton-Regular.ttf", "Anton-Regular.ttf",
                ["C:/Windows/Fonts/impact.ttf", "/System/Library/Fonts/Supplemental/Impact.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
    "bebas":   ("ofl/bebasneue/BebasNeue-Regular.ttf", "BebasNeue-Regular.ttf",
                ["C:/Windows/Fonts/bahnschrift.ttf", "C:/Windows/Fonts/impact.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"]),
    "archivo": ("ofl/archivoblack/ArchivoBlack-Regular.ttf", "ArchivoBlack-Regular.ttf",
                ["C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/arialbd.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
    "inter":   ("ofl/intertight/InterTight%5Bwght%5D.ttf", "InterTight-Variable.ttf",
                ["C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]),
    "mono":    ("ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf", "JetBrainsMono-Variable.ttf",
                ["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]),
}

_lock = threading.Lock()
_cache: dict = {}
_failed: set = set()


def _ensure(name: str) -> str | None:
    """Local path to the Google Font, downloading it once. None if unavailable."""
    gf_path, fname, _ = FONTS[name]
    path = os.path.join(FONT_DIR, fname)
    if os.path.exists(path) and os.path.getsize(path) > 10_000:
        return path
    if name in _failed:
        return None
    with _lock:
        if os.path.exists(path):
            return path
        try:
            from apis.http import download
            os.makedirs(FONT_DIR, exist_ok=True)
            print(f"   -> Downloading font {fname} (Google Fonts, one-time)...")
            download(_GF + gf_path, path + ".part", timeout=30)
            os.replace(path + ".part", path)
            return path
        except Exception as e:
            print(f"   ! Font download failed ({fname}): {e} - using a system font")
            _failed.add(name)
            return None


def get(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    key = (name, size, weight)
    if key in _cache:
        return _cache[key]
    candidates = [_ensure(name)] + FONTS[name][2]
    font = None
    for p in candidates:
        if not p or not os.path.exists(p):
            continue
        try:
            font = ImageFont.truetype(p, size)
            if weight:
                try:
                    font.set_variation_by_axes([weight])
                except Exception:
                    pass        # static font — weight is baked in
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default(size)
    _cache[key] = font
    return font
