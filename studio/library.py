"""
Library: every finished render is archived to output/library/<id>/ so it can
be re-opened, re-edited, re-published, downloaded or deleted later.
"""
import glob
import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta

from flask import Blueprint, abort, jsonify

import config
from studio.description import build_description, load_credits, with_credit
from studio.files import send, slug
from studio.state import log, state
from studio.thumbs import thumb_backgrounds, thumb_settings

bp = Blueprint("library", __name__)

LIB_DIR = os.path.join(config.OUTPUT_DIR, "library")

def lib_path(pid, *parts):
    if not re.fullmatch(r"[\w-]+", pid or ""): abort(404)
    return os.path.join(LIB_DIR, pid, *parts)

def read_meta(pid):
    with open(lib_path(pid, "meta.json"), encoding="utf-8") as f:
        return json.load(f)

def write_meta(pid, meta):
    with open(lib_path(pid, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

def archive_project():
    """Copy the finished render + metadata into the Library. Copies, never hard-links:
    ffmpeg and PIL overwrite output files in place, which would corrupt a linked copy."""
    script, research = state.get("script") or {}, state.get("research") or {}
    if not (state.get("video_path") and os.path.exists(state["video_path"])):
        return None
    pid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug(script.get("title"))
    d = os.path.join(LIB_DIR, pid)
    os.makedirs(d, exist_ok=True)

    def _put(src, name):
        if src and os.path.exists(src):
            shutil.copy2(src, os.path.join(d, name))
            return name
        return None

    files = {
        "video":    _put(state["video_path"], "video.mp4"),
        "thumb":    _put(state.get("thumb_path"), "thumbnail.jpg"),
        "captions": _put(os.path.join(config.OUTPUT_DIR, "narration.srt"), "captions.srt"),
    }
    cover = state.get("thumb_bg") or next((p for v in (state.get("image_map") or {}).values()
                                            for p in (v if isinstance(v, list) else [v]) if p and os.path.exists(p)), None)
    files["cover"] = _put(cover, "cover.jpg")
    # keep a few of the video's photos so the thumbnail can be redesigned later
    os.makedirs(os.path.join(d, "photos"), exist_ok=True)
    for i, p in enumerate(thumb_backgrounds(state.get("image_map"))[:8]):
        shutil.copy2(p, os.path.join(d, "photos", f"{i + 1:02d}.jpg"))
    for name, obj in (("script.json", script), ("research.json", research), ("credits.json", load_credits())):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)

    try:
        from moviepy.editor import VideoFileClip
        with VideoFileClip(state["video_path"]) as clip:
            duration = round(clip.duration, 1)
    except Exception:
        duration = None

    meta = {
        "id":          pid,
        "title":       script.get("title", ""),
        "topic":       research.get("topic", ""),
        "series_name": research.get("series_name", ""),
        "series_episode": research.get("series_episode"),
        "series_connection": research.get("series_connection", ""),
        "next_episode_hint": research.get("next_episode_hint", ""),
        "video_type":  state.get("video_type", "normal"),
        "created_at":  datetime.now().isoformat(timespec="seconds"),
        "render_secs": int(time.time() - state["started_at"]) if state.get("started_at") else None,
        "duration":    duration,
        "sections":    len(script.get("sections", [])),
        "sources":     len((research.get("grounding") or {}).get("sources") or []),
        "description": state.get("description", ""),
        "tags":        script.get("tags", []),
        "yt_url":      None,
        "thumb_style": thumb_settings(script)[0],
        "thumb_text":  state.get("thumb_text"),
        "files":       files,
    }
    write_meta(pid, meta)
    state["library_id"] = pid
    log(f"Saved to Library: {pid}")
    return pid

def sync_library():
    """Push review edits (title, description, tags, thumbnail, upload URL) into the Library entry."""
    pid = state.get("library_id")
    if not pid or not os.path.isdir(lib_path(pid)):
        return
    try:
        meta = read_meta(pid)
        script = state.get("script") or {}
        meta.update({
            "title":       script.get("title", meta.get("title")),
            "tags":        script.get("tags", meta.get("tags")),
            "thumb_style": thumb_settings(script)[0],
            "thumb_text":  state.get("thumb_text"),
            "description": state.get("description", meta.get("description")),
            "yt_url":      state.get("yt_url") or meta.get("yt_url"),
        })
        tp = state.get("thumb_path")
        if tp and os.path.exists(tp) and os.path.abspath(tp) != os.path.abspath(lib_path(pid, "thumbnail.jpg")):
            shutil.copy2(tp, lib_path(pid, "thumbnail.jpg"))
            meta["files"]["thumb"] = "thumbnail.jpg"
        with open(lib_path(pid, "script.json"), "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2)
        write_meta(pid, meta)
    except Exception as e:
        log(f"Library sync failed: {e}", "warn")

def list_library():
    items = []
    if os.path.isdir(LIB_DIR):
        for pid in os.listdir(LIB_DIR):
            try: items.append(read_meta(pid))
            except Exception: continue
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items

def series_context(series_name="", limit=8):
    """Recent YAAS and YouTube history plus the next number for this saved series."""
    items = list_library()
    series_key = (series_name or "").strip().casefold()
    series_items = [item for item in items
                    if series_key and str(item.get("series_name") or "").strip().casefold() == series_key]
    episode_numbers = [item["series_episode"] for item in series_items
                       if isinstance(item.get("series_episode"), int) and item["series_episode"] > 0]

    selected, seen = [], set()
    for item in series_items[:limit] + items[:limit]:
        key = item.get("id") or item.get("title") or item.get("topic") or f"item-{len(selected)}"
        if key not in seen:
            selected.append(item)
            seen.add(key)
    selected.sort(key=lambda item: item.get("created_at", ""), reverse=True)

    history = []
    for item in selected:
        research = {}
        if item.get("id"):
            try:
                with open(lib_path(item["id"], "research.json"), encoding="utf-8") as f:
                    research = json.load(f)
            except (OSError, ValueError):
                pass
        episode = item.get("series_episode", research.get("series_episode"))
        key_points = research.get("key_points") or []
        if not isinstance(key_points, list):
            key_points = []
        history.append({
            "title": (item.get("title") or research.get("video_title") or "").strip()[:160],
            "topic": (item.get("topic") or research.get("topic") or item.get("title") or "").strip()[:200],
            "key_points": [str(point).strip()[:180] for point in key_points[:2]],
            "series_name": str(item.get("series_name") or research.get("series_name", ""))[:200],
            "series_episode": episode,
            "series_connection": str(item.get("series_connection") or research.get("series_connection", ""))[:240],
            "next_episode_hint": str(item.get("next_episode_hint") or research.get("next_episode_hint", ""))[:240],
            "published": bool(item.get("yt_url")),
            "created_at": str(item.get("created_at") or ""),
        })

    # Include recent uploads made outside YAAS when the channel stats key is set.
    # Titles still help prevent repeats even when no YAAS research notes exist.
    try:
        from apis import youtube_stats
        if youtube_stats.configured():
            uploads = youtube_stats.channel_stats().get("recent", [])
            known_titles = {str(video["title"]).casefold() for video in history if video.get("title")}
            for video in reversed(uploads[-16:]):
                title = str(video.get("title") or "").strip()
                if not title or title.casefold() in known_titles:
                    continue
                history.append({
                    "title": title[:160], "topic": title[:200], "key_points": [],
                    "series_name": "", "series_episode": None, "series_connection": "",
                    "next_episode_hint": "", "published": True,
                    "created_at": str(video.get("published") or ""),
                })
                known_titles.add(title.casefold())
    except Exception as exc:
        print(f"   ⚠ Could not load recent YouTube uploads for topic history: {exc}")

    history.sort(key=lambda video: video.get("created_at", ""), reverse=True)
    history = history[:16]

    prior_series = next((video for video in history
                         if series_key and str(video["series_name"]).strip().casefold() == series_key), {})
    return {
        "recent_videos": history,
        "next_episode": max(episode_numbers, default=0) + 1 if series_key else None,
        "previous_episode_title": prior_series.get("title", ""),
        "previous_next_step": prior_series.get("next_episode_hint", ""),
    }

@bp.route("/api/library")
def library_index():
    items = list_library()
    today = datetime.now().date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(59, -1, -1)]
    counts = {d: 0 for d in days}
    for m in items:
        d = (m.get("created_at") or "")[:10]
        if d in counts: counts[d] += 1
    return jsonify({
        "items":    items,
        "activity": [{"day": d, "count": counts[d]} for d in days],
        "totals": {
            "videos":   len(items),
            "shorts":   sum(1 for m in items if m.get("video_type") == "shorts"),
            "uploaded": sum(1 for m in items if m.get("yt_url")),
            "minutes":  round(sum((m.get("duration") or 0) for m in items) / 60, 1),
        },
    })

@bp.route("/library/<pid>/<name>")
def library_file(pid, name):
    allowed = {"video.mp4": "video/mp4", "thumbnail.jpg": "image/jpeg",
               "cover.jpg": "image/jpeg", "captions.srt": "text/plain"}
    if name not in allowed: abort(404)
    return send(lib_path(pid, name), allowed[name], f"{pid}-{name}")

@bp.route("/api/library/<pid>/load", methods=["POST"])
def library_load(pid):
    if state["running"]:
        return jsonify({"ok": False, "error": "Pipeline is running"})
    try:
        meta = read_meta(pid)
        with open(lib_path(pid, "script.json"), encoding="utf-8") as f: script = json.load(f)
        with open(lib_path(pid, "research.json"), encoding="utf-8") as f: research = json.load(f)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not load project: {e}"})
    cover = lib_path(pid, "cover.jpg")
    state.update({
        "script":      script,
        "research":    research,
        "video_type":  meta.get("video_type", "normal"),
        "video_path":  lib_path(pid, "video.mp4"),
        "thumb_path":  lib_path(pid, "thumbnail.jpg"),
        "thumb_bg":    None if glob.glob(lib_path(pid, "photos", "*.jpg")) else (cover if os.path.exists(cover) else None),
        "image_map":   {1: sorted(glob.glob(lib_path(pid, "photos", "*.jpg")))},
        "description": with_credit(meta.get("description") or build_description(script, research, meta.get("video_type", "normal"))),
        "yt_url":      meta.get("yt_url"),
        "library_id":  pid,
        "thumb_style": meta.get("thumb_style"),
        "thumb_text":  meta.get("thumb_text"),
        "thumb_bg_index": 0,
        "error":       None,
    })
    return jsonify({"ok": True})

@bp.route("/api/library/<pid>", methods=["DELETE"])
def library_delete(pid):
    path = lib_path(pid)
    if not os.path.isdir(path):
        return jsonify({"ok": False, "error": "Not found"})
    if state.get("library_id") == pid:
        state["library_id"] = None
    shutil.rmtree(path, ignore_errors=True)
    return jsonify({"ok": True})
