#!/bin/bash
# Run a command against the real sites from your laptop, no cluster involved.
#
#   ./run-local.sh robots          # robots.txt verdict per URL we touch
#   ./run-local.sh list-products   # productIds for chart/values.yaml
#   ./run-local.sh check           # every watched match and its state, sends nothing
#   ./run-local.sh availability    # full run, WILL send Telegram messages
#   ./run-local.sh announce        # full run, WILL send Telegram messages
set -euo pipefail

cd "$(dirname "$0")/app"

if [[ ! -f .env.local ]]; then
    echo "missing app/.env.local - copy app/.env.local.example and fill it in" >&2
    exit 1
fi

if [[ ! -d .venv ]]; then
    echo "creating app/.venv ..."
    python3 -m venv .venv
    ./.venv/bin/pip install --quiet --upgrade pip
    ./.venv/bin/pip install --quiet -r requirements.txt
fi

# `set -a` exports everything the file defines; the UA line contains spaces and
# parentheses, so it must not be word-split.
set -a
# shellcheck disable=SC1091
source .env.local
set +a

mkdir -p "${STATE_DIR}"
exec ./.venv/bin/python -m nffmon "$@"
