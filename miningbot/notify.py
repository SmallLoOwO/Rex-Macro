"""Discord 事件通知（Phase 2）。

把 EventLog 的關鍵事件轉成一句中文訊息，透過 Discord Bot API 送到指定頻道。
- `format_message`：純函式，決定「哪些事件要送、送什麼字」（有單元測試）。
- `make_discord_sink`：給 `EventLog.add_sink` 用的 sink；網路錯誤只記 log，絕不中斷主迴圈。
- `send_message`：直接送一則訊息（測試連線用）。回 (ok, detail)。
- `send_images_message`：送訊息 + 一或多張 PNG 圖片（multipart/form-data 上傳）。

用 stdlib urllib，不額外依賴 requests。
"""
import io
import json
import os
import queue
import threading
import time
import uuid
import urllib.request
import urllib.error
import urllib.parse

API = "https://discord.com/api/v10/channels/{channel_id}/messages"
# 訊息層級操作（編輯／表情）— 用 {channel_id} + {message_id} 套版
MESSAGE_API = "https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
# 表情：貼/移除自己（@me）— {emoji} 需 percent-encoded（unicode 表情要編碼成 UTF-8 %xx）
REACTION_SELF_API = "https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me"
# 表情：列出按過此表情的使用者（含機器人自己）
REACTIONS_API = "https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{emoji}"
# 表情：移除指定使用者的反應（需 Manage Messages 才能移除他人）— {user_id} 或 @me
REACTION_USER_API = "https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/{user_id}"

# 只有這些「值得通知」的事件會送 Discord；其餘（狀態切換、暫停/繼續、心跳…）不送，避免洗版。
# PAUSED/RESUMED 不送——會手動暫停的人一定在畫面前，不需要 Discord 提醒。
# STUCK 不在此：H044 起走 Bot._notify_stuck 專屬路徑（送出後掛 🏠 手動回礦反應鈕）
_TEMPLATES = {
    "RARE_FOUND":      lambda m: "🔔 偵測到稀有礦（chill）！開始自動採集…",
    "TRACKER_FOUND":   lambda m: f"📍 找到追蹤框{m.get('pos', '')}，準備 D3 採集",
    "HARVEST_SUCCESS": lambda m: "✅ 稀有礦採集成功"
                                 + (f"：{m['mineral']}" if m.get("mineral") else "")
                                 + (f"\n🆕 新增：\n" + "\n".join(m["new_found_lines"])
                                    if m.get("new_found_lines") else ""),
    "NEEDS_HUMAN":     lambda m: f"⚠️ 需要人工介入：{m.get('reason', '未知原因')}{m.get('rotation_hint', '')}",
    "SPAWN_CHILL":     lambda m: (f"💎 spawn chill！稀有礦可能生在 礦坑刷新的預設方塊，"
                                  f"bot 處於 {m.get('state', '?')} 挖不到，請手動處理"),
    "MINE_RESET":      lambda m: "🔄 礦坑重置，已停下等待重新定位（按 Q 繼續）",
    "REENTRY_START":   lambda m: "⛏️ 礦坑已重置，開始自動回礦…",
    "REENTRY_SUCCESS": lambda m: f"✅ 自動回礦成功（第 {m.get('attempts', '?')} 輪），恢復挖礦",
}


def format_message(rec) -> str | None:
    """把事件轉成要送出的訊息；不需要通知的事件回 None。

    meta 帶 harvest_id（如 "007"）時統一前綴 [007]，讓使用者從 Discord 看到就能回報
    「哪個編號似乎誤判」——該編號同時出現在 harvest.log 與快照檔名，一鍵就能搜出全部證據。
    """
    tmpl = _TEMPLATES.get(rec.type)
    if tmpl is None:
        return None
    content = tmpl(rec.meta)
    hid = rec.meta.get("harvest_id")
    if hid:
        content = f"[{hid}] {content}"
    return content


# 人工介入分組截圖的群標題（Discord「先聊天框、再背包」分開發送用；
# D3 超時（有框）路徑另有 tracker 群＝追蹤框現況，排最前）
# 近失候選（aim）群改由 remote_aim.build_aim_groups 直接產 caption，
# 走本表 fallback（get(region, region)），不再登記於此。
_REGION_CAPTIONS = {
    "tracker": "🎯 追蹤框（現況）",
    "chat": "📨 聊天框（前 / 後）",
    "backpack": "🎒 背包（前 / 後）",
}


def format_group_messages(content: str, image_groups) -> list:
    """把「分組圖片」攤平成要**分開發送**的 [(訊息文字, 圖片路徑清單), ...]（純函式）。

    image_groups = [(region, [path, ...]), ...]，順序即發送順序（聊天在前、背包在後）。
    第一則帶完整 content ＋該群標題，其餘只帶群標題——避免把整段警告文字在每則重複洗版。
    改自「一則附 4 圖（Discord 2×2）」：拆兩則各 2 圖（前/後對比模式不變），見 2026-07-02 需求。
    """
    out = []
    for i, (region, paths) in enumerate(image_groups):
        caption = _REGION_CAPTIONS.get(region, region)
        text = f"{content}\n{caption}" if i == 0 else caption
        out.append((text, list(paths)))
    return out


def send_message(token: str, channel_id: str, content: str, timeout: float = 10.0):
    """直接送一則純文字訊息到 Discord 頻道。回 (ok: bool, detail: str)。"""
    ok, detail, _ = send_message_with_id(token, channel_id, content, timeout)
    return ok, detail


def send_message_with_id(token: str, channel_id: str, content: str, timeout: float = 10.0):
    """送純文字訊息並回 (ok, detail, message_id)——需要對該訊息貼反應/編輯時用。

    message_id 取自 Discord 回應 JSON 的 "id"（比照 send_embed）；失敗時 None。
    STUCK 🏠 手動回礦鈕（H044）靠它拿 mid 貼反應。
    """
    if not token or not channel_id:
        return False, "缺少 token 或 channel_id", None
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
            body = resp.read().decode("utf-8", "replace")
            try:
                mid = json.loads(body).get("id")
            except (ValueError, AttributeError):
                mid = None
            return True, f"HTTP {resp.status}", mid
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {e.code}: {body}", None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None


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


def send_images_message(token: str, channel_id: str, content: str,
                        image_paths: list, timeout: float = 30.0):
    """送訊息 + 附加多張 PNG 到 Discord 頻道（一則 multipart 訊息）。回 (ok: bool, detail: str)。

    Discord 單則訊息可附多檔（payload.attachments 每檔一筆 id+filename，對應 files[id]）。
    採集放棄 NEEDS_HUMAN 用：附 D3 執行前/後兩張讓人工及時判定 礦是否被挖走。
    image_paths 順序即附件順序（Discord 依此顯示）。
    """
    if not token or not channel_id:
        return False, "缺少 token 或 channel_id"
    files = []
    for p in image_paths:
        try:
            with open(p, "rb") as f:
                files.append((os.path.basename(p), f.read()))
        except Exception as e:
            return False, f"讀圖失敗 ({p}): {e}"
    if not files:
        return False, "無可傳圖片"
    attachments = [{"id": i, "filename": fn} for i, (fn, _) in enumerate(files)]
    payload = {"content": content, "attachments": attachments}
    body, content_type = _build_multipart(payload, files)
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


def fetch_message(token: str, channel_id: str, message_id: str,
                  timeout: float = 10.0) -> dict | None:
    '''取單一 Discord 訊息（含 reactions 摘要）；失敗回 None。'''
    if not token or not channel_id or not message_id:
        return None
    url = MESSAGE_API.format(channel_id=channel_id, message_id=message_id)
    req = urllib.request.Request(
        url, method='GET',
        headers={
            'Authorization': f'Bot {token}',
            'User-Agent': 'miningbot (local automation, 1.0)',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            return body if isinstance(body, dict) else None
    except Exception:
        return None


def find_reaction_increments(message: dict, previous_counts: dict[str, int],
                             emojis) -> tuple[dict[str, int], list[tuple[str, int]]]:
    '''從 Message Object 的 reactions 摘要找出本輪增加的已知 emoji。

    基線採 count 同步語意：取消反應時會下降，之後再點上升即可再次觸發。
    malformed/未知欄位一律忽略，避免 Discord 回傳缺欄時打斷輪詢執行緒。
    '''
    available: dict[str, int] = {}
    for reaction in message.get('reactions') or []:
        if not isinstance(reaction, dict):
            continue
        emoji = reaction.get('emoji') or {}
        if not isinstance(emoji, dict):
            continue
        name = emoji.get('name')
        count = reaction.get('count')
        if not isinstance(name, str) or isinstance(count, bool):
            continue
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue
        available[name] = max(available.get(name, 0), count)

    # 成功抓到訊息但 reactions 暫時省略某項時，保留正基線；否則 bot 自己的 count=1
    # 下一輪重現會被誤判成新點擊。正常取消仍是 2→1（bot 反應留著），不影響重新武裝。
    current = {
        emoji: available.get(emoji, previous_counts.get(emoji, 0))
        for emoji in emojis
    }
    increments = []
    for emoji, count in current.items():
        delta = count - previous_counts.get(emoji, 0)
        if delta > 0:
            increments.append((emoji, delta))
    return current, increments


def find_remote_messages(msgs: list[dict], title: str):
    """從 fetch_messages 回傳（newest-first）中認領既有遙控器訊息。回 (newest_id | None, stale_ids)。

    匹配條件：author.bot 為 True **且** 任一 embed 的 title 等於 title。第一個匹配者為 newest
    （認領），其餘全列 stale（啟動時逐一刪除，清跨重啟殘留）。所有 key 防禦性 .get 取值，
    缺 author/embeds/title 的訊息一律不匹配、不丟例外（fetch 回的資料不可信）。
    """
    matches = []
    for m in msgs:
        if m.get("author", {}).get("bot") is not True:
            continue
        embeds = m.get("embeds") or []
        if not any((e.get("title") == title) for e in embeds):
            continue
        mid = m.get("id")
        if mid is not None:
            matches.append(mid)
    if not matches:
        return None, []
    return matches[0], matches[1:]


def send_embed(token: str, channel_id: str, embed: dict,
               content: str | None = None, timeout: float = 10.0):
    """送含 embed 的訊息到 Discord 頻道。回 (ok: bool, detail: str, message_id: str | None)。

    message_id 取自 Discord 回應 JSON 的 "id" 欄位；分頁功能靠它後續貼表情/編輯。
    失敗時 message_id=None。舊呼叫端忽略回傳值仍相容（沒有人解包成 2-tuple）。
    """
    if not token or not channel_id:
        return False, "缺少 token 或 channel_id", None
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
            body = json.loads(resp.read())
            return True, f"HTTP {resp.status}", body.get("id")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {e.code}: {body}", None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None


def add_reaction(token: str, channel_id: str, message_id: str,
                 emoji: str, timeout: float = 10.0):
    """機器人對訊息貼一個表情。PUT /reactions/{emoji}/@me。回 (ok: bool, detail: str)。

    emoji = unicode 表情（如 "🌍"）；內部自動 percent-encode（Discord 路徑要求）。
    成功回 HTTP 204（無 body）。用於 !list 分頁按鈕。
    """
    if not token or not channel_id or not message_id:
        return False, "缺少 token / channel_id / message_id"
    url = REACTION_SELF_API.format(
        channel_id=channel_id, message_id=message_id,
        emoji=urllib.parse.quote(emoji, safe=""))
    req = urllib.request.Request(
        url, method="PUT",
        headers={
            "Authorization": f"Bot {token}",
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


def get_reactions(token: str, channel_id: str, message_id: str,
                  emoji: str, limit: int = 100, timeout: float = 10.0) -> list[dict]:
    """列出對此訊息此表情按過的使用者（含機器人自己）。GET /reactions/{emoji}。

    失敗回空 list（輪詢失敗不中斷主迴圈）。回傳元素含 "id"（使用者 snowflake）等欄位。
    """
    if not token or not channel_id or not message_id:
        return []
    url = REACTIONS_API.format(
        channel_id=channel_id, message_id=message_id,
        emoji=urllib.parse.quote(emoji, safe=""))
    req = urllib.request.Request(
        f"{url}?limit={limit}", method="GET",
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


def remove_reaction(token: str, channel_id: str, message_id: str,
                    emoji: str, user_id: str, timeout: float = 10.0):
    """移除指定使用者對訊息的反應。DELETE /reactions/{emoji}/{user_id}。回 (ok, detail)。

    emoji 同 add_reaction（unicode 表情，內部 percent-encode）。**需要 Manage Messages 權限**
    才能移除「他人」的反應（移除自己的不需要）。缺權限時呼叫端應靜默降級（只記 log）——
    遙控器改用「seen 集合同步語意」後，使用者自己取消反應再點也能再次觸發，故 remove 失敗
    不影響功能正確性，只是同一顆按鈕得手動取消才能再按。
    """
    if not token or not channel_id or not message_id or not user_id:
        return False, "缺少 token / channel_id / message_id / user_id"
    url = REACTION_USER_API.format(
        channel_id=channel_id, message_id=message_id,
        emoji=urllib.parse.quote(emoji, safe=""), user_id=user_id)
    req = urllib.request.Request(
        url, method="DELETE",
        headers={
            "Authorization": f"Bot {token}",
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


def delete_message(token: str, channel_id: str, message_id: str,
                   timeout: float = 10.0):
    """刪除機器人自己發的訊息。DELETE /channels/{id}/messages/{mid}。回 (ok, detail)。

    遙控器釘底用：當遙控器被新訊息擠上去，刪掉舊的、再貼新的到頻道底。
    失敗只回報不丟例外（缺 manage messages 權限時靜默降級——舊遙控器殘留，新的一樣能用）。
    """
    if not token or not channel_id or not message_id:
        return False, "缺少 token / channel_id / message_id"
    url = MESSAGE_API.format(channel_id=channel_id, message_id=message_id)
    req = urllib.request.Request(
        url, method="DELETE",
        headers={
            "Authorization": f"Bot {token}",
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


def edit_message(token: str, channel_id: str, message_id: str,
                 embed: dict | None = None, content: str | None = None,
                 timeout: float = 10.0):
    """編輯機器人自己發的訊息（改 embed/content）。PATCH /messages/{mid}。回 (ok, detail)。

    分頁切換用：把同一則 !list 訊息的 embed 換成另一個世界的事件清單。
    embed/content 至少給一個；embed 用 {"embeds": [embed]} 包。
    """
    if not token or not channel_id or not message_id:
        return False, "缺少 token / channel_id / message_id"
    payload: dict = {}
    if embed is not None:
        payload["embeds"] = [embed]
    if content is not None:
        payload["content"] = content
    if not payload:
        return False, "沒有要編輯的欄位"
    data = json.dumps(payload).encode("utf-8")
    url = MESSAGE_API.format(channel_id=channel_id, message_id=message_id)
    req = urllib.request.Request(
        url, data=data, method="PATCH",
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


def make_async_sink(inner, log=None, max_queue: int = 64):
    """把同步 sink 包成非同步：record 入佇列，背景 worker 執行緒處理，呼叫端立即返回。

    根因：Discord 圖片通知走 send_images_message（multipart 上傳，timeout 最長 15s），
    若在 EventLog.log → _on_enter 同步跑，會阻塞主迴圈數秒——chill 偵測後遲遲不開始
    採集、HARVESTING 期間 sweep/D3 之間卡頓。包成非同步後主迴圈丟進佇列即返回（~µs），
    上傳在背景進行。單一 worker（保序）、inner 拋例外只記 log 不殺執行緒、daemon 隨主程式結束。
    """
    q: "queue.Queue" = queue.Queue(maxsize=max_queue)
    dropped = 0

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

    def sink(rec) -> bool:
        nonlocal dropped
        try:
            q.put_nowait(rec)
            return True
        except queue.Full:
            dropped += 1
            if log and (dropped == 1 or dropped % 10 == 0):
                log.warning("Discord async sink 佇列滿，已丟棄 %d 筆（最新=%s）",
                            dropped, getattr(rec, "type", "?"))
            return False

    return sink


def _wait_for_file(path: str, timeout: float = 2.0, interval: float = 0.05) -> bool:
    """輪詢等檔案就緒。修 async snapshot race：

    `_snapshot` 把 frame 丟進 snapshot worker 佇列後立即回傳路徑（檔案還沒寫），
    主線接著 `self.log.log(...)` → Discord sink 很快 pull，`os.path.exists(path)`
    经常 False（cv2.imwrite 寫 1080p PNG 需 50-200ms）→ 退回純文字通知，沒圖片。
    snapshot worker 通常 200ms 內寫完；2s 是 10x 餘裕，超過就放棄（算異常）。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(interval)
    return False


def make_discord_sink(token: str, channel_id: str, on_error=None, log=None):
    """回傳 EventLog sink：把值得通知的事件送 Discord；有 image_path 時附加圖片。

    失敗只回報不丟例外。log 是可选的 logging.Logger，用來記錄每筆 Discord 送出的結果。
    """
    def _send(content, paths):
        """送一則：圖片就緒→附圖上傳，否則退回純文字。回 (ok, detail, tag)。

        等 snapshot worker 寫完（race 修復）；都就緒才附圖，否則退回純文字。
        """
        ready = [p for p in paths if _wait_for_file(p)]
        if ready:
            ok, detail = send_images_message(token, channel_id, content, ready)
            return ok, detail, "IMGx%d" % len(ready)
        ok, detail = send_message(token, channel_id, content)
        return ok, detail, ("TXT" if not paths else "NOIMG(wait-timeout)")

    def sink(rec) -> None:
        content = format_message(rec)
        if content is None:
            return
        # image_groups（分組）→ 分開發送多則（採集放棄：先聊天框、再背包，前/後對比模式不變）
        groups = rec.meta.get("image_groups")
        if groups:
            for text, paths in format_group_messages(content, groups):
                ok, detail, tag = _send(text, paths)
                if log:
                    log.info("%s %s(group) -> %s (%s)", tag, rec.type,
                             "OK" if ok else "FAIL", detail)
                if not ok and on_error is not None:
                    on_error(detail)
            return
        # image_paths（多張，一則）優先；無則退回單張 image_path
        multi = rec.meta.get("image_paths") or []
        single = rec.meta.get("image_path")
        paths = [p for p in multi if p] if multi else ([single] if single else [])
        ok, detail, tag = _send(content, paths)
        if log:
            log.info("%s %s -> %s (%s)", tag, rec.type, "OK" if ok else "FAIL", detail)
        if not ok and on_error is not None:
            on_error(detail)
    return sink
