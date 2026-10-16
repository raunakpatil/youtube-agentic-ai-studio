"""
LLM Client — shared across all agents.

1. Gemini / Gemma: tries models in order starting from config.GEMINI_MODEL,
   falling back through the rest of the chain on quota / overload errors.
2. If there's no Gemini key, or every Gemini model fails, hands over to the
   free fallback chain in apis/llm.py: Groq → OpenRouter → Pollinations
   (keyless), so generation always has somewhere to go.

Free-tier daily limits (approximate):
  gemini-2.5-flash      → 500 req/day
  gemini-2.0-flash      → 1,500 req/day
  gemini-2.0-flash-lite → 1,500 req/day
  gemma-4-31b-it        → 500 req/day
"""
import time
import config

# Full list of supported models in preference order.
# The actual runtime order is determined by build_chain() below,
# which rotates this list so config.GEMINI_MODEL comes first.
_ALL_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemma-4-31b-it",        # Gemma 4 31B dense — strong reasoning, free tier
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemma-3-27b-it",
    "gemini-1.5-flash-001",
    "gemini-1.5-pro-001",
]

# Which provider answered the last call — shown in the GUI
last_provider = None


def build_chain(starting_model: str | None = None) -> list:
    """
    Return MODEL_CHAIN rotated so `starting_model` is first.
    If starting_model is not in the list (typo / unknown), falls back to
    the default order so generation always has a working chain.
    """
    preferred = (starting_model or "").strip()
    if preferred and preferred in _ALL_MODELS:
        idx = _ALL_MODELS.index(preferred)
        return _ALL_MODELS[idx:] + _ALL_MODELS[:idx]
    return list(_ALL_MODELS)


_client = None
_client_key = None


def gemini_configured() -> bool:
    key = getattr(config, "GEMINI_API_KEY", "") or ""
    return bool(key) and not key.upper().startswith("YOUR_")


def _get_client():
    """Rebuild the client if the key changed in Settings."""
    global _client, _client_key
    if _client is None or _client_key != config.GEMINI_API_KEY:
        from google import genai
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
        _client_key = config.GEMINI_API_KEY
    return _client


def _is_gone(err: Exception) -> bool:
    """Model retired or unknown — retrying it is pointless."""
    msg = str(err)
    return any(k in msg for k in ["404", "NOT_FOUND", "not found", "is not supported"])


def _should_switch_model(err: Exception) -> bool:
    """Return True for any error code that means we should try the next model."""
    msg = str(err)
    return _is_gone(err) or any(k in msg for k in [
        "429", "RESOURCE_EXHAUSTED", "quota", "rate limit",  # 429 – quota
        "503", "UNAVAILABLE", "overloaded", "high demand",   # 503 – overloaded
        "500", "INTERNAL",                                    # 500 – transient
    ])


def _generate_gemini(prompt: str, starting_model: str | None) -> str:
    global last_provider
    from google.genai import types
    client = _get_client()
    chain  = build_chain(starting_model or getattr(config, "GEMINI_MODEL", None))

    for model in chain:
        for attempt in range(3):   # up to 3 attempts per model before moving on
            try:
                print(f"   → Using {model}…")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.9),
                )
                last_provider = model
                return response.text.strip()

            except Exception as e:
                if _is_gone(e):
                    print(f"   ⚠ {model} unavailable — trying next model…")
                    break
                if _should_switch_model(e):
                    if attempt < 2:
                        wait = 15 * (attempt + 1)   # 15s then 30s
                        print(f"   ⚠ {model} error (attempt {attempt+1}/3) — waiting {wait}s…")
                        time.sleep(wait)
                    else:
                        print(f"   ⚠ {model} failed 3 times — trying next model…")
                else:
                    raise   # auth error or bug — surface immediately

    raise RuntimeError(
        "All Gemini models failed. 503/500 = temporary, retry in a few minutes; "
        "429 = quota, resets at midnight Pacific (https://aistudio.google.com/apikey)."
    )


def generate(prompt: str, starting_model: str | None = None) -> str:
    global last_provider
    from apis import llm

    gemini_err = None
    if gemini_configured():
        try:
            return _generate_gemini(prompt, starting_model)
        except Exception as e:
            gemini_err = e
            if not llm.providers():
                raise
            print(f"   ⚠ Gemini unavailable ({str(e)[:120]}) — switching to fallback LLMs…")
    else:
        print("   → No Gemini key set — using free fallback LLMs")

    try:
        text = llm.chat(prompt)
        last_provider = "fallback"
        return text
    except Exception as e:
        if gemini_err:
            raise RuntimeError(f"Gemini failed: {gemini_err}\nFallbacks failed: {e}") from e
        raise RuntimeError(
            f"{e}\nAdd a free Gemini key in Settings (aistudio.google.com/apikey)."
        ) from e
