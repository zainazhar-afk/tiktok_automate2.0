import pytest
from fastapi import HTTPException

from app.api import videos


def test_resolve_media_file_rejects_path_traversal(tmp_path, monkeypatch):
    output = tmp_path / "output"
    downloads = tmp_path / "downloads"
    output.mkdir()
    downloads.mkdir()
    (output / "ok.mp4").write_bytes(b"video")

    monkeypatch.setattr(videos, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(videos, "DOWNLOAD_DIR", str(downloads))

    assert videos._resolve_media_file("ok.mp4") == str(output / "ok.mp4")

    with pytest.raises(HTTPException) as exc:
        videos._resolve_media_file("../ok.mp4")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        videos._resolve_media_file(r"..\ok.mp4")
    assert exc.value.status_code == 400


def test_list_audio_assets_filters_supported_files(tmp_path):
    (tmp_path / "bg.mp3").write_bytes(b"audio")
    (tmp_path / "voice.WAV").write_bytes(b"audio")
    (tmp_path / "notes.txt").write_text("not audio")

    assert videos._list_audio_assets(str(tmp_path)) == ["bg.mp3", "voice.WAV"]
