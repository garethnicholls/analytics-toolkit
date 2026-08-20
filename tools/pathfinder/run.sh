#!/usr/bin/env bash
set -euo pipefail

python -m pip install -r requirements.txt
exec python web_app.py \
  --host 0.0.0.0 \
  --port "${PORT:-8501}"
