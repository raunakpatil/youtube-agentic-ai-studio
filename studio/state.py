"""
Shared run state for the studio: one video is worked on at a time, so the
pipeline thread and every route read and write this single dict.
Also the live-log queue that /api/stream sends to the browser.
"""
import queue
import threading

log_queue  = queue.Queue()
stop_event = threading.Event()   # set() to request pipeline stop

state = {
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
    "video_map":    {},
    "script":       None,
    "research":     None,
    "yt_url":       None,
    "error":        None,
    "upload_pct":   0,
    "uploading":    False,
    "upload_warning": None,       # e.g. thumbnail refused; the video itself uploaded
    "library_id":   None,         # set once the run is archived to the Library
    "started_at":   None,
}

class Capture:
    """Redirect stdout into the log queue so pipeline prints appear in GUI."""
    def __init__(self, orig): self._orig = orig
    def write(self, t):
        if t.strip(): log_queue.put(("log", t.rstrip()))
        try: self._orig.write(t)
        except UnicodeEncodeError: self._orig.write(t.encode("ascii", "replace").decode())
    def flush(self): self._orig.flush()

def log(msg, level="info"):
    log_queue.put(("log", f"[{level.upper()}] {msg}"))

def stage(name, status):
    state["stages"][name] = status
    log_queue.put(("stage", f"{name}:{status}"))

def is_shorts(script=None):
    script = script if script is not None else (state.get("script") or {})
    return state.get("video_type") == "shorts" or script.get("video_type") == "shorts"
