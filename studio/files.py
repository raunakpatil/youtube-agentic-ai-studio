"""Small file helpers shared by the routes that serve media."""
import os
import re

from flask import abort, request, send_file

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "video").lower()).strip("-")[:40] or "video"

def send(path, mimetype, name=None):
    if path and os.path.exists(path):
        dl = request.args.get("download") == "1"
        return send_file(os.path.abspath(path), mimetype=mimetype,
                         as_attachment=dl, download_name=name or os.path.basename(path))
    abort(404)
