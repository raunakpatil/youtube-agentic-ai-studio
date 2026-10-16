"""
Stock Image Downloader — Pexels first, then the free fallback chain in
apis/images.py (Pixabay → NASA → Openverse → Pollinations AI), so videos get
real B-roll even without a Pexels key.

For normal videos : up to 3 images per section (mid-section B-roll cuts)
For Shorts        : 1 image per query, up to 4 per section (fast slideshow)
Images saved to output/images/section_NN_imgMM.jpg
Credits saved to output/credits.json (used for the description's attribution).
"""
import glob
import json
import os
import random
import requests
import config
from apis import images as image_apis

PEXELS_SEARCH = "https://api.pexels.com/v1/search"

FALLBACK_QUERIES = [
    "space universe stars galaxy",
    "science technology futuristic",
    "earth atmosphere clouds aerial",
    "abstract light particles dark",
    "dramatic landscape nature",
    "neon city night lights",
]

# Every image downloaded this run → credits.json
_credits: list = []
_used_urls: set = set()


def _pexels_ready() -> bool:
    key = getattr(config, "PEXELS_API_KEY", "") or ""
    return bool(key) and not key.upper().startswith("YOUR_")


def _pexels(query: str, orientation: str, count: int) -> list:
    """Pexels candidates in the same shape as apis.images providers."""
    per_page = min(max(count * 3, 15), 40)
    # Randomise page so repeated runs don't fetch the exact same top photos
    page = random.randint(1, 3)
    headers = {"Authorization": config.PEXELS_API_KEY}
    params = {"query": query, "per_page": per_page, "page": page, "orientation": orientation}
    r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
    if r.status_code == 401:
        print("   ⚠ Pexels API key invalid — using free fallback sources")
        config.PEXELS_API_KEY = ""
        return []
    r.raise_for_status()
    photos = r.json().get("photos", [])
    # If a random page returned nothing, retry page 1
    if not photos and page > 1:
        params["page"] = 1
        r2 = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
        photos = r2.json().get("photos", []) if r2.ok else []

    photos.sort(key=lambda p: p["width"] * p["height"], reverse=True)
    # Shuffle within top pool so each run picks different images
    pool = photos[:max(count * 2, 6)]
    random.shuffle(pool)
    return [{
        "url": p["src"].get("large2x") or p["src"]["original"],
        "credit": {"source": "Pexels", "author": p.get("photographer", ""),
                   "license": "Pexels License", "link": p.get("url", "")},
    } for p in pool]


def _candidates(query: str, orientation: str, count: int) -> list:
    if _pexels_ready():
        try:
            c = [x for x in _pexels(query, orientation, count) if x["url"] not in _used_urls]
            if c:
                return c
        except Exception as e:
            print(f"   ⚠ Pexels search failed for '{query}': {e}")
    return image_apis.search(query, orientation, count, exclude_urls=_used_urls)


def _fetch_images(query: str, section_index: int, images_dir: str,
                  count: int = 1, orientation: str = "landscape",
                  img_num_start: int = 0, topic_hint: str = "") -> list:
    """
    Downloads `count` distinct images for a given query.
    img_num_start offsets the filename index (for multi-query sections).
    topic_hint: prepended to the query to boost topical relevance.
    Returns a list of local file paths.
    """
    # Prepend topic hint to improve relevance (e.g. "black holes dramatic wide")
    if topic_hint and topic_hint.lower() not in query.lower():
        search_query = f"{topic_hint} {query}"
    else:
        search_query = query

    saved = []
    for attempt_query in [search_query, query] + FALLBACK_QUERIES:
        for cand in _candidates(attempt_query, orientation, count - len(saved)):
            fname = f"section_{section_index:02d}_img{img_num_start + len(saved) + 1:02d}.jpg"
            path = os.path.join(images_dir, fname)
            if image_apis.fetch(cand, path):
                saved.append(path)
                _used_urls.add(cand["url"])
                _credits.append({"file": fname, "query": attempt_query, **cand["credit"]})
            else:
                print(f"   ⚠ Download failed ({cand['url'][:60]}…)")
            if len(saved) >= count:
                return saved
        if saved:
            break
    return saved


def section_images(images_dir: str, section_id: int) -> list:
    """Images already on disk for a section (used when the Images step is skipped)."""
    return sorted(glob.glob(os.path.join(images_dir, f"section_{section_id:02d}_img*.jpg")))


def download_images(script: dict, output_dir: str) -> dict:
    """
    Downloads stock images for every section.
    Shorts: returns list of paths per section_id (for slideshow).
    Normal: returns list of paths (or None) per section_id.
    """
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    # Clear the previous run's images so stale B-roll never leaks into this video
    for old in glob.glob(os.path.join(images_dir, "section_*.jpg")):
        try:
            os.remove(old)
        except OSError:
            pass
    _credits.clear()
    _used_urls.clear()

    if not _pexels_ready():
        order = " → ".join(getattr(config, "IMAGE_SOURCES", []))
        print(f"   → No Pexels key — using free sources: {order}")

    is_shorts        = script.get("video_type") == "shorts"
    orientation      = "portrait" if is_shorts else "landscape"

    # Extract a short topic hint from the script title for query enrichment
    raw_title  = script.get("title", "")
    # Keep first 4 words as a concise topic hint
    topic_hint = " ".join(raw_title.split()[:4]) if raw_title else ""

    image_map = {}
    for section in script.get("sections", []):
        sid   = section["id"]
        # Collect all image queries defined for this section
        queries = [section.get("image_query", "science universe space")]
        for extra_key in ("image_query_2", "image_query_3", "image_query_4"):
            q = section.get(extra_key, "").strip()
            if q:
                queries.append(q)

        # Shorts: one image per query; normal: first 3 queries for B-roll cuts
        use = queries if is_shorts else queries[:3]
        print(f"   → [{sid}] {len(use)} queries × 1 image each")
        paths = []
        for qi, q in enumerate(use):
            paths.extend(_fetch_images(q, sid, images_dir,
                                       count=1, orientation=orientation,
                                       img_num_start=qi, topic_hint=topic_hint))
        image_map[sid] = paths if (paths or is_shorts) else None
        print(f"         saved {len(paths)} images")

    with open(os.path.join(output_dir, "credits.json"), "w", encoding="utf-8") as f:
        json.dump(_credits, f, indent=2)
    by_source = {}
    for c in _credits:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    if by_source:
        print("   → Image sources: " + ", ".join(f"{k} ×{v}" for k, v in by_source.items()))
    return image_map
