"""Localization: English (``en``) and Ukrainian (``uk``).

All user-facing strings live in :data:`TEXT`. Use :func:`t` to fetch a formatted
string for a language. Button label sets (:func:`all_labels`) let handlers match a
menu tap in any language, and :func:`format_when` renders dates with localized month
and weekday names.

Month-name *input* parsing (English + Ukrainian) is supported via :data:`MONTHS`, which
the parser in :mod:`bot.scheduling` consults regardless of the user's UI language — so a
user can type either language.
"""

from __future__ import annotations

from datetime import datetime

from .scheduling import SEPARATOR, utc_to_local

DEFAULT_LANG = "en"

# Short display labels shown on the picker buttons and in the "language set" message.
# Internal codes stay "en"/"uk" (the ISO codes Telegram sends and the DB stores).
LANGUAGES: dict[str, str] = {"en": "EN", "uk": "UA"}
LANGUAGE_FLAGS: dict[str, str] = {"en": "🇬🇧", "uk": "🇺🇦"}


def normalize_lang(code: str | None) -> str:
    """Return a supported language code, falling back to :data:`DEFAULT_LANG`."""
    if code and code in LANGUAGES:
        return code
    # Telegram client locales arrive like "uk", "en-US"; match on the prefix.
    if code:
        prefix = code.split("-", 1)[0].lower()
        if prefix in LANGUAGES:
            return prefix
    return DEFAULT_LANG


# --- the string tables ---------------------------------------------------------------

TEXT: dict[str, dict[str, str]] = {
    "en": {
        # input format
        "input_hint": f"note text {SEPARATOR} Month Day HH:MM",
        "input_example": f"Doctor appointment {SEPARATOR} June 21 16:00",
        # buttons — reply menu
        "btn_new": "➕ New reminder",
        "btn_list": "📋 My reminders",
        "btn_timezone": "🌍 Timezone",
        "btn_help": "❓ Help",
        # buttons — inline
        "btn_done": "✅ Done",
        "btn_cancel": "✖ Cancel",
        # language
        "choose_language": "🌐 Choose your language / Оберіть мову:",
        "language_set": "✅ Language set to *{name}*.",
        # start / help
        # Bot Description — shown on the empty-chat screen before the user taps Start.
        # Telegram serves this per the user's app language (set via set_my_description).
        "bot_description": (
            "👋 I send reminders before your deadlines — 24 hours and 2 hours ahead.\n\n"
            "Save a note with a date, and I'll ping you in time.\n\n"
            "Tap Start to begin."
        ),
        "greeting": (
            "👋 Welcome! I send reminders before your deadlines — 24h and 2h before.\n\n"
            "Your timezone is *{tz}*. Change it with /timezone, or your language with "
            "/language.\n\n"
            "Tap *{btn_new}* to create your first reminder."
        ),
        "help": (
            "🤖 *Reminder bot*\n\n"
            "Save a note with a deadline and I'll ping you *24h and 2h before* it.\n\n"
            "*Commands*\n"
            "• /remind — new reminder\n"
            "• /list — list active reminders (tap ✅ Done / ✖ Cancel on each)\n"
            "• /timezone `[IANA]` — view or set timezone\n"
            "• /language — change language\n\n"
            "*Create format:* `{hint}`\n"
            "_Example:_ `{example}`\n"
            "The year is assumed; month names work in English or Ukrainian."
        ),
        # new reminder
        "new_prompt": (
            "📝 Send your reminder in this format:\n`{hint}`\n\n_Example:_ `{example}`"
        ),
        "confirm_ok": (
            "✅ Got it: “{note}”\nDue: {due} ({tz})\nI'll remind you at: {pings}"
        ),
        "confirm_none": (
            "✅ Got it: “{note}”\nDue: {due} ({tz})\n"
            "⚠️ That time has already passed — no reminders scheduled."
        ),
        # list
        "list_header": "📋 You have {count} active reminder(s):",
        "list_empty": "You have no active reminders. Tap {btn} to make one.",
        "list_item": "🔔 *{text}*\n🗓 Due: {when}\n⏰ Reminders: {pings}",
        "list_no_pending": "all sent",
        "no_deadline_word": "no deadline",
        # timezone
        "tz_prompt": (
            "🌍 Your timezone is *{tz}*.\n\n"
            "To change it, send an IANA timezone name, e.g. `Europe/Kyiv`, "
            "`America/New_York`, or `Asia/Tokyo`."
        ),
        "tz_set": (
            "✅ Timezone set to *{tz}*. New reminders use this zone; existing ones keep "
            "their original times."
        ),
        "tz_invalid": "⚠️ {tz} isn't a valid IANA timezone. Try e.g. `Europe/Kyiv`.",
        # generic
        "not_recognized": (
            "I didn't recognise that. Tap a button below, or use /help.\n\n"
            "To add a reminder: tap {btn} or send `{hint}`."
        ),
        # callbacks
        "cb_done": "Marked done ✅",
        "cb_cancelled": "Cancelled ✖",
        "cb_gone": "That reminder no longer exists.",
        "cb_done_msg": "✅ Done: “{text}”",
        "cb_cancelled_msg": "✖ Cancelled: “{text}”",
        # pings
        "ping_due_now": "🔔 Reminder — “{text}” is due now.",
        "ping_due_before": "⏰ Reminder — “{text}” is coming up (due {due}).",
        # parse errors
        "err_missing_separator": (
            "Please use the format:\n{hint}\n"
            f"(separate the note and the date/time with a “{SEPARATOR}”)."
        ),
        "err_empty_note": f"The note text is empty. Put your note before the “{SEPARATOR}”.",
        "err_bad_datetime": (
            "I couldn't read the date/time. Use a month name, day, and 24-hour time, "
            "e.g. “{example}”."
        ),
    },
    "uk": {
        "input_hint": f"текст {SEPARATOR} День Місяць ГГ:ХХ",
        "input_example": f"Прийом у лікаря {SEPARATOR} 21 червня 16:00",
        "btn_new": "➕ Нове нагадування",
        "btn_list": "📋 Мої нагадування",
        "btn_timezone": "🌍 Часовий пояс",
        "btn_help": "❓ Допомога",
        "btn_done": "✅ Завершити",
        "btn_cancel": "✖ Скасувати",
        "choose_language": "🌐 Choose your language / Оберіть мову:",
        "language_set": "✅ Мову змінено на *{name}*.",
        "bot_description": (
            "👋 Я надсилаю нагадування перед вашими дедлайнами — за 24 години та за 2 "
            "години.\n\n"
            "Збережіть нотатку з датою — і я нагадаю вчасно.\n\n"
            "Натисніть Start, щоб почати."
        ),
        "greeting": (
            "👋 Вітаю! Я надсилаю нагадування перед дедлайнами — за 24 години та за 2 "
            "години.\n\n"
            "Ваш часовий пояс — *{tz}*. Змінити його можна командою /timezone, а мову — "
            "командою /language.\n\n"
            "Натисніть *{btn_new}*, щоб створити перше нагадування."
        ),
        "help": (
            "🤖 *Бот нагадувань*\n\n"
            "Збережіть нотатку з дедлайном, і я нагадаю *за 24 години та за 2 години* до "
            "нього.\n\n"
            "*Команди*\n"
            "• /remind — нове нагадування\n"
            "• /list — список активних нагадувань (✅ Завершити / ✖ Скасувати на кожному)\n"
            "• /timezone `[IANA]` — переглянути чи задати часовий пояс\n"
            "• /language — змінити мову\n\n"
            "*Формат створення:* `{hint}`\n"
            "_Приклад:_ `{example}`\n"
            "Рік підставляється автоматично; назви місяців — українською або англійською."
        ),
        "new_prompt": (
            "📝 Надішліть нагадування у такому форматі:\n`{hint}`\n\n_Приклад:_ `{example}`"
        ),
        "confirm_ok": (
            "✅ Прийнято: «{note}»\nДедлайн: {due} ({tz})\nНагадаю: {pings}"
        ),
        "confirm_none": (
            "✅ Прийнято: «{note}»\nДедлайн: {due} ({tz})\n"
            "⚠️ Цей час уже минув — нагадування не заплановані."
        ),
        "list_header": "📋 У вас активних нагадувань: {count}",
        "list_empty": "У вас немає активних нагадувань. Натисніть {btn}, щоб створити.",
        "list_item": "🔔 *{text}*\n🗓 Дедлайн: {when}\n⏰ Нагадування: {pings}",
        "list_no_pending": "усі надіслані",
        "no_deadline_word": "без дедлайну",
        "tz_prompt": (
            "🌍 Ваш часовий пояс — *{tz}*.\n\n"
            "Щоб змінити, надішліть назву часового поясу IANA, напр. `Europe/Kyiv`, "
            "`America/New_York` або `Asia/Tokyo`."
        ),
        "tz_set": (
            "✅ Часовий пояс змінено на *{tz}*. Нові нагадування використовують його; "
            "наявні зберігають свій час."
        ),
        "tz_invalid": "⚠️ {tz} — недійсний часовий пояс IANA. Спробуйте напр. `Europe/Kyiv`.",
        "not_recognized": (
            "Не зрозумів. Натисніть кнопку нижче або скористайтесь /help.\n\n"
            "Щоб додати нагадування: натисніть {btn} або надішліть `{hint}`."
        ),
        "cb_done": "Позначено ✅",
        "cb_cancelled": "Скасовано ✖",
        "cb_gone": "Цього нагадування більше не існує.",
        "cb_done_msg": "✅ Готово: «{text}»",
        "cb_cancelled_msg": "✖ Скасовано: «{text}»",
        "ping_due_now": "🔔 Нагадування — «{text}» час настав.",
        "ping_due_before": "⏰ Нагадування — «{text}» незабаром (дедлайн {due}).",
        "err_missing_separator": (
            "Будь ласка, використовуйте формат:\n{hint}\n"
            f"(розділіть текст і дату/час символом «{SEPARATOR}»)."
        ),
        "err_empty_note": f"Текст нагадування порожній. Напишіть його перед «{SEPARATOR}».",
        "err_bad_datetime": (
            "Не вдалося розпізнати дату/час. Вкажіть назву місяця, день і час у "
            "24-годинному форматі, напр. «{example}»."
        ),
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    """Return the localized, formatted string for ``key`` in ``lang``.

    Falls back to English for an unknown language or a key missing in a translation.
    """
    lang = normalize_lang(lang)
    template = TEXT[lang].get(key) or TEXT[DEFAULT_LANG][key]
    return template.format(**kwargs) if kwargs else template


def all_labels(key: str) -> list[str]:
    """Every language's label for a button ``key`` — for matching a menu tap."""
    return [TEXT[lang][key] for lang in LANGUAGES]


# --- localized date display ----------------------------------------------------------

_WEEKDAYS = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "uk": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"],
}
_MONTHS_SHORT = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "uk": ["січ", "лют", "бер", "кві", "тра", "чер",
           "лип", "сер", "вер", "жов", "лис", "гру"],
}


def format_when(dt_utc: datetime, tz_name: str, lang: str) -> str:
    """Format a UTC datetime in the user's timezone with localized names.

    e.g. ``Sat 21 Jun 16:00`` (en) / ``Сб 21 чер 16:00`` (uk).
    """
    lang = normalize_lang(lang)
    local = utc_to_local(dt_utc, tz_name)
    wd = _WEEKDAYS[lang][local.weekday()]
    mon = _MONTHS_SHORT[lang][local.month - 1]
    return f"{wd} {local.day:02d} {mon} {local:%H:%M}"
