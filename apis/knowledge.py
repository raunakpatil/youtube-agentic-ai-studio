"""
Fact grounding — pulls real background facts and citable sources for a topic
so the scriptwriter works from verified material instead of guessing.

  Wikipedia  search → REST summary (keyless)
  arXiv      matching paper abstracts (keyless)
"""
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from apis.http import get, get_json, ttl_cache

_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def wikipedia(topic: str, n: int = 3) -> list:
    s = get_json("https://en.wikipedia.org/w/api.php", params={
        "action": "query", "list": "search", "srsearch": topic,
        "format": "json", "srlimit": n,
    })
    out = []
    for hit in s.get("query", {}).get("search", []):
        title = hit["title"]
        try:
            summ = get_json("https://en.wikipedia.org/api/rest_v1/page/summary/"
                            + quote(title.replace(" ", "_"), safe=""))
        except Exception:
            continue
        extract = (summ.get("extract") or "").strip()
        if not extract or summ.get("type") == "disambiguation":
            continue
        out.append({
            "source": "Wikipedia",
            "title":  title,
            "text":   extract,
            "url":    summ.get("content_urls", {}).get("desktop", {}).get("page", ""),
        })
    return out


def arxiv(topic: str, n: int = 3) -> list:
    words = [w for w in topic.replace('"', "").split() if len(w) > 3][:6]
    if not words:
        return []
    query = " AND ".join(f"all:{w}" for w in words[:4])
    r = get("https://export.arxiv.org/api/query", params={
        "search_query": query, "max_results": n, "sortBy": "relevance",
    }, timeout=20)
    root = ET.fromstring(r.content)
    out = []
    for e in root.findall("a:entry", _ATOM):
        title = " ".join((e.findtext("a:title", namespaces=_ATOM) or "").split())
        summary = " ".join((e.findtext("a:summary", namespaces=_ATOM) or "").split())
        if title:
            out.append({
                "source": "arXiv",
                "title":  title,
                "text":   summary[:600],
                "url":    e.findtext("a:id", namespaces=_ATOM) or "",
            })
    return out


@ttl_cache(60 * 60)
def gather_context(topic: str) -> dict:
    """
    Returns {"facts": str, "sources": [{source,title,url}]}.
    Never raises — an empty result just means the script is ungrounded.
    """
    if not topic.strip():
        return {"facts": "", "sources": []}

    def _run(fn):
        try:
            return fn(topic)
        except Exception as e:
            print(f"   ⚠ {fn.__name__} grounding failed: {e}")
            return []

    with ThreadPoolExecutor(max_workers=2) as ex:
        wiki, papers = ex.map(_run, (wikipedia, arxiv))

    docs = wiki + papers
    facts = "\n\n".join(f"[{d['source']}: {d['title']}]\n{d['text']}" for d in docs)
    return {
        "facts":   facts[:6000],
        "sources": [{"source": d["source"], "title": d["title"], "url": d["url"]}
                    for d in docs],
    }
