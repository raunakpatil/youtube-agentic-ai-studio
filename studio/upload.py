"""Upload blueprint: YouTube sign-in status and publishing (see uploader/youtube.py)."""
import os
import threading

from flask import Blueprint, jsonify, request

import config
from studio.library import sync_library
from studio.state import log, state
from uploader import youtube as yt_uploader

bp = Blueprint("upload", __name__)

def secret_ok():
    try:
        with open(config.YOUTUBE_CLIENT_SECRET, encoding="utf-8") as f:
            return "YOUR_CLIENT_ID" not in f.read()
    except Exception:
        return False

@bp.route("/api/yt-status")
def yt_status():
    return jsonify({"token": yt_uploader.has_token(), "secret": secret_ok()})

@bp.route("/api/upload", methods=["POST"])
def upload_route():
    if state.get("uploading"):
        return jsonify({"ok": False, "error": "Upload already in progress"})
    if not state.get("video_path") or not os.path.exists(state["video_path"]):
        return jsonify({"ok": False, "error": "No video to upload"})
    if not secret_ok():
        return jsonify({"ok": False, "error": "client_secret.json is missing — download it from Google Cloud and save it in the project folder (SETUP.md step 4)"})

    body    = request.get_json(force=True) or {}
    privacy = body.get("privacy", config.VIDEO_PRIVACY)
    publish_at = body.get("publish_at", "").strip()   # RFC 3339 datetime or ""

    def _do_upload():
        state["uploading"]      = True
        state["upload_pct"]     = 0
        state["yt_url"]         = None
        state["upload_warning"] = None
        state["error"]          = None
        try:
            script = state["script"] or {}
            result = yt_uploader.upload_video(
                state["video_path"],
                title=script.get("title", ""),
                description=state.get("description", script.get("description", "")),
                tags=script.get("tags", []),
                privacy=privacy,
                publish_at=publish_at,
                thumb_path=state.get("thumb_path"),
                on_progress=lambda pct: state.__setitem__("upload_pct", pct),
                log=lambda msg: log(msg, "warn"),
            )
            state["yt_url"]         = result["url"]
            state["upload_warning"] = result["thumbnail_error"]
            state["upload_pct"]     = 100
            sync_library()
            log(f"Uploaded! {state['yt_url']}")

        except Exception as e:
            log(f"Upload error: {e}", "error")
            state["error"] = str(e)
        finally:
            state["uploading"] = False

    threading.Thread(target=_do_upload, daemon=True).start()
    return jsonify({"ok": True})
