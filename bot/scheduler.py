"""The minute polling loop that fires due reminders.

SQLite is the source of truth: each tick queries all unsent occurrences whose time has
passed and sends them, marking each sent only after a successful send. This is what
makes the bot restart-safe — after an outage the first tick fires everything overdue
(late, never lost), and the ``sent`` flag prevents duplicates. Messages are localized
to each recipient's language.
"""

from __future__ import annotations

import logging

from telegram.error import Forbidden
from telegram.ext import ContextTypes

from . import db, i18n
from .scheduling import next_monthly_due, plan_occurrences, utcnow

logger = logging.getLogger(__name__)


def roll_recurring(
    conn, reminder_id: int, due_at_utc_str: str, anchor_day: int, tz_name: str, now_utc
):
    """Advance a due recurring reminder to its next cycle; return the new deadline (UTC).

    Computes the next monthly deadline (DST-correct, short-month clamped, catching up past
    several months if needed), plans that cycle's pings, and persists both atomically.
    """
    prev_due = db.from_db(due_at_utc_str)
    next_due = next_monthly_due(prev_due, anchor_day, tz_name, now_utc)
    occurrences = plan_occurrences(next_due, now_utc, tz_name)
    db.advance_recurring(conn, reminder_id, next_due, occurrences)
    return next_due


def _format_ping(row) -> str:
    """Build the localized message text for one due occurrence."""
    lang = i18n.normalize_lang(row["language"])
    # The at-deadline fallback ping (label "0") reads "due now"; advance pings "coming up".
    if row["offset"] == "0":
        return i18n.t(lang, "ping_due_now", text=row["text"])
    due_str = i18n.format_when(db.from_db(row["due_at_utc"]), row["timezone"], lang)
    return i18n.t(lang, "ping_due_before", text=row["text"], due=due_str)


async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue callback: send every due, unsent ping and mark it sent.

    Imports keyboards lazily to avoid a circular import with handlers at module load.
    """
    from .keyboards import reminder_actions

    conn = context.application.bot_data["db"]
    now = utcnow()
    due = db.get_due_occurrences(conn, now)
    for row in due:
        lang = i18n.normalize_lang(row["language"])
        recurring = row["recurrence"] != "none"
        try:
            await context.bot.send_message(
                chat_id=row["chat_id"],
                text=_format_ping(row),
                reply_markup=reminder_actions(row["reminder_id"], lang, recurring=recurring),
            )
        except Forbidden:
            # User blocked or deleted the chat — give up on this ping so it stops retrying.
            logger.warning("Chat %s blocked the bot; dropping ping %s",
                           row["chat_id"], row["occurrence_id"])
            db.mark_sent(conn, row["occurrence_id"])
        except Exception:  # noqa: BLE001 - transient send error; retry next tick.
            logger.exception("Failed to send occurrence %s; will retry", row["occurrence_id"])
        else:
            db.mark_sent(conn, row["occurrence_id"])

    # After sending due pings, roll any recurring reminder whose deadline has passed onto
    # its next cycle. Kept in the same tick so the whole mechanism is restart-safe.
    for rec in db.get_due_recurring(conn, now):
        try:
            roll_recurring(conn, rec["reminder_id"], rec["due_at_utc"],
                           rec["anchor_day"], rec["timezone"], now)
        except Exception:  # noqa: BLE001 - one bad reminder shouldn't stop the rest.
            logger.exception("Failed to roll recurring reminder %s", rec["reminder_id"])
