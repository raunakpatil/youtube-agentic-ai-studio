"""Thumbnail rendering for the current video (designs live in video/thumbnail.py)."""
import os

import config
from studio.state import is_shorts, log, state

def thumb_backgrounds(image_map):
    """Every usable background photo from the video, in scene order."""
    paths = []
    for k in sorted((image_map or {}), key=lambda k: int(k)):
        v = image_map[k]
        for p in (v if isinstance(v, list) else [v]):
            if p and os.path.exists(p) and p not in paths:
                paths.append(p)
    return paths

def thumb_settings(script):
    from video import thumbnail
    style = state.get("thumb_style") or getattr(config, "THUMB_STYLE", thumbnail.DEFAULT_STYLE)
    text = state.get("thumb_text") or thumbnail.auto_text(script.get("title", ""))
    return style, text

def thumb_bg(image_map, bg_override=None):
    if bg_override and os.path.exists(bg_override):
        return bg_override
    bgs = thumb_backgrounds(image_map)
    return bgs[state.get("thumb_bg_index", 0) % len(bgs)] if bgs else None

def make_thumbnail(script, image_map, output_dir, bg_override=None):
    """Render thumbnail.jpg in the chosen style — 16:9 for videos, 9:16 for Shorts."""
    from video import thumbnail
    style, text = thumb_settings(script)
    return thumbnail.render(style, os.path.join(output_dir, "thumbnail.jpg"), text,
                            thumb_bg(image_map, bg_override), config.brand_text(),
                            portrait=is_shorts(script))

def ai_thumbnail_bg(script, research):
    """Generate a text-free thumbnail background with Pollinations (keyless)."""
    from apis.images import pollinations_url
    from apis.http import download
    concept = (research or {}).get("thumbnail_concept") or script.get("title", "")
    portrait = is_shorts(script)
    space = "empty lower half" if portrait else "empty left third"
    prompt = (f"YouTube thumbnail background art, {concept}, cinematic, dramatic rim lighting, "
              f"high contrast, vivid colors, bold composition, {space}, no text, no letters")
    path = os.path.join(config.OUTPUT_DIR, "thumb_bg_ai.jpg")
    log("Generating AI thumbnail art (Pollinations)…")
    w, h = (1080, 1920) if portrait else (1280, 720)
    download(pollinations_url(prompt, w, h), path, timeout=120)
    from apis.images import strip_pollinations_logo
    strip_pollinations_logo(path)
    return path
