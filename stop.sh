#!/bin/bash
cd "$(dirname "$0")"

LOCK_FILE="/tmp/scar.develop.claw.lock"

if [ ! -f "$LOCK_FILE" ]; then
  echo "⚠️  Bot 未在執行"
  exit 0
fi

PID=$(cat "$LOCK_FILE")

if ! kill -0 "$PID" 2>/dev/null; then
  echo "⚠️  PID $PID 已不存在，清除 lock file"
  rm -f "$LOCK_FILE"
  exit 0
fi

kill "$PID"
echo "🛑 已停止 (PID $PID)"
