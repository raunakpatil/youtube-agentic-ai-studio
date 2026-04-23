"""
Script Writer Agent — uses shared Gemini client with model fallback chain.
"""
import json
import re
from agents.gemini_client import generate


def write_script(research: dict, video_type: str = "normal") -> dict:
    """
    Generates a narrated script for a YouTube video or YouTube Short.
    video_type: "normal" (6-8 min, 9 sections) | "shorts" (50-60 sec, 3 sections)
    Returns structured JSON with sections, each containing narration + image_query.
    """
    if video_type == "shorts":
        return _write_shorts_script(research)

    key_points_str = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(research["key_points"]))

    prompt = f"""You are the lead scriptwriter for a viral science YouTube channel (think Kurzgesagt, Veritasium, Vsauce).

Video topic: {research["topic"]}
Title: {research["video_title"]}
Core hook question: {research.get("hook_question", "")}
Key points to cover:
{key_points_str}

Write a GRIPPING, cinematic 6-8 minute script. Non-negotiable rules:

PACING RULES (survival against the YouTube 2-minute drop):
- Section 4 MUST open with a pattern-break re-hook: "But here's where it gets REALLY weird…"
  or "Wait — everything I just told you is only HALF the story." This re-hooks viewers at ~90s.
- Section 6 MUST open with a second re-hook: a sudden gear-shift ("So why does any of this matter?
  Let me show you something that will change how you see the world.") This catches the 3-min drop.
- Use OPEN LOOPS: pose a specific question in section 2 or 3 ("You might wonder: X.") and answer
  it in section 5 or 6 — this forces viewers to stay for the payoff.
- Vary sentence length: punchy 4-word sentences followed by longer ones. Never three long sentences in a row.
- Use "But wait.", "Here's the thing.", "Stay with me." to reset attention.

VISUAL RULES:
- Each section needs 3 distinct image queries (image_query, image_query_2, image_query_3).
  These are used for B-roll cuts every 8-12 seconds within the section. Make them visually different:
  wide shot → close-up → abstract or concept art. NOT three variations of the same thing.

Respond with ONLY a valid JSON object. No markdown fences, no extra text:

{{
  "title": "{research['video_title']}",
  "description": "{research.get('description', '')}",
  "tags": {json.dumps(research.get('tags', []))},
  "sections": [
    {{
      "id": 1,
      "section_type": "hook",
      "title": "Short, punchy on-screen title — NOT 'The Hook'",
      "narration": "Open with an impossible statement or visceral question that stops the scroll. 3-4 sentences. End on an open question that section 2 will tease but section 5 will answer.",
      "image_query": "dramatic wide establishing shot matching the topic",
      "image_query_2": "close-up detail or human reaction shot",
      "image_query_3": "abstract or cosmic concept matching the mood",
      "bullet_points": [],
      "caption_text": "Short punchy caption shown on screen",
      "duration_seconds": 25
    }},
    {{
      "id": 2,
      "section_type": "intro",
      "title": "On-screen title — NOT 'Setting the Stage'",
      "narration": "Establish context and scale. Pose the open-loop question explicitly: 'Here is the question we need to answer: [question].' Promise the viewer the answer is coming and it will change everything. 4-5 sentences.",
      "image_query": "scale or size comparison dramatic wide shot",
      "image_query_2": "scientists or researchers at work close-up",
      "image_query_3": "data visualization or diagram concept",
      "bullet_points": ["The open question we will answer", "Why the scale matters", "What most people get wrong"],
      "caption_text": "What we'll explore today",
      "duration_seconds": 40
    }},
    {{
      "id": 3,
      "section_type": "content",
      "title": "On-screen title — NOT 'First Revelation'",
      "narration": "First deep explanation. Use a concrete analogy ('Imagine if…'). Build simple → complex. 5-7 sentences. End with a setup that makes section 4 feel inevitable.",
      "image_query": "specific concept matching this section — dramatic wide",
      "image_query_2": "close-up detail of the concept",
      "image_query_3": "abstract or metaphorical visual for the analogy used",
      "bullet_points": ["Core fact A", "Core fact B — the surprising part"],
      "caption_text": "The first mind-blowing fact",
      "duration_seconds": 70
    }},
    {{
      "id": 4,
      "section_type": "re_hook",
      "title": "On-screen title — a gear-shift title like 'But Wait.' or 'The Twist Nobody Sees'",
      "narration": "MANDATORY: Open with a re-hook line like 'But here's where it gets REALLY weird…' or 'Wait — everything I just said is only half the story.' Then deliver the counterintuitive twist. The viewer who almost dropped off at 90 seconds just got pulled back. 5-7 sentences.",
      "image_query": "dramatic reveal or twist — light breaking through darkness",
      "image_query_2": "shocked or awed human expression or reaction",
      "image_query_3": "abstract visual representing a paradigm shift",
      "bullet_points": ["What you thought was true", "What is actually true — the twist"],
      "caption_text": "Nothing is what it seems",
      "duration_seconds": 70
    }},
    {{
      "id": 5,
      "section_type": "content",
      "title": "On-screen title — NOT 'Going Deeper'",
      "narration": "The deeper layer. MANDATORY: answer the open-loop question posed in section 2 here. 'Remember the question I asked earlier? Here is the answer — and it's stranger than you imagined.' Then the implications. 5-7 sentences.",
      "image_query": "the answer or resolution concept — dramatic and clear",
      "image_query_2": "scientific or mathematical concept close-up",
      "image_query_3": "wide cosmic or civilizational scale shot",
      "bullet_points": ["The answer to the open question", "Implication A", "Implication B"],
      "caption_text": "The rabbit hole goes deeper",
      "duration_seconds": 70
    }},
    {{
      "id": 6,
      "section_type": "re_hook",
      "title": "On-screen title — a second gear-shift like 'And It Gets Worse.' or 'The Part Nobody Talks About'",
      "narration": "MANDATORY: Second re-hook at the 3-minute mark. Open with a sudden gear-shift: 'So why does any of this actually matter? Let me show you something that changes everything.' Then hit the real-world human stakes hard. 5-6 sentences.",
      "image_query": "human civilization or society wide shot dramatic",
      "image_query_2": "technology or infrastructure close-up",
      "image_query_3": "individual human face or hands — personal scale",
      "bullet_points": ["Why this affects YOU personally", "The consequence most people ignore", "What happens if we do nothing"],
      "caption_text": "What this means for all of us",
      "duration_seconds": 65
    }},
    {{
      "id": 7,
      "section_type": "content",
      "title": "On-screen title — a philosophical or existential angle",
      "narration": "The existential dimension. Make the viewer feel the scale of what this means. What question does this leave unanswered? What do the smartest experts disagree on? 4-6 sentences. End with a rhetorical question that leads into the conclusion.",
      "image_query": "cosmos or infinite space — awe-inspiring wide",
      "image_query_2": "lone human figure against vast landscape or sky",
      "image_query_3": "philosophical or abstract concept — light or shadow",
      "bullet_points": ["The big unanswered question", "What experts disagree on"],
      "caption_text": "The question that keeps scientists up at night",
      "duration_seconds": 60
    }},
    {{
      "id": 8,
      "section_type": "conclusion",
      "title": "On-screen title — a satisfying payoff title",
      "narration": "Bring it home. Three punchy takeaways. Callback to the opening hook ('Remember how I asked…? Now you know.'). End with a direct question for the comments — one that every viewer has a personal answer to.",
      "image_query": "hope or breakthrough — light emerging from darkness",
      "image_query_2": "discovery or revelation — close-up of something revealed",
      "image_query_3": "forward-looking future technology or cosmos",
      "bullet_points": ["Core truth #1 — punchy and memorable", "Core truth #2 — the twist payoff", "Core truth #3 — the call to think"],
      "caption_text": "What have we learned?",
      "duration_seconds": 50
    }},
    {{
      "id": 9,
      "section_type": "cta",
      "title": "On-screen title — e.g. 'Join the Journey'",
      "narration": "We drop a new mind-bending video every week. If this changed how you see the world, subscribe — and hit the bell so you never miss one. Drop your answer in the comments: [specific question from the video]. I read every single one.",
      "image_query": "space stars infinite universe night sky",
      "image_query_2": "community or crowd united by curiosity",
      "image_query_3": "cosmic overview shot — earth from space",
      "bullet_points": [],
      "caption_text": "New video every week",
      "duration_seconds": 18
    }}
  ]
}}

IMPORTANT:
- image_query / image_query_2 / image_query_3 must be VISUALLY DISTINCT from each other (wide → close → abstract).
- Use SPECIFIC Pexels search strings (e.g. "black hole accretion disk simulation" not just "space").
- Narration for sections 4 and 6 MUST start with the mandatory re-hook lines as described.
- The open-loop question from section 2 MUST be answered in section 5.
- Every narration field must contain COMPLETE, broadcast-ready sentences — no placeholders.
- The entire script must feel like Kurzgesagt wrote it: cinematic, urgent, human."""

    print("   → Writing script with Gemini...")
    raw = generate(prompt)
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"Scriptwriter returned no JSON.\n\nRaw:\n{raw[:600]}")

    script = json.loads(match.group())

    if "sections" not in script or len(script["sections"]) < 4:
        raise ValueError("Script returned too few sections.")

    return script


def _write_shorts_script(research: dict) -> dict:
    """
    Generates a tight 50-60 second YouTube Shorts script (3 sections, vertical format).
    """
    key_points_str = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(research["key_points"][:3]))

    prompt = f"""You are a viral YouTube Shorts scriptwriter. You write punchy, addictive 50-60 second vertical videos.

Video topic: {research["topic"]}
Title: {research["video_title"]}
Hook question: {research.get("hook_question", "")}
Key points:
{key_points_str}

Write a GRIPPING 50-60 second Shorts script. Rules:
- Hooks in the FIRST 3 words — no slow intros
- Short, punchy sentences. Every second counts.
- Vertical video style: one idea per second
- End with a cliffhanger or question that forces them to follow/subscribe
- 3 sections ONLY: hook (10-12s), revelation (30-35s), cta (8-10s)
- Total narration must be 120-160 words maximum
- NEVER name the section in the title field — title is INTERNAL only, not shown on screen

Respond with ONLY a valid JSON object. No markdown fences, no extra text:

{{
  "title": "{research['video_title']} #Shorts",
  "description": "Short, punchy 2-sentence description for the Short.",
  "tags": {json.dumps(research.get('tags', []) + ["Shorts", "YouTubeShorts"])},
  "sections": [
    {{
      "id": 1,
      "section_type": "hook",
      "title": "hook_internal",
      "narration": "Open with a jaw-dropping 1-sentence statement. Then the question. 2-3 punchy sentences MAX. About 30-35 words.",
      "image_query": "dramatic space cosmos universe dark",
      "image_query_2": "explosion supernova nebula vivid",
      "image_query_3": "earth from space satellite view",
      "image_query_4": "black hole gravitational waves",
      "bullet_points": [],
      "caption_text": "",
      "duration_seconds": 12
    }},
    {{
      "id": 2,
      "section_type": "content",
      "title": "content_internal",
      "narration": "The core mind-blowing fact, explained in 3-4 punchy sentences. No fluff. Drive home the ONE key insight. About 80-90 words.",
      "image_query": "relevant scientific dramatic image cinematic",
      "image_query_2": "laboratory science experiment glowing",
      "image_query_3": "futuristic technology neon abstract",
      "image_query_4": "human brain neuron synapse close up",
      "bullet_points": [],
      "caption_text": "",
      "duration_seconds": 35
    }},
    {{
      "id": 3,
      "section_type": "cta",
      "title": "cta_internal",
      "narration": "Drop one final mind-bending teaser, then tell them to follow for more facts that break their brain. 15-20 words.",
      "image_query": "stars infinite cosmos night sky milky way",
      "image_query_2": "galaxy spiral arms nebula purple",
      "image_query_3": "universe deep field stars",
      "image_query_4": "space telescope distant galaxies",
      "bullet_points": [],
      "caption_text": "",
      "duration_seconds": 10
    }}
  ]
}}

IMPORTANT:
- Total narration across ALL sections: 120-160 words maximum
- Each section narration must be complete, broadcast-ready sentences
- image_query and image_query_2/3/4 must all be DIFFERENT specific Pexels visual search strings
- title fields are INTERNAL labels only — they are never shown on screen"""

    print("   → Writing Shorts script with Gemini...")
    raw = generate(prompt)
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"Shorts scriptwriter returned no JSON.\n\nRaw:\n{raw[:600]}")

    script = json.loads(match.group())

    if "sections" not in script or len(script["sections"]) < 2:
        raise ValueError("Shorts script returned too few sections.")

    # Tag it so the video creator knows
    script["video_type"] = "shorts"
    return script
