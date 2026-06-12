"""Telegram update handlers: commands, menu buttons, free text, and inline callbacks.

All user-facing text is localized through :mod:`bot.i18n` using each user's stored
language. Reminder creation and timezone changes are short two-step flows tracked with
per-user flags in ``context.user_data`` (``awaiting_reminder`` / ``awaiting_timezone``)
rather than a ConversationHandler. Menu-button handlers are registered before the
free-text catch-all, so tapping a button always wins over an in-progress flow.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import db, i18n, keyboards
from .config import default_timezone
from .scheduling import (
    ParseError,
    is_valid_timezone,
    local_to_utc,
    parse_reminder_input,
    plan_occurrences,
    utc_to_local,
    utcnow,
)

logger = logging.getLogger(__name__)


def _conn(context: ContextTypes.DEFAULT_TYPE):
    """The shared SQLite connection stored on the application."""
    return context.application.bot_data["db"]


def _user(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Return the user row (or None)."""
    return db.get_user(_conn(context), chat_id)


def _user_tz(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    """Return the user's stored timezone, falling back to the default."""
    user = _user(context, chat_id)
    return user["timezone"] if user else default_timezone()


def _user_lang(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    """Return the user's stored UI language, normalized."""
    user = _user(context, chat_id)
    return i18n.normalize_lang(user["language"] if user else None)


def _confirmation(lang: str, tz: str, note: str, due_at_utc, occurrences) -> str:
    """Build the localized confirmation echo for a created reminder."""
    due = i18n.format_when(due_at_utc, tz, lang)
    if occurrences:
        pings = ", ".join(i18n.format_when(fire, tz, lang) for _, fire in occurrences)
        return i18n.t(lang, "confirm_ok", note=note, due=due, tz=tz, pings=pings)
    return i18n.t(lang, "confirm_none", note=note, due=due, tz=tz)


def _format_hint(lang: str) -> dict[str, str]:
    """The input hint + example for a language (passed to error/prompt templates)."""
    return {"hint": i18n.t(lang, "input_hint"), "example": i18n.t(lang, "input_example")}


# --- /start + language ---------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture chat_id on first contact, seed defaults, and show the language picker."""
    chat_id = update.effective_chat.id
    seed_lang = i18n.normalize_lang(getattr(update.effective_user, "language_code", None))
    db.upsert_user(_conn(context), chat_id, default_timezone(), utcnow(), seed_lang)
    await update.message.reply_text(
        i18n.t("en", "choose_language"), reply_markup=keyboards.language_picker()
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The /language command: re-show the language picker."""
    await update.message.reply_text(
        i18n.t(_user_lang(context, update.effective_chat.id), "choose_language"),
        reply_markup=keyboards.language_picker(),
    )


async def _choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> None:
    """Apply a language pick, then greet and (re)show the main menu in that language."""
    query = update.callback_query
    chat_id = query.message.chat.id
    db.set_language(_conn(context), chat_id, lang)
    await query.answer()
    await query.edit_message_text(
        i18n.t(lang, "language_set", name=i18n.LANGUAGES[lang]), parse_mode=ParseMode.MARKDOWN
    )
    tz_name = _user_tz(context, chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=i18n.t(lang, "greeting", tz=tz_name, btn_new=i18n.t(lang, "btn_new")),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboards.main_menu(lang),
    )


# --- new reminder flow ---------------------------------------------------------------

def _begin_new_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    """Mark that the next text message is a reminder; return the localized prompt text."""
    context.user_data["awaiting_reminder"] = True
    context.user_data.pop("awaiting_timezone", None)
    lang = _user_lang(context, chat_id)
    return i18n.t(lang, "new_prompt", **_format_hint(lang))


async def new_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt for reminder input (via /remind or the menu button)."""
    prompt = _begin_new_reminder(context, update.effective_chat.id)
    await update.message.reply_text(prompt, parse_mode=ParseMode.MARKDOWN)


async def _create_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Parse the strict-format input, store the reminder, and echo the schedule."""
    chat_id = update.effective_chat.id
    conn = _conn(context)
    tz_name = _user_tz(context, chat_id)
    lang = _user_lang(context, chat_id)
    now = utcnow()
    now_local = utc_to_local(now, tz_name).replace(tzinfo=None)
    try:
        note, naive_local = parse_reminder_input(text, now_local)
        due_at_utc = local_to_utc(naive_local, tz_name)
    except ParseError as exc:
        # Keep awaiting_reminder set so the user can simply retry.
        await update.message.reply_text(
            i18n.t(lang, f"err_{exc.code}", **_format_hint(lang)), parse_mode=ParseMode.MARKDOWN
        )
        return

    occurrences = plan_occurrences(due_at_utc, now, tz_name)
    db.add_reminder(conn, chat_id, note, due_at_utc, occurrences, now)
    context.user_data.pop("awaiting_reminder", None)
    # Only a "New reminder" shortcut on the echo — no Done/Cancel (those read like a
    # "save" button). Done/Cancel live in /list and on the ping notifications.
    await update.message.reply_text(
        _confirmation(lang, tz_name, note, due_at_utc, occurrences),
        reply_markup=keyboards.new_reminder_button(lang),
    )


# --- /list ---------------------------------------------------------------------------

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show each active reminder as its own message with inline action buttons."""
    chat_id = update.effective_chat.id
    conn = _conn(context)
    tz_name = _user_tz(context, chat_id)
    lang = _user_lang(context, chat_id)
    reminders = db.get_active_reminders(conn, chat_id)
    if not reminders:
        await update.message.reply_text(
            i18n.t(lang, "list_empty", btn=i18n.t(lang, "btn_new"))
        )
        return
    await update.message.reply_text(i18n.t(lang, "list_header", count=len(reminders)))
    for r in reminders:
        due = db.from_db(r["due_at_utc"]) if r["due_at_utc"] else None
        when = i18n.format_when(due, tz_name, lang) if due else i18n.t(lang, "no_deadline_word")
        pending = db.get_pending_occurrences(conn, r["id"])
        pings = (
            ", ".join(i18n.format_when(db.from_db(o["fire_at_utc"]), tz_name, lang) for o in pending)
            if pending else i18n.t(lang, "list_no_pending")
        )
        await update.message.reply_text(
            i18n.t(lang, "list_item", text=r["text"], when=when, pings=pings),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboards.reminder_actions(r["id"], lang),
        )


# --- /timezone -----------------------------------------------------------------------

async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/timezone`` shows the current zone (and prompts); ``/timezone <IANA>`` sets it."""
    if context.args:
        await _set_timezone(update, context, " ".join(context.args).strip())
        return
    await _prompt_timezone(update, context)


async def timezone_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Timezone menu button: show current zone and await a new one."""
    await _prompt_timezone(update, context)


async def _prompt_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    lang = _user_lang(context, chat_id)
    context.user_data["awaiting_timezone"] = True
    context.user_data.pop("awaiting_reminder", None)
    await update.message.reply_text(
        i18n.t(lang, "tz_prompt", tz=_user_tz(context, chat_id)), parse_mode=ParseMode.MARKDOWN
    )


async def _set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE, tz_name: str) -> None:
    lang = _user_lang(context, update.effective_chat.id)
    if not is_valid_timezone(tz_name):
        await update.message.reply_text(
            i18n.t(lang, "tz_invalid", tz=tz_name), parse_mode=ParseMode.MARKDOWN
        )
        return
    db.set_timezone(_conn(context), update.effective_chat.id, tz_name)
    context.user_data.pop("awaiting_timezone", None)
    await update.message.reply_text(
        i18n.t(lang, "tz_set", tz=tz_name), parse_mode=ParseMode.MARKDOWN
    )


# --- /help ---------------------------------------------------------------------------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = _user_lang(context, update.effective_chat.id)
    await update.message.reply_text(
        i18n.t(lang, "help", **_format_hint(lang)), parse_mode=ParseMode.MARKDOWN
    )


# --- free-text catch-all -------------------------------------------------------------

async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route a plain text message based on which flow (if any) the user is in."""
    text = update.message.text or ""
    if context.user_data.get("awaiting_timezone"):
        await _set_timezone(update, context, text.strip())
    elif context.user_data.get("awaiting_reminder"):
        await _create_reminder(update, context, text)
    else:
        lang = _user_lang(context, update.effective_chat.id)
        await update.message.reply_text(
            i18n.t(lang, "not_recognized", btn=i18n.t(lang, "btn_new"),
                   hint=i18n.t(lang, "input_hint")),
            parse_mode=ParseMode.MARKDOWN,
        )


# --- inline button callbacks ---------------------------------------------------------

def _owned_reminder(context: ContextTypes.DEFAULT_TYPE, reminder_id: int, chat_id: int):
    """Return the reminder row if it exists and belongs to ``chat_id``, else ``None``."""
    row = db.get_reminder(_conn(context), reminder_id)
    if row is None or row["chat_id"] != chat_id:
        return None
    return row


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline taps: language pick, New reminder, and Done / Cancel on a reminder."""
    query = update.callback_query
    parts = query.data.split(":")
    action = parts[0]
    chat_id = query.message.chat.id

    if action == "lang":
        await _choose_language(update, context, i18n.normalize_lang(parts[1]))
        return

    if action == "new":
        prompt = _begin_new_reminder(context, chat_id)
        await query.answer()
        await context.bot.send_message(chat_id=chat_id, text=prompt, parse_mode=ParseMode.MARKDOWN)
        return

    lang = _user_lang(context, chat_id)
    reminder_id = int(parts[1])
    row = _owned_reminder(context, reminder_id, chat_id)
    if row is None:
        await query.answer(i18n.t(lang, "cb_gone"), show_alert=True)
        return

    if action == "done":
        db.set_status(_conn(context), reminder_id, "done")
        await query.answer(i18n.t(lang, "cb_done"))
        await query.edit_message_text(i18n.t(lang, "cb_done_msg", text=row["text"]))
    elif action == "cancel":
        db.set_status(_conn(context), reminder_id, "cancelled")
        await query.answer(i18n.t(lang, "cb_cancelled"))
        await query.edit_message_text(i18n.t(lang, "cb_cancelled_msg", text=row["text"]))
    else:
        await query.answer()


# --- registration --------------------------------------------------------------------

def register_handlers(application: Application) -> None:
    """Wire all handlers onto the application in priority order.

    Command and menu-button handlers come before the free-text catch-all so buttons and
    slash commands always take precedence over an in-progress create/timezone flow.
    Menu buttons are matched across every language's label set.
    """
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("remind", new_reminder_start))
    application.add_handler(CommandHandler("list", list_reminders))
    application.add_handler(CommandHandler("timezone", timezone_command))
    application.add_handler(CommandHandler("language", language_command))
    application.add_handler(CommandHandler("help", help_command))

    # Menu buttons send their (localized) label as text — match any language, before the
    # free-text catch-all.
    application.add_handler(MessageHandler(filters.Text(i18n.all_labels("btn_new")), new_reminder_start))
    application.add_handler(MessageHandler(filters.Text(i18n.all_labels("btn_list")), list_reminders))
    application.add_handler(MessageHandler(filters.Text(i18n.all_labels("btn_timezone")), timezone_button))
    application.add_handler(MessageHandler(filters.Text(i18n.all_labels("btn_help")), help_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
    application.add_handler(CallbackQueryHandler(on_callback))
