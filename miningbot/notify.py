"""Discord 事件通知（Phase 2）。

把 EventLog 的關鍵事件轉成一句中文訊息，透過 Discord Bot API 送到指定頻道。
- `format_message`：純函式，決定「哪些事件要送、送什麼字」（有單元測試）。
- `make_discord_sink`：給 `EventLog.add_sink` 用的 sink；網路錯誤只記 log，絕不中斷主迴圈。
- `send_message`：直接送一則訊息（測試連線用）。回 (ok, detail)。

用 stdlib urllib，不額外依賴 requests。
"""
import json
import urllib.request
import urllib.error

API = "https://discord.com/api/v10/channels/{channel_id}/messages"

# 只有這些「值得通知」的事件會送 Discord；其餘（狀態切換、暫停、心跳…）不送，避免洗版。
_TEMPLATES = {
    "RARE_FOUND":      lambda m: "🔔 偵測到稀有礦（chill）！開始自動採集…",
    "HARVEST_SUCCESS": lambda m: "✅ 稀有礦採集成功"
                                 + (f"：{m['mineral']}" if m.get("mineral") else ""),
    "NEEDS_HUMAN":     lambda m: f"⚠️ 需要人工介入：{m.get('reason', '未知原因')}",
    "STUCK":           lambda m: f"⚠️ 腳本可能卡住：{m.get('reason', '無進度')}",
    "MINE_RESET":      lambda m: "🔄 礦坑重置，已停下等待重新定位（按 Q 繼續）",
    "EMERGENCY_STOP":  lambda m: "⛔ 緊急停止（Ctrl+Q）",
}


def format_message(rec) -> str | None:
    """把事件轉成要送出的訊息；不需要通知的事件回 None。"""
    tmpl = _TEMPLATES.get(rec.type)
    if tmpl is None:
        return None
    return tmpl(rec.meta)


def send_message(token: str, channel_id: str, content: str, timeout: float = 10.0):
    """直接送一則訊息到 Discord 頻道。回 (ok: bool, detail: str)。"""
    if not token or not channel_id:
        return False, "缺少 token 或 channel_id"
    url = API.format(channel_id=channel_id)
    data = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "miningbot (local automation, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def make_discord_sink(token: str, channel_id: str, on_error=None):
    """回傳 EventLog sink：把值得通知的事件送 Discord；失敗只回報不丟例外。"""
    def sink(rec) -> None:
        content = format_message(rec)
        if content is None:
            return
        ok, detail = send_message(token, channel_id, content)
        if not ok and on_error is not None:
            on_error(detail)
    return sink
