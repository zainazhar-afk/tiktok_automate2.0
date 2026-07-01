import asyncio

from app.models.schemas import SubtitleTrack
from app.services import state_store, subtitle_editor, subtitles
from app.tenant import reset_current_owner, set_current_owner, storage_video_id


def test_parse_srt_to_words_and_export_vtt():
    content = """1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:03,500 --> 00:00:05,000
Follow for more
"""
    cues = subtitle_editor.parse_subtitle_text(content, "srt")
    words = subtitle_editor.cues_to_words(cues)

    assert [w["text"] for w in words] == ["Hello", "world", "Follow", "for", "more"]
    assert words[0]["start"] == 1.0
    assert words[-1]["end"] == 5.0

    vtt = subtitle_editor.export_vtt({"words": words})
    assert vtt.startswith("WEBVTT")
    assert "Hello world" in vtt


def test_save_track_persists_words(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr(state_store, "DB_PATH", str(db_path))
    state_store.init_db()

    track = SubtitleTrack(
        video_id="abc_123",
        language="en",
        style="neon",
        position="top",
        animation="pop",
        transcript="Hello",
        words=[{"id": "w1", "text": "Hello", "start": 0, "end": 1, "highlighted": True}],
    )

    saved = subtitle_editor.save_track(track)

    assert saved["video_id"] == "abc_123"
    assert saved["style"] == "neon"
    assert saved["words"][0]["highlighted"] is True


def test_apply_transcript_rebuilds_words_and_sidecars(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(state_store, "DB_PATH", str(db_path))
    monkeypatch.setattr(subtitle_editor, "OUTPUT_DIR", str(output_dir))
    state_store.init_db()

    track = SubtitleTrack(
        video_id="abc_123",
        language="ur",
        style="bold",
        position="bottom",
        animation="none",
        transcript="one two three four",
        words=[
            {"id": "w1", "text": "old", "start": 1.0, "end": 2.0, "highlighted": True},
            {"id": "w2", "text": "text", "start": 3.0, "end": 5.0, "highlighted": False},
        ],
    )

    saved = subtitle_editor.apply_transcript(track)

    assert saved["language"] == "ur"
    assert saved["style"] == "bold"
    assert [word["text"] for word in saved["words"]] == ["one", "two", "three", "four"]
    assert saved["words"][0]["start"] == 1.0
    assert saved["words"][-1]["end"] == 5.0
    assert saved["words"][0]["highlighted"] is True
    assert (output_dir / "abc_123_edited.srt").exists()
    assert (output_dir / "abc_123_edited.vtt").exists()


def test_transcription_rejects_too_short_locked_provider_output(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    media = tmp_path / "long.mp4"
    media.write_bytes(b"not a real video, duration is monkeypatched")
    monkeypatch.setattr(subtitles, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(subtitles, "_media_duration", lambda _path: asyncio.sleep(0, result=90.0))

    class Settings:
        transcription_provider = "auto"
        groq_api_keys = ["key"]
        deepgram_api_keys = []
        groq_language = "auto"
        deepgram_language = "auto"
        whisper_model = "base"

    async def fake_groq(_input_path, srt_path, _video_id, _language):
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nToo short\n")
        return True

    monkeypatch.setattr(subtitles, "get_settings", lambda: Settings())
    monkeypatch.setattr(subtitles, "_groq_to_srt", fake_groq)

    result = asyncio.run(
        subtitles.generate_subtitles(str(media), "abc_123", language="ur", provider="groq")
    )

    assert result is None
    assert not (output_dir / "abc_123.srt").exists()


def test_multilingual_language_is_not_forwarded_as_api_code():
    assert subtitles._api_language("multi") == ""


def test_transcribe_track_uses_current_owner_source_and_track(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(state_store, "DB_PATH", str(db_path))
    monkeypatch.setattr(subtitle_editor, "OUTPUT_DIR", str(output_dir))
    state_store.init_db()

    owner_a_source = output_dir / f"{storage_video_id('shared_video', 'owner-a')}_processed.mp4"
    owner_b_source = output_dir / f"{storage_video_id('shared_video', 'owner-b')}_processed.mp4"
    owner_a_source.write_bytes(b"owner-a-media")
    owner_b_source.write_bytes(b"owner-b-media")

    state_store.upsert_video(
        "shared_video",
        owner_id="owner-a",
        status="completed",
        output_path=str(owner_a_source),
    )
    state_store.upsert_video(
        "shared_video",
        owner_id="owner-b",
        status="completed",
        output_path=str(owner_b_source),
    )

    seen_sources: list[str] = []

    async def fake_generate(source, video_id, language="auto", provider="auto"):
        seen_sources.append(source)
        srt_path = output_dir / f"{storage_video_id(video_id)}.srt"
        srt_path.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nOwner A only\n",
            encoding="utf-8",
        )
        return str(srt_path)

    monkeypatch.setattr(subtitle_editor.subtitles, "generate_subtitles", fake_generate)

    token = set_current_owner("owner-a")
    try:
        track = asyncio.run(
            subtitle_editor.transcribe_track("shared_video", language="ur", provider="groq")
        )
    finally:
        reset_current_owner(token)

    assert seen_sources == [str(owner_a_source)]
    assert track["language"] == "ur"
    assert track["transcript"] == "Owner A only"
    assert state_store.get_subtitle_track("shared_video", owner_id="owner-a")["transcript"] == "Owner A only"
    assert state_store.get_subtitle_track("shared_video", owner_id="owner-b") is None
