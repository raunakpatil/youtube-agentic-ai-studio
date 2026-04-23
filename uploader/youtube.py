"""
YouTube Uploader
Authenticates with the YouTube Data API v3 and uploads the final video.
"""
import os
import pickle
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
import config


TOKEN_FILE = "youtube_token.pickle"


def _get_service():
    """Return an authenticated YouTube service object."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if not os.path.exists(config.YOUTUBE_CLIENT_SECRET):
            raise FileNotFoundError(
                f"YouTube OAuth file not found: {config.YOUTUBE_CLIENT_SECRET}\n"
                "Follow the setup guide to create it in Google Cloud Console."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            config.YOUTUBE_CLIENT_SECRET, config.YOUTUBE_SCOPES
        )
        creds = flow.run_local_server(port=8080)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(script: dict, video_path: str) -> str:
    """
    Uploads the video with auto-generated title, description, and tags.
    Returns the public YouTube URL.
    """
    youtube = _get_service()

    description = (
        script.get("description", "") + "\n\n"
        + "─────────────────────────────\n"
        + "Subscribe for new explainers every week!\n"
        + "─────────────────────────────\n"
        + " ".join(f"#{t}" for t in script.get("tags", []))
    )

    body = {
        "snippet": {
            "title":       script["title"],
            "description": description,
            "tags":        script.get("tags", []),
            "categoryId":  config.VIDEO_CATEGORY_ID,
        },
        "status": {
            "privacyStatus":            config.VIDEO_PRIVACY,
            "selfDeclaredMadeForKids":  False,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,   # 5 MB chunks
    )

    insert_req = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    print("   → Uploading…")
    response = None
    while response is None:
        status, response = insert_req.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"   → {pct}% uploaded", end="\r")

    print()
    video_id = response["id"]
    return f"https://www.youtube.com/watch?v={video_id}"
