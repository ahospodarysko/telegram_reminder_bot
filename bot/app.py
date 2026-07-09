"""Application assembly: build the bot, wire handlers, start the polling scheduler."""

from __future__ import annotations

import logging

from telegram.ext import Application

from . import db, i18n
from .config import get_db_path, get_token
from .handlers import register_handlers
from .scheduler import tick

# Tick once a minute — the spec's accepted granularity. ``first=1`` runs the first tick
# a second after startup so any reminders missed during an outage fire promptly.
TICK_INTERVAL_SECONDS = 60

logger = logging.getLogger(__name__)


async def _set_bot_description(application: Application) -> None:
    """Register the per-language "What can this bot do?" description on startup.

    The default (no ``language_code``) covers English and every other locale; Telegram
    serves the Ukrainian text automatically to users whose app language is Ukrainian.
    """
    bot = application.bot
    await bot.set_my_description(i18n.t(i18n.DEFAULT_LANG, "bot_description"))
    await bot.set_my_description(i18n.t("uk", "bot_description"), language_code="uk")


def build_application() -> Application:
    """Construct the configured Application (token from env, DB initialised, handlers wired)."""
    application = Application.builder().token(get_token()).post_init(_set_bot_description).build()

    conn = db.connect(get_db_path())
    db.init_db(conn)
    application.bot_data["db"] = conn

    register_handlers(application)
    application.job_queue.run_repeating(tick, interval=TICK_INTERVAL_SECONDS, first=1)
    return application


def main() -> None:
    """Run the bot via long-polling until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # httpx logs each request URL at INFO — and the Telegram API URL embeds the bot
    # token. Raise its level so the token never reaches the logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    application = build_application()
    logger.info("Starting reminder bot (long-polling, %ss tick)…", TICK_INTERVAL_SECONDS)
    application.run_polling(allowed_updates=["message", "callback_query"])
