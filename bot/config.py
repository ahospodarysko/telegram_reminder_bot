"""Runtime configuration: the bot token and the default timezone for new users.

Secrets are read only from the environment and never logged.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_token() -> str:
    """Return the BotFather token from ``BOT_TOKEN``.

    Raises:
        RuntimeError: if the variable is missing or empty. The token value itself is
            never included in the message, so it cannot leak into logs.
    """
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Put your BotFather token in the BOT_TOKEN "
            "environment variable (see .env.example)."
        )
    return token


def get_db_path() -> str:
    """Return the SQLite database path (``DB_PATH`` env or ``reminders.db``)."""
    return os.environ.get("DB_PATH", "reminders.db").strip() or "reminders.db"


def default_timezone() -> str:
    """Resolve the IANA timezone assigned to a new user on first ``/start``.

    Order of precedence:
        1. ``DEFAULT_TZ`` environment variable, if set.
        2. The host machine's timezone, derived from the ``/etc/localtime`` symlink
           (works on macOS and Linux).
        3. ``"UTC"`` as a last resort.

    A user can always override their own timezone later with ``/timezone``.
    """
    env_tz = os.environ.get("DEFAULT_TZ", "").strip()
    if env_tz:
        return env_tz

    host_tz = _host_timezone()
    if host_tz:
        return host_tz

    return "UTC"


def _host_timezone() -> str | None:
    """Best-effort IANA name of the host timezone, or ``None`` if undetermined.

    On macOS/Linux ``/etc/localtime`` is a symlink into the zoneinfo database, e.g.
    ``/var/db/timezone/zoneinfo/Europe/Kyiv`` or ``/usr/share/zoneinfo/Europe/Kyiv``.
    The IANA name is everything after the ``zoneinfo/`` segment.
    """
    localtime = Path("/etc/localtime")
    try:
        if not localtime.is_symlink():
            return None
        target = localtime.resolve()
    except OSError:
        return None

    parts = target.parts
    if "zoneinfo" in parts:
        idx = parts.index("zoneinfo")
        name = "/".join(parts[idx + 1 :])
        return name or None
    return None
