"""
Image sources beyond Pexels. Tried in the order set by config.IMAGE_SOURCES
until one returns results, so videos still get B-roll with no Pexels key.

  pixabay       Pixabay API (free key)               — Pixabay Content License
  nasa          NASA Image & Video Library (keyless)  — public domain, space topics only
  openverse     Openverse / WordPress (keyless)       — CC licences, attribution kept
  pollinations  Pollinations.ai (keyless)             — AI-generated, last resort

Each candidate carries a `credit` dict; stock.py writes them to credits.json
and the description builder turns them into an attribution block.
"""
import random
import re
from urllib.parse import quote

import config
from apis.http import get, get_json

_SPACE_WORDS = re.compile(
    r"\b(space|galax|star|planet|nebula|black hole|moon|mars|jupiter|saturn|"
    r"astronaut|rocket|cosm|universe|orbit|solar|sun\b|telescope|nasa|comet|"
    r"asteroid|earth from|supernova|eclipse|satellite)", re.I)


def _pixabay(query: str, orientation: str, count: int) -> list:
    key = getattr(config, "PIXABAY_API_KEY", "")
    if not key:
        return []
    d = get_json("https://pixabay.com/api/", params={
        "key": key, "q": query[:100], "image_type": "photo", "safesearch": "true",
        "orientation": "vertical" if orientation == "portrait" else "horizontal",
        "per_page": max(10, count * 3), "min_width": 1280,
    })
    return [{
        "url": h.get("largeImageURL") or h.get("webformatURL"),
        "credit": {"source": "Pixabay", "author": h.get("user", ""),
                   "license": "Pixabay Content License", "link": h.get("pageURL", "")},
    } for h in d.get("hits", [])]


def _nasa(query: str, orientation: str, count: int) -> list:
    if not _SPACE_WORDS.search(query):
        return []          # NASA's library is superb for space, useless otherwise
    d = get_json("https://images-api.nasa.gov/search", params={
        "q": query, "media_type": "image", "page_size": max(10, count * 3),
    })
    out = []
    for item in d.get("collection", {}).get("items", []):
        links = item.get("links") or []
        data = (item.get("data") or [{}])[0]
        if not links:
            continue
        href = links[0].get("href", "")
        out.append({
            "url": re.sub(r"~(thumb|small|medium)\.", "~large.", href),
            "fallback_url": href,
            "credit": {"source": "NASA", "author": data.get("center") or "NASA",
                       "license": "Public domain",
                       "link": f"https://images.nasa.gov/details/{data.get('nasa_id', '')}"},
        })
    return out


def _openverse(query: str, orientation: str, count: int) -> list:
    d = get_json("https://api.openverse.org/v1/images/", params={
        "q": query, "page_size": max(10, count * 3),
        "license_type": "commercial,modification",
        "aspect_ratio": "tall" if orientation == "portrait" else "wide",
        "size": "large", "mature": "false",
    }, timeout=25)
    return [{
        "url": r.get("url"),
        "credit": {"source": "Openverse", "author": r.get("creator") or "Unknown",
                   "license": f"CC {(r.get('license') or '').upper()} {r.get('license_version') or ''}".strip(),
                   "link": r.get("foreign_landing_url") or r.get("url")},
    } for r in d.get("results", []) if r.get("url")]


def pollinations_url(prompt: str, width: int = 1280, height: int = 720,
                     seed: int | None = None) -> str:
    seed = seed if seed is not None else random.randint(1, 10**6)
    return (f"https://image.pollinations.ai/prompt/{quote(prompt[:400], safe='')}"
            f"?width={width}&height={height}&nologo=true&seed={seed}")


def _pollinations(query: str, orientation: str, count: int) -> list:
    w, h = (1080, 1920) if orientation == "portrait" else (1920, 1080)
    prompt = f"cinematic documentary photograph, {query}, dramatic lighting, high detail, no text"
    return [{
        "url": pollinations_url(prompt, w, h),
        "timeout": 120,
        "credit": {"source": "Pollinations AI", "author": "AI-generated",
                   "license": "Pollinations terms", "link": "https://pollinations.ai"},
    } for _ in range(count)]


PROVIDERS = {
    "pixabay":      _pixabay,
    "nasa":         _nasa,
    "openverse":    _openverse,
    "pollinations": _pollinations,
}


def search(query: str, orientation: str = "landscape", count: int = 1,
           exclude_urls: set | None = None) -> list:
    """First provider (in config order, Pexels excluded) that returns results."""
    order = [s for s in getattr(config, "IMAGE_SOURCES", list(PROVIDERS)) if s in PROVIDERS]
    exclude_urls = exclude_urls or set()
    for name in order:
        try:
            cands = [c for c in PROVIDERS[name](query, orientation, count)
                     if c.get("url") and c["url"] not in exclude_urls]
        except Exception as e:
            print(f"   ⚠ {name} image search failed for '{query[:40]}': {e}")
            continue
        if cands:
            pool = cands[:max(count * 2, 6)]
            if name != "pollinations":
                random.shuffle(pool)
            return pool[:count]
    return []


def fetch(candidate: dict, path: str) -> bool:
    """Download a candidate, trying its fallback URL if the large size is missing."""
    for url in (candidate.get("url"), candidate.get("fallback_url")):
        if not url:
            continue
        try:
            r = get(url, timeout=candidate.get("timeout", 30), stream=True)
            ctype = r.headers.get("Content-Type", "")
            if "image" not in ctype and "octet-stream" not in ctype:
                continue
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return True
        except Exception:
            continue
    return False
