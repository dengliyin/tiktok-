#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

PORT="${PORT:-8791}"
URL="http://127.0.0.1:${PORT}"

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display dialog "未找到 python3。请先安装 Xcode Command Line Tools 或 Python 3。" buttons {"好"} default button "好" with icon caution'
  exit 1
fi

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  open "$URL"
  exit 0
fi

python3 product_info_agent_web.py --host 127.0.0.1 --port "$PORT" --open
