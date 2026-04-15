#!/bin/bash
cd "$(dirname "$0")"

# 只需要 requests，不需要 anthropic 了
if [ ! -d ".venv" ]; then
  echo "📦 建立虛擬環境..."
  uv venv
  uv pip install requests
fi

echo "🚀 啟動 claw..."
uv run python bot.py
