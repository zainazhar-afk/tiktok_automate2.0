"""
Ultra-fast YouTube video downloader using yt-dlp + aria2c.
"""
import os
import asyncio
import logging
import re
import subprocess
import time
from typing import Optional
from typing import Callable

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


def _parse_ytdlp_progress(line: str) -> Optional[float]:
    percent = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
    if percent:
        return max(0.0, min(1.0, float(percent.group(1)) / 100.0))
    if "Merging formats" in line or "Merger" in line:
        return 0.95
    if "Deleting original file" in line:
        return 0.98
    return None


def _run_download_command(
    cmd: list[str],
    *,
    timeout: int,
    progress_callback: Callable[[float, str], None],
) -> tuple[int, str, str]:
    output_lines: list[str] = []
    start = time.monotonic()
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)

    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line:
                output_lines.append(line)
                progress = _parse_ytdlp_progress(line)
                if progress is not None:
                    progress_callback(progress, line)
            if timeout and time.monotonic() - start > timeout:
                process.kill()
                return -1, "\n".join(output_lines), "Command timed out"
        return process.wait(timeout=5), "\n".join(output_lines), ""
    except subprocess.TimeoutExpired:
        process.kill()
        return -1, "\n".join(output_lines), "Command timed out"
    except Exception as e:
        process.kill()
        return -1, "\n".join(output_lines), str(e)


async def download_video(
    url: str,
    video_id: str,
    *,
    force: bool = False,
    timeout: int = 300,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Optional[str]:
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
    if progress_callback:
        cmd.append("--newline")

    if aria2c:
        cmd.extend([
            "--downloader", "aria2c",
            "--downloader-args",
            "aria2c:--async-dns=true --min-split-size=1M --max-connection-per-server=8 "
            "--file-allocation=none --max-concurrent-downloads=8 --split=8",
        ])

    logger.info(f"Downloading: {url}")
    if progress_callback:
        progress_callback(0.01, "Starting download")
        rc, _, stderr = await asyncio.to_thread(
            _run_download_command,
            cmd,
            timeout=timeout,
            progress_callback=progress_callback,
        )
    else:
        rc, _, stderr = await asyncio.to_thread(run_command, cmd, timeout=timeout)
    logger.info(f"Download complete: rc={rc}")

    merged = find_merged_file(video_id)
    if merged:
        if progress_callback:
            progress_callback(1.0, "Download complete")
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
