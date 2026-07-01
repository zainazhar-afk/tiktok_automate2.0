import asyncio

import pytest

from app.api import videos
from app.services import job_queue, state_store, variants
from app.tenant import reset_current_owner, set_current_owner, storage_video_id


def _init_tmp_store(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr(state_store, "DB_PATH", str(db_path))
    state_store.init_db()


def test_state_store_allows_same_video_id_per_owner(tmp_path, monkeypatch):
    _init_tmp_store(tmp_path, monkeypatch)

    token = set_current_owner("owner-a")
    try:
        state_store.upsert_video("same-video", title="Owner A", status="completed")
    finally:
        reset_current_owner(token)

    token = set_current_owner("owner-b")
    try:
        state_store.upsert_video("same-video", title="Owner B", status="downloaded")
    finally:
        reset_current_owner(token)

    owner_a = state_store.get_video("same-video", owner_id="owner-a")
    owner_b = state_store.get_video("same-video", owner_id="owner-b")

    assert owner_a["title"] == "Owner A"
    assert owner_a["status"] == "completed"
    assert owner_b["title"] == "Owner B"
    assert owner_b["status"] == "downloaded"
    assert [row["title"] for row in state_store.list_videos(owner_id="owner-a")] == ["Owner A"]
    assert [row["title"] for row in state_store.list_videos(owner_id="owner-b")] == ["Owner B"]


def test_video_file_ownership_uses_persisted_media_paths(tmp_path, monkeypatch):
    _init_tmp_store(tmp_path, monkeypatch)
    output = tmp_path / "output"
    downloads = tmp_path / "downloads"
    output.mkdir()
    downloads.mkdir()
    monkeypatch.setattr(videos, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(videos, "DOWNLOAD_DIR", str(downloads))

    owner_a_file = f"{storage_video_id('abc123', 'owner-a')}_processed.mp4"
    owner_b_file = f"{storage_video_id('abc123', 'owner-b')}_processed.mp4"
    owner_a_path = output / owner_a_file
    owner_b_path = output / owner_b_file
    owner_a_path.write_bytes(b"owner-a-video")
    owner_b_path.write_bytes(b"owner-b-video")
    (output / "abc123_processed.mp4").write_bytes(b"legacy-video")

    state_store.upsert_video(
        "abc123",
        owner_id="owner-a",
        title="Owner A",
        status="completed",
        output_path=str(owner_a_path),
    )
    state_store.upsert_video(
        "abc123",
        owner_id="owner-b",
        title="Owner B",
        status="completed",
        output_path=str(owner_b_path),
    )

    assert videos._filename_owned(owner_a_file, "owner-a")
    assert not videos._filename_owned("abc123_processed.mp4", "owner-a")
    assert not videos._filename_owned(owner_a_file, "owner-b")
    assert videos._filename_owned(owner_b_file, "owner-b")
    assert not videos._filename_owned(owner_b_file, "owner-a")


def test_job_queue_filters_jobs_by_owner(monkeypatch):
    monkeypatch.setattr(job_queue, "_redis", False)
    job_queue._memory_jobs.clear()

    token = set_current_owner("owner-a")
    try:
        job_a = job_queue.create_job("video-a")
    finally:
        reset_current_owner(token)

    token = set_current_owner("owner-b")
    try:
        job_b = job_queue.create_job("video-b")
    finally:
        reset_current_owner(token)

    assert [job.job_id for job in job_queue.list_jobs(owner_id="owner-a")] == [job_a.job_id]
    assert [job.job_id for job in job_queue.list_jobs(owner_id="owner-b")] == [job_b.job_id]
    assert job_queue.get_job(job_a.job_id, owner_id="owner-b") is None
    assert job_queue.get_job(job_a.job_id, owner_id="owner-a").job_id == job_a.job_id


def test_variant_source_status_and_generation_are_owner_scoped(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source_path = uploads / "tenant_source.mp4"
    source_path.write_bytes(b"owner-a-source")

    class Settings:
        uploads_dir = str(uploads)

    monkeypatch.setattr(variants, "get_settings", lambda: Settings())
    monkeypatch.setattr(variants, "find_ffmpeg", lambda: "ffmpeg")
    variants._source_jobs.clear()

    token = set_current_owner("owner-a")
    try:
        variants.register_source("tenant_source", source_path.name, path=str(source_path))
        assert variants.get_source_status("tenant_source")["filename"] == source_path.name
    finally:
        reset_current_owner(token)

    token = set_current_owner("owner-b")
    try:
        with pytest.raises(FileNotFoundError):
            variants.get_source_status("tenant_source")
        with pytest.raises(FileNotFoundError):
            asyncio.run(variants.generate_variants("tenant_source"))
    finally:
        reset_current_owner(token)
        variants._source_jobs.clear()
