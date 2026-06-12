#!/bin/bash
# Wrapper used to launch the bot under a process manager (e.g. launchd / systemd).
# Loads .env into the environment, then execs the bot using the project's virtualenv.
#
# Run directly for a foreground test:   ./run.sh
# Or point a launchd/systemd unit at it (see deploy/).
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    echo "run.sh: .env not found — copy .env.example to .env and set BOT_TOKEN" >&2
    exit 1
fi

# Export every variable defined in .env (BOT_TOKEN, DEFAULT_TZ, DB_PATH, ...).
set -a
# shellcheck disable=SC1091
source .env
set +a

mkdir -p logs

# Prefer the project virtualenv; fall back to whatever python3 is on PATH.
if [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python main.py
else
    exec python3 main.py
fi
