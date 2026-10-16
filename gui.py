"""
YAAS — youtube-agentic-ai-studio · Desktop GUI
Run:  python gui.py
Open: http://localhost:7070

Replaces pipeline.py + review/app.py entirely.
One page controls everything: dashboard, generate, review, library, upload.
"""
import os, sys, json, queue, threading, time, re, shutil, glob
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)   # relative paths (output/, token file) resolve the same from anywhere

# Module-level imports from agents (sys.path is set above)
from agents.researcher import load_banned_topics, save_banned_topics

from flask import Flask, Response, jsonify, request, send_file, abort

import config

LIB_DIR = os.path.join(config.OUTPUT_DIR, "library")

# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL STATE
# ══════════════════════════════════════════════════════════════════════════════

_log_queue  = queue.Queue()
_stop_event = threading.Event()   # set() to request pipeline stop

_state = {
    "running":        False,
    "stop_requested": False,
    "video_type":     "normal",
    "stages": {
        "research":  "pending",   # pending | running | done | error
        "script":    "pending",
        "images":    "pending",
        "narration": "pending",
        "video":     "pending",
    },
    "video_path":   None,
    "thumb_path":   None,
    "thumb_bg":     None,         # explicit thumbnail background (AI art / library cover)
    "thumb_bg_index": 0,          # which video photo the thumbnail uses
    "thumb_style":  None,         # None → config.THUMB_STYLE
    "thumb_text":   None,         # None → auto from the title
    "audio_path":   None,
    "image_map":    {},
    "script":       None,
    "research":     None,
    "yt_url":       None,
    "error":        None,
    "upload_pct":   0,
    "uploading":    False,
    "library_id":   None,         # set once the run is archived to the Library
    "started_at":   None,
}


# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class _Capture:
    """Redirect stdout into the log queue so pipeline prints appear in GUI."""
    def __init__(self, orig): self._orig = orig
    def write(self, t):
        if t.strip(): _log_queue.put(("log", t.rstrip()))
        try: self._orig.write(t)
        except UnicodeEncodeError: self._orig.write(t.encode("ascii", "replace").decode())
    def flush(self): self._orig.flush()

def _log(msg, level="info"):
    _log_queue.put(("log", f"[{level.upper()}] {msg}"))

def _stage(name, status):
    _state["stages"][name] = status
    _log_queue.put(("stage", f"{name}:{status}"))


# ══════════════════════════════════════════════════════════════════════════════
#  THUMBNAIL GENERATOR  (built-in — no separate file needed)
# ══════════════════════════════════════════════════════════════════════════════

def _thumb_backgrounds(image_map):
    """Every usable background photo from the video, in scene order."""
    paths = []
    for k in sorted((image_map or {}), key=lambda k: int(k)):
        v = image_map[k]
        for p in (v if isinstance(v, list) else [v]):
            if p and os.path.exists(p) and p not in paths:
                paths.append(p)
    return paths


def _thumb_settings(script):
    from video import thumbnail
    style = _state.get("thumb_style") or getattr(config, "THUMB_STYLE", thumbnail.DEFAULT_STYLE)
    text = _state.get("thumb_text") or thumbnail.auto_text(script.get("title", ""))
    return style, text


def _thumb_bg(image_map, bg_override=None):
    if bg_override and os.path.exists(bg_override):
        return bg_override
    bgs = _thumb_backgrounds(image_map)
    return bgs[_state.get("thumb_bg_index", 0) % len(bgs)] if bgs else None


def _is_shorts(script=None):
    script = script if script is not None else (_state.get("script") or {})
    return _state.get("video_type") == "shorts" or script.get("video_type") == "shorts"


def _make_thumbnail(script, image_map, output_dir, bg_override=None):
    """Render thumbnail.jpg in the chosen style — 16:9 for videos, 9:16 for Shorts."""
    from video import thumbnail
    style, text = _thumb_settings(script)
    return thumbnail.render(style, os.path.join(output_dir, "thumbnail.jpg"), text,
                            _thumb_bg(image_map, bg_override), config.brand_text(),
                            portrait=_is_shorts(script))


def _ai_thumbnail_bg(script, research):
    """Generate a text-free thumbnail background with Pollinations (keyless)."""
    from apis.images import pollinations_url
    from apis.http import download
    concept = (research or {}).get("thumbnail_concept") or script.get("title", "")
    portrait = _is_shorts(script)
    space = "empty lower half" if portrait else "empty left third"
    prompt = (f"YouTube thumbnail background art, {concept}, cinematic, dramatic rim lighting, "
              f"high contrast, vivid colors, bold composition, {space}, no text, no letters")
    path = os.path.join(config.OUTPUT_DIR, "thumb_bg_ai.jpg")
    _log("Generating AI thumbnail art (Pollinations)…")
    w, h = (1080, 1920) if portrait else (1280, 720)
    download(pollinations_url(prompt, w, h), path, timeout=120)
    return path


# ══════════════════════════════════════════════════════════════════════════════
#  DESCRIPTION / CHAPTERS BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _ts(secs):
    h, m, s = secs//3600, (secs%3600)//60, secs%60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _load_credits():
    try:
        with open(os.path.join(config.OUTPUT_DIR, "credits.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _credit_lines(credits, detailed=True):
    """Attribution block. CC images (Openverse) are listed individually — that's a licence requirement."""
    if not credits: return []
    sources = sorted({c["source"] for c in credits})
    lines = ["Visuals: " + ", ".join(sources)]
    cc = [c for c in credits if c["source"] == "Openverse"]
    if detailed:
        seen = set()
        for c in cc:
            key = (c.get("author"), c.get("link"))
            if key in seen: continue
            seen.add(key)
            lines.append(f"• “{c.get('author','Unknown')}” — {c.get('license','CC')} — {c.get('link','')}")
    if any(c["source"] == "NASA" for c in credits):
        lines.append("Space imagery courtesy of NASA.")
    if any(c["source"] == "Pollinations AI" for c in credits):
        lines.append("Some visuals are AI-generated.")
    return lines

CREDIT_LINE = "🎬 Made with YAAS by Raunak Patil · https://raunakpatil.com"

def _with_credit(desc):
    """Add the credit to descriptions written before it existed."""
    if getattr(config, "CREDIT_YAAS", True) and "raunakpatil.com" not in (desc or ""):
        return (desc or "").rstrip() + "\n\n" + CREDIT_LINE
    return desc

def _build_description(script, research, video_type: str = "normal"):
    sections = script.get("sections", [])
    is_shorts = video_type == "shorts" or script.get("video_type") == "shorts"

    lines = []
    if research.get("hook_question"): lines += [research["hook_question"], ""]
    if script.get("description"):     lines += [script["description"], ""]
    if research.get("why_now"):       lines += [research["why_now"], ""]

    # Chapters only make sense for videos > ~2 min — never for Shorts
    if not is_shorts:
        chapters, cursor = [], 0
        for s in sections:
            words = len(s.get("narration","").split())
            dur = max(8, int(words/110*60))
            chapters.append({"ts": _ts(cursor), "title": s.get("title","")})
            cursor += dur

        if len(chapters) >= 3:
            lines += ["─"*40, "⏱ CHAPTERS", "─"*40]
            for c in chapters: lines.append(f"{c['ts']} {c['title']}")
            lines.append("")

    if research.get("key_points"):
        lines += ["─"*40, "🧠 WHAT YOU'LL LEARN", "─"*40]
        for p in research["key_points"]: lines.append(f"• {p}")
        lines.append("")

    if is_shorts:
        lines += ["👆 Follow for more mind-bending facts!",
                  "💬 Comment: did this surprise you?", ""]
    else:
        lines += ["─"*40, "🔔 Subscribe for a new mind-bending video every week!",
                  "👍 Like if this made you think differently.",
                  "💬 Drop a comment — we read every one.", ""]

    # Sources from fact grounding (Wikipedia / arXiv)
    sources = (research.get("grounding") or {}).get("sources") or []
    if sources and not is_shorts:
        lines += ["─"*40, "📚 SOURCES", "─"*40]
        for s in sources[:6]:
            lines.append(f"• {s['title']} ({s['source']}) {s['url']}")
        lines.append("")

    tail = []
    tags = script.get("tags", [])
    if tags: tail.append(" ".join(f"#{t.replace(' ','')}" for t in tags[:8]))
    if is_shorts: tail.append("#Shorts #YouTubeShorts")
    if getattr(config, "CREDIT_YAAS", True):
        tail.insert(0, CREDIT_LINE + "\n")

    credits = _load_credits()
    for detailed in (True, False):
        credit = _credit_lines(credits, detailed)
        text = "\n".join(lines + (["─"*40] + credit + [""] if credit else []) + tail)
        if len(text) <= 4900:      # YouTube's limit is 5000
            return text
    return text[:4900]


# ══════════════════════════════════════════════════════════════════════════════
#  LIBRARY  (every finished render is archived to output/library/<id>/)
# ══════════════════════════════════════════════════════════════════════════════

def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "video").lower()).strip("-")[:40] or "video"

def _lib_path(pid, *parts):
    if not re.fullmatch(r"[\w-]+", pid or ""): abort(404)
    return os.path.join(LIB_DIR, pid, *parts)

def _read_meta(pid):
    with open(_lib_path(pid, "meta.json"), encoding="utf-8") as f:
        return json.load(f)

def _write_meta(pid, meta):
    with open(_lib_path(pid, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

def _archive_project():
    """Copy the finished render + metadata into the Library. Copies, never hard-links:
    ffmpeg and PIL overwrite output files in place, which would corrupt a linked copy."""
    script, research = _state.get("script") or {}, _state.get("research") or {}
    if not (_state.get("video_path") and os.path.exists(_state["video_path"])):
        return None
    pid = time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(script.get("title"))
    d = os.path.join(LIB_DIR, pid)
    os.makedirs(d, exist_ok=True)

    def _put(src, name):
        if src and os.path.exists(src):
            shutil.copy2(src, os.path.join(d, name))
            return name
        return None

    files = {
        "video":    _put(_state["video_path"], "video.mp4"),
        "thumb":    _put(_state.get("thumb_path"), "thumbnail.jpg"),
        "captions": _put(os.path.join(config.OUTPUT_DIR, "narration.srt"), "captions.srt"),
    }
    cover = _state.get("thumb_bg") or next((p for v in (_state.get("image_map") or {}).values()
                                            for p in (v if isinstance(v, list) else [v]) if p and os.path.exists(p)), None)
    files["cover"] = _put(cover, "cover.jpg")
    # keep a few of the video's photos so the thumbnail can be redesigned later
    os.makedirs(os.path.join(d, "photos"), exist_ok=True)
    for i, p in enumerate(_thumb_backgrounds(_state.get("image_map"))[:8]):
        shutil.copy2(p, os.path.join(d, "photos", f"{i + 1:02d}.jpg"))
    for name, obj in (("script.json", script), ("research.json", research), ("credits.json", _load_credits())):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)

    try:
        from moviepy.editor import VideoFileClip
        with VideoFileClip(_state["video_path"]) as clip:
            duration = round(clip.duration, 1)
    except Exception:
        duration = None

    meta = {
        "id":          pid,
        "title":       script.get("title", ""),
        "topic":       research.get("topic", ""),
        "video_type":  _state.get("video_type", "normal"),
        "created_at":  datetime.now().isoformat(timespec="seconds"),
        "render_secs": int(time.time() - _state["started_at"]) if _state.get("started_at") else None,
        "duration":    duration,
        "sections":    len(script.get("sections", [])),
        "sources":     len((research.get("grounding") or {}).get("sources") or []),
        "description": _state.get("description", ""),
        "tags":        script.get("tags", []),
        "yt_url":      None,
        "thumb_style": _thumb_settings(script)[0],
        "thumb_text":  _state.get("thumb_text"),
        "files":       files,
    }
    _write_meta(pid, meta)
    _state["library_id"] = pid
    _log(f"Saved to Library: {pid}")
    return pid

def _sync_library():
    """Push review edits (title, description, tags, thumbnail, upload URL) into the Library entry."""
    pid = _state.get("library_id")
    if not pid or not os.path.isdir(_lib_path(pid)):
        return
    try:
        meta = _read_meta(pid)
        script = _state.get("script") or {}
        meta.update({
            "title":       script.get("title", meta.get("title")),
            "tags":        script.get("tags", meta.get("tags")),
            "thumb_style": _thumb_settings(script)[0],
            "thumb_text":  _state.get("thumb_text"),
            "description": _state.get("description", meta.get("description")),
            "yt_url":      _state.get("yt_url") or meta.get("yt_url"),
        })
        tp = _state.get("thumb_path")
        if tp and os.path.exists(tp) and os.path.abspath(tp) != os.path.abspath(_lib_path(pid, "thumbnail.jpg")):
            shutil.copy2(tp, _lib_path(pid, "thumbnail.jpg"))
            meta["files"]["thumb"] = "thumbnail.jpg"
        with open(_lib_path(pid, "script.json"), "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2)
        _write_meta(pid, meta)
    except Exception as e:
        _log(f"Library sync failed: {e}", "warn")

def _list_library():
    items = []
    if os.path.isdir(LIB_DIR):
        for pid in os.listdir(LIB_DIR):
            try: items.append(_read_meta(pid))
            except Exception: continue
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE RUNNER  (runs in background thread)
# ══════════════════════════════════════════════════════════════════════════════

def _run_pipeline(steps: list, topic_override: str = "", video_type: str = "normal",
                  focus_angle: str = "", use_trends: bool = False):
    orig_stdout = sys.stdout
    sys.stdout = _Capture(orig_stdout)
    _state["running"] = True
    _state["error"]   = None
    _state["stop_requested"] = False
    _state["started_at"] = time.time()
    _stop_event.clear()

    def _check_stop(after_stage: str):
        """Raise if user clicked Stop."""
        if _stop_event.is_set():
            raise InterruptedError(f"Stopped by user after {after_stage}")

    try:
        Path(config.OUTPUT_DIR).mkdir(exist_ok=True)
        Path(config.IMAGES_DIR).mkdir(exist_ok=True)

        from agents.researcher   import research_topic
        from agents.scriptwriter import write_script
        from video.narrator      import generate_narration
        from video.stock         import download_images, section_images
        from video.creator       import create_video
        from video.music         import mix_music_with_narration

        # ── Research ──────────────────────────────────────────
        if "research" in steps:
            _stage("research", "running")
            trend_context = None
            if use_trends and not topic_override:
                try:
                    from apis.trends import headlines
                    trend_context = headlines()
                except Exception as e:
                    _log(f"Trend Radar unavailable: {e}", "warn")
            research = research_topic(
                channel_description = config.CHANNEL_DESCRIPTION,
                topic_override      = topic_override,
                focus_angle         = focus_angle,
                trend_context       = trend_context,
            )
            _state["research"] = research
            _state.update(library_id=None, thumb_text=None, thumb_bg_index=0)
            with open(f"{config.OUTPUT_DIR}/research.json", "w", encoding="utf-8") as f:
                json.dump(research, f, indent=2)
            _stage("research", "done")
            _log_queue.put(("research", ""))
            _log(f"Topic: {research['video_title']}")
        else:
            try:
                with open(f"{config.OUTPUT_DIR}/research.json", encoding="utf-8") as f:
                    _state["research"] = json.load(f)
            except: pass

        _check_stop("research")
        research = _state["research"]
        if not research: raise ValueError("No research data — run Research step first.")

        # ── Script ────────────────────────────────────────────
        if "script" in steps:
            _stage("script", "running")
            _log(f"Generating {'Shorts' if video_type == 'shorts' else 'normal'} script…")
            script = write_script(research, video_type=video_type)
            _state["script"] = script
            with open(f"{config.OUTPUT_DIR}/script.json", "w", encoding="utf-8") as f:
                json.dump(script, f, indent=2)
            _stage("script", "done")
            _log(f"Script: {len(script['sections'])} sections")
        else:
            try:
                with open(f"{config.OUTPUT_DIR}/script.json", encoding="utf-8") as f:
                    _state["script"] = json.load(f)
            except: pass

        _check_stop("script")
        script = _state["script"]
        if not script: raise ValueError("No script data — run Script step first.")

        # ── Images ────────────────────────────────────────────
        _state["thumb_bg"] = None
        if "images" in steps:
            _stage("images", "running")
            image_map = download_images(script, config.OUTPUT_DIR)
            _state["image_map"] = image_map
            _stage("images", "done")
        else:
            is_shorts = video_type == "shorts" or script.get("video_type") == "shorts"
            image_map = {}
            for s in script.get("sections", []):
                paths = section_images(config.IMAGES_DIR, s["id"])
                image_map[s["id"]] = paths if (paths or is_shorts) else None
            _state["image_map"] = image_map

        _check_stop("images")

        # ── Narration ─────────────────────────────────────────
        if "narration" in steps:
            _stage("narration", "running")
            audio_path = generate_narration(script, config.OUTPUT_DIR)
            _state["audio_path"] = audio_path
            _stage("narration", "done")
        else:
            ap = os.path.join(config.OUTPUT_DIR, "narration.mp3")
            _state["audio_path"] = ap if os.path.exists(ap) else None

        if not _state["audio_path"] or not os.path.exists(_state["audio_path"]):
            raise FileNotFoundError("narration.mp3 missing — run Narration step.")

        _check_stop("narration")

        # ── Music  (optional, non-blocking) ───────────────────
        final_audio_path = _state["audio_path"]
        if config.MUSIC_ENABLED and "music" in steps:
            _log("Mixing background music from library…")
            mixed_path = os.path.join(config.OUTPUT_DIR, "narration_mixed.mp3")
            final_audio_path = mix_music_with_narration(
                narration_path = _state["audio_path"],
                output_path    = mixed_path,
                music_volume   = getattr(config, "MUSIC_VOLUME", 0.12),
                library_dir    = getattr(config, "MUSIC_LIBRARY_DIR", ""),
            )
            _log("Audio ready (narration + music)")

        _check_stop("music")

        # ── Thumbnail ─────────────────────────────────────────
        _log("Generating thumbnail…")
        try:
            image_map_int = {int(k): v for k, v in _state["image_map"].items()}
            thumb = _make_thumbnail(script, image_map_int, config.OUTPUT_DIR)
            _state["thumb_path"] = thumb
            _log(f"Thumbnail saved: {thumb}")
        except Exception as e:
            _log(f"Thumbnail failed (non-fatal): {e}", "warn")

        _check_stop("thumbnail")

        # ── Video ─────────────────────────────────────────────
        if "video" in steps:
            _stage("video", "running")
            image_map_int = {int(k): v for k, v in _state["image_map"].items()}
            video_path = create_video(
                script, final_audio_path, config.OUTPUT_DIR, image_map_int,
                video_type=video_type
            )
            _state["video_path"] = video_path
            _stage("video", "done")
        else:
            vp_short = os.path.join(config.OUTPUT_DIR, "final_short.mp4")
            vp_norm  = os.path.join(config.OUTPUT_DIR, "final_video.mp4")
            vp = vp_short if os.path.exists(vp_short) else vp_norm
            _state["video_path"] = vp if os.path.exists(vp) else None

        # ── Build description ─────────────────────────────────
        if _state["research"] and _state["script"]:
            _state["description"] = _build_description(
                _state["script"], _state["research"], video_type=video_type)

        # ── Archive to Library ───────────────────────────────
        if "video" in steps:
            try: _archive_project()
            except Exception as e: _log(f"Library archive failed (non-fatal): {e}", "warn")

        _log("Pipeline complete!", "info")
        _log_queue.put(("done", ""))

    except InterruptedError as e:
        _log(f"⏹ {e}", "warn")
        for s in _state["stages"]:
            if _state["stages"][s] == "running":
                _state["stages"][s] = "pending"
        _log_queue.put(("stopped", ""))

    except Exception as e:
        import traceback
        traceback.print_exc(file=orig_stdout)
        _state["error"] = str(e)
        for s in _state["stages"]:
            if _state["stages"][s] == "running":
                _state["stages"][s] = "error"
        _log(f"ERROR: {e}", "error")
        _log_queue.put(("error", str(e)))
    finally:
        _state["running"] = False
        sys.stdout = orig_stdout


# ══════════════════════════════════════════════════════════════════════════════
#  FLASK APP
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__, template_folder="gui_templates")


@app.route("/")
def index():
    with open(os.path.join(ROOT, "gui_templates", "index.html"), encoding="utf-8") as f:
        return f.read()


# ── SSE stream ────────────────────────────────────────────────────────────────

@app.route("/api/stream")
def stream():
    def gen():
        while True:
            try:
                kind, msg = _log_queue.get(timeout=30)
                data = json.dumps({"kind": kind, "msg": msg})
                yield f"data: {data}\n\n"
                if kind in ("done", "error", "stopped"):
                    break
            except queue.Empty:
                yield "data: {\"kind\":\"ping\"}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ── Pipeline control ──────────────────────────────────────────────────────────

@app.route("/api/run", methods=["POST"])
def run_pipeline():
    if _state["running"]:
        return jsonify({"ok": False, "error": "Pipeline already running"})
    body       = request.get_json(force=True) or {}
    steps       = body.get("steps", ["research","script","images","narration","music","video"])
    topic       = body.get("topic", "").strip()
    focus_angle = body.get("focus_angle", "").strip()
    video_type  = body.get("video_type", "normal")
    use_trends  = bool(body.get("use_trends", False))
    for s in steps:
        if s in _state["stages"]: _state["stages"][s] = "pending"
    _state["video_type"] = video_type
    _stop_event.clear()
    t = threading.Thread(target=_run_pipeline,
                         args=(steps, topic, video_type, focus_angle, use_trends), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop_pipeline():
    """Request the pipeline to stop after the current stage finishes."""
    _stop_event.set()
    _state["stop_requested"] = True
    _log("⏹ Stop requested — will halt after current step completes…", "warn")
    return jsonify({"ok": True})


@app.route("/api/status")
def status():
    from agents import gemini_client
    return jsonify({
        "running":        _state["running"],
        "stop_requested": _state.get("stop_requested", False),
        "stages":         _state["stages"],
        "has_video":      bool(_state.get("video_path") and os.path.exists(_state["video_path"])),
        "has_thumb":      bool(_state.get("thumb_path") and os.path.exists(_state["thumb_path"])),
        "has_script":     bool(_state.get("script")),
        "has_captions":   os.path.exists(os.path.join(config.OUTPUT_DIR, "narration.srt")),
        "yt_url":         _state.get("yt_url"),
        "error":          _state.get("error"),
        "upload_pct":     _state.get("upload_pct", 0),
        "uploading":      _state.get("uploading", False),
        "video_type":     _state.get("video_type", "normal"),
        "library_id":     _state.get("library_id"),
        "llm":            gemini_client.last_provider,
        "started_at":     _state.get("started_at"),
        "channel_name":   config.CHANNEL_NAME,
        "model":          config.GEMINI_MODEL if gemini_client.gemini_configured() else "free fallback",
    })


# ── Media serving ─────────────────────────────────────────────────────────────

def _send(path, mimetype, name=None):
    if path and os.path.exists(path):
        dl = request.args.get("download") == "1"
        return send_file(os.path.abspath(path), mimetype=mimetype,
                         as_attachment=dl, download_name=name or os.path.basename(path))
    abort(404)

@app.route("/video")
def serve_video():
    return _send(_state.get("video_path"), "video/mp4",
                 f"{_slug((_state.get('script') or {}).get('title'))}.mp4")

@app.route("/thumbnail")
def serve_thumb():
    return _send(_state.get("thumb_path"), "image/jpeg", "thumbnail.jpg")

@app.route("/thumbnail/<int:ts>")  # cache-busting route
def serve_thumb_ts(ts):
    return serve_thumb()

@app.route("/captions")
def serve_captions():
    return _send(os.path.join(config.OUTPUT_DIR, "narration.srt"), "text/plain", "captions.srt")


# ── Script / description data ─────────────────────────────────────────────────

@app.route("/api/output")
def get_output():
    s = _state.get("script") or {}
    r = _state.get("research") or {}
    return jsonify({
        "title":       s.get("title", ""),
        "description": _state.get("description", _build_description(s, r, _state.get("video_type","normal")) if s and r else ""),
        "tags":        s.get("tags", []),
        "sections":    s.get("sections", []),
        "topic":       r.get("topic", ""),
        "why_now":     r.get("why_now", ""),
        "hook":        r.get("hook_question", ""),
        "key_points":  r.get("key_points", []),
        "audience":    r.get("target_audience", ""),
        "thumbnail_concept": r.get("thumbnail_concept", ""),
        "sources":     (r.get("grounding") or {}).get("sources", []),
        "credits":     _load_credits(),
        "video_type":  _state.get("video_type", "normal"),
    })

@app.route("/api/research")
def get_research():
    r = _state.get("research")
    if not r:
        try:
            with open(f"{config.OUTPUT_DIR}/research.json", encoding="utf-8") as f:
                r = json.load(f)
        except Exception:
            r = {}
    return jsonify({
        "topic":      r.get("topic", ""),
        "title":      r.get("video_title", ""),
        "hook":       r.get("hook_question", ""),
        "why_now":    r.get("why_now", ""),
        "key_points": r.get("key_points", []),
        "sources":    (r.get("grounding") or {}).get("sources", []),
    })

@app.route("/api/save-output", methods=["POST"])
def save_output():
    body = request.get_json(force=True) or {}
    if _state["script"]:
        if "title"       in body: _state["script"]["title"]       = body["title"]
        if "description" in body: _state["script"]["description"] = body["description"]
        if "tags"        in body: _state["script"]["tags"]        = body["tags"]
    if "description" in body:
        _state["description"] = body["description"]
    # Persist script to disk
    if _state["script"]:
        with open(f"{config.OUTPUT_DIR}/script.json", "w", encoding="utf-8") as f:
            json.dump(_state["script"], f, indent=2)
    _sync_library()
    return jsonify({"ok": True})


# ── AI description regeneration ───────────────────────────────────────────────

@app.route("/api/regenerate-description", methods=["POST"])
def regen_description():
    if not _state.get("script") or not _state.get("research"):
        return jsonify({"ok": False, "error": "No script loaded"})
    try:
        from agents.gemini_client import generate
        script   = _state["script"]
        research = _state["research"]
        prompt = f"""Write a compelling YouTube video description for this video.

Title: {script.get('title','')}
Topic: {research.get('topic','')}
Hook: {research.get('hook_question','')}
Key points: {json.dumps(research.get('key_points',[]))}
Tags: {json.dumps(script.get('tags',[]))}

The description should:
- Open with the hook question or a gripping statement
- List what viewers will learn (3-5 bullet points)
- Include a strong CTA to subscribe and comment
- End with hashtags

Return ONLY the description text, no explanation."""
        desc = generate(prompt)
        # Keep the chapters + sources + credits block from the built description
        built = _build_description(script, research, _state.get("video_type", "normal"))
        keep = built[built.find("⏱ CHAPTERS") - 41:] if "⏱ CHAPTERS" in built else ""
        if keep:
            desc = desc.rstrip() + "\n\n" + keep
        _state["description"] = desc
        return jsonify({"ok": True, "description": desc})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Thumbnail designer ────────────────────────────────────────────────────────

PREVIEW_DIR = os.path.join(config.OUTPUT_DIR, "thumb_previews")

def _thumb_info():
    from video import thumbnail
    script = _state.get("script") or {}
    style, text = _thumb_settings(script)
    bgs = _thumb_backgrounds(_state.get("image_map"))
    return {
        "style":       style,
        "text":        text,
        "auto_text":   thumbnail.auto_text(script.get("title", "")),
        "custom_text": bool(_state.get("thumb_text")),
        "styles":      [{"id": k, **v} for k, v in thumbnail.STYLES.items()],
        "photos":      len(bgs),
        "photo_index": (_state.get("thumb_bg_index", 0) % len(bgs) + 1) if bgs else 0,
        "background":  "ai" if (_state.get("thumb_bg") or "").endswith("thumb_bg_ai.jpg") else "photo",
        "portrait":    _is_shorts(script),
    }

@app.route("/api/thumbnail", methods=["GET", "POST"])
def thumbnail_api():
    """GET: current design. POST {style?, text?, bg?: next|prev|photo|ai, previews?}: change + re-render."""
    if request.method == "GET":
        return jsonify(_thumb_info())
    script = _state.get("script")
    if not script:
        return jsonify({"ok": False, "error": "No video loaded"})
    from video import thumbnail
    body = request.get_json(force=True) or {}
    try:
        if body.get("style") in thumbnail.STYLES:
            _state["thumb_style"] = body["style"]
        if "text" in body:
            t = (body.get("text") or "").strip()
            _state["thumb_text"] = t if t and t != thumbnail.auto_text(script.get("title", "")) else None
        bg = body.get("bg")
        if bg == "ai":
            _state["thumb_bg"] = _ai_thumbnail_bg(script, _state.get("research"))
        elif bg in ("next", "prev", "photo"):
            if _state.get("thumb_bg", "") and str(_state["thumb_bg"]).endswith("thumb_bg_ai.jpg"):
                _state["thumb_bg"] = None          # leave AI art, back to photos
            elif bg != "photo":
                _state["thumb_bg_index"] = _state.get("thumb_bg_index", 0) + (1 if bg == "next" else -1)

        _state["thumb_path"] = _make_thumbnail(script, _state.get("image_map") or {},
                                               config.OUTPUT_DIR, _state.get("thumb_bg"))
        if body.get("previews"):
            style, text = _thumb_settings(script)
            src = _thumb_bg(_state.get("image_map") or {}, _state.get("thumb_bg"))
            for sid in thumbnail.STYLES:
                thumbnail.render(sid, os.path.join(PREVIEW_DIR, f"{sid}.jpg"), text, src,
                                 config.brand_text(), portrait=_is_shorts(script),
                                 size=(270, 480) if _is_shorts(script) else (480, 270))
        _sync_library()
        return jsonify({"ok": True, "ts": int(time.time() * 1000), **_thumb_info()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/thumb-preview/<style>")
def thumb_preview(style):
    if not re.fullmatch(r"[a-z]+", style): abort(404)
    return _send(os.path.join(PREVIEW_DIR, f"{style}.jpg"), "image/jpeg")

@app.route("/api/thumbnail-ideas", methods=["POST"])
def thumbnail_ideas():
    if not _state.get("script"):
        return jsonify({"ok": False, "error": "No video loaded"})
    from agents.gemini_client import generate
    from agents.json_utils import extract_json
    s, r = _state["script"], _state.get("research") or {}
    prompt = f"""You write the big text on YouTube thumbnails for a viral science channel.
Video title: {s.get('title','')}
Hook: {r.get('hook_question','')}
Thumbnail concept: {r.get('thumbnail_concept','')}

Write 6 thumbnail overlays. Rules: 2–4 words each, never just repeat the title, create curiosity
(a claim, a number, a question, a warning). Wrap the ONE most powerful word in *stars*.
Examples: "Time *stops* here", "*Nobody* survives this", "It's *already* happening".
Return ONLY JSON: {{"texts": ["...", "..."]}}"""
    try:
        data = extract_json(generate(prompt), "Thumbnail ideas")
        texts = [t.strip() for t in data.get("texts", []) if isinstance(t, str) and t.strip()]
        return jsonify({"ok": True, "texts": texts[:6]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/regenerate-thumbnail", methods=["POST"])
def regen_thumbnail():
    """Older endpoint, kept for compatibility: {mode: stock|ai, title?}."""
    body = request.get_json(force=True) or {}
    if "title" in body and _state.get("script"):
        _state["script"]["title"] = body["title"]
    with app.test_request_context(json={"bg": "ai" if body.get("mode") == "ai" else "photo"}):
        return thumbnail_api()


# ── Title Lab + SEO ───────────────────────────────────────────────────────────

def _primary_keyword():
    r = _state.get("research") or {}
    return r.get("topic") or (_state.get("script") or {}).get("title", "")

@app.route("/api/title-ideas", methods=["POST"])
def title_ideas():
    if not _state.get("script"):
        return jsonify({"ok": False, "error": "No script loaded"})
    from agents.gemini_client import generate
    from agents.json_utils import extract_json
    from apis import seo
    r, s = _state.get("research") or {}, _state["script"]
    keyword = _primary_keyword()
    try:
        searches = seo.keyword_ideas(keyword)["suggestions"][:10]
    except Exception:
        searches = []
    prompt = f"""You are a YouTube packaging expert (think MrBeast's title team).
Video topic: {keyword}
Current title: {s.get('title','')}
Hook: {r.get('hook_question','')}
What people actually search on YouTube: {json.dumps(searches)}

Write 6 alternative titles. Mix styles: question, bold claim, number, "what if", curiosity gap, search-optimised.
Each under 70 characters, no clickbait lies, no ALL CAPS (one emphasised word is fine).
Return ONLY JSON: {{"titles": [{{"title": "...", "style": "question"}}]}}"""
    try:
        data = extract_json(generate(prompt), "Title Lab")
        out = []
        for t in data.get("titles", [])[:8]:
            title = t.get("title", "") if isinstance(t, dict) else str(t)
            if not title: continue
            sc = seo.score(title, _state.get("description", ""), s.get("tags", []), keyword,
                           is_shorts=_state.get("video_type") == "shorts")
            title_pts = sum(c["weight"] for c in sc["checks"][:4] if c["ok"])
            out.append({"title": title, "style": t.get("style", "") if isinstance(t, dict) else "",
                        "score": round(title_pts / 45 * 100)})
        out.sort(key=lambda x: -x["score"])
        return jsonify({"ok": True, "titles": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/seo", methods=["POST"])
def seo_score():
    from apis import seo
    b = request.get_json(force=True) or {}
    return jsonify(seo.score(b.get("title", ""), b.get("description", ""), b.get("tags", []),
                             b.get("keyword") or _primary_keyword(),
                             is_shorts=_state.get("video_type") == "shorts"))

@app.route("/api/keywords")
def keywords():
    from apis import seo
    q = request.args.get("q", "").strip() or _primary_keyword()
    if not q:
        return jsonify({"suggestions": [], "related": [], "seed": ""})
    return jsonify({**seo.keyword_ideas(q), "seed": q})


# ── Trend Radar ───────────────────────────────────────────────────────────────

@app.route("/api/trends")
def trends():
    from apis import trends as tr
    if request.args.get("refresh") == "1":
        tr.get_trends.cache_clear()
    return jsonify(tr.get_trends())


# ── Channel stats (YouTube Data API key) ──────────────────────────────────────

@app.route("/api/channel-stats")
def channel_stats():
    from apis import youtube_stats
    if not youtube_stats.configured():
        return jsonify({"ok": False, "configured": False})
    try:
        return jsonify({"ok": True, "configured": True, **youtube_stats.channel_stats()})
    except Exception as e:
        return jsonify({"ok": False, "configured": True, "error": str(e)[:300]})


# ── API stack health ──────────────────────────────────────────────────────────

def _secret_ok():
    try:
        with open(config.YOUTUBE_CLIENT_SECRET, encoding="utf-8") as f:
            return "YOUR_CLIENT_ID" not in f.read()
    except Exception:
        return False

def _providers():
    from agents.gemini_client import gemini_configured
    from apis import youtube_stats
    from apis.llm import _real_key
    img = getattr(config, "IMAGE_SOURCES", [])
    P = lambda id, name, role, group, ready, keyless, link="": dict(
        id=id, name=name, role=role, group=group, ready=bool(ready), keyless=keyless, link=link)
    return [
        P("gemini", "Gemini", "Research + scripts", "AI", gemini_configured(), False, "https://aistudio.google.com/apikey"),
        P("groq", "Groq", "Fast LLM fallback", "AI", _real_key(getattr(config, "GROQ_API_KEY", "")), False, "https://console.groq.com/keys"),
        P("openrouter", "OpenRouter", "Free-model fallback", "AI", _real_key(getattr(config, "OPENROUTER_API_KEY", "")), False, "https://openrouter.ai/keys"),
        P("pollinations_text", "Pollinations Text", "Keyless LLM fallback", "AI", getattr(config, "KEYLESS_LLM_FALLBACK", True), True, "https://pollinations.ai"),
        P("edge_tts", "Edge TTS", "Neural voiceover", "Media", True, True),
        P("pexels", "Pexels", "Stock photos", "Media", _real_key(config.PEXELS_API_KEY), False, "https://www.pexels.com/api/"),
        P("pixabay", "Pixabay", "Stock photos", "Media", _real_key(getattr(config, "PIXABAY_API_KEY", "")) and "pixabay" in img, False, "https://pixabay.com/api/docs/"),
        P("nasa", "NASA Images", "Public-domain space B-roll", "Media", "nasa" in img, True, "https://images.nasa.gov"),
        P("openverse", "Openverse", "CC-licensed images", "Media", "openverse" in img, True, "https://openverse.org"),
        P("pollinations_img", "Pollinations Image", "AI thumbnails + B-roll", "Media", "pollinations" in img, True, "https://pollinations.ai"),
        P("wikipedia", "Wikipedia", "Fact grounding + trends", "Research", True, True, "https://en.wikipedia.org"),
        P("arxiv", "arXiv", "Papers for grounding + trends", "Research", True, True, "https://arxiv.org"),
        P("google_trends", "Google Trends", "Search spikes", "Research", True, True, "https://trends.google.com"),
        P("hackernews", "Hacker News", "Tech front page", "Research", True, True, "https://news.ycombinator.com"),
        P("spaceflight", "Spaceflight News", "Space + science news", "Research", True, True, "https://spaceflightnewsapi.net"),
        P("yt_suggest", "YouTube Autocomplete", "Keyword research", "Growth", True, True),
        P("datamuse", "Datamuse", "Related keywords", "Growth", True, True, "https://www.datamuse.com/api/"),
        P("youtube_data", "YouTube Data API", "Channel stats", "Growth", youtube_stats.configured(), False, "https://console.cloud.google.com/apis/library/youtube.googleapis.com"),
        P("youtube_upload", "YouTube Upload", "OAuth publishing", "Growth", _secret_ok(), False, "https://console.cloud.google.com/apis/credentials"),
    ]

_PROBES = {
    "pollinations_text": "https://text.pollinations.ai/models",
    "nasa":              "https://images-api.nasa.gov/search?q=moon&page_size=1",
    "openverse":         "https://api.openverse.org/v1/images/?q=moon&page_size=1",
    "wikipedia":         "https://en.wikipedia.org/api/rest_v1/page/summary/Moon",
    "arxiv":             "https://export.arxiv.org/api/query?search_query=all:moon&max_results=1",
    "google_trends":     "https://trends.google.com/trending/rss?geo=US",
    "hackernews":        "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=1",
    "spaceflight":       "https://api.spaceflightnewsapi.net/v4/articles/?limit=1",
    "yt_suggest":        "https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q=moon",
    "datamuse":          "https://api.datamuse.com/words?ml=moon&max=1",
}

@app.route("/api/health")
def health():
    providers = _providers()
    if request.args.get("probe") == "1":
        from apis.http import get
        def _ping(item):
            pid, url = item
            t0 = time.time()
            try:
                get(url, timeout=8)
                return pid, {"ok": True, "ms": int((time.time() - t0) * 1000)}
            except Exception as e:
                return pid, {"ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)[:120]}
        with ThreadPoolExecutor(max_workers=len(_PROBES)) as ex:
            probes = dict(ex.map(_ping, _PROBES.items()))
        for p in providers:
            if p["id"] in probes:
                p["probe"] = probes[p["id"]]
    return jsonify({"providers": providers})


# ── Library ───────────────────────────────────────────────────────────────────

@app.route("/api/library")
def library():
    items = _list_library()
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

@app.route("/library/<pid>/<name>")
def library_file(pid, name):
    allowed = {"video.mp4": "video/mp4", "thumbnail.jpg": "image/jpeg",
               "cover.jpg": "image/jpeg", "captions.srt": "text/plain"}
    if name not in allowed: abort(404)
    return _send(_lib_path(pid, name), allowed[name], f"{pid}-{name}")

@app.route("/api/library/<pid>/load", methods=["POST"])
def library_load(pid):
    if _state["running"]:
        return jsonify({"ok": False, "error": "Pipeline is running"})
    try:
        meta = _read_meta(pid)
        with open(_lib_path(pid, "script.json"), encoding="utf-8") as f: script = json.load(f)
        with open(_lib_path(pid, "research.json"), encoding="utf-8") as f: research = json.load(f)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not load project: {e}"})
    cover = _lib_path(pid, "cover.jpg")
    _state.update({
        "script":      script,
        "research":    research,
        "video_type":  meta.get("video_type", "normal"),
        "video_path":  _lib_path(pid, "video.mp4"),
        "thumb_path":  _lib_path(pid, "thumbnail.jpg"),
        "thumb_bg":    None if glob.glob(_lib_path(pid, "photos", "*.jpg")) else (cover if os.path.exists(cover) else None),
        "image_map":   {1: sorted(glob.glob(_lib_path(pid, "photos", "*.jpg")))},
        "description": _with_credit(meta.get("description") or _build_description(script, research, meta.get("video_type", "normal"))),
        "yt_url":      meta.get("yt_url"),
        "library_id":  pid,
        "thumb_style": meta.get("thumb_style"),
        "thumb_text":  meta.get("thumb_text"),
        "thumb_bg_index": 0,
        "error":       None,
    })
    return jsonify({"ok": True})

@app.route("/api/library/<pid>", methods=["DELETE"])
def library_delete(pid):
    path = _lib_path(pid)
    if not os.path.isdir(path):
        return jsonify({"ok": False, "error": "Not found"})
    if _state.get("library_id") == pid:
        _state["library_id"] = None
    shutil.rmtree(path, ignore_errors=True)
    return jsonify({"ok": True})


# ── YouTube upload ────────────────────────────────────────────────────────────

@app.route("/api/yt-status")
def yt_status():
    token_ok = os.path.exists("youtube_token.pickle")
    return jsonify({"token": token_ok, "secret": _secret_ok()})

@app.route("/api/upload", methods=["POST"])
def upload():
    if _state.get("uploading"):
        return jsonify({"ok": False, "error": "Upload already in progress"})
    if not _state.get("video_path") or not os.path.exists(_state["video_path"]):
        return jsonify({"ok": False, "error": "No video to upload"})
    if not _secret_ok():
        return jsonify({"ok": False, "error": "client_secret.json is still the placeholder — see SETUP.md step 4"})

    body    = request.get_json(force=True) or {}
    privacy = body.get("privacy", config.VIDEO_PRIVACY)
    publish_at = body.get("publish_at", "").strip()   # RFC 3339 datetime or ""

    def _do_upload():
        _state["uploading"]  = True
        _state["upload_pct"] = 0
        _state["yt_url"]     = None
        _state["error"]      = None
        try:
            import pickle as pkl
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request

            TOKEN_FILE = "youtube_token.pickle"
            creds = None
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE, "rb") as f: creds = pkl.load(f)
            if creds and not creds.valid and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(TOKEN_FILE, "wb") as f: pkl.dump(creds, f)
                except Exception:
                    creds = None
            if not creds or not creds.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    config.YOUTUBE_CLIENT_SECRET, config.YOUTUBE_SCOPES)
                creds = flow.run_local_server(port=8080)
                with open(TOKEN_FILE, "wb") as f: pkl.dump(creds, f)

            yt = build("youtube", "v3", credentials=creds)
            script = _state["script"] or {}
            desc   = _state.get("description", script.get("description",""))

            body_data = {
                "snippet": {
                    "title":       script.get("title","")[:100],
                    "description": desc[:5000],
                    "tags":        script.get("tags",[]),
                    "categoryId":  config.VIDEO_CATEGORY_ID,
                },
                "status": {
                    # If scheduling: upload as private, YouTube publishes at publishAt
                    "privacyStatus":           "private" if publish_at else privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }
            if publish_at:
                body_data["status"]["publishAt"] = publish_at

            media = MediaFileUpload(
                _state["video_path"], mimetype="video/mp4",
                resumable=True, chunksize=5*1024*1024,
            )
            req = yt.videos().insert(part=",".join(body_data.keys()),
                                     body=body_data, media_body=media)
            response = None
            while response is None:
                status_chunk, response = req.next_chunk()
                if status_chunk:
                    _state["upload_pct"] = int(status_chunk.progress() * 100)

            video_id = response["id"]

            # Upload thumbnail if available
            if _state.get("thumb_path") and os.path.exists(_state["thumb_path"]):
                try:
                    yt.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(
                            _state["thumb_path"], mimetype="image/jpeg")
                    ).execute()
                except: pass

            _state["yt_url"]     = f"https://www.youtube.com/watch?v={video_id}"
            _state["upload_pct"] = 100
            _sync_library()
            _log(f"Uploaded! {_state['yt_url']}")

        except Exception as e:
            _log(f"Upload error: {e}", "error")
            _state["error"] = str(e)
        finally:
            _state["uploading"] = False

    threading.Thread(target=_do_upload, daemon=True).start()
    return jsonify({"ok": True})


# ── Settings read / write ─────────────────────────────────────────────────────

_MASK = "••••"

def _mask(v):
    v = v or ""
    if not v or v.upper().startswith("YOUR_"): return ""
    return _MASK + v[-4:] if len(v) > 8 else _MASK

# body key → (config attr, type). "env" types are written to .env, never config.py
_SETTINGS = {
    "gemini_key":       ("GEMINI_API_KEY",     "env"),
    "pexels_key":       ("PEXELS_API_KEY",     "env"),
    "pixabay_key":      ("PIXABAY_API_KEY",    "env"),
    "groq_key":         ("GROQ_API_KEY",       "env"),
    "openrouter_key":   ("OPENROUTER_API_KEY", "env"),
    "youtube_key":      ("YOUTUBE_API_KEY",    "env"),
    "youtube_channel":  ("YOUTUBE_CHANNEL_ID", "env_plain"),
    "music_enabled":    ("MUSIC_ENABLED",      bool),
    "music_volume":     ("MUSIC_VOLUME",       float),
    "channel_name":     ("CHANNEL_NAME",       str),
    "show_brand":       ("SHOW_CHANNEL_BRAND", bool),
    "thumb_style":      ("THUMB_STYLE",        str),
    "brand_text":       ("BRAND_TEXT",         str),
    "voice_id":         ("VOICE_ID",           str),
    "voice_rate":       ("VOICE_RATE",         str),
    "voice_pitch":      ("VOICE_PITCH",        str),
    "gemini_model":     ("GEMINI_MODEL",       str),
    "overlay":          ("OVERLAY_OPACITY",    float),
    "kb_start":         ("KB_ZOOM_START",      float),
    "kb_end":           ("KB_ZOOM_END",        float),
    "privacy":          ("VIDEO_PRIVACY",      str),
    "broll_interval":   ("BROLL_INTERVAL",     float),
    "broll_xfade":      ("BROLL_XFADE_DUR",    float),
    "render_preset":    ("RENDER_PRESET",      str),
    "fact_grounding":   ("FACT_GROUNDING",     bool),
    "keyless_llm":      ("KEYLESS_LLM_FALLBACK", bool),
    "credit_yaas":      ("CREDIT_YAAS",        bool),
    "image_sources":    ("IMAGE_SOURCES",      list),
    "trends_geo":       ("TRENDS_GEO",         str),
    "groq_model":       ("GROQ_MODEL",         str),
    "openrouter_model": ("OPENROUTER_MODEL",   str),
}

@app.route("/api/settings")
def get_settings():
    out = {}
    for k, (attr, typ) in _SETTINGS.items():
        val = getattr(config, attr, "")
        out[k] = _mask(val) if typ == "env" else val
    out["channel_desc"]  = config.CHANNEL_DESCRIPTION.strip()
    out["music_library"] = getattr(config, "MUSIC_LIBRARY_DIR", "")
    out["banned_topics"] = load_banned_topics()
    return jsonify(out)

@app.route("/api/save-settings", methods=["POST"])
def save_settings():
    body = request.get_json(force=True) or {}
    env_updates, src_updates = {}, {}

    for k, (attr, typ) in _SETTINGS.items():
        if k not in body or body[k] is None:
            continue
        val = body[k]
        if typ in ("env", "env_plain"):
            val = str(val).strip()
            if val.startswith(_MASK):      # untouched masked key
                continue
            env_updates[attr] = val
        elif typ is bool:
            val = val if isinstance(val, bool) else str(val).lower() in ("1", "true", "yes", "on")
            src_updates[attr] = val
        elif typ is float:
            try: val = float(val)
            except (TypeError, ValueError): continue
            src_updates[attr] = val
        elif typ is list:
            val = [str(v) for v in val] if isinstance(val, list) else [v.strip() for v in str(val).split(",") if v.strip()]
            src_updates[attr] = val
        else:
            src_updates[attr] = str(val)
        setattr(config, attr, val)

    try:
        if env_updates:
            config.save_env(env_updates)

        # Patch non-secret settings in config.py
        cfg_path = os.path.join(ROOT, "config.py")
        with open(cfg_path, encoding="utf-8") as f: src = f.read()
        for attr, val in src_updates.items():
            pat = rf'(?m)^({re.escape(attr)}\s*=\s*)[^\n#]+?(\s*(#[^\n]*)?)$'
            src = re.sub(pat, lambda m, v=val: m.group(1) + repr(v) + m.group(2), src, count=1)

        # Channel description (multiline)
        if "channel_desc" in body:
            cd = body["channel_desc"].replace('"""', "'''")
            config.CHANNEL_DESCRIPTION = cd
            src = re.sub(r'(CHANNEL_DESCRIPTION\s*=\s*)"""[\s\S]*?"""',
                         lambda m: f'CHANNEL_DESCRIPTION = """\n{cd.strip()}\n"""', src, count=1)

        with open(cfg_path, "w", encoding="utf-8") as f: f.write(src)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Saved to memory but disk write failed: {e}"})

    # Settings that change API behaviour invalidate the cached results
    from apis import trends as tr
    tr.get_trends.cache_clear()
    from apis import youtube_stats
    youtube_stats.channel_stats.cache_clear()
    return jsonify({"ok": True})


@app.route("/api/banned-topics")
def get_banned_topics():
    return jsonify({"topics": load_banned_topics()})


@app.route("/api/save-banned-topics", methods=["POST"])
def post_banned_topics():
    body   = request.get_json(force=True) or {}
    topics = body.get("topics", [])
    try:
        save_banned_topics(topics)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import webbrowser
    port = int(os.getenv("STUDIO_PORT", 7070))
    print(f"\n🎬  YAAS — youtube-agentic-ai-studio")
    print(f"   Opening at  http://localhost:{port}\n")
    if os.getenv("STUDIO_NO_BROWSER") != "1":
        threading.Timer(1.4, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(port=port, debug=False, threaded=True, use_reloader=False)
