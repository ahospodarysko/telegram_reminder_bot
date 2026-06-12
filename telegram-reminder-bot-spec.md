# Telegram Reminder Bot — Project Specification

**Version:** 1.3
**Language / stack:** Python
**Status:** Implemented (spec reflects current behavior)

---

## 1. Summary

A Telegram bot that lets a user save a note with a due date/time and then sends
them reminders on Telegram at fixed offsets before the deadline — **24 hours
before** and **2 hours before**. There is no at-deadline ping in the normal case;
an at-due ping only fires as a fallback when a reminder is created so close to the
deadline that both offset pings are already in the past (see Section 3.3).

Example: a reminder *"Doctor appointment"* due **21 Jun, 16:00** produces pings at
20 Jun 16:00 and 21 Jun 14:00.

Ping times are also shifted out of the user's **quiet hours** (22:00–08:00 local),
so a reminder never wakes the user at night (see Section 3.6).

The interface is **button-driven** where possible (see Section 6) and **bilingual**
(English / Ukrainian, see Section 3.7): the user taps rather than types for almost
everything.

---

## 2. How the bot reaches the user

The original idea was for `/start` to ask the user for their **phone number or
account ID** so the bot could message them. This is not how Telegram bots work,
and the whole design depends on getting this right:

- A bot **cannot** initiate a conversation with an arbitrary user by phone number
  or account ID. Telegram forbids this (anti-spam protection).
- The user **must contact the bot first**. On a brand-new chat, Telegram shows a
  built-in **START** button; tapping it sends `/start` automatically (the user
  does not type it — see Section 6.1). That update carries the user's `chat_id`.
- That `chat_id` is the exact handle the bot stores and uses to send **every**
  future reminder. No phone number is needed and none should be requested.

**Therefore:** on the first START, the bot captures `chat_id` automatically and
asks the user only to pick a **language** (English / Ukrainian). The timezone is
not asked up front — it is seeded from a host/`DEFAULT_TZ` default and can be
changed any time via `/timezone` (see Sections 3.1 and 6.1).

---

## 3. Key design decisions

These are settled up front because they cause the most trouble if left vague.

### 3.1 Timezones
- Telegram does not reliably expose a user's timezone.
- Each new user is seeded with a **default timezone**, resolved in order:
  `DEFAULT_TZ` env var → the host machine's zone (from `/etc/localtime`) → `UTC`.
- The user is **not** prompted for a timezone on first START; they change it any
  time with `/timezone <IANA>` (or the 🌍 Timezone button).
- Store **all** due times and ping times internally in **UTC**.
- Convert to the user's timezone only for display.
- Changing the timezone does **not** retroactively move existing reminders' stored
  UTC times; it applies to newly created reminders.

### 3.2 Confirmation echo
After a reminder is created, the bot replies with exactly how it interpreted the
input, including all scheduled ping times. This catches parsing/timezone mistakes
immediately. Example:
> ✅ Got it: "Doctor appointment"
> Due: Sat 21 Jun 16:00 (Europe/Kyiv)
> I'll remind you at: Fri 20 Jun 16:00, Sat 21 Jun 14:00

If the deadline has already passed at creation time (so no pings can be scheduled),
the echo says so explicitly instead of listing ping times. The confirmation also
carries a single inline **➕ New reminder** button so the user can immediately add
another (see Section 6.4).

### 3.3 Skipping past offsets
If a reminder is created less than 24h before the deadline, the −24h ping (and
possibly the −2h ping) is already in the past. The scheduler **skips any offset
whose fire time has already passed** and only schedules future ones.

**Too-close fallback:** if *both* the −24h and −2h pings are already in the past
but the deadline itself is still in the future, a single **at-deadline** ping
(offset label `0`) is scheduled instead, so a "too close" reminder still notifies.
If even the deadline has passed, no occurrences are scheduled at all.

### 3.4 Restart safety / missed reminders
The bot and its host can restart. To avoid duplicate or dropped pings:
- Each ping ("occurrence") is stored as its own record with a `sent` flag.
- On every scheduler tick, the bot fires any occurrence whose time has passed and
  is not yet sent, then marks it sent.
- A brief outage results in a slightly **late** reminder rather than a lost one.

### 3.5 Multiple reminders per user
The bot supports an unlimited number of active reminders per user, created at any
time. This falls out of the data model rather than needing special handling:
- Every reminder is an independent row keyed by its own `id` and scoped to the
  user's `chat_id`. Creating a new reminder never overwrites or touches existing
  ones — the user can set one for tomorrow, another the next day, and so on.
- The scheduler is reminder-agnostic: each tick it scans **all** pending
  occurrences across **all** reminders and users, and fires whatever is due. More
  reminders simply means more occurrence rows to scan; no extra logic is needed.
- If several pings fall in the same minute (across one or many reminders), the
  poll fires them as a batch — each is a separate message.
- **IDs the user taps:** `/list` displays each active reminder with inline Done /
  Cancel buttons; those buttons carry the reminder's `id` in their `callback_data`.
  This is how the user acts on one specific reminder when they have many. (Done and
  Cancel are inline-button only — they are not typed `/done`/`/cancel` commands.)

### 3.6 Quiet hours
No ping fires between **22:00 (inclusive) and 08:00 (exclusive)** in the user's
local time:
- A fire time at/after 22:00 is moved to **08:00 the next morning**.
- A fire time before 08:00 is moved to **08:00 the same morning**.
- Times already inside the allowed window are left unchanged.

Because both offsets can be shifted to the same 08:00, two pings that would land in
the same night **collapse to a single 08:00 ping** (occurrences are de-duplicated by
fire time). The too-close fallback ping (Section 3.3) is quiet-hours-adjusted too.

### 3.7 Languages
The bot UI is bilingual — **English (`en`)** and **Ukrainian (`uk`)**:
- On first START the user picks a language; it is stored per user and changeable
  any time via `/language` or by re-running the picker.
- The initial language is seeded from the Telegram client locale when supported,
  otherwise English.
- All user-facing strings, the command menu, button labels, and date formatting
  (localized weekday/month names) follow the chosen language.
- **Reminder input accepts month names in either language regardless of UI
  language** — e.g. both `June 21` and `21 червня` parse (see Section 6.5).

---

## 4. Architecture

Four logical components:

1. **Bot interface** — receives messages/commands/button taps from Telegram and
   replies. Created via BotFather, which issues the bot token.
2. **Parser** — converts a user message into a structured reminder (text + due
   datetime). v1 uses a strict format; natural-language parsing is a later add-on.
3. **Storage** — SQLite database holding reminders and their ping occurrences.
4. **Scheduler** — a polling loop that fires due reminders.

### 4.1 Telegram connection mode
Use **long-polling** (`getUpdates`). It works behind a home network / NAT and
needs no public HTTPS endpoint. Webhooks can be considered later if hosting on a
server with a public URL.

### 4.2 Scheduler approach
Use a **polling loop** (runs every minute):
1. Query storage for occurrences due now and not yet sent.
2. Send each via the bot.
3. Mark them sent.

This is simple, robust, restart-safe, and handles missed reminders naturally.
One-minute granularity is acceptable for this use case. (An in-memory job queue
such as `python-telegram-bot`'s `JobQueue` is an alternative but loses scheduled
jobs on restart unless reloaded from storage.)

---

## 5. Data model

Conceptual; final column types decided at implementation.

### 5.1 `users`
| Field | Description |
|---|---|
| `chat_id` | Telegram chat id (primary key). Captured on first START. |
| `timezone` | IANA timezone string, e.g. `Europe/Kyiv`. Seeded from a default. |
| `language` | UI language code, `en` or `uk` (default `en`). |
| `created_at` | First seen timestamp (UTC). |

### 5.2 `reminders`
| Field | Description |
|---|---|
| `id` | Primary key. |
| `chat_id` | Owner (references `users.chat_id`). |
| `text` | The note, e.g. "Doctor appointment". |
| `type` | `timed` (has deadline + offsets) or `list`/`note` (no scheduled pings). |
| `due_at_utc` | Deadline in UTC (null for plain lists/notes). |
| `status` | `active` / `done` / `cancelled`. |
| `created_at` | UTC. |

### 5.3 `occurrences`
| Field | Description |
|---|---|
| `id` | Primary key. |
| `reminder_id` | References `reminders.id`. |
| `offset` | `-24h`, `-2h`, or `0` (the at-deadline fallback — see Section 3.3). |
| `fire_at_utc` | Exact ping time in UTC, already quiet-hours-adjusted (Section 3.6). |
| `sent` | Boolean flag, default false. |

Splitting pings into their own `occurrences` records is what makes
"skip past offsets" and restart-safety straightforward.

**Relationships:** one user (`chat_id`) → **many** `reminders`; one reminder →
**many** `occurrences`. There is no limit on how many reminders a user can have,
and creating a new one never affects existing ones. This is what allows the user
to set a reminder today, another tomorrow, and so on indefinitely.

---

## 6. User-facing behavior & button-driven UX

The bot is designed so the user taps rather than types wherever Telegram allows.

### 6.1 First contact — the START button
When a user opens the bot for the very first time, Telegram automatically shows a
built-in **START** button in place of the text input. Tapping it sends `/start`
on the user's behalf — **this is not something you build; every bot has it.** That
first tap is also what delivers the `chat_id` and grants permission to message the
user, so it can't be skipped — but from the user's side it is a button, not typing.

On that first START the bot:
1. Captures and stores the user's `chat_id`, seeding a default timezone (Section 3.1)
   and a default language guessed from the Telegram client locale.
2. Shows an inline **language picker** (🇬🇧 EN / 🇺🇦 UA).
3. On the language pick: confirms the language, greets the user, states the current
   (default) timezone and how to change it, and presents the main reply keyboard (6.3).

The timezone is **not** asked here — it is defaulted and changed later via
`/timezone`. (No phone number / account id is ever requested — see Section 2.)

### 6.2 Tappable command menu
Register all commands with `setMyCommands` (see Section 8). They then appear in a
menu next to the input field, so even `/list`, `/cancel`, etc. are tap-to-select
from a list with descriptions rather than typed from memory.

### 6.3 Reply keyboard (main menu)
After the first bot message, a persistent **reply keyboard** replaces the phone
keyboard with the main actions, e.g.:

```
[ ➕ New reminder ] [ 📋 My reminders ]
[ 🌍 Timezone    ] [ ❓ Help        ]
```

Tapping a button sends its text, which the bot handles like a command. Note a
reply keyboard only appears after the bot has sent a message — which is why the
built-in START button covers the very first step.

### 6.4 Inline buttons on each reminder
`/list` entries (and reminder ping messages) carry **inline buttons** (attached
under the message) for per-item actions:

```
🔔 Doctor appointment
🗓 Due: Sat 21 Jun 16:00
⏰ Reminders: Fri 20 Jun 16:00, Sat 21 Jun 14:00
[ ✅ Done ] [ ✖ Cancel ]
```

These use `callback_data` (`done:<id>` / `cancel:<id>`) and act invisibly (no extra
message from the user); tapping edits the message in place to confirm. This is the
cleanest way to let the user act on a specific reminder out of many. (There is no
Snooze button — it was dropped from v1.)

The reminder **confirmation echo** (Section 3.2) instead carries a single inline
**➕ New reminder** button (`callback_data = new`) — a shortcut to start another,
rather than Done/Cancel which would read like a "save" control.

### 6.5 Creating a reminder
- **Input format (strict):** `note text @ Month Day HH:MM`, entered after tapping
  *➕ New reminder* (or `/remind`). Examples: `Doctor appointment @ June 21 16:00`
  or `Прийом у лікаря @ 21 червня 16:00`.
- The separator is `@`, matched on its **last** occurrence so a note containing `@`
  still parses (the trailing date/time never contains one).
- **No year is typed:** the year defaults to the current year and rolls forward to
  next year if that date/time has already passed locally (so "March 1" entered in
  June means *next* March).
- Date parsing is **order- and language-agnostic**: it finds the `HH:MM` token
  (24-hour), a numeric day, and a month name in English **or** Ukrainian, in any
  order — independent of the user's UI language.
- Bot parses, converts the local wall-clock time to UTC, stores the reminder,
  computes the ping times (skipping past offsets, applying quiet hours), and sends
  the confirmation echo (Section 3.2). Parse failures return a localized, retryable
  error (`missing_separator` / `empty_note` / `bad_datetime`).

### 6.6 Commands (also reachable as buttons)
| Command | Purpose |
|---|---|
| `/start` | Register user and show the language picker (normally via the START button). |
| `/remind` | Create a reminder (also the *➕ New reminder* button). |
| `/list` | Show active reminders, each with inline ✅ Done / ✖ Cancel buttons. |
| `/timezone [IANA]` | View the current timezone, or set it when an argument is given (also the *🌍 Timezone* button). |
| `/language` | Re-show the language picker to change UI language. |
| `/help` | Show usage. |

**Done / Cancel** are inline-button actions only (`done:<id>` / `cancel:<id>`), not
typed commands. **Snooze** was removed from v1.

### 6.7 Lists / plain notes
The **data model already supports** deadline-less items: `reminders.type` defaults
to `timed` but allows `list`/`note`, `due_at_utc` is nullable, and `/list` renders a
"no deadline" entry with no pending pings. However, the **v1 create flow always
produces a `timed` reminder** — every creation requires a parseable date/time, so
plain lists/notes are not yet user-creatable. Exposing them in the UI is a future
extension (Section 11).

### 6.8 Optional: deep-link onboarding
A link or QR code of the form `https://t.me/YourBot?start=PAYLOAD` opens the bot
and shows the START button; tapping sends `/start PAYLOAD`. Useful if you ever
onboard users from a website or printed code.

---

## 7. Tech stack

- **Language:** Python 3.11+
- **Telegram library:** `python-telegram-bot` (mature; supports reply/inline
  keyboards, callback queries, and a `JobQueue` if needed).
- **Storage:** SQLite (single-file, zero-config; more than enough for personal use).
- **Datetime handling:** standard library `datetime` + `zoneinfo` for timezones.
  Optional `dateparser` later for natural-language dates.
- **Bot creation:** BotFather → bot token (handled as a secret — see Section 8).

---

## 8. Bot configuration & secret handling

The bot's one-time settings (command menu, menu button, display name and
descriptions) are applied through ordinary Telegram Bot API calls. The clean
approach is **configuration-as-code**: a small setup script that applies them all,
runnable once and re-runnable whenever a setting changes.

### 8.1 What the setup step configures
| API method | Sets |
|---|---|
| `setMyCommands` | The tappable command list (6.2). |
| `setChatMenuButton` | The menu button next to the input. |
| `setMyName` | The bot's display name. |
| `setMyDescription` | The text shown on an empty chat, before START. |
| `setMyShortDescription` | The short bio on the bot's profile. |
| `getMe` | Sanity check that the token is valid. |

### 8.2 Token / secret handling (important)
The bot token is a **full-access credential**: anyone holding it can read every
message the bot receives, send messages as the bot, and change all its settings.
Treat it like a password.

- **Never hardcode** the token in source, and **never commit** it to version
  control (use `.gitignore` for any local secrets file).
- **Never paste** it into a chat, log, screenshot, or shared document.
- Supply it at runtime via an **environment variable** (e.g. `BOT_TOKEN`). Both
  the bot and the setup script read it from the environment on startup.
- If a token is ever exposed, revoke/rotate it in BotFather immediately.

> Note: configuration cannot be done on the user's behalf by pasting the token
> elsewhere — the token must stay in the user's own environment. The setup script
> is what applies the settings, using the locally-provided `BOT_TOKEN`.

---

## 9. Hosting

A reminder bot needs **something always running** to fire pings. Options:
- A small VPS or a Raspberry Pi running the bot as a long-lived process
  (e.g. under `systemd` or a process manager), with `BOT_TOKEN` in its environment.
- A free-tier cloud instance.
- If serverless is ever used, a scheduled (cron) trigger must invoke the poll
  function, since serverless functions don't stay alive between requests.

Long-polling means no inbound public endpoint is required.

---

## 10. Suggested build order

1. **Setup script** — apply `setMyCommands` (en + uk), menu button,
   name/descriptions; read `BOT_TOKEN` from the environment (Section 8).
2. Bot handles the START button: captures `chat_id`, seeds a default timezone, shows
   the language picker, then the main reply keyboard.
3. Create + store a reminder in the strict `@` format (no year, EN/UK months), with
   the confirmation echo.
4. Polling scheduler that sends due pings (occurrences + `sent` flag).
5. Add −24h / −2h offsets with past-offset skipping and the at-deadline fallback.
6. Add quiet-hours shifting (22:00–08:00) and same-night collision de-duplication.
7. `/list` with inline Done / Cancel buttons; `/timezone`; `/language` + i18n (en/uk).
8. Restart-safety verification (occurrences + `sent` flag).
9. Later: natural-language dates, recurring reminders, user-creatable lists/notes.

---

## 11. Future extensions (out of scope for v1)

- Natural-language date parsing ("next Friday at 4pm").
- Recurring reminders (daily / weekly / monthly).
- Customizable offsets and quiet hours per user/reminder.
- Snooze action on pings (was dropped from v1).
- User-creatable plain lists/notes (the schema already supports them — Section 6.7).
- Multiple lists and shared lists.
- Additional UI languages beyond English / Ukrainian.
- A Telegram Web App (mini-app) opened from the menu button for richer UI.
