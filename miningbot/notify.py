"""Discord 事件通知（Phase 2）。

把 EventLog 的關鍵事件轉成一句中文訊息，透過 Discord Bot API 送到指定頻道。
- `format_message`：純函式，決定「哪些事件要送、送什麼字」（有單元測試）。
- `make_discord_sink`：給 `EventLog.add_sink` 用的 sink；網路錯誤只記 log，絕不中斷主迴圈。
- `send_message`：直接送一則訊息（測試連線用）。回 (ok, detail)。
- `send_image_message`：送訊息 + 附加一張 PNG 圖片（multipart/form-data 上傳）。

用 stdlib urllib，不額外依賴 requests。
"""
import io
import json
import os
import queue
import threading
import uuid
import urllib.request
import urllib.error

API = "https://discord.com/api/v10/channels/{channel_id}/messages"

# 只有這些「值得通知」的事件會送 Discord；其餘（狀態切換、暫停/繼續、心跳…）不送，避免洗版。
# PAUSED/RESUMED 不送——會手動暫停的人一定在畫面前，不需要 Discord 提醒。
_TEMPLATES = {
    "RARE_FOUND":      lambda m: "🔔 偵測到稀有礦（chill）！開始自動採集…",
    "TRACKER_FOUND":   lambda m: f"📍 找到追蹤框{m.get('pos', '')}，準備 D3 採集",
    "HARVEST_SUCCESS": lambda m: "✅ 稀有礦採集成功"
                                 + (f"：{m['mineral']}" if m.get("mineral") else ""),
    "NEEDS_HUMAN":     lambda m: f"⚠️ 需要人工介入：{m.get('reason', '未知原因')}",
    "STUCK":           lambda m: f"⚠️ 腳本可能卡住：{m.get('reason', '無進度')}",
    "MINE_RESET":      lambda m: "🔄 礦坑重置，已停下等待重新定位（按 Q 繼續）",
}


def format_message(rec) -> str | None:
    """把事件轉成要送出的訊息；不需要通知的事件回 None。"""
    tmpl = _TEMPLATES.get(rec.type)
    if tmpl is None:
        return None
    return tmpl(rec.meta)


def send_message(token: str, channel_id: str, content: str, timeout: float = 10.0):
    """直接送一則純文字訊息到 Discord 頻道。回 (ok: bool, detail: str)。"""
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


def _build_multipart(payload: dict, files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """建 multipart/form-data body（Discord 訊息 + 檔案附件）。

    files = [(filename, binary_data), ...]
    回傳 (body_bytes, content_type_header)。
    """
    boundary = "----miningbot" + uuid.uuid4().hex
    buf = io.BytesIO()
    # payload_json（訊息內容 + 附件 metadata）
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(b'Content-Disposition: form-data; name="payload_json"\r\n')
    buf.write(b'Content-Type: application/json\r\n\r\n')
    buf.write(json.dumps(payload).encode("utf-8"))
    buf.write(b"\r\n")
    # 檔案欄位
    for i, (filename, data) in enumerate(files):
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="files[{i}]"; filename="{filename}"\r\n'.encode())
        buf.write(b'Content-Type: image/png\r\n\r\n')
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def send_image_message(token: str, channel_id: str, content: str,
                       image_path: str, timeout: float = 15.0):
    """送訊息 + 附加一張 PNG 到 Discord 頻道。回 (ok: bool, detail: str)。

    image_path 是本機 PNG 檔案路徑；函式會讀取後以 multipart 上傳。
    """
    if not token or not channel_id:
        return False, "缺少 token 或 channel_id"
    try:
        with open(image_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return False, f"讀圖失敗 ({image_path}): {e}"
    filename = os.path.basename(image_path)
    payload = {"content": content, "attachments": [{"id": 0, "filename": filename}]}
    body, content_type = _build_multipart(payload, [(filename, data)])
    url = API.format(channel_id=channel_id)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": content_type,
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


def fetch_messages(token: str, channel_id: str, after: str | None = None,
                   limit: int = 10, timeout: float = 10.0) -> list[dict]:
    """GET /channels/{id}/messages — 取最近訊息（newest-first）。after = 只取此 ID 之後的。

    失敗回空 list（輪詢失敗不中斷主迴圈）。
    """
    if not token or not channel_id:
        return []
    url = API.format(channel_id=channel_id)
    params = f"?limit={limit}"
    if after:
        params += f"&after={after}"
    req = urllib.request.Request(
        url + params, method="GET",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "miningbot (local automation, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def send_embed(token: str, channel_id: str, embed: dict,
               content: str | None = None, timeout: float = 10.0):
    """送含 embed 的訊息到 Discord 頻道。回 (ok: bool, detail: str)。"""
    if not token or not channel_id:
        return False, "缺少 token 或 channel_id"
    payload = {"embeds": [embed]}
    if content:
        payload["content"] = content
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API.format(channel_id=channel_id), data=data, method="POST",
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


def make_async_sink(inner, log=None):
    """把同步 sink 包成非同步：record 入佇列，背景 worker 執行緒處理，呼叫端立即返回。

    根因：Discord 圖片通知走 send_image_message（multipart 上傳，timeout 最長 15s），
    若在 EventLog.log → _on_enter 同步跑，會阻塞主迴圈數秒——chill 偵測後遲遲不開始
    採集、HARVESTING 期間 sweep/D3 之間卡頓。包成非同步後主迴圈丟進佇列即返回（~µs），
    上傳在背景進行。單一 worker（保序）、inner 拋例外只記 log 不殺執行緒、daemon 隨主程式結束。
    """
    q: "queue.Queue" = queue.Queue()

    def _worker():
        while True:
            rec = q.get()
            try:
                inner(rec)
            except Exception as e:                       # 某次上傳失敗不該讓 worker 死掉
                if log:
                    log.error("async sink 處理事件失敗: %s", e)
            finally:
                q.task_done()

    threading.Thread(target=_worker, daemon=True, name="discord-sink").start()

    def sink(rec) -> None:
        q.put(rec)

    return sink


def make_discord_sink(token: str, channel_id: str, on_error=None, log=None):
    """回傳 EventLog sink：把值得通知的事件送 Discord；有 image_path 時附加圖片。

    失敗只回報不丟例外。log 是可选的 logging.Logger，用來記錄每筆 Discord 送出的結果。
    """
    def sink(rec) -> None:
        content = format_message(rec)
        if content is None:
            return
        image_path = rec.meta.get("image_path")
        if image_path and os.path.exists(image_path):
            ok, detail = send_image_message(token, channel_id, content, image_path)
            if log:
                log.info("IMG %s image=%s -> %s (%s)", rec.type,
                         os.path.basename(image_path), "OK" if ok else "FAIL", detail)
        else:
            ok, detail = send_message(token, channel_id, content)
            if log:
                log.info("TXT %s -> %s (%s)", rec.type, "OK" if ok else "FAIL", detail)
        if not ok and on_error is not None:
            on_error(detail)
    return sink
