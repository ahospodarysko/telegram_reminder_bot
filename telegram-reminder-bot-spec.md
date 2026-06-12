# Telegram Reminder Bot — Project Specification

**Version:** 1.2
**Language / stack:** Python
**Status:** Draft for implementation

---

## 1. Summary

A Telegram bot that lets a user save a note with a due date/time and then sends
them reminders on Telegram at fixed offsets before the deadline — **1 day before,
12 hours before, 6 hours before** — and at the **deadline itself**.

Example: a reminder *"Doctor appointment"* due **21 Jun, 16:00** produces pings at
20 Jun 16:00, 21 Jun 04:00, 21 Jun 10:00, and 21 Jun 16:00.

The interface is **button-driven** where possible (see Section 6): the user taps
rather than types for almost everything.

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
instead asks the user for their **timezone**, the one thing it cannot infer.

---

## 3. Key design decisions

These are settled up front because they cause the most trouble if left vague.

### 3.1 Timezones
- Telegram does not reliably expose a user's timezone.
- Ask each user for their timezone once (on first START, changeable via `/timezone`).
- Store **all** due times and ping times internally in **UTC**.
- Convert to the user's timezone only for display.

### 3.2 Confirmation echo
After a reminder is created, the bot replies with exactly how it interpreted the
input, including all scheduled ping times. This catches parsing/timezone mistakes
immediately. Example:
> Got it: *"Doctor appointment"* due **Sat 21 Jun 16:00 (Europe/Kyiv)**.
> I'll remind you at: 20 Jun 16:00, 21 Jun 04:00, 21 Jun 10:00, 21 Jun 16:00.

### 3.3 Skipping past offsets
If a reminder is created less than 24h before the deadline, the −24h (and possibly
−12h / −6h) pings are already in the past. The scheduler **skips any offset whose
fire time has already passed** and only schedules future ones. If the reminder is
created very close to the deadline, the at-due ping still fires.

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
- **IDs the user types/taps:** `/list` displays each active reminder with its `id`,
  and cancel/done target that same `id` (via inline buttons or `/cancel <id>`).
  This is how the user picks one specific reminder when they have many.

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
| `timezone` | IANA timezone string, e.g. `Europe/Kyiv`. |
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
| `offset` | One of `-24h`, `-12h`, `-6h`, `0`. |
| `fire_at_utc` | Exact ping time in UTC. |
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
1. Captures and stores the user's `chat_id`.
2. Greets the user and explains what the bot does.
3. Asks for their timezone and stores it.
4. Presents the main reply keyboard (6.3) for everything afterward.

(No phone number / account id is ever requested — see Section 2.)

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
Reminder messages and `/list` entries carry **inline buttons** (attached under the
message) for per-item actions:

```
🔔 Doctor appointment — Sat 21 Jun 16:00
[ ✅ Done ] [ 😴 Snooze ] [ ✖ Cancel ]
```

These use `callback_data` and act invisibly (no extra message from the user). This
is the cleanest way to let the user act on a specific reminder out of many.

### 6.5 Creating a reminder
- **v1 input format (strict):** e.g. `Doctor appointment | 2026-06-21 16:00`
  (note text and datetime separated by a delimiter), entered after tapping
  *➕ New reminder*.
- Bot parses, stores the reminder, computes the four ping times, skips any past
  offsets, and sends the confirmation echo (Section 3.2).

### 6.6 Commands (also reachable as buttons)
| Command | Purpose |
|---|---|
| `/start` | Register user, set timezone (normally via the START button). |
| `/remind` | Create a timed reminder (also the *➕ New reminder* button). |
| `/list` | Show active reminders with inline action buttons. |
| `/cancel <id>` | Cancel a reminder (also the *✖ Cancel* inline button). |
| `/done <id>` | Mark complete (also the *✅ Done* inline button). |
| `/snooze <id> <duration>` | Push forward (also the *😴 Snooze* inline button). |
| `/timezone` | View or change timezone. |
| `/help` | Show usage. |

### 6.7 Lists / plain notes
The grocery-list case usually has no deadline. Such items use `type = list`/`note`
and receive **no scheduled pings** (or a single optional reminder), keeping timed
reminders and plain lists cleanly separated.

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

1. **Setup script** — apply `setMyCommands`, menu button, name/descriptions;
   read `BOT_TOKEN` from the environment (Section 8).
2. Bot handles the START button: captures `chat_id`, asks for and stores timezone,
   shows the main reply keyboard.
3. Create + store a reminder in the strict format, with the confirmation echo.
4. Polling scheduler that sends the **at-due** ping.
5. Add −24h / −12h / −6h offsets with past-offset skipping.
6. `/list` with inline Done / Snooze / Cancel buttons; `/timezone`.
7. Restart-safety verification (occurrences + `sent` flag).
8. Later: natural-language dates, recurring reminders, lists/notes.

---

## 11. Future extensions (out of scope for v1)

- Natural-language date parsing ("next Friday at 4pm").
- Recurring reminders (daily / weekly / monthly).
- Customizable offsets per reminder.
- Multiple lists and shared lists.
- A Telegram Web App (mini-app) opened from the menu button for richer UI.
