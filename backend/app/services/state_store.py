"""
Persistence for download/process state, captions, hashtags, thumbnails.

SQLite remains the default local store. Set STATE_STORE_BACKEND=supabase or
postgres with SUPABASE_DB_URL/DATABASE_URL to use Supabase Postgres.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - only raised when Postgres backend is requested
    psycopg = None
    dict_row = None

DEFAULT_DB_PATH = os.path.join(get_settings().data_dir, "app_state.db")
DB_PATH = DEFAULT_DB_PATH
_FORCE_SQLITE = False
_POSTGRES_DISABLED_REASON: str | None = None


def _database_url() -> str:
    settings = get_settings()
    return settings.supabase_db_url or settings.database_url


def _use_postgres() -> bool:
    if _FORCE_SQLITE:
        return False
    if DB_PATH != DEFAULT_DB_PATH:
        return False
    backend = (get_settings().state_store_backend or "sqlite").lower()
    if backend in {"supabase", "postgres"}:
        return bool(_database_url())
    if backend == "auto":
        return bool(_database_url())
    return False


def backend_name() -> str:
    if _use_postgres():
        configured = (get_settings().state_store_backend or "postgres").lower()
        return "supabase" if configured in {"supabase", "auto"} else "postgres"
    return "sqlite"


def backend_status() -> dict:
    settings = get_settings()
    configured = (settings.state_store_backend or "sqlite").lower()
    return {
        "configured": configured,
        "effective": backend_name(),
        "supabase_configured": bool(settings.supabase_url and settings.supabase_db_url),
        "fallback_reason": _POSTGRES_DISABLED_REASON or "",
    }


def _sqlite_conn() -> sqlite3.Connection:
    os.makedirs(get_settings().data_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _postgres_conn():
    if psycopg is None or dict_row is None:
        raise RuntimeError("psycopg is not installed. Run pip install -r backend/requirements.txt")
    return psycopg.connect(_database_url(), row_factory=dict_row, connect_timeout=15)


def _conn():
    return _postgres_conn() if _use_postgres() else _sqlite_conn()


def _ph() -> str:
    return "%s" if _use_postgres() else "?"


def _row_dict(row) -> dict:
    return dict(row)


def _decode_state_row(row) -> dict:
    d = _row_dict(row)
    if d.get("hashtags"):
        d["hashtags"] = json.loads(d["hashtags"])
    if d.get("metadata"):
        d["metadata"] = json.loads(d["metadata"])
    return d


def _create_schema(conn):
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subtitle_tracks (
            video_id TEXT PRIMARY KEY,
            language TEXT DEFAULT 'en',
            style TEXT DEFAULT 'default',
            position TEXT DEFAULT 'bottom',
            animation TEXT DEFAULT 'none',
            transcript TEXT,
            words TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS timeline_projects (
            video_id TEXT PRIMARY KEY,
            project TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_profiles (
            owner_id TEXT PRIMARY KEY,
            plan TEXT DEFAULT 'free',
            subscription_status TEXT DEFAULT 'inactive',
            stripe_customer_id TEXT,
            rights_accepted INTEGER DEFAULT 0,
            metadata TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_events (
            event_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            metadata TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_usage_owner_type_created
        ON usage_events(owner_id, event_type, created_at)
    """)
    conn.commit()


def init_db():
    global _FORCE_SQLITE, _POSTGRES_DISABLED_REASON
    try:
        with _conn() as conn:
            _create_schema(conn)
    except Exception as exc:
        if not _use_postgres() or not get_settings().state_store_fallback_to_sqlite:
            raise
        _FORCE_SQLITE = True
        _POSTGRES_DISABLED_REASON = str(exc).splitlines()[0]
        with _conn() as conn:
            _create_schema(conn)


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
    ph = _ph()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT * FROM video_state WHERE video_id = {ph}", (video_id,)
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
                   VALUES ({0}, {0}, {0}, {0}, {0}, {0}, {0}, {0}, {0}, {0}, {0}, {0})""".format(ph),
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
                    updates.append(f"{key} = {ph}")
                    values.append(val)
            if updates:
                values.append(video_id)
                conn.execute(
                    f"UPDATE video_state SET {', '.join(updates)} WHERE video_id = {ph}",
                    values,
                )
        conn.commit()


def get_video(video_id: str) -> Optional[dict]:
    ph = _ph()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT * FROM video_state WHERE video_id = {ph}", (video_id,)
        ).fetchone()
    if not row:
        return None
    return _decode_state_row(row)


def list_videos(status: Optional[str] = None) -> list[dict]:
    ph = _ph()
    with _conn() as conn:
        if status:
            rows = conn.execute(
                f"SELECT * FROM video_state WHERE status = {ph} ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM video_state ORDER BY updated_at DESC"
            ).fetchall()
    return [_decode_state_row(row) for row in rows]


def save_subtitle_track(video_id: str, track: dict):
    now = datetime.now(timezone.utc).isoformat()
    words = track.get("words") or []
    transcript = track.get("transcript")
    if transcript is None:
        transcript = " ".join(w.get("text", "") for w in words).strip()

    ph = _ph()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO subtitle_tracks
               (video_id, language, style, position, animation, transcript, words, updated_at)
               VALUES ({0}, {0}, {0}, {0}, {0}, {0}, {0}, {0})
               ON CONFLICT(video_id) DO UPDATE SET
                   language = excluded.language,
                   style = excluded.style,
                   position = excluded.position,
                   animation = excluded.animation,
                   transcript = excluded.transcript,
                   words = excluded.words,
                   updated_at = excluded.updated_at""".format(ph),
            (
                video_id,
                track.get("language", "en"),
                track.get("style", "default"),
                track.get("position", "bottom"),
                track.get("animation", "none"),
                transcript,
                json.dumps(words),
                now,
            ),
        )
        conn.commit()


def get_subtitle_track(video_id: str) -> Optional[dict]:
    ph = _ph()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT * FROM subtitle_tracks WHERE video_id = {ph}", (video_id,)
        ).fetchone()
    if not row:
        return None
    d = _row_dict(row)
    d["words"] = json.loads(d["words"] or "[]")
    return d


def save_timeline_project(video_id: str, project: dict):
    now = datetime.now(timezone.utc).isoformat()
    data = dict(project)
    data["updated_at"] = now
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO timeline_projects (video_id, project, updated_at)
               VALUES ({0}, {0}, {0})
               ON CONFLICT(video_id) DO UPDATE SET
                   project = excluded.project,
                   updated_at = excluded.updated_at""".format(ph),
            (video_id, json.dumps(data), now),
        )
        conn.commit()


def get_timeline_project(video_id: str) -> Optional[dict]:
    ph = _ph()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT project FROM timeline_projects WHERE video_id = {ph}", (video_id,)
        ).fetchone()
    if not row:
        return None
    project_json = row["project"] if isinstance(row, dict) else row["project"]
    if not project_json:
        return None
    try:
        return json.loads(project_json)
    except json.JSONDecodeError:
        return None


def get_account_profile(owner_id: str) -> Optional[dict]:
    ph = _ph()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT * FROM account_profiles WHERE owner_id = {ph}", (owner_id,)
        ).fetchone()
    if not row:
        return None
    data = _row_dict(row)
    data["rights_accepted"] = bool(data.get("rights_accepted"))
    if data.get("metadata"):
        data["metadata"] = json.loads(data["metadata"])
    else:
        data["metadata"] = {}
    return data


def get_account_profile_by_customer(stripe_customer_id: str) -> Optional[dict]:
    if not stripe_customer_id:
        return None
    ph = _ph()
    with _conn() as conn:
        row = conn.execute(
            f"SELECT * FROM account_profiles WHERE stripe_customer_id = {ph}",
            (stripe_customer_id,),
        ).fetchone()
    if not row:
        return None
    data = _row_dict(row)
    data["rights_accepted"] = bool(data.get("rights_accepted"))
    if data.get("metadata"):
        data["metadata"] = json.loads(data["metadata"])
    else:
        data["metadata"] = {}
    return data


def save_account_profile(
    owner_id: str,
    *,
    plan: Optional[str] = None,
    subscription_status: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    rights_accepted: Optional[bool] = None,
    metadata: Optional[dict] = None,
) -> dict:
    existing = get_account_profile(owner_id) or {}
    next_data = {
        "plan": plan if plan is not None else existing.get("plan", "free"),
        "subscription_status": (
            subscription_status
            if subscription_status is not None
            else existing.get("subscription_status", "inactive")
        ),
        "stripe_customer_id": (
            stripe_customer_id
            if stripe_customer_id is not None
            else existing.get("stripe_customer_id")
        ),
        "rights_accepted": (
            rights_accepted
            if rights_accepted is not None
            else bool(existing.get("rights_accepted", False))
        ),
        "metadata": metadata if metadata is not None else existing.get("metadata", {}),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    ph = _ph()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO account_profiles
               (owner_id, plan, subscription_status, stripe_customer_id, rights_accepted, metadata, updated_at)
               VALUES ({0}, {0}, {0}, {0}, {0}, {0}, {0})
               ON CONFLICT(owner_id) DO UPDATE SET
                   plan = excluded.plan,
                   subscription_status = excluded.subscription_status,
                   stripe_customer_id = excluded.stripe_customer_id,
                   rights_accepted = excluded.rights_accepted,
                   metadata = excluded.metadata,
                   updated_at = excluded.updated_at""".format(ph),
            (
                owner_id,
                next_data["plan"],
                next_data["subscription_status"],
                next_data["stripe_customer_id"],
                1 if next_data["rights_accepted"] else 0,
                json.dumps(next_data["metadata"]),
                next_data["updated_at"],
            ),
        )
        conn.commit()
    return get_account_profile(owner_id) or {"owner_id": owner_id, **next_data}


def record_usage(owner_id: str, event_type: str, quantity: int = 1, metadata: Optional[dict] = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    event = {
        "event_id": uuid.uuid4().hex,
        "owner_id": owner_id,
        "event_type": event_type,
        "quantity": max(1, int(quantity or 1)),
        "metadata": metadata or {},
        "created_at": now,
    }
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO usage_events
               (event_id, owner_id, event_type, quantity, metadata, created_at)
               VALUES ({0}, {0}, {0}, {0}, {0}, {0})""".format(ph),
            (
                event["event_id"],
                event["owner_id"],
                event["event_type"],
                event["quantity"],
                json.dumps(event["metadata"]),
                event["created_at"],
            ),
        )
        conn.commit()
    return event


def usage_totals(owner_id: str, period_start: str) -> dict[str, int]:
    ph = _ph()
    with _conn() as conn:
        rows = conn.execute(
            f"""SELECT event_type, COALESCE(SUM(quantity), 0) AS total
                FROM usage_events
                WHERE owner_id = {ph} AND created_at >= {ph}
                GROUP BY event_type""",
            (owner_id, period_start),
        ).fetchall()
    return {row["event_type"]: int(row["total"] or 0) for row in rows}
