# Telegram Reminder Bot

A Telegram bot for timed reminders. Save a note with a deadline and the bot pings you
**24 hours before** and **2 hours before** the deadline.
Reminders can be **one-time** or **monthly** — a monthly reminder repeats on the same
day each month until you stop it.
The interface is available in **English and Ukrainian** — chosen on `/start` and
changeable anytime with `/language`.

Example — *"Doctor appointment"* due **21 Jun 16:00** → pings at 20 Jun 16:00 and
21 Jun 14:00. (If a reminder is created too close to the deadline for those offsets,
a single at-deadline ping fires instead.)

All times are stored in UTC and shown in your timezone. The bot is button-driven: you
tap rather than type for almost everything.

## How it works

- **First contact:** Telegram shows a built-in **START** button on a new chat. Tapping
  it sends `/start`, which gives the bot your `chat_id` (the handle it uses to message
  you) and shows a language picker (English / Українська). No phone number is requested.
- **Language:** stored per user. All messages, menus, and date displays are localized,
  and date *input* accepts month names in either language (`June 21` or `21 червня`).
- **Timezone:** new users default to the host machine's timezone (or `DEFAULT_TZ`).
  Change yours anytime with `/timezone`.
- **Monthly reminders:** pick *Monthly* when creating a reminder and give just a day +
  time (e.g. `Pay rent @ 5 09:00`). It fires every month on that day; short months clamp
  to the last day (a 31st becomes 28/29 Feb, 30 Apr…). The deadline is recomputed in
  local time each cycle, so the wall-clock time stays put across DST. **Done (this cycle)**
  rolls it to next month; **Stop repeating** ends the series.
- **Quiet hours:** no ping fires between **22:00 and 08:00** in the user's local time.
  Any ping that would land in that window is pushed to 08:00 that morning (e.g. a 2h-ahead
  ping for a 09:00 deadline moves from 07:00 to 08:00). Pings that collapse onto the same
  time are de-duplicated.
- **Restart-safe scheduling:** every ping is a row in an `occurrences` table with a
  `sent` flag. A loop runs each minute, fires any unsent ping whose time has passed,
  and marks it sent. A brief outage yields a *late* reminder, never a lost or duplicated
  one — SQLite is the source of truth, reloaded on startup.

## Project layout

```
bot/
  config.py      # BOT_TOKEN + default timezone resolution
  db.py          # SQLite schema + CRUD (source of truth)
  scheduling.py  # pure time logic: offsets, skip-past, tz conversion, parsing, monthly recurrence
  i18n.py        # English + Ukrainian strings, localized dates, button label sets
  keyboards.py   # reply + inline keyboards (language-aware)
  handlers.py    # commands, menu buttons, free text, inline callbacks
  scheduler.py   # the minute polling loop (sends pings, rolls recurring reminders forward)
  app.py         # builds the Application and runs long-polling
setup_bot.py     # one-time Bot API configuration (commands, menu, name, descriptions)
main.py          # entrypoint: python main.py
tests/           # unit tests for the time-critical logic
```

## Setup

### 1. Create the bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`.
2. Follow the prompts; BotFather gives you a **token** like `123456:ABC-DEF...`.

### 2. Configure the environment

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `BOT_TOKEN` to your BotFather token. Optionally set `DEFAULT_TZ`
(IANA timezone for new users) and `DB_PATH`.

The token is read **only** from the environment. Load `.env` into your shell however you
prefer, e.g.:

```bash
set -a; source .env; set +a
```

> **Secret handling:** the token is a full-access credential — treat it like a password.
> Never commit `.env`, paste the token into a chat, or print it. If it leaks, revoke it
> in BotFather. `.env` and the `*.db` files are gitignored.

### 3. Apply one-time bot configuration

```bash
python setup_bot.py
```

This validates the token (`getMe`) and sets the command menu, menu button, display name,
and descriptions. It is idempotent — re-run it whenever you change those settings.

### 4. Run the bot

The simplest way is `run.sh`, which loads `.env` into the environment and starts the
bot using the project's virtualenv (falling back to `python3` if `.venv` is absent):

```bash
chmod +x run.sh   # first time only
./run.sh
```

Or run it directly, loading `.env` into your shell yourself:

```bash
set -a; source .env; set +a
python main.py
```

The bot connects via long-polling (no public URL needed) and logs to stdout. `Ctrl-C`
stops it. To keep a foreground run going on a laptop, prefix it with `caffeinate -s` so
the machine doesn't sleep.

The bot must stay running to fire reminders. For unattended, always-on hosting (e.g. a
Mac mini server) run it under a process manager — see [`deploy/README.md`](deploy/README.md)
for a ready-made `launchd` setup using `run.sh`.

## Using the bot

Open the bot in Telegram and tap **START**. You'll get a menu:

```
[ ➕ New reminder ] [ 📋 My reminders ]
[ 🌍 Timezone    ] [ ❓ Help         ]
```

- **➕ New reminder** (or `/remind`) → first choose a type:
  - **🔔 Basic** → send `note text @ Month Day HH:MM`, e.g. `Doctor appointment @ June 21 16:00`.
    The year is assumed to be the current one (rolling to next year if that date has already
    passed), and the time is 24-hour.
  - **🔁 Monthly** → send `note text @ Day HH:MM` (no month), e.g. `Pay rent @ 5 09:00`.
    It repeats on that day every month.

  The bot echoes how it understood the input and lists every scheduled ping time.
- **📋 My reminders** (or `/list`) → each active reminder with an inline **✖ Cancel**
  button (for a monthly one, Cancel stops the series).
- **🌍 Timezone** (or `/timezone [IANA]`) → view or change your timezone.

### Commands

| Command | Purpose |
|---|---|
| `/start` | Register and show the menu |
| `/remind` | Create a reminder (one-time or monthly) |
| `/list` | List active reminders (with an inline ✖ Cancel on each) |
| `/timezone [IANA]` | View or set your timezone |
| `/language` | Switch between English and Ukrainian |
| `/help` | Usage help |

## Tests

```bash
python -m unittest discover -s tests
```

Covers offset computation, past-offset skipping, UTC↔timezone conversion, the "due now"
query, and input parsing — no token or network required.

## Tech

- Python 3.11+ (developed on 3.13)
- [`python-telegram-bot`](https://python-telegram-bot.org/) (async; `[job-queue]` extra)
- SQLite via stdlib `sqlite3`; `datetime` + `zoneinfo` for timezones
- Long-polling (`getUpdates`) — works behind NAT, no public endpoint

## Out of scope

Natural-language dates, customizable offsets, and shared lists are future extensions
(see `telegram-reminder-bot-spec.md` §11). Recurrence beyond monthly — weekly, yearly,
"every N months", or "nth weekday" — is designed for but not yet implemented.
