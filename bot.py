#!/usr/bin/env python3
"""
scar.develop.claw — 透過 Telegram 遠端指揮開發的小助手
使用 claude CLI，session 可在 VS Code 接力
"""

import os
import re
import sys
import time
import json
import atexit
import logging
import subprocess
import requests

LOG_FILE = os.path.join(os.path.dirname(__file__), "claw.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
)
log = logging.getLogger("claw")

BOT_TOKEN = "8520043517:AAFLuAOBi8NyvjdUr2pE6-ANAAo5V25vatc"
ALLOWED_CHAT_ID = 715517829
WORK_DIR = "/Users/scarkuo/Desktop/GameProject/sns"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
LOCK_FILE = "/tmp/scar.develop.claw.lock"
SESSION_MAP_FILE = os.path.join(os.path.dirname(__file__), "session_map.json")

# 目前 session id（None = 尚未開始）
current_session_id: str | None = None
last_msg_time: float = 0
SESSION_TIMEOUT = 30 * 60  # 30 分鐘沒對話自動重置

# session 對應表：cli ↔ ide 雙向查詢
ide_session_map: dict[str, str] = {}  # cli_session_id -> ide_session_id
cli_session_map: dict[str, str] = {}  # ide_session_id -> cli_session_id


def load_session_map():
    """從檔案載入 session mapping"""
    global ide_session_map, cli_session_map
    if os.path.exists(SESSION_MAP_FILE):
        try:
            with open(SESSION_MAP_FILE, encoding="utf-8") as f:
                data = json.load(f)
            ide_session_map = data.get("ide_session_map", {})
            cli_session_map = data.get("cli_session_map", {})
            log.info(f"載入 session map：{len(cli_session_map)} 組對應")
        except Exception as e:
            log.warning(f"載入 session map 失敗：{e}")


def save_session_map():
    """將 session mapping 寫入檔案"""
    try:
        with open(SESSION_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump({"ide_session_map": ide_session_map, "cli_session_map": cli_session_map}, f, indent=2)
    except Exception as e:
        log.warning(f"儲存 session map 失敗：{e}")


def register_session_mapping(cli_id: str, ide_id: str):
    """建立 cli ↔ ide session 雙向對應"""
    ide_session_map[cli_id] = ide_id
    cli_session_map[ide_id] = cli_id
    save_session_map()
    log.info(f"session mapping: {cli_id[:8]} ↔ {ide_id[:8]}")


def build_context_from_jsonl(session_id: str, max_exchanges: int = 10) -> str | None:
    """從 JSONL 讀取對話歷史，組成 context 字串"""
    claude_projects = os.path.expanduser("~/.claude/projects")
    jsonl_path = None
    for encoded in os.listdir(claude_projects):
        candidate = os.path.join(claude_projects, encoded, f"{session_id}.jsonl")
        if os.path.exists(candidate):
            jsonl_path = candidate
            break
    if not jsonl_path:
        return None

    exchanges = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = obj.get("type")
                if role not in ("user", "assistant"):
                    continue
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    content = "\n".join(texts)
                content = str(content).strip()
                if content:
                    exchanges.append((role, content))
    except Exception as e:
        log.warning(f"讀取 JSONL 失敗：{e}")
        return None

    if not exchanges:
        return None

    # 只取最後 max_exchanges 輪
    exchanges = exchanges[-(max_exchanges * 2):]
    lines = ["[以下是先前對話記錄，請接續協助]\n"]
    for role, content in exchanges:
        prefix = "User" if role == "user" else "Assistant"
        lines.append(f"{prefix}: {content[:1000]}\n")
    lines.append("[對話記錄結束，請繼續]\n")
    return "\n".join(lines)


def acquire_lock():
    """確保只有一個 instance 在跑"""
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE) as f:
            pid = f.read().strip()
        try:
            os.kill(int(pid), 0)
            print(f"❌ 已有 instance 在執行 (PID {pid})，退出")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass  # 舊 PID 已不存在，繼續
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(LOCK_FILE) and os.remove(LOCK_FILE))


def send_tg(text: str):
    """傳送訊息，超過 4000 字自動分段"""
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": ALLOWED_CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown"
            }, timeout=10)
        except Exception:
            requests.post(f"{TG_API}/sendMessage", json={
                "chat_id": ALLOWED_CHAT_ID,
                "text": chunk
            }, timeout=10)


def get_updates(offset: int) -> list:
    try:
        resp = requests.get(f"{TG_API}/getUpdates", params={
            "offset": offset,
            "timeout": 10,
            "allowed_updates": ["message"]
        }, timeout=15)
        return resp.json().get("result", [])
    except Exception as e:
        log.warning(f"getUpdates 失敗: {e}")
        return []


def decode_claude_project_path(encoded: str) -> str | None:
    """
    將 ~/.claude/projects/ 的 encoded 目錄名還原為真實路徑
    encoded 格式：每個 / 換成 -，例如 /Users/scar/proj/my-app → -Users-scar-proj-my-app
    難點：目錄名本身可能含 -，需要貪婪匹配實際存在的路徑
    """
    # 去掉開頭的 -，從 / 開始貪婪建構路徑
    rest = encoded.lstrip("-")
    current = "/"

    while rest:
        matched = False
        # 嘗試從最長到最短的 token（貪婪）
        for end in range(len(rest), 0, -1):
            token = rest[:end]
            candidate = os.path.join(current, token)
            if os.path.isdir(candidate):
                # 確認剩下的部分用 - 開頭（path separator）或已結束
                tail = rest[end:]
                if tail == "" or tail.startswith("-"):
                    current = candidate
                    rest = tail.lstrip("-")
                    matched = True
                    break
        if not matched:
            break

    return current if current != "/" else None


def resolve_session_prefix(prefix: str) -> str | None:
    """用前 8 碼找出完整 session ID，找不到或有歧義回 None"""
    prefix = prefix.lower()
    claude_projects = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(claude_projects):
        return None
    matches = []
    for encoded in os.listdir(claude_projects):
        proj_dir = os.path.join(claude_projects, encoded)
        if not os.path.isdir(proj_dir):
            continue
        for fname in os.listdir(proj_dir):
            if fname.endswith(".jsonl") and fname.lower().startswith(prefix):
                matches.append(fname[:-6])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        log.warning(f"前綴 {prefix} 有 {len(matches)} 個 session 符合")
    return None


def find_session_cwd(session_id: str) -> str:
    """從 ~/.claude/projects/ 找出 session 屬於哪個專案目錄"""
    claude_projects = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(claude_projects):
        return WORK_DIR
    for encoded in os.listdir(claude_projects):
        session_file = os.path.join(claude_projects, encoded, f"{session_id}.jsonl")
        if os.path.exists(session_file):
            decoded = decode_claude_project_path(encoded)
            if decoded and os.path.isdir(decoded):
                log.info(f"session {session_id[:8]} → {decoded}")
                return decoded
    return WORK_DIR


def get_session_first_message(jsonl_path: str) -> str:
    """讀取 session JSONL，取出第一則 user 訊息作為標題"""
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "user":
                    content = obj.get("message", {}).get("content", "")
                    if isinstance(content, list):
                        # content 可能是 [{"type": "text", "text": "..."}]
                        texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                        content = " ".join(texts)
                    content = str(content).strip().replace("\n", " ")
                    return content[:60] + ("..." if len(content) > 60 else "")
    except Exception:
        pass
    return "（無法讀取）"


def get_latest_session() -> str | None:
    """找出最近修改的 session ID"""
    claude_projects = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(claude_projects):
        return None
    latest_mtime = 0
    latest_id = None
    for encoded in os.listdir(claude_projects):
        proj_dir = os.path.join(claude_projects, encoded)
        if not os.path.isdir(proj_dir):
            continue
        for fname in os.listdir(proj_dir):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(proj_dir, fname)
            mtime = os.path.getmtime(fpath)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_id = fname[:-6]
    return latest_id


def list_recent_sessions(days: int = 30) -> str:
    """列出最近 N 天內有活動的 sessions，依修改時間排序"""
    claude_projects = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(claude_projects):
        return "找不到 ~/.claude/projects 目錄"

    cutoff = time.time() - days * 86400
    sessions = []

    for encoded in os.listdir(claude_projects):
        proj_dir = os.path.join(claude_projects, encoded)
        if not os.path.isdir(proj_dir):
            continue
        decoded = decode_claude_project_path(encoded)
        proj_name = os.path.basename(decoded) if decoded else encoded[-20:]

        for fname in os.listdir(proj_dir):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(proj_dir, fname)
            mtime = os.path.getmtime(fpath)
            if mtime < cutoff:
                continue
            session_id = fname[:-6]  # 去掉 .jsonl
            first_msg = get_session_first_message(fpath)
            sessions.append((mtime, session_id, proj_name, first_msg))

    if not sessions:
        return f"最近 {days} 天內沒有 session 記錄"

    sessions.sort(reverse=True)

    now = time.time()
    lines = [f"📋 最近 {days} 天 Sessions（共 {len(sessions)} 個）：\n"]
    for i, (mtime, sid, proj, msg) in enumerate(sessions[:20], 1):
        diff = now - mtime
        if diff < 3600:
            age = f"{int(diff // 60)} 分鐘前"
        elif diff < 86400:
            age = f"{int(diff // 3600)} 小時前"
        else:
            age = f"{int(diff // 86400)} 天前"

        marker = " ◀ 目前" if sid == current_session_id else ""
        lines.append(f"{i}. [{proj}] {msg}\n   `{sid[:8]}...` · {age}{marker}\n")

    if len(sessions) > 20:
        lines.append(f"\n（只顯示最近 20 筆，共 {len(sessions)} 筆）")

    lines.append("\n切換 session：傳送 `<session-id> <指令>`")
    return "\n".join(lines)


TG_ENV_CONTEXT = "[ENV: Telegram] 使用者正透過 Telegram 傳送此訊息，請以適合 Telegram 的方式回應（簡潔、純文字為主，避免過長輸出）。\n\n"


def run_claude(user_message: str) -> tuple[str, str | None]:
    """
    呼叫 claude CLI，回傳 (response_text, session_id)
    第一次用 -p，之後用 -r <session_id> 繼續
    """
    global current_session_id

    message_with_ctx = TG_ENV_CONTEXT + user_message

    cwd = WORK_DIR
    cmd = [
        "claude", "-p",
        "--dangerously-skip-permissions",
        "--output-format", "json",
        "--model", "sonnet",
        message_with_ctx
    ]

    # 有 session 就繼續，否則開新的
    if current_session_id:
        cwd = find_session_cwd(current_session_id)
        cmd = [
            "claude", "-p",
            "--dangerously-skip-permissions",
            "--output-format", "json",
            "--model", "sonnet",
            "-r", current_session_id,
            message_with_ctx
        ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            stdin=subprocess.DEVNULL,
            cwd=cwd, timeout=300
        )

        if result.returncode != 0:
            err = result.stderr
            if current_session_id and "No conversation found" in err:
                ide_id = current_session_id

                # 查有沒有已建立的對應 CLI session
                existing_cli = cli_session_map.get(ide_id)
                if existing_cli:
                    log.info(f"找到對應 CLI session：{existing_cli[:8]}，切換並重試")
                    current_session_id = existing_cli
                    return run_claude(user_message)

                # 從 JSONL 重建 context，開新 session
                log.info(f"IDE session {ide_id[:8]} 無法 resume，從 JSONL 重建 context")
                context = build_context_from_jsonl(ide_id)
                if context is None:
                    return f"❌ Session `{ide_id[:8]}` 找不到且無法讀取歷史記錄", None

                current_session_id = None  # 強制開新 session
                response, new_cli_id = run_claude(context + f"\nUser: {user_message}")
                if new_cli_id:
                    register_session_mapping(new_cli_id, ide_id)
                    current_session_id = new_cli_id
                return response, new_cli_id

            return f"❌ claude CLI 錯誤：\n{err[:2000]}", None

        raw = result.stdout.strip()
        try:
            data = json.loads(raw)
            session_id = data.get("session_id")
            response = data.get("result", "（無回應）")
            return response, session_id
        except json.JSONDecodeError:
            return raw[:4000], None

    except subprocess.TimeoutExpired:
        return "❌ 逾時（300s）", None
    except Exception as e:
        return f"❌ 執行失敗：{e}", None


def main():
    global current_session_id, last_msg_time

    acquire_lock()
    load_session_map()
    log.info("scar.develop.claw 啟動")

    # 啟動時自動載入最新 session
    current_session_id = get_latest_session()
    if current_session_id:
        log.info(f"自動載入最新 session: {current_session_id[:8]}")

    # 啟動時跳過所有舊訊息，只處理啟動後的新訊息
    updates = get_updates(0)
    offset = updates[-1]["update_id"] + 1 if updates else 0
    log.info(f"啟動 offset: {offset}")

    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "").strip()

            log.info(f"收到訊息 from={chat_id} text={text!r}")

            if chat_id != ALLOWED_CHAT_ID or not text:
                continue

            # 30 分鐘沒對話，回到最新 session
            now = time.time()
            if now - last_msg_time > SESSION_TIMEOUT:
                current_session_id = get_latest_session()
                if current_session_id:
                    log.info(f"timeout，回到最新 session: {current_session_id[:8]}")
            last_msg_time = now

            # 特殊指令
            if text in ("/help", "/start"):
                help_text = (
                    "🤖 *scar.develop.claw 指令列表*\n\n"
                    "*/help* — 顯示此說明\n"
                    "*/session* — 顯示目前 session ID 與 VS Code 接手指令\n"
                    "*/sessions* — 列出最近 30 天的 sessions\n"
                    "*/sessions \\[天數\\]* — 列出最近 N 天的 sessions（例：`/sessions 7`）\n"
                    "*/reset* — 重置目前 session，下次對話開新的\n"
                    "*/change \\[id\\]* — 切換到指定 session（支援前 8 碼）\n"
                    "*/restart* — 重啟 bot 服務\n"
                    "*/stop* — 關閉 bot 服務\n\n"
                    "💬 *直接傳文字* — 傳送給 Claude 執行"
                )
                send_tg(help_text)
                continue

            if text == "/reset":
                current_session_id = None
                send_tg("🔄 Session 已重置，下次對話開始全新 session")
                continue

            if text == "/session":
                if current_session_id:
                    send_tg(f"📋 目前 session：`{current_session_id[:8]}`\n\nVS Code 接手：\n`claude -r {current_session_id}`")
                else:
                    send_tg("尚未開始 session")
                continue

            if text.startswith("/change"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2 or not parts[1].strip():
                    send_tg("用法：`/change <session-id>`\n例：`/change 6708d8c7`")
                    continue
                prefix = parts[1].strip()
                # 完整 UUID 直接用，否則用前綴查找
                full_uuid = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                if re.match(full_uuid, prefix, re.IGNORECASE):
                    current_session_id = prefix.lower()
                    send_tg(f"✅ 已切換至 session `{current_session_id[:8]}`")
                else:
                    resolved = resolve_session_prefix(prefix.lower())
                    if resolved:
                        current_session_id = resolved
                        send_tg(f"✅ 已切換至 session `{current_session_id[:8]}`")
                    else:
                        send_tg(f"❌ 找不到符合 `{prefix}` 的 session，請用 `/sessions` 查看列表")
                log.info(f"/change → session: {current_session_id}")
                continue

            if text == "/stop":
                send_tg("🛑 Bot 已關閉")
                log.info("收到 /stop 指令，關閉 bot")
                sys.exit(0)

            if text == "/restart":
                send_tg("🔄 Bot 重啟中...")
                log.info("收到 /restart 指令，重啟 bot")
                bot_dir = os.path.dirname(os.path.abspath(__file__))
                # sleep 2 讓自己先 sys.exit → atexit 清掉 lock file，新 instance 才能順利啟動
                subprocess.Popen(
                    ["sh", "-c", f"sleep 2 && cd '{bot_dir}' && uv run python bot.py >> claw.log 2>&1"],
                    start_new_session=True,
                    close_fds=True
                )
                sys.exit(0)

            if text.startswith("/sessions"):
                parts = text.split()
                days = 30
                if len(parts) > 1:
                    try:
                        days = int(parts[1])
                    except ValueError:
                        pass
                send_tg(list_recent_sessions(days))
                continue

            # 偵測訊息開頭是否為 VS Code session ID（UUID 格式）
            uuid_pattern = r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*(.*)'
            uuid_match = re.match(uuid_pattern, text, re.IGNORECASE | re.DOTALL)
            if uuid_match:
                session_from_msg = uuid_match.group(1)
                text = uuid_match.group(2).strip()
                current_session_id = session_from_msg
                log.info(f"切換至 VS Code session: {current_session_id}")
                if not text:
                    send_tg(f"✅ 已切換至 session `{current_session_id[:8]}`\n請繼續輸入指令")
                    continue

            # 一般指令
            is_new = current_session_id is None
            send_tg("⏳ 處理中...")
            log.info(f"呼叫 claude session={current_session_id}")

            response, session_id = run_claude(text)
            log.info(f"claude 回應長度={len(response)} session={session_id}")

            if session_id:
                current_session_id = session_id

            # 新 session 時附上接手指令
            if is_new and current_session_id:
                response += f"\n\n---\n📋 VS Code 接手：`claude -r {current_session_id}`"

            send_tg(response)

        time.sleep(1)


if __name__ == "__main__":
    main()
