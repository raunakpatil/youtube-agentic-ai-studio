"""
Public channel stats via the YouTube Data API v3 (free API key, ~3 quota
units per refresh out of 10,000/day). Accepts a channel ID (UC…) or @handle.
"""
import config
from apis.http import get_json, ttl_cache

_API = "https://www.googleapis.com/youtube/v3"


def configured() -> bool:
    return bool(getattr(config, "YOUTUBE_API_KEY", "")) and bool(getattr(config, "YOUTUBE_CHANNEL_ID", ""))


@ttl_cache(10 * 60)
def channel_stats() -> dict:
    key = config.YOUTUBE_API_KEY
    ident = config.YOUTUBE_CHANNEL_ID.strip()
    params = {"part": "snippet,statistics,contentDetails", "key": key}
    if ident.startswith("@"):
        params["forHandle"] = ident
    else:
        params["id"] = ident
    d = get_json(f"{_API}/channels", params=params)
    if not d.get("items"):
        raise ValueError(f"No channel found for '{ident}'")
    ch = d["items"][0]
    st = ch.get("statistics", {})
    uploads = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")

    recent = []
    if uploads:
        pl = get_json(f"{_API}/playlistItems", params={
            "part": "contentDetails", "playlistId": uploads, "maxResults": 24, "key": key})
        ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if ids:
            vids = get_json(f"{_API}/videos", params={
                "part": "snippet,statistics", "id": ",".join(ids), "key": key})
            for v in vids.get("items", []):
                recent.append({
                    "id":        v["id"],
                    "title":     v["snippet"]["title"],
                    "published": v["snippet"]["publishedAt"],
                    "views":     int(v["statistics"].get("viewCount", 0)),
                    "likes":     int(v["statistics"].get("likeCount", 0)),
                })
    return {
        "title":       ch["snippet"]["title"],
        "thumbnail":   ch["snippet"].get("thumbnails", {}).get("default", {}).get("url", ""),
        "subscribers": int(st.get("subscriberCount", 0)),
        "views":       int(st.get("viewCount", 0)),
        "videos":      int(st.get("videoCount", 0)),
        "recent":      sorted(recent, key=lambda v: v["published"]),
    }
