"""
SQLite persistence for download/process state, captions, hashtags, thumbnails.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings

DB_PATH = os.path.join(get_settings().data_dir, "app_state.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(get_settings().data_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_state (
                video_id TEXT PRIMARY KEY,
                title TEXT,
                channel TEXT,
                status TEXT DEFAULT 'discovered',
                download_path TEXT,
                output_path TEXT,
                thumbnail_path TEXT,
                caption TEXT,
                hashtags TEXT,
                error TEXT,
                metadata TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()


def upsert_video(
    video_id: str,
    *,
    title: str = "",
    channel: str = "",
    status: Optional[str] = None,
    download_path: Optional[str] = None,
    output_path: Optional[str] = None,
    thumbnail_path: Optional[str] = None,
    caption: Optional[str] = None,
    hashtags: Optional[list[str]] = None,
    error: Optional[str] = None,
    metadata: Optional[dict] = None,
):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM video_state WHERE video_id = ?", (video_id,)
        ).fetchone()

        fields = {
            "title": title,
            "channel": channel,
            "status": status,
            "download_path": download_path,
            "output_path": output_path,
            "thumbnail_path": thumbnail_path,
            "caption": caption,
            "hashtags": json.dumps(hashtags) if hashtags is not None else None,
            "error": error,
            "metadata": json.dumps(metadata) if metadata is not None else None,
            "updated_at": now,
        }

        if row is None:
            conn.execute(
                """INSERT INTO video_state
                   (video_id, title, channel, status, download_path, output_path,
                    thumbnail_path, caption, hashtags, error, metadata, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video_id,
                    title,
                    channel,
                    status or "discovered",
                    download_path,
                    output_path,
                    thumbnail_path,
                    caption,
                    json.dumps(hashtags) if hashtags else None,
                    error,
                    json.dumps(metadata) if metadata else None,
                    now,
                ),
            )
        else:
            updates = []
            values = []
            for key, val in fields.items():
                if val is not None:
                    updates.append(f"{key} = ?")
                    values.append(val)
            if updates:
                values.append(video_id)
                conn.execute(
                    f"UPDATE video_state SET {', '.join(updates)} WHERE video_id = ?",
                    values,
                )
        conn.commit()


def get_video(video_id: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM video_state WHERE video_id = ?", (video_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("hashtags"):
        d["hashtags"] = json.loads(d["hashtags"])
    if d.get("metadata"):
        d["metadata"] = json.loads(d["metadata"])
    return d


def list_videos(status: Optional[str] = None) -> list[dict]:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM video_state WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM video_state ORDER BY updated_at DESC"
            ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("hashtags"):
            d["hashtags"] = json.loads(d["hashtags"])
        if d.get("metadata"):
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return result
