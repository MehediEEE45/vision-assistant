#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x ../.venv/bin/python ]; then
    echo "Run setup.command --models first."
    exit 1
fi
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export YOLO_OFFLINE=True
exec ../.venv/bin/python -m va_lab.assistant "$@"
