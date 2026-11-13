"""
Research Agent — uses shared Gemini client with model fallback chain.
Banned topics are read from banned_topics.txt (one topic per line) in the
project root. Edit that file — or use the GUI textarea — instead of changing
Python code.
"""
import os
import random
import time
import config
from agents.gemini_client import generate
from agents.json_utils import extract_json

# Path to the banned-topics file (sits next to this package's parent directory)
_BANNED_TOPICS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "banned_topics.txt",
)

_BUILTIN_BANNED = [
    "The Boltzmann Brain",
    "Simulation Theory",
    "Quantum Immortality",
]

# All available focus angles — used by researcher AND exposed to the GUI
FOCUS_ANGLES = [
    "Theoretical Physics & Time Travel",
    "The Dark Forest Theory & Aliens",
    "Existential Human Psychology & Illusions",
    "Frightening AI Futures & Simulation Theory",
    "Mind-bending Mathematical Paradoxes",
    "The limits of Human Biology & Immortality",
    "Quantum Mechanics & Alternate Realities",
    "Cosmic scale, Black Holes, and the end of the Universe",
    "Neuroscience & the Mystery of Consciousness",
    "Ancient Civilisations & Lost History",
    "Cutting-edge Biotechnology & Genetic Engineering",
    "The Future of Space Colonisation",
]


def load_banned_topics() -> list:
    """
    Return the combined list of banned topics.
    Built-in list is always included; file entries are appended.
    Returns an empty-safe list — never raises.
    """
    topics = list(_BUILTIN_BANNED)
    try:
        if os.path.exists(_BANNED_TOPICS_FILE):
            with open(_BANNED_TOPICS_FILE, encoding="utf-8") as f:
                for line in f:
                    t = line.strip()
                    if t and not t.startswith("#") and t not in topics:
                        topics.append(t)
    except Exception as e:
        print(f"   ⚠ Could not read banned_topics.txt: {e}")
    return topics


def save_banned_topics(topics: list) -> None:
    """
    Write the user-managed portion of the banned list to banned_topics.txt.
    Built-in topics are excluded from the file (they're always applied anyway).
    """
    user_topics = [t for t in topics if t not in _BUILTIN_BANNED and t.strip()]
    with open(_BANNED_TOPICS_FILE, "w", encoding="utf-8") as f:
        f.write("# One banned topic per line. Lines starting with # are comments.\n")
        f.write("# Built-in banned: The Boltzmann Brain, Simulation Theory, Quantum Immortality\n")
        f.write("# Add topics here after you make a video about them.\n\n")
        for t in user_topics:
            f.write(t + "\n")


def _grounding(topic: str) -> dict:
    """Wikipedia + arXiv background facts for a topic (empty if disabled/offline)."""
    if not getattr(config, "FACT_GROUNDING", True):
        return {"facts": "", "sources": []}
    from apis.knowledge import gather_context
    print(f"   → Grounding facts: Wikipedia + arXiv for \"{topic[:60]}\"…")
    ctx = gather_context(topic)
    print(f"   → {len(ctx['sources'])} sources found")
    return ctx


def _parse(raw: str) -> dict:
    data = extract_json(raw, "Researcher")
    for field in ["topic", "video_title", "key_points", "tags"]:
        if field not in data:
            raise ValueError(f"Research JSON missing field: '{field}'")
    return data


def _episode_history_text(context: dict) -> str:
    lines = []
    for video in (context.get("recent_videos") or [])[:16]:
        parts = []
        if video.get("series_episode"):
            parts.append(f"episode {video['series_episode']} of {video.get('series_name') or 'the series'}")
        parts.append("published" if video.get("published") else "saved render")
        if video.get("title"):
            parts.append(f"title: {video['title']}")
        if video.get("topic"):
            parts.append(f"topic: {video['topic']}")
        points = video.get("key_points") or []
        if points:
            parts.append("covered: " + "; ".join(str(point) for point in points[:2]))
        if video.get("series_connection"):
            parts.append(f"series link: {video['series_connection']}")
        if video.get("next_episode_hint"):
            parts.append(f"planned next: {video['next_episode_hint']}")
        lines.append("  - " + " | ".join(parts))
    return "\n".join(lines) or "  - None yet"


def _track_series(data: dict, channel_series: str, episode_context: dict) -> dict:
    name = channel_series.strip()
    data.update({
        "series_name": name,
        "series_episode": episode_context.get("next_episode") if name else None,
        "previous_episode_title": episode_context.get("previous_episode_title", "") if name else "",
        "series_connection": str(data.get("series_connection") or "").strip() if name else "",
        "next_episode_hint": str(data.get("next_episode_hint") or "").strip() if name else "",
    })
    return data


def research_topic(channel_description: str,
                   topic_override: str = "",
                   focus_angle: str = "",
                   trend_context: list | None = None,
                   channel_series: str = "",
                   episode_context: dict | None = None) -> dict:
    """
    Research a video topic for the channel.

    Parameters
    ----------
    channel_description : the channel's style / audience description from config.py
    topic_override      : if non-empty, Gemini is told to write a video about
                          THIS EXACT topic — no random angle, no creative
                          interpretation. The bug fix: previously this was
                          prepended to channel_description and then ignored
                          because the random_angle prompt dominated.
    focus_angle         : if non-empty (and topic_override is empty), use this
                          angle instead of picking one randomly. Allows the GUI
                          dropdown to steer AI picks without locking the topic.
    trend_context       : optional list of headlines trending right now (Trend
                          Radar). The AI may ride one if it fits the niche.

    The result carries a "grounding" dict ({facts, sources}) from Wikipedia and
    arXiv that the scriptwriter uses to stay factual and the description cites.
    """
    banned     = load_banned_topics()
    banned_str = ", ".join(f'"{t}"' for t in banned)
    channel_series = channel_series.strip()
    episode_context = episode_context or {}
    series_text = channel_series or "No ongoing series was specified."
    recent_text = _episode_history_text(episode_context)
    episode_number = episode_context.get("next_episode") or 1
    next_step = episode_context.get("previous_next_step") or "No next-step note has been saved yet."
    episode_plan = (f"This is tracked episode #{episode_number}. Continue prior coverage and use the saved next-step hint when it fits: {next_step}"
                    if channel_series else "No named series is set; use recent videos only to avoid repetition.")

    # ── MODE 1: USER-SPECIFIED EXACT TOPIC ───────────────────────────────────
    # The old bug: topic_override was prepended to channel_description, but the
    # prompt still said "Focus on: >>> {random_angle} <<<" so Gemini ignored it.
    # Fix: bypass the angle system entirely and issue a direct instruction.
    if topic_override.strip():
        exact_topic = topic_override.strip()
        print(f"   → Exact topic override: \"{exact_topic}\"")
        grounding = _grounding(exact_topic)
        facts_block = (f"\nVERIFIED BACKGROUND (from Wikipedia / arXiv — build on these, don't contradict them):\n"
                       f"{grounding['facts'][:3500]}\n") if grounding["facts"] else ""

        prompt = f"""You are a top YouTube content strategist for a viral science/tech channel.

Channel description:
{channel_description}

Ongoing channel series or theme:
{series_text}

Recent videos in the channel library (do not repeat them; build on them when a series is set):
{recent_text}

Series progression:
{episode_plan}

MANDATORY INSTRUCTION: You MUST make a video about this EXACT topic:
>>> {exact_topic} <<<

Do NOT substitute a different topic, do NOT pick a related angle — write specifically
about "{exact_topic}". The user has explicitly requested this topic.

BANNED TOPICS: Do NOT include any of these in the output: {banned_str}
If the requested topic conflicts with a banned one, still write about it (user override).

Your mission: Research and plan a compelling 6-8 minute YouTube video about "{exact_topic}".
If it fits the saved series, explain the connection honestly and suggest one concrete next episode. Do not change the exact topic or claim a connection that is not real.
{facts_block}
Respond with ONLY a valid JSON object. No markdown fences, no explanation:

{{
  "topic": "{exact_topic}",
  "why_now": "Why this topic resonates with audiences right now",
  "video_title": "MIND-BLOWING YouTube title under 70 characters about {exact_topic}",
  "description": "2-sentence YouTube description optimised for SEO and curiosity",
  "hook_question": "The single most mind-blowing question this video answers",
  "key_points": [
    "First key concept or revelation about {exact_topic}",
    "Second key concept — the twist or surprise",
    "Third key concept — deeper implication",
    "Fourth key concept — real-world consequence",
    "Fifth key concept — the philosophical angle"
  ],
  "target_audience": "Exactly who will watch and share this",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8"],
  "thumbnail_concept": "Describe the perfect YouTube thumbnail for this topic",
  "series_connection": "One sentence on how this fits the prior episode, or say it is standalone",
  "next_episode_hint": "One concrete, non-repeating direction for the next episode",
  "estimated_virality": "high"
}}"""

        data = _parse(generate(prompt))
        data["grounding"] = grounding
        return _track_series(data, channel_series, episode_context)

    # ── MODE 2: AI PICKS THE TOPIC ───────────────────────────────────────────
    # A saved series is the channel's main direction; a GUI angle is secondary.
    if channel_series:
        chosen_angle = channel_series
        print(f"   → Ongoing channel series: {chosen_angle}")
    elif focus_angle.strip():
        chosen_angle = focus_angle.strip()
        print(f"   → Focus angle (GUI selected): {chosen_angle}")
    else:
        chosen_angle = channel_description.strip() or random.choice(FOCUS_ANGLES)
        print(f"   → Channel direction: {chosen_angle[:100]}")

    print(f"   → Asking the AI for topic ideas within: {chosen_angle}")

    trend_block = ""
    if trend_context:
        print(f"   → Trend-aware: {len(trend_context)} live headlines from Trend Radar")
        joined = "\n".join(f"  - {t}" for t in trend_context[:25])
        trend_block = (
            "OPTIONAL TRENDING RIGHT NOW (news, papers, search spikes):\n"
            f"{joined}\n"
            "   If one of these connects naturally to the theme, build the video around it "
            "for timeliness and say so in \"why_now\". If none fit, ignore them.\n"
        )

    prompt = f"""You are a top YouTube content strategist for a viral science/tech channel.

Channel description:
{channel_description}

Ongoing channel series or theme:
{series_text}

Recent videos in the channel library (do not repeat them; choose the next useful step when a series is set):
{recent_text}

CRITICAL INSTRUCTIONS FOR THIS RUN:
1. The channel's main theme is: >>> {chosen_angle} <<<. Keep the selected topic inside this niche.
2. If a GUI focus angle was selected, use it only when it fits the saved series/theme: {focus_angle.strip() or "none"}.
3. BANNED TOPICS: Do NOT repeat any of these: {banned_str}.
4. Continue tracked episode #{episode_number} when a series is set. Avoid re-teaching covered points; use the prior next-step hint when it fits: {next_step}
5. Return "series_connection" (one honest sentence linking this episode to prior coverage) and "next_episode_hint" (one concrete follow-up for the next video). Do not put episode numbers in the public title.
6. Cache Bust ID: {time.time()} (Ensure completely unique output).
{trend_block}
Your mission:
1. Think of 3-4 compelling video topics that advance the channel's series without repeating recent coverage.
2. Select the single best next topic that is genuinely compelling, timely, and explainable in 6-8 minutes.

Respond with ONLY a valid JSON object. No markdown fences, no explanation:

{{
  "topic": "The specific video topic",
  "why_now": "Why this topic is hitting the zeitgeist right now",
  "video_title": "MIND-BLOWING YouTube title under 70 characters",
  "description": "2-sentence YouTube description optimised for SEO and curiosity",
  "hook_question": "The single most mind-blowing question this video answers",
  "key_points": [
    "First key concept or revelation",
    "Second key concept — the twist or surprise",
    "Third key concept — deeper implication",
    "Fourth key concept — real-world consequence",
    "Fifth key concept — the philosophical angle"
  ],
  "target_audience": "Exactly who will watch and share this",
  "tags": ["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8"],
  "series_connection": "One sentence on how this episode builds on prior coverage",
  "next_episode_hint": "One concrete, non-repeating direction for the following episode",
  "thumbnail_concept": "Describe the perfect YouTube thumbnail",
  "estimated_virality": "high"
}}"""

    data = _parse(generate(prompt))
    data["grounding"] = _grounding(data["topic"])
    return _track_series(data, channel_series, episode_context)
