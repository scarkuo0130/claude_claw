#!/usr/bin/env python3
"""
從命令列推送 Telegram 通知
用法：python notify.py "訊息內容"
"""
import sys
import requests

BOT_TOKEN = "8520043517:AAFLuAOBi8NyvjdUr2pE6-ANAAo5V25vatc"
ALLOWED_CHAT_ID = 715517829
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send(text: str):
    requests.post(f"{TG_API}/sendMessage", json={
        "chat_id": ALLOWED_CHAT_ID,
        "text": text[:4000],
    }, timeout=10)


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "✅ Claude 完成工作"
    send(msg)
