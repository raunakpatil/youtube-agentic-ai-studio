"""
Shared run state for the studio: one video is worked on at a time, so the
pipeline thread and every route read and write this single dict.
The live log the browser shows is in studio/events.py.
"""
import threading

from studio.events import events

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

def stage(name, status):
    state["stages"][name] = status
    events.emit("stage", f"{name}:{status}")

def is_shorts(script=None):
    script = script if script is not None else (state.get("script") or {})
    return state.get("video_type") == "shorts" or script.get("video_type") == "shorts"
