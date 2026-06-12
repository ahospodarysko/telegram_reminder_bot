"""One-time (re-runnable) bot configuration via the Telegram Bot API.

Applies the command menu, menu button, display name, and descriptions as
configuration-as-code. Every call is a set-operation, so this is safe to run again
whenever a setting changes. Reads ``BOT_TOKEN`` from the environment; never prints it.

Usage:
    python setup_bot.py
"""

from __future__ import annotations

import asyncio

from telegram import BotCommand, MenuButtonCommands
from telegram.error import TelegramError

from bot.config import get_token

# The tappable command menu (shown next to the input field), per language. Telegram
# shows the set matching the user's client language, falling back to the default (en).
COMMANDS: list[BotCommand] = [
    BotCommand("start", "Register and show the menu"),
    BotCommand("remind", "Create a new reminder"),
    BotCommand("list", "List active reminders"),
    BotCommand("timezone", "View or set your timezone"),
    BotCommand("language", "Change language"),
    BotCommand("help", "How to use the bot"),
]

COMMANDS_UK: list[BotCommand] = [
    BotCommand("start", "Реєстрація та головне меню"),
    BotCommand("remind", "Створити нагадування"),
    BotCommand("list", "Список активних нагадувань"),
    BotCommand("timezone", "Переглянути чи задати часовий пояс"),
    BotCommand("language", "Змінити мову"),
    BotCommand("help", "Як користуватися ботом"),
]

BOT_NAME = "Reminder Bot"
SHORT_DESCRIPTION = "Saves your notes and reminds you before the deadline."
DESCRIPTION = (
    "I send reminders before your deadlines — 24h and 2h before. Tap START to begin, "
    "then add a reminder with a date and time."
)


async def configure() -> None:
    """Apply all settings, using getMe as a token sanity check."""
    from telegram import Bot

    bot = Bot(token=get_token())
    async with bot:
        me = await bot.get_me()
        print(f"✓ Token valid — connected as @{me.username} ({me.first_name})")

        await bot.set_my_commands(COMMANDS)
        await bot.set_my_commands(COMMANDS_UK, language_code="uk")
        print(f"✓ Set {len(COMMANDS)} commands (en + uk)")

        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        print("✓ Set menu button to the command list")

        await bot.set_my_name(BOT_NAME)
        print(f"✓ Set name: {BOT_NAME}")

        await bot.set_my_description(DESCRIPTION)
        print("✓ Set description")

        await bot.set_my_short_description(SHORT_DESCRIPTION)
        print("✓ Set short description")

    print("\nDone. Configuration is idempotent — re-run anytime settings change.")


def main() -> None:
    try:
        asyncio.run(configure())
    except TelegramError as exc:
        raise SystemExit(f"Telegram API error: {exc}") from exc


if __name__ == "__main__":
    main()
