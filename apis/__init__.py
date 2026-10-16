"""
Free API integrations.

Every module here is fail-soft: a dead or rate-limited service returns an
empty result (and logs a warning) instead of breaking the pipeline.

Keyless (work out of the box):
  trends.py     Google Trends RSS · Wikipedia most-read · Hacker News ·
                Spaceflight News · arXiv
  knowledge.py  Wikipedia search + summaries · arXiv abstracts (fact grounding)
  seo.py        YouTube autocomplete · Datamuse (keyword research, SEO score)
  images.py     NASA Image Library · Openverse (CC) · Pollinations (AI images)
  llm.py        Pollinations text (last-resort LLM fallback)

Free key (optional):
  images.py     Pixabay
  llm.py        Groq · OpenRouter
  youtube_stats.py  YouTube Data API v3 (public channel stats)
"""
