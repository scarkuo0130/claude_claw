#!/usr/bin/env python3
"""
scar.develop.claw MCP server
提供工具讓 Claude Code 可以管理 claw bot
"""

import os
import json
import signal
import subprocess
from mcp.server.fastmcp import FastMCP

BASE_DIR = os.path.dirname(__file__)
LOG_FILE = os.path.join(BASE_DIR, "claw.log")
LOCK_FILE = "/tmp/scar.develop.claw.lock"
BOT_SCRIPT = os.path.join(BASE_DIR, "bot.py")

mcp = FastMCP("claw")


def _get_bot_pid() -> int | None:
    if not os.path.exists(LOCK_FILE):
        return None
    try:
        with open(LOCK_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError, OSError):
        return None


@mcp.tool()
def claw_status() -> str:
    """查看 claw bot 目前狀態（是否運作中、PID）"""
    pid = _get_bot_pid()
    if pid:
        return f"✅ 運作中 (PID {pid})\nLog: {LOG_FILE}"
    return "❌ 未運作"


@mcp.tool()
def claw_log(lines: int = 50) -> str:
    """讀取 claw bot 最後 N 行 log"""
    if not os.path.exists(LOG_FILE):
        return "Log 檔不存在"
    with open(LOG_FILE, encoding="utf-8") as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


@mcp.tool()
def claw_start() -> str:
    """啟動 claw bot（如果未在運作）"""
    if _get_bot_pid():
        return "⚠️ 已在運作中"
    subprocess.Popen(
        ["uv", "run", "python", "bot.py"],
        cwd=BASE_DIR,
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    return "✅ 已啟動"


@mcp.tool()
def claw_stop() -> str:
    """停止 claw bot"""
    pid = _get_bot_pid()
    if not pid:
        return "⚠️ 未在運作"
    try:
        os.kill(pid, signal.SIGTERM)
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        return f"✅ 已停止 (PID {pid})"
    except Exception as e:
        return f"❌ 停止失敗：{e}"


@mcp.tool()
def claw_restart() -> str:
    """重啟 claw bot"""
    stop_result = claw_stop()
    import time
    time.sleep(1)
    start_result = claw_start()
    return f"{stop_result}\n{start_result}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
