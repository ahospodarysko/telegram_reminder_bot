"""PostgreSQL storage layer — the source of truth for users, reminders, and pings.

Datetimes are stored as naive ``TIMESTAMP`` columns holding UTC instants (no session
timezone conversion involved); :func:`to_db`/:func:`from_db` convert to/from
timezone-aware UTC ``datetime`` objects at the boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        chat_id    BIGINT PRIMARY KEY,
        timezone   TEXT NOT NULL,
        language   TEXT NOT NULL DEFAULT 'en',
        created_at TIMESTAMP NOT NULL
    )
    """,
    # "offset" is a reserved word in PostgreSQL, so the column is named offset_label;
    # queries alias it back to "offset" for Python code that reads row["offset"].
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id         BIGSERIAL PRIMARY KEY,
        chat_id    BIGINT NOT NULL REFERENCES users(chat_id),
        text       TEXT NOT NULL,
        type       TEXT NOT NULL DEFAULT 'timed',
        due_at_utc TIMESTAMP,
        status     TEXT NOT NULL DEFAULT 'active',
        recurrence TEXT NOT NULL DEFAULT 'none',
        anchor_day INTEGER,
        created_at TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS occurrences (
        id           BIGSERIAL PRIMARY KEY,
        reminder_id  BIGINT NOT NULL REFERENCES reminders(id),
        offset_label TEXT NOT NULL,
        fire_at_utc  TIMESTAMP NOT NULL,
        sent         INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_occurrences_due
        ON occurrences(sent, fire_at_utc)
    """,
]


def to_db(dt: datetime) -> datetime:
    """Convert a UTC-aware (or naive) datetime to the naive form stored in Postgres."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def from_db(value: datetime) -> datetime:
    """Reattach UTC tzinfo to a naive datetime read back from the database."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def connect(dsn: str) -> psycopg.Connection:
    """Open a PostgreSQL connection with dict-style row access.

    Autocommit is left off (the psycopg default): callers wrap writes in
    ``with conn.transaction():`` blocks, which commit on success and roll back on
    exception without closing the connection (unlike plain ``with conn:``, whose
    ``__exit__`` also closes it — fine for a one-shot script, wrong for a long-lived
    connection reused across requests).
    """
    return psycopg.connect(dsn, row_factory=dict_row)


def init_db(conn: psycopg.Connection) -> None:
    """Create tables/indexes if missing and apply lightweight column migrations."""
    with conn.transaction():
        for statement in SCHEMA:
            conn.execute(statement)
        _migrate(conn)


def _migrate(conn: psycopg.Connection) -> None:
    """Add columns introduced after a DB may already have been created."""
    user_columns = {
        row["column_name"]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
        )
    }
    if "language" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")

    reminder_columns = {
        row["column_name"]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'reminders'"
        )
    }
    if "recurrence" not in reminder_columns:
        conn.execute("ALTER TABLE reminders ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'none'")
    if "anchor_day" not in reminder_columns:
        conn.execute("ALTER TABLE reminders ADD COLUMN anchor_day INTEGER")


def reset_all_tables(conn: psycopg.Connection) -> None:
    """Delete every row and reset id sequences. Tests/dev only — never call in prod."""
    with conn.transaction():
        conn.execute("TRUNCATE occurrences, reminders, users RESTART IDENTITY CASCADE")


# --- users ---------------------------------------------------------------------------

def upsert_user(
    conn: psycopg.Connection, chat_id: int, tz_name: str, now_utc: datetime, language: str = "en"
) -> None:
    """Insert a user on first contact; leave an existing user's settings untouched."""
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO users (chat_id, timezone, language, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(chat_id) DO NOTHING
            """,
            (chat_id, tz_name, language, to_db(now_utc)),
        )


def get_user(conn: psycopg.Connection, chat_id: int) -> dict | None:
    """Return the user row for ``chat_id`` or ``None``."""
    return conn.execute(
        "SELECT chat_id, timezone, language, created_at FROM users WHERE chat_id = %s",
        (chat_id,),
    ).fetchone()


def set_timezone(conn: psycopg.Connection, chat_id: int, tz_name: str) -> None:
    """Update a user's timezone (does not retroactively change stored UTC times)."""
    with conn.transaction():
        conn.execute(
            "UPDATE users SET timezone = %s WHERE chat_id = %s", (tz_name, chat_id)
        )


def set_language(conn: psycopg.Connection, chat_id: int, language: str) -> None:
    """Update a user's UI language."""
    with conn.transaction():
        conn.execute(
            "UPDATE users SET language = %s WHERE chat_id = %s", (language, chat_id)
        )


# --- reminders -----------------------------------------------------------------------

def add_reminder(
    conn: psycopg.Connection,
    chat_id: int,
    text: str,
    due_at_utc: datetime | None,
    occurrences: list[tuple[str, datetime]],
    now_utc: datetime,
    type_: str = "timed",
    recurrence: str = "none",
    anchor_day: int | None = None,
) -> int:
    """Insert a reminder and its occurrence rows in a single transaction.

    ``recurrence`` is ``'none'`` (one-shot), ``'monthly'``, or ``'note'`` (periodic
    nudges, no real deadline); ``anchor_day`` is the 1–31 day-of-month a monthly
    reminder repeats on (``None`` otherwise).

    Returns:
        The new reminder's id.
    """
    with conn.transaction():
        cur = conn.execute(
            """
            INSERT INTO reminders
                (chat_id, text, type, due_at_utc, status, recurrence, anchor_day, created_at)
            VALUES (%s, %s, %s, %s, 'active', %s, %s, %s)
            RETURNING id
            """,
            (chat_id, text, type_, to_db(due_at_utc) if due_at_utc else None,
             recurrence, anchor_day, to_db(now_utc)),
        )
        reminder_id = cur.fetchone()["id"]
        _insert_occurrences(conn, reminder_id, occurrences)
    return reminder_id


def get_active_reminders(conn: psycopg.Connection, chat_id: int) -> list[dict]:
    """Return a user's active reminders, soonest deadline first."""
    return conn.execute(
        """
        SELECT id, chat_id, text, type, due_at_utc, status, recurrence, anchor_day, created_at
        FROM reminders
        WHERE chat_id = %s AND status = 'active'
        ORDER BY due_at_utc IS NULL, due_at_utc ASC
        """,
        (chat_id,),
    ).fetchall()


def get_reminder(conn: psycopg.Connection, reminder_id: int) -> dict | None:
    """Return a single reminder row by id, or ``None``."""
    return conn.execute(
        """
        SELECT id, chat_id, text, type, due_at_utc, status, recurrence, anchor_day, created_at
        FROM reminders WHERE id = %s
        """,
        (reminder_id,),
    ).fetchone()


def set_status(conn: psycopg.Connection, reminder_id: int, status: str) -> None:
    """Set a reminder's status (``active`` / ``done`` / ``cancelled``)."""
    with conn.transaction():
        conn.execute(
            "UPDATE reminders SET status = %s WHERE id = %s", (status, reminder_id)
        )


def purge_expired_reminders(conn: psycopg.Connection, cutoff_utc: datetime) -> int:
    """Delete one-shot reminders (and their occurrences) whose deadline passed before
    ``cutoff_utc``.

    A reminder that still has an unsent occurrence is kept — the scheduler sends
    overdue pings (late, never lost) before anything is purged. Recurring reminders are
    never purged; they roll forward until cancelled.

    Returns:
        The number of reminders deleted.
    """
    with conn.transaction():
        ids = [
            row["id"]
            for row in conn.execute(
                """
                SELECT r.id FROM reminders r
                WHERE r.recurrence = 'none'
                  AND r.due_at_utc IS NOT NULL
                  AND r.due_at_utc <= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM occurrences o
                      WHERE o.reminder_id = r.id AND o.sent = 0
                  )
                """,
                (to_db(cutoff_utc),),
            )
        ]
        if not ids:
            return 0
        placeholders = ",".join(["%s"] * len(ids))
        conn.execute(f"DELETE FROM occurrences WHERE reminder_id IN ({placeholders})", tuple(ids))
        conn.execute(f"DELETE FROM reminders WHERE id IN ({placeholders})", tuple(ids))
    return len(ids)


def get_due_recurring(conn: psycopg.Connection, now_utc: datetime) -> list[dict]:
    """Return active recurring reminders whose deadline has passed (need rolling forward).

    Joins the owner's timezone so the caller can recompute the next local deadline.
    """
    return conn.execute(
        """
        SELECT
            r.id         AS reminder_id,
            r.due_at_utc AS due_at_utc,
            r.anchor_day AS anchor_day,
            r.recurrence AS recurrence,
            u.timezone   AS timezone
        FROM reminders r
        JOIN users u ON u.chat_id = r.chat_id
        WHERE r.status = 'active'
          AND r.recurrence != 'none'
          AND r.due_at_utc <= %s
        ORDER BY r.due_at_utc ASC
        """,
        (to_db(now_utc),),
    ).fetchall()


def advance_recurring(
    conn: psycopg.Connection,
    reminder_id: int,
    next_due_utc: datetime,
    occurrences: list[tuple[str, datetime]],
) -> None:
    """Roll a recurring reminder to its next cycle: new deadline + fresh occurrence rows.

    Done in one transaction. Past (sent) occurrence rows are left in place; only the new
    cycle's pings are inserted (unsent), so :func:`get_pending_occurrences` reflects them.
    """
    with conn.transaction():
        conn.execute(
            "UPDATE reminders SET due_at_utc = %s WHERE id = %s",
            (to_db(next_due_utc), reminder_id),
        )
        _insert_occurrences(conn, reminder_id, occurrences)


# --- occurrences ---------------------------------------------------------------------

def get_pending_occurrences(conn: psycopg.Connection, reminder_id: int) -> list[dict]:
    """Return a reminder's not-yet-sent occurrences (upcoming pings), soonest first."""
    return conn.execute(
        """
        SELECT offset_label AS offset, fire_at_utc FROM occurrences
        WHERE reminder_id = %s AND sent = 0
        ORDER BY fire_at_utc ASC
        """,
        (reminder_id,),
    ).fetchall()


def get_due_occurrences(conn: psycopg.Connection, now_utc: datetime) -> list[dict]:
    """Return all unsent occurrences due at or before ``now_utc`` for active reminders.

    Joins through to the reminder text, owner ``chat_id``, and the user's timezone so the
    scheduler can render and send each ping. This single query across all users/reminders
    is what makes the scheduler reminder-agnostic and restart-safe.
    """
    return conn.execute(
        """
        SELECT
            o.id           AS occurrence_id,
            o.offset_label AS offset,
            o.fire_at_utc  AS fire_at_utc,
            r.id           AS reminder_id,
            r.text         AS text,
            r.due_at_utc   AS due_at_utc,
            r.recurrence   AS recurrence,
            r.chat_id      AS chat_id,
            u.timezone     AS timezone,
            u.language     AS language
        FROM occurrences o
        JOIN reminders r ON r.id = o.reminder_id
        JOIN users u     ON u.chat_id = r.chat_id
        WHERE o.sent = 0
          AND r.status = 'active'
          AND o.fire_at_utc <= %s
        ORDER BY o.fire_at_utc ASC
        """,
        (to_db(now_utc),),
    ).fetchall()


def mark_sent(conn: psycopg.Connection, occurrence_id: int) -> None:
    """Mark an occurrence as sent so it never fires again."""
    with conn.transaction():
        conn.execute("UPDATE occurrences SET sent = 1 WHERE id = %s", (occurrence_id,))


def _insert_occurrences(
    conn: psycopg.Connection, reminder_id: int, occurrences: list[tuple[str, datetime]]
) -> None:
    """Bulk-insert occurrence rows (caller owns the transaction)."""
    if not occurrences:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO occurrences (reminder_id, offset_label, fire_at_utc, sent)
            VALUES (%s, %s, %s, 0)
            """,
            [(reminder_id, label, to_db(fire_at)) for label, fire_at in occurrences],
        )
