"""Timeline editing and crop render helpers."""
import asyncio
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models.schemas import TimelineClip, TimelineProject
from app.services import google_ai, groq_ai, smart_crop_tracker, state_store, subtitle_editor
from app.services.processor import TARGET_H, TARGET_W, probe_video, validate_output
from app.services.subtitle_editor import source_video_path
from app.tenant import storage_video_id
from app.utils.helpers import find_ffmpeg, run_command

OUTPUT_DIR = os.path.abspath("output")
TEMP_DIR = os.path.abspath(os.path.join("temp", "timeline"))
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


def _safe_video_id(video_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id or ""):
        raise ValueError("Invalid video id")
    return video_id


def _clip_dict(clip: TimelineClip) -> dict:
    data = clip.model_dump()
    data["source_start"] = round(float(data["source_start"]), 3)
    data["source_end"] = round(max(data["source_start"] + 0.1, float(data["source_end"])), 3)
    return data


async def default_project(video_id: str) -> dict:
    video_id = _safe_video_id(video_id)
    source = source_video_path(video_id)
    duration = 30.0
    if source:
        duration = (await probe_video(source)).get("duration", 30.0)
    end = round(min(max(duration, 0.5), 30.0), 3)
    return {
        "video_id": video_id,
        "crop_mode": "center",
        "keep_face_centered": False,
        "split_layout": "speaker_gameplay",
        "clips": [{
            "id": uuid.uuid4().hex[:10],
            "title": "Clip 1",
            "source_start": 0.0,
            "source_end": end,
            "muted": False,
            "crop_mode": "center",
            "layout": "single",
            "x_pct": 0.0,
            "y_pct": 0.0,
            "w_pct": 1.0,
            "h_pct": 1.0,
            "keyframes": [],
            "broll_source": None,
            "broll_mode": "none",
            "broll_start": 0.0,
            "auto_zoom": False,
            "zoom_strength": 0.06,
        }],
        "jump_cut_cleanup": False,
        "auto_captions": False,
        "hook_title": "",
        "hook_subtitle": "",
        "brand_template": "none",
        "brand_name": "",
        "brand_primary_color": "#06b6d4",
        "brand_accent_color": "#facc15",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_or_create_project(video_id: str) -> dict:
    video_id = _safe_video_id(video_id)
    saved = state_store.get_timeline_project(video_id)
    if saved:
        normalized = TimelineProject(**saved).model_dump()
        normalized["updated_at"] = saved.get("updated_at")
        if normalized != saved:
            state_store.save_timeline_project(video_id, normalized)
            return state_store.get_timeline_project(video_id) or normalized
        return normalized
    project = await default_project(video_id)
    state_store.save_timeline_project(video_id, project)
    return state_store.get_timeline_project(video_id) or project


def save_project(project: TimelineProject) -> dict:
    video_id = _safe_video_id(project.video_id)
    data = project.model_dump()
    data["video_id"] = video_id
    data["clips"] = [_clip_dict(TimelineClip(**clip)) for clip in data.get("clips", [])]
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_store.save_timeline_project(video_id, data)
    return state_store.get_timeline_project(video_id) or data


def _bounded_crop(clip: TimelineClip) -> tuple[float, float, float, float]:
    w = max(0.05, min(1.0, clip.w_pct))
    h = max(0.05, min(1.0, clip.h_pct))
    x = max(0.0, min(1.0 - w, clip.x_pct))
    y = max(0.0, min(1.0 - h, clip.y_pct))
    return x, y, w, h


def _safe_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    name = filename.strip()
    if not name or name in {".", ".."}:
        return None
    if "/" in name or "\\" in name or Path(name).name != name:
        return None
    return name


def _resolve_broll_source(filename: str | None) -> str | None:
    safe = _safe_filename(filename)
    if not safe:
        return None
    visible_filenames: set[str] = set()
    for row in state_store.list_videos():
        for key in ["output_path", "download_path", "thumbnail_path"]:
            value = row.get(key)
            if value:
                visible_filenames.add(os.path.basename(value))
        vid = str(row.get("video_id") or "")
        if vid:
            file_id = storage_video_id(vid)
            visible_filenames.update({
                f"{file_id}.mp4",
                f"{file_id}_processed.mp4",
                f"{file_id}_edited.mp4",
                f"{file_id}_timeline.mp4",
            })
    if safe not in visible_filenames:
        return None
    for directory in [OUTPUT_DIR, os.path.abspath(os.path.join("temp", "downloads"))]:
        root = Path(directory).resolve()
        path = (root / safe).resolve()
        if path.parent == root and path.is_file():
            return str(path)
    return None


def _escape_filter_path(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    return p.replace(":", "\\:")


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round((seconds - int(seconds)) * 100))
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _hex_to_ass(color: str, fallback: str) -> str:
    raw = (color or fallback).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", raw):
        raw = fallback.lstrip("#")
    rr, gg, bb = raw[0:2], raw[2:4], raw[4:6]
    return f"&H00{bb}{gg}{rr}&"


def _caption_words_for_clip(track: dict | None, clip: TimelineClip, duration: float) -> list[dict]:
    if not track:
        return []
    words = []
    for word in track.get("words", []):
        try:
            start = float(word.get("start", 0.0))
            end = float(word.get("end", start + 0.25))
        except Exception:
            continue
        if end < clip.source_start or start > clip.source_end:
            continue
        local_start = max(0.0, start - clip.source_start)
        local_end = min(duration, max(local_start + 0.12, end - clip.source_start))
        if local_start >= duration:
            continue
        words.append({
            "id": word.get("id") or uuid.uuid4().hex[:10],
            "text": word.get("text", ""),
            "start": round(local_start, 3),
            "end": round(local_end, 3),
            "highlighted": bool(word.get("highlighted")),
        })
    return words


def _write_segment_ass(
    project: TimelineProject,
    clip: TimelineClip,
    subtitle_track: dict | None,
    work_dir: str,
    index: int,
    duration: float,
) -> str | None:
    has_hook = index == 1 and bool((project.hook_title or project.hook_subtitle).strip())
    has_brand = project.brand_template != "none" and bool(project.brand_name.strip())
    caption_words = _caption_words_for_clip(subtitle_track, clip, duration) if project.auto_captions else []
    if not has_hook and not has_brand and not caption_words:
        return None

    primary = _hex_to_ass(project.brand_primary_color, "#06b6d4")
    accent = _hex_to_ass(project.brand_accent_color, "#facc15")
    caption_margin = 150 if project.brand_template == "podcast" else 110
    ass_path = os.path.join(work_dir, f"segment_{index:03d}.ass")
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {TARGET_W}",
        f"PlayResY: {TARGET_H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Caption,Arial Black,62,&H00FFFFFF&,{accent},&H00101010&,&HA0000000&,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,{caption_margin},1",
        f"Style: CaptionAccent,Arial Black,62,{accent},{primary},&H00101010&,&HA0000000&,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,{caption_margin},1",
        f"Style: Hook,Arial Black,78,{primary},&H00FFFFFF&,&H00101010&,&H90000000&,-1,0,0,0,100,100,0,0,1,6,3,8,70,70,130,1",
        "Style: HookSub,Arial,44,&H00FFFFFF&,&H00FFFFFF&,&H00101010&,&H90000000&,0,0,0,0,100,100,0,0,1,4,1,8,90,90,255,1",
        f"Style: Brand,Arial Black,38,{accent},&H00FFFFFF&,&H00101010&,&H90000000&,-1,0,0,0,100,100,0,0,1,4,1,7,70,70,95,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]

    hook_end = min(duration, 4.2)
    if has_hook and hook_end > 0.2:
        if project.hook_title.strip():
            lines.append(
                f"Dialogue: 2,{_ass_time(0.0)},{_ass_time(hook_end)},Hook,,0,0,0,,{{\\fad(80,120)}}{_ass_escape(project.hook_title.strip())}"
            )
        if project.hook_subtitle.strip():
            lines.append(
                f"Dialogue: 2,{_ass_time(0.25)},{_ass_time(hook_end)},HookSub,,0,0,0,,{{\\fad(80,120)}}{_ass_escape(project.hook_subtitle.strip())}"
            )

    if has_brand:
        brand_text = _ass_escape(project.brand_name.strip())
        if project.brand_template == "product":
            brand_text = r"{\bord5}" + brand_text
        elif project.brand_template == "podcast":
            brand_text = r"{\fsp2}" + brand_text.upper()
        lines.append(
            f"Dialogue: 1,{_ass_time(0.0)},{_ass_time(duration)},Brand,,0,0,0,,{{\\fad(60,60)}}{brand_text}"
        )

    for cue in subtitle_editor.words_to_cues(caption_words, max_words=5, max_gap=0.55):
        parts = []
        for word in cue["words"]:
            text = _ass_escape(str(word.get("text", "")))
            if word.get("highlighted"):
                parts.append(r"{\c" + accent + r"\b1}" + text + r"{\r}")
            else:
                parts.append(text)
        cue_text = " ".join(parts).strip()
        if cue_text:
            lines.append(
                f"Dialogue: 3,{_ass_time(cue['start'])},{_ass_time(cue['end'])},Caption,,0,0,0,,{{\\fad(40,60)}}{cue_text}"
            )

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return ass_path


async def _detect_silences(source_path: str, noise_db: float, min_silence: float) -> list[tuple[float, float]]:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return []
    cmd = [
        ffmpeg, "-hide_banner", "-i", source_path,
        "-af", f"silencedetect=noise={noise_db:.1f}dB:d={min_silence:.2f}",
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
        end = ends[idx] if idx < len(ends) else start + min_silence
        if end > start:
            silences.append((start, end))
    return silences


def _zoom_chain(strength: float) -> str:
    strength = max(0.0, min(0.2, strength))
    if strength <= 0:
        return ""
    width = int(round(TARGET_W * (1.0 + strength) / 2.0) * 2)
    height = int(round(TARGET_H * (1.0 + strength) / 2.0) * 2)
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H}"
    )


def _with_auto_zoom(chain: str, clip: TimelineClip) -> str:
    zoom = _zoom_chain(clip.zoom_strength if clip.auto_zoom else 0.0)
    return f"{chain},{zoom}" if zoom else chain


def _with_jump_cut_fade(chain: str, duration: float, enabled: bool) -> str:
    if not enabled:
        return chain
    fade = min(0.08, max(0.02, duration / 8.0))
    out_start = max(0.0, duration - fade)
    return f"{chain},fade=t=in:st=0:d={fade:.3f},fade=t=out:st={out_start:.3f}:d={fade:.3f}"


def _relative_keyframes(clip: TimelineClip) -> list[dict]:
    frames = []
    for frame in sorted(clip.keyframes or [], key=lambda item: item.time):
        local_time = max(0.0, float(frame.time) - clip.source_start)
        frames.append({
            "time": round(local_time, 3),
            "x_pct": max(0.0, min(1.0, float(frame.x_pct))),
            "y_pct": max(0.0, min(1.0, float(frame.y_pct))),
            "w_pct": max(0.05, min(1.0, float(frame.w_pct))),
            "h_pct": max(0.05, min(1.0, float(frame.h_pct))),
        })
    return frames


def _interpolated_expr(points: list[tuple[float, float]], default: float) -> str:
    if not points:
        return f"{default:.6f}"
    if len(points) == 1:
        return f"{points[0][1]:.6f}"
    expr = f"{points[-1][1]:.6f}"
    for idx in range(len(points) - 2, -1, -1):
        t0, v0 = points[idx]
        t1, v1 = points[idx + 1]
        if t1 <= t0:
            segment = f"{v1:.6f}"
        else:
            segment = f"({v0:.6f}+{(v1 - v0):.6f}*(t-{t0:.3f})/{(t1 - t0):.3f})"
        expr = f"if(lte(t,{t0:.3f}),{v0:.6f},if(lte(t,{t1:.3f}),{segment},{expr}))"
    return expr


def _keyframed_crop_chain(clip: TimelineClip) -> str | None:
    frames = _relative_keyframes(clip)
    if not frames:
        return None
    first = frames[0]
    w = first["w_pct"]
    h = first["h_pct"]
    x_expr = _interpolated_expr([(frame["time"], frame["x_pct"]) for frame in frames], clip.x_pct)
    y_expr = _interpolated_expr([(frame["time"], frame["y_pct"]) for frame in frames], clip.y_pct)
    crop_w = f"trunc(iw*{w:.6f}/2)*2"
    crop_h = f"trunc(ih*{h:.6f}/2)*2"
    x_safe = f"max(0,min(iw-{crop_w},iw*({x_expr})))"
    y_safe = f"max(0,min(ih-{crop_h},ih*({y_expr})))"
    return (
        f"crop=w='{crop_w}':h='{crop_h}':x='{x_safe}':y='{y_safe}',"
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},setsar=1"
    )


def _normal_chain(clip: TimelineClip, keep_face_centered: bool) -> str:
    crop_mode = "face" if keep_face_centered else clip.crop_mode
    keyframed = _keyframed_crop_chain(clip)
    if keyframed:
        return f"{_with_auto_zoom(keyframed, clip)},setpts=PTS-STARTPTS"
    if crop_mode == "manual":
        x, y, w, h = _bounded_crop(clip)
        chain = (
            f"crop=iw*{w:.5f}:ih*{h:.5f}:iw*{x:.5f}:ih*{y:.5f},"
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setsar=1"
        )
        return f"{_with_auto_zoom(chain, clip)},setpts=PTS-STARTPTS"
    chain = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},setsar=1"
    )
    return f"{_with_auto_zoom(chain, clip)},setpts=PTS-STARTPTS"


def _half_chain() -> str:
    half = TARGET_H // 2
    return (
        f"scale={TARGET_W}:{half}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{half},setsar=1,setpts=PTS-STARTPTS"
    )


def _cover_chain(clip: TimelineClip) -> str:
    chain = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},setsar=1"
    )
    return f"{_with_auto_zoom(chain, clip)},setpts=PTS-STARTPTS"


def _base_filter_complex(clip: TimelineClip, keep_face_centered: bool, broll_path: str | None) -> str:
    broll_mode = clip.broll_mode if broll_path else "none"
    if broll_mode == "cover":
        return f"[1:v]{_cover_chain(clip)}[basev]"
    if broll_mode == "pip":
        pip_chain = "scale=360:640:force_original_aspect_ratio=increase,crop=360:640,setsar=1,setpts=PTS-STARTPTS"
        return (
            f"[0:v]{_normal_chain(clip, keep_face_centered)}[mainv];"
            f"[1:v]{pip_chain}[pipv];"
            f"[mainv][pipv]overlay=x=W-w-42:y=H-h-128:shortest=1,setsar=1[basev]"
        )
    if broll_mode == "split":
        chain = _with_auto_zoom("vstack=inputs=2,setsar=1", clip)
        return (
            f"[0:v]{_half_chain()}[mainv];"
            f"[1:v]{_half_chain()}[brollv];"
            f"[mainv][brollv]{chain}[basev]"
        )
    if clip.layout == "split" or clip.crop_mode == "split":
        half = TARGET_H // 2
        top = f"scale={TARGET_W}:{half}:force_original_aspect_ratio=increase,crop={TARGET_W}:{half}"
        bottom = (
            f"scale={TARGET_W}:{half}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{half},boxblur=14:4"
        )
        chain = _with_auto_zoom("vstack=inputs=2,setsar=1", clip)
        return (
            f"[0:v]split=2[a][b];"
            f"[a]{top}[top];"
            f"[b]{bottom}[bottom];"
            f"[top][bottom]{chain}[basev]"
        )
    return f"[0:v]{_normal_chain(clip, keep_face_centered)}[basev]"


def _filter_complex(
    clip: TimelineClip,
    keep_face_centered: bool,
    broll_path: str | None,
    ass_path: str | None,
    duration: float,
    jump_cut_cleanup: bool,
) -> str:
    base = _base_filter_complex(clip, keep_face_centered, broll_path)
    tail = _with_jump_cut_fade("format=yuv420p", duration, jump_cut_cleanup)
    if ass_path:
        return f"{base};[basev]{tail},ass='{_escape_filter_path(ass_path)}'[v]"
    return f"{base};[basev]{tail}[v]"


def _audio_args(clip: TimelineClip, duration: float, source_has_audio: bool, jump_cut_cleanup: bool) -> list[str]:
    if not source_has_audio:
        return ["-an"]
    filters: list[str] = []
    if clip.muted:
        filters.append("volume=0")
    if jump_cut_cleanup:
        fade = min(0.08, max(0.02, duration / 8.0))
        out_start = max(0.0, duration - fade)
        filters.extend([
            f"afade=t=in:st=0:d={fade:.3f}",
            f"afade=t=out:st={out_start:.3f}:d={fade:.3f}",
        ])
    args = ["-map", "0:a?"]
    if filters:
        args.extend(["-af", ",".join(filters)])
    args.extend(["-c:a", "aac", "-b:a", "128k"])
    return args


async def _render_segment(
    ffmpeg: str,
    source: str,
    clip: TimelineClip,
    out_path: str,
    keep_face_centered: bool,
    source_has_audio: bool,
    *,
    project: TimelineProject,
    subtitle_track: dict | None,
    work_dir: str,
    index: int,
) -> None:
    start = max(0.0, clip.source_start)
    duration = max(0.1, clip.source_end - clip.source_start)
    broll_path = _resolve_broll_source(clip.broll_source) if clip.broll_mode != "none" else None
    ass_path = _write_segment_ass(project, clip, subtitle_track, work_dir, index, duration)
    inputs = [
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-i", source,
    ]
    if broll_path:
        inputs.extend([
            "-stream_loop", "-1",
            "-ss", f"{clip.broll_start:.3f}",
            "-i", broll_path,
        ])
    cmd = [
        ffmpeg, "-y",
        *inputs,
        "-filter_complex", _filter_complex(
            clip,
            keep_face_centered,
            broll_path,
            ass_path,
            duration,
            project.jump_cut_cleanup,
        ),
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        *_audio_args(clip, duration, source_has_audio, project.jump_cut_cleanup),
        "-t", f"{duration:.3f}",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_path,
    ]
    rc, _stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=600)
    if rc != 0 or not os.path.exists(out_path):
        raise RuntimeError(stderr[-500:] if stderr else "Timeline segment render failed")


def _write_concat_list(paths: list[str], list_path: str) -> None:
    with open(list_path, "w", encoding="utf-8") as f:
        for path in paths:
            safe = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe}'\n")


async def apply_silence_cuts(
    project: TimelineProject,
    *,
    noise_db: float,
    min_silence: float,
    padding: float,
    min_clip: float,
) -> dict:
    video_id = _safe_video_id(project.video_id)
    source = source_video_path(video_id)
    if not source:
        raise FileNotFoundError("Processed video not found")
    probe = await probe_video(source)
    duration = max(0.1, float(probe.get("duration", 30.0)))
    silences = await _detect_silences(source, noise_db, min_silence)
    cursor = 0.0
    segments: list[tuple[float, float]] = []

    for start, end in sorted(silences):
        if end - start < min_silence:
            continue
        keep_end = max(cursor, start - padding)
        if keep_end - cursor >= min_clip:
            segments.append((round(cursor, 3), round(keep_end, 3)))
        cursor = min(duration, max(cursor, end + padding))

    if duration - cursor >= min_clip:
        segments.append((round(cursor, 3), round(duration, 3)))

    if not segments:
        segments = [(0.0, round(min(duration, max(project.clips[0].source_end if project.clips else duration, 0.5)), 3))]

    base = project.clips[0] if project.clips else TimelineClip(
        id=uuid.uuid4().hex[:10],
        title="Clip",
        source_start=0.0,
        source_end=min(duration, 30.0),
    )
    clips: list[dict] = []
    for idx, (start, end) in enumerate(segments, start=1):
        clip = base.model_dump()
        clip.update({
            "id": uuid.uuid4().hex[:10],
            "title": f"Speech cut {idx}",
            "source_start": start,
            "source_end": max(start + 0.1, end),
        })
        clips.append(clip)

    next_project = TimelineProject(**{
        **project.model_dump(),
        "clips": clips,
        "jump_cut_cleanup": True,
    })
    return save_project(next_project)


async def apply_smart_crop(
    project: TimelineProject,
    *,
    clip_id: str | None,
    mode: str,
    sample_interval: float,
) -> dict:
    video_id = _safe_video_id(project.video_id)
    source = source_video_path(video_id)
    if not source:
        raise FileNotFoundError("Processed video not found")
    if not project.clips:
        raise ValueError("Timeline must contain at least one clip")

    selected = next((clip for clip in project.clips if clip.id == clip_id), None) if clip_id else project.clips[0]
    if selected is None:
        raise ValueError("Selected clip not found")

    mode = mode if mode in {"face", "object"} else "face"
    analysis = await asyncio.to_thread(
        smart_crop_tracker.analyze_clip,
        source,
        selected,
        mode,
        sample_interval,
    )
    keyframes = analysis.get("keyframes") or []
    if not keyframes:
        raise RuntimeError("Smart crop analysis did not produce keyframes")

    next_clips = []
    for clip in project.clips:
        data = clip.model_dump()
        if clip.id == selected.id:
            first = keyframes[0]
            data.update({
                "crop_mode": mode,
                "layout": "single",
                "x_pct": first["x_pct"],
                "y_pct": first["y_pct"],
                "w_pct": first["w_pct"],
                "h_pct": first["h_pct"],
                "keyframes": keyframes,
            })
        next_clips.append(data)

    next_project = TimelineProject(**{
        **project.model_dump(),
        "crop_mode": mode,
        "keep_face_centered": mode == "face",
        "clips": next_clips,
    })
    saved = save_project(next_project)
    return {
        "project": saved,
        "clip_id": selected.id,
        "mode": mode,
        "keyframes": len(keyframes),
        "detections": int(analysis.get("detections", 0)),
        "frames_analyzed": int(analysis.get("frames_analyzed", 0)),
        "confidence": float(analysis.get("confidence", 0.0)),
        "tracker": analysis.get("tracker", "opencv"),
        "message": analysis.get("message", ""),
    }


def _text_excerpt(track: dict, limit: int = 1800) -> str:
    text = re.sub(r"\s+", " ", track.get("transcript") or "").strip()
    if not text:
        text = " ".join(str(w.get("text", "")) for w in track.get("words", [])).strip()
    return text[:limit]


def _sentence_candidates(text: str) -> list[str]:
    sentences = [s.strip(" -") for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    scored: list[tuple[int, str]] = []
    terms = {
        "secret", "why", "how", "mistake", "best", "worst", "money", "free",
        "fast", "simple", "proof", "results", "before", "after", "never",
    }
    for sentence in sentences:
        tokens = re.findall(r"[A-Za-z0-9']+", sentence.lower())
        score = len([tok for tok in tokens if tok in terms]) * 5
        score += 8 if "?" in sentence else 0
        score += 5 if re.search(r"\b\d+(\.\d+)?\b", sentence) else 0
        score += min(12, len(tokens))
        scored.append((score, sentence))
    return [item for _score, item in sorted(scored, reverse=True)[:6]]


def _clean_hook_text(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip().strip('"')
    return clean[: limit - 1].rstrip() + "..." if len(clean) > limit else clean


def _fallback_hooks(project: TimelineProject, transcript: str) -> list[dict]:
    candidates = _sentence_candidates(transcript)
    base_title = candidates[0] if candidates else project.hook_title or "Watch this before you post"
    templates = [
        ("The part everyone misses", base_title, "curiosity", 72),
        ("This changes the edit", candidates[1] if len(candidates) > 1 else base_title, "pattern interrupt", 68),
        ("Steal this workflow", candidates[2] if len(candidates) > 2 else base_title, "how-to", 64),
        ("The fastest way to improve this", candidates[3] if len(candidates) > 3 else base_title, "value", 61),
        ("Before you upload", candidates[4] if len(candidates) > 4 else base_title, "warning", 58),
    ]
    return [
        {
            "title": _clean_hook_text(title, 62),
            "subtitle": _clean_hook_text(subtitle, 92),
            "angle": angle,
            "confidence": confidence,
        }
        for title, subtitle, angle, confidence in templates
    ]


async def generate_hook_suggestions(project: TimelineProject) -> dict:
    video_id = _safe_video_id(project.video_id)
    track = subtitle_editor.get_or_create_track(video_id)
    transcript = _text_excerpt(track)
    prompt = f"""
Return JSON only.
Create 5 short-form hook/title overlays for this edited video.
Each object must contain title, subtitle, angle, confidence.
Keep title under 8 words and subtitle under 16 words.
Use direct, non-clickbait language.
Transcript:
{transcript}
Current clips:
{json.dumps([{"start": c.source_start, "end": c.source_end, "title": c.title} for c in project.clips], ensure_ascii=True)}
"""
    provider = "groq"
    parsed = await groq_ai.generate_json(prompt, timeout=35)
    if not isinstance(parsed, list):
        provider = "gemini"
        parsed = await google_ai.generate_json(prompt, timeout=35)

    suggestions: list[dict] = []
    if isinstance(parsed, list):
        for raw in parsed:
            if not isinstance(raw, dict):
                continue
            title = _clean_hook_text(str(raw.get("title") or ""), 62)
            if not title:
                continue
            try:
                confidence = float(raw.get("confidence", 70))
            except Exception:
                confidence = 70.0
            suggestions.append({
                "title": title,
                "subtitle": _clean_hook_text(str(raw.get("subtitle") or ""), 92),
                "angle": _clean_hook_text(str(raw.get("angle") or "hook"), 40),
                "confidence": max(0.0, min(100.0, confidence)),
            })
    if suggestions:
        return {"suggestions": suggestions[:5], "provider": provider}
    return {"suggestions": _fallback_hooks(project, transcript), "provider": "local"}


async def render_project(project: TimelineProject, progress_callback=None) -> dict:
    saved = save_project(project)
    video_id = _safe_video_id(project.video_id)
    source = source_video_path(video_id)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    if not source:
        raise FileNotFoundError("Processed video not found")
    if not project.clips:
        raise ValueError("Timeline must contain at least one clip")

    render_id = uuid.uuid4().hex[:8]
    file_id = storage_video_id(video_id)
    work_dir = os.path.join(TEMP_DIR, f"{file_id}_{render_id}")
    os.makedirs(work_dir, exist_ok=True)
    try:
        if progress_callback:
            progress_callback(0.05, "Preparing render")
        source_probe = await probe_video(source)
        source_has_audio = bool(source_probe.get("has_audio"))
        subtitle_track = subtitle_editor.get_or_create_track(video_id) if project.auto_captions else None
        segment_paths: list[str] = []
        total_segments = max(1, len(project.clips))
        for index, clip in enumerate(project.clips, start=1):
            if clip.source_end <= clip.source_start:
                raise ValueError(f"Clip {index} end must be after start")
            if progress_callback:
                progress_callback(0.08 + (index - 1) / total_segments * 0.76, f"Rendering clip {index}/{total_segments}")
            segment_path = os.path.join(work_dir, f"segment_{index:03d}.mp4")
            await _render_segment(
                ffmpeg,
                source,
                clip,
                segment_path,
                project.keep_face_centered,
                source_has_audio,
                project=project,
                subtitle_track=subtitle_track,
                work_dir=work_dir,
                index=index,
            )
            segment_paths.append(segment_path)
            if progress_callback:
                progress_callback(0.08 + index / total_segments * 0.76, f"Rendered clip {index}/{total_segments}")

        list_path = os.path.join(work_dir, "concat.txt")
        _write_concat_list(segment_paths, list_path)
        output_path = os.path.join(OUTPUT_DIR, f"{file_id}_timeline.mp4")
        if progress_callback:
            progress_callback(0.9, "Combining rendered clips")
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        rc, _stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=600)
        if rc != 0 or not os.path.exists(output_path):
            raise RuntimeError(stderr[-500:] if stderr else "Timeline concat failed")
        ok, reason = await validate_output(output_path)
        if not ok:
            raise RuntimeError(f"Timeline output invalid: {reason}")
        if progress_callback:
            progress_callback(0.98, "Validating output")
        state_store.upsert_video(video_id, status="completed", output_path=output_path)
        state_store.upsert_video(
            f"{video_id}_timeline",
            title=f"{video_id} timeline",
            status="completed",
            output_path=output_path,
            metadata={"source_video_id": video_id},
        )
        return {
            "video_id": video_id,
            "output_path": output_path,
            "filename": Path(output_path).name,
            "project": saved,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
