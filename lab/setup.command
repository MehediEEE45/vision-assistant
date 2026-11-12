#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -x /opt/homebrew/bin/python3.11 ]; then
    python=/opt/homebrew/bin/python3.11
elif command -v python3.11 >/dev/null 2>&1; then
    python=python3.11
else
    python=python3
fi
"$python" tools/setup_lab.py "$@"
