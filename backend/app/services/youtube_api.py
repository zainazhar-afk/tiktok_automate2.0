"""
YouTube Data API v3 discovery — search with filters and pagination.
Falls back to yt-dlp when no API key is configured.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"


def _parse_duration(iso: str) -> int:
    """Parse ISO 8601 duration (PT1M30S) to seconds."""
    if not iso:
        return 0
    m = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        iso,
    )
    if not m:
        return 0
    h, mn, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mn * 60 + s


def _best_thumbnail(thumbnails: dict) -> Optional[str]:
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails:
            return thumbnails[key].get("url")
    return None


async def search_videos(
    query: str,
    *,
    max_results: int = 20,
    page_token: Optional[str] = None,
    order: str = "relevance",
    min_duration: int = 15,
    max_duration: int = 90,
    min_views: Optional[int] = None,
    max_views: Optional[int] = None,
    published_within_days: Optional[int] = None,
    region_code: Optional[str] = None,
    video_category_id: Optional[str] = None,
) -> dict:
    """
    Search Shorts via YouTube Data API.
    Returns {videos, total, next_page_token, prev_page_token, source}.
    """
    settings = get_settings()
    if not settings.youtube_api_key:
        return {"videos": [], "next_page_token": None, "source": "api_unconfigured"}

    params: dict = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "videoDuration": "short",
        "maxResults": min(max_results, 50),
        "order": order,
        "key": settings.youtube_api_key,
    }
    if page_token:
        params["pageToken"] = page_token
    if region_code:
        params["regionCode"] = region_code
    if video_category_id:
        params["videoCategoryId"] = video_category_id
    if published_within_days:
        since = datetime.now(timezone.utc) - timedelta(days=published_within_days)
        params["publishedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=30) as client:
        search_resp = await client.get(f"{API_BASE}/search", params=params)
        search_resp.raise_for_status()
        search_data = search_resp.json()

    video_ids = [
        item["id"]["videoId"]
        for item in search_data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    if not video_ids:
        return {
            "videos": [],
            "total": 0,
            "next_page_token": search_data.get("nextPageToken"),
            "prev_page_token": search_data.get("prevPageToken"),
            "source": "youtube_api",
        }

    details_params = {
        "part": "snippet,contentDetails,statistics",
        "id": ",".join(video_ids),
        "key": settings.youtube_api_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        details_resp = await client.get(f"{API_BASE}/videos", params=details_params)
        details_resp.raise_for_status()
        details_data = details_resp.json()

    videos = []
    for item in details_data.get("items", []):
        vid = item["id"]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        duration = _parse_duration(content.get("duration", ""))
        views = int(stats.get("viewCount", 0)) if stats.get("viewCount") else None

        if duration < min_duration or duration > max_duration:
            continue
        if min_views is not None and (views or 0) < min_views:
            continue
        if max_views is not None and views is not None and views > max_views:
            continue

        videos.append({
            "id": vid,
            "title": snippet.get("title", "Untitled"),
            "channel": snippet.get("channelTitle", "Unknown"),
            "duration": duration,
            "views": views,
            "thumbnail": _best_thumbnail(snippet.get("thumbnails", {})),
            "url": f"https://www.youtube.com/shorts/{vid}",
            "is_short": duration <= 90,
            "published_at": snippet.get("publishedAt"),
            "tags": snippet.get("tags", []),
            "description": snippet.get("description", ""),
        })

    return {
        "videos": videos,
        "total": len(videos),
        "next_page_token": search_data.get("nextPageToken"),
        "prev_page_token": search_data.get("prevPageToken"),
        "source": "youtube_api",
    }


async def discover_trending(
    *,
    max_results: int = 20,
    page_token: Optional[str] = None,
    region_code: str = "US",
    **filters,
) -> dict:
    """Trending Shorts via API search."""
    filters.setdefault("order", "viewCount")
    return await search_videos(
        "trending shorts viral",
        max_results=max_results,
        page_token=page_token,
        region_code=region_code,
        **filters,
    )


async def discover_hashtag(
    hashtag: str,
    *,
    max_results: int = 20,
    page_token: Optional[str] = None,
    **filters,
) -> dict:
    tag = hashtag.lstrip("#")
    return await search_videos(
        f"#{tag} shorts",
        max_results=max_results,
        page_token=page_token,
        **filters,
    )
