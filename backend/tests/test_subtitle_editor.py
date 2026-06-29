from app.models.schemas import SubtitleTrack
from app.services import state_store, subtitle_editor


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
