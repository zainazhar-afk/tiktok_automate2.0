"""
Auto subtitle generation via faster-whisper (optional dependency).

If faster-whisper isn't installed, generation is skipped gracefully so the
rest of the processing pipeline keeps working. Install with:
    pip install faster-whisper

The generated .srt is meant to be burned into the video by the processor's
`subtitles` filter.
"""
import asyncio
import logging
import os
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

_model_cache: dict = {}


def _whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _format_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _transcribe_to_srt(input_path: str, srt_path: str, model_size: str) -> bool:
    """Blocking transcription; runs inside a thread."""
    from faster_whisper import WhisperModel

    model = _model_cache.get(model_size)
    if model is None:
        # int8 keeps it light enough for CPU; falls back automatically on GPU absence
        model = WhisperModel(model_size, device="auto", compute_type="int8")
        _model_cache[model_size] = model

    segments, _info = model.transcribe(input_path, vad_filter=True, word_timestamps=False)

    lines = []
    idx = 1
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_format_ts(seg.start)} --> {_format_ts(seg.end)}")
        lines.append(text)
        lines.append("")
        idx += 1

    if idx == 1:
        return False  # nothing transcribed

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True


async def generate_subtitles(input_path: str, video_id: str) -> Optional[str]:
    """Transcribe audio to an .srt file. Returns path or None when unavailable."""
    if not _whisper_available():
        logger.warning(
            "auto_subtitles requested but faster-whisper is not installed; "
            "skipping. Install with: pip install faster-whisper"
        )
        return None

    if not os.path.exists(input_path):
        return None

    srt_path = os.path.join(OUTPUT_DIR, f"{video_id}.srt")
    model_size = get_settings().whisper_model
    try:
        ok = await asyncio.to_thread(_transcribe_to_srt, input_path, srt_path, model_size)
    except Exception as e:
        logger.warning(f"Subtitle transcription failed for {video_id}: {e}")
        return None

    if ok and os.path.exists(srt_path):
        logger.info(f"Subtitles generated: {srt_path}")
        return srt_path
    return None
