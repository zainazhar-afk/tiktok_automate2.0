"""
YouTube content discovery — YouTube Data API (primary) + yt-dlp fallback.
"""
import json
import logging
import asyncio
from typing import Optional
from datetime import datetime, timedelta

from app.config import get_settings
from app.services import youtube_api
from app.utils.helpers import find_ytdlp, run_command, find_python

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[dict, datetime]] = {}
CACHE_TTL = timedelta(minutes=15)


def _extract_thumbnail(info: dict) -> Optional[str]:
    thumb = info.get("thumbnail")
    if thumb:
        return thumb
    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        best = max(
            thumbnails,
            key=lambda t: (t.get("width") or 0) * (t.get("height") or 0),
        )
        if best.get("url"):
            return best["url"]
    video_id = info.get("id")
    if video_id:
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return None


def _parse_ytdlp_info(raw: str) -> list[dict]:
    results = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        try:
            info = json.loads(line)
            duration = info.get("duration", 0) or 0
            results.append({
                "id": info.get("id", ""),
                "title": info.get("title", "Untitled"),
                "channel": info.get("channel", info.get("uploader", "Unknown")),
                "duration": int(duration),
                "views": info.get("view_count"),
                "thumbnail": _extract_thumbnail(info),
                "url": info.get("webpage_url", f"https://youtube.com/shorts/{info.get('id', '')}"),
                "is_short": duration <= 90,
                "tags": [],
                "description": "",
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def _filter_kwargs(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


async def search_videos(query: str, **kwargs) -> dict:
    """Search with API first, yt-dlp fallback."""
    page_token = kwargs.pop("page_token", None)
    max_results = kwargs.pop("max_results", 20)
    filters = _filter_kwargs(**kwargs)

    cache_key = f"search:{query}:{max_results}:{page_token}:{filters}"
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if datetime.now() - ts < CACHE_TTL:
            return data

    settings = get_settings()
    if settings.youtube_api_key:
        try:
            result = await youtube_api.search_videos(
                query, max_results=max_results, page_token=page_token, **filters
            )
            if result.get("videos"):
                _cache[cache_key] = (result, datetime.now())
                return result
        except Exception as e:
            logger.warning(f"YouTube API search failed, falling back to yt-dlp: {e}")

    videos = await _ytdlp_search(query, max_results, filters)
    result = {
        "videos": videos,
        "total": len(videos),
        "next_page_token": None,
        "prev_page_token": None,
        "source": "yt-dlp",
    }
    _cache[cache_key] = (result, datetime.now())
    return result


async def discover_trending(**kwargs) -> dict:
    page_token = kwargs.pop("page_token", None)
    max_results = kwargs.pop("max_results", 20)
    filters = _filter_kwargs(**kwargs)

    settings = get_settings()
    if settings.youtube_api_key:
        try:
            return await youtube_api.discover_trending(
                max_results=max_results, page_token=page_token, **filters
            )
        except Exception as e:
            logger.warning(f"YouTube API trending failed: {e}")

    return await search_videos("trending viral shorts", max_results=max_results, **filters)


async def discover_hashtag(hashtag: str, **kwargs) -> dict:
    settings = get_settings()
    if settings.youtube_api_key:
        try:
            return await youtube_api.discover_hashtag(hashtag, **kwargs)
        except Exception as e:
            logger.warning(f"YouTube API hashtag failed: {e}")
    tag = hashtag.lstrip("#")
    return await search_videos(f"#{tag} shorts", **kwargs)


async def discover_competitor_channel(handle: str, max_results: int = 50) -> dict:
    """Competitor scraping still uses yt-dlp (no API equivalent for /shorts tab)."""
    cache_key = f"discover:competitor:{handle}:{max_results}"
    if cache_key in _cache:
        data, ts = _cache[cache_key]
        if datetime.now() - ts < CACHE_TTL:
            return data

    ytdlp = find_ytdlp()
    if not ytdlp:
        return {"videos": [], "total": 0, "source": "unavailable"}

    url = f"https://youtube.com/@{handle}/shorts"
    cmd = [
        ytdlp, url,
        "--dump-json", "--skip-download",
        "--no-warnings", "--ignore-errors",
        "--match-filter", "duration >= 15 & duration <= 90",
        "--flat-playlist",
        "--playlist-end", str(max_results),
    ]
    rc, stdout, _ = await asyncio.to_thread(run_command, cmd, timeout=90)
    videos = _parse_ytdlp_info(stdout) if rc == 0 and stdout.strip() else []
    result = {"videos": videos, "total": len(videos), "source": "yt-dlp-competitor"}
    _cache[cache_key] = (result, datetime.now())
    return result


async def _ytdlp_search(query: str, max_results: int, filters: dict) -> list[dict]:
    ytdlp = find_ytdlp()
    if not ytdlp:
        return _fallback_search(query, max_results)

    min_d = filters.get("min_duration", 15)
    max_d = filters.get("max_duration", 90)
    cmd = [
        ytdlp, f"ytsearch{max_results}:{query} shorts",
        "--dump-json", "--skip-download",
        "--no-warnings", "--ignore-errors",
        "--match-filter", f"duration >= {min_d} & duration <= {max_d}",
        "--flat-playlist",
    ]
    rc, stdout, _ = await asyncio.to_thread(run_command, cmd, timeout=60)
    return _parse_ytdlp_info(stdout) if rc == 0 and stdout.strip() else []


def _fallback_search(query: str, max_results: int) -> list[dict]:
    python = find_python()
    if not python:
        return []
    script = f"""
import json, sys
try:
    from yt_dlp import YoutubeDL
    opts = {{'quiet': True, 'no_warnings': True, 'ignoreerrors': True,
           'match_filter': lambda x: 15 <= (x.get('duration') or 0) <= 90,
           'extract_flat': True}}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f'ytsearch{max_results}:{query} shorts', download=False)
        if info and 'entries' in info:
            for e in info['entries']:
                if e:
                    print(json.dumps({{k: e.get(k) for k in ['id','title','channel','uploader','duration','view_count','thumbnail','webpage_url']}}))
except Exception as e:
    print(json.dumps({{'error': str(e)}}), file=sys.stderr)
"""
    rc, stdout, _ = run_command([python, "-c", script], timeout=60)
    return _parse_ytdlp_info(stdout) if rc == 0 else []


def clear_cache():
    _cache.clear()
