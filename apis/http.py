"""
Shared HTTP helpers — one session with a polite User-Agent, JSON helpers
and a tiny thread-safe TTL cache so the dashboard doesn't hammer free APIs.
"""
import functools
import threading
import time

import requests

USER_AGENT = (
    "YTAgenticStudio/2.0 "
    "(+https://github.com/raunakpatil/youtube-agentic-ai-studio)"
)

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def get(url: str, params: dict | None = None, timeout: float = 12,
        headers: dict | None = None, stream: bool = False) -> requests.Response:
    r = _session.get(url, params=params, timeout=timeout,
                     headers=headers, stream=stream)
    r.raise_for_status()
    return r


def get_json(url: str, params: dict | None = None, timeout: float = 12,
             headers: dict | None = None):
    return get(url, params=params, timeout=timeout, headers=headers).json()


def post_json(url: str, payload: dict, timeout: float = 60,
              headers: dict | None = None):
    r = _session.post(url, json=payload, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r.json()


def download(url: str, path: str, timeout: float = 30) -> str:
    """Stream a URL to disk. Returns the path."""
    r = get(url, timeout=timeout, stream=True)
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return path


def ttl_cache(seconds: float):
    """Memoise a function's result per-arguments for `seconds`."""
    def deco(fn):
        store: dict = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            with lock:
                hit = store.get(key)
                if hit and now - hit[0] < seconds:
                    return hit[1]
            val = fn(*args, **kwargs)
            with lock:
                store[key] = (now, val)
            return val

        wrapper.cache_clear = store.clear
        return wrapper
    return deco
