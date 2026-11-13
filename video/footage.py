"""Pixabay stock video search and download, with a 24-hour API result cache."""
import hashlib
import json
import os
import re
import time

import requests

import config

SEARCH_URL = "https://pixabay.com/api/videos/"
CACHE_SECONDS = 24 * 60 * 60
MAX_CLIP_BYTES = 40 * 1024 * 1024


def _slug_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _visuals(section: dict) -> list[dict]:
    raw = section.get("visuals")
    if isinstance(raw, list) and raw:
        out = []
        for item in raw[:6]:
            if not isinstance(item, dict):
                continue
            query = str(item.get("search_query", "")).strip()
            cue = str(item.get("narration_cue", "")).strip()
            if query.lower().startswith(("exact words", "specific real video")):
                query = ""
            if cue.lower().startswith("exact words"):
                cue = ""
            if query:
                out.append({"search_query": query, "narration_cue": cue})
        if out:
            return out

    # Older saved scripts have photo queries only. Derive literal searches from
    # their narration rather than falling back to unrelated generic stock.
    sentences = _sentences(section.get("narration", ""))
    out = []
    for i, sentence in enumerate(sentences[:3]):
        cue = " ".join(sentence.split()[:10])
        out.append({"search_query": cue, "narration_cue": cue})
    if not out and section.get("title"):
        title = str(section["title"]).strip()
        out.append({"search_query": title, "narration_cue": title})
    return out


def _cached_hits(query: str, cache_dir: str) -> list[dict]:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, _slug_hash(query.casefold()) + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        if time.time() - float(cached.get("saved_at", 0)) < CACHE_SECONDS:
            return cached.get("hits", [])
    except (OSError, ValueError, TypeError):
        pass

    key = getattr(config, "PIXABAY_API_KEY", "") or ""
    if not key or key.upper().startswith("YOUR_"):
        return []
    try:
        response = requests.get(SEARCH_URL, params={
            "key": key,
            "q": query[:100],
            "per_page": 20,
            "safesearch": "true",
            "video_type": "all",
        }, timeout=20)
        if response.status_code == 401:
            print("   ⚠ Pixabay video key was rejected; keeping relevant stills for these scenes.")
            return []
        if response.status_code == 429:
            print("   ⚠ Pixabay video search rate limit reached; keeping relevant stills for these scenes.")
            return []
        response.raise_for_status()
        hits = response.json().get("hits", [])
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(), "hits": hits}, f)
        return hits
    except Exception as e:
        # Do not print request URLs: Pixabay puts the private API key in its URL.
        print(f"   ⚠ Pixabay video search failed ({type(e).__name__}); keeping relevant stills for this scene.")
        return []


def _rendition(hit: dict, orientation: str) -> tuple[str, dict] | None:
    files = hit.get("videos") or {}
    preferred = ("small", "medium", "tiny")
    options = []
    for size in preferred:
        item = files.get(size) or {}
        url = item.get("url")
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        if not url or not width or not height:
            continue
        matching = (height > width) if orientation == "portrait" else (width >= height)
        size_bytes = int(item.get("size") or 0)
        if size_bytes and size_bytes > MAX_CLIP_BYTES:
            continue
        options.append((matching, size, item))
    if not options:
        return None
    options.sort(key=lambda entry: (entry[0], entry[1] == "small"), reverse=True)
    _, size, item = options[0]
    return size, item


def _pick_hit(hits: list[dict], orientation: str, target_seconds: float,
              used_ids: set[str]) -> tuple[dict, str, dict] | None:
    candidates = []
    for hit in hits:
        video_id = str(hit.get("id", ""))
        duration = float(hit.get("duration") or 0)
        if not video_id or video_id in used_ids or duration < max(4.0, target_seconds * 0.55):
            continue
        rendition = _rendition(hit, orientation)
        if not rendition:
            continue
        size, file_info = rendition
        width, height = int(file_info.get("width") or 0), int(file_info.get("height") or 0)
        matches = (height > width) if orientation == "portrait" else (width >= height)
        covers = duration >= target_seconds
        candidates.append((matches, covers, min(duration, 45), hit, size, file_info))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    _, _, _, hit, size, file_info = candidates[0]
    return hit, size, file_info


def _download(url: str, path: str) -> bool:
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".part"
    total = 0
    try:
        with requests.get(url, stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            length = int(response.headers.get("Content-Length") or 0)
            if length > MAX_CLIP_BYTES:
                return False
            with open(temp, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_CLIP_BYTES:
                        raise ValueError("Video clip exceeds the local size limit")
                    f.write(chunk)
        if total < 1024:
            return False
        os.replace(temp, path)
        return True
    except Exception:
        return False
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


def _fallback_queries(visual: dict) -> list[str]:
    first = visual.get("search_query", "").strip()
    cue = visual.get("narration_cue", "").strip()
    return list(dict.fromkeys(q[:100] for q in (first, cue) if q and q != first))


def _target_duration(section: dict, count: int, is_shorts: bool) -> float:
    words = max(1, len(str(section.get("narration", "")).split()))
    section_seconds = max(8.0, words / 110 * 60)
    target = section_seconds / max(1, count)
    return min(16.0, max(5.0, target)) if is_shorts else min(30.0, max(8.0, target))


def download_footage(script: dict, output_dir: str) -> dict:
    """Download one specific stock clip per narration beat; never use generic filler."""
    videos_dir = os.path.join(output_dir, "videos")
    assets_dir = os.path.join(videos_dir, "assets")
    cache_dir = os.path.join(output_dir, "footage_cache")
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)
    video_type = script.get("video_type", "normal")
    orientation = "portrait" if video_type == "shorts" else "landscape"
    key = getattr(config, "PIXABAY_API_KEY", "") or ""
    has_key = bool(key) and not key.upper().startswith("YOUR_")
    if not has_key:
        print("   → No Pixabay video key; using relevant stills only where footage is unavailable.")
    used_ids: set[str] = set()
    video_map: dict[int, list[dict]] = {}
    credits_path = os.path.join(output_dir, "credits.json")

    for section in script.get("sections", []):
        sid = int(section.get("id", 0))
        visuals = _visuals(section)
        target = _target_duration(section, len(visuals), video_type == "shorts")
        entries = []
        for index, visual in enumerate(visuals, 1):
            cue = visual.get("narration_cue", "")
            queries = _fallback_queries(visual)
            result = None
            if has_key:
                for query in queries:
                    hits = _cached_hits(query, cache_dir)
                    result = _pick_hit(hits, orientation, target, used_ids)
                    if result:
                        break
            entry = {"path": None, "narration_cue": cue,
                     "search_query": visual.get("search_query", "")}
            if result:
                hit, rendition_name, file_info = result
                video_id = str(hit["id"])
                path = os.path.join(assets_dir, f"{video_id}_{rendition_name}.mp4")
                if _download(file_info["url"], path):
                    used_ids.add(video_id)
                    entry["path"] = path
                    credit = {
                        "source": "Pixabay", "media_type": "video",
                        "author": hit.get("user", ""),
                        "license": "Pixabay Content License",
                        "link": hit.get("pageURL", "https://pixabay.com/videos/"),
                        "query": visual.get("search_query", ""),
                        "file": os.path.basename(path),
                    }
                    entry["credit"] = credit
                    print(f"         footage {index}: Pixabay clip {video_id} ({hit.get('duration', 0)}s)")
                else:
                    print(f"         footage {index}: download failed; using the matching still instead")
            else:
                if has_key:
                    print(f"         footage {index}: no matching clip found; using the matching still instead")
            entries.append(entry)
        video_map[sid] = entries

    with open(os.path.join(videos_dir, "footage.json"), "w", encoding="utf-8") as f:
        json.dump({"title": script.get("title", ""), "video_type": video_type,
                   "sections": {str(k): v for k, v in video_map.items()}}, f, indent=2)

    try:
        with open(credits_path, encoding="utf-8") as f:
            credits = json.load(f)
    except (OSError, ValueError):
        credits = []
    credits = [c for c in credits if c.get("media_type") != "video"]
    credits.extend(e["credit"] for entries in video_map.values() for e in entries if e.get("credit"))
    with open(credits_path, "w", encoding="utf-8") as f:
        json.dump(credits, f, indent=2)

    return video_map


def load_footage(script: dict, output_dir: str) -> dict:
    """Load the last run's clip map when the Visuals step is skipped."""
    path = os.path.join(output_dir, "videos", "footage.json")
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return {}
    if saved.get("title") != script.get("title"):
        return {}
    result = {}
    for sid, entries in (saved.get("sections") or {}).items():
        result[int(sid)] = [
            {**e, "path": e.get("path") if e.get("path") and os.path.isfile(e["path"]) else None}
            for e in entries
        ]
    return result
