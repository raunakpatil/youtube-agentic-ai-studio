"""Settings blueprint: keys go to .env, everything else to settings.json."""
from flask import Blueprint, jsonify, request

import config
from agents.researcher import load_banned_topics, save_banned_topics

bp = Blueprint("settings", __name__)

_MASK = "••••"

def _mask(v):
    v = v or ""
    if not v or v.upper().startswith("YOUR_"): return ""
    return _MASK + v[-4:] if len(v) > 8 else _MASK

# body key → (config attr, type). "env" types are written to .env; the rest to
# settings.json (config.save_settings). config.py is never written.
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

@bp.route("/api/settings")
def get_settings():
    out = {}
    for k, (attr, typ) in _SETTINGS.items():
        val = getattr(config, attr, "")
        out[k] = _mask(val) if typ == "env" else val
    out["channel_desc"]  = config.CHANNEL_DESCRIPTION.strip()
    out["music_library"] = getattr(config, "MUSIC_LIBRARY_DIR", "")
    out["banned_topics"] = load_banned_topics()
    return jsonify(out)

@bp.route("/api/save-settings", methods=["POST"])
def save_settings_route():
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

    if body.get("channel_desc") is not None:
        cd = str(body["channel_desc"]).strip()
        src_updates["CHANNEL_DESCRIPTION"] = config.CHANNEL_DESCRIPTION = cd

    try:
        if env_updates:
            config.save_env(env_updates)
        if src_updates:
            config.save_settings(src_updates)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Saved to memory but disk write failed: {e}"})

    # Settings that change API behaviour invalidate the cached results
    from apis import trends as tr
    tr.get_trends.cache_clear()
    from apis import youtube_stats
    youtube_stats.channel_stats.cache_clear()
    return jsonify({"ok": True})

@bp.route("/api/banned-topics")
def get_banned_topics():
    return jsonify({"topics": load_banned_topics()})

@bp.route("/api/save-banned-topics", methods=["POST"])
def post_banned_topics():
    body   = request.get_json(force=True) or {}
    topics = body.get("topics", [])
    try:
        save_banned_topics(topics)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def import_settings(path):
    """`python gui.py --import-settings old_config.py`: carry over settings an older
    YAAS saved into config.py. The file is parsed, never run."""
    values = config.import_legacy_config(path)
    if not values:
        print(f"No changed settings found in {path}; nothing to import.")
        return
    config.save_settings(values)
    print(f"Imported {len(values)} setting(s) into {config.SETTINGS_PATH}:")
    for k in sorted(values):
        print(f"  {k}")
