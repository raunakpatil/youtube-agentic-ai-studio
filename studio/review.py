"""
Review & publish blueprint: script/description data, the thumbnail designer,
and the Title Lab / SEO tools.
"""
import json
import os
import re
import time

from flask import Blueprint, abort, jsonify, request

import config
from studio.description import build_description, load_credits
from studio.files import send
from studio.library import sync_library
from studio.state import is_shorts, state
from studio.thumbs import ai_thumbnail_bg, make_thumbnail, thumb_backgrounds, thumb_bg, thumb_settings

bp = Blueprint("review", __name__)

@bp.route("/thumbnail")
def serve_thumb():
    return send(state.get("thumb_path"), "image/jpeg", "thumbnail.jpg")

@bp.route("/thumbnail/<int:ts>")  # cache-busting route
def serve_thumb_ts(ts):
    return serve_thumb()

@bp.route("/api/output")
def get_output():
    s = state.get("script") or {}
    r = state.get("research") or {}
    return jsonify({
        "title":       s.get("title", ""),
        "description": state.get("description", build_description(s, r, state.get("video_type","normal")) if s and r else ""),
        "tags":        s.get("tags", []),
        "sections":    s.get("sections", []),
        "topic":       r.get("topic", ""),
        "why_now":     r.get("why_now", ""),
        "hook":        r.get("hook_question", ""),
        "key_points":  r.get("key_points", []),
        "audience":    r.get("target_audience", ""),
        "thumbnail_concept": r.get("thumbnail_concept", ""),
        "sources":     (r.get("grounding") or {}).get("sources", []),
        "credits":     load_credits(),
        "video_type":  state.get("video_type", "normal"),
    })

@bp.route("/api/research")
def get_research():
    r = state.get("research")
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

@bp.route("/api/save-output", methods=["POST"])
def save_output():
    body = request.get_json(force=True) or {}
    if state["script"]:
        if "title"       in body: state["script"]["title"]       = body["title"]
        if "description" in body: state["script"]["description"] = body["description"]
        if "tags"        in body: state["script"]["tags"]        = body["tags"]
    if "description" in body:
        state["description"] = body["description"]
    # Persist script to disk
    if state["script"]:
        with open(f"{config.OUTPUT_DIR}/script.json", "w", encoding="utf-8") as f:
            json.dump(state["script"], f, indent=2)
    sync_library()
    return jsonify({"ok": True})

@bp.route("/api/regenerate-description", methods=["POST"])
def regen_description():
    if not state.get("script") or not state.get("research"):
        return jsonify({"ok": False, "error": "No script loaded"})
    try:
        from agents.gemini_client import generate
        script   = state["script"]
        research = state["research"]
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
        built = build_description(script, research, state.get("video_type", "normal"))
        keep = built[built.find("⏱ CHAPTERS") - 41:] if "⏱ CHAPTERS" in built else ""
        if keep:
            desc = desc.rstrip() + "\n\n" + keep
        state["description"] = desc
        return jsonify({"ok": True, "description": desc})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

PREVIEW_DIR = os.path.join(config.OUTPUT_DIR, "thumb_previews")

def _thumb_info():
    from video import thumbnail
    script = state.get("script") or {}
    style, text = thumb_settings(script)
    bgs = thumb_backgrounds(state.get("image_map"))
    return {
        "style":       style,
        "text":        text,
        "auto_text":   thumbnail.auto_text(script.get("title", "")),
        "custom_text": bool(state.get("thumb_text")),
        "styles":      [{"id": k, **v} for k, v in thumbnail.STYLES.items()],
        "photos":      len(bgs),
        "photo_index": (state.get("thumb_bg_index", 0) % len(bgs) + 1) if bgs else 0,
        "background":  "ai" if (state.get("thumb_bg") or "").endswith("thumb_bg_ai.jpg") else "photo",
        "portrait":    is_shorts(script),
    }

@bp.route("/api/thumbnail", methods=["GET", "POST"])
def thumbnail_api():
    """GET: current design. POST {style?, text?, bg?: next|prev|photo|ai, previews?}: change + re-render."""
    if request.method == "GET":
        return jsonify(_thumb_info())
    return jsonify(_update_thumbnail(request.get_json(force=True) or {}))

def _update_thumbnail(body: dict) -> dict:
    script = state.get("script")
    if not script:
        return {"ok": False, "error": "No video loaded"}
    from video import thumbnail
    try:
        if body.get("style") in thumbnail.STYLES:
            state["thumb_style"] = body["style"]
        if "text" in body:
            t = (body.get("text") or "").strip()
            state["thumb_text"] = t if t and t != thumbnail.auto_text(script.get("title", "")) else None
        bg = body.get("bg")
        if bg == "ai":
            state["thumb_bg"] = ai_thumbnail_bg(script, state.get("research"))
        elif bg in ("next", "prev", "photo"):
            if state.get("thumb_bg", "") and str(state["thumb_bg"]).endswith("thumb_bg_ai.jpg"):
                state["thumb_bg"] = None          # leave AI art, back to photos
            elif bg != "photo":
                state["thumb_bg_index"] = state.get("thumb_bg_index", 0) + (1 if bg == "next" else -1)

        state["thumb_path"] = make_thumbnail(script, state.get("image_map") or {},
                                             config.OUTPUT_DIR, state.get("thumb_bg"))
        if body.get("previews"):
            style, text = thumb_settings(script)
            src = thumb_bg(state.get("image_map") or {}, state.get("thumb_bg"))
            for sid in thumbnail.STYLES:
                thumbnail.render(sid, os.path.join(PREVIEW_DIR, f"{sid}.jpg"), text, src,
                                 config.brand_text(), portrait=is_shorts(script),
                                 size=(270, 480) if is_shorts(script) else (480, 270))
        sync_library()
        return {"ok": True, "ts": int(time.time() * 1000), **_thumb_info()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@bp.route("/thumb-preview/<style>")
def thumb_preview(style):
    if not re.fullmatch(r"[a-z]+", style): abort(404)
    return send(os.path.join(PREVIEW_DIR, f"{style}.jpg"), "image/jpeg")

@bp.route("/api/thumbnail-ideas", methods=["POST"])
def thumbnail_ideas():
    if not state.get("script"):
        return jsonify({"ok": False, "error": "No video loaded"})
    from agents.gemini_client import generate
    from agents.json_utils import extract_json
    s, r = state["script"], state.get("research") or {}
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

@bp.route("/api/regenerate-thumbnail", methods=["POST"])
def regen_thumbnail():
    """Older endpoint, kept for compatibility: {mode: stock|ai, title?}."""
    body = request.get_json(force=True) or {}
    if "title" in body and state.get("script"):
        state["script"]["title"] = body["title"]
    return jsonify(_update_thumbnail({"bg": "ai" if body.get("mode") == "ai" else "photo"}))

def _primary_keyword():
    r = state.get("research") or {}
    return r.get("topic") or (state.get("script") or {}).get("title", "")

@bp.route("/api/title-ideas", methods=["POST"])
def title_ideas():
    if not state.get("script"):
        return jsonify({"ok": False, "error": "No script loaded"})
    from agents.gemini_client import generate
    from agents.json_utils import extract_json
    from apis import seo
    r, s = state.get("research") or {}, state["script"]
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
            sc = seo.score(title, state.get("description", ""), s.get("tags", []), keyword,
                           is_shorts=state.get("video_type") == "shorts")
            title_pts = sum(c["weight"] for c in sc["checks"][:4] if c["ok"])
            out.append({"title": title, "style": t.get("style", "") if isinstance(t, dict) else "",
                        "score": round(title_pts / 45 * 100)})
        out.sort(key=lambda x: -x["score"])
        return jsonify({"ok": True, "titles": out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@bp.route("/api/seo", methods=["POST"])
def seo_score():
    from apis import seo
    b = request.get_json(force=True) or {}
    return jsonify(seo.score(b.get("title", ""), b.get("description", ""), b.get("tags", []),
                             b.get("keyword") or _primary_keyword(),
                             is_shorts=state.get("video_type") == "shorts"))

@bp.route("/api/keywords")
def keywords():
    from apis import seo
    q = request.args.get("q", "").strip() or _primary_keyword()
    if not q:
        return jsonify({"suggestions": [], "related": [], "seed": ""})
    return jsonify({**seo.keyword_ideas(q), "seed": q})
