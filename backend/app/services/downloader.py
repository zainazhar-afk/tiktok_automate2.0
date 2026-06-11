"""
Ultra-fast YouTube video downloader using yt-dlp + aria2c.
"""
import os
import asyncio
import logging
from typing import Optional

from app.config import get_settings
from app.utils.helpers import find_ytdlp, find_aria2c, find_ffmpeg, run_command

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.abspath("temp/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def find_merged_file(video_id: str) -> Optional[str]:
    """Return path only if a fully merged video file exists."""
    for ext in ["mp4", "webm", "mkv"]:
        path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
        if os.path.isfile(path) and os.path.getsize(path) > 100_000:
            return path
    return None


def _has_fragments(video_id: str) -> bool:
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(video_id) and (".f" in f or f.endswith(".m4a")):
            return True
    return False


def _cleanup_fragments(video_id: str):
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(video_id) and f != f"{video_id}.mp4":
            try:
                os.remove(os.path.join(DOWNLOAD_DIR, f))
            except OSError:
                pass


async def download_video(url: str, video_id: str, *, force: bool = False) -> Optional[str]:
    """Download a single video. Skips if merged file already exists."""
    existing = find_merged_file(video_id)
    if existing and not force:
        logger.info(f"Skipping download, already exists: {existing}")
        return existing

    ytdlp = find_ytdlp()
    if not ytdlp:
        logger.error("yt-dlp not found")
        return None

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.error("ffmpeg required to merge downloads")
        return None

    aria2c = find_aria2c()
    _cleanup_fragments(video_id)

    output_template = os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s")
    expected_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    cmd = [
        ytdlp, url,
        "-o", output_template,
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-warnings",
        "--force-ipv4",
        "--concurrent-fragments", "8",
        "--no-mtime",
        "--no-write-thumbnail",
        "--no-write-info-json",
        "--no-embed-metadata",
        "--no-embed-subs",
        "--no-embed-chapters",
        "--ffmpeg-location", ffmpeg,
    ]

    if aria2c:
        cmd.extend([
            "--downloader", "aria2c",
            "--downloader-args",
            "aria2c:--async-dns=true --min-split-size=1M --max-connection-per-server=8 "
            "--file-allocation=none --max-concurrent-downloads=8 --split=8",
        ])

    logger.info(f"Downloading: {url}")
    rc, _, stderr = await asyncio.to_thread(run_command, cmd, timeout=300)
    logger.info(f"Download complete: rc={rc}")

    merged = find_merged_file(video_id)
    if merged:
        _cleanup_fragments(video_id)
        return merged

    if _has_fragments(video_id):
        logger.error(f"Download left unmerged fragments for {video_id} — ffmpeg merge failed")

    logger.error(f"Download failed for {video_id}: {stderr[:500] if stderr else 'no merged file'}")
    return None


async def batch_download(
    videos: list[tuple[str, str]],
    max_concurrent: Optional[int] = None,
) -> dict[str, Optional[str]]:
    settings = get_settings()
    limit = max_concurrent or settings.max_download_concurrent
    sem = asyncio.Semaphore(limit)
    results: dict[str, Optional[str]] = {}

    async def download_one(url: str, vid: str):
        async with sem:
            path = await download_video(url, vid)
            results[vid] = path

    await asyncio.gather(
        *[download_one(url, vid) for url, vid in videos],
        return_exceptions=True,
    )
    return results


def cleanup_download(video_id: str):
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(video_id):
            try:
                os.remove(os.path.join(DOWNLOAD_DIR, f))
            except OSError:
                pass
