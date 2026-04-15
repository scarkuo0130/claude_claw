#!/bin/bash
cd "$(dirname "$0")"

PID_FILE=".bot.pid"

stop_bot() {
  if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
      echo "🛑 停止舊程序 (PID: $OLD_PID)..."
      kill "$OLD_PID"
      # 等待最多 5 秒
      for i in $(seq 1 10); do
        kill -0 "$OLD_PID" 2>/dev/null || break
        sleep 0.5
      done
      if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  強制終止..."
        kill -9 "$OLD_PID"
      fi
    else
      echo "ℹ️  PID $OLD_PID 已不存在"
    fi
    rm -f "$PID_FILE"
  else
    # 沒有 pid 檔，用 pgrep 找
    OLD_PID=$(pgrep -f "python bot.py" | head -1)
    if [ -n "$OLD_PID" ]; then
      echo "🛑 停止舊程序 (PID: $OLD_PID)..."
      kill "$OLD_PID"
      sleep 1
    fi
  fi
}

start_bot() {
  echo "🚀 啟動 claw bot..."
  nohup uv run python bot.py >> claw.log 2>&1 &
  NEW_PID=$!
  echo "$NEW_PID" > "$PID_FILE"
  echo "✅ 已啟動 (PID: $NEW_PID)，log: claw.log"
}

case "${1:-restart}" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
      echo "⚠️  Bot 已在執行 (PID: $(cat $PID_FILE))，請先 stop 或用 restart"
      exit 1
    fi
    start_bot
    ;;
  stop)
    stop_bot
    echo "🛑 Bot 已停止"
    ;;
  restart|*)
    stop_bot
    sleep 0.5
    start_bot
    ;;
esac
