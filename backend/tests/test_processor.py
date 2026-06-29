import asyncio
import os
import random

import pytest

from app.models.schemas import AntiDetectionConfig, AntiDetectionLevel
from app.services import processor
from app.utils.helpers import find_ffmpeg, run_command


class DummySettings:
    music_dir = os.path.abspath("assets/music")
    voiceover_dir = os.path.abspath("assets/voiceover")


def test_build_command_adds_safe_video_and_audio_outputs(tmp_path):
    config = AntiDetectionConfig(
        level=AntiDetectionLevel.MILD,
        scene_reversal=False,
        frame_insertion=False,
        color_lut=False,
        crop_jitter=False,
        remove_watermark=False,
        remove_text_overlays=False,
        audio_pitch_shift=False,
        audio_eq=False,
        strong_audio_randomization=False,
    )
    probe = {
        "duration": 2.0,
        "fps": 30.0,
        "width": 1920,
        "height": 1080,
        "has_audio": False,
        "crop": None,
    }

    cmd = processor._build_command(
        "ffmpeg",
        "input.mp4",
        str(tmp_path / "out.mp4"),
        config,
        probe,
        random.Random(1),
        None,
        None,
        DummySettings(),
    )
    joined = " ".join(cmd)

    assert "-filter_complex" in cmd
    assert "anullsrc=channel_layout=stereo:sample_rate=44100" in joined
    assert "-map [vout] -map [aout]" in joined
    assert "scale=1080:1920" in joined
    assert "-pix_fmt yuv420p" in joined


def test_with_progress_output_enables_ffmpeg_progress():
    cmd = processor._with_progress_output(["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"])

    assert cmd[:4] == ["ffmpeg", "-progress", "pipe:1", "-nostats"]
    assert cmd.count("-progress") == 1
    assert processor._with_progress_output(cmd) == cmd


def test_text_banner_removal_can_crop_top_and_bottom():
    config = AntiDetectionConfig(
        remove_top_text_banner=True,
        remove_text_overlays=True,
        text_removal_mode="crop",
        top_text_height_pct=0.10,
        bottom_text_height_pct=0.12,
    )

    steps = processor._text_removal_steps(config)

    assert steps == ["crop=1080:1498:0:192,scale=1080:1920"]


def test_text_removal_custom_region_uses_delogo():
    config = AntiDetectionConfig(
        remove_text_overlays=False,
        text_removal_regions=[
            {"x_pct": 0.1, "y_pct": 0.2, "w_pct": 0.3, "h_pct": 0.1}
        ],
    )

    steps = processor._text_removal_steps(config)

    assert steps == ["delogo=x=108:y=384:w=324:h=192:show=0"]


def test_process_video_tiny_fixture(tmp_path, monkeypatch):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not installed")

    source = tmp_path / "source.mp4"
    output = tmp_path / "output"
    output.mkdir()
    rc, _stdout, stderr = run_command(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x568:rate=15:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        timeout=60,
    )
    assert rc == 0, stderr

    monkeypatch.setattr(processor, "OUTPUT_DIR", str(output))
    config = AntiDetectionConfig(
        level=AntiDetectionLevel.MILD,
        frame_insertion=False,
        color_lut=False,
        crop_jitter=False,
        remove_watermark=False,
        remove_text_overlays=False,
        audio_pitch_shift=False,
        audio_eq=False,
        strong_audio_randomization=False,
    )
    progress: list[float] = []

    result = asyncio.run(
        processor.process_video(
            str(source),
            "fixture",
            config,
            progress_callback=progress.append,
        )
    )

    assert result is not None
    assert os.path.exists(result)
    assert progress
    assert max(progress) >= 0.9
