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


class QuotaExceededError(Exception):
    """Raised when the YouTube Data API returns a quota/rate-limit 403."""


def _raise_for_quota(resp: "httpx.Response") -> None:
    """Detect quota/rate-limit 403s and raise QuotaExceededError with a clear message."""
    if resp.status_code != 403:
        return
    reason = ""
    try:
        errors = resp.json().get("error", {}).get("errors", [])
        reason = (errors[0].get("reason") if errors else "") or ""
    except Exception:
        pass
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"):
        raise QuotaExceededError(
            "YouTube Data API quota exceeded for today. It resets at midnight "
            "Pacific Time. Set a different API key or wait for the reset."
        )


# Content niches → search keywords + closest YouTube videoCategoryId.
# Keywords drive keyword/search discovery; category_id is used for the
# region "mostPopular" trending chart when the category is assignable.
NICHE_PRESETS: dict[str, dict] = {
    "motivational": {"keywords": "motivation motivational success mindset discipline", "category_id": "22"},
    "comedy": {"keywords": "funny comedy hilarious meme skit", "category_id": "23"},
    "gaming": {"keywords": "gaming gameplay gamer clutch", "category_id": "20"},
    "fitness": {"keywords": "gym workout fitness exercise", "category_id": "17"},
    "sports": {"keywords": "sports highlights goal football", "category_id": "17"},
    "food": {"keywords": "food recipe cooking asmr", "category_id": "26"},
    "education": {"keywords": "facts educational learn did you know", "category_id": "27"},
    "tech": {"keywords": "tech gadgets technology review", "category_id": "28"},
    "beauty": {"keywords": "beauty makeup skincare tutorial", "category_id": "26"},
    "pets": {"keywords": "cute pets animals dog cat", "category_id": "15"},
    "travel": {"keywords": "travel adventure destination", "category_id": "19"},
    "music": {"keywords": "music song cover dance", "category_id": "10"},
}

# Rough region → relevanceLanguage to bias keyword search toward the region.
REGION_LANGUAGE = {
    "US": "en", "GB": "en", "CA": "en", "AU": "en",
    "IN": "hi", "DE": "de", "FR": "fr", "ES": "es",
    "BR": "pt", "JP": "ja", "KR": "ko",
}


def _parse_duration(iso: str) -> int:
    """Parse ISO 8601 duration (PT1M30S) to seconds."""
    if not iso:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return 0
    h, mn, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mn * 60 + s


def _best_thumbnail(thumbnails: dict) -> Optional[str]:
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails:
            return thumbnails[key].get("url")
    return None


def _apply_niche(query: str, niche: Optional[str]) -> str:
    """Inject niche keywords into the search query."""
    if not niche:
        return query
    preset = NICHE_PRESETS.get(niche.lower())
    if not preset:
        return f"{query} {niche}".strip()
    return f"{query} {preset['keywords']}".strip()


def _niche_category_id(niche: Optional[str]) -> Optional[str]:
    if not niche:
        return None
    return NICHE_PRESETS.get(niche.lower(), {}).get("category_id")


def _video_from_item(item: dict, min_duration: int, max_duration: int,
                     min_views: Optional[int], max_views: Optional[int]) -> Optional[dict]:
    vid = item["id"]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    duration = _parse_duration(content.get("duration", ""))
    views = int(stats.get("viewCount", 0)) if stats.get("viewCount") else None

    if duration < min_duration or duration > max_duration:
        return None
    if min_views is not None and (views or 0) < min_views:
        return None
    if max_views is not None and views is not None and views > max_views:
        return None

    return {
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
    }


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
    niche: Optional[str] = None,
) -> dict:
    """
    Search Shorts via YouTube Data API search.list.
    Returns {videos, total, next_page_token, prev_page_token, source}.
    """
    settings = get_settings()
    if not settings.youtube_api_key:
        return {"videos": [], "next_page_token": None, "source": "api_unconfigured"}

    query = _apply_niche(query, niche)
    category_id = video_category_id or _niche_category_id(niche)

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
        lang = REGION_LANGUAGE.get(region_code.upper())
        if lang:
            params["relevanceLanguage"] = lang
    if category_id:
        params["videoCategoryId"] = category_id
    if published_within_days:
        since = datetime.now(timezone.utc) - timedelta(days=published_within_days)
        params["publishedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=30) as client:
        search_resp = await client.get(f"{API_BASE}/search", params=params)
        _raise_for_quota(search_resp)
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

    details = await _fetch_details(video_ids)
    videos = []
    for item in details:
        v = _video_from_item(item, min_duration, max_duration, min_views, max_views)
        if v:
            videos.append(v)

    return {
        "videos": videos,
        "total": len(videos),
        "next_page_token": search_data.get("nextPageToken"),
        "prev_page_token": search_data.get("prevPageToken"),
        "source": "youtube_api",
    }


async def _fetch_details(video_ids: list[str]) -> list[dict]:
    settings = get_settings()
    details_params = {
        "part": "snippet,contentDetails,statistics",
        "id": ",".join(video_ids),
        "key": settings.youtube_api_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE}/videos", params=details_params)
        _raise_for_quota(resp)
        resp.raise_for_status()
        return resp.json().get("items", [])


async def discover_trending(
    *,
    max_results: int = 20,
    page_token: Optional[str] = None,
    region_code: str = "US",
    niche: Optional[str] = None,
    video_category_id: Optional[str] = None,
    min_duration: int = 15,
    max_duration: int = 90,
    min_views: Optional[int] = None,
    max_views: Optional[int] = None,
    **_ignored,
) -> dict:
    """
    True regional trending via videos.list chart=mostPopular.
    This reflects CURRENT trending per region (refreshes through the day)
    and respects regionCode, unlike search.list which only soft-biases.
    """
    settings = get_settings()
    if not settings.youtube_api_key:
        return {"videos": [], "next_page_token": None, "source": "api_unconfigured"}

    category_id = video_category_id or _niche_category_id(niche)
    params: dict = {
        "part": "snippet,contentDetails,statistics",
        "chart": "mostPopular",
        "regionCode": (region_code or "US").upper(),
        "maxResults": min(max_results * 2, 50),  # over-fetch; we filter to Shorts
        "key": settings.youtube_api_key,
    }
    if page_token:
        params["pageToken"] = page_token
    if category_id:
        params["videoCategoryId"] = category_id

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{API_BASE}/videos", params=params)
            _raise_for_quota(resp)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        # Some category/region combos aren't assignable for mostPopular → fall back to search
        logger.warning(f"mostPopular chart failed ({e}); falling back to search")
        return await search_videos(
            "trending viral shorts",
            max_results=max_results,
            region_code=region_code,
            niche=niche,
            order="viewCount",
            min_duration=min_duration,
            max_duration=max_duration,
            min_views=min_views,
            max_views=max_views,
        )

    videos = []
    for item in data.get("items", []):
        v = _video_from_item(item, min_duration, max_duration, min_views, max_views)
        if v:
            videos.append(v)
        if len(videos) >= max_results:
            break

    # If region/category trending has too few Shorts, supplement with search
    if len(videos) < max(3, max_results // 4):
        supplement = await search_videos(
            "trending viral shorts",
            max_results=max_results,
            region_code=region_code,
            niche=niche,
            order="viewCount",
            min_duration=min_duration,
            max_duration=max_duration,
            min_views=min_views,
            max_views=max_views,
        )
        seen = {v["id"] for v in videos}
        for v in supplement.get("videos", []):
            if v["id"] not in seen:
                videos.append(v)

    return {
        "videos": videos[:max_results],
        "total": len(videos[:max_results]),
        "next_page_token": data.get("nextPageToken"),
        "prev_page_token": data.get("prevPageToken"),
        "source": f"youtube_api_trending_{params['regionCode']}",
    }


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
