# claude_claw

透過 Telegram 遠端指揮 Claude Code 的小助手。在手機上傳訊息，Claude 就在你的電腦上執行開發工作。

## 系統需求

- macOS（或 Linux）
- [Claude Code CLI](https://claude.ai/code) 已安裝並登入
- [uv](https://github.com/astral-sh/uv) 已安裝
- Python 3.12+
- Telegram Bot Token（向 [@BotFather](https://t.me/BotFather) 申請）

## 安裝步驟

### 1. Clone 專案

```bash
git clone https://github.com/scarkuo0130/claude_claw.git
cd claude_claw
```

### 2. 設定 Bot Token 與 Chat ID

編輯 `bot.py`，修改以下三個常數：

```python
BOT_TOKEN = "你的 Telegram Bot Token"
ALLOWED_CHAT_ID = 你的 Telegram Chat ID   # 只允許這個帳號使用
WORK_DIR = "/你的/工作目錄"               # Claude 預設操作的專案路徑
```

> 取得 Chat ID：對 Bot 傳任意訊息後，開啟 `https://api.telegram.org/bot<TOKEN>/getUpdates`，找 `chat.id` 欄位。

同樣修改 `notify.py` 裡的 `BOT_TOKEN` 與 `ALLOWED_CHAT_ID`。

### 3. 安裝依賴

```bash
uv venv
uv pip install -r requirements.txt
```

### 4. 啟動 Bot

**背景執行（推薦）：**

```bash
./restart.sh start
```

**前景執行（開發用）：**

```bash
./run.sh
```

啟動後 Telegram 會收到通知，顯示目前 session 狀態。

## 使用方式

直接在 Telegram 傳送文字訊息即可叫 Claude 執行工作。

### 指令列表

| 指令 | 說明 |
| ---- | ---- |
| `/help` | 顯示指令說明 |
| `/session` | 顯示目前 session ID |
| `/sessions` | 列出最近 30 天的 sessions |
| `/sessions 7` | 列出最近 7 天的 sessions |
| `/change <id>` | 切換至指定 session（支援前 8 碼） |
| `/reset` | 重置 session，下次對話建立全新的 |
| `/restart` | 重啟 bot |
| `/stop` | 關閉 bot |

### 切換 VS Code Session

在 VS Code / Claude Code IDE 開啟的 session 可以直接在 Telegram 接手：

```text
<session-uuid> 繼續剛才的工作
```

或從 IDE 接手 Telegram 的 session：

```bash
claude -r <session-id>
```

## MCP Server（選用）

提供工具讓 Claude Code 直接管理 bot，無需手動執行 shell 指令。

在 Claude Code 設定中加入：

```json
{
  "mcpServers": {
    "claw": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py"],
      "cwd": "/你的/claude_claw/路徑"
    }
  }
}
```

可用工具：`claw_status`、`claw_start`、`claw_stop`、`claw_restart`、`claw_log`

## 手動推送通知

從終端機或 Claude hook 推送訊息到 Telegram：

```bash
python notify.py "部署完成"
```

## Claude Code Stop Hook（自動通知）

讓 Claude Code 完成工作後自動傳送 TG 通知，在 `.claude/settings.local.json` 加入：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "INPUT=$(cat); SESSION_ID=$(echo \"$INPUT\" | jq -r '(.session_id // \"unknown\")[:8]'); python /你的/claude_claw/路徑/notify.py \"✅ Claude 完成工作 [${SESSION_ID}]\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

設定後每次 Claude Code 停止時，Telegram 就會自動收到通知。

## 管理指令

```bash
./restart.sh start    # 啟動
./restart.sh stop     # 停止
./restart.sh          # 重啟
./stop.sh             # 停止（另一種方式）
```

Log 位置：`claw.log`
