"""AI-style clip scoring for timeline edits using local transcript/audio/vision signals."""
from __future__ import annotations

import asyncio
import os
import re

from app.models.schemas import ClipScoreMetric, TimelineClip, TimelineClipScore, TimelineProject
from app.services import subtitle_editor
from app.services.subtitle_editor import source_video_path
from app.utils.helpers import find_ffmpeg, run_command

HOOK_TERMS = {
    "secret", "why", "how", "what", "mistake", "best", "worst", "never",
    "money", "free", "fast", "simple", "proof", "results", "before", "after",
    "watch", "first", "finally", "truth", "problem", "solution",
}
ENERGY_TERMS = {"insane", "crazy", "huge", "amazing", "love", "hate", "fail", "win", "shocking"}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _words_for_clip(track: dict, clip: TimelineClip) -> list[dict]:
    words = []
    for word in track.get("words", []):
        try:
            start = float(word.get("start", 0.0))
            end = float(word.get("end", start))
        except Exception:
            continue
        if end >= clip.source_start and start <= clip.source_end:
            words.append(word)
    return words


def _clip_text(track: dict, clip: TimelineClip) -> str:
    words = _words_for_clip(track, clip)
    if words:
        return " ".join(str(word.get("text", "")) for word in words).strip()
    return clip.title or ""


def _hook_strength(text: str, title: str) -> tuple[float, str]:
    source = f"{title} {text}".lower()
    tokens = re.findall(r"[a-z0-9']+", source)
    if not tokens:
        return 35.0, "No transcript text available"
    hook_hits = sum(1 for tok in tokens if tok in HOOK_TERMS)
    energy_hits = sum(1 for tok in tokens if tok in ENERGY_TERMS)
    number_bonus = 12 if re.search(r"\b\d+(\.\d+)?\b", source) else 0
    question_bonus = 10 if "?" in source or any(tok in {"why", "how", "what"} for tok in tokens[:10]) else 0
    score = min(100.0, 28 + hook_hits * 10 + energy_hits * 7 + number_bonus + question_bonus + min(18, len(tokens) / 2))
    detail = f"{hook_hits} hook words, {energy_hits} energy words"
    return round(score, 1), detail


async def _detect_silences(source_path: str) -> list[tuple[float, float]]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    cmd = [ffmpeg, "-hide_banner", "-i", source_path, "-af", "silencedetect=noise=-35dB:d=0.45", "-f", "null", "-"]
    rc, stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=900)
    text = "\n".join([stdout or "", stderr or ""])
    if rc != 0 and not text:
        return []
    starts = [float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    return [(start, ends[idx] if idx < len(ends) else start + 1.0) for idx, start in enumerate(starts)]


async def _detect_scenes(source_path: str) -> list[float]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    cmd = [ffmpeg, "-hide_banner", "-i", source_path, "-vf", "select=gt(scene\\,0.34),showinfo", "-an", "-f", "null", "-"]
    rc, stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=900)
    text = "\n".join([stdout or "", stderr or ""])
    if rc != 0 and not text:
        return []
    times = [float(v) for v in re.findall(r"pts_time:([0-9.]+)", text)]
    deduped: list[float] = []
    for value in sorted(times):
        if not deduped or value - deduped[-1] > 1.4:
            deduped.append(value)
    return deduped


def _dead_air_metric(clip: TimelineClip, silences: list[tuple[float, float]]) -> tuple[float, str, float]:
    duration = max(0.1, clip.source_end - clip.source_start)
    silence = sum(_overlap(clip.source_start, clip.source_end, s, e) for s, e in silences)
    pct = min(1.0, silence / duration)
    score = _clamp(100.0 - pct * 135.0)
    return round(score, 1), f"{round(pct * 100)}% silent/dead air", pct


def _caption_readability(track: dict, clip: TimelineClip) -> tuple[float, str]:
    words = _words_for_clip(track, clip)
    duration = max(0.1, clip.source_end - clip.source_start)
    if not words:
        return 45.0, "No caption words for this clip"
    wps = len(words) / duration
    avg_len = sum(len(str(w.get("text", ""))) for w in words) / max(1, len(words))
    pace_score = 100.0 - abs(wps - 2.9) * 22.0
    length_score = 100.0 - max(0.0, avg_len - 8.5) * 6.0
    highlight_bonus = 6.0 if any(w.get("highlighted") for w in words) else 0.0
    score = _clamp(pace_score * 0.65 + length_score * 0.35 + highlight_bonus)
    return round(score, 1), f"{len(words)} words, {wps:.1f} words/sec"


def _face_visibility_sync(source_path: str, clip: TimelineClip) -> tuple[float, str]:
    try:
        import cv2  # type: ignore
    except Exception:
        if clip.crop_mode == "face" or clip.keyframes:
            return 68.0, "Tracking keyframes present"
        return 45.0, "OpenCV unavailable"
    cap = cv2.VideoCapture(source_path)
    if not cap.isOpened():
        return 45.0, "Could not open video for face scan"
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        cap.release()
        return 45.0, "Face detector unavailable"
    sampled = 0
    hits = 0
    t = clip.source_start
    while t <= clip.source_end + 0.001 and sampled < 18:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(34, 34))
        sampled += 1
        if len(faces) > 0:
            hits += 1
        t += 0.6
    cap.release()
    if sampled == 0:
        return 45.0, "No frames sampled"
    pct = hits / sampled
    return round(_clamp(35 + pct * 65), 1), f"Face visible in {hits}/{sampled} sampled frames"


def _pacing_metric(clip: TimelineClip, scene_count: int, dead_air_pct: float) -> tuple[float, str]:
    duration = max(0.1, clip.source_end - clip.source_start)
    duration_score = 100.0 - abs(duration - 24.0) * 2.0
    scene_rate = scene_count / max(1.0, duration / 15.0)
    scene_score = min(100.0, 45 + scene_rate * 18)
    score = _clamp(duration_score * 0.55 + scene_score * 0.3 + (100 - dead_air_pct * 100) * 0.15)
    return round(score, 1), f"{duration:.1f}s, {scene_count} scene changes"


async def score_project(project: TimelineProject) -> dict:
    video_id = project.video_id
    source = source_video_path(video_id)
    if not source or not os.path.exists(source):
        raise FileNotFoundError("Video not found")
    track = subtitle_editor.get_or_create_track(video_id)
    silences, scenes = await asyncio.gather(_detect_silences(source), _detect_scenes(source))
    scores: list[TimelineClipScore] = []
    face_tasks = [asyncio.to_thread(_face_visibility_sync, source, clip) for clip in project.clips]
    face_results = await asyncio.gather(*face_tasks, return_exceptions=True)

    for idx, clip in enumerate(project.clips):
        text = _clip_text(track, clip)
        hook, hook_detail = _hook_strength(text, clip.title)
        dead_air, dead_air_detail, dead_air_pct = _dead_air_metric(clip, silences)
        caption, caption_detail = _caption_readability(track, clip)
        face_result = face_results[idx]
        if isinstance(face_result, Exception):
            face, face_detail = 45.0, str(face_result)
        else:
            face, face_detail = face_result
        scene_count = len([t for t in scenes if clip.source_start <= t <= clip.source_end])
        scene_score = min(100.0, 45 + scene_count * 14)
        pacing, pacing_detail = _pacing_metric(clip, scene_count, dead_air_pct)
        retention = _clamp(hook * 0.24 + dead_air * 0.18 + face * 0.16 + caption * 0.16 + pacing * 0.16 + scene_score * 0.10)
        metrics = [
            ClipScoreMetric(label="Hook strength", value=hook, detail=hook_detail),
            ClipScoreMetric(label="Dead-air control", value=dead_air, detail=dead_air_detail),
            ClipScoreMetric(label="Face visibility", value=face, detail=face_detail),
            ClipScoreMetric(label="Caption readability", value=caption, detail=caption_detail),
            ClipScoreMetric(label="Pacing", value=pacing, detail=pacing_detail),
            ClipScoreMetric(label="Scene energy", value=round(scene_score, 1), detail=f"{scene_count} detected scene changes"),
            ClipScoreMetric(label="Retention prediction", value=round(retention, 1), detail="Weighted local prediction"),
        ]
        reasons = []
        for metric in metrics[:6]:
            if metric.value >= 75:
                reasons.append(f"Strong {metric.label.lower()}")
            elif metric.value < 50:
                reasons.append(f"Needs {metric.label.lower()} work")
        scores.append(TimelineClipScore(
            clip_id=clip.id,
            title=clip.title or f"Clip {idx + 1}",
            overall=round(retention, 1),
            metrics=metrics,
            reasons=reasons[:4],
        ))
    return {
        "video_id": video_id,
        "scores": [score.model_dump() for score in scores],
        "analysis": {
            "silence_segments": len(silences),
            "scene_changes": len(scenes),
            "transcript_words": len(track.get("words", [])),
        },
    }
