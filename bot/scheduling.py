"""Pure time logic for the reminder bot — no Telegram or database imports.

Everything here is deterministic and unit-testable. The rest of the app stores all
datetimes in UTC and only converts to a user's timezone for display, using the helpers
below.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Ping offsets before the deadline. Order is the order in which the pings fire and are
# displayed. There is no at-due ping — a reminder notifies 24h and 2h ahead only.
OFFSETS: list[tuple[str, timedelta]] = [
    ("-24h", timedelta(hours=24)),
    ("-2h", timedelta(hours=2)),
]

# Input format for v1 reminder creation: "note text @ Month Day HH:MM" (24-hour time).
# The year is omitted — it defaults to the current year, rolling to next year if that
# date/time has already passed (see parse_reminder_input). The separator is matched on
# its LAST occurrence, so a note that happens to contain it still parses correctly — the
# trailing date/time never contains the separator.
SEPARATOR = "@"

# Month names accepted in input, mapped (lowercased) to month number. Covers English
# full + abbreviated, and Ukrainian nominative + genitive (the genitive form is what
# Ukrainian dates use, e.g. "21 червня"). The parser tries all of these regardless of
# the user's UI language, so either language can be typed.
_EN_FULL = ["january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december"]
_EN_ABBR = ["jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec"]
_UK_NOMINATIVE = ["січень", "лютий", "березень", "квітень", "травень", "червень",
                  "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"]
_UK_GENITIVE = ["січня", "лютого", "березня", "квітня", "травня", "червня",
                "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
MONTHS: dict[str, int] = {
    name: i
    for names in (_EN_FULL, _EN_ABBR, _UK_NOMINATIVE, _UK_GENITIVE)
    for i, name in enumerate(names, start=1)
}

_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# Recurrence keywords accepted on the date side of the input (after the separator). All
# map to 'monthly' in v1 — the schema/code allow weekly/yearly later (see the plan).
# Multi-word phrases are listed so a prefix match strips the whole phrase; matching is
# case-insensitive and language-agnostic (EN + UK), like MONTHS.
_RECURRENCE_KEYWORDS: list[tuple[str, str]] = [
    ("every month", "monthly"),
    ("кожного місяця", "monthly"),
    ("monthly", "monthly"),
    ("щомісяця", "monthly"),
]


class ParseError(ValueError):
    """A user-input parse failure carrying a translation ``code`` (see bot.i18n).

    The handler maps ``code`` to a localized message, so no English text lives here.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime, truncated to whole minutes.

    Minute granularity matches the scheduler's one-minute tick and keeps stored fire
    times tidy.
    """
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def get_zone(tz_name: str) -> ZoneInfo:
    """Return a ``ZoneInfo`` for ``tz_name`` or raise ``ValueError`` if invalid."""
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"Unknown timezone: {tz_name!r}") from exc


def is_valid_timezone(tz_name: str) -> bool:
    """True if ``tz_name`` is a resolvable IANA timezone."""
    try:
        get_zone(tz_name)
        return True
    except ValueError:
        return False


def local_to_utc(naive_local: datetime, tz_name: str) -> datetime:
    """Interpret a naive wall-clock datetime as being in ``tz_name`` and convert to UTC.

    Args:
        naive_local: a datetime with ``tzinfo is None`` (wall-clock time the user typed).
        tz_name: IANA timezone the wall-clock time belongs to.

    Returns:
        A timezone-aware UTC datetime.
    """
    if naive_local.tzinfo is not None:
        raise ValueError("local_to_utc expects a naive (tz-less) datetime")
    aware_local = naive_local.replace(tzinfo=get_zone(tz_name))
    return aware_local.astimezone(timezone.utc)


def utc_to_local(dt_utc: datetime, tz_name: str) -> datetime:
    """Convert a UTC datetime to a timezone-aware datetime in ``tz_name``."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(get_zone(tz_name))


def compute_occurrences(
    due_at_utc: datetime, now_utc: datetime
) -> list[tuple[str, datetime]]:
    """Compute the future ping occurrences for a deadline.

    For each offset the fire time is ``due_at_utc - offset``. Offsets whose fire time
    is already in the past (``<= now_utc``) are skipped, so a reminder created close to
    its deadline only schedules the pings still ahead — including the at-due ping if the
    deadline itself is still in the future.

    Args:
        due_at_utc: deadline, timezone-aware UTC.
        now_utc: current time, timezone-aware UTC.

    Returns:
        ``(offset_label, fire_at_utc)`` pairs in chronological order. May be empty if
        the deadline has already passed.
    """
    occurrences: list[tuple[str, datetime]] = []
    for label, delta in OFFSETS:
        fire_at = due_at_utc - delta
        if fire_at > now_utc:
            occurrences.append((label, fire_at))
    return occurrences


# Quiet hours: no ping fires between QUIET_START (inclusive) and QUIET_END (exclusive),
# measured in the user's local time. Anything landing in the window is pushed to
# QUIET_END that morning.
QUIET_START = 22  # 22:00
QUIET_END = 8     # 08:00


def shift_out_of_quiet_hours(fire_at_utc: datetime, tz_name: str) -> datetime:
    """Move a fire time out of the user's 22:00–08:00 quiet window, to 08:00 local.

    A time at/after 22:00 moves to 08:00 the next morning; a time before 08:00 moves to
    08:00 the same morning. Times already in the allowed window are returned unchanged.
    """
    local = utc_to_local(fire_at_utc, tz_name)
    if local.hour >= QUIET_START:
        target = (local + timedelta(days=1)).replace(
            hour=QUIET_END, minute=0, second=0, microsecond=0
        )
    elif local.hour < QUIET_END:
        target = local.replace(hour=QUIET_END, minute=0, second=0, microsecond=0)
    else:
        return fire_at_utc
    return target.astimezone(timezone.utc)


def plan_occurrences(
    due_at_utc: datetime, now_utc: datetime, tz_name: str
) -> list[tuple[str, datetime]]:
    """Compute future pings, honoring quiet hours and de-duplicating collisions.

    Like :func:`compute_occurrences`, but each fire time is first shifted out of the
    user's quiet hours (see :func:`shift_out_of_quiet_hours`). Two offsets that land in
    the same night collapse to a single 08:00 ping; past pings are dropped. Results are
    sorted by fire time.

    Fallback: if a reminder is created so close to the deadline that every offset ping is
    already in the past, a single at-deadline ping (label ``"0"``) is scheduled instead
    (also quiet-hours adjusted), so a "too close" reminder still notifies. If even the
    deadline has passed, the result is empty.

    Returns:
        ``(offset_label, fire_at_utc)`` pairs, unique by fire time, soonest first.
    """
    seen: set[datetime] = set()
    planned: list[tuple[str, datetime]] = []
    for label, delta in OFFSETS:
        fire_at = shift_out_of_quiet_hours(due_at_utc - delta, tz_name)
        if fire_at <= now_utc or fire_at in seen:
            continue
        seen.add(fire_at)
        planned.append((label, fire_at))

    if not planned:
        fallback = shift_out_of_quiet_hours(due_at_utc, tz_name)
        if fallback > now_utc:
            planned.append(("0", fallback))

    planned.sort(key=lambda pair: pair[1])
    return planned


class ParsedReminder(NamedTuple):
    """Result of :func:`parse_reminder_input`.

    ``when`` is the first deadline as naive wall-clock time in the user's timezone (the
    caller converts it to UTC). For one-shot reminders ``recurrence`` is ``'none'`` and
    ``anchor_day`` is ``None``; for monthly ones ``recurrence`` is ``'monthly'`` and
    ``anchor_day`` is the original 1–31 day-of-month to repeat on.
    """

    note: str
    when: datetime
    recurrence: str
    anchor_day: int | None


def parse_reminder_input(
    text: str, now_local: datetime, force_recurrence: str | None = None
) -> ParsedReminder:
    """Parse a reminder input into a :class:`ParsedReminder`.

    Two shapes are accepted on the date side (after the *last* :data:`SEPARATOR`, so a
    note containing the separator still parses):

    - One-shot: ``"note @ Month Day HH:MM"``. The year is not typed — it defaults to
      ``now_local``'s year and rolls to next year if that date/time has already passed.
    - Recurring monthly: ``"note @ monthly Day HH:MM"`` (or ``every month`` / Ukrainian
      ``щомісяця`` / ``кожного місяця``). The **month name is omitted**; only day-of-month
      and time are given. The first deadline is that day/time this month if still ahead,
      otherwise next month (day clamped to the month's length).

    ``force_recurrence`` pins the type instead of auto-detecting it from a keyword: the
    type-picker flow passes ``'monthly'`` (parse day + time, keyword optional) or
    ``'none'`` (parse as one-shot). Left ``None`` (e.g. ``/remind``), the keyword decides.

    Args:
        text: the raw user input.
        now_local: current time in the user's timezone, naive (``tzinfo is None``).
        force_recurrence: ``'monthly'`` / ``'none'`` to pin the type, or ``None`` to detect.

    Raises:
        ParseError: with a ``.code`` (``missing_separator`` / ``empty_note`` /
            ``bad_datetime`` / ``bad_recurrence``) the caller translates.
    """
    note_part, sep, datetime_part = text.rpartition(SEPARATOR)
    if not sep:
        raise ParseError("missing_separator")
    note = note_part.strip()
    when = datetime_part.strip()
    if not note:
        raise ParseError("empty_note")

    if force_recurrence == "monthly":
        # Type already chosen — strip the keyword if the user typed one anyway.
        recurrence, remainder = "monthly", _match_recurrence(when)[1]
    elif force_recurrence == "none":
        recurrence, remainder = "none", when
    else:
        recurrence, remainder = _match_recurrence(when)

    if recurrence != "none":
        day, hour, minute = _parse_day_time(remainder)
        first_due = _build_first_monthly(now_local, day, hour, minute)
        return ParsedReminder(note, first_due, recurrence, day)

    month, day, hour, minute = _parse_when_parts(when)
    parsed = _build(now_local.year, month, day, hour, minute)
    if parsed < now_local:
        # The date has already passed this year — assume the user means next year.
        parsed = _build(now_local.year + 1, month, day, hour, minute)
    return ParsedReminder(note, parsed, "none", None)


def _match_recurrence(when: str) -> tuple[str, str]:
    """Detect a leading recurrence keyword. Returns ``(kind, remainder_after_keyword)``.

    ``kind`` is ``'none'`` (and ``remainder`` is ``when`` unchanged) when no keyword leads.
    """
    lowered = when.lower()
    for phrase, kind in _RECURRENCE_KEYWORDS:
        if lowered == phrase or lowered.startswith(phrase + " "):
            return kind, when[len(phrase):].strip()
    return "none", when


def _parse_day_time(when: str) -> tuple[int, int, int]:
    """Extract ``(day, hour, minute)`` from a recurring date side (no month name).

    Raises:
        ParseError("bad_recurrence"): if the time or a 1–31 day is missing/invalid.
    """
    time_match = _TIME_RE.search(when)
    if not time_match:
        raise ParseError("bad_recurrence")
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    if hour > 23 or minute > 59:
        raise ParseError("bad_recurrence")

    rest = (when[: time_match.start()] + " " + when[time_match.end() :]).split()
    day = None
    for token in rest:
        token = token.strip(".,").lower()
        if token.isdigit() and day is None:
            day = int(token)
    if day is None or not 1 <= day <= 31:
        raise ParseError("bad_recurrence")
    return day, hour, minute


def _clamped_date(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build a naive datetime, clamping ``day`` to the month's last day (handles 29–31).

    Day 31 → 28/29 Feb, 30 Apr, etc.; days that exist in the month are preserved. This is
    the short-month rule (plan §3.2): a monthly reminder still fires every month.
    """
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, min(day, last_day), hour, minute)


def _next_month(year: int, month: int) -> tuple[int, int]:
    """The (year, month) one calendar month after the given one."""
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _build_first_monthly(now_local: datetime, day: int, hour: int, minute: int) -> datetime:
    """First deadline for a monthly reminder: this month if still ahead, else next month."""
    candidate = _clamped_date(now_local.year, now_local.month, day, hour, minute)
    if candidate < now_local:
        year, month = _next_month(now_local.year, now_local.month)
        candidate = _clamped_date(year, month, day, hour, minute)
    return candidate


def next_monthly_due(
    prev_due_utc: datetime, anchor_day: int, tz_name: str, now_utc: datetime
) -> datetime:
    """Compute the next monthly deadline strictly after ``now_utc``.

    Advances month-by-month from ``prev_due_utc`` (catch-up after downtime, plan §3.4),
    rebuilding the deadline in the user's *local* time each step so the wall-clock time
    is DST-stable, and clamping ``anchor_day`` to each month's length (plan §3.2).

    Args:
        prev_due_utc: the current/just-passed deadline, timezone-aware UTC.
        anchor_day: the original day-of-month (1–31) to repeat on.
        tz_name: the user's IANA timezone.
        now_utc: current time, timezone-aware UTC.

    Returns:
        The next deadline as timezone-aware UTC.
    """
    local_prev = utc_to_local(prev_due_utc, tz_name)
    hour, minute = local_prev.hour, local_prev.minute
    year, month = local_prev.year, local_prev.month
    while True:
        year, month = _next_month(year, month)
        naive = _clamped_date(year, month, anchor_day, hour, minute)
        due_utc = local_to_utc(naive, tz_name)
        if due_utc > now_utc:
            return due_utc


def _parse_when_parts(when: str) -> tuple[int, int, int, int]:
    """Extract ``(month, day, hour, minute)`` from a "Month Day HH:MM" string.

    Language- and order-agnostic: finds the ``HH:MM`` token, a numeric day token, and a
    month-name token (English or Ukrainian) in any order. Does not validate the day
    against a month/year — :func:`_build` does that once the year is known.

    Raises:
        ParseError("bad_datetime"): if any part is missing or out of range.
    """
    time_match = _TIME_RE.search(when)
    if not time_match:
        raise ParseError("bad_datetime")
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    if hour > 23 or minute > 59:
        raise ParseError("bad_datetime")

    rest = (when[: time_match.start()] + " " + when[time_match.end() :]).split()
    month = day = None
    for token in rest:
        token = token.strip(".,").lower()
        if not token:
            continue
        if token.isdigit():
            if day is None:
                day = int(token)
        elif token in MONTHS:
            month = MONTHS[token]
    if month is None or day is None:
        raise ParseError("bad_datetime")
    return month, day, hour, minute


def _build(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Construct a datetime, raising ``ParseError("bad_datetime")`` if it's invalid."""
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        raise ParseError("bad_datetime") from None
