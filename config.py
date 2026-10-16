import os

# ─────────────────────────────────────────────────────────────────────────────
#  YAAS — youtube-agentic-ai-studio · Configuration
#  API keys live in .env (git-ignored) — copy .env.example to .env, or paste
#  them into the GUI's Settings page, which writes .env for you.
#  All settings are documented. Change only what you need.
# ─────────────────────────────────────────────────────────────────────────────

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_env(path: str = ENV_PATH) -> None:
    """Minimal .env reader (no extra dependency). Real env vars win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def save_env(values: dict, path: str = ENV_PATH) -> None:
    """Update KEY=value pairs in .env, keeping comments and unrelated keys."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    remaining = dict(values)
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and k in remaining:
            lines[i] = f"{k}={remaining.pop(k)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


_load_env()

# ─────────────────────────────────────────
#  API Keys  (all free-tier — only Gemini is recommended; the rest are optional)
# ─────────────────────────────────────────
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",     "")   # aistudio.google.com/apikey
PEXELS_API_KEY     = os.getenv("PEXELS_API_KEY",     "")   # pexels.com/api
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")   # optional, unused by default

# Optional free keys — each one unlocks an extra provider
PIXABAY_API_KEY    = os.getenv("PIXABAY_API_KEY",    "")   # pixabay.com/api/docs — more stock images
GROQ_API_KEY       = os.getenv("GROQ_API_KEY",       "")   # console.groq.com — fast LLM fallback
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")   # openrouter.ai — free LLM fallback
YOUTUBE_API_KEY    = os.getenv("YOUTUBE_API_KEY",    "")   # console.cloud.google.com — channel stats
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")   # UC… id or @handle

# Settings the GUI stores in .env rather than in this file
ENV_KEYS = [
    "GEMINI_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "GROQ_API_KEY",
    "OPENROUTER_API_KEY", "YOUTUBE_API_KEY", "YOUTUBE_CHANNEL_ID",
]

# ─────────────────────────────────────────
#  Free API stack  (keyless — work out of the box)
# ─────────────────────────────────────────
# Ground every script in real facts from Wikipedia + arXiv, and cite them
FACT_GROUNDING = True

# When Gemini has no key or runs out of quota: Groq → OpenRouter → Pollinations
# (Pollinations is keyless, so the pipeline never dead-ends)
KEYLESS_LLM_FALLBACK = True
GROQ_MODEL           = "llama-3.3-70b-versatile"
OPENROUTER_MODEL     = "meta-llama/llama-3.3-70b-instruct:free"

# Image sources tried after Pexels, in order:
#   pixabay (key) · nasa (public domain, space topics) · openverse (CC) · pollinations (AI)
IMAGE_SOURCES = ["pixabay", "nasa", "openverse", "pollinations"]

# Trend Radar — Google Trends region and arXiv fields to watch
TRENDS_GEO       = "US"
ARXIV_CATEGORIES = ["astro-ph.CO", "gr-qc", "quant-ph", "cs.AI", "q-bio.NC"]

# ─────────────────────────────────────────
#  Your Channel Identity
#  The more specific you are, the better the AI's topic suggestions.
# ─────────────────────────────────────────
CHANNEL_DESCRIPTION = """
A mind-bending science and technology channel in the style of Vsauce, Veritasium, and Kurzgesagt.
We focus heavily on deep, existential "What If" scenarios, the extreme future of Artificial Intelligence,
theoretical physics, and mind-expanding thought experiments.
Every video should explore the absolute limits of science, space, or tech, making the viewer question reality.
Target audience: highly curious thinkers who want their minds blown by deep scientific and philosophical dives.
"""
CHANNEL_NAME = "My AI Channel"   # shown on-screen and in upload metadata

# On-video branding: the "▶ CHANNEL NAME" tag in the hook and on Shorts,
# plus the channel line on thumbnails. Leave BRAND_TEXT empty to use CHANNEL_NAME.
SHOW_CHANNEL_BRAND = True
BRAND_TEXT         = ""

# Default thumbnail style: "impact" | "cinematic" | "split" | "studio"
# (you can switch per video on the Review page)
THUMB_STYLE        = "impact"

# Adds "Made with YAAS by Raunak Patil · https://raunakpatil.com" to descriptions
CREDIT_YAAS        = True


def brand_text() -> str:
    """The on-video brand label, or "" when branding is switched off."""
    if not SHOW_CHANNEL_BRAND:
        return ""
    return (BRAND_TEXT or CHANNEL_NAME or "").strip()

# ─────────────────────────────────────────
#  Voice (Edge TTS — free, no API key)
#  Voices confirmed to emit word-level timing (needed for caption sync):
#    en-GB-RyanNeural     — British, deep, cinematic
#    en-US-AndrewNeural   — US, warm, authoritative  ← default
#    en-US-BrianNeural    — US, calm, documentary
#    en-US-GuyNeural      — US, clear, neutral
# ─────────────────────────────────────────
VOICE_ID    = "en-US-AndrewNeural"
VOICE_RATE  = "-5%"     # slow down slightly for narration feel
VOICE_PITCH = "-3Hz"    # slightly deeper = more cinematic

# ─────────────────────────────────────────
#  AI Model
#  Starting model for the fallback chain — the system auto-switches
#  through all models below if quota or errors are hit.
#  Change this in the GUI under Settings → AI Model, or here directly.
#  Options (free tier):
#    gemini-2.5-flash        — highest quality   (500 req/day)
#    gemma-4-31b-it          — Gemma 4 31B       (500 req/day)
#    gemini-2.0-flash        — recommended       (1500 req/day)  ← default
#    gemini-2.0-flash-lite   — fastest           (1500 req/day)
#    gemini-1.5-flash-001    — reliable fallback (1500 req/day)
# ─────────────────────────────────────────
GEMINI_MODEL = "gemini-2.0-flash"

# ─────────────────────────────────────────
#  Video Dimensions
# ─────────────────────────────────────────
VIDEO_WIDTH  = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS    = 24

# YouTube Shorts dimensions (9:16 vertical)
SHORTS_WIDTH  = 1080
SHORTS_HEIGHT = 1920
SHORTS_FPS    = 30

# ─── Visual Style ───────────────────────
# Ken Burns effect: how much to zoom/pan each image
KB_ZOOM_START = 1.00    # starting scale (1.0 = no zoom)
KB_ZOOM_END   = 1.10    # ending scale   (1.1 = 10% zoom in)

# Image crossfade duration (seconds)
# 0.0 = instant cut  |  0.5 = snappy  |  0.7 = smooth  |  1.2 = dreamy
CROSSFADE_DURATION = 0.7

# Normal video B-roll cycling
BROLL_INTERVAL  = 10.0   # seconds each image stays on screen
BROLL_XFADE_DUR =  1.2   # crossfade duration (must be < BROLL_INTERVAL)

# Render quality preset (ffmpeg libx264)
# "ultrafast" = fastest/largest  |  "veryfast" = recommended  |  "medium" = best quality
RENDER_PRESET = "ultrafast"

# Overlay opacity: lower = more image visible but text harder to read (0–1)
OVERLAY_OPACITY = 0.62

# Colour palette — customise to match your brand
COLORS = {
    "background": (10,  10,  20),
    "overlay":    (0,   0,   0),
    "primary":    (99,  102, 241),   # indigo
    "accent":     (167, 139, 250),   # purple
    "highlight":  (251, 191,  36),   # amber
    "white":      (255, 255, 255),
    "light":      (199, 210, 254),   # indigo-200
    "success":    (52,  211, 153),
    "red":        (239,  68,  68),
}

# Fonts — add your own .ttf paths for best results; system falls back gracefully
FONT_PATHS = {
    "bold":    [
        "C:/Windows/Fonts/Impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "regular": [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "light":   [
        "C:/Windows/Fonts/segoeuil.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}

# ─────────────────────────────────────────
#  Review Server
# ─────────────────────────────────────────
REVIEW_PORT = 5050

# ─────────────────────────────────────────
#  YouTube Upload
# ─────────────────────────────────────────
YOUTUBE_CLIENT_SECRET = "client_secret.json"   # OAuth credentials file (see SETUP.md)
YOUTUBE_SCOPES        = ["https://www.googleapis.com/auth/youtube.upload"]
VIDEO_CATEGORY_ID     = "27"       # 27 = Education
VIDEO_PRIVACY         = "public"   # "public" | "unlisted" | "private"

# ─────────────────────────────────────────
#  Background Music
#  Drop MP3/WAV files into the  music library/  folder.
#  Tracks are shuffled and looped automatically to match video length.
# ─────────────────────────────────────────
MUSIC_ENABLED     = True
MUSIC_VOLUME      = 0.12          # 0.0–1.0  (0.12 = subtle underscore)
MUSIC_LIBRARY_DIR = os.path.join(os.path.dirname(__file__), "music library")

# ─────────────────────────────────────────
#  Paths  (do not change unless you know what you're doing)
# ─────────────────────────────────────────
OUTPUT_DIR   = "output"
IMAGES_DIR   = "output/images"
