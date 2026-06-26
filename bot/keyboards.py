"""Reply and inline keyboard builders, localized per user language.

Reply-keyboard buttons send their (localized) label text as a normal message; handlers
match on the set of labels across all languages via :func:`bot.i18n.all_labels`. Inline
buttons carry ``callback_data`` of the form ``action:id`` or ``lang:code``.
"""

from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from . import i18n


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    """The persistent two-row main menu in the user's language."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(i18n.t(lang, "btn_new")), KeyboardButton(i18n.t(lang, "btn_list"))],
         [KeyboardButton(i18n.t(lang, "btn_timezone")), KeyboardButton(i18n.t(lang, "btn_help"))]],
        resize_keyboard=True,
        is_persistent=True,
    )


def reminder_actions(reminder_id: int, lang: str, recurring: bool = False) -> InlineKeyboardMarkup:
    """Inline action buttons under a reminder.

    One-shot: Done / Cancel. Recurring: the labels become "Done (this cycle)" — which
    rolls the series forward — and "Stop repeating", which ends it. The ``callback_data``
    actions stay ``done`` / ``cancel``; the handler branches on the reminder's recurrence.
    """
    done_key = "btn_done_cycle" if recurring else "btn_done"
    cancel_key = "btn_stop_repeating" if recurring else "btn_cancel"
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(i18n.t(lang, done_key), callback_data=f"done:{reminder_id}"),
            InlineKeyboardButton(i18n.t(lang, cancel_key), callback_data=f"cancel:{reminder_id}"),
        ]]
    )


def reminder_cancel_action(reminder_id: int, lang: str) -> InlineKeyboardMarkup:
    """A single Cancel button — used in /list for both one-shot and recurring reminders."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(i18n.t(lang, "btn_cancel"), callback_data=f"cancel:{reminder_id}")]]
    )


def reminder_type_picker(lang: str) -> InlineKeyboardMarkup:
    """Inline buttons to choose a reminder type (callback ``newtype:monthly|basic``)."""
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(i18n.t(lang, "btn_type_monthly"), callback_data="newtype:monthly"),
            InlineKeyboardButton(i18n.t(lang, "btn_type_basic"), callback_data="newtype:basic"),
        ]]
    )


def new_reminder_button(lang: str) -> InlineKeyboardMarkup:
    """A single inline '➕ New reminder' button (callback ``new``) for the confirmation."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(i18n.t(lang, "btn_new"), callback_data="new")]]
    )


def language_picker() -> InlineKeyboardMarkup:
    """Inline buttons to choose a UI language (shown with native names + flags)."""
    row = [
        InlineKeyboardButton(f"{i18n.LANGUAGE_FLAGS[code]} {name}", callback_data=f"lang:{code}")
        for code, name in i18n.LANGUAGES.items()
    ]
    return InlineKeyboardMarkup([row])
