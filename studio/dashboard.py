"""Home-screen data: Trend Radar, channel stats and the free-API health panel."""
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

import config
from studio.upload import secret_ok

bp = Blueprint("dashboard", __name__)

@bp.route("/api/trends")
def trends():
    from apis import trends as tr
    if request.args.get("refresh") == "1":
        tr.get_trends.cache_clear()
    return jsonify(tr.get_trends())

@bp.route("/api/channel-stats")
def channel_stats():
    from apis import youtube_stats
    if not youtube_stats.configured():
        return jsonify({"ok": False, "configured": False})
    try:
        return jsonify({"ok": True, "configured": True, **youtube_stats.channel_stats()})
    except Exception as e:
        return jsonify({"ok": False, "configured": True, "error": str(e)[:300]})

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
        P("pixabay", "Pixabay", "Stock photos + video clips", "Media", _real_key(getattr(config, "PIXABAY_API_KEY", "")), False, "https://pixabay.com/api/docs/"),
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
        P("youtube_upload", "YouTube Upload", "OAuth publishing", "Growth", secret_ok(), False, "https://console.cloud.google.com/apis/credentials"),
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

@bp.route("/api/health")
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
