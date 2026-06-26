"""SQLite storage layer — the source of truth for users, reminders, and pings.

All datetimes are stored as UTC strings (``YYYY-MM-DD HH:MM:SS``); that format sorts
lexicographically, so range queries on fire times work with plain string comparison.
Helpers convert to/from timezone-aware UTC ``datetime`` objects at the boundary.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

_DB_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id    INTEGER PRIMARY KEY,
    timezone   TEXT NOT NULL,
    language   TEXT NOT NULL DEFAULT 'en',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL REFERENCES users(chat_id),
    text       TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'timed',
    due_at_utc TEXT,
    status     TEXT NOT NULL DEFAULT 'active',
    recurrence TEXT NOT NULL DEFAULT 'none',
    anchor_day INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS occurrences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id INTEGER NOT NULL REFERENCES reminders(id),
    offset      TEXT NOT NULL,
    fire_at_utc TEXT NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_occurrences_due
    ON occurrences(sent, fire_at_utc);
"""


def to_db(dt: datetime) -> str:
    """Serialize a UTC datetime to the stored string form."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(_DB_DATETIME_FORMAT)


def from_db(value: str) -> datetime:
    """Parse a stored datetime string back to a timezone-aware UTC datetime."""
    return datetime.strptime(value, _DB_DATETIME_FORMAT).replace(tzinfo=timezone.utc)


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with row access by name and FK enforcement.

    ``check_same_thread=False`` is safe here: access is serialized through the bot's
    single asyncio event loop.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables/indexes if missing and apply lightweight column migrations."""
    with conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a DB may already have been created."""
    user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "language" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")

    reminder_columns = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)")}
    if "recurrence" not in reminder_columns:
        conn.execute("ALTER TABLE reminders ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'none'")
    if "anchor_day" not in reminder_columns:
        conn.execute("ALTER TABLE reminders ADD COLUMN anchor_day INTEGER")


# --- users ---------------------------------------------------------------------------

def upsert_user(
    conn: sqlite3.Connection, chat_id: int, tz_name: str, now_utc: datetime, language: str = "en"
) -> None:
    """Insert a user on first contact; leave an existing user's settings untouched."""
    with conn:
        conn.execute(
            """
            INSERT INTO users (chat_id, timezone, language, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO NOTHING
            """,
            (chat_id, tz_name, language, to_db(now_utc)),
        )


def get_user(conn: sqlite3.Connection, chat_id: int) -> sqlite3.Row | None:
    """Return the user row for ``chat_id`` or ``None``."""
    return conn.execute(
        "SELECT chat_id, timezone, language, created_at FROM users WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()


def set_timezone(conn: sqlite3.Connection, chat_id: int, tz_name: str) -> None:
    """Update a user's timezone (does not retroactively change stored UTC times)."""
    with conn:
        conn.execute(
            "UPDATE users SET timezone = ? WHERE chat_id = ?", (tz_name, chat_id)
        )


def set_language(conn: sqlite3.Connection, chat_id: int, language: str) -> None:
    """Update a user's UI language."""
    with conn:
        conn.execute(
            "UPDATE users SET language = ? WHERE chat_id = ?", (language, chat_id)
        )


# --- reminders -----------------------------------------------------------------------

def add_reminder(
    conn: sqlite3.Connection,
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

    ``recurrence`` is ``'none'`` (one-shot) or ``'monthly'``; ``anchor_day`` is the 1–31
    day-of-month to repeat on (``None`` for one-shot).

    Returns:
        The new reminder's id.
    """
    with conn:
        cur = conn.execute(
            """
            INSERT INTO reminders
                (chat_id, text, type, due_at_utc, status, recurrence, anchor_day, created_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (chat_id, text, type_, to_db(due_at_utc) if due_at_utc else None,
             recurrence, anchor_day, to_db(now_utc)),
        )
        reminder_id = int(cur.lastrowid)
        _insert_occurrences(conn, reminder_id, occurrences)
    return reminder_id


def get_active_reminders(conn: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """Return a user's active reminders, soonest deadline first."""
    return conn.execute(
        """
        SELECT id, chat_id, text, type, due_at_utc, status, recurrence, anchor_day, created_at
        FROM reminders
        WHERE chat_id = ? AND status = 'active'
        ORDER BY due_at_utc IS NULL, due_at_utc ASC
        """,
        (chat_id,),
    ).fetchall()


def get_reminder(conn: sqlite3.Connection, reminder_id: int) -> sqlite3.Row | None:
    """Return a single reminder row by id, or ``None``."""
    return conn.execute(
        """
        SELECT id, chat_id, text, type, due_at_utc, status, recurrence, anchor_day, created_at
        FROM reminders WHERE id = ?
        """,
        (reminder_id,),
    ).fetchone()


def set_status(conn: sqlite3.Connection, reminder_id: int, status: str) -> None:
    """Set a reminder's status (``active`` / ``done`` / ``cancelled``)."""
    with conn:
        conn.execute(
            "UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id)
        )


def get_due_recurring(conn: sqlite3.Connection, now_utc: datetime) -> list[sqlite3.Row]:
    """Return active recurring reminders whose deadline has passed (need rolling forward).

    Joins the owner's timezone so the caller can recompute the next local deadline.
    """
    return conn.execute(
        """
        SELECT
            r.id         AS reminder_id,
            r.due_at_utc AS due_at_utc,
            r.anchor_day AS anchor_day,
            u.timezone   AS timezone
        FROM reminders r
        JOIN users u ON u.chat_id = r.chat_id
        WHERE r.status = 'active'
          AND r.recurrence != 'none'
          AND r.due_at_utc <= ?
        ORDER BY r.due_at_utc ASC
        """,
        (to_db(now_utc),),
    ).fetchall()


def advance_recurring(
    conn: sqlite3.Connection,
    reminder_id: int,
    next_due_utc: datetime,
    occurrences: list[tuple[str, datetime]],
) -> None:
    """Roll a recurring reminder to its next cycle: new deadline + fresh occurrence rows.

    Done in one transaction. Past (sent) occurrence rows are left in place; only the new
    cycle's pings are inserted (unsent), so :func:`get_pending_occurrences` reflects them.
    """
    with conn:
        conn.execute(
            "UPDATE reminders SET due_at_utc = ? WHERE id = ?",
            (to_db(next_due_utc), reminder_id),
        )
        _insert_occurrences(conn, reminder_id, occurrences)


# --- occurrences ---------------------------------------------------------------------

def get_pending_occurrences(conn: sqlite3.Connection, reminder_id: int) -> list[sqlite3.Row]:
    """Return a reminder's not-yet-sent occurrences (upcoming pings), soonest first."""
    return conn.execute(
        """
        SELECT offset, fire_at_utc FROM occurrences
        WHERE reminder_id = ? AND sent = 0
        ORDER BY fire_at_utc ASC
        """,
        (reminder_id,),
    ).fetchall()


def get_due_occurrences(conn: sqlite3.Connection, now_utc: datetime) -> list[sqlite3.Row]:
    """Return all unsent occurrences due at or before ``now_utc`` for active reminders.

    Joins through to the reminder text, owner ``chat_id``, and the user's timezone so the
    scheduler can render and send each ping. This single query across all users/reminders
    is what makes the scheduler reminder-agnostic and restart-safe.
    """
    return conn.execute(
        """
        SELECT
            o.id          AS occurrence_id,
            o.offset      AS offset,
            o.fire_at_utc AS fire_at_utc,
            r.id          AS reminder_id,
            r.text        AS text,
            r.due_at_utc  AS due_at_utc,
            r.recurrence  AS recurrence,
            r.chat_id     AS chat_id,
            u.timezone    AS timezone,
            u.language    AS language
        FROM occurrences o
        JOIN reminders r ON r.id = o.reminder_id
        JOIN users u     ON u.chat_id = r.chat_id
        WHERE o.sent = 0
          AND r.status = 'active'
          AND o.fire_at_utc <= ?
        ORDER BY o.fire_at_utc ASC
        """,
        (to_db(now_utc),),
    ).fetchall()


def mark_sent(conn: sqlite3.Connection, occurrence_id: int) -> None:
    """Mark an occurrence as sent so it never fires again."""
    with conn:
        conn.execute("UPDATE occurrences SET sent = 1 WHERE id = ?", (occurrence_id,))


def _insert_occurrences(
    conn: sqlite3.Connection, reminder_id: int, occurrences: list[tuple[str, datetime]]
) -> None:
    """Bulk-insert occurrence rows (caller owns the transaction)."""
    conn.executemany(
        "INSERT INTO occurrences (reminder_id, offset, fire_at_utc, sent) VALUES (?, ?, ?, 0)",
        [(reminder_id, label, to_db(fire_at)) for label, fire_at in occurrences],
    )
