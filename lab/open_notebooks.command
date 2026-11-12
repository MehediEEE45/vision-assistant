#!/bin/bash
set -e
cd "$(dirname "$0")/notebooks"
exec ../../.venv/bin/python -m jupyterlab
