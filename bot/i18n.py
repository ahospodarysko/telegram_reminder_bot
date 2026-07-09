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
        "input_hint_monthly": f"note text {SEPARATOR} Day",
        "input_example_monthly": f"Pay rent {SEPARATOR} 5",
        # buttons — reply menu
        "btn_new": "➕ New reminder",
        "btn_list": "📋 My reminders",
        "btn_timezone": "🌍 Timezone",
        "btn_help": "❓ Help",
        # buttons — inline
        "btn_done": "✅ Done",
        "btn_cancel": "✖ Close",
        "btn_stop_repeating": "🛑 Stop repeating",
        "btn_type_monthly": "🔁 Monthly",
        "btn_type_basic": "🔔 Basic",
        "btn_type_note": "📝 Note (every 2h)",
        # language
        "choose_language": "🌐 Choose your language / Оберіть мову:",
        "language_set": "✅ Language set to *{name}*.",
        # start / help
        # Bot Description — shown on the empty-chat screen before the user taps Start.
        # Telegram serves this per the user's app language (set via set_my_description).
        "bot_description": (
            "👋 I help you not to forget things.\n\n"
            "One-time and monthly reminders, plus quick notes that nudge you every "
            "2 hours until you close them.\n\n"
            "Tap Start to begin."
        ),
        "greeting": (
            "👋 Welcome! I'll help you not to forget things.\n\n"
            "There are three reminder types:\n"
            "🔔 *Basic* — one-time; pings 24h and 2h before the deadline\n"
            "🔁 *Monthly* — repeats every month; pings 48h and 24h ahead and at 09:00 "
            "on the day\n"
            "📝 *Note* — a simple everyday note; nudges every 2 hours until you close it\n\n"
            "Your timezone is *{tz}*. Change it with /timezone, or your language with "
            "/language. See /help for details.\n\n"
            "Tap *{btn_new}* to create your first reminder."
        ),
        "help": (
            "🤖 *Reminder bot*\n\n"
            "I'll help you not to forget things — one-time and monthly reminders, plus "
            "quick notes that nudge you every 2 hours until you close them.\n"
            "Reminders that would land at night (22:00–08:00) are moved to 08:00. All "
            "times use *your* timezone and a 24-hour clock.\n\n"
            "*Reminder types* — tap ➕ New reminder (or /remind), then choose:\n\n"
            "🔔 *Basic* — one-time, for a specific date.\n"
            "Send: `{hint}`\n"
            "_Example:_ `{example}`\n"
            "→ Pings 24h and 2h before the deadline (here: 20 Jun 16:00 and 21 Jun "
            "14:00); if it's closer than that, a single ping at the deadline. The year "
            "is filled in automatically (rolls to next year if that date has passed); "
            "month names work in English or Ukrainian. After the deadline it stays in "
            "/list for 5 more days, then deletes itself.\n\n"
            "🔁 *Monthly* — repeats on the same day every month.\n"
            "Send: `{hint_monthly}` — just the day of the month, no time.\n"
            "_Example:_ `{example_monthly}`\n"
            "→ Pings 48h and 24h ahead, and at 09:00 on the day itself. "
            "Go to 📋 My reminders to close it.\n\n"
            "📝 *Note* — a simple everyday note.\n"
            "Send plain text, e.g. `Buy groceries: milk, bread, eggs`\n"
            "→ I'll remind you every 2 hours. Go to 📋 My reminders to close it.\n\n"
            "*Commands*\n"
            "• /remind — create a reminder (Basic, Monthly, or Note)\n"
            "• /list — active reminders with their upcoming pings (✖ Close removes one)\n"
            "• /timezone `[IANA]` — view or set your timezone, e.g. `/timezone Europe/Kyiv`\n"
            "• /language — switch English / Українська\n"
            "• /help — this message"
        ),
        # new reminder
        "choose_reminder_type": "🆕 Choose reminder type:",
        "new_prompt": (
            "📝 Send your reminder in this format:\n`{hint}`\n\n_Example:_ `{example}`"
        ),
        "new_prompt_monthly": (
            "🔁 Send your monthly reminder in this format:\n`{hint}`\n\n"
            "_Example:_ `{example}`\nIt repeats on that day every month — I'll ping you "
            "48h and 24h ahead and at 09:00 on the day itself."
        ),
        "new_prompt_note": (
            "📝 Send your note — just the text, no date.\n\n"
            "_Example:_ `Buy groceries: milk, bread, eggs`\n"
            "I'll remind you every 2 hours until you close it."
        ),
        "confirm_note": (
            "✅ Got it: “{note}”\n"
            "📝 I'll remind you every 2 hours — first at {first}.\n"
            "Go to 📋 My reminders to close it."
        ),
        "err_empty_note_text": "The note is empty — send just the text you want to remember.",
        "confirm_ok": (
            "✅ Got it: “{note}”\nDue: {due}\nI'll remind you at: {pings}"
        ),
        "confirm_none": (
            "✅ Got it: “{note}”\nDue: {due}\n"
            "⚠️ That time has already passed — no reminders scheduled."
        ),
        # recurring
        "recur_monthly_desc": (
            "monthly on day {day} — reminders 48h and 24h ahead and at 09:00 on the day"
        ),
        "recur_note_desc": "every 2 hours",
        "confirm_recurring": (
            "✅ Got it: “{note}”\n🔁 Repeats {rule}"
        ),
        "confirm_recurring_none": (
            "✅ Got it: “{note}”\n🔁 Repeats {rule}"
        ),
        # list
        "list_header": "📋 You have {count} active reminder(s):",
        "list_empty": "You have no active reminders. Tap {btn} to make one.",
        "list_item": "🔔 *{text}*\n🗓 Due: {when}\n⏰ Reminders:{pings}",
        "list_item_recurring": (
            "🔁 *{text}*\n🔄 Repeats {rule}"
        ),
        "list_no_pending": "all sent",
        "list_autodelete": "🗑 _Deadline passed — auto-deletes {when}._",
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
        "cb_cancelled": "Closed ✖",
        "cb_gone": "That reminder no longer exists.",
        "cb_done_msg": "✅ Done: “{text}”",
        "cb_cancelled_msg": "✖ Closed: “{text}”",
        # pings
        "ping_due_now": "🔔 Reminder — “{text}” is due now.",
        "ping_due_before": "⏰ Reminder — “{text}” is coming up (due {due}).",
        "ping_note": "📝 Don't forget: “{text}”",
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
        "err_bad_recurrence": (
            "I couldn't read the day. Give a day of the month (1–31), e.g. “5”."
        ),
    },
    "uk": {
        "input_hint": f"текст {SEPARATOR} День Місяць ГГ:ХХ",
        "input_example": f"Прийом у лікаря {SEPARATOR} 21 червня 16:00",
        "input_hint_monthly": f"текст {SEPARATOR} День",
        "input_example_monthly": f"Оренда {SEPARATOR} 5",
        "btn_new": "➕ Нове нагадування",
        "btn_list": "📋 Мої нагадування",
        "btn_timezone": "🌍 Часовий пояс",
        "btn_help": "❓ Допомога",
        "btn_done": "✅ Завершити",
        "btn_cancel": "✖ Закрити",
        "btn_stop_repeating": "🛑 Зупинити повтор",
        "btn_type_monthly": "🔁 Щомісячне",
        "btn_type_basic": "🔔 Стандартне",
        "btn_type_note": "📝 Нотатка (кожні 2 год)",
        "choose_language": "🌐 Choose your language / Оберіть мову:",
        "language_set": "✅ Мову змінено на *{name}*.",
        "bot_description": (
            "👋 Допоможу нічого не забути.\n\n"
            "Разові та щомісячні нагадування, а також нотатки, що нагадують кожні "
            "2 години, доки ви їх не закриєте.\n\n"
            "Натисніть Start, щоб почати."
        ),
        "greeting": (
            "👋 Вітаю! Допоможу нічого не забути.\n\n"
            "Є три типи нагадувань:\n"
            "🔔 *Стандартне* — разове; нагадаю за 24 год і за 2 год до дедлайну\n"
            "🔁 *Щомісячне* — повторюється щомісяця; нагадаю за 48 год, за 24 год і о "
            "09:00 у сам день\n"
            "📝 *Нотатка* — звичайна нотатка; нагадування кожні 2 години, доки не "
            "закриєте\n\n"
            "Ваш часовий пояс — *{tz}*. Змінити його можна командою /timezone, а мову — "
            "командою /language. Деталі — у /help.\n\n"
            "Натисніть *{btn_new}*, щоб створити перше нагадування."
        ),
        "help": (
            "🤖 *Бот нагадувань*\n\n"
            "Допоможу нічого не забути — разові та щомісячні нагадування, а також "
            "нотатки, що нагадують кожні 2 години, доки ви їх не закриєте.\n"
            "Нагадування, що припадають на ніч (22:00–08:00), переносяться на 08:00. "
            "Усі часи — у *вашому* часовому поясі, формат 24-годинний.\n\n"
            "*Типи нагадувань* — натисніть ➕ Нове нагадування (або /remind) і оберіть:\n\n"
            "🔔 *Стандартне* — разове, на конкретну дату.\n"
            "Надішліть: `{hint}`\n"
            "_Приклад:_ `{example}`\n"
            "→ Нагадаю за 24 год і за 2 год до дедлайну (тут: 20 чер 16:00 та 21 чер "
            "14:00); якщо часу менше — одне нагадування в сам дедлайн. Рік підставляється "
            "автоматично (якщо дата вже минула — наступний рік); назви місяців — "
            "українською або англійською. Після дедлайну воно ще 5 днів лишається у "
            "/list, а потім видаляється автоматично.\n\n"
            "🔁 *Щомісячне* — повторюється того самого числа щомісяця.\n"
            "Надішліть: `{hint_monthly}` — лише число місяця, без часу.\n"
            "_Приклад:_ `{example_monthly}`\n"
            "→ Нагадаю за 48 год, за 24 год і о 09:00 у сам день. "
            "Щоб закрити, відкрийте 📋 Мої нагадування.\n\n"
            "📝 *Нотатка* — звичайна нотатка на кожен день.\n"
            "Надішліть звичайний текст, напр. `Купити продукти: молоко, хліб, яйця`\n"
            "→ Нагадуватиму кожні 2 години. Щоб закрити, відкрийте "
            "📋 Мої нагадування.\n\n"
            "*Команди*\n"
            "• /remind — створити нагадування (Стандартне, Щомісячне чи Нотатка)\n"
            "• /list — активні нагадування з часом пінгів (✖ Закрити — видалити)\n"
            "• /timezone `[IANA]` — переглянути чи змінити часовий пояс, напр. `/timezone Europe/Kyiv`\n"
            "• /language — змінити мову (English / Українська)\n"
            "• /help — це повідомлення"
        ),
        "choose_reminder_type": "🆕 Оберіть тип нагадування:",
        "new_prompt": (
            "📝 Надішліть нагадування у такому форматі:\n`{hint}`\n\n_Приклад:_ `{example}`"
        ),
        "new_prompt_monthly": (
            "🔁 Надішліть щомісячне нагадування у форматі:\n`{hint}`\n\n"
            "_Приклад:_ `{example}`\nВоно повторюватиметься цього числа щомісяця — "
            "нагадаю за 48 год, за 24 год і о 09:00 у сам день."
        ),
        "new_prompt_note": (
            "📝 Надішліть нотатку — просто текст, без дати.\n\n"
            "_Приклад:_ `Купити продукти: молоко, хліб, яйця`\n"
            "Нагадуватиму кожні 2 години, доки не закриєте її."
        ),
        "confirm_note": (
            "✅ Прийнято: «{note}»\n"
            "📝 Нагадуватиму кожні 2 години — перше о {first}.\n"
            "Щоб закрити, відкрийте 📋 Мої нагадування."
        ),
        "err_empty_note_text": "Нотатка порожня — надішліть просто текст, який треба запам'ятати.",
        "confirm_ok": (
            "✅ Прийнято: «{note}»\nДедлайн: {due}\nНагадаю: {pings}"
        ),
        "confirm_none": (
            "✅ Прийнято: «{note}»\nДедлайн: {due}\n"
            "⚠️ Цей час уже минув — нагадування не заплановані."
        ),
        "recur_monthly_desc": (
            "щомісяця {day}-го числа — нагадування за 48 год, за 24 год і о 09:00 "
            "у сам день"
        ),
        "recur_note_desc": "кожні 2 години",
        "confirm_recurring": (
            "✅ Прийнято: «{note}»\n🔁 Повторюється {rule}"
        ),
        "confirm_recurring_none": (
            "✅ Прийнято: «{note}»\n🔁 Повторюється {rule}"
        ),
        "list_header": "📋 У вас активних нагадувань: {count}",
        "list_empty": "У вас немає активних нагадувань. Натисніть {btn}, щоб створити.",
        "list_item": "🔔 *{text}*\n🗓 Дедлайн: {when}\n⏰ Нагадування:{pings}",
        "list_item_recurring": (
            "🔁 *{text}*\n🔄 Повторюється {rule}"
        ),
        "list_no_pending": "усі надіслані",
        "list_autodelete": "🗑 _Дедлайн минув — буде видалено автоматично {when}._",
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
        "cb_cancelled": "Закрито ✖",
        "cb_gone": "Цього нагадування більше не існує.",
        "cb_done_msg": "✅ Готово: «{text}»",
        "cb_cancelled_msg": "✖ Закрито: «{text}»",
        "ping_due_now": "🔔 Нагадування — «{text}» час настав.",
        "ping_due_before": "⏰ Нагадування — «{text}» незабаром (дедлайн {due}).",
        "ping_note": "📝 Не забудьте: «{text}»",
        "err_missing_separator": (
            "Будь ласка, використовуйте формат:\n{hint}\n"
            f"(розділіть текст і дату/час символом «{SEPARATOR}»)."
        ),
        "err_empty_note": f"Текст нагадування порожній. Напишіть його перед «{SEPARATOR}».",
        "err_bad_datetime": (
            "Не вдалося розпізнати дату/час. Вкажіть назву місяця, день і час у "
            "24-годинному форматі, напр. «{example}»."
        ),
        "err_bad_recurrence": (
            "Не вдалося розпізнати число. Вкажіть число місяця (1–31), напр. «5»."
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
