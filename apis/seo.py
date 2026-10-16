"""
SEO toolkit — keyword research from what people actually type into YouTube,
plus a transparent, rule-based score for title / description / tags.

  YouTube autocomplete  suggestqueries.google.com (keyless)
  Datamuse              related words (keyless)
"""
import json
import re

from apis.http import get, get_json, ttl_cache


@ttl_cache(60 * 60)
def youtube_suggestions(query: str, lang: str = "en") -> list:
    """Real YouTube search-box suggestions for a query."""
    if not query.strip():
        return []
    r = get("https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "ds": "yt", "q": query, "hl": lang})
    data = json.loads(r.content.decode("utf-8", errors="replace"))
    return [s for s in data[1] if isinstance(s, str)]


@ttl_cache(60 * 60)
def related_words(query: str, limit: int = 12) -> list:
    d = get_json("https://api.datamuse.com/words", params={"ml": query, "max": limit})
    return [w["word"] for w in d if " " in w["word"] or len(w["word"]) > 3]


def keyword_ideas(seed: str) -> dict:
    """Autocomplete expansions + semantically related words for a seed."""
    seed = re.sub(r"[^\w\s'-]", " ", seed).strip()
    short = " ".join(seed.split()[:4])
    suggestions, related = [], []
    for q in (short, f"why {short}", f"what if {short}"):
        try:
            suggestions += youtube_suggestions(q)
        except Exception as e:
            print(f"   ⚠ YouTube suggest failed: {e}")
    try:
        related = related_words(short)
    except Exception as e:
        print(f"   ⚠ Datamuse failed: {e}")

    seen, uniq = set(), []
    for s in suggestions:
        k = s.lower().strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(s)
    return {"suggestions": uniq[:20], "related": related[:12]}


_CURIOSITY = ("why", "how", "what", "secret", "never", "truth", "impossible",
              "hidden", "actually", "really", "if", "nobody", "strange", "?")


def score(title: str, description: str, tags: list, keyword: str = "",
          is_shorts: bool = False) -> dict:
    """
    100-point score built from YouTube's published best practices.
    Each check returns a tip so the number is actionable, not a mystery.
    """
    title = title or ""
    description = description or ""
    tags = [t for t in (tags or []) if t.strip()]
    kw = (keyword or "").lower().strip()
    kw_words = [w for w in re.findall(r"\w+", kw) if len(w) > 3]
    tl, dl = title.lower(), description.lower()

    def has_kw(text: str) -> bool:
        if not kw_words:
            return True
        hits = sum(1 for w in kw_words if w in text)
        return hits >= max(1, len(kw_words) // 2)

    letters = [c for c in title if c.isalpha()]
    caps_ratio = sum(c.isupper() for c in letters) / max(1, len(letters))
    tag_chars = sum(len(t) for t in tags) + max(0, len(tags) - 1)

    checks = [
        ("Title length 30–70 chars", 15, 30 <= len(title) <= 70,
         f"{len(title)} chars. Under 70 avoids truncation in search results."),
        ("Keyword in title", 15, has_kw(tl),
         f"Work “{keyword}” (or its core words) into the title."),
        ("Curiosity / question hook", 10, any(w in tl for w in _CURIOSITY) or any(c.isdigit() for c in title),
         "Add a question, a number, or a curiosity word (why, how, secret…)."),
        ("Not shouting", 5, caps_ratio < 0.6,
         "Mostly-caps titles read as spam. Capitalise one or two words for emphasis."),
        ("Keyword early in description", 10, has_kw(dl[:200]),
         "Mention the keyword in the first two lines — that's what shows under the video."),
        ("Description 250+ chars", 10, len(description) >= 250,
         f"{len(description)} chars. Longer descriptions give YouTube more context."),
        ("Chapters", 10, is_shorts or bool(re.search(r"(^|\n)0:00\s", description)),
         "Add timestamps starting at 0:00 — chapters show in search and boost retention."),
        ("8–15 tags", 10, 8 <= len(tags) <= 15,
         f"{len(tags)} tags. Aim for 8–15 mixing broad and specific phrases."),
        ("Tags under 500 chars", 5, tag_chars <= 500,
         f"{tag_chars}/500 chars — YouTube rejects tag lists over the limit."),
        ("1–15 hashtags", 5, 1 <= len(re.findall(r"#\w+", description)) <= 15,
         "Add a few #hashtags at the end (over 15 and YouTube ignores them all)."),
        ("Call to action", 5, any(w in dl for w in ("subscribe", "comment", "follow")),
         "Ask viewers to subscribe or comment."),
    ]
    total = sum(w for _, w, ok, _ in checks if ok)
    return {
        "score":  total,
        "grade":  "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 50 else "D",
        "checks": [{"label": l, "weight": w, "ok": ok, "tip": tip}
                   for l, w, ok, tip in checks],
    }
