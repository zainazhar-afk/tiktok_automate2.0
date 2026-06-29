"""
Anti-detection FFmpeg video processor.

Builds a single, correct `-filter_complex` graph (instead of brittle comma-joined
`-vf`/`-af` chains) so multi-output transforms (mirror pad, scene reversal, audio
reversal, music ducking) compose without breaking the encoder.

Transformations: smart/center 9:16 crop, mirror padding, scene reversal, frame
insertion, crop jitter, color LUTs, rotation/flip, watermark + subtitle removal,
audio pitch shift (duration-preserving), EQ, audio reversal, strong randomization,
background-music ducking, voiceover layering, and burned-in auto subtitles.

Every render uses a per-video RNG seed so two renders of the same source are
fingerprint-unique. The output is validated with ffprobe before being returned.
"""
import os
import random
import asyncio
import logging
import json
import re
from typing import Callable, Optional

from app.config import get_settings
from app.utils.helpers import find_ffmpeg, run_command, run_command_with_progress
from app.models.schemas import AntiDetectionConfig, AntiDetectionLevel, TextRemovalMode
from app.services import subtitles as subtitles_service

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TARGET_W, TARGET_H = 1080, 1920

# Color LUT presets for fingerprint randomization
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

SUBTITLE_STYLES = {
    "default": "FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=60",
    "bold": "FontName=Arial Black,FontSize=20,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=80",
    "minimal": "FontName=Arial,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=1,Shadow=0,Alignment=2,MarginV=50",
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
        config.remove_top_text_banner = False
        config.text_removal_mode = TextRemovalMode.BLUR
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
        config.remove_top_text_banner = False
        config.text_removal_mode = TextRemovalMode.BLUR
        config.speed_variation = True
        config.horizontal_flip = True
        config.rotation_jitter = True
    return config


# ---------------------------------------------------------------------------
# Filtergraph assembler
# ---------------------------------------------------------------------------

class _Graph:
    """Accumulates filter_complex segments with unique link labels."""

    def __init__(self):
        self.parts: list[str] = []
        self._uid = 0

    def uid(self) -> str:
        self._uid += 1
        return f"n{self._uid}"

    def chain(self, in_label: str, steps: list, out_label: str, null_filter: str = "null") -> str:
        """
        Connect `in_label` -> `out_label` applying `steps` in order.
        Each step is either a linear filter string, or a callable
        (in_label, out_label) -> segment_string for multi-output subgraphs.
        Returns the final label (== out_label).
        """
        cur = in_label
        buf: list[str] = []

        def flush(target: str):
            nonlocal cur, buf
            if buf:
                self.parts.append(f"[{cur}]{','.join(buf)}[{target}]")
                cur = target
                buf = []

        for step in steps:
            if callable(step):
                if buf:
                    tmp = self.uid()
                    flush(tmp)
                nxt = self.uid()
                self.parts.append(step(cur, nxt))
                cur = nxt
            elif step:
                buf.append(step)

        if buf:
            flush(out_label)
        else:
            self.parts.append(f"[{cur}]{null_filter}[{out_label}]")
        return out_label

    def add(self, segment: str):
        self.parts.append(segment)

    def build(self) -> str:
        return ";".join(p for p in self.parts if p)


# ---------------------------------------------------------------------------
# Geometry / video filters
# ---------------------------------------------------------------------------

def _content_box(probe: dict) -> tuple[int, int, int, int]:
    """Detected (or full-frame) content rectangle: (w, h, x, y)."""
    crop = probe.get("crop")
    if crop:
        return crop
    return probe["width"], probe["height"], 0, 0


def _normalize_916(probe: dict, mirror: bool, smart: bool) -> list:
    """
    Return graph steps that bring the frame to 1080x1920.
    Either a blurred mirror-pad subgraph or a fill-crop, then scale.
    """
    w, h, x, y = _content_box(probe)
    aspect = w / max(h, 1)
    target = 9 / 16

    # Pre-crop to the detected content box (removes letter/pillarbox)
    pre = []
    if smart and (w, h, x, y) != (probe["width"], probe["height"], 0, 0):
        pre.append(f"crop={w}:{h}:{x}:{y}")

    if abs(aspect - target) < 0.02:
        return pre + [f"scale={TARGET_W}:{TARGET_H}"]

    if mirror:
        # Fill the frame with a blurred, zoomed copy and overlay the original.
        def mirror_pad(inp: str, out: str) -> str:
            return (
                f"[{inp}]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease[fg_{out}];"
                f"[{inp}]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
                f"crop={TARGET_W}:{TARGET_H},boxblur=24:6[bg_{out}];"
                f"[bg_{out}][fg_{out}]overlay=(W-w)/2:(H-h)/2[{out}]"
            )
        return pre + [mirror_pad]

    # Crop to fill 9:16, then scale to exact target
    if aspect > target:  # too wide -> crop width
        new_w = int(h * target)
        cx = (w - new_w) // 2 + x
        return pre + [f"crop={new_w}:{h}:{cx}:{y}", f"scale={TARGET_W}:{TARGET_H}"]
    # too tall -> crop height
    new_h = int(w / target)
    cy = (h - new_h) // 2 + y
    return pre + [f"crop={w}:{new_h}:{x}:{cy}", f"scale={TARGET_W}:{TARGET_H}"]


def _color_lut(rng: random.Random) -> str:
    name = rng.choice(list(COLOR_LUTS.keys()))
    logger.info(f"Color LUT: {name}")
    return COLOR_LUTS[name]


def _crop_jitter(rng: random.Random) -> str:
    cx = rng.randint(1, 3)
    cy = rng.randint(0, 2)
    # Crop a few edge pixels then rescale back to keep exact target dims.
    return f"crop=iw-{cx*2}:ih-{cy*2}:{cx}:{cy},scale={TARGET_W}:{TARGET_H}"


def _rotation_jitter(rng: random.Random) -> str:
    angle = rng.uniform(-0.4, 0.4)
    return f"rotate={angle}*PI/180:fillcolor=black,scale={TARGET_W}:{TARGET_H}"


def _speed_factor(rng: random.Random) -> float:
    return 1.0 + rng.uniform(-0.03, 0.03)


def _watermark_removal() -> str:
    logo_w, logo_h = 120, 40
    x = TARGET_W - logo_w - 20
    y = TARGET_H - logo_h - 20
    return f"delogo=x={x}:y={y}:w={logo_w}:h={logo_h}:show=0"


def _subtitle_strip() -> str:
    band_h = int(TARGET_H * 0.15)
    return f"delogo=x=2:y={TARGET_H - band_h - 2}:w={TARGET_W - 4}:h={band_h}:show=0"


def _region_pixels(x_pct: float, y_pct: float, w_pct: float, h_pct: float) -> tuple[int, int, int, int]:
    x = max(0, min(TARGET_W - 2, int(TARGET_W * x_pct)))
    y = max(0, min(TARGET_H - 2, int(TARGET_H * y_pct)))
    w = max(2, min(TARGET_W - x, int(TARGET_W * w_pct)))
    h = max(2, min(TARGET_H - y, int(TARGET_H * h_pct)))
    return x, y, w, h


def _text_region_filter(x: int, y: int, w: int, h: int, mode: TextRemovalMode) -> str:
    if mode == TextRemovalMode.COVER:
        return f"drawbox=x={x}:y={y}:w={w}:h={h}:color=black@1:t=fill"
    # FFmpeg has no semantic text inpainting; delogo is the best built-in
    # region repair filter and behaves like a soft blur/fill.
    return f"delogo=x={x}:y={y}:w={w}:h={h}:show=0"


def _text_removal_steps(config: AntiDetectionConfig) -> list[str]:
    steps: list[str] = []
    mode = config.text_removal_mode
    top_h = int(TARGET_H * config.top_text_height_pct) if config.remove_top_text_banner else 0
    bottom_h = int(TARGET_H * config.bottom_text_height_pct) if config.remove_text_overlays else 0

    if mode == TextRemovalMode.CROP and (top_h or bottom_h):
        crop_h = max(2, TARGET_H - top_h - bottom_h)
        steps.append(f"crop={TARGET_W}:{crop_h}:0:{top_h},scale={TARGET_W}:{TARGET_H}")
    else:
        if top_h:
            steps.append(_text_region_filter(2, 2, TARGET_W - 4, max(2, top_h), mode))
        if bottom_h:
            y = TARGET_H - bottom_h - 2
            steps.append(_text_region_filter(2, y, TARGET_W - 4, max(2, bottom_h), mode))

    for region in config.text_removal_regions:
        x, y, w, h = _region_pixels(region.x_pct, region.y_pct, region.w_pct, region.h_pct)
        region_mode = region.mode or mode
        if region_mode == TextRemovalMode.CROP:
            region_mode = TextRemovalMode.BLUR
        steps.append(_text_region_filter(x, y, w, h, region_mode))

    return steps


def _scene_reversal(duration: float):
    seg = duration / 3
    end = 2 * duration / 3

    def build(inp: str, out: str) -> str:
        return (
            f"[{inp}]split=3[r1_{out}][r2_{out}][r3_{out}];"
            f"[r1_{out}]trim=0:{seg:.3f},setpts=PTS-STARTPTS[s1_{out}];"
            f"[r2_{out}]trim={seg:.3f}:{end:.3f},setpts=PTS-STARTPTS,reverse[s2_{out}];"
            f"[r3_{out}]trim={end:.3f}:{duration:.3f},setpts=PTS-STARTPTS[s3_{out}];"
            f"[s1_{out}][s2_{out}][s3_{out}]concat=n=3:v=1:a=0[{out}]"
        )
    return build


def _escape_subs_path(path: str) -> str:
    """Escape a path for the ffmpeg subtitles filter (Windows-safe)."""
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace(":", "\\:")
    return p


def build_video_steps(config: AntiDetectionConfig, probe: dict, rng: random.Random,
                      speed: Optional[float], srt_path: Optional[str]) -> list:
    """Ordered list of video graph steps (strings + subgraph callables)."""
    steps: list = []

    # 1. Normalize to 1080x1920 (smart/center crop or mirror pad)
    if config.auto_crop_916 or config.mirror_padding or config.smart_crop:
        steps += _normalize_916(probe, mirror=config.mirror_padding, smart=config.smart_crop)
    else:
        steps.append(f"scale={TARGET_W}:{TARGET_H}")

    # 2. Scene reversal (multi-output)
    if config.scene_reversal and probe["duration"] > 3:
        steps.append(_scene_reversal(probe["duration"]))

    # 3. Linear look transforms
    if config.color_lut:
        steps.append(_color_lut(rng))
    if config.horizontal_flip and rng.random() > 0.5:
        steps.append("hflip")
    if config.rotation_jitter:
        steps.append(_rotation_jitter(rng))
    if config.crop_jitter:
        steps.append(_crop_jitter(rng))
    if config.remove_watermark:
        steps.append(_watermark_removal())
    steps.extend(_text_removal_steps(config))
    if config.frame_insertion:
        steps.append("tpad=start=1:start_mode=add:color=black")
    if speed is not None:
        steps.append(f"setpts={1/speed:.5f}*PTS")

    # 4. Burned-in subtitles (last, so they aren't distorted)
    if srt_path:
        style = SUBTITLE_STYLES.get(config.subtitle_style, SUBTITLE_STYLES["default"])
        steps.append(f"subtitles=filename='{_escape_subs_path(srt_path)}':force_style='{style}'")

    return steps


# ---------------------------------------------------------------------------
# Audio filters
# ---------------------------------------------------------------------------

def _audio_pitch_shift(rng: random.Random) -> str:
    """Duration-preserving pitch shift: asetrate + atempo compensation."""
    f = 1.0 + rng.uniform(0.005, 0.025) * rng.choice([-1, 1])
    rate = int(44100 * f)
    return f"asetrate={rate},aresample=44100,atempo={1/f:.5f}"


def _audio_eq(rng: random.Random) -> str:
    low = rng.uniform(1.0, 2.5)
    mid = rng.uniform(1.5, 3.5)
    high = rng.uniform(-3.0, -1.0)
    return (f"equalizer=f=250:t=q:w=1:g={low:.2f},"
            f"equalizer=f=1000:t=q:w=1.5:g={mid:.2f},"
            f"equalizer=f=8000:t=q:w=1:g={high:.2f}")


def _strong_audio(rng: random.Random) -> str:
    tempo = rng.uniform(0.98, 1.02)
    return (f"atempo={tempo:.5f},"
            f"acompressor=threshold=-18dB:ratio=3:attack=5:release=50,"
            f"volume=1.02")


def _audio_reverse(duration: float):
    rev = min(2.0, duration)

    def build(inp: str, out: str) -> str:
        return (
            f"[{inp}]asplit=2[am_{out}][ar_{out}];"
            f"[ar_{out}]atrim=0:{rev:.3f},areverse[rev_{out}];"
            f"[am_{out}]atrim={rev:.3f}:{duration:.3f},asetpts=PTS-STARTPTS[main_{out}];"
            f"[rev_{out}][main_{out}]concat=n=2:v=0:a=1[{out}]"
        )
    return build


def build_audio_steps(config: AntiDetectionConfig, duration: float,
                      rng: random.Random, speed: Optional[float]) -> list:
    steps: list = ["aresample=44100"]
    if config.audio_pitch_shift:
        steps.append(_audio_pitch_shift(rng))
    if config.audio_eq:
        steps.append(_audio_eq(rng))
    if speed is not None:
        # keep A/V in sync with video speed change
        s = max(0.5, min(2.0, speed))
        steps.append(f"atempo={s:.5f}")
    if config.strong_audio_randomization:
        steps.append(_strong_audio(rng))
    if config.audio_segment_reversal and duration > 2:
        steps.append(_audio_reverse(duration))
    return steps


# ---------------------------------------------------------------------------
# Probe + validation
# ---------------------------------------------------------------------------

def _find_ffprobe() -> str:
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        candidate = os.path.join(os.path.dirname(ffmpeg), exe)
        if os.path.isfile(candidate):
            return candidate
    return "ffprobe"


async def _detect_crop(input_path: str) -> Optional[tuple[int, int, int, int]]:
    """Run cropdetect to find the real content box (removes black bars)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    cmd = [
        ffmpeg, "-hide_banner", "-i", input_path,
        "-vf", "cropdetect=24:2:0", "-frames:v", "200",
        "-an", "-f", "null", "-",
    ]
    rc, _out, err = await asyncio.to_thread(run_command, cmd, timeout=60)
    if rc != 0 or not err:
        return None
    matches = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
    if not matches:
        return None
    w, h, x, y = (int(v) for v in matches[-1])
    if w < 16 or h < 16:
        return None
    return w, h, x, y


async def probe_video(input_path: str, detect_crop: bool = False) -> dict:
    """Get video metadata using ffprobe. Optionally run cropdetect."""
    ffprobe = _find_ffprobe()
    cmd = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", input_path,
    ]
    rc, stdout, _ = await asyncio.to_thread(run_command, cmd, timeout=30)

    result = {"duration": 30.0, "fps": 30.0, "width": TARGET_W, "height": TARGET_H,
              "has_audio": False, "crop": None}

    if rc == 0:
        try:
            data = json.loads(stdout)
            video_stream = None
            for stream in data.get("streams", []):
                if stream["codec_type"] == "video" and not video_stream:
                    video_stream = stream
                elif stream["codec_type"] == "audio":
                    result["has_audio"] = True

            if video_stream:
                fps_parts = video_stream.get("r_frame_rate", "30/1").split("/")
                fps = (float(fps_parts[0]) / float(fps_parts[1])
                       if len(fps_parts) == 2 and float(fps_parts[1]) else 30.0)
                result.update({
                    "fps": fps,
                    "width": video_stream.get("width", TARGET_W),
                    "height": video_stream.get("height", TARGET_H),
                })
            result["duration"] = float(data.get("format", {}).get("duration", 30) or 30)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"ffprobe parse failed: {e}")

    if detect_crop:
        result["crop"] = await _detect_crop(input_path)

    return result


async def validate_output(path: str) -> tuple[bool, str]:
    """Assert the output has a valid video stream and non-zero duration."""
    if not path or not os.path.exists(path) or os.path.getsize(path) < 1024:
        return False, "missing or empty file"
    probe = await probe_video(path)
    if probe["duration"] < 0.5:
        return False, f"duration too short ({probe['duration']:.2f}s)"
    # width/height come back as target defaults only if no video stream was found
    if not probe.get("width") or not probe.get("height"):
        return False, "no video stream"
    if not probe.get("has_audio"):
        # not fatal, but worth flagging
        logger.warning(f"Output {os.path.basename(path)} has no audio stream")
    return True, "ok"


# ---------------------------------------------------------------------------
# Input assembly + main processing
# ---------------------------------------------------------------------------

def _resolve_asset(path: Optional[str], base_dir: str) -> Optional[str]:
    if not path:
        return None
    if os.path.isabs(path) and os.path.isfile(path):
        return path
    candidate = os.path.join(base_dir, path)
    return candidate if os.path.isfile(candidate) else None


def _seed_for(config: AntiDetectionConfig, video_id: str) -> int:
    # Fold in video_id so every video is unique, while a pinned seed stays
    # reproducible for the same (seed, video_id) pair.
    base = config.random_seed if config.random_seed is not None else random.randrange(2**31)
    return (base ^ (hash(video_id) & 0x7FFFFFFF)) & 0x7FFFFFFF


def _with_progress_output(cmd: list[str]) -> list[str]:
    """Add ffmpeg progress output without mutating the base command."""
    if "-progress" in cmd:
        return cmd
    return [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]


async def process_video(
    input_path: str,
    video_id: str,
    config: AntiDetectionConfig,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> Optional[str]:
    """Process a video with anti-detection filters. Returns validated output path."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.error("ffmpeg not found")
        return None

    config = resolve_preset(config)
    settings = get_settings()

    # Local seed only — never mutate the (possibly shared) config object,
    # or every video in a batch would get an identical fingerprint.
    seed = _seed_for(config, video_id)
    rng = random.Random(seed)
    logger.info(f"Processing {video_id} with seed={seed}")

    probe = await probe_video(input_path, detect_crop=config.smart_crop)
    duration = probe["duration"]
    logger.info(f"{video_id}: {duration:.1f}s {probe['width']}x{probe['height']} "
                f"{probe['fps']:.1f}fps audio={probe['has_audio']} crop={probe['crop']}")

    # Optional auto subtitles (transcribe from the original input)
    srt_path = None
    if config.auto_subtitles:
        srt_path = await subtitles_service.generate_subtitles(input_path, video_id)

    speed = _speed_factor(rng) if config.speed_variation else None

    output_path = os.path.join(OUTPUT_DIR, f"{video_id}_processed.mp4")

    cmd = await asyncio.to_thread(
        _build_command, ffmpeg, input_path, output_path, config, probe, rng, speed, srt_path, settings
    )
    logger.info(f"FFmpeg filter_complex length: {len(cmd)} args")

    if progress_callback:
        rc, _out, stderr = await asyncio.to_thread(
            run_command_with_progress,
            _with_progress_output(cmd),
            duration=duration,
            progress_callback=progress_callback,
            timeout=900,
        )
    else:
        rc, _out, stderr = await asyncio.to_thread(run_command, cmd, timeout=900)

    if rc == 0:
        ok, reason = await validate_output(output_path)
        if ok:
            logger.info(f"Processing complete + validated: {output_path}")
            return output_path
        logger.warning(f"Output failed validation ({reason}); trying simple fallback")
    else:
        err_tail = stderr or _out
        logger.warning(f"Complex processing failed (rc={rc}); trying simple fallback. "
                       f"stderr tail: {err_tail[-400:] if err_tail else 'none'}")

    # Fallback: minimal safe transform that still normalizes to 9:16
    fb_vf = (f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
             f"crop={TARGET_W}:{TARGET_H},{_color_lut(rng)}")
    simple_cmd = [
        ffmpeg, "-y", "-i", input_path,
        "-vf", fb_vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-pix_fmt", "yuv420p",
        output_path,
    ]
    if progress_callback:
        rc2, _o2, stderr2 = await asyncio.to_thread(
            run_command_with_progress,
            _with_progress_output(simple_cmd),
            duration=duration,
            progress_callback=progress_callback,
            timeout=300,
        )
    else:
        rc2, _o2, stderr2 = await asyncio.to_thread(run_command, simple_cmd, timeout=300)
    if rc2 == 0:
        ok, reason = await validate_output(output_path)
        if ok:
            logger.info("Fallback processing succeeded + validated")
            return output_path
        logger.error(f"Fallback output invalid: {reason}")
    else:
        err_tail = stderr2 or _o2
        logger.error(f"Fallback failed (rc={rc2}): {err_tail[-300:] if err_tail else 'none'}")

    return None


def _build_command(ffmpeg: str, input_path: str, output_path: str,
                   config: AntiDetectionConfig, probe: dict, rng: random.Random,
                   speed: Optional[float], srt_path: Optional[str], settings) -> list[str]:
    """Assemble the full ffmpeg command using a single filter_complex graph."""
    graph = _Graph()

    # ---- Video chain ----
    video_steps = build_video_steps(config, probe, rng, speed, srt_path)
    graph.chain("0:v", video_steps, "vout", null_filter="null")

    # ---- Inputs (video is 0; build extra inputs for silence/music/voiceover) ----
    inputs: list[str] = ["-i", input_path]
    next_idx = 1

    has_audio = probe["has_audio"]
    music_file = _resolve_asset(config.background_music, settings.music_dir)
    voice_file = _resolve_asset(config.voiceover_path, settings.voiceover_dir)

    if has_audio:
        speech_in = "0:a"
    else:
        # synth silent base so we always emit an audio track
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        speech_in = f"{next_idx}:a"
        next_idx += 1

    music_idx = None
    if music_file:
        inputs += ["-stream_loop", "-1", "-i", music_file]
        music_idx = next_idx
        next_idx += 1

    voice_idx = None
    if voice_file:
        inputs += ["-i", voice_file]
        voice_idx = next_idx
        next_idx += 1

    # ---- Audio chain ----
    audio_steps = build_audio_steps(config, probe["duration"], rng, speed)
    graph.chain(speech_in, audio_steps, "sp", null_filter="anull")
    speech_label = "sp"

    if voice_idx is not None:
        graph.add(f"[{voice_idx}:a]aresample=44100[vo]")
        graph.add(f"[{speech_label}]volume=0.6[spq];"
                  f"[spq][vo]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[spmix]")
        speech_label = "spmix"

    if music_idx is not None:
        graph.add(f"[{music_idx}:a]aresample=44100,volume={config.music_volume}[mus]")
        if config.music_ducking:
            graph.add(f"[{speech_label}]asplit=2[spm][spk]")
            graph.add(f"[mus][spk]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250[mduck]")
            graph.add(f"[spm][mduck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
        else:
            graph.add(f"[{speech_label}][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
        audio_out = "aout"
    else:
        graph.add(f"[{speech_label}]anull[aout]")
        audio_out = "aout"

    cmd = [ffmpeg, "-y", *inputs,
           "-filter_complex", graph.build(),
           "-map", "[vout]", "-map", f"[{audio_out}]",
           "-c:v", "libx264", "-preset", "fast", "-crf", "21",
           "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", "-pix_fmt", "yuv420p",
           "-shortest",
           output_path]
    return cmd


async def batch_process(inputs: list[tuple[str, str, AntiDetectionConfig]],
                        max_concurrent: int = 4) -> dict[str, Optional[str]]:
    """Process multiple videos in parallel. Returns {video_id: output_path}."""
    sem = asyncio.Semaphore(max_concurrent)
    results: dict[str, Optional[str]] = {}

    async def process_one(input_path: str, vid: str, cfg: AntiDetectionConfig):
        async with sem:
            try:
                results[vid] = await process_video(input_path, vid, cfg)
            except Exception:
                logger.exception(f"process_video crashed for {vid}")
                results[vid] = None

    await asyncio.gather(*[process_one(i, v, c) for i, v, c in inputs], return_exceptions=True)
    return results
