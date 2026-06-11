from fastapi import APIRouter, HTTPException

from app.models.schemas import SearchRequest, DiscoverRequest, BatchDownloadRequest
from app.services import discovery, downloader

router = APIRouter()


def _search_filters(req) -> dict:
    return {
        "max_results": req.max_results,
        "page_token": req.page_token,
        "order": req.order,
        "min_duration": req.min_duration,
        "max_duration": req.max_duration,
        "min_views": req.min_views,
        "max_views": req.max_views,
        "published_within_days": req.published_within_days,
        "region_code": req.region_code,
        "video_category_id": req.video_category_id,
    }


@router.post("/search")
async def search_videos(req: SearchRequest):
    try:
        result = await discovery.search_videos(req.query, **_search_filters(req))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/discover")
async def discover_content(req: DiscoverRequest):
    try:
        filters = _search_filters(req)
        if req.source == "trending":
            result = await discovery.discover_trending(**filters)
        elif req.source == "hashtag":
            if not req.query:
                raise HTTPException(status_code=400, detail="Hashtag query required")
            result = await discovery.discover_hashtag(req.query, **filters)
        elif req.source == "competitor":
            if not req.query:
                raise HTTPException(status_code=400, detail="Competitor handle required")
            result = await discovery.discover_competitor_channel(req.query, req.max_results)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown source: {req.source}")

        return {**result, "source": result.get("source", req.source)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery failed: {str(e)}")


@router.post("/download")
async def download_video(req: dict):
    url = req.get("url")
    video_id = req.get("video_id")
    force = req.get("force", False)
    if not url or not video_id:
        raise HTTPException(status_code=400, detail="url and video_id required")

    path = await downloader.download_video(url, video_id, force=force)
    if not path:
        raise HTTPException(status_code=500, detail="Download failed — check ffmpeg is installed")

    return {"video_id": video_id, "path": path, "status": "downloaded", "skipped": not force and path}


@router.post("/batch-download")
async def batch_download(req: BatchDownloadRequest):
    videos = [(v.url, v.video_id) for v in req.videos]
    results = await downloader.batch_download(videos, req.max_concurrent)
    successful = {k: v for k, v in results.items() if v is not None}
    failed = [k for k, v in results.items() if v is None]
    return {
        "downloaded": len(successful),
        "failed": len(failed),
        "results": successful,
        "failed_ids": failed,
    }


@router.get("/download/{video_id}")
async def check_download(video_id: str):
    path = downloader.find_merged_file(video_id)
    if path:
        return {"video_id": video_id, "exists": True, "path": path}
    return {"video_id": video_id, "exists": False}


@router.post("/cache/clear")
async def clear_cache():
    discovery.clear_cache()
    return {"status": "cleared"}
