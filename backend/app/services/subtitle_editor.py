"""Editable subtitle tracks, sidecar export, and burned-in render helpers."""
import asyncio
import html
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from app.models.schemas import SubtitleTrack
from app.services import state_store, subtitles
from app.utils.helpers import find_ffmpeg, run_command

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SUPPORTED_POSITIONS = {"top", "middle", "bottom"}
SUPPORTED_STYLES = {"default", "bold", "minimal", "neon"}
SUPPORTED_ANIMATIONS = {"none", "pop", "slide", "karaoke"}


def _safe_video_id(video_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id or ""):
        raise ValueError("Invalid video id")
    return video_id


def _parse_ts(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        h = 0
        m, s = parts
    elif len(parts) == 3:
        h, m, s = parts
    else:
        return 0.0
    return int(h) * 3600 + int(m) * 60 + float(s)


def _format_srt_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_ts(seconds: float) -> str:
    return _format_srt_ts(seconds).replace(",", ".")


def parse_subtitle_text(content: str, fmt: str = "srt") -> list[dict]:
    """Parse SRT/VTT into cue dicts: {start, end, text}."""
    text = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if fmt.lower() == "vtt":
        text = re.sub(r"^\s*WEBVTT.*?(?:\n\n|\Z)", "", text, flags=re.S)

    cues: list[dict] = []
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        time_idx = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if time_idx == -1:
            continue
        start_raw, end_raw = [p.strip().split(" ", 1)[0] for p in lines[time_idx].split("-->", 1)]
        cue_text = " ".join(lines[time_idx + 1 :]).strip()
        if not cue_text:
            continue
        cues.append({
            "start": _parse_ts(start_raw),
            "end": _parse_ts(end_raw),
            "text": cue_text,
        })
    return cues


def cues_to_words(cues: list[dict]) -> list[dict]:
    words: list[dict] = []
    for cue in cues:
        parts = re.findall(r"\S+", cue.get("text", ""))
        if not parts:
            continue
        start = float(cue.get("start", 0.0))
        end = max(start + 0.2, float(cue.get("end", start + 1.0)))
        step = (end - start) / len(parts)
        for idx, part in enumerate(parts):
            words.append({
                "id": uuid.uuid4().hex[:10],
                "text": part,
                "start": round(start + step * idx, 3),
                "end": round(start + step * (idx + 1), 3),
                "highlighted": False,
            })
    return words


def words_to_cues(words: list[dict], *, max_words: int = 6, max_gap: float = 0.6) -> list[dict]:
    sorted_words = sorted(words, key=lambda w: (float(w.get("start", 0)), float(w.get("end", 0))))
    cues: list[dict] = []
    current: list[dict] = []

    def flush():
        if not current:
            return
        cues.append({
            "start": float(current[0].get("start", 0)),
            "end": float(current[-1].get("end", current[0].get("start", 0) + 1)),
            "words": [dict(w) for w in current],
            "text": " ".join(str(w.get("text", "")).strip() for w in current).strip(),
        })
        current.clear()

    last_end: Optional[float] = None
    for word in sorted_words:
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        start = float(word.get("start", 0))
        if current and (len(current) >= max_words or (last_end is not None and start - last_end > max_gap)):
            flush()
        current.append(word)
        last_end = float(word.get("end", start + 0.3))
    flush()
    return cues


def export_srt(track: dict) -> str:
    lines: list[str] = []
    for idx, cue in enumerate(words_to_cues(track.get("words", [])), start=1):
        lines.append(str(idx))
        lines.append(f"{_format_srt_ts(cue['start'])} --> {_format_srt_ts(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def export_vtt(track: dict) -> str:
    lines = ["WEBVTT", ""]
    for cue in words_to_cues(track.get("words", [])):
        lines.append(f"{_format_vtt_ts(cue['start'])} --> {_format_vtt_ts(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _default_words(text: str) -> list[dict]:
    parts = re.findall(r"\S+", text.strip()) or ["Edit", "your", "captions"]
    words: list[dict] = []
    for idx, part in enumerate(parts):
        start = idx * 0.45
        words.append({
            "id": uuid.uuid4().hex[:10],
            "text": part,
            "start": round(start, 3),
            "end": round(start + 0.42, 3),
            "highlighted": False,
        })
    return words


def _transcript_parts(text: str) -> list[str]:
    return re.findall(r"\S+", text.strip())


def _word_boundaries(words: list[dict]) -> list[float]:
    sorted_words = sorted(words, key=lambda w: (float(w.get("start", 0)), float(w.get("end", 0))))
    if not sorted_words:
        return []
    boundaries = [float(sorted_words[0].get("start", 0.0) or 0.0)]
    for prev, current in zip(sorted_words, sorted_words[1:]):
        prev_end = float(prev.get("end", prev.get("start", 0.0) + 0.3) or 0.0)
        current_start = float(current.get("start", prev_end) or prev_end)
        boundaries.append(max(boundaries[-1], (prev_end + current_start) / 2))
    last = sorted_words[-1]
    last_start = float(last.get("start", boundaries[-1]) or boundaries[-1])
    last_end = float(last.get("end", last_start + 0.3) or last_start + 0.3)
    boundaries.append(max(boundaries[-1] + 0.12, last_end))
    return boundaries


def _interpolate_boundaries(boundaries: list[float], position: float) -> float:
    if not boundaries:
        return max(0.0, position * 0.45)
    if len(boundaries) == 1:
        return boundaries[0]
    position = max(0.0, min(1.0, position))
    scaled = position * (len(boundaries) - 1)
    lower = int(scaled)
    upper = min(lower + 1, len(boundaries) - 1)
    frac = scaled - lower
    return boundaries[lower] + (boundaries[upper] - boundaries[lower]) * frac


def _align_transcript_words(transcript: str, existing_words: list[dict]) -> list[dict]:
    parts = _transcript_parts(transcript)
    if not parts:
        return []
    existing = sorted(existing_words or [], key=lambda w: (float(w.get("start", 0)), float(w.get("end", 0))))
    boundaries = _word_boundaries(existing)
    if not boundaries:
        boundaries = [idx * 0.45 for idx in range(len(parts) + 1)]

    new_words: list[dict] = []
    existing_count = len(existing)
    total = len(parts)
    for idx, text in enumerate(parts):
        start = _interpolate_boundaries(boundaries, idx / total)
        end = _interpolate_boundaries(boundaries, (idx + 1) / total)
        if end <= start:
            end = start + 0.2

        existing_idx = min(existing_count - 1, round(idx * max(existing_count - 1, 0) / max(total - 1, 1))) if existing_count else -1
        existing_word = existing[existing_idx] if existing_idx >= 0 else {}
        new_words.append({
            "id": existing_word.get("id") or uuid.uuid4().hex[:10],
            "text": text,
            "start": round(max(0.0, start), 3),
            "end": round(max(start + 0.12, end), 3),
            "highlighted": bool(existing_word.get("highlighted", False)),
        })
    return new_words


def _track_from_words(video_id: str, words: list[dict], language: str = "en") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "video_id": video_id,
        "language": language,
        "style": "default",
        "position": "bottom",
        "animation": "none",
        "transcript": " ".join(w.get("text", "") for w in words).strip(),
        "words": words,
        "updated_at": now,
    }


def get_or_create_track(video_id: str) -> dict:
    video_id = _safe_video_id(video_id)
    saved = state_store.get_subtitle_track(video_id)
    if saved:
        return saved

    srt_path = os.path.join(OUTPUT_DIR, f"{video_id}.srt")
    if os.path.exists(srt_path):
        with open(srt_path, "r", encoding="utf-8") as f:
            words = cues_to_words(parse_subtitle_text(f.read(), "srt"))
        track = _track_from_words(video_id, words)
        state_store.save_subtitle_track(video_id, track)
        return state_store.get_subtitle_track(video_id) or track

    video = state_store.get_video(video_id) or {}
    fallback_text = video.get("caption") or video.get("title") or "Edit your captions"
    track = _track_from_words(video_id, _default_words(fallback_text))
    state_store.save_subtitle_track(video_id, track)
    return state_store.get_subtitle_track(video_id) or track


def _normalize_language(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return "auto" if raw in {"", "auto", "detect", "default", "none"} else raw


async def transcribe_track(
    video_id: str,
    force: bool = True,
    language: str = "auto",
    provider: str = "auto",
) -> dict:
    video_id = _safe_video_id(video_id)
    source = source_video_path(video_id)
    if not source:
        raise FileNotFoundError("Processed video not found")

    requested_language = _normalize_language(language)
    srt_path = os.path.join(OUTPUT_DIR, f"{video_id}.srt")
    if force or not os.path.exists(srt_path):
        generated = await subtitles.generate_subtitles(
            source,
            video_id,
            language=requested_language,
            provider=provider,
        )
        if not generated:
            if requested_language == "en":
                raise RuntimeError(
                    "Transcript generation failed for English audio. "
                    "If the source audio is Urdu, choose Audio language = Urdu, Auto detect, or Multilingual."
                )
            raise RuntimeError(
                "Transcript generation failed. Check Groq/Deepgram keys, choose the source audio language, "
                "or install faster-whisper."
            )
        srt_path = generated

    with open(srt_path, "r", encoding="utf-8") as f:
        words = cues_to_words(parse_subtitle_text(f.read(), "srt"))
    if not words:
        raise RuntimeError("Transcript generation produced no words")

    existing = state_store.get_subtitle_track(video_id) or {}
    track_language = requested_language if requested_language != "auto" else existing.get("language", "auto")
    track = _track_from_words(video_id, words, track_language)
    track.update({
        "style": existing.get("style", "default"),
        "position": existing.get("position", "bottom"),
        "animation": existing.get("animation", "none"),
    })
    state_store.save_subtitle_track(video_id, track)
    return state_store.get_subtitle_track(video_id) or track


def save_track(track: SubtitleTrack) -> dict:
    video_id = _safe_video_id(track.video_id)
    data = track.model_dump()
    data["video_id"] = video_id
    data["style"] = data.get("style") if data.get("style") in SUPPORTED_STYLES else "default"
    data["position"] = data.get("position") if data.get("position") in SUPPORTED_POSITIONS else "bottom"
    data["animation"] = data.get("animation") if data.get("animation") in SUPPORTED_ANIMATIONS else "none"
    data["transcript"] = data.get("transcript") or " ".join(w["text"] for w in data.get("words", []))
    state_store.save_subtitle_track(video_id, data)
    return state_store.get_subtitle_track(video_id) or data


def apply_transcript(track: SubtitleTrack) -> dict:
    video_id = _safe_video_id(track.video_id)
    data = track.model_dump()
    transcript = data.get("transcript", "").strip()
    words = _align_transcript_words(transcript, data.get("words", []))
    if not words:
        raise ValueError("Transcript is empty")

    data["video_id"] = video_id
    data["words"] = words
    data["transcript"] = " ".join(word["text"] for word in words).strip()
    data["style"] = data.get("style") if data.get("style") in SUPPORTED_STYLES else "default"
    data["position"] = data.get("position") if data.get("position") in SUPPORTED_POSITIONS else "bottom"
    data["animation"] = data.get("animation") if data.get("animation") in SUPPORTED_ANIMATIONS else "none"
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_store.save_subtitle_track(video_id, data)
    saved = state_store.get_subtitle_track(video_id) or data
    write_sidecars(saved)
    return saved


def import_track(video_id: str, content: str, fmt: str) -> dict:
    video_id = _safe_video_id(video_id)
    cues = parse_subtitle_text(content, fmt)
    words = cues_to_words(cues)
    if not words:
        raise ValueError("No subtitle cues found")
    existing = state_store.get_subtitle_track(video_id) or {}
    track = _track_from_words(video_id, words, existing.get("language", "en"))
    track.update({
        "style": existing.get("style", "default"),
        "position": existing.get("position", "bottom"),
        "animation": existing.get("animation", "none"),
    })
    state_store.save_subtitle_track(video_id, track)
    return state_store.get_subtitle_track(video_id) or track


async def _translate_text(text: str, source: str, target: str) -> str:
    if source == target:
        return text
    params = {"q": text, "langpair": f"{source}|{target}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get("https://api.mymemory.translated.net/get", params=params)
        resp.raise_for_status()
        data = resp.json()
    translated = data.get("responseData", {}).get("translatedText")
    return html.unescape(translated or text)


async def translate_track(video_id: str, source_language: str, target_language: str) -> dict:
    track = get_or_create_track(video_id)
    cues = words_to_cues(track.get("words", []), max_words=8)
    translated_words: list[dict] = []
    for cue in cues:
        translated = await _translate_text(cue["text"], source_language, target_language)
        new_words = cues_to_words([{
            "start": cue["start"],
            "end": cue["end"],
            "text": translated,
        }])
        translated_words.extend(new_words)
    next_track = {
        **track,
        "language": target_language,
        "transcript": " ".join(w["text"] for w in translated_words).strip(),
        "words": translated_words,
    }
    state_store.save_subtitle_track(video_id, next_track)
    return state_store.get_subtitle_track(video_id) or next_track


def write_sidecars(track: dict) -> dict:
    video_id = _safe_video_id(track["video_id"])
    srt_path = os.path.join(OUTPUT_DIR, f"{video_id}_edited.srt")
    vtt_path = os.path.join(OUTPUT_DIR, f"{video_id}_edited.vtt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(export_srt(track))
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(export_vtt(track))
    return {"srt": srt_path, "vtt": vtt_path}


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round((seconds - int(seconds)) * 100))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _style_line(track: dict) -> str:
    style = track.get("style", "default")
    position = track.get("position", "bottom")
    alignment = {"bottom": 2, "middle": 5, "top": 8}.get(position, 2)
    margin_v = {"bottom": 120, "middle": 40, "top": 120}.get(position, 120)
    if style == "bold":
        return f"Style: Default,Arial Black,72,&H0000FFFF,&H000000FF,&H00000000,&HAA000000,-1,0,0,0,100,100,0,0,1,6,2,{alignment},80,80,{margin_v},1"
    if style == "minimal":
        return f"Style: Default,Arial,54,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,{alignment},80,80,{margin_v},1"
    if style == "neon":
        return f"Style: Default,Arial Black,68,&H0000FFAA,&H000000FF,&H00000000,&HAA220044,-1,0,0,0,100,100,0,0,1,5,3,{alignment},80,80,{margin_v},1"
    return f"Style: Default,Arial,62,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,-1,0,0,0,100,100,0,0,1,4,2,{alignment},80,80,{margin_v},1"


def write_ass(track: dict) -> str:
    video_id = _safe_video_id(track["video_id"])
    ass_path = os.path.join(OUTPUT_DIR, f"{video_id}_edited.ass")
    animation = track.get("animation", "none")
    prefix = ""
    if animation == "pop":
        prefix = r"{\fad(80,80)\t(0,120,\fscx108\fscy108)}"
    elif animation == "slide":
        prefix = r"{\move(540,1780,540,1660,0,180)}"
    elif animation == "karaoke":
        prefix = r"{\fad(40,60)}"

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        _style_line(track),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for cue in words_to_cues(track.get("words", [])):
        parts = []
        for word in cue["words"]:
            text = _ass_escape(str(word.get("text", "")))
            if word.get("highlighted"):
                parts.append(r"{\c&H0000FFFF&\b1}" + text + r"{\r}")
            else:
                parts.append(text)
        line = " ".join(parts).strip()
        if line:
            lines.append(
                f"Dialogue: 0,{_ass_time(cue['start'])},{_ass_time(cue['end'])},Default,,0,0,0,,{prefix}{line}"
            )

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return ass_path


def _escape_filter_path(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    return p.replace(":", "\\:")


def source_video_path(video_id: str) -> Optional[str]:
    video_id = _safe_video_id(video_id)
    for suffix in ["_processed.mp4", "_edited.mp4", ".mp4"]:
        path = os.path.join(OUTPUT_DIR, f"{video_id}{suffix}")
        if os.path.isfile(path):
            return path
    video = state_store.get_video(video_id) or {}
    output = video.get("output_path")
    if output and os.path.isfile(output):
        return output
    return None


async def render_video(video_id: str) -> dict:
    track = get_or_create_track(video_id)
    ffmpeg = find_ffmpeg()
    source = source_video_path(video_id)
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    if not source:
        raise FileNotFoundError("Processed video not found")

    ass_path = write_ass(track)
    write_sidecars(track)
    output_path = os.path.join(OUTPUT_DIR, f"{video_id}_edited.mp4")
    vf = f"ass='{_escape_filter_path(ass_path)}'"
    cmd = [
        ffmpeg, "-y", "-i", source,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    rc, _stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=600)
    if rc != 0 or not os.path.exists(output_path):
        raise RuntimeError(stderr[-500:] if stderr else "Subtitle render failed")
    state_store.upsert_video(video_id, status="completed", output_path=output_path)
    return {
        "video_id": video_id,
        "output_path": output_path,
        "filename": Path(output_path).name,
    }
