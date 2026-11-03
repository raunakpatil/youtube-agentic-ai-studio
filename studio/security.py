"""
Local-only guard.

The studio listens on localhost, but any website open in the same browser can
still send it requests: a "simple" text/plain POST needs no CORS preflight, so
without this a malicious page could start a run, change settings or publish to
the user's YouTube channel. DNS rebinding (attacker.com resolving to 127.0.0.1)
would also let that page read responses. Both are stopped here, for every
route present and future.
"""
from flask import jsonify, request

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

def _hostname(netloc: str) -> str:
    """'localhost:7070' → 'localhost', '[::1]:7070' → '[::1]'."""
    netloc = (netloc or "").strip().lower()
    if netloc.startswith("["):
        return netloc.split("]", 1)[0] + "]"
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc

def _same_origin(url: str) -> bool:
    """True when url (an Origin or Referer) is this studio itself."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == request.host.lower()

def local_only():
    # DNS rebinding: a browser always sends the name it used in the Host header
    if _hostname(request.host) not in _LOCAL_HOSTS:
        return jsonify({"ok": False, "error": "YAAS only accepts requests to localhost."}), 403

    if request.method not in _WRITE_METHODS:
        return None
    # Browsers attach Origin to cross-site writes (Referer as a fallback); tools
    # like curl send neither and are allowed — they can't be driven by a webpage.
    origin = request.headers.get("Origin")
    if origin is not None:
        if not _same_origin(origin):          # includes the opaque "null" origin
            return jsonify({"ok": False, "error": "Cross-site request blocked."}), 403
    else:
        referer = request.headers.get("Referer")
        if referer and not _same_origin(referer):
            return jsonify({"ok": False, "error": "Cross-site request blocked."}), 403
    # A JSON body forces a CORS preflight, which a foreign page can't pass
    if request.method in ("POST", "PUT", "PATCH") and not request.is_json:
        return jsonify({"ok": False, "error": "Send requests as JSON."}), 415
    return None


def init_app(app):
    app.before_request(local_only)
