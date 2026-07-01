import asyncio

import pytest

from app.services import downloader


class Settings:
    max_download_mb = 1024
    max_source_duration_seconds = 1800


def _stub_tools(monkeypatch, tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", str(downloads))
    monkeypatch.setattr(downloader, "validate_public_video_url", lambda url: url)
    monkeypatch.setattr(downloader, "find_ytdlp", lambda: "yt-dlp")
    monkeypatch.setattr(downloader, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(downloader, "find_aria2c", lambda: None)
    monkeypatch.setattr(downloader, "get_settings", lambda: Settings())


def test_download_progress_mode_surfaces_stdout_error(tmp_path, monkeypatch):
    _stub_tools(monkeypatch, tmp_path)

    def fake_run(_cmd, *, timeout, progress_callback):
        progress_callback(0.2, "[download] 20.0% of source")
        return 1, "ERROR: [download] video does not pass filter (duration <= 1800)", ""

    monkeypatch.setattr(downloader, "_run_download_command", fake_run)

    with pytest.raises(downloader.DownloadError) as exc:
        asyncio.run(
            downloader.download_video(
                "https://youtube.com/watch?v=abc123",
                "abc123",
                progress_callback=lambda _progress, _line: None,
                raise_on_error=True,
            )
        )

    assert "does not pass filter" in str(exc.value)
    assert "MAX_SOURCE_DURATION_SECONDS" in str(exc.value)


def test_download_accepts_variant_format_and_duration_override(tmp_path, monkeypatch):
    _stub_tools(monkeypatch, tmp_path)
    captured = {}

    def fake_run(cmd, *, timeout, progress_callback):
        captured["cmd"] = cmd
        return 1, "ERROR: synthetic", ""

    monkeypatch.setattr(downloader, "_run_download_command", fake_run)

    result = asyncio.run(
        downloader.download_video(
            "https://youtube.com/watch?v=abc123",
            "abc123",
            progress_callback=lambda _progress, _line: None,
            format_selector="best[height<=720]",
            max_duration_seconds=14400,
        )
    )

    assert result is None
    cmd = captured["cmd"]
    assert cmd[cmd.index("--format") + 1] == "best[height<=720]"
    assert cmd[cmd.index("--match-filter") + 1] == "duration <= 14400"


def test_download_retries_without_aria2c_when_external_downloader_fails(tmp_path, monkeypatch):
    _stub_tools(monkeypatch, tmp_path)
    monkeypatch.setattr(downloader, "find_aria2c", lambda: "aria2c")
    calls = []

    def fake_run(cmd, *, timeout, progress_callback):
        calls.append(cmd)
        if "--downloader" in cmd:
            return 1, "ERROR: aria2c exited with code 22", ""
        output = tmp_path / "downloads" / "abc123.mp4"
        output.write_bytes(b"0" * 100_001)
        progress_callback(0.5, "[download] 50.0% of source")
        return 0, "[download] 100.0% of source", ""

    monkeypatch.setattr(downloader, "_run_download_command", fake_run)

    result = asyncio.run(
        downloader.download_video(
            "https://youtube.com/watch?v=abc123",
            "abc123",
            progress_callback=lambda _progress, _line: None,
            raise_on_error=True,
        )
    )

    assert result == str(tmp_path / "downloads" / "abc123.mp4")
    assert len(calls) == 2
    assert "--downloader" in calls[0]
    assert "--downloader" not in calls[1]


def test_download_can_disable_external_downloader(tmp_path, monkeypatch):
    _stub_tools(monkeypatch, tmp_path)
    monkeypatch.setattr(downloader, "find_aria2c", lambda: "aria2c")
    captured = {}

    def fake_run(cmd, *, timeout, progress_callback):
        captured["cmd"] = cmd
        output = tmp_path / "downloads" / "abc123.mp4"
        output.write_bytes(b"0" * 100_001)
        return 0, "[download] 100.0% of source", ""

    monkeypatch.setattr(downloader, "_run_download_command", fake_run)

    result = asyncio.run(
        downloader.download_video(
            "https://youtube.com/watch?v=abc123",
            "abc123",
            progress_callback=lambda _progress, _line: None,
            use_external_downloader=False,
        )
    )

    assert result == str(tmp_path / "downloads" / "abc123.mp4")
    assert "--downloader" not in captured["cmd"]


def test_progress_normalizer_keeps_video_audio_downloads_monotonic():
    normalizer = downloader._DownloadProgressNormalizer()
    sequence = [
        (0.10, "[download] 10.0% of 136.11MiB"),
        (0.98, "[download] 98.0% of 136.11MiB"),
        (0.12, "[download] 12.0% of 98.04MiB"),
        (0.50, "[download] 50.0% of 98.04MiB"),
        (0.98, "[download] 98.0% of 98.04MiB"),
        (0.95, "[Merger] Merging formats"),
    ]

    values = [normalizer.normalize(progress, line)[0] for progress, line in sequence]

    assert values == sorted(values)
    assert values[1] > 0.8
    assert values[2] > values[1]
    assert values[-1] >= 0.95
