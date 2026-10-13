#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
echo '打开 http://127.0.0.1:8765；停止请按 Ctrl+C。'
.venv/bin/python app.py
