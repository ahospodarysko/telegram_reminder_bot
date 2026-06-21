#!/bin/bash
# Convenience wrapper: run the bot against the TEST bot for development.
# Sets BOT_ENV=test (selecting TEST_BOT_TOKEN + reminders.test.db) and defers to run.sh,
# which loads .env and launches the bot under the project virtualenv.
#
#   ./run-test.sh
#
# Production stays the default — use ./run.sh for the live bot.
set -euo pipefail

cd "$(dirname "$0")"

exec env BOT_ENV=test ./run.sh
