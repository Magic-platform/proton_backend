import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path


DEFAULT_DB_PATH = "/home/ubuntu/opt/backend_proton/data/scheduled_mails.sqlite3"
STATUSES = {"pending", "processing", "sent", "failed", "cancelled"}


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)

    if parsed.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone")

    return parsed.astimezone(UTC)


def get_db_path() -> str:
    configured_path = os.getenv("SCHEDULED_DB_PATH")

    if configured_path:
        return configured_path

    if os.name == "nt":
        return "data/scheduled_mails.sqlite3"

    return DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    db_path = Path(get_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def db_connection():
    connection = connect()

    try:
        yield connection
    finally:
        connection.close()


def init_db() -> None:
    with db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_mails (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                base44_email_id TEXT,
                to_json TEXT NOT NULL,
                cc_json TEXT,
                bcc_json TEXT,
                subject TEXT NOT NULL,
                text TEXT NOT NULL,
                html TEXT,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                locked_at TEXT,
                last_attempt_at TEXT,
                sent_at TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_mails_due ON scheduled_mails(status, scheduled_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_mails_created ON scheduled_mails(created_at)"
        )
        connection.commit()


def row_to_mail(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None

    item = dict(row)
    item["to"] = json.loads(item.pop("to_json"))
    item["cc"] = json.loads(item.pop("cc_json") or "[]")
    item["bcc"] = json.loads(item.pop("bcc_json") or "[]")
    return item


def create_scheduled_mail(
    *,
    idempotency_key: str,
    to: list[str],
    subject: str,
    text: str,
    scheduled_at: str,
    html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    base44_email_id: str | None = None,
) -> dict:
    init_db()
    cc = cc or []
    bcc = bcc or []
    timestamp = to_utc_iso(now_utc())

    with db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM scheduled_mails WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()

        if existing:
            connection.commit()
            return row_to_mail(existing)

        mail_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO scheduled_mails (
                id, idempotency_key, base44_email_id, to_json, cc_json, bcc_json,
                subject, text, html, scheduled_at, status, attempts, max_attempts,
                locked_at, last_attempt_at, sent_at, error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 3, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (
                mail_id,
                idempotency_key,
                base44_email_id,
                json.dumps(to),
                json.dumps(cc),
                json.dumps(bcc),
                subject,
                text,
                html,
                scheduled_at,
                timestamp,
                timestamp,
            ),
        )
        created = connection.execute(
            "SELECT * FROM scheduled_mails WHERE id = ?",
            (mail_id,),
        ).fetchone()
        connection.commit()
        return row_to_mail(created)


def list_scheduled_mails(
    *,
    status: str | None = None,
    limit: int = 50,
    before_created_at: str | None = None,
) -> dict:
    init_db()
    limit = max(1, min(limit, 200))
    conditions = []
    params = []

    if status:
        if status not in STATUSES:
            raise ValueError("invalid status")
        conditions.append("status = ?")
        params.append(status)

    if before_created_at:
        conditions.append("created_at < ?")
        params.append(before_created_at)

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM scheduled_mails {where_sql} ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with db_connection() as connection:
        rows = connection.execute(query, params).fetchall()

    items = [row_to_mail(row) for row in rows]
    return {"items": items, "count": len(items)}


def get_scheduled_mail(mail_id: str) -> dict | None:
    init_db()
    with db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM scheduled_mails WHERE id = ?",
            (mail_id,),
        ).fetchone()
    return row_to_mail(row)


def cancel_scheduled_mail(mail_id: str) -> dict | None:
    init_db()
    timestamp = to_utc_iso(now_utc())

    with db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM scheduled_mails WHERE id = ?",
            (mail_id,),
        ).fetchone()

        if row is None:
            connection.commit()
            return None

        if row["status"] not in {"pending", "failed"}:
            connection.commit()
            return row_to_mail(row)

        connection.execute(
            """
            UPDATE scheduled_mails
            SET status = 'cancelled', updated_at = ?, locked_at = NULL
            WHERE id = ?
            """,
            (timestamp, mail_id),
        )
        updated = connection.execute(
            "SELECT * FROM scheduled_mails WHERE id = ?",
            (mail_id,),
        ).fetchone()
        connection.commit()
        return row_to_mail(updated)


def reset_stale_processing(stale_after_minutes: int = 15) -> int:
    init_db()
    threshold = to_utc_iso(now_utc() - timedelta(minutes=stale_after_minutes))
    timestamp = to_utc_iso(now_utc())

    with db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT id, attempts, max_attempts
            FROM scheduled_mails
            WHERE status = 'processing'
              AND locked_at IS NOT NULL
              AND locked_at < ?
            """,
            (threshold,),
        ).fetchall()

        for row in rows:
            next_status = "pending" if row["attempts"] < row["max_attempts"] else "failed"
            error = "processing lock expired" if next_status == "failed" else None
            connection.execute(
                """
                UPDATE scheduled_mails
                SET status = ?, locked_at = NULL, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status, error, timestamp, row["id"]),
            )

        connection.commit()
        return len(rows)


def claim_due_mail() -> dict | None:
    init_db()
    timestamp = to_utc_iso(now_utc())

    with db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT *
            FROM scheduled_mails
            WHERE status = 'pending'
              AND scheduled_at <= ?
              AND attempts < max_attempts
            ORDER BY scheduled_at ASC, created_at ASC
            LIMIT 1
            """,
            (timestamp,),
        ).fetchone()

        if row is None:
            connection.commit()
            return None

        connection.execute(
            """
            UPDATE scheduled_mails
            SET status = 'processing',
                locked_at = ?,
                last_attempt_at = ?,
                attempts = attempts + 1,
                updated_at = ?,
                error = NULL
            WHERE id = ? AND status = 'pending'
            """,
            (timestamp, timestamp, timestamp, row["id"]),
        )
        claimed = connection.execute(
            "SELECT * FROM scheduled_mails WHERE id = ?",
            (row["id"],),
        ).fetchone()
        connection.commit()
        return row_to_mail(claimed)


def mark_sent(mail_id: str) -> dict | None:
    timestamp = to_utc_iso(now_utc())

    with db_connection() as connection:
        connection.execute(
            """
            UPDATE scheduled_mails
            SET status = 'sent',
                sent_at = ?,
                locked_at = NULL,
                error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, mail_id),
        )
        row = connection.execute(
            "SELECT * FROM scheduled_mails WHERE id = ?",
            (mail_id,),
        ).fetchone()
        connection.commit()
    return row_to_mail(row)


def mark_failed_or_retry(mail_id: str, error: str, retry_delay_minutes: int = 5) -> dict | None:
    timestamp = to_utc_iso(now_utc())

    with db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT attempts, max_attempts FROM scheduled_mails WHERE id = ?",
            (mail_id,),
        ).fetchone()

        if row is None:
            connection.commit()
            return None

        if row["attempts"] < row["max_attempts"]:
            next_status = "pending"
            next_scheduled_at = to_utc_iso(now_utc() + timedelta(minutes=retry_delay_minutes))
        else:
            next_status = "failed"
            next_scheduled_at = None

        if next_scheduled_at:
            connection.execute(
                """
                UPDATE scheduled_mails
                SET status = ?, scheduled_at = ?, locked_at = NULL, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status, next_scheduled_at, error[:2000], timestamp, mail_id),
            )
        else:
            connection.execute(
                """
                UPDATE scheduled_mails
                SET status = ?, locked_at = NULL, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status, error[:2000], timestamp, mail_id),
            )

        updated = connection.execute(
            "SELECT * FROM scheduled_mails WHERE id = ?",
            (mail_id,),
        ).fetchone()
        connection.commit()
        return row_to_mail(updated)
