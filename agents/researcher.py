"""
Research Agent — uses shared Gemini client with model fallback chain.
Banned topics are read from banned_topics.txt (one topic per line) in the
project root. Edit that file — or use the GUI textarea — instead of changing
Python code.
"""
import json
import os
import re
import random
import time
from agents.gemini_client import generate

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


def research_topic(channel_description: str,
                   topic_override: str = "",
                   focus_angle: str = "") -> dict:
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
    """
    banned     = load_banned_topics()
    banned_str = ", ".join(f'"{t}"' for t in banned)

    # ── MODE 1: USER-SPECIFIED EXACT TOPIC ───────────────────────────────────
    # The old bug: topic_override was prepended to channel_description, but the
    # prompt still said "Focus on: >>> {random_angle} <<<" so Gemini ignored it.
    # Fix: bypass the angle system entirely and issue a direct instruction.
    if topic_override.strip():
        exact_topic = topic_override.strip()
        print(f"   → Exact topic override: \"{exact_topic}\"")

        prompt = f"""You are a top YouTube content strategist for a viral science/tech channel.

Channel description:
{channel_description}

MANDATORY INSTRUCTION: You MUST make a video about this EXACT topic:
>>> {exact_topic} <<<

Do NOT substitute a different topic, do NOT pick a related angle — write specifically
about "{exact_topic}". The user has explicitly requested this topic.

BANNED TOPICS: Do NOT include any of these in the output: {banned_str}
If the requested topic conflicts with a banned one, still write about it (user override).

Your mission: Research and plan a compelling 6-8 minute YouTube video about "{exact_topic}".

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
  "estimated_virality": "high"
}}"""

        raw = generate(prompt)
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$",          "", raw).strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError(f"Researcher returned no JSON.\nRaw:\n{raw[:600]}")
        data = json.loads(match.group())
        for field in ["topic", "video_title", "key_points", "tags"]:
            if field not in data:
                raise ValueError(f"Research JSON missing field: '{field}'")
        return data

    # ── MODE 2: AI PICKS THE TOPIC ───────────────────────────────────────────
    # Use focus_angle if supplied by the GUI dropdown; otherwise pick randomly.
    if focus_angle.strip():
        chosen_angle = focus_angle.strip()
        print(f"   → Focus angle (GUI selected): {chosen_angle}")
    else:
        chosen_angle = random.choice(FOCUS_ANGLES)
        print(f"   → Focus angle (random): {chosen_angle}")

    print(f"   → Asking Gemini for topic ideas within: {chosen_angle}")

    prompt = f"""You are a top YouTube content strategist for a viral science/tech channel.

Channel description:
{channel_description}

CRITICAL INSTRUCTIONS FOR THIS RUN:
1. Focus entirely on this specific theme: >>> {chosen_angle} <<<
2. BANNED TOPICS: Do NOT suggest any of the following — we already made videos about them: {banned_str}. You must give me a brand new, highly original concept.
3. Cache Bust ID: {time.time()} (Ensure completely unique output).

Your mission:
1. Think of 3-4 highly compelling video topic ideas within that specific theme.
2. Select the single BEST topic that is genuinely mind-blowing, timely, and explainable in 6-8 minutes.

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
  "thumbnail_concept": "Describe the perfect YouTube thumbnail",
  "estimated_virality": "high"
}}"""

    raw = generate(prompt)
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$",          "", raw).strip()

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"Researcher returned no JSON.\nRaw:\n{raw[:600]}")

    data = json.loads(match.group())
    for field in ["topic", "video_title", "key_points", "tags"]:
        if field not in data:
            raise ValueError(f"Research JSON missing field: '{field}'")
    return data
