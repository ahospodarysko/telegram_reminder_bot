# Deploying on an always-on Mac (launchd)

Run the bot as a `launchd` agent so it starts at boot, restarts on crash, and keeps
running unattended. These steps target macOS (e.g. a Mac mini server).

> **One bot token = one runner.** Telegram allows only a single long-polling client
> per bot token. Stop any other instance (your laptop) before starting it here, or
> use a separate bot token from BotFather for this machine.

## 1. Get the code and set up

```bash
git clone git@github.com:ahospodarysko/telegram_reminder_bot.git
cd telegram_reminder_bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then edit: set BOT_TOKEN, optionally DEFAULT_TZ / DB_PATH
chmod +x run.sh
```

A fresh `reminders.db` is created on first run; copy your existing one over if you
want to keep prior test data.

## 2. Keep the machine awake

```bash
sudo pmset -a sleep 0 disksleep 0
```

Also enable **automatic login** (System Settings → Users & Groups) so the agent
starts after a reboot without anyone logging in.

## 3. Install the launchd agent

```bash
# Fill in your username and install the template.
sed "s/__USER__/$(whoami)/g" deploy/com.ahospodarysko.reminderbot.plist \
    > ~/Library/LaunchAgents/com.ahospodarysko.reminderbot.plist

# (Adjust the paths in the plist if you cloned somewhere other than ~/telegram_reminder_bot.)

launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ahospodarysko.reminderbot.plist
launchctl print gui/$(id -u)/com.ahospodarysko.reminderbot | grep -i state   # expect "running"
```

## 4. Watch the logs

```bash
tail -f logs/bot.log
# or remotely:  ssh user@macmini.local 'tail -f ~/telegram_reminder_bot/logs/bot.log'
```

## Managing the service

```bash
# Restart after pulling new code:
git pull && launchctl kickstart -k gui/$(id -u)/com.ahospodarysko.reminderbot

# Stop / uninstall:
launchctl bootout gui/$(id -u)/com.ahospodarysko.reminderbot
```
