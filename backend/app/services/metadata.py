"""
Auto-generate TikTok captions, hashtags, and cover thumbnails.

Caption strategy:
  - Parse video title into a hook (first segment before | or #)
  - Add channel credit and a short CTA line
  - Optionally weave in top keywords from YouTube tags

Hashtag strategy:
  - Extract explicit #tags from title
  - Convert title keywords to hashtags (stopword-filtered)
  - Add YouTube API tags when available
  - Append niche defaults (#shorts #fyp #viral #foryou + topic tags)

Thumbnail strategy:
  - ffmpeg extracts a frame at ~25% of video duration
  - Center-crop to 9:16 (1080x1920) for TikTok cover
"""
import asyncio
import logging
import os
import random
import re
from typing import Optional

from app.utils.helpers import find_ffmpeg, run_command

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "in", "on", "of", "is", "it",
    "this", "that", "with", "my", "your", "at", "by", "from", "latest", "new",
    "video", "short", "shorts", "part", "ep", "episode",
}

NICHE_HASHTAGS = ["shorts", "fyp", "foryou", "viral", "trending", "tiktok"]


def _extract_title_hook(title: str) -> str:
    hook = re.split(r"[|#]", title)[0].strip()
    hook = re.sub(r"\s+", " ", hook)
    return hook[:120] if hook else title[:120]


def _title_keywords(title: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[a-zA-Z]{3,}", title.lower())
    seen = set()
    keywords = []
    for w in words:
        if w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        keywords.append(w)
        if len(keywords) >= limit:
            break
    return keywords


def generate_caption(
    title: str,
    channel: str = "",
    description: str = "",
    tags: Optional[list[str]] = None,
) -> str:
    hook = _extract_title_hook(title)
    ctas = [
        "Save this for later 🔖",
        "Follow for more 🔥",
        "Double tap if you agree 💯",
        "Share with someone who needs this 👇",
    ]
    lines = [hook]
    if channel:
        lines.append(f"via {channel}")
    if description:
        first_line = description.strip().split("\n")[0][:100]
        if first_line and first_line.lower() not in hook.lower():
            lines.append(first_line)
    lines.append(random.choice(ctas))
    return "\n\n".join(lines)


def generate_hashtags(
    title: str,
    tags: Optional[list[str]] = None,
    niche: Optional[str] = None,
    limit: int = 20,
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(tag: str):
        tag = tag.strip().lstrip("#").replace(" ", "")
        if not tag or len(tag) < 2:
            return
        key = tag.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(f"#{tag}")

    for m in re.findall(r"#(\w+)", title):
        add(m)

    for kw in _title_keywords(title):
        add(kw)

    if tags:
        for t in tags[:10]:
            add(t)

    if niche:
        add(niche)

    for t in NICHE_HASHTAGS:
        add(t)

    return found[:limit]


async def generate_thumbnail(
    video_path: str,
    video_id: str,
    duration: float = 30.0,
) -> Optional[str]:
    """Extract a 9:16 cover frame from processed video."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not os.path.exists(video_path):
        return None

    output_path = os.path.join(OUTPUT_DIR, f"{video_id}_cover.jpg")
    timestamp = max(1.0, duration * 0.25)

    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920"
    )
    cmd = [
        ffmpeg, "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-vframes", "1",
        "-vf", vf,
        "-q:v", "2",
        output_path,
    ]
    rc, _, stderr = await asyncio.to_thread(run_command, cmd, timeout=60)
    if rc == 0 and os.path.exists(output_path):
        logger.info(f"Thumbnail generated: {output_path}")
        return output_path

    logger.warning(f"Thumbnail failed: {stderr[:200] if stderr else 'unknown'}")
    return None


async def generate_all_metadata(
    video_id: str,
    video_path: str,
    title: str = "",
    channel: str = "",
    description: str = "",
    tags: Optional[list[str]] = None,
    duration: float = 30.0,
) -> dict:
    caption = generate_caption(title, channel, description, tags)
    hashtags = generate_hashtags(title, tags)
    thumbnail_path = await generate_thumbnail(video_path, video_id, duration)
    return {
        "caption": caption,
        "hashtags": hashtags,
        "thumbnail_path": thumbnail_path,
    }
