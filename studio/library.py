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
