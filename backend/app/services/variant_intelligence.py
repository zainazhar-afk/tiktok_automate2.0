"""Transcript/audio/scene scoring for long-form-to-shorts planning."""
import asyncio
import json
import os
import re
from dataclasses import dataclass, field

from app.models.schemas import VariantSpec
from app.services import google_ai, groq_ai, subtitles as subtitles_service
from app.services.processor import probe_video
from app.services.subtitle_editor import parse_subtitle_text
from app.utils.helpers import find_ffmpeg, run_command

OUTPUT_DIR = os.path.abspath("output")

HOOK_TERMS = {
    "secret", "mistake", "mistakes", "why", "how", "what", "best", "worst",
    "never", "always", "first", "finally", "truth", "problem", "solution",
    "money", "save", "growth", "viral", "watch", "important", "simple",
    "easy", "fast", "free", "proof", "results", "before", "after",
}
ENERGY_TERMS = {
    "amazing", "insane", "crazy", "huge", "massive", "powerful", "love",
    "hate", "fail", "win", "shocking", "surprising", "unbelievable",
}
CTA_TERMS = {"follow", "subscribe", "comment", "share", "download", "buy", "try", "click"}


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Candidate:
    start: float
    end: float
    score: float
    angle: str
    hook: str
    title: str
    reasons: list[str] = field(default_factory=list)
    transcript_excerpt: str = ""
    source_signals: list[str] = field(default_factory=list)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def _clean_text(text: str, limit: int = 170) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean[: limit - 1].rstrip() + "..." if len(clean) > limit else clean


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _silence_overlap(start: float, end: float, silences: list[tuple[float, float]]) -> float:
    return sum(_overlap(start, end, s, e) for s, e in silences)


def _text_between(cues: list[Cue], start: float, end: float) -> str:
    parts = [cue.text for cue in cues if cue.end >= start and cue.start <= end]
    return _clean_text(" ".join(parts), 220)


async def _transcript_cues(source_path: str, upload_id: str) -> tuple[list[Cue], bool]:
    srt_path = os.path.join(OUTPUT_DIR, f"{upload_id}_analysis.srt")
    if not os.path.exists(srt_path):
        generated = await subtitles_service.generate_subtitles(source_path, f"{upload_id}_analysis")
        if generated:
            srt_path = generated
    if not os.path.exists(srt_path):
        return [], False
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            parsed = parse_subtitle_text(f.read(), "srt")
    except Exception:
        return [], False
    cues = [
        Cue(float(item["start"]), float(item["end"]), str(item["text"]))
        for item in parsed
        if str(item.get("text", "")).strip()
    ]
    return cues, bool(cues)


async def _detect_silences(source_path: str) -> list[tuple[float, float]]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    cmd = [
        ffmpeg, "-hide_banner", "-i", source_path,
        "-af", "silencedetect=noise=-35dB:d=0.45",
        "-f", "null", "-",
    ]
    rc, stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=900)
    text = "\n".join([stdout or "", stderr or ""])
    if rc != 0 and not text:
        return []

    starts = [float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    silences: list[tuple[float, float]] = []
    for idx, start in enumerate(starts):
        end = ends[idx] if idx < len(ends) else start + 1.0
        if end > start:
            silences.append((start, end))
    return silences


async def _detect_scenes(source_path: str) -> list[float]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    cmd = [
        ffmpeg, "-hide_banner", "-i", source_path,
        "-vf", "select=gt(scene\\,0.34),showinfo",
        "-an", "-f", "null", "-",
    ]
    rc, stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=900)
    text = "\n".join([stdout or "", stderr or ""])
    if rc != 0 and not text:
        return []
    times = [float(v) for v in re.findall(r"pts_time:([0-9.]+)", text)]
    deduped: list[float] = []
    for value in sorted(times):
        if not deduped or value - deduped[-1] > 1.5:
            deduped.append(value)
    return deduped[:300]


def _speech_segments(duration: float, silences: list[tuple[float, float]]) -> list[tuple[float, float]]:
    segments: list[tuple[float, float]] = []
    cur = 0.0
    for start, end in sorted(silences):
        if start - cur >= 3.0:
            segments.append((cur, start))
        cur = max(cur, end)
    if duration - cur >= 3.0:
        segments.append((cur, duration))
    return segments or [(0.0, duration)]


def _hook_score(text: str) -> tuple[float, list[str]]:
    tokens = _tokenize(text)
    if not tokens:
        return 0.0, []
    reasons: list[str] = []
    hook_hits = len([tok for tok in tokens if tok in HOOK_TERMS])
    energy_hits = len([tok for tok in tokens if tok in ENERGY_TERMS])
    cta_hits = len([tok for tok in tokens if tok in CTA_TERMS])
    question = "?" in text
    numbers = bool(re.search(r"\b\d+(\.\d+)?\b", text))
    score = hook_hits * 7 + energy_hits * 5 + cta_hits * 3
    if question:
        score += 8
        reasons.append("question hook")
    if numbers:
        score += 6
        reasons.append("specific number")
    if hook_hits:
        reasons.append("strong hook words")
    if energy_hits:
        reasons.append("high-emotion language")
    if cta_hits:
        reasons.append("CTA language")
    density = min(20.0, len(tokens) / 2.0)
    return min(45.0, score + density), reasons


def _angle_for(text: str, index: int) -> str:
    lower = text.lower()
    if "?" in text or any(term in lower for term in ["why", "how", "what"]):
        return "curiosity hook"
    if any(term in lower for term in ["mistake", "wrong", "problem", "avoid"]):
        return "problem-solution"
    if any(term in lower for term in ["result", "proof", "case", "before", "after"]):
        return "proof moment"
    if any(term in lower for term in ["buy", "try", "download", "offer"]):
        return "CTA variant"
    return [
        "hook-first",
        "feature focus",
        "fast recap",
        "objection handler",
        "social proof",
    ][index % 5]


def _candidate_window(anchor: float, duration: float, clip_len: float) -> tuple[float, float]:
    start = _clamp(anchor - 2.0, 0.0, max(0.0, duration - clip_len))
    return round(start, 3), round(min(duration, start + clip_len), 3)


def _score_candidate(
    start: float,
    end: float,
    cues: list[Cue],
    silences: list[tuple[float, float]],
    scenes: list[float],
    anchor_reason: str,
    index: int,
) -> Candidate:
    length = max(0.1, end - start)
    text = _text_between(cues, start, end)
    hook, text_reasons = _hook_score(text)
    silence_ratio = _silence_overlap(start, end, silences) / length
    scene_hits = len([t for t in scenes if start <= t <= end])
    boundary_silence = min(
        _silence_overlap(start, min(end, start + 1.2), silences)
        + _silence_overlap(max(start, end - 1.2), end, silences),
        2.4,
    )
    duration_score = 12.0 if 18 <= length <= 42 else 7.0 if 12 <= length <= 45 else 2.0
    scene_score = min(12.0, scene_hits * 3.0)
    dead_air_penalty = min(25.0, silence_ratio * 70.0 + boundary_silence * 4.0)
    speech_score = max(0.0, 22.0 - dead_air_penalty)
    score = _clamp(hook + duration_score + scene_score + speech_score + 12.0, 0.0, 100.0)

    reasons = [anchor_reason, *text_reasons]
    if silence_ratio < 0.12:
        reasons.append("low dead air")
    if scene_hits:
        reasons.append("scene-change energy")
    if boundary_silence < 0.4:
        reasons.append("clean boundaries")
    if not text and not cues:
        reasons.append("audio/scene heuristic")

    angle = _angle_for(text, index)
    title = text.split(".")[0].strip() if text else angle.replace("-", " ").title()
    title = _clean_text(title or f"Short variant {index + 1}", 70)
    hook_text = _clean_text(text, 105) if text else f"{angle.replace('-', ' ').title()} moment"
    return Candidate(
        start=round(start, 3),
        end=round(end, 3),
        score=round(score, 1),
        angle=angle,
        title=title,
        hook=hook_text,
        reasons=list(dict.fromkeys(reasons))[:5],
        transcript_excerpt=text,
        source_signals=["transcript"] if cues else [],
    )


def _build_candidates(
    duration: float,
    cues: list[Cue],
    silences: list[tuple[float, float]],
    scenes: list[float],
    count: int,
) -> list[Candidate]:
    clip_len = min(45.0, max(14.0, duration / max(count * 1.8, 1)))
    anchors: list[tuple[float, str]] = []

    scored_cues = []
    for cue in cues:
        score, _ = _hook_score(cue.text)
        scored_cues.append((score, cue.start, "transcript hook"))
    anchors.extend([(start, reason) for _score, start, reason in sorted(scored_cues, reverse=True)[: count * 3]])

    speech = _speech_segments(duration, silences)
    for start, end in speech:
        if end - start >= 6.0:
            anchors.append((start, "speaker/segment change"))
            if end - start > 35:
                anchors.append(((start + end) / 2.0, "speech density"))

    for scene in scenes[: count * 3]:
        anchors.append((scene, "scene change"))

    if not anchors:
        max_start = max(0.0, duration - clip_len)
        anchors = [(max_start * idx / max(count - 1, 1), "even fallback") for idx in range(count)]

    candidates: list[Candidate] = []
    seen: set[tuple[int, int]] = set()
    for idx, (anchor, reason) in enumerate(anchors):
        start, end = _candidate_window(anchor, duration, clip_len)
        key = (round(start), round(end))
        if key in seen or end - start < 3:
            continue
        seen.add(key)
        candidate = _score_candidate(start, end, cues, silences, scenes, reason, idx)
        signals = set(candidate.source_signals)
        if silences:
            signals.add("dead-air removal")
        if scenes:
            signals.add("scene changes")
        if reason in {"speaker/segment change", "speech density"}:
            signals.add("speaker/segment changes")
        candidate.source_signals = sorted(signals)
        candidates.append(candidate)

    return sorted(candidates, key=lambda item: item.score, reverse=True)


def _select_top(candidates: list[Candidate], count: int) -> list[Candidate]:
    selected: list[Candidate] = []
    for candidate in candidates:
        if len(selected) >= count:
            break
        too_similar = False
        for existing in selected:
            overlap = _overlap(candidate.start, candidate.end, existing.start, existing.end)
            shorter = min(candidate.end - candidate.start, existing.end - existing.start)
            if shorter > 0 and overlap / shorter > 0.55:
                too_similar = True
                break
        if not too_similar:
            selected.append(candidate)

    for candidate in candidates:
        if len(selected) >= count:
            break
        if candidate not in selected:
            selected.append(candidate)
    return selected[:count]


async def _ai_rewrite(candidates: list[Candidate], duration: float, count: int) -> tuple[list[Candidate] | None, str | None]:
    if not candidates:
        return None, None
    payload = [
        {
            "index": idx,
            "start": item.start,
            "end": item.end,
            "score": item.score,
            "angle": item.angle,
            "excerpt": item.transcript_excerpt[:280],
            "reasons": item.reasons,
        }
        for idx, item in enumerate(candidates[: max(count * 2, 12)])
    ]
    prompt = f"""
Return JSON only.
Pick the best {count} short-form clips from these candidate moments.
The source duration is {duration:.2f} seconds.
Prefer strong hooks, clean speech, low dead air, clear topic shifts, and non-duplicated segments.
Return an array of objects with: index, title, hook, angle, compliance_note.
Candidates:
{json.dumps(payload, ensure_ascii=True)}
"""
    provider = "groq"
    parsed = await groq_ai.generate_json(prompt, timeout=45)
    if not isinstance(parsed, list):
        provider = "gemini"
        parsed = await google_ai.generate_json(prompt, timeout=45)
    if not isinstance(parsed, list):
        return None, None
    by_index = {idx: item for idx, item in enumerate(candidates)}
    rewritten: list[Candidate] = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw.get("index"))
        except Exception:
            continue
        base = by_index.get(idx)
        if not base or base in rewritten:
            continue
        rewritten.append(Candidate(
            **{
                **base.__dict__,
                "title": _clean_text(str(raw.get("title") or base.title), 70),
                "hook": _clean_text(str(raw.get("hook") or base.hook), 110),
                "angle": _clean_text(str(raw.get("angle") or base.angle), 40),
                "reasons": list(dict.fromkeys([f"{provider} selected", *base.reasons]))[:5],
            }
        ))
    return (rewritten[:count], provider) if rewritten else (None, None)


async def intelligent_plan(source_path: str, upload_id: str, *, count: int = 10) -> tuple[list[VariantSpec], bool, dict]:
    probe, transcript_result, silences, scenes = await asyncio.gather(
        probe_video(source_path),
        _transcript_cues(source_path, upload_id),
        _detect_silences(source_path),
        _detect_scenes(source_path),
    )
    duration = max(1.0, float(probe.get("duration", 30.0)))
    cues, transcript_available = transcript_result
    candidates = _build_candidates(duration, cues, silences, scenes, count)
    selected = _select_top(candidates, count)
    ai_selected, ai_provider = await _ai_rewrite(selected, duration, count)
    if ai_selected:
        selected = ai_selected

    while len(selected) < count:
        idx = len(selected)
        start = round(max(0.0, (duration - 20.0) * idx / max(count - 1, 1)), 3)
        end = round(min(duration, start + min(30.0, duration)), 3)
        selected.append(_score_candidate(start, end, cues, silences, scenes, "coverage fallback", idx))

    specs = [
        VariantSpec(
            id=f"variant_{idx:02d}",
            title=item.title or f"Short variant {idx}",
            hook=item.hook or "Lead with the strongest moment.",
            start=item.start,
            end=max(item.start + 0.2, item.end),
            angle=item.angle,
            compliance_note="Selected from transcript/audio/scene scoring; review claims before publishing.",
            score=item.score,
            reasons=item.reasons,
            transcript_excerpt=item.transcript_excerpt,
            source_signals=item.source_signals,
        )
        for idx, item in enumerate(selected[:count], start=1)
    ]
    analysis = {
        "duration": duration,
        "transcript_available": transcript_available,
        "transcript_cues": len(cues),
        "silence_segments": len(silences),
        "scene_changes": len(scenes),
        "candidate_count": len(candidates),
        "planner": f"{ai_provider}_rerank" if ai_provider else "local_intelligence",
        "signals": [
            signal for signal, enabled in [
                ("transcript hooks", transcript_available),
                ("dead-air removal", bool(silences)),
                ("speaker/segment pauses", bool(silences)),
                ("scene changes", bool(scenes)),
                ("best-moment scoring", True),
            ] if enabled
        ],
    }
    return specs, bool(ai_provider), analysis
