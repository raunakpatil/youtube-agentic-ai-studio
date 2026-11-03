"""
YouTube Uploader — the one place YAAS talks to the YouTube Data API v3.

  get_credentials()  load the saved OAuth token, refresh it if it expired,
                     or run the browser sign-in once and save the result
  upload_video()     upload the MP4 (resumable), then set the thumbnail
  fit_tags()         trim tags to YouTube's 500-character limit

The token is stored as JSON (youtube_token.json), never pickled.
Google libraries are imported lazily so importing this module stays cheap.
"""
import logging
import os

import config

logger = logging.getLogger(__name__)

# Older versions pickled the token to youtube_token.pickle. That file is never
# loaded (unpickling runs code); users sign in once more and can delete it.
TOKEN_FILE = "youtube_token.json"

TITLE_MAX = 100          # characters
DESCRIPTION_MAX = 5000   # characters
TAGS_MAX_CHARS = 500     # all tags together, as YouTube counts them


def has_token() -> bool:
    return os.path.exists(TOKEN_FILE)


def _save_token(creds) -> None:
    """Write the token readable by the current user only (where the OS allows it)."""
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def _load_token():
    from google.oauth2.credentials import Credentials
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        return Credentials.from_authorized_user_file(TOKEN_FILE, config.YOUTUBE_SCOPES)
    except ValueError as e:              # malformed / missing fields → sign in again
        logger.warning(f"   ⚠ Ignoring unreadable {TOKEN_FILE}: {e}")
        return None


def get_credentials(log=print):
    """Return valid OAuth credentials, refreshing or signing in as needed."""
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = _load_token()
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
        except Exception as e:           # revoked or expired refresh token
            log(f"Saved YouTube sign-in could not be refreshed ({e}); signing in again.")
            creds = None

    if not creds or not creds.valid:
        if not os.path.exists(config.YOUTUBE_CLIENT_SECRET):
            raise FileNotFoundError(
                f"YouTube OAuth file not found: {config.YOUTUBE_CLIENT_SECRET}\n"
                "Follow SETUP.md step 4 to create it in Google Cloud Console."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            config.YOUTUBE_CLIENT_SECRET, config.YOUTUBE_SCOPES)
        creds = flow.run_local_server(port=8080)
        _save_token(creds)
    return creds


def _tag_cost(tag: str) -> int:
    # YouTube wraps a tag that contains a space in quotes, and those count
    return len(tag) + (2 if " " in tag else 0)


def fit_tags(tags, limit: int = TAGS_MAX_CHARS) -> list:
    """
    Clean tags and keep as many as fit in YouTube's limit, in order.
    The limit covers every tag plus the commas between them; over it, YouTube
    rejects the whole upload with `invalidTags`. Angle brackets are not allowed.
    """
    out, seen, used = [], set(), 0
    for tag in tags or []:
        tag = " ".join(str(tag).replace("<", "").replace(">", "").split())
        key = tag.lower()
        if not tag or key in seen:
            continue
        cost = _tag_cost(tag) + (1 if out else 0)       # comma before all but the first
        if used + cost > limit:
            continue                                     # a shorter tag later may still fit
        out.append(tag)
        seen.add(key)
        used += cost
    return out


def _service(creds):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds)


def _thumbnail_error(err: Exception) -> str:
    status = getattr(getattr(err, "resp", None), "status", None)
    if status == 403:
        return ("YouTube refused the custom thumbnail. Custom thumbnails need a verified "
                "channel (youtube.com/verify). Upload it from YouTube Studio instead.")
    return f"Thumbnail upload failed: {str(err)[:300]}"


def upload_video(video_path: str, title: str, description: str = "", tags=None,
                 privacy: str | None = None, publish_at: str = "",
                 thumb_path: str | None = None, on_progress=None, log=print) -> dict:
    """
    Upload a video and (optionally) its thumbnail.

    publish_at: RFC 3339 time to schedule the video; it is uploaded as private
                and YouTube makes it public at that time.
    on_progress: called with an int percentage while the file uploads.
    Returns {"id", "url", "thumbnail_error"}. A failed thumbnail does not fail
    the upload — the video is already live — so it is logged and returned.
    """
    from googleapiclient.http import MediaFileUpload

    yt = _service(get_credentials(log=log))
    body = {
        "snippet": {
            "title":       (title or "")[:TITLE_MAX],
            "description": (description or "")[:DESCRIPTION_MAX],
            "tags":        fit_tags(tags),
            "categoryId":  config.VIDEO_CATEGORY_ID,
        },
        "status": {
            "privacyStatus":           "private" if publish_at else (privacy or config.VIDEO_PRIVACY),
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

    media = MediaFileUpload(video_path, mimetype="video/mp4",
                            resumable=True, chunksize=5 * 1024 * 1024)
    req = yt.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk()
        if status and on_progress:
            on_progress(int(status.progress() * 100))

    video_id = response["id"]
    thumb_error = None
    if thumb_path and os.path.exists(thumb_path):
        try:
            yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg"),
            ).execute()
        except Exception as e:
            thumb_error = _thumbnail_error(e)
            log(thumb_error)

    return {"id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_error": thumb_error}
