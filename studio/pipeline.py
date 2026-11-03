"""Pipeline blueprint: the page itself, starting/stopping runs, live progress, status."""
import os
import threading

from flask import Blueprint, Response, current_app, jsonify, request

import config
from studio.files import send, slug
from studio.runner import run_pipeline_thread
from studio.events import events, log
from studio.state import state, stop_event

bp = Blueprint("pipeline", __name__)
_start_lock = threading.Lock()     # two quick clicks must not start two runs
PING_SECS = 15

@bp.route("/")
def index():
    with open(os.path.join(current_app.root_path, "templates", "index.html"), encoding="utf-8") as f:
        return f.read()

@bp.route("/api/stream")
def stream():
    """
    Server-sent events for the live log. Stays open across runs; each tab keeps
    its own position (see studio/events.py), so tabs never take each other's
    messages. A reconnect resumes from Last-Event-ID; a new tab replays the
    current run.
    """
    after = events.cursor(request.headers.get("Last-Event-ID"))

    def gen():
        nonlocal after
        yield "retry: 3000\n\n"
        while True:
            batch = events.wait(after, timeout=PING_SECS)
            if not batch:
                yield ": ping\n\n"          # comment line: keeps the connection alive
                continue
            for event in batch:
                yield events.sse(event)
            after = batch[-1]["id"]
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@bp.route("/api/run", methods=["POST"])
def start_run():
    body       = request.get_json(force=True) or {}
    steps       = body.get("steps", ["research","script","images","narration","music","video"])
    topic       = body.get("topic", "").strip()
    focus_angle = body.get("focus_angle", "").strip()
    video_type  = body.get("video_type", "normal")
    use_trends  = bool(body.get("use_trends", False))
    with _start_lock:
        if state["running"]:
            return jsonify({"ok": False, "error": "Pipeline already running"})
        state["running"] = True
        for s in steps:
            if s in state["stages"]: state["stages"][s] = "pending"
        state["video_type"] = video_type
        stop_event.clear()
        events.new_run()
        t = threading.Thread(target=run_pipeline_thread, name="yaas-pipeline",
                             args=(steps, topic, video_type, focus_angle, use_trends), daemon=True)
        t.start()
    return jsonify({"ok": True})

@bp.route("/api/stop", methods=["POST"])
def stop_pipeline():
    """Request the pipeline to stop after the current stage finishes."""
    stop_event.set()
    state["stop_requested"] = True
    log("⏹ Stop requested — will halt after current step completes…", "warn")
    return jsonify({"ok": True})

@bp.route("/api/status")
def status_route():
    from agents import gemini_client
    return jsonify({
        "running":        state["running"],
        "stop_requested": state.get("stop_requested", False),
        "stages":         state["stages"],
        "has_video":      bool(state.get("video_path") and os.path.exists(state["video_path"])),
        "has_thumb":      bool(state.get("thumb_path") and os.path.exists(state["thumb_path"])),
        "has_script":     bool(state.get("script")),
        "has_captions":   os.path.exists(os.path.join(config.OUTPUT_DIR, "narration.srt")),
        "yt_url":         state.get("yt_url"),
        "error":          state.get("error"),
        "upload_pct":     state.get("upload_pct", 0),
        "uploading":      state.get("uploading", False),
        "upload_warning": state.get("upload_warning"),
        "video_type":     state.get("video_type", "normal"),
        "library_id":     state.get("library_id"),
        "llm":            gemini_client.last_provider,
        "started_at":     state.get("started_at"),
        "channel_name":   config.CHANNEL_NAME,
        "model":          config.GEMINI_MODEL if gemini_client.gemini_configured() else "free fallback",
    })

@bp.route("/video")
def serve_video():
    return send(state.get("video_path"), "video/mp4",
                f"{slug((state.get('script') or {}).get('title'))}.mp4")

@bp.route("/captions")
def serve_captions():
    return send(os.path.join(config.OUTPUT_DIR, "narration.srt"), "text/plain", "captions.srt")
