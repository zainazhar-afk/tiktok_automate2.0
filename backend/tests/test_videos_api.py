import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import videos
from app.services import state_store
from app.tenant import storage_video_id


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


def test_list_videos_returns_owned_unavailable_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    output = tmp_path / "output"
    downloads = tmp_path / "downloads"
    output.mkdir()
    downloads.mkdir()
    monkeypatch.setattr(state_store, "DB_PATH", str(db_path))
    monkeypatch.setattr(videos, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(videos, "DOWNLOAD_DIR", str(downloads))
    state_store.init_db()

    missing_filename = f"{storage_video_id('missing_export', 'owner-a')}_processed.mp4"
    state_store.upsert_video(
        "missing_export",
        owner_id="owner-a",
        title="Missing export",
        status="completed",
        output_path=str(output / missing_filename),
        caption="Ready caption",
        hashtags=["#ready"],
    )

    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(user_id="owner-a")))
    result = asyncio.run(videos.list_videos(request, type="processed"))

    assert result["total"] == 1
    row = result["videos"][0]
    assert row["id"] == "missing_export"
    assert row["filename"] == missing_filename
    assert row["visibility_status"] == "unavailable"
    assert "missing" in row["unavailable_reason"].lower()
