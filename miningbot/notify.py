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

# 個人 bot 寫死（spec §7）：NEEDS_HUMAN 推播用 <@ID> mention，無需 Config 欄位。
# Discord mention 格式：<@USER_ID>；USER_ID 必須是字串（數字會被當角色 ID）。
PING_USER_ID = "373438562940747776"

# P2 format_status_text 用的狀態中文化映射（與 status_hud._STATE_ZH 同內容、不同模組；
# 命名 _STATUS_ZH 避免跨模組同名混淆）。模組層級常數——不必每次 tick 重建。
_STATUS_ZH = {
    "MINING": "挖礦中", "HARVESTING": "採集稀有礦",
    "NEEDS_HUMAN": "需要人工", "RESET_WAIT": "礦坑重置·待定位",
    "REENTRY": "重置·自動回礦",
}


# --- P2: 狀態訊息 post-once-then-edit 純函式（spec §7 A 混合更新策略）---
# 遙控器卡是 1 則常駐訊息；狀態/動態用 edit_message 即時更新（重要內容），
# 運行時間/音訊等不重要內容靠下次 repin 順帶刷新。


def should_edit_for_state(old_state: str | None, new_state: str,
                          old_action: str | None, new_action: str) -> bool:
    """狀態/動作變動是否該觸發立即 edit_message。

    spec §7 A：狀態 transition（MINING→HARVESTING 等）跟關鍵動作字串變動
    （命中座標、verify 結果）都該即時 edit；其餘（運行時間、音訊分數）靠 repin。

    old_state=None 視為強制觸發（首次 post 之後的呼叫端會用 None 起步）。
    """
    if old_state is None or old_state != new_state:
        return True
    # 狀態相同，看動作字串
    if old_action != new_action:
        return True
    return False


class EditThrottle:
    """狀態訊息 edit_message 降頻器：避免狀態機快速擺盪洗版。

    每次 allow_edit(now) 檢查距上次 edit 是否 >= min_interval_s；通過則更新
    last_edit_at。不通過不更新（保留原本時間基準）。
    時間由呼叫端注入（time.monotonic），方便單元測試。
    """

    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._last_edit_at: float | None = None

    @property
    def last_edit_at(self) -> float | None:
        return self._last_edit_at

    def allow_edit(self, now: float) -> bool:
        if self._last_edit_at is None or (now - self._last_edit_at) >= self.min_interval_s:
            self._last_edit_at = now
            return True
        return False


# --- P2: 訊息內容格式化純函式（spec §7）---


def format_status_text(state: str, last_action: str, audio_score: float,
                       capacity_pct: float | None, uptime_s: int) -> str:
    """狀態訊息內容（給 StatusMessenger.post/edit 用）。

    跟 status_hud.py 同風格（左下角 HUD 文字版），但搬到 Discord 卡片。
    state 用模組層 _STATUS_ZH 映射成中文；映射不到用原文。
    uptime 格式 XhYYm（不顯示秒，discord 卡片不需要那麼細）。
    """
    tag = _STATUS_ZH.get(state, state)
    cap_s = f"　容量: {capacity_pct:.0f}%" if capacity_pct is not None else ""
    h = uptime_s // 3600
    m = (uptime_s % 3600) // 60
    return (
        f"● {tag}\n"
        f"動作: {last_action}\n"
        f"音訊: {audio_score:.2f}{cap_s}    運行: {h}h{m:02d}m"
    )


def format_ping_content(harvest_id: str | None, reason: str, fallback: bool) -> str:
    """NEEDS_HUMAN PING 訊息內容。

    用 <@USER_ID> mention 推播；harvest_id 有則前綴 [XXX]；fallback 與否
    決定後續玩家該去哪處理（Discord 反應按鈕 vs 網頁點選）。
    """
    hid = f"[{harvest_id}] " if harvest_id else ""
    ping = f"<@{PING_USER_ID}>"
    if fallback:
        body = f"{ping} ⚠️ {hid}需要人工：{reason}\n（fallback 模式：用 Discord 反應按鈕處理）"
    else:
        body = f"{ping} ⚠️ {hid}需要人工：{reason}\n（在網頁處理：pinch-zoom 點選截圖）"
    return body


def format_resolve_text(harvest_id: str | None, reply_source: str, detail: str = "") -> str:
    """NEEDS_HUMAN 結案編輯內容（把原 PING 訊息 edit 成 ✅）。

    reply_source: "web" / "discord" / "skip" / "timeout"；detail 是可选補充
    （例如玩家點擊座標、verify 結果）。
    """
    hid = f"[{harvest_id}] " if harvest_id else ""
    src_map = {"web": "在網頁處理", "discord": "在 Discord 處理",
               "skip": "已跳過", "timeout": "已逾時"}
    src_txt = src_map.get(reply_source, reply_source)
    detail_s = f"（{detail}）" if detail else ""
    return f"✅ {hid}已{src_txt}{detail_s}"


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


class RepinDebouncer:
    """釘底防抖：看到新訊息只立旗標，頻道安靜滿 quiet_s 秒才真的刪舊貼新。

    2026-07-19 spec：舊釘底「一看到新訊息就刪舊貼新」在連發（稀有礦通知＋截圖、
    八方位發圖空檔）時反覆刪貼；改為安靜窗到期一次到位。純邏輯零 I/O：時間一律
    由呼叫端注入（time.monotonic()），可直接單元測試。遙控器與回礦卡各持一個
    實例。旗標／時間都是單一指派，GIL 下原子——主迴圈 mark_pending（回礦收尾）
    與輪詢執行緒 due/clear 的競態最壞多等一輪或多重貼一次，無正確性問題。
    """

    def __init__(self):
        self.pending = False        # 需要重貼（卡片被擠上去／回礦收尾主動要求）
        self.last_activity = 0.0    # 頻道最後一則新訊息的時刻（monotonic）

    def note_activity(self, now: float):
        """頻道出現任何新訊息（含 bot 自己發的）就刷新活動時間。"""
        self.last_activity = now

    def mark_pending(self):
        """卡片需要重貼到頻道底（先立旗標，等安靜窗到期才動手）。"""
        self.pending = True

    def mark_pending_now(self):
        """立刻需要重貼（2026-07-20）：繞過安靜窗，due() 下一輪恆成立。

        用於「退出精細選擇」等單次事件——卡被擠到上面時不該再等 quiet_s；
        常態 repin 仍走 mark_pending + quiet_s 防連發刪貼。
        """
        self.pending = True
        self.last_activity = 0.0

    def due(self, now: float, quiet_s: float) -> bool:
        """該重貼了嗎：旗標立著且距最後活動已安靜滿 quiet_s。"""
        return self.pending and (now - self.last_activity) >= quiet_s

    def clear(self):
        """卡片已重新貼到頻道底，殘留 pending 清掉（防剛貼完又多刪貼一次）。"""
        self.pending = False


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


def make_discord_sink(token: str, channel_id: str, on_error=None, log=None,
                      giveup_image_mode: str = "groups",
                      _send_images_override=None):
    """回傳 EventLog sink：把值得通知的事件送 Discord；有 image_path 時附加圖片。

    失敗只回報不丟例外。log 是可选的 logging.Logger，用來記錄每筆 Discord 送出的結果。

    giveup_image_mode（P2 spec §7）：
    - "groups"（預設）：既有行為，image_groups 各 group 一則訊息、附 group 內圖片。
      相容既有呼叫端（main.py 不傳此參數即走此路徑）。
    - "single"（P2 新）：採集放棄事件改為一則訊息 + 一張全畫面圖（meta["image_path"]），
      取代 image_groups 4-6 弚分組。細看的聊天/背包截圖在網頁歷史紀錄看（spec §5）。
      沒帶 image_path 時 fall through 到既有 groups / multi / single 路徑。

    _send_images_override：測試用，覆寫 send_images_message；production 為 None。
    """
    _send_images = _send_images_override or send_images_message

    def _send(content, paths):
        """送一則：圖片就緒→附圖上傳，否則退回純文字。回 (ok, detail, tag)。

        production 等 snapshot worker 寫完（race 修復）；都就緒才附圖，否則退回純文字。
        測試注入 _send_images_override 時路徑非真實檔案，跳過等待直接送（測試關心
        的是 send_images 被怎麼呼叫，不是檔案 race）。
        """
        if _send_images_override is None:
            ready = [p for p in paths if _wait_for_file(p)]
        else:
            ready = list(paths)
        if ready:
            ok, detail = _send_images(token, channel_id, content, ready)
            return ok, detail, "IMGx%d" % len(ready)
        ok, detail = send_message(token, channel_id, content)
        return ok, detail, ("TXT" if not paths else "NOIMG(wait-timeout)")

    def sink(rec) -> None:
        content = format_message(rec)
        if content is None:
            return
        # P2 single 模式：優先用 image_path（單張全畫面）取代 image_groups
        if giveup_image_mode == "single":
            single_img = rec.meta.get("image_path")
            if single_img:
                ok, detail, tag = _send(content, [single_img])
                if log:
                    log.info("%s %s -> %s (%s)", tag, rec.type,
                             "OK" if ok else "FAIL", detail)
                if not ok and on_error is not None:
                    on_error(detail)
                return
            # 沒 image_path：fall through 到 groups / text 路徑（既有行為）
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


# --- P2: StatusMessenger（狀態訊息 post-once-then-edit；spec §7 A）---


class StatusMessenger:
    """遙控器卡的「狀態顯示」部分用 edit_message 即時更新（取代部分釘底）。

    生命週期：
    - ensure_posted() 一次：post 初始訊息，拿 message_id
    - update() 多次：狀態/動作變動 + throttle 通過 → edit_message 同一則

    跟既有 RepinDebouncer 平行（不取代）：RepinDebouncer 仍管卡片釘底（被擠上去時
    刪舊貼新），StatusMessenger 管卡片內容（不刪不貼，就 edit）。

    send_fn / edit_fn 注入：production 用本模組的 send_message_with_id / edit_message；
    測試用 fake callable。所有發訊動作失敗只回 False，不丟例外（沿用 notify 既有慣例）。
    """

    def __init__(self, token: str, channel_id: str, edit_min_interval_s: float,
                 send_fn, edit_fn, log=None):
        self._token = token
        self._channel_id = channel_id
        self._throttle = EditThrottle(min_interval_s=edit_min_interval_s)
        self._send_fn = send_fn
        self._edit_fn = edit_fn
        self._log = log
        self._message_id: str | None = None
        self._last_state: str | None = None
        self._last_action: str | None = None

    @property
    def message_id(self) -> str | None:
        return self._message_id

    @property
    def last_state(self) -> str | None:
        return self._last_state

    @property
    def last_action(self) -> str | None:
        return self._last_action

    def ensure_posted(self, now: float) -> bool:
        """post 初始狀態訊息；已 post 過 no-op。回 True = 此次 post 成功 / 已 post。"""
        if self._message_id is not None:
            return True
        content = format_status_text("MINING", "啟動中", 0.0, None, 0)
        ok, detail, mid = self._send_fn(self._token, self._channel_id, content)
        if not ok or mid is None:
            if self._log:
                self._log.warning("StatusMessenger post 失敗: %s", detail)
            return False
        self._message_id = mid
        # post 視為一次「edit 起點」—— throttle 從此刻起算
        self._throttle.allow_edit(now)
        return True

    def update(self, state: str, last_action: str, audio_score: float,
               capacity_pct: float | None, uptime_s: int, now: float) -> bool:
        """狀態/動作變動 + throttle 通過 → edit_message。回 True = 此次 edit 成功。"""
        if self._message_id is None:
            return False
        if not should_edit_for_state(self._last_state, state, self._last_action, last_action):
            return False
        if not self._throttle.allow_edit(now):
            return False
        content = format_status_text(state, last_action, audio_score, capacity_pct, uptime_s)
        ok, detail = self._edit_fn(
            self._token, self._channel_id, self._message_id, content=content,
        )
        if not ok:
            if self._log:
                self._log.warning("StatusMessenger edit 失敗: %s", detail)
            return False
        # 成功才更新追蹤狀態
        self._last_state = state
        self._last_action = last_action
        return True


# --- P2: PingResolveMessenger（NEEDS_HUMAN 推播 + 結案編輯；spec §7 B / D）---


class PingResolveMessenger:
    """NEEDS_HUMAN PING 推播 + 結案 edit 同則。

    送 PING 訊息用 send_fn（含 message_id 回傳）；結案用 edit_fn 把同則改成 ✅。
    生命週期：
    - send_ping() 一次：拿到 message_id，呼叫端存起來
    - resolve(message_id) 一次：編輯該則為 ✅；只能 resolve 一次（編輯 idempotent 但語意上是結案）

    為了擋下「resolve 一個未經 send_ping 開立的 message_id」（例如 caller 變數初值、
    跨重啟殘留），本類別內部追蹤本次 send_ping 開立的 ID 集；不在集中即視為未知，
    回 False。這是防禦性 state，不跨 session 持久化。

    失敗只回 False / None，不丟例外（沿用 notify 既有慣例）。
    """

    def __init__(self, token: str, channel_id: str, send_fn, edit_fn, log=None):
        self._token = token
        self._channel_id = channel_id
        self._send_fn = send_fn
        self._edit_fn = edit_fn
        self._log = log
        self._issued_ids: set[str] = set()

    def send_ping(self, harvest_id: str | None, reason: str,
                  fallback: bool, now: float) -> str | None:
        """發 PING 訊息，回 message_id（失敗 None）。

        now 參數目前未直接使用（保留給未來 rate-limit）；先介面對齊 StatusMessenger。
        """
        content = format_ping_content(harvest_id, reason, fallback)
        ok, detail, mid = self._send_fn(self._token, self._channel_id, content)
        if not ok or mid is None:
            if self._log:
                self._log.warning("PingResolveMessenger send_ping 失敗: %s", detail)
            return None
        self._issued_ids.add(mid)
        return mid

    def resolve(self, message_id: str, harvest_id: str | None,
                reply_source: str, detail: str = "") -> bool:
        """把 PING 訊息 edit 成 ✅ 結案。回 True = 編輯成功。

        空字串 / 未經 send_ping 開立的 message_id 一律回 False（避免誤編其他訊息）。
        """
        if not message_id or message_id not in self._issued_ids:
            return False
        content = format_resolve_text(harvest_id, reply_source, detail)
        ok, detail_msg = self._edit_fn(
            self._token, self._channel_id, message_id, content=content,
        )
        if not ok:
            if self._log:
                self._log.warning("PingResolveMessenger resolve 失敗: %s", detail_msg)
            return False
        return True
