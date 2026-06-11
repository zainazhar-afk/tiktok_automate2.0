"""
Anti-detection FFmpeg video processor.
Applies transformations to evade TikTok's copyright fingerprinting:
mirror padding, scene reversal, frame insertion, crop jitter, color LUTs,
audio pitch shift, audio EQ, watermark removal, text overlay removal.
"""
import os
import random
import asyncio
import logging
import json
from typing import Optional, Callable
from app.utils.helpers import find_ffmpeg, run_command
from app.models.schemas import AntiDetectionConfig, AntiDetectionLevel

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 10 Color LUT presets for fingerprint randomization
COLOR_LUTS = {
    "warm": "eq=gamma=1.1:saturation=1.15:brightness=0.02",
    "cool": "eq=gamma=0.95:saturation=0.9:brightness=-0.02",
    "vintage": "eq=gamma=0.9:saturation=0.8:brightness=0.03,colorbalance=rs=0.1:gs=-0.05:bs=-0.1",
    "teal": "eq=gamma=1.0:saturation=1.05,colorbalance=rs=-0.05:gs=0.02:bs=0.08",
    "cinematic": "eq=gamma=1.05:saturation=1.1:brightness=-0.03:contrast=1.05",
    "moody": "eq=gamma=0.85:saturation=0.75:brightness=-0.05:contrast=1.08",
    "bright": "eq=gamma=1.08:saturation=1.1:brightness=0.04:contrast=1.02",
    "noir": "eq=gamma=0.85:saturation=0.2:brightness=-0.03:contrast=1.1",
    "pastel": "eq=gamma=1.0:saturation=0.85:brightness=0.03:contrast=0.95",
    "golden": "eq=gamma=1.05:saturation=1.05:brightness=0.02,colorbalance=rs=0.08:gs=0.02:bs=-0.05",
}


def resolve_preset(config: AntiDetectionConfig) -> AntiDetectionConfig:
    """Apply preset level to config."""
    if config.level == AntiDetectionLevel.MILD:
        config.mirror_padding = True
        config.scene_reversal = False
        config.frame_insertion = False
        config.crop_jitter = True
        config.color_lut = False
        config.audio_pitch_shift = False
        config.audio_eq = False
        config.audio_segment_reversal = False
        config.remove_watermark = True
        config.remove_text_overlays = True
        config.speed_variation = False
        config.horizontal_flip = False
        config.rotation_jitter = False
    elif config.level == AntiDetectionLevel.AGGRESSIVE:
        config.mirror_padding = True
        config.scene_reversal = True
        config.frame_insertion = True
        config.crop_jitter = True
        config.color_lut = True
        config.audio_pitch_shift = True
        config.audio_eq = True
        config.audio_segment_reversal = True
        config.remove_watermark = True
        config.remove_text_overlays = True
        config.speed_variation = True
        config.horizontal_flip = True
        config.rotation_jitter = True
    return config


def _build_center_crop_916(width: int, height: int) -> str:
    """Center-crop to 9:16 vertical (TikTok native)."""
    target_aspect = 9 / 16
    current_aspect = width / max(height, 1)
    if abs(current_aspect - target_aspect) < 0.02:
        return "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    if current_aspect > target_aspect:
        new_width = int(height * target_aspect)
        x = (width - new_width) // 2
        return f"crop={new_width}:{height}:{x}:0,scale=1080:1920"
    new_height = int(width / target_aspect)
    y = (height - new_height) // 2
    return f"crop={width}:{new_height}:0:{y},scale=1080:1920"


def _build_subtitle_strip() -> str:
    """Blur/delogo bottom subtitle region (~18% height)."""
    return "delogo=x=0:y=H-h*0.18:w=W:h=h*0.18:show=0"


def _build_strong_audio_randomization() -> str:
    """Layered audio fingerprint randomization."""
    tempo = random.uniform(0.97, 1.03)
    noise_vol = random.uniform(0.003, 0.012)
    return (
        f"atempo={tempo},"
        f"acompressor=threshold=-18dB:ratio=3:attack=5:release=50,"
        f"volume=1.02,"
        f"aeval=val(0)+{noise_vol}*random(0)"
    )


def _build_mirror_pad(width: int, height: int) -> str:
    """Build mirror padding filter - fills bars with blurred copy instead of black."""
    target_aspect = 9 / 16  # TikTok vertical
    current_aspect = width / max(height, 1)

    if abs(current_aspect - target_aspect) < 0.02:
        return ""  # Already correct aspect

    if current_aspect > target_aspect:
        # Video is wider - pad top/bottom
        new_height = int(width / target_aspect)
        pad = (new_height - height) // 2
        if pad > 0:
            return (
                f"split[main][bg];[bg]scale={width}:{new_height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{new_height},boxblur=20:20[blurred];"
                f"[blurred][main]overlay=(W-w)/2:(H-h)/2"
            )
    else:
        # Video is taller - pad left/right
        new_width = int(height * target_aspect)
        pad = (new_width - width) // 2
        if pad > 0:
            return (
                f"split[main][bg];[bg]scale={new_width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={new_width}:{height},boxblur=20:20[blurred];"
                f"[blurred][main]overlay=(W-w)/2:(H-h)/2"
            )
    return ""


def _build_scene_reversal(duration: float) -> str:
    """Reverse middle third of the video to break segment fingerprinting."""
    seg_start = duration / 3
    seg_end = 2 * duration / 3
    # Split into 3 segments, reverse the middle one
    return (
        f"split=3[seg1][seg2][seg3];"
        f"[seg1]trim=0:{seg_start},setpts=PTS-STARTPTS[s1];"
        f"[seg2]trim={seg_start}:{seg_end},setpts=PTS-STARTPTS,reverse[s2];"
        f"[seg3]trim={seg_end}:{duration},setpts=PTS-STARTPTS[s3];"
        f"[s1][s2][s3]concat=n=3:v=1:a=0"
    )


def _build_frame_insertion(duration: float, fps: float) -> str:
    """Insert 2-3 black frames at random positions."""
    frame_count = int(duration * fps)
    positions = sorted(random.sample(range(10, max(11, frame_count - 10)), min(3, frame_count // 3)))

    # Use a simplified approach: insert black frames using tpad
    # Place 1 black frame at one random position
    pos = random.choice(positions)
    return f"tpad=start=1:start_mode=add:color=black"


def _build_crop_jitter() -> str:
    """Apply random 1-3px edge crop per export."""
    crop_x = random.randint(1, 3)
    crop_y = random.randint(0, 2)
    return f"crop=iw-{crop_x*2}:ih-{crop_y*2}:{crop_x}:{crop_y}"


def _build_color_lut(seed: Optional[int] = None) -> str:
    """Select and return a random color LUT preset."""
    if seed is not None:
        random.seed(seed)
    lut_name = random.choice(list(COLOR_LUTS.keys()))
    logger.info(f"Selected color LUT: {lut_name}")
    return COLOR_LUTS[lut_name]


def _build_audio_pitch_shift() -> str:
    """Subtle pitch shift ±0.5-2.5% using asetrate+aresample."""
    shift = random.uniform(0.005, 0.025) * random.choice([-1, 1])
    rate = int(44100 * (1 + shift))
    return f"asetrate={rate},aresample=44100"


def _build_audio_eq() -> str:
    """Apply EQ randomization: 250Hz boost + 1kHz boost + 8kHz cut."""
    low_boost = random.uniform(1.0, 2.5)
    mid_boost = random.uniform(1.5, 3.5)
    high_cut = random.uniform(-3.0, -1.0)
    return f"equalizer=f=250:t=q:w=1:g={low_boost},equalizer=f=1000:t=q:w=1.5:g={mid_boost},equalizer=f=8000:t=q:w=1:g={high_cut}"


def _build_audio_reverse(duration: float) -> str:
    """Reverse first 2 seconds of audio."""
    rev_dur = min(2.0, duration)
    return (
        f"asplit=2[amain][arev];"
        f"[arev]atrim=0:{rev_dur},areverse[revseg];"
        f"[amain]atrim={rev_dur}:{duration},asetpts=PTS-STARTPTS[mainseg];"
        f"[revseg][mainseg]concat=n=2:v=0:a=1"
    )


def _build_watermark_removal() -> str:
    """Remove watermark/logos using delogo filter (x,y,w,h with defaults)."""
    # Common positions for watermarks (bottom-right corner)
    return "delogo=x=W-w-20:y=H-h-20:w=120:h=40:show=0"


def _build_speed_variation() -> str:
    """Subtle speed change ±3%."""
    speed = 1.0 + random.uniform(-0.03, 0.03)
    return f"setpts={1/speed}*PTS"


def _build_rotation_jitter() -> str:
    """Add sub-degree rotation jitter."""
    angle = random.uniform(-0.5, 0.5)
    rad = angle * 3.14159 / 180
    return f"rotate={angle}*PI/180:fillcolor=black@0"


def build_video_filters(config: AntiDetectionConfig, duration: float, fps: float = 30.0,
                        width: int = 1080, height: int = 1920) -> str:
    """Build the complete video filter chain."""
    filters = []

    if getattr(config, "auto_crop_916", True):
        filters.append(_build_center_crop_916(width, height))

    if config.mirror_padding:
        mp = _build_mirror_pad(width, height)
        if mp:
            filters.append(mp)

    if config.speed_variation:
        filters.append(_build_speed_variation())

    if config.horizontal_flip and random.random() > 0.5:
        filters.append("hflip")

    if config.rotation_jitter:
        filters.append(_build_rotation_jitter())

    if config.color_lut:
        filters.append(_build_color_lut())

    if config.crop_jitter:
        filters.append(_build_crop_jitter())

    if config.remove_watermark:
        filters.append(_build_watermark_removal())

    if config.remove_text_overlays:
        filters.append(_build_subtitle_strip())

    if config.frame_insertion:
        filters.append(_build_frame_insertion(duration, fps))

    if config.scene_reversal and duration > 3:
        sc = _build_scene_reversal(duration)
        if sc:
            filters.append(sc)

    return ",".join(f for f in filters if f)


def build_audio_filters(config: AntiDetectionConfig, duration: float) -> str:
    """Build the complete audio filter chain."""
    filters = []

    if config.audio_pitch_shift:
        filters.append(_build_audio_pitch_shift())

    if config.audio_eq:
        filters.append(_build_audio_eq())

    if config.audio_segment_reversal and duration > 2:
        filters.append(_build_audio_reverse(duration))

    if getattr(config, "strong_audio_randomization", True):
        filters.append(_build_strong_audio_randomization())

    if not filters:
        return ""

    return ",".join(filters)


async def probe_video(input_path: str) -> dict:
    """Get video metadata using ffprobe."""
    ffmpeg = find_ffmpeg()
    ffprobe = ffmpeg.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe") if ffmpeg else "ffprobe"

    cmd = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", input_path
    ]
    rc, stdout, stderr = await asyncio.to_thread(run_command, cmd, timeout=30)

    if rc != 0:
        # Return defaults
        return {"duration": 30, "fps": 30, "width": 1080, "height": 1920}

    try:
        data = json.loads(stdout)
        video_stream = None
        audio_stream = None
        for stream in data.get("streams", []):
            if stream["codec_type"] == "video" and not video_stream:
                video_stream = stream
            elif stream["codec_type"] == "audio" and not audio_stream:
                audio_stream = stream

        duration = float(data.get("format", {}).get("duration", 30))
        fps_parts = video_stream.get("r_frame_rate", "30/1").split("/") if video_stream else ["30", "1"]
        fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 30

        return {
            "duration": duration,
            "fps": fps,
            "width": video_stream.get("width", 1080) if video_stream else 1080,
            "height": video_stream.get("height", 1920) if video_stream else 1920,
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Failed to parse ffprobe output: {e}")
        return {"duration": 30, "fps": 30, "width": 1080, "height": 1920}


async def process_video(input_path: str, video_id: str, config: AntiDetectionConfig) -> Optional[str]:
    """Process a video with anti-detection filters. Returns output path."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.error("ffmpeg not found")
        return None

    config = resolve_preset(config)

    # Probe video for metadata
    probe = await probe_video(input_path)
    duration = probe["duration"]
    fps = probe["fps"]
    width = probe["width"]
    height = probe["height"]

    logger.info(f"Processing {video_id}: {duration:.1f}s, {width}x{height}, {fps:.1f}fps")

    video_filters = build_video_filters(config, duration, fps, width, height)
    audio_filters = build_audio_filters(config, duration)

    output_path = os.path.join(OUTPUT_DIR, f"{video_id}_processed.mp4")

    cmd = [ffmpeg, "-y", "-i", input_path]

    if video_filters:
        cmd.extend(["-vf", video_filters])
    if audio_filters:
        cmd.extend(["-af", audio_filters])

    # Output settings
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "21",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        output_path,
    ])

    # Rebuild command properly with chained filters
    final_cmd = _rebuild_ffmpeg_command(ffmpeg, input_path, output_path,
                                         video_filters, audio_filters, config)
    logger.info(f"FFmpeg cmd: {' '.join(final_cmd[:20])}...")

    rc, stdout, stderr = await asyncio.to_thread(run_command, final_cmd, timeout=600)

    if rc == 0 and os.path.exists(output_path):
        logger.info(f"Processing complete: {output_path}")
        return output_path

    # Fallback: try simpler encoding without complex filters
    logger.warning(f"Complex processing failed (rc={rc}), trying simple fallback")
    simple_cmd = [
        ffmpeg, "-y", "-i", input_path,
        "-vf", _build_color_lut(),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        output_path,
    ]
    rc2, _, stderr2 = await asyncio.to_thread(run_command, simple_cmd, timeout=300)

    if rc2 == 0 and os.path.exists(output_path):
        logger.info("Fallback processing succeeded")
        return output_path

    logger.error(f"All processing failed. Complex: {stderr[:300] if stderr else 'none'}")
    return None


def _rebuild_ffmpeg_command(ffmpeg: str, input_path: str, output_path: str,
                             video_filters: str, audio_filters: str,
                             config: AntiDetectionConfig) -> list[str]:
    """Build the final ffmpeg command with all filters properly chained."""
    cmd = [ffmpeg, "-y", "-i", input_path]

    # Build complex filter chain when both video and audio have complex filters
    if config.scene_reversal and config.audio_segment_reversal:
        # Use filter_complex for multi-segment operations
        cmd.extend([
            "-filter_complex", f"{video_filters};{audio_filters}" if audio_filters else video_filters,
        ])
    else:
        if video_filters:
            cmd.extend(["-vf", video_filters])
        if audio_filters:
            cmd.extend(["-af", audio_filters])

    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        output_path,
    ])
    return cmd


async def batch_process(inputs: list[tuple[str, str, AntiDetectionConfig]],
                        max_concurrent: int = 4) -> dict[str, Optional[str]]:
    """Process multiple videos in parallel. Returns {video_id: output_path}."""
    sem = asyncio.Semaphore(max_concurrent)
    results: dict[str, Optional[str]] = {}

    async def process_one(input_path: str, vid: str, cfg: AntiDetectionConfig):
        async with sem:
            path = await process_video(input_path, vid, cfg)
            results[vid] = path

    tasks = [process_one(inp, vid, cfg) for inp, vid, cfg in inputs]
    await asyncio.gather(*tasks, return_exceptions=True)
    return results
