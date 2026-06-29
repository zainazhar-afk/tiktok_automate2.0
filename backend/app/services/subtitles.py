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
import re
import shutil
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
AUTO_LANGUAGE_VALUES = {"", "auto", "detect", "default", "none"}
TRANSCRIPTION_PROVIDERS = {"auto", "groq", "deepgram", "whisper"}


def _normalize_language(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return "" if raw in AUTO_LANGUAGE_VALUES else raw


def _normalize_provider(value: str | None) -> str:
    raw = (value or "auto").strip().lower()
    return raw if raw in TRANSCRIPTION_PROVIDERS else "auto"


def _groq_language(value: str | None) -> str:
    language = _normalize_language(value)
    return "" if language == "multi" else language


def _find_ffprobe() -> Optional[str]:
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    from_path = shutil.which(exe)
    if from_path:
        return from_path
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        sibling = os.path.join(os.path.dirname(ffmpeg), exe)
        if os.path.isfile(sibling):
            return sibling
    return None


async def _media_duration(input_path: str) -> float:
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return 0.0
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    rc, stdout, _stderr = await asyncio.to_thread(run_command, cmd, timeout=60)
    if rc != 0:
        return 0.0
    try:
        return max(0.0, float(stdout.strip()))
    except ValueError:
        return 0.0


def _parse_srt_ts(value: str) -> float:
    try:
        h, m, s = value.strip().replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return 0.0


def _srt_stats(srt_path: str) -> dict:
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    time_re = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
        r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
    )
    cue_count = 0
    last_end = 0.0
    text_lines: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or line.upper() == "WEBVTT":
            continue
        match = time_re.search(line)
        if match:
            cue_count += 1
            last_end = max(last_end, _parse_srt_ts(match.group("end")))
            continue
        text_lines.append(line)

    text = " ".join(text_lines).strip()
    return {
        "cues": cue_count,
        "words": len(re.findall(r"\S+", text)),
        "chars": len(text),
        "last_end": last_end,
    }


async def _srt_looks_usable(srt_path: str, input_path: str, provider: str) -> bool:
    stats = _srt_stats(srt_path)
    if stats["words"] == 0 and stats["chars"] < 2:
        logger.warning(f"{provider} transcript produced no text")
        return False

    duration = await _media_duration(input_path)
    if duration < 12:
        return True

    if duration >= 60 and stats["words"] < 14 and stats["chars"] < 80:
        logger.warning(f"{provider} transcript looks too short for {duration:.1f}s media")
        return False
    if duration >= 30 and stats["words"] < 8 and stats["chars"] < 40:
        logger.warning(f"{provider} transcript looks too short for {duration:.1f}s media")
        return False
    if duration >= 30 and stats["last_end"] < duration * 0.2 and stats["words"] < 16:
        logger.warning(f"{provider} transcript covers only {stats['last_end']:.1f}s of {duration:.1f}s media")
        return False
    return True


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


async def _groq_to_srt(input_path: str, srt_path: str, video_id: str, language: str = "") -> bool:
    global _groq_key_offset

    settings = get_settings()
    keys = settings.groq_api_keys
    if not keys:
        return False

    audio_path = await _compressed_audio_path(input_path, video_id)
    ordered = keys[_groq_key_offset:] + keys[:_groq_key_offset]
    mime = mimetypes.guess_type(audio_path)[0] or "audio/mpeg"
    selected_language = _groq_language(language)

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
                    if selected_language:
                        data["language"] = selected_language
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


async def _deepgram_to_srt(input_path: str, srt_path: str, language: str = "") -> bool:
    global _deepgram_key_offset

    settings = get_settings()
    keys = settings.deepgram_api_keys
    if not keys:
        return False

    ordered = keys[_deepgram_key_offset:] + keys[:_deepgram_key_offset]
    mime = mimetypes.guess_type(input_path)[0] or "application/octet-stream"
    selected_language = _normalize_language(language)
    params = {
        "model": settings.deepgram_model,
        "smart_format": "true",
        "punctuate": "true",
        "utterances": "true",
        "diarize": "true",
    }
    if selected_language:
        params["language"] = selected_language
    else:
        params["detect_language"] = "true"
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


def _transcribe_to_srt(input_path: str, srt_path: str, model_size: str, language: str = "") -> bool:
    """Blocking transcription; runs inside a thread."""
    from faster_whisper import WhisperModel

    model = _model_cache.get(model_size)
    if model is None:
        # int8 keeps it light enough for CPU; falls back automatically on GPU absence
        model = WhisperModel(model_size, device="auto", compute_type="int8")
        _model_cache[model_size] = model

    selected_language = _normalize_language(language)
    segments, _info = model.transcribe(
        input_path,
        vad_filter=True,
        word_timestamps=False,
        language=selected_language or None,
    )

    cues = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        cues.append({"start": seg.start, "end": seg.end, "text": text})
    return _write_cues_srt(cues, srt_path)


async def generate_subtitles(
    input_path: str,
    video_id: str,
    language: str | None = None,
    provider: str | None = None,
) -> Optional[str]:
    """Transcribe audio to an .srt file. Returns path or None when unavailable."""
    if not os.path.exists(input_path):
        return None

    srt_path = os.path.join(OUTPUT_DIR, f"{video_id}.srt")
    settings = get_settings()
    selected_provider = _normalize_provider(provider or settings.transcription_provider)
    explicit_language = language is not None
    selected_language = _normalize_language(language)
    groq_language = selected_language if explicit_language else _normalize_language(settings.groq_language)
    deepgram_language = selected_language if explicit_language else _normalize_language(settings.deepgram_language)
    whisper_language = selected_language if explicit_language else ""

    async def usable(provider_name: str) -> bool:
        if not os.path.exists(srt_path):
            return False
        if selected_provider != "auto":
            return True
        ok = await _srt_looks_usable(srt_path, input_path, provider_name)
        if not ok:
            try:
                os.remove(srt_path)
            except OSError:
                pass
        return ok

    if selected_provider in {"auto", "groq"} and settings.groq_api_keys:
        ok = await _groq_to_srt(input_path, srt_path, video_id, groq_language)
        if ok and await usable("Groq"):
            return srt_path
        if selected_provider == "groq":
            logger.warning("Groq transcription failed and provider is locked to groq")
            return None

    if selected_provider in {"auto", "deepgram"} and settings.deepgram_api_keys:
        ok = await _deepgram_to_srt(input_path, srt_path, deepgram_language)
        if ok and await usable("Deepgram"):
            return srt_path
        if selected_provider == "deepgram":
            logger.warning("Deepgram transcription failed and provider is locked to deepgram")
            return None

    if selected_provider in {"auto", "whisper"}:
        if not _whisper_available():
            logger.warning(
                "faster-whisper is not installed and API transcription is unavailable; "
                "skipping. Install with: pip install faster-whisper"
            )
            return None

        model_size = get_settings().whisper_model
        try:
            ok = await asyncio.to_thread(
                _transcribe_to_srt,
                input_path,
                srt_path,
                model_size,
                whisper_language,
            )
        except Exception as e:
            logger.warning(f"Subtitle transcription failed for {video_id}: {e}")
            return None

        if ok and await usable("faster-whisper"):
            logger.info(f"Subtitles generated: {srt_path}")
            return srt_path
    return None
