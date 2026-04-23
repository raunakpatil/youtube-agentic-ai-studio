"""
Review Server
Spins up a local Flask web app so you can watch the video,
read the script, and approve or reject before uploading.
"""
import os
import json
import threading
import webbrowser
import time
from flask import Flask, render_template, jsonify, request, send_file, abort
import config

app = Flask(__name__, template_folder="templates")

# Shared state (set before server starts)
_state = {
    "review_data": {},
    "decision": None,     # "approved" | "rejected"
}


@app.route("/")
def index():
    return render_template("review.html")


@app.route("/api/data")
def get_data():
    data = _state["review_data"]
    # Strip the video path from JSON (serve it via /video endpoint instead)
    safe = {k: v for k, v in data.items() if k != "video_path"}
    return jsonify(safe)


@app.route("/video")
def serve_video():
    path = _state["review_data"].get("video_path", "")
    if path and os.path.exists(path):
        return send_file(path, mimetype="video/mp4")
    abort(404)


@app.route("/api/approve", methods=["POST"])
def approve():
    _state["decision"] = "approved"
    # Give the browser time to get the response before we shut down
    threading.Timer(0.5, _shutdown).start()
    return jsonify({"status": "approved"})


@app.route("/api/reject", methods=["POST"])
def reject():
    _state["decision"] = "rejected"
    threading.Timer(0.5, _shutdown).start()
    return jsonify({"status": "rejected"})


def _shutdown():
    os.kill(os.getpid(), 9)   # hard exit — pipeline catches this


def start_review_server(review_data: dict) -> bool:
    """
    Saves review data, starts Flask, opens the browser, and blocks
    until the user clicks Approve or Reject.
    Returns True if approved, False if rejected.
    """
    _state["review_data"] = review_data

    def open_browser():
        time.sleep(1.8)
        webbrowser.open(f"http://localhost:{config.REVIEW_PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"   → Review dashboard at http://localhost:{config.REVIEW_PORT}")

    try:
        app.run(port=config.REVIEW_PORT, debug=False, use_reloader=False)
    except SystemExit:
        pass

    return _state.get("decision") == "approved"
