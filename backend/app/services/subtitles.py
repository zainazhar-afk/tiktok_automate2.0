"""
Auto subtitle generation via Deepgram or faster-whisper.

Deepgram is used first when DEEPGRAM_API_KEYS are configured. If it is not
configured, quota-limited, or fails, faster-whisper is used as a local fallback.
If faster-whisper isn't installed, generation is skipped gracefully so the rest
of the processing pipeline keeps working. Install with:
    pip install faster-whisper

The generated .srt is meant to be burned into the video by the processor's
`subtitles` filter.
"""
import asyncio
import logging
import os
import mimetypes
from typing import Optional

import httpx

from app.config import get_settings
from app.utils.helpers import find_ffmpeg, run_command

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

_model_cache: dict = {}
_groq_key_offset = 0
_deepgram_key_offset = 0


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


def _write_cues_srt(cues: list[dict], srt_path: str) -> bool:
    lines = []
    idx = 1
    for cue in cues:
        text = str(cue.get("text", "")).strip()
        start = float(cue.get("start", 0.0) or 0.0)
        end = float(cue.get("end", start + 0.4) or start + 0.4)
        if not text or end <= start:
            continue
        lines.append(str(idx))
        lines.append(f"{_format_ts(start)} --> {_format_ts(end)}")
        lines.append(text)
        lines.append("")
        idx += 1
    if idx == 1:
        return False
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True


async def _compressed_audio_path(input_path: str, video_id: str) -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return input_path
    temp_dir = os.path.abspath(os.path.join("temp", "transcribe"))
    os.makedirs(temp_dir, exist_ok=True)
    out_path = os.path.join(temp_dir, f"{video_id}_speech.mp3")
    cmd = [
        ffmpeg, "-y",
        "-i", input_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "48k",
        out_path,
    ]
    rc, _stdout, _stderr = await asyncio.to_thread(run_command, cmd, timeout=600)
    if rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
        return out_path
    return input_path


def _groq_cues(payload: dict) -> list[dict]:
    segments = payload.get("segments") or []
    cues = []
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        cues.append({
            "start": float(segment.get("start", 0.0) or 0.0),
            "end": float(segment.get("end", 0.0) or 0.0),
            "text": text,
        })
    if cues:
        return cues
    text = str(payload.get("text", "")).strip()
    if text:
        return [{"start": 0.0, "end": 30.0, "text": text}]
    return []


async def _groq_to_srt(input_path: str, srt_path: str, video_id: str) -> bool:
    global _groq_key_offset

    settings = get_settings()
    keys = settings.groq_api_keys
    if not keys:
        return False

    audio_path = await _compressed_audio_path(input_path, video_id)
    ordered = keys[_groq_key_offset:] + keys[:_groq_key_offset]
    mime = mimetypes.guess_type(audio_path)[0] or "audio/mpeg"

    async with httpx.AsyncClient(timeout=300) as client:
        for key in ordered:
            try:
                with open(audio_path, "rb") as media:
                    files = {"file": (os.path.basename(audio_path), media, mime)}
                    data = {
                        "model": settings.groq_transcription_model,
                        "response_format": "verbose_json",
                        "temperature": "0",
                    }
                    if settings.groq_language:
                        data["language"] = settings.groq_language
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {key}"},
                        data=data,
                        files=files,
                    )
                if resp.status_code in {401, 403, 408, 413, 429, 500, 502, 503, 504}:
                    logger.warning(f"Groq transcription key failed: HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                cues = _groq_cues(resp.json())
                if _write_cues_srt(cues, srt_path):
                    _groq_key_offset = (keys.index(key) + 1) % len(keys)
                    logger.info(f"Groq subtitles generated: {srt_path}")
                    return True
            except Exception as e:
                logger.warning(f"Groq transcription failed with one key: {e}")
                continue
    return False


def _deepgram_cues(payload: dict) -> list[dict]:
    results = payload.get("results", {})
    utterances = results.get("utterances") or []
    cues = []
    for utterance in utterances:
        text = str(utterance.get("transcript", "")).strip()
        if not text:
            continue
        speaker = utterance.get("speaker")
        if speaker is not None:
            text = f"Speaker {speaker}: {text}"
        cues.append({
            "start": float(utterance.get("start", 0.0) or 0.0),
            "end": float(utterance.get("end", 0.0) or 0.0),
            "text": text,
        })
    if cues:
        return cues

    channels = results.get("channels") or []
    if not channels:
        return []
    alternatives = channels[0].get("alternatives") or []
    if not alternatives:
        return []
    words = alternatives[0].get("words") or []
    current: list[dict] = []
    last_end: Optional[float] = None
    last_speaker = None

    def flush():
        nonlocal current, last_end, last_speaker
        if not current:
            return
        text = " ".join(
            str(word.get("punctuated_word") or word.get("word") or "").strip()
            for word in current
        ).strip()
        if text:
            speaker = current[0].get("speaker")
            if speaker is not None:
                text = f"Speaker {speaker}: {text}"
            cues.append({
                "start": float(current[0].get("start", 0.0) or 0.0),
                "end": float(current[-1].get("end", current[0].get("start", 0.0) + 0.4) or 0.0),
                "text": text,
            })
        current = []
        last_end = None
        last_speaker = None

    for word in words:
        text = str(word.get("word") or word.get("punctuated_word") or "").strip()
        if not text:
            continue
        start = float(word.get("start", 0.0) or 0.0)
        end = float(word.get("end", start + 0.4) or start + 0.4)
        speaker = word.get("speaker")
        gap = start - last_end if last_end is not None else 0.0
        span = end - float(current[0].get("start", start) if current else start)
        if current and (len(current) >= 9 or gap > 0.75 or span > 4.5 or speaker != last_speaker):
            flush()
        current.append(word)
        last_end = end
        last_speaker = speaker
    flush()
    return cues


async def _deepgram_to_srt(input_path: str, srt_path: str) -> bool:
    global _deepgram_key_offset

    settings = get_settings()
    keys = settings.deepgram_api_keys
    if not keys:
        return False

    ordered = keys[_deepgram_key_offset:] + keys[:_deepgram_key_offset]
    mime = mimetypes.guess_type(input_path)[0] or "application/octet-stream"
    params = {
        "model": settings.deepgram_model,
        "language": settings.deepgram_language,
        "smart_format": "true",
        "punctuate": "true",
        "utterances": "true",
        "diarize": "true",
    }
    with open(input_path, "rb") as f:
        media = f.read()

    async with httpx.AsyncClient(timeout=300) as client:
        for key in ordered:
            try:
                resp = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    params=params,
                    headers={
                        "Authorization": f"Token {key}",
                        "Content-Type": mime,
                    },
                    content=media,
                )
                if resp.status_code in {401, 403, 408, 429, 500, 502, 503, 504}:
                    logger.warning(f"Deepgram transcription key failed: HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                cues = _deepgram_cues(resp.json())
                if _write_cues_srt(cues, srt_path):
                    _deepgram_key_offset = (keys.index(key) + 1) % len(keys)
                    logger.info(f"Deepgram subtitles generated: {srt_path}")
                    return True
            except Exception as e:
                logger.warning(f"Deepgram transcription failed with one key: {e}")
                continue
    return False


def _transcribe_to_srt(input_path: str, srt_path: str, model_size: str) -> bool:
    """Blocking transcription; runs inside a thread."""
    from faster_whisper import WhisperModel

    model = _model_cache.get(model_size)
    if model is None:
        # int8 keeps it light enough for CPU; falls back automatically on GPU absence
        model = WhisperModel(model_size, device="auto", compute_type="int8")
        _model_cache[model_size] = model

    segments, _info = model.transcribe(input_path, vad_filter=True, word_timestamps=False)

    cues = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        cues.append({"start": seg.start, "end": seg.end, "text": text})
    return _write_cues_srt(cues, srt_path)


async def generate_subtitles(input_path: str, video_id: str) -> Optional[str]:
    """Transcribe audio to an .srt file. Returns path or None when unavailable."""
    if not os.path.exists(input_path):
        return None

    srt_path = os.path.join(OUTPUT_DIR, f"{video_id}.srt")
    settings = get_settings()
    provider = settings.transcription_provider.lower()

    if provider in {"auto", "groq"} and settings.groq_api_keys:
        ok = await _groq_to_srt(input_path, srt_path, video_id)
        if ok and os.path.exists(srt_path):
            return srt_path
        if provider == "groq":
            logger.warning("Groq transcription failed and provider is locked to groq")
            return None

    if provider in {"auto", "deepgram"} and settings.deepgram_api_keys:
        ok = await _deepgram_to_srt(input_path, srt_path)
        if ok and os.path.exists(srt_path):
            return srt_path
        if provider == "deepgram":
            logger.warning("Deepgram transcription failed and provider is locked to deepgram")
            return None

    if not _whisper_available():
        logger.warning(
            "faster-whisper is not installed and Deepgram is unavailable; "
            "skipping. Install with: pip install faster-whisper"
        )
        return None

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
