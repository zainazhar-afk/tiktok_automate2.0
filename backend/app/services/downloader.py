"""
YouTube video downloader using yt-dlp with optional aria2c acceleration.
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
from app.services.safety import safe_id, validate_public_video_url
from app.tenant import storage_video_id
from app.utils.helpers import find_ytdlp, find_aria2c, find_ffmpeg, run_command

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.abspath("temp/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class DownloadError(RuntimeError):
    """Raised when a caller needs the concrete yt-dlp failure reason."""


def _summarize_download_error(*parts: str) -> str:
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        return "Video download failed"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    preferred = [
        line for line in lines
        if (
            "ERROR:" in line
            or "does not pass filter" in line
            or "File is larger than max-filesize" in line
            or "Requested format is not available" in line
            or "Sign in" in line
            or "Private video" in line
            or "This video is unavailable" in line
        )
    ]
    selected = preferred[-3:] if preferred else lines[-3:]
    summary = re.sub(r"\s+", " ", " ".join(selected)).strip()
    return summary[:700] if summary else "Video download failed"


def _download_failure_detail(rc: int, stdout: str, stderr: str) -> str:
    detail = _summarize_download_error(stdout, stderr)
    if "does not pass filter" in detail and "duration <=" in detail:
        detail = f"{detail} Increase MAX_SOURCE_DURATION_SECONDS to allow longer sources."
    if rc == 0 and detail == "Video download failed":
        detail = "yt-dlp finished without creating a merged media file"
    return detail


def _is_aria2c_failure(detail: str) -> bool:
    lowered = detail.lower()
    return "aria2c exited" in lowered or "external downloader" in lowered


def _build_download_command(
    *,
    ytdlp: str,
    url: str,
    output_template: str,
    selected_format: str,
    max_download_mb: int,
    duration_limit: int,
    ffmpeg: str,
    newline: bool,
    aria2c: str | None,
) -> list[str]:
    cmd = [
        ytdlp, url,
        "-o", output_template,
        "--format", selected_format,
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
        "--max-filesize", f"{max_download_mb}M",
        "--match-filter", f"duration <= {duration_limit}",
        "--ffmpeg-location", ffmpeg,
    ]
    if newline:
        cmd.append("--newline")

    if aria2c:
        cmd.extend([
            "--downloader", "aria2c",
            "--downloader-args",
            "aria2c:--async-dns=true --min-split-size=1M --max-connection-per-server=8 "
            "--file-allocation=none --max-concurrent-downloads=8 --split=8",
        ])
    return cmd


def find_merged_file(video_id: str) -> Optional[str]:
    """Return path only if a fully merged video file exists."""
    video_id = safe_id(video_id, "video id")
    file_id = storage_video_id(video_id)
    for ext in ["mp4", "webm", "mkv"]:
        path = os.path.join(DOWNLOAD_DIR, f"{file_id}.{ext}")
        if os.path.isfile(path) and os.path.getsize(path) > 100_000:
            return path
    return None


def _has_fragments(video_id: str) -> bool:
    video_id = safe_id(video_id, "video id")
    file_id = storage_video_id(video_id)
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(file_id) and (".f" in f or f.endswith(".m4a")):
            return True
    return False


def _cleanup_fragments(video_id: str):
    video_id = safe_id(video_id, "video id")
    file_id = storage_video_id(video_id)
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(file_id) and f != f"{file_id}.mp4":
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


class _DownloadProgressNormalizer:
    """Keep UI progress monotonic across separate video/audio downloads."""

    def __init__(self, initial: float = 0.01):
        self.phase = 0
        self.last_raw = 0.0
        self.last_reported = initial

    def normalize(self, progress: float, line: str) -> tuple[float, str]:
        if "[download]" in line:
            if self.last_raw and progress + 0.2 < self.last_raw and self.last_reported > 0.5:
                self.phase += 1
            self.last_raw = progress
            if self.phase == 0:
                normalized = progress * 0.85
            elif self.phase == 1:
                normalized = 0.85 + progress * 0.10
            else:
                normalized = 0.95 + progress * 0.03
        else:
            normalized = progress

        normalized = max(self.last_reported, min(1.0, normalized))
        self.last_reported = normalized
        if abs(normalized - progress) >= 0.005:
            return normalized, f"Overall {normalized * 100:.1f}% - {line}"
        return normalized, line


def _run_download_command(
    cmd: list[str],
    *,
    timeout: int,
    progress_callback: Callable[[float, str], None],
) -> tuple[int, str, str]:
    output_lines: list[str] = []
    normalizer = _DownloadProgressNormalizer()
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
                    normalized, message = normalizer.normalize(progress, line)
                    progress_callback(normalized, message)
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
    raise_on_error: bool = False,
    format_selector: str | None = None,
    max_duration_seconds: int | None = None,
    use_external_downloader: bool = True,
) -> Optional[str]:
    """Download a single video. Skips if merged file already exists."""
    video_id = safe_id(video_id, "video id")
    url = validate_public_video_url(url)
    existing = find_merged_file(video_id)
    if existing and not force:
        logger.info(f"Skipping download, already exists: {existing}")
        return existing

    ytdlp = find_ytdlp()
    if not ytdlp:
        detail = "yt-dlp not found"
        logger.error(detail)
        if raise_on_error:
            raise DownloadError(detail)
        return None

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        detail = "ffmpeg required to merge downloads"
        logger.error(detail)
        if raise_on_error:
            raise DownloadError(detail)
        return None

    settings = get_settings()
    aria2c = find_aria2c() if use_external_downloader else None
    _cleanup_fragments(video_id)

    file_id = storage_video_id(video_id)
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")
    selected_format = format_selector or "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best"
    duration_limit = int(max_duration_seconds or settings.max_source_duration_seconds)

    async def run_download(use_aria2c: bool) -> tuple[int, str, str]:
        cmd = _build_download_command(
            ytdlp=ytdlp,
            url=url,
            output_template=output_template,
            selected_format=selected_format,
            max_download_mb=settings.max_download_mb,
            duration_limit=duration_limit,
            ffmpeg=ffmpeg,
            newline=bool(progress_callback),
            aria2c=aria2c if use_aria2c else None,
        )
        if progress_callback:
            progress_callback(0.01, "Starting download" if use_aria2c else "Retrying download without aria2c")
            return await asyncio.to_thread(
                _run_download_command,
                cmd,
                timeout=timeout,
                progress_callback=progress_callback,
            )
        return await asyncio.to_thread(run_command, cmd, timeout=timeout)

    logger.info(f"Downloading: {url}")
    rc, stdout, stderr = await run_download(bool(aria2c))
    logger.info(f"Download complete: rc={rc}")

    merged = find_merged_file(video_id)
    if merged:
        if progress_callback:
            progress_callback(1.0, "Download complete")
        _cleanup_fragments(video_id)
        return merged

    if _has_fragments(video_id):
        logger.error(f"Download left unmerged fragments for {video_id}; ffmpeg merge failed")

    detail = _download_failure_detail(rc, stdout, stderr)
    if aria2c and _is_aria2c_failure(detail):
        logger.warning(f"aria2c failed for {video_id}; retrying with yt-dlp downloader")
        if progress_callback:
            progress_callback(0.01, "aria2c failed; retrying with yt-dlp downloader")
        _cleanup_fragments(video_id)
        rc, stdout, stderr = await run_download(False)
        logger.info(f"Download retry complete: rc={rc}")
        merged = find_merged_file(video_id)
        if merged:
            if progress_callback:
                progress_callback(1.0, "Download complete")
            _cleanup_fragments(video_id)
            return merged
        if _has_fragments(video_id):
            logger.error(f"Download left unmerged fragments for {video_id}; ffmpeg merge failed")
        detail = _download_failure_detail(rc, stdout, stderr)

    logger.error(f"Download failed for {video_id}: {detail}")
    if progress_callback:
        progress_callback(0.0, f"Download failed: {detail}")
    if raise_on_error:
        raise DownloadError(detail)
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
        vid = safe_id(vid, "video id")
        url = validate_public_video_url(url)
        async with sem:
            path = await download_video(url, vid)
            results[vid] = path

    await asyncio.gather(
        *[download_one(url, vid) for url, vid in videos],
        return_exceptions=True,
    )
    return results


def cleanup_download(video_id: str):
    video_id = safe_id(video_id, "video id")
    file_id = storage_video_id(video_id)
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith(file_id):
            try:
                os.remove(os.path.join(DOWNLOAD_DIR, f))
            except OSError:
                pass
