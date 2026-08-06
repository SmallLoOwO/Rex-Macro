"""WebIPC server：FastAPI app + WebSocket endpoint。

WebIPC thread（Task 10 整合進 main.py）跑 uvicorn server；client 連線維護
FallbackState.client_count；命令透過 parse_message 解析後 push 進 PendingReplies。
"""
import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import PurePath
from typing import Callable

import uvicorn
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from miningbot.web_protocol import (
    WebMessage, parse_message, parse_fire_at_payload,
    parse_reentry_click_payload, serialize_message,
)
from miningbot.web_ipc import PendingReplies, FallbackState
from miningbot.web_annotation import NO_LABEL, cell_crop_box
from miningbot.web_history import (
    annotation_queue, index_readable, load_stats, verdict_category,
)


_log = logging.getLogger(__name__)

# Ctrl+Z 還原限時的**後備**值（spec 05）。真正的門檻是 `Config.annotate_undo_window_s`，
# 由 main.py 一路透過 WebIPCThread 傳進來；這個常數只在「沒有 Config 可注入」的
# 測試／standalone 呼叫下生效。web_server 不 import config（它是被注入的），所以
# 這裡無法直接引用——一份常數比三處字面值好，改門檻請改 Config 那一個。
_UNDO_WINDOW_FALLBACK_S = 900.0


class ConnectionRegistry:
    """當下 WebSocket 連線池；thread-safe（WebIPC thread 跟事件 sink 都會呼叫）。

    broadcast 是 async（WebSocket send_text 是 async）；但事件 sink 是同步呼叫
    （WebEventSink.__call__ 在 bot 主迴圈 thread 上跑）。解法：維護 WebSocket
    物件清單，broadcast 用 asyncio.run_coroutine_threadsafe 把「逐一 send_text」
    的 coroutine 丟進 server 的 event loop（由 set_loop 注入）跑。

    廣播失敗（連線已斷）只 log 不丟，並把壞連線移出 registry——比照 notify.py
    既有「失敗只回報」慣例，避免冷啟／斷線抖動炸到主迴圈。
    """

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        # 2026-07-27：使用者的實際用法是「有提醒才連進來」，不會整場開著分頁盯。
        # 舊設計 broadcast 是純廣播、沒有任何補送——推播那當下如果玩家還沒連上
        # （正是「被提醒才連」這個用法的常態），訊息就直接消失，連進來只看到空白
        # idle 畫面（07-27 harvest 115／reentry #26 實錄）。這裡補一個「目前這輪
        # 介入」的重播緩衝：begin 時清空重錄，介入結束（成功/失敗/逾時退回 Discord）
        # 呼叫 end 清掉，避免對已結束的介入重播一份過期的「還在等你點」。
        self._replay: list[tuple[str, bytes]] = []
        self._recording = False

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """WebIPC thread 啟動後注入 event loop（broadcast 用）。

        Task 10 的 WebIPCThread.start 在 uvicorn server 起來後呼叫；
        在此之前 broadcast 直接 return（server 還沒跑起來，沒人可送）。
        """
        self._loop = loop

    async def attach(self, ws: WebSocket) -> None:
        """新連線併入廣播池：先補送目前這輪介入，補完才開始收廣播。

        兩件事的順序不可反（2026-07-30）：舊版是 `add` 完才 `replay_to`，兩者之間
        bot 主執行緒正在推的那批圖會**既走 broadcast 送一次、又被重播再送一次**。
        client 靠「meta 後面緊接的那張 binary 就是它的圖」配對（見
        `_send_web_intervention_frames`），多出來的 meta 會把後面每張圖都推移一格 →
        圖落在錯的方位格。實測：滿載跑 tests/test_web_server_real_socket.py 時
        layer 收到 ['mid','up','mid'] 而不是 ['mid','up']。玩家的實際用法正是
        「被提醒才連進來」，連上時機就落在 push 進行中，這條 race 在實機必然踩到。

        修法＝把「重播緩衝已無新內容」與「併池」放進同一個 lock 區段，配合
        `_record_replay` 在**錄製當下**就固定收件人清單：任一則訊息對任一條連線，
        要嘛在併池前被錄進 replay（由這裡送），要嘛在併池後才錄（由 broadcast 送），
        不可能兩者皆是。併池後到 return 之間沒有 await，live 廣播插不進重播序列中間。
        """
        sent = 0
        while True:
            with self._lock:
                items = self._replay[sent:]
                if not items:
                    self._connections.add(ws)
                    return
            if not await self._send_items(ws, items):
                return          # 連線已斷；endpoint 的 finally 會 remove（discard 冪等）
            sent += len(items)
            # ponytail: 推播比重播快就會多繞一圈；一輪介入上限 ~17 則，實務上跑 1-2 圈。

    def remove(self, ws: WebSocket) -> None:
        with self._lock:
            self._connections.discard(ws)

    def begin_intervention_replay(self) -> None:
        """新一輪介入開始：清掉舊緩衝、開始記錄接下來的 broadcast/broadcast_binary。"""
        with self._lock:
            self._replay = []
            self._recording = True

    def end_intervention_replay(self) -> None:
        """這輪介入結束（成功/失敗/逾時退回 Discord）：停止記錄＋清緩衝。

        沒清的話下一個連進來的 client（哪怕介入早就結束）還是會重播一份
        「還在等你點」的過期畫面——比空白更誤導。
        """
        with self._lock:
            self._recording = False
            self._replay = []

    async def _send_items(self, ws: WebSocket, items) -> bool:
        """把 (kind, payload) 序列依序送給單一連線；送失敗回 False（連線已斷）。"""
        for kind, payload in items:
            try:
                if kind == "text":
                    await ws.send_text(payload)
                else:
                    await ws.send_bytes(payload)
            except Exception as e:
                _log.warning("web: 重播給新連線失敗: %s", e)
                return False
        return True

    async def replay_to(self, ws: WebSocket) -> None:
        """補送目前這輪介入的完整序列（如果有的話）給指定連線。

        沒有 recording 中的介入就是 no-op——正常 idle 連線不受影響。
        併池請走 `attach`（含防重複的分段重播）；這支只補送、不動連線池。
        """
        with self._lock:
            items = list(self._replay)
        await self._send_items(ws, items)

    def _record_replay(self, kind: str, payload) -> list:
        """錄進重播緩衝，並回傳「這一則的收件人」快照。

        收件人必須在這裡（錄製當下、同一個 lock 區段）就固定，不能等 coroutine 真的
        被 event loop 排到才去看 `self._connections`——那之間新連線可能已經併池，
        於是同一則訊息被 broadcast 與 `attach` 的重播各送一次（見 `attach`）。
        """
        with self._lock:
            if self._recording:
                self._replay.append((kind, payload))
            return list(self._connections)

    def broadcast(self, msg: WebMessage) -> None:
        """同步呼叫介面（事件 sink 用）；內部丟進 event loop 跑。"""
        text = serialize_message(msg)
        conns = self._record_replay("text", text)
        if self._loop is None or not conns:
            return  # server 還沒跑起來／當下沒人連著（晚到的連線靠 replay 補）
        asyncio.run_coroutine_threadsafe(self._broadcast_async(conns, text), self._loop)

    async def _broadcast_async(self, conns, text: str) -> None:
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception as e:
                _log.warning("web: broadcast send 失敗（連線可能已斷）: %s", e)
                self.remove(ws)

    def broadcast_binary(self, data: bytes) -> None:
        """截圖 push 用（Task 10 在 main.py 裡接）。"""
        conns = self._record_replay("binary", data)
        if self._loop is None or not conns:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_binary_async(conns, data), self._loop)

    async def _broadcast_binary_async(self, conns, data: bytes) -> None:
        for ws in conns:
            try:
                await ws.send_bytes(data)
            except Exception as e:
                _log.warning("web: binary broadcast 失敗: %s", e)
                self.remove(ws)


def create_app(
    pending: PendingReplies,
    fallback: FallbackState,
    broadcast_callback: Callable[[WebMessage], None] | None,
    on_startup: Callable[[asyncio.AbstractEventLoop], None] | None = None,
    config=None,
    overrides_path: str | None = None,
    snapshot_index_path: str | None = None,
    fixtures_dir: str | None = None,
    snapshots_root: str | None = None,
    negatives_dir: str | None = None,
    ping_interval_s: float = 30.0,
    undo_window_s: float = _UNDO_WINDOW_FALLBACK_S,   # Ctrl+Z 還原限時（spec 05）
    layer_getter: Callable[[], dict] | None = None,
    player_state_getter: Callable[[], dict] | None = None,
) -> FastAPI:
    """建 FastAPI app。

    broadcast_callback：事件到達時呼叫（WebEventSink 用同一個 callback）。
        若傳 None，自動接到 registry.broadcast（production 路徑）；測試可注入
        自訂 callback 觀察廣播呼叫。
    on_startup：可選啟動回呼，在 uvicorn lifespan startup 階段（loop 已跑起來）
        被呼叫，傳入當下 event loop。WebIPCThread 用它把 loop 注入 registry，
        讓 broadcast 的 run_coroutine_threadsafe 有 loop 可 schedule。測試不傳。
    config：P3 玩家設定面板用——傳入 Config instance 時掛 `GET/POST /api/config`
        與 `GET /`（HTML）三條 route；不傳則只保留 P1 既有 routes（向下相容）。
    overrides_path：P3 持久化路徑；傳入時啟動讀回套用、POST 寫回。可選。
    snapshot_index_path：P5 Task 6 歷史/標註面板用——snapshot_index.jsonl 路徑
        （通常 ``<log_dir>/snapshot_index.jsonl``）。未傳時 history/episode/history
        HTML 三條 route 回 503；annotate HTML 不靠它（只渲染表單）。
    fixtures_dir：P5 Task 6 標註寫入目標目錄（如 ``tests/fixtures``）。未傳時
        POST /api/annotate 回 503。
    layer_getter：目標層同步用（2026-07-26）。回一個 dict：
        ``{"effective": str, "world": str|None, "from_world_map": bool}``。
        傳入時 ``GET /api/config`` 的 ``reentry_target_layer`` 與 ``GET /`` 的表單
        現值都改用 ``effective``——也就是 **bot 當下真正會用的層**，而不是
        ``cfg.reentry_target_layer`` 這個 fallback 預設值。

        為什麼需要它：Discord 的 `層` 指令寫的是**每世界黏性層 map**
        （``sticky_layers.json``，見 main._rr_execute 的 "layer" 分支），
        執行期優先序是 ``sticky_layers[world] > cfg.reentry_target_layer``。
        網頁先前只讀後者，於是 Discord 明明已經把 Lucernia 記成 Shamrock，
        設定頁還是顯示 "Mantle Layer"——兩邊各講各的（2026-07-26 實機確認）。

        不傳（None）時完全走舊行為：讀寫都只碰 cfg.reentry_target_layer。
        測試與任何不帶 bot 的呼叫端因此不受影響。
    ping_interval_s：P4 WebSocket heartbeat 間隔（秒）。**P5 Task 2 已退役**——
        text-message "ping" 只能在 TCP 全斷才拋例外，無法偵測手機背景化／
        Tailscale relay 半斷的 half-open 連線；改依賴 uvicorn 預設 20s 協議級
        ping frame（真正的 keep-alive）。參數保留以免破壞既有呼叫端，但 ws_endpoint
        不再讀它（silent ignored）。詳見 Config.websocket_ping_interval_s 註解。

    player_state_getter：雷達開關同步用（2026-07-28；保留清單已從網頁移除）。
        回一個 dict：``{"radar": {"scan": bool, "cave": bool}}``——雷達開關是
        Bot 執行期的可變狀態（不是 Config 欄位），沒有 getter 就沒有
        「網頁載入時要顯示什麼現值」的資料來源。掛 `GET /api/player`；不傳則
        該 route 回空殼（radar={}），不 500。

    lifespan 注入（uvicorn 0.51+）：原本 brief 的 `config.lifespan = patched` 行不通
    （uvicorn 0.51 的 config.lifespan 是字串 "auto"，不是 callable）；改用 FastAPI
    的 lifespan context manager，副作用是低且與 TestClient 相容。
    """
    @asynccontextmanager
    async def _lifespan(app):
        if on_startup is not None:
            on_startup(asyncio.get_running_loop())
        yield

    app = FastAPI(title="MiningBot Web IPC", lifespan=_lifespan)
    registry = ConnectionRegistry()
    app.state.registry = registry
    if broadcast_callback is None:
        broadcast_callback = registry.broadcast
    app.state.broadcast = broadcast_callback  # 測試與 sink 直接呼叫

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/intervention")
    def intervention():
        """P4 Task 6：介入面板 HTML（pinch-zoom canvas + tap UI）。

        純前端：連 /ws → 收 INTERVENTION_NEEDED event + binary PNG → 顯示 →
        玩家 pinch/scroll zoom + tap → 送 fire_at / reentry_click。
        不需 Config；unconditional mount（手機開瀏覽器直接連 URL）。
        """
        from miningbot.web_static import render_intervention_html
        return Response(
            content=render_intervention_html(),
            media_type="text/html",
        )

    # ── P5 Task 6：歷史紀錄 + 標註 endpoints（unconditional mount） ─────────
    app.state.snapshot_index_path = snapshot_index_path
    app.state.fixtures_dir = fixtures_dir
    app.state.snapshots_root = snapshots_root
    app.state.negatives_dir = negatives_dir

    @app.get("/snapshot")
    def get_snapshot(path: str):
        """把快照 PNG 送給瀏覽器（2026-07-26 補；先前完全沒有這條）。

        沒有它，`/annotate` 的 `<img src=...>` 永遠是破圖——標註工具（spec §5 C）
        整個不能用，而歷史頁的縮圖也無從顯示。後端把路徑寫進 snapshot_index.jsonl，
        前端卻拿不到圖，是典型的「兩邊各做一半」。

        Security：快照路徑來自 query string，等於讓外部指定要讀哪個檔。防護是
        **realpath 必須落在 snapshots_root 底下**——比字串比對可靠，symlink 與
        `..` 都會在 realpath 階段被攤平。另外只放行 .png，避免有人拿它讀 log/設定檔。
        （沿用 _is_safe_category 的教訓：路徑檢查一律在正規化**之後**做。）
        """
        target, reason = _safe_snapshot_target(path, snapshots_root)
        if target is None:
            return _err(reason[0], reason[1])
        try:
            with open(target, "rb") as f:
                data = f.read()
        except OSError as e:
            _log.warning("web: /snapshot 讀檔失敗 %s: %s", target, e)
            return _err(404, "snapshot unreadable")
        return Response(content=data, media_type="image/png")

    @app.get("/api/history")
    def get_api_history():
        """回所有 episode 列表（spec §5；web_history.load_episodes）。"""
        if snapshot_index_path is None:
            return _err(503, "history not configured")
        from miningbot.web_history import load_episodes
        return load_episodes(snapshot_index_path)

    @app.get("/api/episode/{episode_id}")
    def get_api_episode(episode_id: str):
        """回單一 episode 詳細；找不到 404；未配置 503。"""
        if snapshot_index_path is None:
            return _err(503, "history not configured")
        from miningbot.web_history import load_episode_detail
        detail = load_episode_detail(episode_id, snapshot_index_path)
        if detail is None:
            return _err(404, f"episode not found: {episode_id}")
        return detail

    @app.post("/api/annotate")
    def post_api_annotate(payload: dict):
        """驗證 annotation → 寫素材（crop+json 或全幀+json）。

        回 201 成功；400 schema 不通過；503 未配置目標目錄。

        **一般症狀**（FN/FP/該拒沒拒/對照組）→ `tests/fixtures/<category>/`，
        crop PNG + json，與 `/snapshot` 同一份路徑守門。
        PNG 先寫再寫 json，絕不留孤兒 json（先前正是這狀態：3 png 0 json）。

        **no_target**（人確認過的真陰性，2026-07-29）→ `<log_dir>/corpus/negatives/`，
        **全幀** PNG + json（偵測器吃的原圖格式，保留週邊脈絡）。全幀 1-3MB 不進 git
        （fixtures 全進版控），走 corpus/ 與 reentry 語料同一個 retention-immune 父層。
        `negatives_dir` 沒配置就退回只寫 json 並記 warning。

        category 推導順序：payload.category > image 路徑前綴 > 預設 "aim"。
        """
        from miningbot.web_annotation import validate_annotation
        if not validate_annotation(payload):
            return _err(400, "invalid annotation payload")
        image_field = payload["image"]
        stem = os.path.splitext(os.path.basename(image_field))[0]
        source_path = payload.get("source_path")
        record = {k: v for k, v in payload.items() if k != "source_path"}

        # ── no_target：存全幀到 corpus/negatives/ ────────────────────────
        if record.get("symptom") == "no_target":
            target_dir = negatives_dir
            if not target_dir:
                _log.warning(
                    "web: no_target 但 negatives_dir 未配置，只寫 json（%s）", stem)
            else:
                png_path = os.path.join(target_dir, stem + ".png")
                if not (isinstance(source_path, str) and source_path
                        and _copy_full_frame(source_path, png_path, snapshots_root)):
                    _log.warning(
                        "web: no_target 全幀複製失敗（%s），只寫 json", stem)
                    png_path = None
            try:
                if target_dir:
                    os.makedirs(target_dir, exist_ok=True)
                target_path = os.path.join(target_dir or "", stem + ".json")
                _atomic_write_json(target_path, record)
            except OSError as e:
                _log.warning("web: /api/annotate 寫入失敗 (%s): %s", target_path, e)
                return _err(500, f"write failed: {e}")
            # reentry 幀可以跑 teleport_board 判決（吃全幀）；追蹤框那條路
            # 需要粗格裁圖但 no_target 沒畫框 → annotation_verdict 回 None。
            import re as _re
            verdict_cat = ("reentry" if _re.search(r"reentry_ep\d+", image_field)
                           else None)
            verdict = annotation_verdict(
                verdict_cat, None,
                source_path if isinstance(source_path, str) else None,
                "no_target")
            content = {"ok": True, "path": target_path,
                       "category": "negatives", "png": png_path}
            if verdict is not None:
                content["verdict"] = verdict
            return JSONResponse(status_code=201, content=content)

        # ── 一般症狀：crop PNG + json 到 fixtures/<category>/ ─────────────
        if fixtures_dir is None:
            return _err(503, "history not configured")
        category = _derive_category(payload)
        target_dir = os.path.join(fixtures_dir, *category.split("/"))
        png_path = None
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as e:
            _log.warning("web: /api/annotate 建目錄失敗 (%s): %s", target_dir, e)
            return _err(500, f"write failed: {e}")

        if isinstance(source_path, str) and source_path:
            target, reason = _safe_snapshot_target(source_path, snapshots_root)
            if target is None:
                return _err(reason[0], f"source_path: {reason[1]}")
            ann = record["annotation"]
            png_path = os.path.join(target_dir, stem + ".png")
            ok, detail, local_cx, local_cy = _write_cell_crop_png(
                target, png_path, ann["cx"], ann["cy"])
            if not ok:
                _log.warning("web: /api/annotate 裁圖失敗 (%s): %s", png_path, detail)
                return _err(500, f"crop failed: {detail}")
            record["annotation"] = {**ann, "cx": local_cx, "cy": local_cy}
        else:
            _log.warning(
                "web: /api/annotate 沒帶 source_path，只寫 json（%s）——"
                "這張素材沒有配對裁圖，無法拿去加強偵測", stem)

        try:
            target_path = os.path.join(target_dir, stem + ".json")
            _atomic_write_json(target_path, record)
        except OSError as e:
            _log.warning("web: /api/annotate 寫入失敗 (%s): %s", target_path, e)
            return _err(500, f"write failed: {e}")
        verdict = annotation_verdict(
            category, png_path,
            source_path if isinstance(source_path, str) else None,
            record.get("symptom"))
        content = {"ok": True, "path": target_path, "category": category,
                   "png": png_path}
        if verdict is not None:
            content["verdict"] = verdict
        return JSONResponse(status_code=201, content=content)

    @app.post("/api/annotate/undo")
    def post_api_annotate_undo(payload: dict):
        """刪掉剛寫下的標註素材（json + 配對 png），讓那張快照回到待標佇列。

        玩家標錯的唯一補救：素材一落地就進了 `annotated_stems` 去重集合，那張圖
        從此不再排進佇列，錯的標註會被 tuning 迴圈當真。回 200 成功；404 找不到
        （已經刪過／根本沒寫成功）；400 缺 image；409 超過可還原時間（spec 05：
        只救當下誤按，不刪可能已進版控的舊素材）；503 目標目錄未配置。

        Security：只吃 basename，目錄一律自己推（`_derive_category` 同一份守門），
        絕不接受呼叫端給的路徑——不然這條 route 就是任意檔案刪除。
        """
        image = payload.get("image")
        stem = os.path.splitext(os.path.basename(image))[0] if isinstance(image, str) else ""
        if not stem:
            return _err(400, "image required")
        if payload.get("symptom") == "no_target":
            target_dir = negatives_dir          # 真陰性走 corpus/negatives/（全幀）
        elif fixtures_dir is None:
            return _err(503, "history not configured")
        else:
            target_dir = os.path.join(fixtures_dir,
                                      *_derive_category(payload).split("/"))
        if not target_dir:
            return _err(503, "negatives dir not configured")
        # 視窗閘（spec 05）：玩家情境是「剛按錯要重送」，15 分鐘剛好編碼那個情境；
        # 超時一律**一個檔都不刪**（可能已 commit 進版控）。找不到檔仍走 404。
        # 兩個副檔名都要查：json 已被手動刪掉、png 還在時，不查 png 等於放行任何年紀
        # 的孤兒圖。取最新的 mtime——只要其中一個是剛寫的，就還在「當下誤按」的情境裡。
        newest = None
        for ext in (".json", ".png"):
            path = os.path.join(target_dir, stem + ext)
            if os.path.isfile(path):
                mtime = os.path.getmtime(path)
                newest = mtime if newest is None else max(newest, mtime)
        if newest is not None:
            age = time.time() - newest
            if age > undo_window_s:
                return _err(409, "超過可還原時間——Ctrl+Z 只救剛剛的誤按")
        removed = []
        for ext in (".json", ".png"):
            path = os.path.join(target_dir, stem + ext)
            try:
                os.remove(path)
                removed.append(path)
            except FileNotFoundError:
                continue
            except OSError as e:
                _log.warning("web: /api/annotate/undo 刪除失敗 (%s): %s", path, e)
                return _err(500, f"delete failed: {e}")
        if not removed:
            return _err(404, "annotation not found")
        _log.info("web: 標註已還原 %s（刪 %d 檔）", stem, len(removed))
        return JSONResponse(status_code=200,
                            content={"ok": True, "removed": removed})

    _FAILURES_DEFAULT_LIMIT = 50

    def _failure_items(limit: int):
        """tier0 快照 + 現行偵測器判定；回 None 代表索引讀不到（呼叫端回 503）。

        判決來源就是 `/api/annotate` 那一支 `annotation_verdict`——沒有第二份實作。
        `verdict_category` 回 None 的（追蹤框那條路的全幀快照）不給判決並附理由：
        那支偵測器吃的是粗格裁圖，餵全幀等於給一個與 production 無關的答案。
        """
        if not snapshot_index_path or not index_readable(snapshot_index_path):
            return None
        rows = annotation_queue(snapshot_index_path, None, 0)
        items = []
        for row in rows[:limit]:
            category = verdict_category(row["label"])
            verdict = note = None
            if category is None:
                note = "全幀不是追蹤框偵測器吃的格式（需 320×270 粗格裁圖）——請走 /annotate"
            else:
                # NO_LABEL 而不是 None：這頁沒有玩家標籤可比，`None` 會被當成
                # 「對照組」而回一個憑空的 agree 給讀 JSON 的 agent。
                verdict = annotation_verdict(
                    category, None, row["path"], NO_LABEL)
                if verdict is None:
                    note = "偵測不可用（見 log）"
            items.append({**row, "verdict": verdict, "verdict_note": note})
        return {"total": len(rows), "shown": len(items), "limit": limit,
                "items": items}

    @app.get("/api/failures")
    def get_api_failures(limit: int = _FAILURES_DEFAULT_LIMIT):
        """agent 用 `curl` 抓的 JSON 版（與 `/failures` 同一份資料）。"""
        data = _failure_items(limit)
        if data is None:
            return _err(503, "snapshot index not available")
        return data

    @app.get("/failures")
    def get_failures(limit: int = _FAILURES_DEFAULT_LIMIT):
        """偵測失敗佇列（spec D4a）——tier0 快照集中一頁，每張附現行判定。

        這一頁的讀者是 agent，不是玩家：排版可以醜，資料要全。
        """
        data = _failure_items(limit)
        if data is None:
            return _err(503, "snapshot index not available")
        from miningbot.web_static import render_failures_html
        return Response(content=render_failures_html(data),
                        media_type="text/html")

    def _stats_data():
        """`load_stats` + 503 守門；回 None 代表索引讀不到。"""
        if not snapshot_index_path or not index_readable(snapshot_index_path):
            return None
        return load_stats(snapshot_index_path)

    @app.get("/api/stats")
    def get_api_stats():
        """agent 用 `curl` 抓的 JSON 版（與 `/stats` 同一份資料）。"""
        data = _stats_data()
        if data is None:
            return _err(503, "snapshot index not available")
        return data

    @app.get("/stats")
    def get_stats():
        """「什麼最常爆」統計（spec D4b）——先知道哪條最痛，才知道該修哪條。"""
        data = _stats_data()
        if data is None:
            return _err(503, "snapshot index not available")
        from miningbot.web_static import render_stats_html
        return Response(content=render_stats_html(data), media_type="text/html")

    @app.get("/history")
    def get_history():
        """歷史面板 HTML（Task 7 補完整 UI；Task 6 先 routing 通）。"""
        if snapshot_index_path is None:
            return _err(503, "history not configured")
        from miningbot.web_history import load_episodes
        from miningbot.web_static import render_history_html
        episodes = load_episodes(snapshot_index_path)
        return Response(
            content=render_history_html(episodes),
            media_type="text/html",
        )

    @app.get("/episode")
    def get_episode_page(id: str):
        """episode 詳細頁 HTML（spec §5 B）——時間軸 + 縮圖分組 + 標註歷程。

        2026-07-26 補：`/api/episode/{id}` 從 P5 就在，但沒有任何前端頁面用它。
        """
        if snapshot_index_path is None:
            return _err(503, "history not configured")
        from miningbot.web_history import (
            load_episode_detail, list_annotations_for_episode,
        )
        from miningbot.web_static import render_episode_html
        detail = load_episode_detail(id, snapshot_index_path)
        if detail is None:
            return _err(404, f"episode not found: {id}")
        # 素材檔名用**裸編號**（`auto_26_*.json`），不是 URL 上的 key（`reentry:26`）
        # ——這裡必須從 detail 取回裸編號，直接把 id 傳下去會一張標註都撈不到。
        annotations = (
            list_annotations_for_episode(
                str(detail.get("harvest_id", "")), fixtures_dir)
            if fixtures_dir else []
        )
        return Response(
            content=render_episode_html(detail, annotations),
            media_type="text/html",
        )

    @app.get("/annotate")
    def get_annotate(episode: str | None = None, snapshot: str | None = None,
                     queue: str | None = None):
        """標註工具 HTML（Task 7 補完整 UI；Task 6 先 routing 通）。

        不需 snapshot_index_path——只渲染表單。rarity_choices 從 game_data 撈。

        `?queue=tier0`（2026-07-28）：把所有 tier0 快照排成一串，一張接一張走。
        沒有這個佇列就永遠停在 2 張——tier 排序早就寫好了，缺的只是連續動線。
        索引沒配置就退回單張模式（不是錯誤，只是沒得排）。

        `?queue=tier0,tier2`（2026-07-31）：多個 tier 併成一串。tier0 全是 bot
        什麼都沒接受的圖（實測 227 張裡 220 張 `sweep_empty`），「bot 接受了但
        接錯」那兩個症狀只在 tier2 出現得了——導覽列的入口因此改指這一串。
        認不得的 tier 字樣直接略過；全都認不得就退回 tier0。

        2026-08-06：sweep_empty（八方掃描診斷比較地圖）從標註佇列濾除——
        標註無益；/api/failures 仍照常顯示（agent 排錯需要）。
        """
        from miningbot.web_static import render_annotate_html
        rarity_choices = _rarity_choices_from_game_data()
        rows = None                    # None＝沒進佇列模式（有別於「佇列是空的」）
        if queue and snapshot_index_path:
            from miningbot.web_history import annotation_queue
            tiers = [int(part[4:]) for part in queue.split(",")
                     if part.startswith("tier") and part[4:].isdigit()]
            rows = annotation_queue(snapshot_index_path, fixtures_dir,
                                    tiers or [0], negatives_dir=negatives_dir,
                                    exclude_sweep_empty=True)
        return Response(
            content=render_annotate_html(
                episode_id=episode or "",
                snapshot_path=snapshot or "",
                rarity_choices=rarity_choices,
                queue=rows,
            ),
            media_type="text/html",
        )

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        fallback.client_connected()
        # 連線進出要留痕（2026-07-29）：「網頁介入為什麼沒觸發」只能靠這個分辨
        # 「人根本沒連上」與「連上了但沒點」——先前兩者在 log 裡完全同形。
        _log.info("web: client 連上（目前 %d 條）", fallback.client_count)
        # 2026-07-27：使用者是「被提醒才連進來」，不是整場開著分頁——連上那一刻
        # 補送目前這輪介入（如果有的話），不然剛好連在 push 之後就永遠看不到。
        # 補送與併池是同一件事，必須由 attach 一起做（先 add 再重播會送出重複的
        # meta，把圖配到錯的方位——見 ConnectionRegistry.attach）。
        await registry.attach(websocket)
        # P5 Task 2：app-level text-message heartbeat 已退役——uvicorn 預設 20s
        # 協議級 ping frame 是真正的 keep-alive（半開連線 OS buffer 滿才會丟例外）；
        # text "ping" 只在 TCP 全斷才拋，無法偵測手機背景化／Tailscale relay 半斷。
        try:
            while True:
                text = await websocket.receive_text()
                msg = parse_message(text)
                if msg is None:
                    # 壞訊息不 crash，記 log
                    _log.warning("web: 收到不合法訊息，忽略: %r", text[:200])
                    continue
                if msg.type == "command":
                    _handle_command(msg.payload, pending)
                # P4: ping/pong 訊息由 WebSocket 協議層處理，這裡只接 text 不特別回應
                # event type 由 server 發、client 收；client 不該送 event，忽略
        except WebSocketDisconnect:
            pass
        except Exception as e:
            _log.warning("web: WebSocket 連線例外: %s", e)
        finally:
            registry.remove(websocket)
            fallback.client_disconnected()
            _log.info("web: client 斷線（剩 %d 條）", fallback.client_count)

    # P3: 玩家設定面板 endpoints（僅在傳入 config 時掛上；既有呼叫端不受影響）
    if config is not None:
        from miningbot.web_config_whitelist import (
            is_web_configurable, validate_value, WEB_CONFIGURABLE_FIELDS,
        )
        from miningbot.web_config_persistence import (
            load_overrides, save_overrides, apply_overrides_to_config,
        )

        # 啟動時讀 overrides 套用（building blocks；main.py Task 4 也會做一次冪等）
        # 不快取 in-memory overrides——save_overrides 會重讀檔，避免 HTTP/WS 兩條路徑
        # 各自維護 cache 導致相互覆寫（P3 final-review Important 1）。
        if overrides_path:
            initial_overrides = load_overrides(overrides_path)
            apply_overrides_to_config(config, initial_overrides)
            app.state.overrides_path = overrides_path
        else:
            app.state.overrides_path = None

        def _layer_info() -> dict | None:
            """目標層現況；layer_getter 未接或丟例外 → None（退回舊行為）。

            getter 讀的是 bot 執行緒的狀態，只做純字串讀取（不 mutate），
            但仍包 try——網頁面板壞掉不該是「設定頁整頁 500」。
            """
            if layer_getter is None:
                return None
            try:
                info = layer_getter()
            except Exception as e:
                _log.warning("web: layer_getter 失敗（退回 config 值）: %s", e)
                return None
            return info if isinstance(info, dict) else None

        @app.get("/api/config")
        def get_config():
            """回白名單 4 欄現值（不洩漏門檻/ROI/機密）。

            reentry_target_layer 特別處理：接了 layer_getter 就回**執行期有效層**
            （sticky_layers[world] 優先），否則玩家會看到跟 Discord 不一致的值。
            """
            data = {f: getattr(config, f) for f in WEB_CONFIGURABLE_FIELDS}
            info = _layer_info()
            if info and isinstance(info.get("effective"), str):
                data["reentry_target_layer"] = info["effective"]
            return data

        @app.post("/api/config")
        def post_config(payload: dict):
            """驗證 → runtime 改 Config → 持久化 overrides JSON。

            三道閘：缺欄位 400、非白名單 400、值不通過 validate_value 400。
            """
            field = payload.get("field")
            value = payload.get("value")
            if field is None or value is None:
                return _err(400, "missing field or value")
            if not is_web_configurable(field):
                return _err(400, f"field not web-configurable: {field}")
            if not validate_value(field, value):
                return _err(400, f"invalid value for {field}: {value!r}")
            # runtime 即時生效
            setattr(config, field, value)
            # 偵測階級門檻：同步到 game_data 模組級變數（同 config setattr，純賦值無 I/O）
            if field == "detection_disabled_tiers":
                from miningbot.game_data import set_detection_disabled_tiers
                set_detection_disabled_tiers(value)
                # 推 pending 讓主迴圈發 Discord 確認（比照 set_layer；背景執行緒不做
                # Discord I/O）。值已即時生效，這裡只補「（來自網頁）」確認訊息，
                # 讓玩家知道改了什麼、現在偵測哪些階級——否則設了像沒設。
                pending.push("control:set_detection_tier", True)
            # 持久化（若有指定路徑）——不帶 current_overrides，save_overrides 自會重讀檔
            if app.state.overrides_path:
                save_overrides(app.state.overrides_path, field, value)
            # 目標層要跟 Discord `層` 指令做同一件事：釘住 session 黏性層 +
            # 記住「當前世界 → 層」+ 寫穿 sticky_layers.json。那需要 bot 的世界狀態
            # 與檔案寫入，都屬主迴圈執行緒——這裡只 push，由 _consume_web_pending 執行
            # （比照 control:config_set 的既有慣例；CLAUDE.md：背景執行緒只發布 pending）。
            #
            # 上面的 setattr + save_overrides 保留不動：它更新的是 fallback 預設值，
            # 對「世界尚未偵測到」與「其他世界」仍然有意義。萬一主迴圈忙碌讓 push 被
            # 拒（同 key 尚未消費），至少 fallback 已經生效，不會整個沒反應。
            queued = None
            if field == "reentry_target_layer" and layer_getter is not None:
                queued = pending.push("control:set_layer", {"layer": value})
                if not queued:
                    _log.warning("web: set_layer 排入失敗（上一則尚未消費）: %r", value)
            result = {"ok": True, "field": field, "value": value}
            if queued is not None:
                result["layer_queued"] = queued
            return result

        @app.get("/api/player")
        def get_player_state():
            """雷達開關現值（2026-07-28）：不是 Config 欄位，另開一條
            route——`player_state_getter` 沒接就回空殼，設定頁不因此整頁掛掉。
            """
            if player_state_getter is None:
                return {"radar": {}}
            try:
                state = player_state_getter()
            except Exception as e:
                _log.warning("web: player_state_getter 失敗（回空殼）: %s", e)
                return {"radar": {}}
            if not isinstance(state, dict):
                return {"radar": {}}
            return {"radar": state.get("radar", {})}

        @app.post("/api/radar")
        def post_radar(payload: dict):
            """D2 連續使用開關（掃描/削洞，2026-07-28）：非 Config 欄位、走
            pending 異步路徑。
            """
            which = payload.get("which")
            value = payload.get("value")
            if which not in ("scan", "cave") or not isinstance(value, bool):
                return _err(400, f"invalid payload: {payload!r}")
            pending.push("control:radar_toggle", {"which": which, "value": value})
            return {"ok": True, "which": which, "value": value}

        @app.get("/")
        def root():
            """玩家設定面板 HTML（Task 3 補完整內容）。"""
            from miningbot.web_static import render_index_html
            return Response(
                content=render_index_html(config, layer_info=_layer_info()),
                media_type="text/html",
            )

    return app


def _safe_snapshot_target(path: str, snapshots_root: str | None):
    """把外部給的快照路徑收斂成「可以讀的真實檔案」；回 (target, None) 或 (None, (status, reason))。

    路徑來自 query string／POST body，等於讓外部指定要讀哪個檔。防護是
    **realpath 必須落在 snapshots_root 底下**——比字串比對可靠，symlink 與
    `..` 都會在 realpath 階段被攤平。另外只放行 .png，避免有人拿它讀 log／設定檔。
    （沿用 _is_safe_category 的教訓：路徑檢查一律在正規化**之後**做。）

    /snapshot 與 /api/annotate 共用同一份守門——annotate 也要照著這個路徑去讀
    原始快照來裁 PNG，兩邊的安全性檢查不能各寫一套。
    """
    if snapshots_root is None:
        return None, (503, "snapshots root not configured")
    root = os.path.realpath(snapshots_root)
    target = os.path.realpath(path)
    if os.path.splitext(target)[1].lower() != ".png":
        return None, (400, "only .png is served")
    # commonpath 會在不同磁碟機時丟 ValueError（Windows），視同越界
    try:
        inside = os.path.commonpath([root, target]) == root
    except ValueError:
        inside = False
    if not inside:
        _log.warning("web: 拒絕越界快照路徑 %r（root=%r）", path, root)
        return None, (403, "path outside snapshots root")
    if not os.path.isfile(target):
        return None, (404, "snapshot not found")
    return target, None


def annotation_verdict(category: str, crop_png: str | None,
                       source_frame: str | None, symptom):
    """跑現行偵測器對這張素材，回 `verdict` dict；不可用時回 `None`。

    **降級規則（H061 的教訓）**：web 路徑要跑偵測器就會把 `cv2`/`vision` 這串相依
    拉進來。用 deferred import + try/except，缺件或偵測器拋例外時回 `None`
    （＝存檔照樣成功、回應不附 verdict），而且**降級要留一行 log**——H061 正是
    daemon thread 裡的 ImportError 噴進不存在的 stderr 而整個蒸發。

    哪一支偵測器：跟 production 實際跑的那支對齊，才有診斷價值。
    - `aim/`：`vision.detect_tracker_core` 吃 320×270 粗格裁圖（素材 PNG 就是這個
      格式，見 `web_annotation.cell_crop_box`）。
    - `reentry/`：`teleport_board.detect` 吃**全幀**——它的 ROI 是螢幕座標，餵裁圖
      等於把整張圖切在 ROI 外，判什麼都沒意義。所以這裡用原始快照。
    """
    try:
        import cv2
        import numpy as np

        from miningbot.config import DEFAULT as _cfg
        from miningbot.web_annotation import NO_LABEL, verdict_agrees

        def _load(path):
            if not path:
                return None
            return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

        # no_target：玩家確認「這張沒東西」。reentry 全幀可以跑 teleport_board；
        # 追蹤框那條路吃粗格裁圖但 no_target 沒有 cx/cy（沒畫框），無從裁——
        # 回 None（偵測不可用），存檔照樣成功。
        cat = category or ""
        if not cat:
            return None
        if cat.split("/", 1)[0] == "reentry":
            from miningbot import teleport_board
            frame = _load(source_frame)
            if frame is None:
                return None
            got = teleport_board.detect(frame)
            detector = "accepted" if got else "rejected"
            score = ({"score": round(float(got[2]), 3), "x": got[0], "y": got[1]}
                     if got else {})
        else:
            from miningbot import vision
            crop = _load(crop_png)
            if crop is None:
                return None
            hit = vision.detect_tracker_core(
                crop, _cfg.tracker_core_profiles,
                min_area=_cfg.tracker_core_min_area,
                max_area=_cfg.tracker_core_max_area,
                ar_lo=_cfg.tracker_core_ar_lo, ar_hi=_cfg.tracker_core_ar_hi,
                extent_min=_cfg.tracker_core_extent_min,
                border_margin=_cfg.tracker_core_border_margin,
                border_dark_max=_cfg.tracker_core_border_dark_max,
                border_dark_frac_min=_cfg.tracker_core_border_dark_frac_min)
            detector = "accepted" if hit else "rejected"
            score = ({"profile": hit[2], "border_frac": round(float(hit[3]), 3),
                      "x": hit[0], "y": hit[1]} if hit else {})
    except Exception as e:
        _log.warning("web: /api/annotate 回判決降級（偵測不可用，存檔不受影響）：%r", e)
        return None
    labelled = symptom != NO_LABEL
    return {"detector": detector, "score": score,
            "your_label": symptom if labelled else None,
            "agree": verdict_agrees(detector, symptom) if labelled else None}


def _copy_full_frame(source_path: str, target_png: str, snapshots_root) -> bool:
    """把原始全幀快照**原樣**複製到 corpus/negatives/（no_target 用）。

    走跟 `_safe_snapshot_target` 同一份路徑守門——外部送進來的路徑不得越界。
    用 `np.fromfile` + `imencode` + `tofile` 而不是 `shutil.copy`：同一份 code
    在中文路徑下 `cv2.imwrite` 會靜默失敗（見 `tests/fixtures/README.md`），
    保持一致的 CJK-safe I/O 比省一次 decode/encode 更重要。
    """
    target, reason = _safe_snapshot_target(source_path, snapshots_root)
    if target is None:
        return False
    try:
        import cv2
        import numpy as np
        buf = np.fromfile(target, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            return False
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            return False
        os.makedirs(os.path.dirname(target_png), exist_ok=True)
        encoded.tofile(target_png)
        return True
    except (OSError, ValueError):
        return False


def _write_cell_crop_png(source_path: str, target_png: str, cx: int, cy: int):
    """從原始全幀裁出粗格大小的 crop 寫成素材 PNG；回 (ok, detail, local_cx, local_cy)。

    spec §5「每張 2 檔」：`<name>.png` 是**檢測函式輸入格式**的裁圖，`<name>.json`
    是 metadata。先前手動標註只寫 json，產出的是指向不存在檔案的孤兒——而
    `aim/` 素材的用途正是「加強目標框偵測」，沒有那張裁圖就完全沒有價值。

    座標換算：回傳的 local_cx/local_cy 是方框中心在**裁圖內**的座標。這與自動
    收集路徑的 `annotation_xy` 語意一致（main.py 傳 `(x - cx0, y - cy0)`），
    也對得上 spec 的範例（`cx: 211, cy: 189` 落在 320×270 裡）。

    CJK path safety（tests/fixtures/README.md 硬規則）：`cv2.imread` / `imwrite`
    在中文路徑下會**靜默失敗**，一律走 `np.fromfile` + `imdecode` /
    `imencode` + `tofile`。這個 repo 的路徑就含中文，踩過。
    """
    import cv2
    import numpy as np

    try:
        buf = np.fromfile(source_path, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except (OSError, ValueError) as e:
        return False, f"讀取原始快照失敗: {e}", 0, 0
    if frame is None:
        return False, "原始快照無法解碼", 0, 0
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = cell_crop_box(w, h, cx, cy)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return False, f"裁圖為空（cx={cx}, cy={cy}, frame={w}x{h}）", 0, 0
    try:
        ok, encoded = cv2.imencode(".png", crop)
        if not ok:
            return False, "PNG encode 失敗", 0, 0
        encoded.tofile(target_png)
    except (OSError, ValueError) as e:
        return False, f"寫入素材 PNG 失敗: {e}", 0, 0
    return True, None, int(cx) - x0, int(cy) - y0


def _err(status: int, reason: str) -> JSONResponse:
    """統一 JSON 錯誤回應（HTTP 狀態碼 + reason）。"""
    return JSONResponse(status_code=status, content={"error": reason})


def _derive_category(payload: dict) -> str:
    """從 payload 推 fixtures 子目錄：payload.category > image 前綴 > "aim"。

    payload 显式帶 ``category`` 時（如 "reentry/teleport_board"）優先採用；
    否則看 image 是否含路徑前綴（如 "reentry/teleport_board/x.png"）；
    都沒有就用 "aim"（spec §5：玩家最常標註 harvest 手動瞄準素材）。

    Security：不容許絕對路徑或任何 ``..`` 元件跳出 ``fixtures_dir``。檢查
    走 ``_is_safe_category``——跨平台關鍵在 ``PurePath.parts`` 同時識別
    ``\\`` 與 ``/``，舊版 ``norm.split("/")`` 在 Windows 會把 ``"..\\foo"``
    當成單一 element 而漏判 ``..``（CVE-style bypass）。
    """
    cat = payload.get("category")
    if isinstance(cat, str) and cat and _is_safe_category(cat):
        return os.path.normpath(cat).lstrip(os.sep).lstrip("/")
    image = payload.get("image")
    if isinstance(image, str) and "/" in image:
        head = os.path.dirname(image)
        if head and _is_safe_category(head):
            return os.path.normpath(head).lstrip(os.sep).lstrip("/")
    return "aim"


def _is_safe_category(path: str) -> bool:
    """原始 category / image-prefix 字串是否安全當 fixtures 子目錄。

    跨平台關鍵：``PurePath.parts`` 同時識別 ``\\`` 與 ``/``，是 ``..`` 偵測
    最可靠的 API；不能用 ``split("/")``——``os.path.normpath("../foo")``
    在 Windows 回 ``"..\\foo"``，``split("/")`` 視為單一 element 而漏判。
    ``os.path.isabs`` 補上 ``C:\\`` / UNC / POSIX 絕對路徑（``/etc/passwd``
    在 Windows 上也被認定為 abs，避免 ``os.path.join`` 重置回絕對根）。
    """
    if not path or os.path.isabs(path):
        return False
    return ".." not in PurePath(path).parts


def _atomic_write_json(target_path: str, data: dict) -> None:
    """tempfile + os.replace 原子寫 JSON；與 P5 Task 5 main.py 一致。"""
    tmp_path = target_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp_path, target_path)


def _rarity_choices_from_game_data() -> tuple[list[str], list[str]]:
    """從 game_data.rare_ores() 撈 tier 清單；檔缺/壞 → 空 list。

    純读取 game_data 全域快取；rare_ores 已有 try/except 容錯。未啟動 world
    時回全世界聯集（保守，spec §5：寧可多列型別讓玩家選）。
    """
    try:
        from miningbot.game_data import rare_ores
        from miningbot.web_annotation import rarity_choices_from_game_data
        return rarity_choices_from_game_data(list(rare_ores().values()))
    except Exception as e:
        _log.warning("web: rarity_choices 撈取失敗（fallback 空 list）: %s", e)
        return [], ["原色", "Spectral", "Ionized"]


def _handle_command(payload: dict, pending: PendingReplies) -> None:
    """把 command payload 解析後 push 進 PendingReplies。

    P5 Task 1 協議重設：fire_at / reentry_click 改走 thin validator，
    client 端 JS 自己換算原生座標；server 不再收 canvas_size/zoom/pan_offset。
    其他命令沿用 P1 行為（control:* routing key）。

    payload 結構：
    - fire_at / reentry_click：必有 flow + harvest_id（或 attempt_id）+ x + y
      （P5 Task 1 schema；x/y 是 int 範圍 [0, 1920) / [0, 1080)）
    - config_set：必有 field + value（白名單驗證在 main.py 整合時做）
    - pause / resume / request_frame：控制類，無 routing key，用 "control:*"
    - skip / reroll / sweep（2026-07-26 回礦面板三顆按鈕）：同樣走 "control:*"，
      由 main._await_web_reentry_action 在等待迴圈裡直接撿——主迴圈此刻卡在
      介入等待中，`_consume_web_pending` 跑不到，只靠它們會等到本輪逾時才生效。

    若 payload 缺 routing key 必要欄位或 parse 失敗，記 log 不 push（防護）。
    """
    cmd = payload.get("cmd")
    if cmd in ("fire_at", "reentry_click"):
        parser = parse_fire_at_payload if cmd == "fire_at" else parse_reentry_click_payload
        parsed = parser(payload)
        if parsed is None:
            _log.warning("web: %s payload invalid: %r", cmd, payload)
            return
        flow = parsed["flow"]
        ep_id = parsed.get("harvest_id") or parsed.get("attempt_id")
        if not flow or not ep_id:
            _log.warning("web: %s 缺 flow/episode_id", cmd)
            return
        key = f"{flow}:{ep_id}"
        pending.push(key, parsed)
        return
    # 既有 control:* 路徑（pause / resume / config_set / request_frame 等）
    if cmd is not None:
        pending.push(f"control:{cmd}", payload)


class WebIPCThread:
    """WebIPC daemon thread：跑 uvicorn server（spec §8）。

    port=0：作業系統隨機分配；actual_port 在 server socket bind 完後填。
    bot 啟動時 start()（比照 Discord polling thread；main.py:2308 區段），
    關機時 stop()＋join()。

    loop 注入（uvicorn 0.51+）：brief 原本 `config.lifespan = patched` 在 uvicorn
    0.51 行不通（config.lifespan 是字串 "auto"，不是 callable）；改走 FastAPI
    lifespan——on_startup callback 在 uvicorn lifespan startup 內被呼叫，
    當下 loop 即 server loop，交給 registry.set_loop，broadcast 即可用
    run_coroutine_threadsafe 跨 thread 投遞。

    actual_port 不在 lifespan 內取（lifespan 啟動時 asyncio.Server 尚未建立，
    srv.sockets 是空的）；改在 start() 內 polling 等 socket bind 完（< 5s）。
    """

    def __init__(
        self,
        pending: PendingReplies,
        fallback: FallbackState,
        port: int = 8765,
        host: str = "127.0.0.1",
        config=None,
        overrides_path: str | None = None,
        snapshot_index_path: str | None = None,
        fixtures_dir: str | None = None,
        snapshots_root: str | None = None,
        negatives_dir: str | None = None,
        undo_window_s: float = _UNDO_WINDOW_FALLBACK_S,
        layer_getter: Callable[[], dict] | None = None,
        player_state_getter: Callable[[], dict] | None = None,
    ):
        self.pending = pending
        self.fallback = fallback
        self.port = port
        self.host = host  # 綁 127.0.0.1（spec §2：Tailscale Serve 在外層出 HTTPS）
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self.actual_port: int = 0
        # P4: 從 Config 讀 WebSocket heartbeat 間隔；未傳 config 走 create_app 預設 30s。
        ping_interval_s = (
            getattr(config, "websocket_ping_interval_s", 30.0)
            if config is not None else 30.0
        )
        # P3：config + overrides_path 傳給 create_app，讓 HTTP endpoints
        # （GET/POST /api/config、GET /）能在 thread 內掛上。不傳時向下相容（P1 既有測試）。
        # P5：snapshot_index_path + fixtures_dir 必須從 Bot.__init__ 顯式轉發，
        # 否則 create_app 預設 None → /api/history、/api/episode、/api/annotate、
        # /history 全回 503（main.py 是 production 路徑唯一呼叫端）。
        self.app = create_app(
            pending, fallback, broadcast_callback=None,
            on_startup=self._on_startup,
            config=config, overrides_path=overrides_path,
            snapshot_index_path=snapshot_index_path,
            fixtures_dir=fixtures_dir,
            snapshots_root=snapshots_root,
            negatives_dir=negatives_dir,
            undo_window_s=undo_window_s,
            ping_interval_s=ping_interval_s,
            layer_getter=layer_getter,
            player_state_getter=player_state_getter,
        )

    def _on_startup(self, loop: asyncio.AbstractEventLoop) -> None:
        """在 uvicorn event loop 內被呼叫：把 loop 注入 registry。

        broadcast_callback 走 registry.broadcast→run_coroutine_threadsafe，
        需要這個 loop 當 schedule target。
        """
        self.app.state.registry.set_loop(loop)

    def start(self, bind_wait_s: float = 20.0) -> None:
        """啟動 uvicorn daemon thread；阻塞到 actual_port 已知或 `bind_wait_s` 超時。

        port=0 時 actual_port 是 OS 分配的隨機 port；呼叫端可接著 log 出 URL。

        預設 5.0→20.0（2026-07-29 實機，見 Config.web_server_bind_wait_s）：超時**不是**
        「這個位址綁不上」的證據——真綁不上時 uvicorn 自己會設 should_exit，下面的迴圈
        立刻跳出。超時只代表 uvicorn 第一次啟動的一次性成本還沒付完（主執行緒忙著
        Bot.__init__ 時特別容易），砍掉它反而害呼叫端誤判位址不通、退回 127.0.0.1。
        """
        if self._thread is not None:
            return  # 已啟動（冪等）
        # log_config=None 是**必要**的，不是偏好（2026-07-26 實機）：
        # uvicorn 預設 log_config 內含 `uvicorn.logging.DefaultFormatter`，它的
        # __init__ 無條件呼叫 `sys.stdout.isatty()`。實機用 `pythonw -m miningbot`
        # 啟動，pythonw **沒有 stdout**（`sys.stdout is None`）→ AttributeError →
        # logging.config.dictConfig 失敗 → `ValueError: Unable to configure
        # formatter 'default'` 直接從 uvicorn.Config(...) 拋出來，bot 執行緒當場死。
        # ⚠ 注意這發生在 **Config 建構時**，不是 import 時——所以「import 時
        # dictConfig 0 calls」的檢查看起來乾淨卻毫無保護力。
        #
        # 設 None 之後 uvicorn 完全不碰 logging 設定。
        #
        # ⚠ 這裡原本寫「它的 logger 直接 propagate 到 root，由 diagnostics.setup_logging
        # 收進 miningbot.log」——**那是錯的**：setup_logging 只掛 handler 在 `miningbot`
        # logger，root 從頭到尾沒有任何 handler，pythonw 又沒有 stderr，所以 uvicorn 印的
        # 東西全部蒸發。2026-07-26 因此漏掉「缺 websockets → /ws 回 404」整整一輪：
        # uvicorn 其實有印 `No supported WebSocket library detected`，只是沒人接。
        # 現在由 diagnostics._ADOPTED_LOGGERS 顯式收編 `uvicorn` logger（propagate=False
        # + 同一份 miningbot.log handler），uvicorn 訊息才真的跟 bot 敘事同檔。
        #
        # log_level="warning" 即使在 log_config=None 下也會被套用到
        # uvicorn.error/access/asgi（見 uvicorn/config.py configure_logging），
        # 所以收編後不會有每個 HTTP 請求一行的 access log 噪音。
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",  # uvicorn 預設 info 太吵；warning 即可
            log_config=None,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="web-ipc"
        )
        self._thread.start()
        # 等 uvicorn bind 完 socket 才能讀 actual_port（lifespan startup 階段
        # servers 還沒建立；這裡 polling 是簡單可靠的解法，< 5s）。
        # `servers` 屬性在 startup() 跑完前不存在，用 getattr 避免 AttributeError。
        deadline = time.monotonic() + bind_wait_s
        while time.monotonic() < deadline:
            servers = getattr(self._server, "servers", None) or []
            for srv in servers:
                if srv.sockets:
                    self.actual_port = srv.sockets[0].getsockname()[1]
                    break
            if self.actual_port > 0:
                break
            if self._server.should_exit:
                break  # uvicorn 綁失敗（例如 port 被佔）；讓 actual_port 留 0
            time.sleep(0.02)
        # 超時仍無 actual_port：silent return 會讓呼叫端 log 出 http://127.0.0.1:0
        # 看似成功；這裡顯式警告＋請求 thread 退出，避免 daemon 殘留與假啟動訊息。
        # ⚠ 兩種情況要分開講（2026-07-29 排錯教訓：舊訊息把兩者寫成一句「可能還在
        # init 或綁失敗」，害人以為 Tailscale 沒起來，實際是超時太短）：
        #   should_exit=True  → uvicorn 自己判定綁不上（位址不存在／port 被佔）。
        #   should_exit=False → 還沒綁到失敗那一步，純粹是 bind_wait_s 不夠。
        if self.actual_port == 0:
            if self._server.should_exit:
                _log.warning(
                    "WebIPC server 綁不上 %s:%s（uvicorn 已自行放棄；位址不存在或 "
                    "port 被佔）——actual_port 留 0", self.host, self.port)
            else:
                _log.warning(
                    "WebIPC server %.0fs 內未 bind socket，但 uvicorn 沒判定失敗"
                    "（should_exit=False）＝**還在 init、不是位址不通**；"
                    "調大 Config.web_server_bind_wait_s 再看——已請求 thread 退出",
                    bind_wait_s)
            self._server.should_exit = True

    def stop(self) -> None:
        """設 should_exit=True，uvicorn 主迴圈下一輪會收掉。"""
        if self._server is not None:
            self._server.should_exit = True

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
