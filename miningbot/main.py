import os
import sys
import math
import time
import logging
import ctypes
import json
import threading
import queue
import itertools

import numpy as np

from .config import (DEFAULT as cfg, resolve_log_dir,
                     resolve_runtime_log_path)
from .events import EventLog, make_file_sink
from .states import (State, Observation, decide_transition, resolve_state_transition,
                     toggle_pause_action, is_blocked_from_mining, can_consume_ability,
                     should_notify_spawn_chill, update_capacity_streak,
                     can_accept_manual_reentry, can_consume_rotate)
from . import capture, vision, ocr, audio, miner, harvester, diagnostics, window, game_data, metrics
from . import sampler, reentry, roblox_menu, remote_aim, reentry_remote, discord_commands
# notify 純 stdlib（urllib/json），放模組層同樣是 H061 的一環：原本各處都用
# `from . import notify` deferred import，其中 Bot.__init__ 那次已排在 OCR worker
# thread 之後。函式內既有的 local import 保留不動（從 sys.modules 取，無 import 工作）。
from . import notify
# web_config_persistence / web_config_whitelist 是純 Python（json + os），跟 web_server
# 那條 fastapi 重型鏈無關，但同樣不放在 thread 啟動之後才 import（H061 通則）。
from . import web_config_persistence
from .web_config_whitelist import is_web_configurable, validate_value
from . import calibrate_pitch
from . import input_control as ic
from .preflight import PreflightFacts, run_checks

# H061（2026-07-26）：web 模組（fastapi/uvicorn/starlette，實機 import 鏈 ~5.7s）**必須**
# 在模組層 import，不可 deferred 到 Bot.run() 內。
#
# 真根因（`de1f4c4` 實機定位）：`Bot.run()` 跑在 daemon thread，舊碼在那裡才 deferred import
# web 模組；實機直譯器（`pythonw -m miningbot` ＝ Microsoft Store 版 Python，跟 `uv sync` 灌的
# .venv 是兩個環境）當時**沒裝 fastapi/uvicorn** → ModuleNotFoundError 在 worker thread 拋出
# → pythonw 沒有 console，Python 預設的 threading.excepthook 把 traceback 印到不存在的
# stderr → **整個失敗蒸發**。實機症狀（只挖 D1、D2/D4/D5 沒了、稀有礦不處理、last_action
# 停在俯仰歸位、遙控器沒出來、log 不再增長）全是「執行緒早就死了」，不是卡住。
#
# ⚠ 調查期間曾判定成「多執行緒同時 deferred import C 擴展 → import lock 死結」，**那個結論
# 是錯的**：mini repro 用 `uv run` 跑（venv 有 uvicorn），整條調查比對了錯的直譯器。查實機
# 問題第一件事＝確認 production 與重現環境是不是同一顆 Python（`Bot.__init__` 現在會印
# `interpreter:`）。完整敘事見 `docs/incidents.md` H061。
#
# 模組層 import 仍是對的做法：整條鏈在 `from miningbot.main import main`（__main__.py）期間
# 就跑完，那時只有 Tk splash、零個 bot thread。splash 會多顯示數秒，這是刻意的：
# __main__.py 的載入視窗本來就是為重型 import 準備的。
#
# ⚠ 不要因為「啟動慢」把這段搬回 run() 或改成 lazy import——缺件會再度變成 worker thread
# 內的無聲死亡。同理，未來新增任何重型第三方 import 都放模組層，不要放進 thread 已啟動
# 之後的路徑。另外兩道防線也別拆：`status_hud._run_bot_guarded`（執行緒 crash 必留 log ＋
# 彈框）與 `run()` 內 WebIPC 區塊的 try/except（web 壞掉不可停止挖礦）。
#
# fastapi/uvicorn 缺件時**降級不中斷**：實機用 `pythonw -m miningbot`（Microsoft Store
# 版 Python）跑，那個直譯器跟 `uv sync` 灌的 .venv 是兩個環境——H061 的真正起點就是
# 「.venv 有 uvicorn、實機直譯器沒有」。這裡吞掉 ImportError 並關掉 web 子系統，讓挖礦
# 照跑（每條 web 路徑都守 _web_pending is None，會自動退回 Discord fallback）。
# 沿用本專案既有慣例：外部引擎/素材缺件時降級 + 明確警告，不靜默改變行為。
WEB_IMPORT_ERROR: str | None = None
if cfg.web_server_enabled:
    try:
        from . import web_server as _web_server_preload   # noqa: F401
        from . import web_ipc as _web_ipc_preload         # noqa: F401
        from . import web_sink as _web_sink_preload       # noqa: F401
    except ImportError as _web_import_exc:                # pragma: no cover - 環境相依
        WEB_IMPORT_ERROR = (
            f"{_web_import_exc}（直譯器 {sys.executable}）")
        cfg.web_server_enabled = False

# 遙控器（持久控制訊息）— 反應按鈕。▶️ 繼續挖礦（等同 Q / !resume），⏸️ 暫停（等同 Ctrl+Q / !pause）。
# 用 emoji 而非 Discord Components 按鈕：本專案全程 stdlib urllib，無 Websocket/interaction 基礎建設；
# 反應輪詢模式已由 !list 分頁驗證可行（_poll_list_reactions），沿用同一條路徑最簡。
_REMOTE_RESUME_EMOJI = "▶️"
_REMOTE_PAUSE_EMOJI = "⏸️"
_REMOTE_ABILITY_EMOJI = "⚡"   # 遠端使用能力（遊戲內按一次 X；等同 `ability` 指令）
_REMOTE_SNAP_EMOJI = "📷"     # 即時截圖回傳（2026-07-17 需求：唯讀觀測，輪詢執行緒直接抓）
_REMOTE_REENTER_EMOJI = "🏠"  # 手動回礦（等同 `回礦` 指令／STUCK 🏠；只寫旗標，主迴圈消費）
_WEB_ESCALATE_EMOJI = "🔀"    # 2026-07-27：網頁等待提醒訊息上的「立刻改用 Discord」反應
# 遙控器 embed 標題——啟動時靠它掃頻道「認領」跨重啟殘留的遙控器（find_remote_messages），
# 故字串必須與 _build_remote_embed 的 "title" 一字不差（含中間那個空格）。
_REMOTE_TITLE = "🎮 挖 礦機器人遙控器"

# P5 Task 5：自動收集素材根目錄（spec §5 素材庫結構）。
# 預設指向 repo tests/fixtures/——測試經 monkeypatch 改寫到 tmp_path。
# 不寫 assets/（gitignored；CLAUDE.md「素材契約」明示 tests/fixtures/ 才追蹤）。
_AUTO_FIXTURE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures")

# auto-collected 沒跑偵測，無法量測框大小，用 nominal 值（spec §5 範例 size=50）。
# tracker area 80~1800 → 邊長 9~42，視覺框邊長 50~207；50 落在合理範圍內。
_AUTO_FIXTURE_DEFAULT_SIZE = 50


class _HotkeyController:
    """熱鍵邊緣觸發邏輯。down_fn 由外部注入（生產用 GetAsyncKeyState，測試用 mock）。"""

    def __init__(self, down_fn, on_stop, on_toggle, on_quit):
        self._down = down_fn
        self._on_stop = on_stop
        self._on_toggle = on_toggle
        self._on_quit = on_quit
        self._prev_ctrlq = False
        self._prev_q = False

    def tick(self):
        ctrl = self._down(0x11)
        q    = self._down(0x51)
        f12  = self._down(0x7B)
        if ctrl and q:
            if not self._prev_ctrlq:
                self._on_stop()
            self._prev_ctrlq = True
            self._prev_q = True            # 放開時不再另觸發單獨 Q
            return
        self._prev_ctrlq = False
        if q and not ctrl:
            if not self._prev_q:
                self._on_toggle()
            self._prev_q = True
        else:
            self._prev_q = False
        # R 取樣視窗已退役（2026-07-17）：截圖→遙控器 📷、俯仰→回礦 `仰角` 指令
        # 跳過環境檢查不設專用鍵：F 系多被 Roblox 內建佔用（F8 實測有遊戲功能、
        # 會誤觸），改由 Q 在啟動階段語意分派（states.toggle_pause_action 的 skip_env）
        if f12:
            self._on_quit()


class Bot:
    def __init__(self):
        self.state = State.MINING
        self.paused = False
        self.human_cleared = False
        cfg.log_dir = resolve_log_dir(cfg.log_dir)
        cfg.manual_snapshot_dir = resolve_runtime_log_path(
            cfg.manual_snapshot_dir, cfg.log_dir)
        cfg.reentry_remote_ledger = resolve_runtime_log_path(
            cfg.reentry_remote_ledger, cfg.log_dir)
        cfg.boost_count_ledger = resolve_runtime_log_path(
            cfg.boost_count_ledger, cfg.log_dir)
        self.logger = diagnostics.setup_logging(cfg.log_dir, cfg.log_level)
        self.logger.info("runtime log directory: %s", cfg.log_dir)
        # H061：把直譯器印出來。這台機器有兩個 Python——`pythonw -m miningbot`（實機、
        # Microsoft Store 版）與 `uv sync` 灌的 .venv，套件不一定同步。H061 就是
        # 「.venv 有 uvicorn、實機沒有」，而整輪調查都在 .venv 裡重現不出來。
        # 一行 log 就能讓「你重現的環境跟實機是不是同一個」變成看一眼的事。
        self.logger.info("interpreter: %s", sys.executable)
        if WEB_IMPORT_ERROR:
            self.logger.warning(
                "網頁 UI 依賴缺件 → 已自動停用：%s。挖礦與 Discord 不受影響"
                "（介入流程走 fallback）；要啟用請對**這個直譯器**裝 fastapi/uvicorn。",
                WEB_IMPORT_ERROR)
        # 子系統 logger（分檔隔離噪音：心跳/重複動作/採集細節各自獨立檔）
        self.log_hb = diagnostics.get_logger("heartbeat")      # -> heartbeat.log
        self.log_act = diagnostics.get_logger("mining")        # -> actions.log
        self.log_harvest = diagnostics.get_logger("harvest")   # -> harvest.log
        self.log_discord = diagnostics.get_logger("discord")   # -> discord.log
        self.log = EventLog()
        self.log.add_sink(make_file_sink(f"{cfg.log_dir}/events.log"))
        self.log.add_sink(lambda rec: self.logger.info("EVENT %s %s", rec.type, rec.meta))
        # Discord 事件通知（有設 token+channel 才啟用；失敗只記 log，不影響挖礦）
        if cfg.discord_bot_token and cfg.discord_channel_id:
            from . import notify
            # 包成非同步 sink：圖片上傳（multipart，timeout 最長 15s）移到背景 worker，
            # 不阻塞主迴圈——否則 chill 偵測後遲遲不採集、HARVESTING 期間卡頓。
            self.log.add_sink(notify.make_async_sink(
                notify.make_discord_sink(
                    cfg.discord_bot_token, cfg.discord_channel_id,
                    on_error=lambda d: self.logger.error("Discord 通知失敗: %s", d),
                    log=self.log_discord,
                    giveup_image_mode="single"),
                log=self.log_discord,
                max_queue=cfg.discord_sink_queue_max))
            self.logger.info("Discord 通知已啟用 (channel=%s)", cfg.discord_channel_id)
        else:
            self.logger.info("Discord 通知未啟用（.env 未設 token/channel）")
        # 多參考集（各種 chill 實錄裁片，取最高分）；空則退回單一參考檔
        refs, sr = audio.load_references(cfg.chill_refs_dir, cfg.chill_audio_path)
        self.logger.info("chill 參考集載入 %d 個（decimate=%d）", len(refs), cfg.audio_match_decimate)
        # 用音檔實際的取樣率，避免 WAV 非 48kHz 時視窗長度不符
        self.listener = audio.ChillListener(
            refs, sr, cfg.audio_window_seconds, cfg.audio_score_interval_s,
            event_threshold=(cfg.audio_event_threshold if cfg.audio_event_record else None),
            on_event=self._on_audio_event, decimate=cfg.audio_match_decimate)
        # 重置完成鈴聲擷取（第一階段：只錄不比對）——與 ChillListener 隔離
        self._reset_chime_active = False
        self._reset_wait_since = 0.0             # RESET_WAIT 進場時刻（HUD/診斷用）
        self._chime_armed_at = 0.0               # H045 容量錨：觀測到容量歸零的時刻（0=本輪未觀測到）
        self._last_chime_diag = 0.0
        self._reset_chime_recorder = None
        if cfg.reset_chime_capture:
            chunk_seconds = 4096 / cfg.audio_sample_rate      # LoopbackCapture 預設 chunk_frames
            detector = audio.AdaptiveSpikeDetector(
                spike_factor=cfg.reset_chime_spike_factor,
                baseline_alpha=cfg.reset_chime_baseline_alpha,
                min_floor=cfg.reset_chime_min_floor,
                warmup_samples=max(1, round(cfg.reset_chime_warmup_s / chunk_seconds)))
            self._reset_chime_recorder = audio.ResetChimeRecorder(
                sample_rate=cfg.audio_sample_rate,
                window_s=cfg.reset_chime_window_s,
                post_roll_s=cfg.reset_chime_post_roll_s,
                chunk_seconds=chunk_seconds,
                detector=detector,
                out_dir=f"{cfg.log_dir}/snapshots/audio",
                max_clips=cfg.reset_chime_max_clips,
                log=self._on_reset_chime_saved,
                diag=self._reset_chime_diag)
        # 啟動喇叭 loopback 擷取，扇出給 listener（chill 核心）＋ reset-chime recorder
        self._audio_cap = audio.LoopbackCapture(self._on_audio_chunk)
        try:
            self._audio_cap.start()
            self.logger.info("audio loopback capture started (ref sr=%d)", sr)
        except Exception as e:
            self.logger.error("音訊擷取啟動失敗，chill 偵測停用: %s", e)
        self.harvest = harvester.HarvestState(rotations=0, elapsed_s=0.0)
        self._harvest_start = 0.0
        self._harvest_seq = self._load_harvest_seq()  # 採集流水號（持久化跨 session；每進一次 HARVESTING +1）；格式化成 001 貫穿 log/快照/Discord
        # 非同步快照：主線只丟佇列（即時拿路徑），背景執行緒做 PNG 編碼+寫檔（不卡 aim→D3）
        self._snap_q: queue.PriorityQueue = queue.PriorityQueue(maxsize=cfg.snapshot_queue_max)
        self._snap_seq = itertools.count()
        threading.Thread(target=self._snapshot_worker, daemon=True).start()
        self._latency = metrics.LatencyTracker(cfg.perf_sample_window)
        self._last_perf_log = time.monotonic()
        self._prev_frame = None
        self._last_progress = time.time()
        # Q 跳過啟動環境檢查（spec 2026-07-10 第 2 節；原 F8 與 Roblox 內建功能衝突改 Q）：
        # _skip_env_check 由啟動階段的 Q（toggle_pause_action='skip_env'）設定，
        # 只在 _startup_phase=True（run() 環境檢查階段）有效；init 完成後 _startup_phase=False。
        self._skip_env_check = threading.Event()
        self._startup_phase = False
        self._stuck_notified = False
        self._manual_reentry = False           # Discord 回礦 指令/STUCK 🏠（輪詢執行緒寫、主迴圈消費）
        self._rr_trigger = "reset"             # 本輪 REENTRY 觸發來源（reset/manual；建 ctx 時寫入）
        self._stuck_alert_mid = None           # STUCK 警告訊息 id（🏠 反應輪詢；進度恢復即作廢）
        self._stuck_seen: dict[str, int] = {}  # 🏠 反應數基線（bot 自己貼成功時為 1）
        self._rr_open_first_ts = 0.0           # H044 開場探測：episode 首擊時刻（0=非探測中）
        self._rr_open_last_ts = 0.0            # H044 開場探測：上一次探測時刻
        self._rr_last_probe = (None, None, 0.0, 0.0)  # 最後一探讀值 (surface, cap, p_mean, p_frac)；give_up 通知附帶
        self._spawn_chill_notified = False        # spawn chill 去抖動：同一波 chill 只通知一次（_check_spawn_chill 在 chill 回落時重新武裝）
        self._last_heartbeat = time.time()
        self._peak_audio_since_hb = 0.0           # 上次 heartbeat 至今的最高音訊分數（捕捉 30s 取樣漏掉的 chill 尖峰）
        self._antiafk_last = 0.0                   # 防掛機：上次按 Space 的時間（0=未在計時；暫停中才啟用）
        self._antiafk_pressed_at = 0.0             # H060：上次真的按下 Space 的時刻（chill 靜音窗錨點）
        self._antiafk_mute_logged = False          # H060：本次按鍵的靜音已記過一筆（避免每幀洗 log）
        self._last_boost = 0.0                       # 上次按 D5 的時間（冷卻用）
        # boost 沒到期警報（2026-07-25）：MINING 且未暫停時 boost 連續 > boost_stall_warn_s 沒重上
        # = 遊戲時間可能凍結／焦點丟失／偵測誤判。一次警報後鎖住，恢復（boost 重上）才解鎖，避免洗頻道。
        self._boost_stall_notified = False
        self._last_activity = 0.0                    # 上次按 D4 刷新的時間（定時用）
        self._last_d3_fire_at: float | None = None  # session 級；實際 hold-click 當下起算
        self._last_boost_check = 0.0                 # boost 偵測節流：上次真的 edge-match 的時間
        self._boost_present = False                  # 上次偵測到的 boost 瓶子在否（節流間沿用，避免每幀掃）
        # boost 使用計數（2026-07-19）：D5 有時按了不觸發、腳本會重按——「使用」只在
        # 瓶子重新出現時 +1（一段 pending 內多次重按算一次）；右下角計數器＝ground truth。
        self._boost_press_pending = False            # 按過 D5、瓶子尚未重現（重現確認才算一次使用）
        self._boost_uses = 0                         # 本行程確認成功的使用數（≠ stats["boosts"] 按鍵數）
        self._bc_last_pair_screen = None             # 上次存 FOV 前後幀對時的螢幕計數（節流錨）
        self._bc_last_unreadable = 0.0               # 計數器讀不出 → 全幀快照節流（模板增補素材）
        self._last_activity_check = 0.0              # D4 冷卻偵測節流：上次真的 edge-match 的時間
        # D2 雷達連續使用（2026-07-25）：兩個能力冷卻獨立，各記各的上次觸發時刻。
        # _radar_toggle 是 Discord 執行期開關；2026-07-26 起持久化到 radar_toggle.json
        # ——Discord 改了會 save，重啟時從檔案載入（不退回 cfg 預設，使用者要求）。
        self._radar_last = {"scan": 0.0, "cave": 0.0}
        self._radar_toggle = self._load_radar_toggle()
        self._radar_auto_scan_at = 0.0               # **連續使用**上次按左鍵的時刻（採集自己按的不算）
        self._radar_check_at = 0.0                   # 徽章偵測節流錨
        self._radar_local_present = False            # 節流間沿用的快取
        self._radar_cave_present = False
        self._radar_ocr_ok = True                    # OCR 引擎可用否（run() 啟動時探測；False→定時後備）
        self._activity_present = False               # 上次偵測到的 D4 冷卻圖示在否（節流間沿用）
        self._keep_ores: set[str] = self._load_keep_ores()  # D4 保留清單（持久化；Discord !keep 修改）
        self._d4_unknown_at = 0.0                    # D4 事件文字認不得的 hold 起點（0=沒在 hold；雙樣本確認用）
        self._last_discord_msg_id: str | None = None  # Discord 命令輪詢基準（首次只記錄不處理）
        self._poll_fail_logged_at = 0.0               # 輪詢失敗警告節流（60s 一則，避免斷網洗版）
        # Discord !list 表情分頁追蹤（都在 poll 執行緒上讀寫，無跨執行緒競爭）
        self._list_message_id: str | None = None        # 最新一則 !list 訊息 ID（表情分頁標的）
        self._list_current_world: str | None = None     # 該訊息目前顯示的世界（None=全世界聯集）
        self._list_reactions_seen: dict[str, int] = {}  # 每表情反應數基線（取消後再點可重新觸發）
        # 遙控器（釘底控制訊息 + 反應按鈕，混合設計 2026-07-09）：狀態變更/按鈕點擊一律
        # edit_message 原地編輯（不產生新訊息、不推播），**只有**被其他訊息擠上去時才刪舊
        # 重貼回頻道底（_repost_remote_control）。啟動時 _ensure_remote_control 先清跨重啟
        # 殘留的舊遙控器（舊設計 id 只在記憶體、重啟後永遠刪不到的根因）再貼新的。
        # 反應 ▶️/⏸️ 由 _poll_remote_reactions 偵測新點擊（seen 採同步語意：使用者取消可再點）。
        self._remote_message_id: str | None = None
        self._remote_reactions_seen: dict[str, int] = {}
        self._remote_last_shown: tuple | None = None    # 上次 PATCH 時的 (paused, state)，避免重複 PATCH
        # 反應清除可用性（2026-07-26）：按完按鈕原地把該表情清空再重貼，訊息不必刪貼。
        # 需要 MANAGE_MESSAGES（實測本頻道有）；被收回權限或改回 DM 時第一次 403 就
        # 永久降級（遙控器回刪貼、其餘卡片回「使用者自行取消反應」的舊語意）。
        self._reaction_clear_ok = True
        # 網頁介入進行中的 Discord 提醒訊息 id（介入結束就收回，不留殭屍訊息）
        self._web_intervention_mid: str | None = None
        # 2026-07-27：使用者要求「加反應在等待訊息上，點了直接切 Discord」——
        # routing_key -> (message_id, baseline_count)，_poll_web_escalate_reactions
        # 逐一查有沒有人多按一次；按了就排 control:force_discord:<routing_key>，
        # 等待迴圈立刻放棄 web、退回 Discord（不必等滿整個 budget）。
        self._web_escalate: dict[str, tuple[str, int]] = {}
        # 釘底防抖（2026-07-19 spec）：看到新訊息只立旗標，頻道安靜滿
        # cfg.discord_repin_quiet_s 才刪舊貼新（_repin_tick）；回礦收尾由 _rr_finalize
        # 主動立遙控器旗標——修「回礦完成後要等使用者發話遙控器才出現」的消費競態。
        from . import notify as _notify
        self._remote_repin = _notify.RepinDebouncer()   # 遙控器（非 REENTRY 時作用）
        self._rr_repin = _notify.RepinDebouncer()       # 回礦卡（REENTRY 中作用）
        # 狀態小窗用的即時資訊
        self._started = time.time()
        self.last_action = "—"
        self.stats = {"boosts": 0, "rerolls": 0, "rares": 0, "stuck": 0}
        self._human_reason = "需要人工介入"
        # 採集放棄（D3 階段失敗）時預先截好的圖 + 額外 event 欄位（如 rotation_hint）。
        # _on_enter(NEEDS_HUMAN) 會優先用 extra_image，否則跑 _save_needs_human_screenshot。
        # 用完即清空（一次性），避免跨事件殘留。
        self._needs_human_extra_image = None
        self._needs_human_extra_meta: dict = {}
        # Discord 遠端瞄準（2026-07-11 spec）：giveup 時的 aim context＋sweep 各方位近失候選
        self._aim_context = None                 # AimContext（giveup 時建、回挖礦/重置時作廢）
        self._sweep_shots: list = []             # [remote_aim.SweepShot]（episode 級、跨層累積）
        self._target_observations: list = []     # accepted/fired/seen-once，保留絕對方位與原圖
        self._target_recovery_attempts = 0       # episode 級有界復原；不在 RESWEEP 重置
        # B3：輪詢執行緒寫 pending、主迴圈讀清；_aim_busy 擋執行中再回覆（不排隊）
        self._pending_aim = None                 # AimReply（輪詢解析結果、主迴圈消費）
        self._aim_busy = False                   # fire 執行中（主迴圈設、輪詢執行緒讀）
        # Discord `ability` 指令／遙控器 ⚡（2026-07-12 spec）：輪詢執行緒寫旗標、
        # 主迴圈消費後按 X。布林於 GIL 下原子（同 human_cleared 跨執行緒寫入模式）。
        self._pending_ability = False
        # Discord `轉` 指令（2026-07-21 H059）：遠端轉 45°，供使用者手動校正斜向面向
        # （回礦落地約一半機率對角，自動視覺判定已證實做不到——見 07-21 findings）。
        # 同上：輪詢執行緒只寫 ±1，輸入一律由主迴圈 _consume_pending_rotate 送。
        self._pending_rotate = 0
        # Discord 遠端回礦（2026-07-12 spec）：輪詢執行緒只寫 _pending_reentry（含原文，
        # 供 ledger 指令流水），主迴圈消費；比照 _pending_aim／_aim_busy。
        self._rr_ctx = None                      # RemoteReentryContext（進 REENTRY remote 時建、收尾時清）
        self._pending_reentry = None              # (raw, RemoteReply)：輪詢解析結果、主迴圈消費
        self._rr_busy = False                    # 開場鏈/指令執行中（主迴圈設、輪詢執行緒讀）
        # Discord 俯仰校準（2026-07-18 spec）：輪詢執行緒只寫 pending，進場/動作/寫檔全在
        # 主迴圈。session 活著＝強制暫停中（paused 底下的旗標，不是 states.py 新狀態）。
        self._calib_session = None                # calibrate_pitch.CalibSession | None
        self._pending_calib_start = None          # "mining"/"reentry"：指令驗收後待主迴圈進場
        self._pending_calib_action = None         # "up"/…/"exit"：反應輪詢/文字指令待主迴圈消費
        self._pending_calib_px = 0                # 文字指令的像素覆寫（`上 12`；0=用現行幅度）
        self._rr_sticky_layer = cfg.reentry_target_layer   # 黏性目標層（`層` 指令改；來源優先序見 _adopt_sticky_for_world）
        # 2026-07-20：每世界黏性層持久化——init 讀回磁碟 map，世界偵測到時自動套該世界的層。
        try:
            with open(cfg.reentry_remote_sticky_layers_path, "r", encoding="utf-8") as f:
                self._rr_sticky_layers = reentry_remote.parse_sticky_layers(f.read())
        except OSError:
            self._rr_sticky_layers = {}
        self._rr_layer_user_pinned = False          # 本 session 是否被 `層` 釘過（釘過則世界偵測不再覆寫）
        self._evac_done = False                   # RESET_WAIT 撤離結果（REENTRY embed 僅供 footer 標注，不改流程）
        self._rr_embed_mid = None                 # REENTRY episode embed 訊息 id（_rr_finalize 時刪除，避免殘留死卡）
        self._rr_reactions_seen: dict[str, int] = {}  # embed 反應數基線（同步語意）
        self._rr_last_min = -1                    # embed 分鐘數節流：變了才 PATCH（每分鐘最多 1 次，防 rate limit）
        self._last_reset_check = 0.0
        self._mine_resetting = False
        # Capacity 監看（輔助信號，2026-07-12 起不再觸發 RESET_WAIT）：背景 worker 每輪多讀
        # Capacity% 快取於此（HUD 顯示＋加速輪詢判斷）；連續 2 次 ≥100 只記一次飽和 INFO，
        # 唯一停機條件是 reset 橫幅（cap_trigger 當假陽性會死鎖，見 config 容量區塊註解）。
        self._capacity_pct = None
        self._capacity_streak = 0
        self._capacity_full_logged = False      # 容量飽和 INFO 去抖（首次觸發記一次，回 MINING 清除）
        # Movement Mode 前置檢查延後到第一次礦坑重置後才跑（2026-07-11 需求）：
        # 啟動時不再跑選單鏈（實測 71-82s）——回礦/傳送功能未完成，session 之間沒有
        # 東西會動到這個設定。改在 session 內第一次 RESET_WAIT 結束、回 MINING 時跑一次。
        self._movement_check_due = False       # RESET_WAIT 進場時立起、回 MINING 時消費
        self._movement_mode_checked = False    # session 內只跑一次（之後不再跑）
        # 重置自動回礦（REENTRY）：reset banner 消失起算的沉澱計時＋單輪執行狀態
        self._reset_clear_since = 0.0            # 0=banner 還在（或不在 RESET_WAIT）
        self._reentry = None                     # reentry.ReentryState（進 REENTRY 時建立）
        self._reentry_ref = None                 # 傳送前參考幀（幀差判傳送完成）
        self._reentry_done = False
        self._reentry_failed = False
        self._reentry_panel_xy = None            # sweep 選定的面板螢幕座標
        self._move_diffs = []                    # NAVIGATE 途中連續幀差（movement_status 用）
        self._last_nav_frame = None
        # 頂部事件列 OCR 快取（背景 worker _banner_ocr_loop 寫、主迴圈讀）：
        # tesserocr 單次 ~400ms 若同步跑會把 MINING tick 從 ~0.15s 撐到 ~0.6s，
        # boost 到期偵測（0.2s 高頻）跟著被拖慢——移出主迴圈後 tick 穩定。
        self._banner_text = ""                   # 最近一次頂部列 OCR 全文（D4 路徑重用免重跑）
        self._banner_text_at = 0.0               # 該次 OCR 完成時間（判斷快取新鮮度）
        self._latest_frame = None                # 主迴圈每 tick 發佈最新幀給 worker（唯讀共享）
        # 視窗跑位偵測（item ④）：啟動聚焦後記基準，之後相對基準判斷
        self._window_baseline = None
        self._last_window_check = 0.0
        self._window_bad = False
        self._window_displaced_reason = None
        # 熱鍵控制器：邊緣觸發邏輯在 _HotkeyController，背景執行緒持續輪詢
        _u = ctypes.windll.user32
        self._hk = _HotkeyController(
            lambda vk: bool(_u.GetAsyncKeyState(vk) & 0x8000),
            self._pause,            # Ctrl+Q：只暫停（不繼續）
            self._toggle_pause,     # Q：開關 暫停↔繼續
            self._quit,
        )
        self._pitch_offset_px = 0             # 目前俯仰距夾限偏移（回礦歸位後＝reentry_pitch_back_px、
                                              # 挖礦標準角歸位後＝sweep_pitch_center_back_px）
        self._rr_pitch_back_px = None         # REENTRY session 期望回拉量（None＝本 episode 沒調過→
                                              # config 標準角；`上|下`/`歸位` 更新，重骰/重探開場沿用——
                                              # 2026-07-19 使用者反映重骰洗掉已設定仰角）
        # boost_active = boost 生效中的瓶子圖；邏輯「瓶子消失才重上」（見 _boost_needs_refresh）。
        # 缺圖不擋啟動，只是停用 boost 自動重上。D4 改用定時、D2 採集流程、Z 擱置，皆不需模板。
        self._templates = {}
        bp = "assets/boost_active.png"
        if os.path.exists(bp):
            self._templates["boost_active"] = vision.load_template(bp)
        else:
            self._templates["boost_active"] = None
            self.logger.warning("缺少模板 %s — boost 自動重上停用，之後補圖即可", bp)
        # D4 冷卻圖示：用來判斷 D4 是否就緒（圖示不在 = 冷卻好）。
        # 缺圖不擋啟動，_activity_ready 會退回定時後備。
        cp = cfg.activity_cooldown_template
        if os.path.exists(cp):
            self._templates["activity_cooldown"] = vision.load_template(cp)
        else:
            self._templates["activity_cooldown"] = None
            self.logger.warning("缺少模板 %s — D4 改用定時後備（每 %.0fs），補圖後改用冷卻偵測",
                                cp, cfg.activity_reroll_interval_s)
        # 多階級標記模板（assets/markers/*.png；用 fetch_trackers 下載）
        self._marker_templates = self._load_marker_templates()
        # 形狀確認集（混合偵測用）：只取「實機裁圖」（3 通道、無 alpha）——
        # wiki 透明圖實測在合理尺度配不到遊戲內渲染框，留著當參考但不進確認集。
        self._shape_templates = {
            n: t for n, t in self._marker_templates.items()
            if t is not None and t.ndim == 3 and t.shape[2] == 3
        } if cfg.tracker_shape_confirm else {}
        if cfg.tracker_shape_confirm:
            if self._shape_templates:
                self.logger.info("形狀確認啟用，實機裁圖 %d 張: %s",
                                 len(self._shape_templates), ", ".join(self._shape_templates))
            else:
                self.logger.warning("形狀確認已開但無實機裁圖（assets/markers 內需有無 alpha 的裁圖）"
                                    "— 暫退回純 HSV，之後從 log 收集各階實機框補上")
        # re-entry 傳送面板模板（assets/surface/*.png；calibrate_surface --import 產出）。
        # 開了 auto_reenter 但沒模板＝掃不到面板必然全 reroll → 視同關閉並警告，不空轉。
        self._panel_templates = self._load_panel_templates()
        # RapidOCR／tesserocr 預熱：與音訊載入/HUD 倒數/聚焦重疊，UI 前置檢查不再踩冷 init。
        # 2026-07-10 移到 __init__（原在 run() 尾，排在 UI 檢查之後才啟動，首個 UI 檢查自己
        # 踩 6~11s 冷 init；_get_rapid_engine/_get_tess_api 有鎖冪等，未裝時快速失敗一次）。
        threading.Thread(target=ocr.rapidocr_available, daemon=True).start()
        threading.Thread(target=ocr.tesserocr_available, args=(cfg.tesseract_path,), daemon=True).start()
        self._init_discord_messengers()

    def _init_discord_messengers(self):
        """P2 Task 7：PingResolveMessenger（NEEDS_HUMAN PING 推播 + 結案編輯同則）初始化。

        只在 Discord token/channel 已設時啟用；失敗只記 log，不影響挖礦（沿用
        notify.make_discord_sink 既有慣例）。
        _pending_ping_mid 給 anchor D（_resolve_ping_if_any）用：routing_key "harvest:007"
        → PING message_id；玩家 reply 完成時對照同一份 dict 編輯 ✅。

        2026-07-26：原本這裡還會建一個 StatusMessenger，post 一則**獨立**的純文字狀態
        訊息。那違反 spec §7 A「遙控器卡（合併狀態顯示，1 則常駐）」——遙控器 embed
        本來就有 `**狀態**` 欄，等於同一份狀態在頻道裡有兩則。已移除，狀態顯示併回
        遙控器卡（見 _build_remote_embed）。

        從 __init__ 抽出成獨立 method（2026-07-26）：__init__ 整段太重（音訊、模板、
        thread）無法在測試裡跑，這個區塊的整合行為因此從 P2 一路 skip 到現在。抽出後
        可用 Bot.__new__ 的 fake bot 直接驗，不必啟動整台 bot。
        """
        if cfg.discord_bot_token and cfg.discord_channel_id:
            try:
                self._ping_messenger = notify.PingResolveMessenger(
                    token=cfg.discord_bot_token, channel_id=cfg.discord_channel_id,
                    send_fn=notify.send_message_with_id,
                    edit_fn=notify.edit_message,
                    log=self.log_discord,
                )
            except Exception as e:
                self.logger.error("PingResolveMessenger 初始化失敗: %s", e)
                self._ping_messenger = None
        else:
            self._ping_messenger = None
        self._pending_ping_mid: dict[str, str] = {}  # routing_key → PING message_id（anchor D 用）
        # 遙控器卡狀態刷新降頻（spec §7 A「降頻上限 discord_status_edit_min_interval_s」）：
        # 狀態轉換觸發 edit，但狀態機快速擺盪（MINING↔HARVESTING）時不逐次 PATCH。
        # 擋下來的那次不更新 _remote_last_shown，下一輪輪詢（1s）條件仍成立會自動補上。
        self._remote_edit_throttle = notify.EditThrottle(
            min_interval_s=cfg.discord_status_edit_min_interval_s)

    def _load_panel_templates(self) -> list:
        import glob
        tmpls = [vision.load_template(p)
                 for p in sorted(glob.glob(os.path.join(cfg.reentry_panel_dir, "*.png")))]
        if cfg.reentry_mode == "auto":
            if tmpls:
                self.logger.info("reentry_mode=auto，面板模板 %d 張（%s）",
                                 len(tmpls), cfg.reentry_panel_dir)
            else:
                self.logger.warning("reentry_mode=auto 但 %s 無面板模板——自動回礦視同關閉；"
                                    "先用遙控器 📷 截編號樣本＋calibrate_surface --import 裁模板",
                                    cfg.reentry_panel_dir)
        return tmpls

    def _auto_reenter_active(self) -> bool:
        """auto 模式的有效值：mode=auto＋面板模板存在（缺模板視同關閉）。"""
        return cfg.reentry_mode == "auto" and bool(self._panel_templates)

    def _remote_reenter_active(self) -> bool:
        """remote 模式的有效值：mode=remote＋「回到地表」按鈕座標已校準（(0,0)=未校準視同關閉）。"""
        return cfg.reentry_mode == "remote" and tuple(cfg.reentry_surface_button_xy) != (0, 0)

    def _reentry_active(self) -> bool:
        """任一回礦模式啟用（REENTRY 觸發條件；傳 Observation.auto_reenter）。"""
        return self._auto_reenter_active() or self._remote_reenter_active()

    def _load_marker_templates(self) -> dict:
        import glob
        templates = {}
        for p in sorted(glob.glob(os.path.join(cfg.marker_dir, "*.png"))):
            name = os.path.splitext(os.path.basename(p))[0]
            templates[name] = vision.load_template_any(p)   # 保留 alpha（wiki 透明外框）
        if not templates and os.path.exists("assets/marker.png"):
            templates["marker"] = vision.load_template_any("assets/marker.png")
        if not templates:                            # 完全沒有標記模板 → 採集會找不到標記（不擋啟動）
            self.logger.warning("沒有任何標記模板（%s 為空且無 assets/marker.png）— 採集無法定位",
                                cfg.marker_dir)
        else:
            self.logger.info("loaded %d marker templates: %s",
                             len(templates), ", ".join(templates))
        return templates

    def _collect_preflight_facts(self) -> PreflightFacts:
        """啟動自檢：收集 I/O 事實給 preflight.run_checks（純決策）。任何來源失敗都優雅降級
        （count 0 / age -1），preflight 本身絕不可擋啟動。"""
        import glob
        # marker_real_count：與 __init__ 的 _shape_templates 同一套過濾（無 alpha 的實機裁圖）
        marker_real_count = len(self._shape_templates)
        try:
            chill_ref_count = len(glob.glob(os.path.join(cfg.chill_refs_dir, "*.wav")))
        except Exception:
            chill_ref_count = 0
        rare_ores_path = os.path.join("assets", "rare_ores.json")
        try:
            age_days = (time.time() - os.path.getmtime(rare_ores_path)) / 86400.0
        except OSError:
            age_days = -1.0
        ores_all_present = os.path.exists(os.path.join("assets", "ores_all.json"))
        d4_cooldown_present = os.path.exists(cfg.activity_cooldown_template)
        discord_token_set = bool(cfg.discord_bot_token and cfg.discord_channel_id)
        # 引擎可用性：rapidocr_available()／tesserocr_available() 都是冪等、有鎖的主動探測
        # （鏡射同一套模式），不是取樣 lazy 旗標——避免 preflight 在任何 OCR 呼叫之前取樣到
        # 樂觀初值（旗標只在真的跑過一次失敗的 OCR 後才會翻正確）。
        try:
            rapidocr_ok = ocr.rapidocr_available()
        except Exception:
            rapidocr_ok = False
        try:
            tesserocr_ok = ocr.tesserocr_available(cfg.tesseract_path)
        except Exception:
            tesserocr_ok = False
        log_dir_abspath = os.path.abspath(cfg.log_dir)
        snapshots_dir = os.path.join(cfg.log_dir, "snapshots")
        snapshots_total_mb = 0.0
        try:
            total_bytes = 0
            for root, _dirs, files in os.walk(snapshots_dir):
                for name in files:
                    try:
                        total_bytes += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        pass
            snapshots_total_mb = total_bytes / (1024 * 1024)
        except OSError:
            snapshots_total_mb = 0.0
        return PreflightFacts(
            marker_real_count=marker_real_count,
            chill_ref_count=chill_ref_count,
            rare_ores_json_age_days=age_days,
            ores_all_present=ores_all_present,
            d4_cooldown_present=d4_cooldown_present,
            discord_token_set=discord_token_set,
            tesserocr_ok=tesserocr_ok,
            rapidocr_ok=rapidocr_ok,
            log_dir_abspath=log_dir_abspath,
            snapshots_total_mb=snapshots_total_mb,
            audio_decimate=cfg.audio_match_decimate,
            audio_interval_s=cfg.audio_score_interval_s,
        )

    def _run_preflight(self) -> list[str]:
        """跑 preflight 檢查、記 log、寫警訊檔，回傳 WARN 訊息清單。

        WARN 是「環境/資產降級」診斷（tesserocr 沒裝、snapshots 太大…），是給
        「之後的 AI agent 去修」的待辦，不是掛機者要即時看的東西——所以**不進即時
        Discord 通知**（使用者回饋 2026-07-07），改寫進 logs/preflight_alerts.md 供
        後續 agent 巡檢修復。任何環節失敗都吞掉、不擋啟動——preflight 是輔助可見度，
        不是啟動關卡。"""
        try:
            facts = self._collect_preflight_facts()
            results = run_checks(facts)
        except Exception as e:
            self.logger.warning("preflight 自檢失敗（不影響啟動）: %r", e)
            return []
        warn_msgs = []
        for lv, m in results:
            if lv == "WARN":
                self.logger.warning("[preflight] %s", m)
                warn_msgs.append(m)
            else:
                self.logger.info("[preflight] %s", m)
        self._write_preflight_alerts(warn_msgs)
        return warn_msgs

    def _write_preflight_alerts(self, warn_msgs):
        """把 preflight WARN 寫進 logs/preflight_alerts.md（每次啟動覆寫＝當前狀態快照，
        修好的項目自然消失、不累積雜訊）。這是給後續 AI agent 巡檢修復的警訊清單，
        刻意與即時 Discord 通知分流（使用者回饋：診斷降級訊息不該洗掉要即時閱讀的訊息）。
        無 WARN 時也覆寫成「無警訊」，讓 agent 一眼看出已清乾淨。絕不可擋啟動。"""
        try:
            path = os.path.join(cfg.log_dir, "preflight_alerts.md")
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            lines = [
                "# Preflight 警訊（供後續 AI agent 巡檢修復）",
                "",
                f"> 最後更新：{ts}（每次 bot 啟動覆寫＝當前環境/資產降級快照）。",
                "> 這些是靜默降級診斷，不是即時 Discord 通知。修好對應項目後此檔會自動變乾淨。",
                "",
            ]
            if warn_msgs:
                lines.append(f"## 待修 {len(warn_msgs)} 項")
                lines += [f"- [ ] {m}" for m in warn_msgs]
            else:
                lines.append("## 無警訊 ✅")
            os.makedirs(cfg.log_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            self.logger.warning("寫 preflight 警訊檔失敗（不影響啟動）: %r", e)

    def _snapshot_cleanup_once(self):
        """啟動時清理過舊/過量快照（Phase 3.2）：632MB 且在 OneDrive 同步夾的實測痛點對策。

        純決策交給 diagnostics.plan_snapshot_cleanup（有測試）；這裡只做 I/O：
        scandir 收集 logs/snapshots 底下所有檔案 → 純函式決定該刪誰 → os.remove。
        **安全邊界：只掃/只刪 `cfg.log_dir/snapshots` 底下**，絕不碰其他路徑（不誤刪
        OneDrive Pictures/Roblox 的手動 ground-truth 截圖、也不碰 log_dir 下其他 *.log）。
        任何環節失敗都吞掉、不擋啟動或主迴圈——這是背景清理，不是關鍵路徑。
        """
        if not cfg.snapshot_retention_enabled:
            return
        try:
            snap_dir = os.path.join(cfg.log_dir, "snapshots")
            if not os.path.isdir(snap_dir):
                return
            entries = []
            for root, _dirs, files in os.walk(snap_dir):
                for name in files:
                    path = os.path.join(root, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    entries.append((path, st.st_mtime, st.st_size))
            doomed = diagnostics.plan_snapshot_cleanup_tiered(
                entries, time.time(), cfg.snapshot_max_age_days, cfg.snapshot_max_total_mb,
                category_limits={
                    "trace": (cfg.snapshot_trace_max_age_days,
                              cfg.snapshot_trace_max_total_mb),
                })
            freed_bytes = 0
            deleted = 0
            for path in doomed:
                try:
                    size = os.path.getsize(path)
                    os.remove(path)
                    freed_bytes += size
                    deleted += 1
                except OSError:
                    pass
            self.logger.info("快照清理：刪 %d 檔、釋出 %.0fMB", deleted, freed_bytes / (1024 * 1024))
        except Exception as e:
            self.logger.warning("快照清理失敗（不影響啟動）: %r", e)

    def _boost_needs_refresh(self, frame) -> bool:
        """boost 邏輯：瓶子（buff）消失 → 該重上 D5。

        無模板時停用；剛按過 D5（冷卻內）不重按，避免瓶子出現前狂按。
        **高頻偵測「不空轉」（#4）**：提早補 D5 無意義（不刷新、還浪費換道具時間），只能「到期
        瞬間即補」→ 越快偵測瓶子消失越好。偵測已便宜（單尺度 `boost_buff_scales` ~56ms），故用
        高頻 `boost_check_interval_s`(0.2s)；節流間沿用上次 `_boost_present`。瓶子是固定尺寸 UI
        → 用 `boost_buff_scales`（會變大小的追蹤框才用多尺度 `marker_scales`；D4 用 `buff_scales`）。
        即使高頻，重按 D5 仍受 `boost_cooldown_s`(5s) 這關 gate，不會狂按。
        """
        t = self._templates.get("boost_active")
        if t is None:
            return False
        now = time.time()
        if now - self._last_boost_check >= cfg.boost_check_interval_s:
            self._last_boost_check = now
            # 在整條效果列裡用「形狀/邊緣」找瓶子（忽略顏色與會變的數字、容忍疊加位移）
            self._boost_present = vision.find_template_edges(
                capture.crop(frame, cfg.boost_indicator_region), t,
                cfg.boost_edge_threshold, cfg.boost_buff_scales) is not None
            if self._boost_present and self._boost_press_pending:
                # 成功觸發確認（2026-07-19）：只認「偵測到瓶子重現」這一刻，樂觀快取
                # （_harvest_boost_guard 的 True）不算證據——它不清 pending。
                self._confirm_boost_use(frame)
        if self._boost_present:
            return False
        return (time.time() - self._last_boost) > cfg.boost_cooldown_s

    def _confirm_boost_use(self, frame):
        """瓶子重現＝一次成功使用：+1、讀右下角計數器對帳、落 jsonl。

        右下角計數器（session 內使用次數、重進歸零）是 ground truth：D5 失敗重按
        時螢幕數字不動，內部 uses 與 screen 的差可離線對答案。讀不出（未知字元/
        遮擋）→ 全幀快照節流落檔，供之後增補數字模板。
        """
        self._boost_press_pending = False
        self._boost_uses += 1
        screen = self._boost_screen_count(frame)
        if screen is None and time.time() - self._bc_last_unreadable > 600:
            self._bc_last_unreadable = time.time()
            self._snapshot(frame, "boost_count_unreadable")
        self._bc_append({"t": round(time.time(), 3), "kind": "use", "screen": screen,
                         "uses": self._boost_uses, "presses": self.stats["boosts"]})

    def _boost_screen_count(self, frame):
        """右下角 boost 使用次數（int｜None）；None＝讀不出（寧可不讀不誤讀）。"""
        return vision.read_boost_use_count(
            capture.crop(frame, cfg.boost_count_region),
            cfg.boost_count_digit_max_mismatch)

    def _bc_append(self, d):
        """boost 使用/FOV 帳本：append-only JSONL（曲線離線分析讀這份）。"""
        try:
            os.makedirs(os.path.dirname(cfg.boost_count_ledger), exist_ok=True)
            with open(cfg.boost_count_ledger, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        except OSError as e:
            self.logger.warning("boost 帳本寫入失敗: %s", e)

    def _boost_fov_pair_save(self, before_frame, screen):
        """補瓶前後幀對（FOV 曲線量測點）：到期(縮)→補瓶展開，同場景自比無雜訊。

        呼叫端已等 boost_fov_settle_s（FOV 展開完成）才進來。JPEG 存檔控量；
        路徑落 jsonl，離線用兩固定地標像素距離比值算縮放係數。
        """
        import cv2                                  # lazy（同 _save_needs_human_screenshot）
        after = capture.grab()
        d = os.path.join(cfg.log_dir, "boost_fov")
        os.makedirs(d, exist_ok=True)
        tag = f"{time.strftime('%Y%m%d_%H%M%S')}_c{screen}"
        bp = os.path.join(d, f"{tag}_before.jpg")
        ap = os.path.join(d, f"{tag}_after.jpg")
        cv2.imwrite(bp, before_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        cv2.imwrite(ap, after, [cv2.IMWRITE_JPEG_QUALITY, 85])
        self._bc_last_pair_screen = screen
        self._bc_append({"t": round(time.time(), 3), "kind": "refill_pair",
                         "screen_before": screen, "before": bp, "after": ap})
        self.logger.info("boost FOV 前後幀對已存（screen=%s）", screen)

    def _activity_ready(self, frame) -> bool:
        """D4 活動：右下角冷卻圖示「不在」= 冷卻好 → 該按 D4 右鍵刷新事件。

        有冷卻圖模板 → 用偵測（能用就用，不浪費）；缺模板 → 退回定時後備。
        """
        if not cfg.activity_reroll_enabled:
            return False
        t = self._templates.get("activity_cooldown")
        if t is None:                                 # 後備：沒有冷卻圖模板 → 定時
            return (time.time() - self._last_activity) > cfg.activity_reroll_interval_s
        now = time.time()
        if now - self._last_activity_check >= cfg.activity_check_interval_s:
            self._last_activity_check = now
            # 在整條效果/冷卻列裡用「形狀/邊緣」找 D4 冷卻圖示（與 boost 同一列；固定 UI → buff_scales 少尺度）
            self._activity_present = vision.find_template_edges(
                capture.crop(frame, cfg.boost_indicator_region), t,
                cfg.activity_cooldown_edge_threshold, cfg.buff_scales) is not None
        return miner.cooldown_ready(self._activity_present, time.time() - self._last_activity,
                                    cfg.activity_cooldown_grace_s)

    def _radar_badges(self, frame):
        """效果列現況 → (local_present, cave_skim_present)；節流快取。

        就緒判定與 D4 同語意：徽章**不在**＝冷卻好。徽章位置會隨 buff 疊加漂移，
        故走 find_effect_slots 逐格 OCR（不可釘死座標，見 vision.find_effect_slots）。
        零格時直接早退不跑 OCR——挖礦中大多數時間效果列是空的，省掉每輪的 tesseract。
        """
        now = time.time()
        if now - self._radar_check_at < cfg.radar_check_interval_s:
            return self._radar_local_present, self._radar_cave_present
        self._radar_check_at = now
        band = capture.crop(frame, cfg.scan_confirm_region)
        slots = vision.find_effect_slots(band)
        if not slots:
            self._radar_local_present = self._radar_cave_present = False
            return False, False
        texts = [ocr.read_text(band[y:y + h, x:x + w], cfg.tesseract_path)
                 for (x, y, w, h) in slots]
        self._radar_local_present = harvester.scan_succeeded(texts)
        self._radar_cave_present = harvester.cave_skim_present(texts)
        return self._radar_local_present, self._radar_cave_present

    def _run_scan(self):
        """觸發 D2 左鍵掃描並記下時刻。

        冷卻是**共享**的：採集流程按的這一次同樣會讓連續使用進入冷卻。時刻記在同一個
        _radar_last["scan"] 上，兩邊看同一個時鐘——否則 OCR 不可用（定時後備）時，
        連續使用會以為冷卻還沒開始而在採集掃完後立刻再按一次無效的。
        """
        harvester.execute_scan()
        if getattr(self, "_radar_last", None) is not None:   # 見 _await_scan_ready 的 getattr 註解
            self._radar_last["scan"] = time.time()

    def _await_scan_ready(self, where: str) -> bool:
        """採集掃描前先等 D2 左鍵冷卻結束（2026-07-25 使用者指定解法）。

        連續使用（`掃描 開`）會週期性用掉 Cyberscan。冷卻中直接 execute_scan 會按下去
        沒作用 → 沒有追蹤框 → 白掃 8 方位 ~19s、還可能誤交人工。這裡改成等冷卻結束
        再掃：多等 ≤30s 換一次有效掃描，遠優於白掃。

        **必須在拍 reference 幀之前呼叫**——等待期間場景會變（其他玩家/光照），
        先拍 ref 再等 30s 會讓排除基準過期，反而製造假陽性。

        回 True＝已就緒；False＝等到逾時仍在冷卻（呼叫端照常往下掃，不卡死採集入口）。

        只有「連續使用開著」或「剛被連續使用佔掉冷卻」時才真的等——否則直接放行，
        讓功能關閉時的採集時序與加這功能之前**逐字不變**（採集自己按的那次也會設
        _radar_last，但那不該讓下一次 resweep 開始等待，那是既有行為不是本功能的事）。
        """
        # getattr 預設值：部分測試用 Bot.__new__ 繞過 __init__ 建物件（同檔既有慣例，
        # 見 _pre_scan_ref / _post_harvest_watch）——缺屬性時一律當「功能沒開」直接放行。
        recent_auto = (time.time() - getattr(self, "_radar_auto_scan_at", 0.0)
                       ) < cfg.radar_repeat_interval_s
        toggles = getattr(self, "_radar_toggle", None) or {}
        if not (toggles.get("scan", False) or recent_auto):
            return True
        deadline = time.time() + cfg.radar_scan_wait_max_s
        logged = False
        while True:
            since = time.time() - (getattr(self, "_radar_last", None) or {}).get("scan", 0.0)
            present = False
            if self._radar_ocr_ok:
                self._radar_check_at = 0.0          # 繞過節流：等待中要讀當下真值
                present, _ = self._radar_badges(capture.grab())
            if harvester.scan_cooldown_ready(present, since, cfg.radar_repeat_interval_s,
                                             self._radar_ocr_ok):
                if logged:
                    self.log_harvest.info("[scan-wait] %s D2 冷卻結束（等了 %.1fs）→ 開始掃描",
                                          where, cfg.radar_scan_wait_max_s
                                          - (deadline - time.time()))
                return True
            if time.time() >= deadline:
                self.logger.warning(
                    "[scan-wait] %s 等 D2 冷卻逾時 %.0fs 仍未就緒 → 照常掃描（可能白掃）",
                    where, cfg.radar_scan_wait_max_s)
                return False
            if not logged:
                self.log_harvest.info("[scan-wait] %s D2 左鍵冷卻中 → 等冷卻結束再掃描", where)
                self.last_action = "等 D2 冷卻"
                logged = True
            time.sleep(cfg.radar_scan_wait_poll_s)

    def _radar_ready(self, frame, which: str) -> bool:
        """D2 某能力是否該按了（連續使用模式）。which='scan'|'cave'。

        啟用來源是 `_radar_toggle[which]`——__init__ 從 cfg 預設值初始化、Discord
        `掃描/削洞 [開|關]` 在執行期改它，所以 toggle 是同時反映 cfg 與 Discord 指令
        的真相來源。早期版本在 toggle 之外還檢查 cfg.*_repeat_enabled，但 cfg 是靜態
        預設、Discord 指令不改它，導致 Discord 開了仍被 cfg=False 壓掉、70 分鐘 MINING
        零 SCAN/CAVE 動作（2026-07-25 18:25 場實機）。
        """
        if not self._radar_toggle.get(which, False):
            return False
        last = self._radar_last.get(which, 0.0)
        if not self._radar_ocr_ok:                    # 後備：OCR 引擎不可用 → 定時
            return (time.time() - last) > cfg.radar_repeat_interval_s
        local, cave = self._radar_badges(frame)
        present = local if which == "scan" else cave
        return miner.cooldown_ready(present, time.time() - last, cfg.radar_grace_s)

    def _handle_use_d4(self, frame):
        """D4 就緒時的 keep/reroll 決策（2026-07-19 01:16 未知連刷對策）。

        ① 快取文字必須晚於上次 D4 動作（miner.d4_text_fresh）——動作前的快取
        描述的是已處理過的舊事件；不夠新就同步重讀當前幀。
        ② 認不得的文字先 hold 一輪，等背景 worker 下一份新樣本仍認不得才刷新
        （miner.plan_d4 雙樣本確認）——單次誤讀就右鍵會把 keep 事件不可逆刷掉。
        ③ 決策 log 落原始文字、hold 時存 review 快照——01:16 事故的原始 OCR
        文字完全無從回溯，這裡把證據補上。
        """
        now = time.time()
        if (self._d4_unknown_at > 0.0
                and self._banner_text_at <= self._d4_unknown_at
                and now - self._d4_unknown_at <= cfg.reset_check_interval_s * 3):
            return          # hold 中：等 worker 新樣本（~2s 一份），不每 tick 同步 OCR
        if miner.d4_text_fresh(now, self._banner_text_at, self._last_activity,
                               cfg.reset_check_interval_s):
            event_text = self._banner_text.strip()
        else:
            event_text = ocr.read_text(capture.crop(frame, cfg.chill_text_region),
                                       cfg.tesseract_path).strip()
            self._maybe_detect_world(event_text)
        ev = game_data.match_event(event_text)
        verdict = miner.plan_d4(
            kept=bool(ev) and game_data.is_kept(event_text, self._keep_ores),
            matched=ev is not None,
            unknown_confirmed=self._d4_unknown_at > 0.0,
            resetting=self._mine_resetting)
        if verdict == "skip":
            return          # 重置倒數：事件列被重置公告蓋掉，讀值無效、不進 hold 記帳
        if verdict == "hold":
            self._d4_unknown_at = now
            self.logger.info("D4: 事件文字認不得，hold 一輪等新樣本再確認 (text=%r)",
                             event_text[:80])
            self._snapshot(frame, "d4_unknown")
            return
        self._d4_unknown_at = 0.0
        if verdict == "keep":
            self.logger.info("D4: 保留事件 %s（在 keep 清單中）", ev["ore"])
            self.last_action = f"保留事件: {ev['ore']}"
            miner.use_activity_keep()
        else:
            self.log_act.info("mining: 刷新事件 -> D4 右鍵 (%s) text=%r",
                              ev["ore"] if ev else "未知/無事件", event_text[:80])
            self.last_action = "刷新事件(D4)"
            miner.use_activity()
        self.stats["rerolls"] += 1
        self._last_activity = time.time()

    # ---- 提醒與快照 ---------------------------------------------------------
    def _alert(self, message: str):
        """本機提醒：WARNING log（操作者通知已交 Discord，不再發聲）。"""
        self.logger.warning("ALERT %s", message)

    def _snapshot(self, frame, label: str) -> str | None:
        """關鍵事件存畫面（非同步寫檔）。即時回傳路徑，imwrite 丟背景執行緒不卡主線。

        採集 aim→D3 銜接時 d3_fire/chat 全幀 PNG imwrite ~50-200ms 會卡住發射時序，
        故與 chill 發送同理移到背景執行緒（見 `_snapshot_worker`）。
        """
        if not cfg.save_snapshots or frame is None:
            return None
        return self._enqueue_snapshot(frame, label)

    def _enqueue_snapshot(self, frame, label: str) -> str | None:
        """算好路徑（即時回傳）後把 (frame 複本, 路徑) 丟佇列給背景執行緒寫檔。"""
        snap_dir, path = diagnostics.snapshot_path(cfg.log_dir, label)
        if not diagnostics.snapshot_enqueue_allowed(
                label, self._snap_q.qsize(), cfg.snapshot_queue_max,
                cfg.snapshot_queue_critical_reserve):
            self.logger.warning("snapshot 佇列保留/已滿，丟棄 %s", label)
            return None
        try:
            # frame.copy()：主迴圈會覆寫 buffer，背景寫檔前須複製避免讀到髒資料
            payload = (frame.copy(), snap_dir, path, label)
            self._snap_q.put_nowait(
                (diagnostics.snapshot_priority(label), next(self._snap_seq), payload))
            self.logger.info("SNAPSHOT %s -> %s (async)", label, path)
        except queue.Full:
            self.logger.warning("snapshot 佇列滿，丟棄 %s", label)
            return None
        return path

    def _snapshot_worker(self):
        """背景執列緒：從佇列取出畫面寫檔（PNG 編碼+磁碟 I/O 不卡主線）。"""
        import cv2                                  # lazy（同 _save_needs_human_screenshot）
        while True:
            _priority, _seq, payload = self._snap_q.get()
            frame, snap_dir, path, label = payload
            tmp = diagnostics.tmp_snapshot_path(path)  # 保留 .png 給 cv2（見該函式註解）
            try:
                os.makedirs(snap_dir, exist_ok=True)
                # ★ 原子寫入：先寫 .part 再 os.replace 改名。改名前 path 不存在 →
                # Discord 上傳執行緒（notify.py 的 os.path.exists 檢查）讀不到半成品，
                # 退回純文字通知（安全）；改名後即完整檔。修「Discord 收到半張截圖」race：
                # cv2.imwrite 寫 1080p PNG 需 50-200ms，期間檔案已存在但不完整，與 Discord
                # sink 並行時 read() 會拿到被截斷的 PNG（解碼只秀上半部 = 「只有一半」）。
                if not cv2.imwrite(tmp, frame):
                    raise RuntimeError("cv2.imwrite returned False")
                os.replace(tmp, path)                # atomic（同磁碟區；Windows 亦保證）
                try:
                    diagnostics.append_snapshot_index(cfg.log_dir, label, path)
                except Exception as e:
                    self.logger.warning("snapshot index failed (%s): %s", label, e)
            except Exception as e:
                self.logger.error("async snapshot failed (%s): %s", label, e)
                # 清掉可能殘留的 .part（imwrite 失敗或例外中斷時避免堆積）
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass
            finally:
                self._snap_q.task_done()

    def _wait_snapshot_ready(self, path: str, timeout_s: float | None = None) -> bool:
        """Wait until an async atomic snapshot exists and is non-empty."""
        if not path:
            return False
        timeout_s = (cfg.remote_aim_snapshot_wait_s if timeout_s is None
                     else max(0.0, timeout_s))
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    return True
            except OSError:
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def _ready_snapshot_paths(self, paths, timeout_s: float | None = None):
        """Resolve several async snapshot paths within one shared wait budget."""
        timeout_s = (cfg.remote_aim_snapshot_wait_s if timeout_s is None
                     else max(0.0, timeout_s))
        deadline = time.monotonic() + timeout_s
        ready = []
        for path in paths:
            remaining = max(0.0, deadline - time.monotonic())
            if self._wait_snapshot_ready(path, remaining):
                ready.append(path)
            else:
                self.logger.warning("snapshot not ready before send: %s", path)
        return ready

    def _drain_snapshot_queue(self, timeout_s: float) -> bool:
        """Give the daemon writer a bounded shutdown window."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while self._snap_q.unfinished_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))
        return True

    def _d3_cooldown_remaining(self) -> float:
        return harvester.d3_cooldown_remaining(
            time.monotonic(), self._last_d3_fire_at, cfg.d3_cooldown_s)

    def _fire_d3_at(self, x: int, y: int) -> bool:
        """Run the single canonical D3 sequence, stamping cooldown at the shot."""
        remaining = self._d3_cooldown_remaining()
        if remaining > 0:
            self.log_harvest.info("D3 cooldown blocked shot at (%d,%d): %.2fs left",
                                  x, y, remaining)
            return False
        ic.key_press("2")
        time.sleep(0.15)
        ic.key_press("3")
        time.sleep(0.3)
        self._last_d3_fire_at = time.monotonic()
        ic.click_at(int(x), int(y), hold=0.4)
        time.sleep(0.5)
        return True

    def _wait_for_d3_cooldown(self, deadline: float | None = None):
        """Cooperatively wait for remote fire without ever shooting inside 10s."""
        while True:
            remaining = self._d3_cooldown_remaining()
            if remaining <= 0:
                return True, ""
            if not getattr(self, "_running", True):
                return False, "程式已停止"
            if getattr(self, "paused", False):
                return False, "已暫停"
            if getattr(self, "_mine_resetting", False):
                return False, "礦坑重置中"
            if deadline is not None and time.time() >= deadline:
                return False, "等待 D3 冷卻時預算用盡"
            self.last_action = f"D3 冷卻 {remaining:.1f}s"
            time.sleep(min(0.1, remaining))

    # ---- 觀察 ---------------------------------------------------------------
    def observe(self, frame) -> Observation:
        score = self.listener.latest_score()
        if score > self._peak_audio_since_hb:
            self._peak_audio_since_hb = score       # 捕捉 30s heartbeat 取樣漏掉的 chill 尖峰
        chill_audio = score >= cfg.audio_match_threshold
        # H060：防掛機 Space 的原地跳音效會被認成 chill（2026-07-22 三次 REENTRY 誤報
        # 全在按鍵後 2s）。bot 知道自己何時按的 → 用時間窗直接排除，不倚賴參考集品質。
        if chill_audio and audio.chill_muted_after_antiafk(
                self._antiafk_pressed_at, time.time(), cfg.antiafk_chill_mute_s):
            chill_audio = False
            if not self._antiafk_mute_logged:      # 每次按鍵只記一筆，不每幀洗 log
                self._antiafk_mute_logged = True
                self.logger.info("chill 靜音（音訊 %.2f）：防掛機 Space 後 %.0fs 內，"
                                 "判定為原地跳音效", score, cfg.antiafk_chill_mute_s)
        chill_text = False
        if chill_audio:
            if not cfg.chill_require_ocr:
                chill_text = True                    # 只靠音訊（OCR 不穩/視窗化）
                self.logger.info("chill 觸發（音訊 %.2f，未要求 OCR 確認）", score)
            else:
                region = capture.crop(frame, cfg.chill_text_region)
                text = ocr.read_text(region, cfg.tesseract_path).strip()
                chill_text = ocr.contains_any(text, cfg.chill_phrases)
                if chill_text:
                    self.logger.info("chill CONFIRMED (audio=%.2f text=%r)", score, text)
                else:
                    self.logger.warning("audio triggered (%.2f) but text NOT confirmed: %r",
                                        score, text)
                    self._snapshot(frame, "audio_no_text")
        # chill 確認時跳過 reset 的同步 Tesseract OCR（~3s）：chill 優先序高於 reset
        # （states.decide_transition MINING/RESET_WAIT 皆 chill 先判），這幀必轉 HARVESTING，
        # reset 結果用不到。讓採集盡快開始——reset 途中遇 chill 要搶在礦物被重置前挖掉。
        # chill 未確認（require_ocr 下 OCR 沒過）才照常檢查 reset，不漏判礦坑重置。
        chill_confirmed = chill_audio and chill_text
        mine_resetting = False if chill_confirmed else self._check_reset(frame)
        manual = self._manual_reentry
        if manual:
            self._manual_reentry = False        # 一次性消費：不留舊旗標補刀（比照 aim-reply 不排隊）
        return Observation(chill_audio=chill_audio, chill_text=chill_text,
                           harvest_done=False, harvest_failed=False,
                           human_cleared=self.human_cleared,
                           mine_resetting=mine_resetting,
                           reset_complete=self._update_reset_complete(),
                           reentry_done=self._reentry_done,
                           reentry_failed=self._reentry_failed,
                           auto_reenter=self._reentry_active(),
                           manual_reentry=manual)

    def _update_reset_complete(self) -> bool:
        """RESET_WAIT 中追蹤「banner reset 字樣已消失＋沉澱夠久」（REENTRY 觸發條件）。

        banner 快取由背景 worker 更新（auto_reenter 下 RESET_WAIT 也跑）；字樣一回來
        計時歸零重來——重置訊息可能閃爍，沉澱期就是為了吃掉這種抖動。
        """
        if self.state is not State.RESET_WAIT or not self._reentry_active():
            self._reset_clear_since = 0.0
            return False
        if self._mine_resetting:
            self._reset_clear_since = 0.0
            return False
        now = time.time()
        if self._reset_clear_since == 0.0:
            self._reset_clear_since = now
            return False
        return now - self._reset_clear_since >= cfg.reentry_reset_settle_s

    def _maybe_detect_world(self, event_text: str):
        """用 OCR 到的事件文字推斷目前世界（事件分世界）；鎖定後採集確認的低階排除清單
        會收斂成該世界的，更準。世界改變時記一筆 log。無法判斷時保持現況（不洗 log）。"""
        prev = game_data.current_world_name()
        world = game_data.update_world_from_event(event_text)
        if world and world != prev:
            self.logger.info("偵測到世界: %s（依事件 %r）", world, event_text.strip()[:40])
            self._adopt_sticky_for_world(world)

    def _maybe_detect_world_from_ore_lines(self, new_lines):
        """礦名反推世界（Task 4.1）：7/9 世界 events 空、事件式偵測永遠鎖不了它們；
        帳本新增行裡的被動聊天 Surreal/Mythic 礦名（其名在 common_ores，才是
        detect_world_from_ore 的比對來源）是更高頻的世界信號，且 verify OCR 已經在讀
        這些行——零額外 OCR 成本。餵「全部新增行」（ledger.new_lines）而非只餵稀有行
        （稀有礦依定義不在 common_ores、永遠對不上）。只在世界尚未鎖定時嘗試（已鎖定
        就不需要、也避免和事件式偵測的結果互相覆蓋）。只掛在 HARVESTING 的 verify/帳本
        路徑，MINING 期間的聊天輪詢不做（會加 OCR 成本，見 t4.1-brief）。
        """
        if game_data.current_world_name() is not None:
            return
        for line in new_lines:
            ore_name = ocr.found_ore_name(line, cfg.found_keywords)
            if not ore_name:
                continue
            world = game_data.detect_world_from_ore(ore_name)
            if world:
                game_data.set_world(world)
                self.logger.info("世界鎖定（礦名反推）: %s（依礦名 %r）", world, ore_name)
                self._adopt_sticky_for_world(world)
                return

    def _check_reset(self, frame) -> bool:
        """讀重置偵測快取。OCR 本體已移背景 worker（_banner_ocr_loop），不再卡主迴圈。

        H051：HARVESTING 也讀——worker 在該狀態不跑，快取凍住＝「進採集前重置已偵測」，
        decide_transition 靠它把採集收尾導回 RESET_WAIT（RESET_WAIT/REENTRY/NEEDS_HUMAN
        各分支不讀此旗標，維持 False 不影響）。
        """
        if self.state not in (State.MINING, State.HARVESTING):
            return False
        return self._mine_resetting

    def _check_spawn_chill(self, obs, frame):
        """spawn chill 通知：chill 響但 bot 在挖不到的狀態（NEEDS_HUMAN/REENTRY）→ 通知一次。

        礦坑刷新時偶爾稀有礦直接生在預設方塊（spawn chill），chill 音效照響但 bot 不在
        可挖區域、無法自動採集。決策走純函式 should_notify_spawn_chill；這裡只管
        episode 去抖動（chill_audio 回落時重置旗標）＋副作用（截圖/事件/Discord/本機提醒）。
        """
        if not obs.chill_audio:
            self._spawn_chill_notified = False       # chill 結束 → 重新武裝，下次可再通知
            return
        if not should_notify_spawn_chill(self.state, obs.chill_audio, obs.chill_text,
                                         self._spawn_chill_notified):
            return
        self._spawn_chill_notified = True
        path = self._snapshot(frame, "spawn_chill")
        self.log.log("SPAWN_CHILL", state=self.state.value,
                     audio=round(self.listener.latest_score(), 2), image_path=path)
        self.logger.warning("spawn chill：chill 觸發（音訊 %.2f）但處於 %s（挖不到），已通知",
                            self.listener.latest_score(), self.state.value)
        self._alert("spawn chill！稀有 礦在刷新預設方塊，bot 挖不到")

    def _banner_ocr_loop(self):
        """背景執行緒：頂部事件列 OCR（重置偵測＋世界推斷）移出主迴圈。

        原本 _check_reset 每 2s 在主迴圈同步跑 tesserocr（~400ms）——這是 MINING tick
        最大的週期性卡點，boost 到期偵測（0.2s 高頻、「到期即補」）每 2 秒就被拖一次。
        worker 只讀 _latest_frame（主迴圈每 tick 發佈；grab 回傳的 buffer 之後不再被
        改寫，跨執行緒唯讀安全），結果寫 _mine_resetting/_banner_text 快取（bool/str
        賦值在 GIL 下原子，與熱鍵執行緒寫 human_cleared 同模式）。tesserocr 走
        threading.local，worker 自持一個引擎實例（與 capture 的 mss 同模式）。
        只在 MINING 且未暫停時跑（原 _check_reset 同語意）；D4 路徑重用 _banner_text。
        """
        while self._running:
            time.sleep(0.1)
            try:
                frame = self._latest_frame
                # auto_reenter 下 RESET_WAIT 也要跑：REENTRY 的觸發條件是「reset 字樣
                # 消失＋沉澱」，worker 不跑快取凍在 True、reset_complete 永遠不成立。
                allowed = (self.state is State.MINING
                           or (self._reentry_active()
                               and self.state is State.RESET_WAIT))
                if frame is None or self.paused or not allowed:
                    continue
                now = time.time()
                # 近門檻加速（2026-07-11）：Capacity ≥99 → worker 輪詢加速到 0.5s，
                # 容量飽和期間高頻監看橫幅（平時仍 2.0s）。capacity OCR 全滅時沿用 reset_check_interval_s。
                if (self._capacity_pct is not None
                        and self._capacity_pct >= cfg.capacity_fast_from):
                    interval = cfg.capacity_fast_interval_s
                else:
                    interval = cfg.reset_check_interval_s
                if now - self._last_reset_check < interval:
                    continue
                self._last_reset_check = now
                text = ocr.read_text(capture.crop(frame, cfg.chill_text_region),
                                     cfg.tesseract_path)
                self._banner_text = text
                self._banner_text_at = time.time()
                self._maybe_detect_world(text)  # 搭便車：頂部事件列也用來推斷目前世界
                banner_resetting = ocr.contains_any(text, cfg.reset_phrases)
                # Capacity 監看（輔助信號，2026-07-12 起不再觸發 RESET_WAIT）：同輪裁
                # capacity_region → parse → 快取＋streak。已確認飽和（streak>=2）後跳過
                # capacity OCR 省一半開銷——值已釘死不會變，加速輪詢 0.5s 期間可能持續很久；
                # _capacity_pct 維持舊值供 HUD 顯示與加速間隔判斷（banner OCR 每輪照跑）。
                # H045：RESET_WAIT 期間即使飽和鎖定（streak>=2）也照讀容量——
                # 100→0 的翻轉就是「重置真的完成」的錨，鈴聲錄音窗靠它開。
                if self._capacity_streak < 2 or self.state is State.RESET_WAIT:
                    cap_pct_this = ocr.read_capacity_pct(
                        capture.crop(frame, cfg.capacity_region), cfg.tesseract_path)
                    if cap_pct_this is not None:
                        self._capacity_pct = cap_pct_this   # 讀成功才更新（失敗沿用舊值）
                    self._capacity_streak, cap_trigger = update_capacity_streak(
                        self._capacity_streak, cap_pct_this, cfg.capacity_reset_threshold)
                    if cap_trigger and not self._capacity_full_logged:
                        self.logger.info("容量已滿（≥%.0f 連續2次），不停機、已加速監看重置橫幅",
                                         cfg.capacity_reset_threshold)
                        self._capacity_full_logged = True
                    self._maybe_arm_chime(cap_pct_this)
                # 唯一停機信號是 reset 橫幅；cap_trigger 不再寫 _mine_resetting／_human_reason
                # （2026-07-12 死鎖實錄：Capacity 假陽性 → 卡死 RESET_WAIT）。
                resetting = banner_resetting
                if resetting and not self._mine_resetting:
                    self.logger.info("偵測到礦坑重置: %r", text.strip()[:60])
                    self._human_reason = "礦坑重置，請重新定位後按 Q 繼續"
                self._mine_resetting = resetting
            except Exception as e:              # OCR 偶發失敗不中斷 worker
                self.logger.error("banner OCR worker: %s", e)

    def _window_displaced(self) -> bool:
        """節流查 Roblox 視窗是否跑位（失焦/被移動或縮放）。需先有啟動基準。"""
        if not cfg.window_check_enabled or self._window_baseline is None:
            return False
        now = time.time()
        if now - self._last_window_check < cfg.window_check_interval_s:
            return self._window_bad
        self._last_window_check = now
        current = window.query_window(cfg.window_title)
        reason = window.displacement_reason(
            current, self._window_baseline,
            cfg.window_pos_tolerance_px, cfg.window_size_tolerance_px)
        if reason is not None:
            b = self._window_baseline
            self.logger.info("視窗檢查 %s: cur(%d,%d,%d,%d fg=%s) vs base(%d,%d,%d,%d)",
                             reason, current.x, current.y, current.w, current.h,
                             current.foreground, b.x, b.y, b.w, b.h)
        self._window_displaced_reason = reason
        self._window_bad = reason is not None
        return self._window_bad

    def _focus_roblox(self) -> bool:
        """啟動時：找到 Roblox 視窗、**最大化填滿螢幕**、叫到最前面取得焦點。

        回傳是否真的取得前景焦點。False = 輸入不會進遊戲，run() 應中止而非空挖瞎挖。
        注意：用 SW_MAXIMIZE（不可用 SW_RESTORE，會把已最大化的視窗縮成小視窗 → 座標全錯）。
        """
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, cfg.window_title)
        if not hwnd:
            self.logger.error("找不到 Roblox 視窗（title=%s）", cfg.window_title)
            return False
        u.ShowWindow(hwnd, 3)                        # SW_MAXIMIZE：鎖定填滿螢幕
        time.sleep(0.3)
        fg = u.GetForegroundWindow()
        t1 = u.GetWindowThreadProcessId(fg, 0)
        t2 = u.GetWindowThreadProcessId(hwnd, 0)
        u.AttachThreadInput(t1, t2, True)
        u.BringWindowToTop(hwnd); u.SetForegroundWindow(hwnd)
        u.AttachThreadInput(t1, t2, False)
        # 輪詢等焦點到手（上限 1.0s、每 50ms 查）：多數情況 0.1-0.3s 即成功，固定睡滿
        # 1.0s 是白等——此函式在採集成功回正/Q 恢復/回 MINING/防掛機保活都會跑，每次省 ~1s。
        deadline = time.time() + 1.0
        while time.time() < deadline and u.GetForegroundWindow() != hwnd:
            time.sleep(0.05)
        if u.GetForegroundWindow() != hwnd:          # API 沒成功 → 點畫面中央取焦（已最大化，中央在遊戲內）
            import pydirectinput
            pydirectinput.moveTo(cfg.screen_w // 2, cfg.screen_h // 2)
            time.sleep(0.2); pydirectinput.click(); time.sleep(0.5)
        got = (u.GetForegroundWindow() == hwnd)
        self.logger.info("Roblox 聚焦%s (hwnd=%s, fg=%s)", "成功" if got else "失敗",
                         hwnd, u.GetForegroundWindow())
        if not got:
            self.logger.warning("Roblox 未取得前景焦點 — 輸入不會進遊戲；請點一下遊戲視窗再啟動")
        return got

    def _set_movement_mode(self, target: str, skip_event=None) -> bool:
        """把 Roblox 設定 Movement Mode 切到 target（三值之一）。

        決策純函式在 roblox_menu.py，這裡只做 I/O（Esc/點擊/捲動/OCR）。冪等：已是
        目標值時不點任何箭頭直接收工。任一步不確定 → Esc 回中性 → 整鏈重試
        cfg.menu_retry_max 次 → 仍失敗回 False（呼叫端依情境分流 NEEDS_HUMAN 或記警告）。

        skip_event：Q 跳過旗標（只啟動呼叫端傳；其餘呼叫端不傳＝只吃時間預算）。
        時間預算 cfg.menu_budget_s（實測成功 71~82s、失敗曾燒 170s；spec 2026-07-10 第 4 節）：
        起算 deadline，鏈內所有檢查點超時即中止走失敗路徑。

        優化候選（先靠本方法的 log 收數據，再決定做不做）：
        - 座標快取直點：Settings 分頁 / Movement Mode 列 / 右箭頭座標若每次都穩定不變，
          可跳過部分 OCR 直接點擊（見 log_act 的「MM座標記錄（快取候選）」一行）。
        - 滑條直拉到底（2026-07-09 使用者實測）：捲軸拉到最底就能看到 Movement Mode；
          若 log 顯示逐屏滾輪捲動找標籤是耗時大宗，可改成一步拖到底取代逐屏捲動。
        - 現行每次 `_menu_ocr` 是 RapidOCR 全面板辨識（~1-3s），是主要耗時來源的假設，
          待 log（`menu OCR[...]` 的 grab/ocr 耗時拆分）證實。
        """
        t_start = time.perf_counter()
        deadline = time.perf_counter() + cfg.menu_budget_s

        def _aborted() -> bool:
            if not self._running:
                return True
            if skip_event is not None and skip_event.is_set():
                return True
            return time.perf_counter() > deadline

        others = tuple(o for o in cfg.movement_mode_options if o != target)
        for attempt in range(cfg.menu_retry_max + 1):
            if _aborted():   # 此處選單是關的（上一輪失敗後已 Esc），不再按 Esc
                reason = "Q 跳過" if skip_event is not None and skip_event.is_set() else \
                         ("程式結束" if not self._running else f"預算 {cfg.menu_budget_s:.0f}s 超時")
                self.log_act.info("Movement Mode 切換中止（%s）：target=%s 於第 %d 次嘗試前，總耗時 %.1fs",
                                  reason, target, attempt + 1, time.perf_counter() - t_start)
                return False
            if self._set_movement_mode_once(target, others, should_abort=_aborted):
                self.log_act.info(
                    "Movement Mode 切換鏈成功：target=%s 嘗試次數=%d 總耗時 %.1fs",
                    target, attempt + 1, time.perf_counter() - t_start)
                return True
            self.log_act.warning("Movement Mode 切換失敗（第 %d 次），Esc 回中性後重試",
                                 attempt + 1)
            ic.key_press("esc")
            time.sleep(cfg.menu_close_settle_s)
        self.log_act.info(
            "Movement Mode 切換鏈失敗：target=%s 共 %d 次嘗試，總耗時 %.1fs",
            target, cfg.menu_retry_max + 1, time.perf_counter() - t_start)
        return False

    def _set_movement_mode_once(self, target: str, others: tuple, should_abort=None) -> bool:
        """單次嘗試：開選單→找 Settings→找 Movement Mode 列→比對值→不符則點右箭頭。

        should_abort：可注入的中止判斷（_aborted 閉包）。在捲屏迴圈與箭頭點擊迴圈每輪頂
        檢查——中止＝直接 return False，**不自己按 Esc**：外層失敗路徑必按一次 Esc 回中性，
        這裡再按會變兩下（第二下重開選單、留著吃掉後續挖礦按鍵）（spec 2026-07-10 第 6 節）。
        """
        t_start = time.perf_counter()

        t0 = time.perf_counter()
        ic.key_press("esc")
        time.sleep(cfg.menu_open_settle_s)
        esc_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        records = self._menu_ocr("open-check")
        ocr_open_s = time.perf_counter() - t0
        if not roblox_menu.menu_open(records, cfg.menu_fuzzy_min_ratio):
            self.log_act.warning("Movement Mode 切換：Esc 後未偵測到選單開啟")
            self.log_act.info(
                "MM切換總結 target=%s 失敗於=未偵測到選單開啟：總耗時 %.1fs（esc %.1f + OCR(open) %.1f）",
                target, time.perf_counter() - t_start, esc_s, ocr_open_s)
            return False

        tab_xy = roblox_menu.find_tab_center(records, "Settings", cfg.menu_fuzzy_min_ratio)
        if tab_xy is None:
            self.log_act.warning("Movement Mode 切換：找不到 Settings 分頁")
            self.log_act.info(
                "MM切換總結 target=%s 失敗於=找不到 Settings 分頁：總耗時 %.1fs（esc %.1f + OCR(open) %.1f）",
                target, time.perf_counter() - t_start, esc_s, ocr_open_s)
            return False
        t0 = time.perf_counter()
        ic.click_at(*tab_xy)
        time.sleep(cfg.menu_open_settle_s)
        tab_s = time.perf_counter() - t0

        row_y = None
        records = []
        scroll_count = 0
        t0 = time.perf_counter()
        fast_row = self._menu_movement_fast("initial")
        if fast_row is not None:
            row_y, value_text = fast_row
        else:
            for i in range(cfg.menu_scroll_max_screens):
                if should_abort and should_abort():
                    # 不在這裡按 Esc：回 False 後外層「失敗→Esc 回中性」必按一次，這裡再按
                    # 會變兩下（第二下把剛收的選單重新打開、留著吃掉後續挖礦按鍵）
                    self.log_act.info("Movement Mode 切換中止：捲屏階段（選單交外層 Esc 收），總耗時 %.1fs",
                                      time.perf_counter() - t_start)
                    return False
                records = self._menu_ocr(f"scroll-{i + 1}")
                row_y = roblox_menu.find_label_row_y(records, "Movement Mode", cfg.menu_fuzzy_min_ratio)
                if row_y is not None:
                    break
                ic.move_to(*cfg.menu_scroll_xy)
                ic.scroll(cfg.menu_scroll_amount)
                time.sleep(cfg.menu_open_settle_s)
                scroll_count += 1
        scroll_s = time.perf_counter() - t0
        if row_y is None:
            self.log_act.warning("Movement Mode 切換：捲動 %d 屏仍找不到標籤",
                                 cfg.menu_scroll_max_screens)
            self.log_act.info(
                "MM切換總結 target=%s 失敗於=捲動仍找不到標籤：總耗時 %.1fs"
                "（esc %.1f + OCR(open) %.1f + tab %.1f + 找標籤 %.1fs/捲%d屏）",
                target, time.perf_counter() - t_start, esc_s, ocr_open_s, tab_s,
                scroll_s, scroll_count)
            return False

        t0 = time.perf_counter()
        if fast_row is None:
            value_text = roblox_menu.read_row_value(
                records, row_y, cfg.menu_value_column_x_range, cfg.menu_row_y_tolerance_px)
        read_s = time.perf_counter() - t0
        if roblox_menu.value_matches_target(value_text, target, others, cfg.menu_fuzzy_min_ratio):
            self.log_act.info("Movement Mode 已是目標值 %s，收工", target)
            self.log_act.info(
                "MM座標記錄（快取候選）：Settings=%s row_y=%d arrow=(%d,%d)",
                tab_xy, row_y, cfg.menu_arrow_right_x, row_y)
            self.log_act.info(
                "MM切換總結 target=%s 成功（已是目標值）：總耗時 %.1fs"
                "（esc %.1f + OCR(open) %.1f + tab %.1f + 找標籤 %.1fs/捲%d屏 + 讀值 %.1f）",
                target, time.perf_counter() - t_start, esc_s, ocr_open_s, tab_s,
                scroll_s, scroll_count, read_s)
            ic.key_press("esc")
            time.sleep(cfg.menu_close_settle_s)
            return True

        t0 = time.perf_counter()
        for click_i in range(cfg.menu_arrow_click_max):
            if should_abort and should_abort():
                # 同捲屏階段：Esc 交外層失敗路徑收，避免按兩下重開選單
                self.log_act.info("Movement Mode 切換中止：箭頭點擊階段（選單交外層 Esc 收），總耗時 %.1fs",
                                  time.perf_counter() - t_start)
                return False
            ic.click_at(cfg.menu_arrow_right_x, row_y)
            time.sleep(cfg.menu_arrow_settle_s)
            fast_row = self._menu_movement_fast(f"arrow-{click_i + 1}")
            if fast_row is not None:
                row_y, value_text = fast_row
            else:
                records = self._menu_ocr(f"arrow-{click_i + 1}")
                value_text = roblox_menu.read_row_value(
                    records, row_y, cfg.menu_value_column_x_range, cfg.menu_row_y_tolerance_px)
            if roblox_menu.value_matches_target(value_text, target, others, cfg.menu_fuzzy_min_ratio):
                arrow_s = time.perf_counter() - t0
                self.log_act.info("Movement Mode 切到 %s（點了 %d 次右箭頭）", target, click_i + 1)
                self.log_act.info(
                    "MM座標記錄（快取候選）：Settings=%s row_y=%d arrow=(%d,%d)",
                    tab_xy, row_y, cfg.menu_arrow_right_x, row_y)
                self.log_act.info(
                    "MM切換總結 target=%s 成功：總耗時 %.1fs"
                    "（esc %.1f + OCR(open) %.1f + tab %.1f + 找標籤 %.1fs/捲%d屏 + 箭頭×%d %.1f）",
                    target, time.perf_counter() - t_start, esc_s, ocr_open_s, tab_s,
                    scroll_s, scroll_count, click_i + 1, arrow_s)
                ic.key_press("esc")
                time.sleep(cfg.menu_close_settle_s)
                return True
        arrow_s = time.perf_counter() - t0

        self.log_act.warning("Movement Mode 切換：點滿 %d 次右箭頭仍未到目標 %s（現讀值=%r）",
                             cfg.menu_arrow_click_max, target, value_text)
        self.log_act.info(
            "MM切換總結 target=%s 失敗於=點滿右箭頭仍未到目標：總耗時 %.1fs"
            "（esc %.1f + OCR(open) %.1f + tab %.1f + 找標籤 %.1fs/捲%d屏 + 箭頭×%d %.1f）",
            target, time.perf_counter() - t_start, esc_s, ocr_open_s, tab_s,
            scroll_s, scroll_count, cfg.menu_arrow_click_max, arrow_s)
        return False

    def _menu_ocr(self, label: str = ""):
        """截圖＋裁 menu_panel_region＋OCR 文字框（回傳座標已還原成全螢幕座標）。"""
        t0 = time.perf_counter()
        frame = capture.grab()
        crop = capture.crop(frame, cfg.menu_panel_region)
        r = cfg.menu_panel_region
        t1 = time.perf_counter()
        records = ocr.read_text_boxes(crop, region_offset=(r.x, r.y))
        t2 = time.perf_counter()
        self.log_act.debug("menu OCR[%s]：%d 框，grab %.0fms + ocr %.0fms",
                           label, len(records), (t1 - t0) * 1000, (t2 - t1) * 1000)
        return records

    def _menu_movement_fast(self, label: str = ""):
        """讀固定 Movement Mode 列；不確定即回 None，呼叫端保留全面板 OCR 後備。"""
        t0 = time.perf_counter()
        frame = capture.grab()
        t1 = time.perf_counter()
        try:
            label_text = ocr.read_text_line(
                capture.crop(frame, cfg.menu_movement_label_region), engine="rapidocr")
            value_text = ocr.read_text_line(
                capture.crop(frame, cfg.menu_movement_value_region), engine="rapidocr")
        except Exception as exc:
            self.log_act.debug("menu fixed-ROI[%s] 不可用，回退全面板 OCR：%r", label, exc)
            return None
        option = roblox_menu.find_matching_option(
            value_text, cfg.movement_mode_options, cfg.menu_fuzzy_min_ratio)
        if (not roblox_menu.text_matches_label(
                label_text, "Movement Mode", cfg.menu_fuzzy_min_ratio)
                or option is None):
            self.log_act.debug(
                "menu fixed-ROI[%s] 不確定，回退全面板 OCR：label=%r value=%r",
                label, label_text, value_text)
            return None
        t2 = time.perf_counter()
        self.log_act.debug(
            "menu fixed-ROI[%s]：value=%r grab %.0fms + rec %.0fms",
            label, option, (t1 - t0) * 1000, (t2 - t1) * 1000)
        return cfg.menu_movement_row_y, value_text

    def _ensure_chat_open(self):
        """啟動 UI 前置檢查：聊天圖示狀態判定聊天框開關；關閉就點圖示開啟（H047／H063）。

        舊版靠輸入列 placeholder OCR 判斷，但聊天框開著且久無新訊息會被遊戲自動隱藏、
        placeholder 隨之消失 → 假陰性「關閉」→ 對已開啟的聊天框連點 toggle 圖示，反而
        關掉（2026-07-17／07-18 兩場實機事故）。改用左上聊天圖示外觀：開＝實心白泡泡、
        關＝空心白邊，任何狀態都看得到，不受自動隱藏影響。unknown（灰值落兩側夾之外，
        例如重置白閃過渡幀，或補丁被暗色浮層蓋住的 41.0）絕不點擊——誤判開頂多維持
        現狀，誤判關點下去才會把開著的聊天框關掉，比照 `_ensure_player_list_closed`
        的 toggle 安全方向。
        判關時**只點一次**（H063：`chat_open_max_retries=0`）——實機 5 場重試 0 次救回，
        而每次重試都是一次 toggle，讀值錯時奇數次點擊剛好把聊天框關掉。點擊/重讀額度
        用盡仍未判開 → 保留 WARNING + HUD，另存快照（snapshots/trace/，label
        chat_open_fail）供診斷，照常啟動（不發 Discord：啟動時人在旁邊，比照 preflight
        警訊分流慣例，見 CLAUDE.md）。
        """
        clicks = 0
        reads = 0
        while True:
            if self._env_check_skip("聊天框檢查"):   # Q 已按 → 略過該輪（含重試/重讀）
                return
            frame = capture.grab()
            crop = capture.crop(frame, cfg.chat_icon_state_region)
            state = vision.chat_icon_state(
                crop, cfg.chat_icon_probe,
                cfg.chat_icon_open_min_gray, cfg.chat_icon_closed_max_gray,
                cfg.chat_icon_closed_min_gray)
            probe_mean = vision.chat_icon_probe_mean(crop, cfg.chat_icon_probe)
            action = roblox_menu.plan_chat_open_action(
                state, clicks, reads,
                max_clicks=cfg.chat_open_max_retries + 1, max_reads=3)
            if action == "done":
                self.logger.info("UI 前置檢查：聊天框已開啟（圖示實心，probe=%.1f）", probe_mean)
                return
            if action == "click":
                if clicks >= 1:
                    self._focus_roblox()
                    self.logger.info(
                        "UI 前置檢查：聊天圖示仍空心，第 %d 次重試（重新聚焦再點，probe=%.1f）",
                        clicks, probe_mean)
                else:
                    self.logger.info("UI 前置檢查：聊天圖示空心，點擊開啟（probe=%.1f）", probe_mean)
                ic.click_at(*cfg.chat_icon_xy)
                time.sleep(cfg.chat_open_settle_s)
                clicks += 1
                continue
            if action == "reread":
                reads += 1
                # INFO 不是 DEBUG（H063）：unknown 是「補丁沒讀到圖示」的主要失敗型，
                # 實機 log_level=INFO，落 DEBUG 等於事後查不到它發生過。
                self.logger.info(
                    "UI 前置檢查：聊天圖示判定 unknown（未落兩側夾），重讀（第 %d 次，probe=%.1f）",
                    reads, probe_mean)
                time.sleep(0.3)
                continue
            # give_up：點擊或重讀額度用盡，或防禦性未知 state
            self.logger.warning(
                "UI 前置檢查：聊天框未開啟，可能影響採集確認（state=%s, probe=%.1f）", state, probe_mean)
            self.last_action = "⚠ 聊天框未開啟，採集確認可能失效"
            self._snapshot(frame, "chat_open_fail")   # label 無 reentry/sweep/d3/chill 關鍵字 → snapshots/trace/
            return

    def _ensure_player_list_closed(self):
        """啟動 UI 前置檢查：右上角玩家列表（Tab toggle）開著就按 Tab 關閉，避免遮擋右側點擊。

        Tab 是 toggle，列表沒開時按 Tab 反而打開 → 只有確實偵測到列表才可以按 Tab。
        偵測引擎用 RapidOCR（read_text_boxes）：實測 tesseract read_text 漏開啟樣本（單一前處理
        必有背景盲區，見 CLAUDE.md H014 精神）。rapidocr 不可用就整個跳過——寧漏勿誤，絕不盲按 Tab。
        """
        if not ocr.rapidocr_available():
            self.logger.warning("UI 前置檢查：rapidocr 不可用，跳過玩家列表檢查（寧漏勿誤，不盲按 Tab）")
            return
        t0 = time.perf_counter()
        frame = capture.grab()
        recs = ocr.read_text_boxes(capture.crop(frame, cfg.player_list_region))
        ocr1_ms = (time.perf_counter() - t0) * 1000
        joined = " ".join(r["text"] for r in recs)
        if not ocr.contains_any(joined, cfg.player_list_phrases):
            self.logger.info("UI 前置檢查：玩家列表已關閉（OCR %.0fms，%d 框）", ocr1_ms, len(recs))
            return
        self.logger.info("UI 前置檢查：玩家列表開啟，按 Tab 關閉（OCR %.0fms，%d 框）", ocr1_ms, len(recs))
        ic.key_press("tab")
        time.sleep(cfg.menu_open_settle_s)
        if self._env_check_skip("玩家列表複檢"):   # Q 已按 → 省下 ~2-8s 第二次 OCR
            return
        t0 = time.perf_counter()
        frame = capture.grab()
        recs = ocr.read_text_boxes(capture.crop(frame, cfg.player_list_region))
        ocr2_ms = (time.perf_counter() - t0) * 1000
        joined = " ".join(r["text"] for r in recs)
        if not ocr.contains_any(joined, cfg.player_list_phrases):
            self.logger.info("UI 前置檢查：玩家列表已關閉（按 Tab 後確認，OCR %.0fms）", ocr2_ms)
            return
        # 絕不按第二次 Tab：若第二次偵測是誤判，再按會把已關的列表重新打開。
        self.logger.warning("UI 前置檢查：玩家列表仍未關閉，可能遮擋點擊；請手動確認（OCR %.0fms）",
                            ocr2_ms)
        self.last_action = "⚠ 玩家列表未關閉，可能遮擋點擊"

    def _hotkey_loop(self):
        """背景執行緒：每 50ms 輪詢一次熱鍵，不受主迴圈阻塞影響。"""
        while self._running:
            self._hk.tick()
            time.sleep(0.05)

    # ---- Discord 命令輪詢 ----------------------------------------------------
    def _discord_poll_loop(self):
        """背景執行緒：定期輪詢 Discord 頻道新訊息，處理 ! 命令。"""
        while self._running:
            try:
                if self._running:
                    self._poll_discord()
            except Exception as e:
                # 輪詢失敗不中斷主迴圈，但要留痕（節流 60s）：07-19 RR#2 頻道
                # 01:37~02:17 全靜默，事後無法分辨「沒人打字」還是「輪詢死了」。
                now = time.time()
                if now - self._poll_fail_logged_at >= 60.0:
                    self._poll_fail_logged_at = now
                    self.log_discord.warning("discord poll failed: %s: %s",
                                             type(e).__name__, e)
            time.sleep(cfg.discord_poll_interval_s)      # 啟動即首輪；之後固定退避，失敗時也不空轉

    def _poll_discord(self):
        """讀 Discord 新訊息，處理命令；並輪詢 list 分頁與遙控器的反應點擊。"""
        from . import notify
        # 1. 表情輪詢：先查當前狀態的短命控制卡，再查持久遙控器／低優先 list 分頁。
        # 每張卡都只做一個 GET；沒有新文字訊息時也必須照常檢查。
        if self._rr_embed_mid and self.state is State.REENTRY:
            self._poll_rr_reactions()
        if self._stuck_alert_mid and self.state is not State.MINING:
            self._stuck_alert_mid = None       # 離開 MINING＝卡住語境失效，🏠 作廢（訊息留著）
        elif self._stuck_alert_mid:
            self._poll_stuck_reaction()
        if self._remote_message_id:
            self._poll_remote_reactions()
        if getattr(self, "_web_escalate", None):
            self._poll_web_escalate_reactions()
        if self._calib_session is not None:
            self._poll_calib_reactions()
        if self._list_message_id:
            self._poll_list_reactions()
        # 1b. 狀態同步：暫停/挖 礦狀態變了就原地編輯遙控器（PATCH，不推播）。
        # 只用 (paused, state) 當觸發條件避免高頻 PATCH 撞 rate limit；last_action 只在真的
        # PATCH 時順帶刷新（不在觸發條件內，否則每次 last_action 變都會 PATCH）。
        # REENTRY 中釘底凍結（2026-07-19 使用者需求）：遙控器功能回礦時用不上（暫停/繼續
        # ＝跳過、📷 有回礦卡自己的），八方位發圖會讓釘底邏輯每輪刪舊重貼＝洗版。
        # 狀態 PATCH 不閘——(paused, state) 變化天然只在進/出 REENTRY 各觸發一次，
        # 進場那次會把遙控器換成「回礦中，操作請用回礦卡」指引（_build_remote_embed）。
        # 反應輪詢照跑（▶️/⏸️→跳過 仍要通）；REENTRY 中釘底改由回礦卡接手（見 _repin_tick）。
        # 2026-07-26 加降頻（spec §7 A 降頻上限 discord_status_edit_min_interval_s）：
        # 狀態機快速擺盪（MINING↔HARVESTING）時不逐次 PATCH。被擋下的那次不更新
        # _remote_last_shown，下一輪輪詢（1s）條件仍成立會自動補，狀態不會停在舊值。
        if self._remote_message_id and self._remote_last_shown != (self.paused, self.state.value):
            if self._remote_edit_throttle.allow_edit(time.monotonic()):
                self._edit_remote_control()
        # 網頁常駐狀態鏡射（2026-07-28）：跟 Discord 遙控器 PATCH 用同一個變化條件，
        # 但獨立追蹤——不依賴 _remote_message_id（那是 Discord embed 是否已存在，
        # 跟網頁有沒有人連著無關）、也不跟 Discord API 節流共用（WS 廣播不吃 rate limit）。
        if getattr(self, "_web_status_last_shown", None) != (self.paused, self.state.value):
            self._web_status_last_shown = (self.paused, self.state.value)
            self._broadcast_status()
        # 2. 新訊息命令輪詢
        msgs = notify.fetch_messages(
            cfg.discord_bot_token, cfg.discord_channel_id,
            after=self._last_discord_msg_id, limit=10)
        # 2a. 釘底防抖（2026-07-19 spec，取代「一看到新訊息就刪舊貼新」）：看到新訊息
        # 只立旗標＋刷活動時間，頻道安靜滿 cfg.discord_repin_quiet_s 才刪舊貼新——
        # 連發（稀有礦通知＋截圖、八方位發圖空檔）期間不反覆刪貼，安靜後一次到位。
        # msgs 為空的輪次也要跑（到期重貼正是發生在安靜輪），所以放在 early return
        # 之前。REENTRY 凍結／回礦卡接手／_rr_busy 語意都在 _repin_tick 內；回礦收尾
        # 由 _rr_finalize 主動立遙控器旗標，不再依賴「輪詢剛好看到新訊息」。
        self._repin_tick(msgs, time.monotonic())
        if not msgs:
            return
        newest_id = msgs[0]["id"]                        # Discord 回傳 newest-first
        if self._last_discord_msg_id is None:
            # 首次輪詢：只記基準 ID，不處理歷史命令（避免重跑舊指令）
            self._last_discord_msg_id = newest_id
            self.log_discord.info("首次輪詢：基準 msg_id=%s（跳過歷史命令）", newest_id)
            return
        for msg in reversed(msgs):                       # oldest-first，確保命令順序
            self._last_discord_msg_id = msg["id"]
            if msg.get("author", {}).get("bot"):
                continue                                 # 跳過 bot 自己發的訊息
            content = msg.get("content", "").strip()
            # 命令不需 ! 前綴：第一個詞（不分大小寫）比對已知命令即觸發。
            # lstrip("!") 保留舊 ! 前綴相容；空白/空字串 = 一般聊天，忽略。
            command = discord_commands.parse_command(content)
            if command is not None:
                self._handle_discord_command(command)
            elif self._calib_session is not None:
                # 校準卡活躍（modal、必暫停）：文字指令與反應等價（`上|下 [px]` 等）
                self._handle_calib_text(content)
            elif self._aim_context is not None and self.state is State.NEEDS_HUMAN:
                # B3：NEEDS_HUMAN 且 aim context 存活時，一般訊息當瞄準回覆（無前綴，spec 第 2 節）
                self._handle_aim_reply(content)
            elif self._rr_ctx is not None and self.state is State.REENTRY:
                # 遠端回礦：REENTRY(remote) 等待時，一般訊息當回礦指令（無前綴，2026-07-12 spec）
                self._handle_reentry_reply(content)
            else:
                # 俯仰指令在挖礦中打了沒反應（2026-07-19 使用者反映）→ 回指引不靜默
                self._maybe_pitch_guidance(content)

    def _poll_list_reactions(self):
        """輪詢 list 訊息的表情：偵測「新點擊」→ 切換到該世界分頁（編輯同一則訊息）。

        單次抓 Message Object 的 reactions count 摘要；反應數上升 = 新點擊 → 切換。
        機器人自己貼表情時已把成功的 PUT 記成基線 1，故首輪不會誤觸發。
        一次輪詢最多切一頁（避免連續 PATCH）；點到「目前頁」的同行表情為 no-op。

        注意：WORLD_EMOJI = {世界名: 表情}，items() 解包成 (world, emoji)——
        早期版本曾把 world/emoji 變數對調（2026-07-05 修復）；現在由 emoji_to_world
        做單一反向映射，避免輪詢端再重複解包邏輯。
        """
        from . import notify
        token = cfg.discord_bot_token
        ch = cfg.discord_channel_id
        mid = self._list_message_id
        message = notify.fetch_message(token, ch, mid)
        if message is None:
            return
        self._list_reactions_seen, increments = notify.find_reaction_increments(
            message, self._list_reactions_seen, game_data.WORLD_EMOJI.values())
        for emoji, delta in increments:
            world = game_data.emoji_to_world(emoji)
            if world is None:
                continue
            if world != self._list_current_world:
                embed = game_data.format_event_list_embed(self._keep_ores, world=world)
                notify.edit_message(token, ch, mid, embed=embed)
                self._list_current_world = world
                self.log_discord.info("list 分頁切換 -> %s（反應 +%d）", world, delta)
                # 2026-07-26：切完把該表情歸零——不然使用者要「取消再點」才切得回來
                self._reset_reaction_button(mid, emoji, self._list_reactions_seen)
                return                              # 一次輪詢只切一頁

    # ---- 遙控器（單一持久訊息 + 反應按鈕）--------------------------------------
    def _build_remote_embed(self) -> dict:
        """組遙控器 embed。狀態欄同步顯示當前挖 礦狀態 + 暫停旗標，每次編輯都更新。"""
        if self.state is State.REENTRY:
            # 2026-07-19：回礦中遙控器功能用不上（暫停/繼續＝跳過、📷 有回礦卡自己的）——
            # 進 REENTRY 時 (paused, state) 變化天然觸發單次 PATCH 成這張指引卡，之後凍結
            #（釘底重貼也停，換回礦卡釘底）；離開 REENTRY 再 PATCH 回一般遙控器。
            return {
                "title": _REMOTE_TITLE,
                "description": (
                    "**狀態**：⛏ 回礦流程中\n"
                    "\n"
                    "操作已移至下方 **回礦卡**（顯示 attempt／目標層／俯仰等即時資訊，"
                    "會釘在頻道底）\n"
                    "此遙控器暫停即時更新，回礦結束後恢復；▶️/⏸️ 此時＝跳過回挖礦"
                ),
                "color": 0x5865F2,
                "footer": {"text": "回礦結束後恢復即時更新"},
            }
        running = not self.paused
        status_text = (f"{'🟢 挖礦中' if running else '🔴 已暫停'}"
                       f"　{self.state.value}"
                       + (f"（{self.last_action}）" if self.last_action and self.last_action != "—" else ""))
        return {
            "title": _REMOTE_TITLE,
            "description": (
                f"**狀態**：{status_text}\n"
                f"{self._build_remote_metrics_line()}\n"
                f"\n"
                f" 點 **{_REMOTE_RESUME_EMOJI}** 繼續挖礦（等同按 Q / `resume`）\n"
                f" 點 **{_REMOTE_PAUSE_EMOJI}** 暫停（等同按 Ctrl+Q / `pause`）\n"
                f" 點 **{_REMOTE_ABILITY_EMOJI}** 使用能力（在遊戲內按一次 X；等同 `ability`）\n"
                f" 點 **{_REMOTE_SNAP_EMOJI}** 截圖（立即回傳當前畫面）\n"
                f" 點 **{_REMOTE_REENTER_EMOJI}** 回礦（等同 `回礦` 指令，重走回礦流程取回正確方位）\n"
                f"\n"
                f"_狀態變更會直接更新此訊息；被其他通知擠上去時會重貼回頻道底_"
            ),
            "color": 0x57F287 if running else 0xED4245,
            "footer": {"text": "遙控器會維持在頻道最底部"},
        }

    def _build_remote_metrics_line(self) -> str:
        """遙控器狀態欄第二行：音訊／容量／運行時間（spec §7 A 的「不重要」那類）。

        2026-07-26 合併：這幾項原本在一則獨立的 StatusMessenger 訊息裡。spec §7 A 標題
        就是「遙控器卡（合併狀態顯示，1 則常駐）」，同一份狀態不該散在兩則訊息。

        ⚠ 這三個值**自己不觸發 edit**——只有 (paused, state) 變動或釘底重貼才會重組
        embed，順帶把最新值帶上去。否則音訊分數每 tick 都在動，等於每 3s PATCH 一次
        直到天荒地老（使用者 2026-07-26 明確要求：只有狀態轉換才刷新）。

        本函式由 Discord 輪詢執行緒呼叫，讀的是主迴圈寫的欄位——全部是單一 float/int
        的讀取（GIL 下為原子），讀到略舊的值只影響顯示，故不加鎖。
        """
        try:
            audio_score = self.listener.latest_score()
        except Exception:
            audio_score = 0.0
        cap = getattr(self, "_capacity_pct", None)
        cap_s = f"　容量 {cap:.0f}%" if cap is not None else ""
        uptime_s = int(time.time() - self._started)
        h, m = uptime_s // 3600, (uptime_s % 3600) // 60
        return f"音訊 {audio_score:.2f}{cap_s}　運行 {h}h{m:02d}m"

    def _post_remote_control(self):
        """貼一則新的遙控器到頻道底，貼 ▶️/⏸️ 反應，記基線。失敗靜默（下輪重試）。

        成功時用 add_reaction 的結果建立 count 基線（成功=1、失敗=0），避免額外三次
        get_reactions，也避免首輪把機器人自己的反應當成新點擊。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        embed = self._build_remote_embed()
        ok, detail, mid = notify.send_embed(token, ch, embed)
        if not (ok and mid):
            self.log_discord.info("remote post FAIL -> %s", detail)
            return
        seen = {}
        for em in (_REMOTE_RESUME_EMOJI, _REMOTE_PAUSE_EMOJI, _REMOTE_ABILITY_EMOJI,
                   _REMOTE_SNAP_EMOJI, _REMOTE_REENTER_EMOJI):
            added, _ = notify.add_reaction(token, ch, mid, em)
            seen[em] = 1 if added else 0
        self._remote_message_id = mid
        self._remote_reactions_seen = seen
        # 狀態同步基線：剛貼的 embed 已反映當前 (paused, state)，記下避免下輪重複 PATCH
        self._remote_last_shown = (self.paused, self.state.value)
        self._remote_repin.clear()   # 已貼到頻道底：清殘留 pending，防剛貼完又被防抖多刪貼一次
        self.log_discord.info("remote posted -> mid=%s (state=%s paused=%s)",
                              mid, self.state.value, self.paused)

    def _edit_remote_control(self):
        """原地編輯遙控器 embed（PATCH，不產生新訊息、不推播）。狀態變更或按鈕點擊後呼叫。

        取代舊設計（刪舊貼新）：編輯同一則訊息即更新狀態顯示，不洗版、不觸發通知。
        失敗處理：訊息被人手動刪掉（HTTP 404 / 10008）→ 視為遙控器遺失，重貼一則；
        其他失敗（網路、rate limit）→ 只記 log，下輪再試，_remote_message_id 保留。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        mid = self._remote_message_id
        ok, detail = notify.edit_message(token, ch, mid, embed=self._build_remote_embed())
        if ok:
            self.log_discord.debug("remote edited -> mid=%s (%s)", mid, detail)
            # 成功才更新同步基線：避免下輪重複 PATCH 同一狀態
            self._remote_last_shown = (self.paused, self.state.value)
        else:
            self.log_discord.info("remote edit FAIL -> mid=%s %s", mid, detail)
            # 訊息被人手動刪掉（HTTP 404 / 10008）→ 視為遙控器遺失，重貼一則取代
            if "HTTP 404" in detail or "10008" in detail:
                self.log_discord.info("remote 消失（已刪）-> 重貼一則")
                self._remote_message_id = None
                self._post_remote_control()       # _post 內部會設 _remote_last_shown
                return
            # 其他失敗（網路、rate limit）：不更新 _remote_last_shown → 下輪 _poll_discord
            # 的狀態同步條件（last_shown != current）仍成立，會自動重試。

    def _repost_remote_control(self):
        """刪舊遙控器、貼新的到頻道底。

        兩個呼叫路徑：(1) 被其他訊息擠上去時重新釘底（_poll_discord 2a）——這條是本函式
        的**主要用途**；(2) 按鈕觸發後表情歸零的**降級路徑**：2026-07-26 起優先走
        `_reset_reaction_button`（原地清那顆表情，訊息不動），只有清不掉（權限被收回／
        改回 DM，HTTP 403 code 50003/50013）才落到這裡。
        刪除結果必記 log（舊設計不記，刪除失敗無從診斷）；刪失敗不擋重貼。
        """
        from . import notify
        old = self._remote_message_id
        if old:
            ok, detail = notify.delete_message(
                cfg.discord_bot_token, cfg.discord_channel_id, old)
            self.log_discord.info("remote repost delete mid=%s -> %s", old, detail)
        self._post_remote_control()

    def _repin_tick(self, msgs: list, now: float):
        """釘底防抖一輪：立旗標＋執行到期重貼（只做 Discord I/O，輪詢執行緒呼叫）。

        看到新訊息（含 bot 自己發的）只刷活動時間、立「待重貼」旗標；距頻道最後
        活動安靜滿 cfg.discord_repin_quiet_s 才真的刪舊貼新（RepinDebouncer）——
        連發期間不反覆刪貼，安靜後一次到位。REENTRY 中遙控器旗標不因新訊息立
        （釘底由回礦卡接手），改由 _rr_finalize 收尾主動立；回礦卡照舊受
        _rr_busy 擋（發圖/指令執行中不搬卡，掃完下一輪一次到位）。
        """
        frozen = self.state is State.REENTRY
        if msgs:
            self._remote_repin.note_activity(now)
            self._rr_repin.note_activity(now)
            newest = msgs[0]["id"]
            if (not frozen and self._remote_message_id
                    and newest != self._remote_message_id):
                self._remote_repin.mark_pending()
            if (frozen and self._rr_embed_mid and self._rr_ctx is not None
                    and newest != self._rr_embed_mid):
                self._rr_repin.mark_pending()
        quiet = cfg.discord_repin_quiet_s
        if not frozen and self._remote_repin.due(now, quiet):
            self._repost_remote_control()
        if (frozen and self._rr_ctx is not None and not self._rr_busy
                and self._rr_ctx.phase == "awaiting_cmd"
                and self._rr_repin.due(now, quiet)):
            self._rr_repost_embed()

    def _ensure_remote_control(self):
        """啟動時清掉跨重啟殘留的舊遙控器，再貼一則新的到頻道底。取代直接 _post_remote_control。

        根因（2026-07-09）：_remote_message_id 只存在記憶體，重啟後不認得上一輪的遙控器
        → 舊的永遠不會被刪、每次啟動多留一則（logs/discord.log 實錄）。對策：掃頻道近期
        20 則訊息 → find_remote_messages 找出**所有**遙控器（bot 作者＋embed 標題比對），
        全部刪除（每筆記 log）後貼新的。不做「認領＋原地編輯」：啟動訊息剛貼完，舊遙控器
        必不在頻道底，認領後第一輪 _poll_discord 也會立刻重貼（混合設計釘底），白做 PATCH。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        msgs = notify.fetch_messages(token, ch, limit=20)
        newest, stale = notify.find_remote_messages(msgs, _REMOTE_TITLE)
        # 清跨重啟殘留：每筆刪除都記 log（舊設計 delete 失敗無 log，無從診斷）
        for sid in ([newest] if newest else []) + stale:
            ok, detail = notify.delete_message(token, ch, sid)
            self.log_discord.info("remote stale delete mid=%s -> %s", sid, detail)
        self._post_remote_control()

    def _ensure_no_stale_calib(self):
        """啟動清跨重啟殘留校準卡：session 不跨重啟，殘留卡一律作廢刪除（spec 第 2 節）。

        復用 find_remote_messages 的「bot 作者＋embed 標題」匹配；newest 也不認領——
        殘留卡的 session 記帳已丟失，認領只會做出角度與記帳脫鉤的卡。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        msgs = notify.fetch_messages(token, ch, limit=20)
        newest, stale = notify.find_remote_messages(msgs, calibrate_pitch.CALIB_TITLE)
        for mid in ([newest] if newest else []) + stale:
            ok, detail = notify.delete_message(token, ch, mid)
            self.log_discord.info("stale calib card mid=%s deleted -> %s", mid, detail)

    def _reset_reaction_button(self, mid, emoji: str, seen: dict) -> bool:
        """按鈕按完歸零：清掉該表情的所有反應 → 機器人重貼一次 → 基線回 1。

        2026-07-26 使用者要求「善用刪除反應的功能，這樣就不用一直將訊息與反應全部
        刪除」。做完之後訊息原地不動、同一顆按鈕可以立刻再按。

        回 True＝已歸零；False＝這個頻道做不到（呼叫端該降級）。
        `_reaction_clear_ok` 記住永久性失敗（403/50003/50013），之後不再白試——
        暫時性失敗（網路/rate limit）不設旗標，下次照常再試。
        """
        from . import notify
        if not mid or not self._reaction_clear_ok:
            return False
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ok, detail = notify.clear_reaction(token, ch, mid, emoji)
        if not ok:
            if notify.reaction_clear_unsupported(detail):
                self._reaction_clear_ok = False
                self.log_discord.info(
                    "反應清除不可用（%s）→ 之後一律降級（遙控器回刪貼、其餘靠使用者自行取消）",
                    detail)
            else:
                self.log_discord.info("反應清除失敗（暫時性，下次再試）：%s", detail)
            return False
        # 機器人重貼自己那一顆，按鈕才不會消失；基線隨之回到 1
        added, add_detail = notify.add_reaction(token, ch, mid, emoji)
        seen[emoji] = 1 if added else 0
        if not added:
            self.log_discord.info("反應清除後重貼 %s 失敗：%s", emoji, add_detail)
        return True

    def _poll_remote_reactions(self):
        """輪詢遙控器反應：偵測 ▶️/⏸️ 新點擊 → 觸發 resume/pause，並把按下的表情歸零。

        動作觸發後**只清那顆表情再重貼**（2026-07-26），訊息原地不動。
        舊做法是刪舊訊息貼新的，理由寫著「DM 無法清除他人表情 HTTP 403 code 50003」
        ——但遙控器早就搬到伺服器頻道（實測 type=0、bot 有 MANAGE_MESSAGES），
        那個前提已經不成立，代價卻一直付著：每按一次按鈕就多一則訊息、7 次 API。
        真的清不掉（權限被收回／改回 DM）才降級回刪貼。

        單次抓 Message Object 的 reactions count；count 基線採同步語意，使用者自己取消
        反應時基線下降，下次再點即可再次觸發。fetch 失敗回 None 時保留舊基線。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        mid = self._remote_message_id
        message = notify.fetch_message(token, ch, mid)
        if message is None:
            return
        emojis = (_REMOTE_RESUME_EMOJI, _REMOTE_PAUSE_EMOJI, _REMOTE_ABILITY_EMOJI,
                  _REMOTE_SNAP_EMOJI, _REMOTE_REENTER_EMOJI)
        self._remote_reactions_seen, increments = notify.find_reaction_increments(
            message, self._remote_reactions_seen, emojis)
        actions = dict(zip(emojis, ("resume", "pause", "ability", "snap", "reenter")))
        action_taken = None
        for emoji, delta in increments:
            action = actions[emoji]
            action_taken = action
            if self._calib_session is not None and action != "snap":
                # 校準中：▶️/⏸️ 只記離場後意圖；⚡/🏠 拒絕。📷 唯讀照常（fall through）。
                if action in ("resume", "pause"):
                    self._calib_session.prev_paused = (action == "pause")
                    notify.send_message(token, ch,
                        f"🎯 校準中——離開校準後將"
                        f"{'保持暫停' if action == 'pause' else '恢復挖礦'}")
                else:
                    notify.send_message(token, ch, "❌ 校準中——先按校準卡 ❌ 離開再操作")
                self.log_discord.info("remote %s during calib -> intent/reject", action)
                break
            if action == "resume":
                # 等同 !resume：清人工旗標 + 解暫停；非阻塞狀態下也是 no-op 安全
                was_blocked = is_blocked_from_mining(self.state, self.paused)
                self.human_cleared = True
                self._rr_skip_on_pause_resume("remote ▶️")   # 回礦中繼續＝跳過回挖礦
                if self.paused:
                    self._resume()
                self.log_discord.info("remote ▶️ resume（反應 +%d, was_blocked=%s）",
                                      delta, was_blocked)
            elif action == "ability":
                # 等同 !ability：只寫旗標（輪詢執行緒鐵律——此方法在 Discord 輪詢執行緒跑，
                # 不碰 input_control），主迴圈 _tick 開頭消費 → 在遊戲內按一次 X。
                self._pending_ability = True
                self.log_discord.info("remote ⚡ ability（反應 +%d, queued state=%s）",
                                      delta, self.state.value)
            elif action == "snap":
                # 📷 即時截圖（2026-07-17）：唯讀觀測、零遊戲輸入——鐵律管的是輸入，
                # capture.grab 每執行緒自持 mss 實例，輪詢執行緒直接抓；主迴圈卡在
                # sweep/開場探測時也能看到當下畫面（排錯用途的重點就在這）。
                # 落「編號樣本」（sampler.save_sample）：R 取樣視窗退役後，
                # calibrate_surface --import NNN 的素材來源就是這裡。
                frame = capture.grab()
                stem = sampler.save_sample(frame, cfg.manual_snapshot_dir,
                                           self._pitch_offset_px)
                path = os.path.join(cfg.manual_snapshot_dir, f"{stem}.png")
                ok_send, detail = notify.send_images_message(
                    token, ch, f"📷 當前畫面 #{stem}（state={self.state.value}"
                               f"{'，已暫停' if self.paused else ''}）", [path])
                self.log_discord.info("remote 📷 screenshot #%s -> %s (%s)",
                                      stem, path, detail)
            elif action == "reenter":
                # 🏠 手動回礦（2026-07-17）：與 `回礦` 指令/STUCK 🏠 同一條路——守門
                # 純函式＋只寫旗標，REENTRY 開場鏈由主迴圈跑（可取回正確方位）。
                ok_re, reason = can_accept_manual_reentry(
                    self.state, self._reentry_active())
                if not ok_re:
                    notify.send_message(token, ch, f"❌ 回礦（🏠）未接受：{reason}")
                else:
                    self._manual_reentry = True
                    if self.paused:
                        self.paused = False
                        self._antiafk_last = 0.0
                    notify.send_message(
                        token, ch, "⛏ 手動回礦已排入（🏠）→ 下個 tick 進 REENTRY")
                self.log_discord.info("remote 🏠 reenter -> accepted=%s state=%s",
                                      ok_re, self.state.value)
            else:  # pause
                already = self.paused
                self._pause()
                self.log_discord.info("remote ⏸️ pause（反應 +%d, already=%s）",
                                      delta, already)
            break                              # 一次輪詢只處理一個動作
        if action_taken:
            # 表情歸零＝使用者可立即再點。優先原地清反應（訊息不動）；
            # 清不掉才退回舊的刪貼路徑。
            emoji = next((em for em, _ in increments if actions.get(em) == action_taken),
                         None)
            if not (emoji and self._reset_reaction_button(
                    mid, emoji, self._remote_reactions_seen)):
                self._repost_remote_control()

    def _handle_discord_command(self, command: discord_commands.DiscordCommand):
        """解析並執行 Discord 命令，更新 _keep_ores 並回覆結果。

        字串正規化與命令白名單在 discord_commands.parse_command；此處只做 I/O dispatch。
        """
        from . import notify
        token = cfg.discord_bot_token
        ch = cfg.discord_channel_id
        cmd = command.name
        args = command.args

        if self._calib_session is not None and cmd in (
                "pause", "resume", "回礦", "reenter", "ability", "轉", "rotate"):
            # 校準中（2026-07-18 spec 第 1 節）：pause/resume 只記離場後意圖不解除校準；
            # 其餘遊戲輸入指令一律拒絕不排隊。📷/shot/status 等唯讀不在此列、照常。
            if cmd in ("pause", "resume"):
                self._calib_session.prev_paused = (cmd == "pause")
                notify.send_message(token, ch,
                    f"🎯 校準中——已記下：離開校準後將"
                    f"{'保持暫停' if cmd == 'pause' else '恢復挖礦'}")
            else:
                notify.send_message(token, ch, "❌ 校準中——先按校準卡 ❌ 離開再操作")
            self.log_discord.info("CMD %s during calib -> intent/reject", cmd)
            return

        if cmd == "list":
            # list [世界]：指定分頁；無指定 → 預設 = 偵測到的世界（未偵測 = 全世界聯集）。
            # 送出後貼表情按鈕，之後使用者點表情即可切換分頁（編輯同一則訊息）。
            world: str | None = None
            if args:
                arg = args[0].lower()
                world = next((w for w in game_data.WORLDS if w.lower() == arg), None)
                if world is None:
                    notify.send_message(token, ch,
                        f"⚠️ 找不到世界 '{args[0]}'（已有：{', '.join(game_data.WORLDS)}）。顯示預設分頁。")
            if world is None:
                world = game_data.current_world_name()
            embed = game_data.format_event_list_embed(self._keep_ores, world=world)
            ok, detail, mid = notify.send_embed(token, ch, embed)
            if ok and mid:
                self._list_message_id = mid
                self._list_current_world = world
                self._list_reactions_seen = {}
                for em in game_data.WORLD_EMOJI.values():
                    added, _ = notify.add_reaction(token, ch, mid, em)
                    self._list_reactions_seen[em] = 1 if added else 0
            self.log_discord.info("CMD list -> world=%s mid=%s (%s)", world, mid, detail)

        elif cmd == "keep":
            added, not_found = [], []
            for a in args:
                ore = game_data.fuzzy_match_ore(a)
                if ore:
                    self._keep_ores.add(ore)
                    added.append(ore)
                else:
                    not_found.append(a)
            kept = game_data.format_keep_by_world(self._keep_ores)
            msg = f"✅ 新增保留：{', '.join(added) or '（無）'}\n目前保留：\n{kept}"
            if not_found:
                msg += f"\n⚠️ 找不到：{', '.join(not_found)}（用 `list` 看 礦物名）"
            notify.send_message(token, ch, msg)
            self._save_keep_ores()
            self.log_discord.info("CMD keep %s -> added=%s keep=%s", args, added, self._keep_ores)

        elif cmd == "unkeep":
            removed = []
            for a in args:
                ore = game_data.fuzzy_match_ore(a)
                if ore and ore in self._keep_ores:
                    self._keep_ores.discard(ore)
                    removed.append(ore)
            kept = game_data.format_keep_by_world(self._keep_ores)
            notify.send_message(token, ch,
                f"❌ 取消保留：{', '.join(removed) or '（無）'}\n目前保留：\n{kept}")
            self._save_keep_ores()
            self.log_discord.info("CMD unkeep %s -> removed=%s keep=%s", args, removed, self._keep_ores)

        elif cmd == "clear":
            self._keep_ores.clear()
            self._save_keep_ores()
            notify.send_message(token, ch, "🗑️ 保留清單已清空（所有事件都會刷新）")
            self.log_discord.info("CMD clear -> keep set cleared")

        elif cmd == "pause":
            # 遠距暫停：等同在電腦前按 Ctrl+Q（只暫停，不繼續；繼續走 !resume）。
            # _pause() idempotent 且會設 _antiafk_last，主迴圈暫停分支（run() 內）每輪
            # 呼叫 _antiafk_tick("暫停") → 防掛機在暫停期間照常保活，無需這裡額外處理。
            already = self.paused
            self._pause()
            notify.send_message(token, ch,
                f"{'ℹ️ 已在暫停中' if already else '⏸ 已暫停'}（狀態: {self.state.value}）\n"
                f"防掛機保持開啟，每 {cfg.antiafk_interval_s / 60:.0f} 分鐘自動保活一次\n"
                f"→ 用 `resume` 恢復挖礦（等同按 Q）")
            self.log_discord.info("CMD pause -> state=%s paused=%s", self.state.value, self.paused)

        elif cmd == "resume":
            # 遠距恢復採礦：等同在電腦前按 Q。設 human_cleared=True，主迴圈下個 tick
            # decide_transition 就會從 NEEDS_HUMAN/RESET_WAIT 跳 MINING（_on_enter(MINING)
            # 會 _focus_roblox；失敗自動降級回 NEEDS_HUMAN，使用者再 resume 一次）。
            # 在 MINING 暫停中（paused=True）也能用——同時 un pause 讓它能動。
            # 注意：執行緒安全——simple boolean assignment 在 Python GIL 下為原子，
            # 與既有 _toggle_pause 從熱鍵執行緒寫 human_cleared 同模式。
            # 阻塞判斷走純函式 is_blocked_from_mining（states.py；有測試覆蓋），
            # 避免 inline條件漏掉 RESET_WAIT 或暫停的 case。
            was_blocked = is_blocked_from_mining(self.state, self.paused)
            self.human_cleared = True
            self._rr_skip_on_pause_resume("cmd resume")   # 回礦中繼續＝跳過回挖礦
            if self.paused:
                self.paused = False
                self._antiafk_last = 0.0
            if was_blocked:
                notify.send_message(token, ch,
                    f"✅ 收到繼續指令（狀態: {self.state.value}{'，暫停中' if self.paused else ''}）\n"
                    f"→ 下個 tick 嘗試恢復挖礦（會先重新聚焦 Roblox；失敗會再回報）")
            else:
                notify.send_message(token, ch,
                    f"ℹ️ 目前狀態 {self.state.value}（非 NEEDS_HUMAN/RESET_WAIT/暫停），"
                    f"不需要恢復；last_action={self.last_action}")
            self.log_discord.info("CMD resume -> state=%s paused=False human_cleared=True",
                                  self.state.value)

        elif cmd == "status":
            s = self.stats
            up = int(time.time() - self._started)
            kept = ", ".join(sorted(self._keep_ores)) or "（空）"
            try:
                audio_score = self.listener.latest_score()
            except Exception:
                audio_score = 0.0
            notify.send_message(token, ch,
                f"📊 **狀態**：{self.state.value}（{self.last_action}）"
                + ("（暫停）" if self.paused else "") + "\n"
                f"⏱ 運行 {up // 60}m{up % 60:02d}s    🔊 音訊 {audio_score:.2f}\n"
                f"📈 boost {s['boosts']} · 刷新 {s['rerolls']} · 稀有 {s['rares']} · 卡住 {s['stuck']}"
                f" · 掃描 {s.get('radar_scans', 0)} · 削洞 {s.get('cave_skims', 0)}\n"
                + harvester.format_radar_status(self._radar_toggle["scan"],
                                                self._radar_toggle["cave"],
                                                self._radar_ocr_ok) + "\n"
                f"📝 保留：{kept}")
            self.log_discord.info("CMD status -> state=%s", self.state.value)

        elif cmd in ("校準", "calib"):
            # 俯仰校準（2026-07-18 spec）：此處在輪詢執行緒——只驗收＋寫 pending 旗標，
            # 暫停/pitch_reset/發卡全由主迴圈 _calib_start 執行（遊戲輸入鐵律）。
            target = calibrate_pitch.parse_calib_target(args)
            if target is None:
                notify.send_message(token, ch, "用法：`校準 挖礦`（預設）或 `校準 回礦`")
            else:
                ok_c, reason = calibrate_pitch.can_accept_calibration(
                    self.state is State.REENTRY, self._calib_session is not None)
                if not ok_c:
                    notify.send_message(token, ch, f"❌ 校準未接受：{reason}")
                else:
                    self._pending_calib_start = target
                    notify.send_message(token, ch,
                        "🎯 校準已排入 → 將暫停挖礦、歸位到 config 現值並發校準卡")
            self.log_discord.info("CMD 校準 -> target=%s state=%s", target, self.state.value)

        elif cmd == "shot":
            # 遠端截圖：抓全螢幕傳到 Discord，供遠距檢查當下畫面。
            # grab() 用 threading.local 持有各自的 mss 實例，此處在 discord 輪詢執行緒
            # 呼叫安全（非主迴圈執行緒）；DPI-aware 已全程式層級設好。
            # save_snapshot 同步 imwrite（單次命令不在熱迴圈，可接受）。
            try:
                frame = capture.grab()
                path = diagnostics.save_snapshot(frame, cfg.log_dir, "remote_check")
                ok, detail = notify.send_images_message(token, ch,
                    f"📸 遠端截圖（狀態: {self.state.value}）", [path])
                if not ok:
                    notify.send_message(token, ch, f"⚠️ 截圖傳送失敗：{detail}")
            except Exception as e:
                notify.send_message(token, ch, f"⚠️ 截圖失敗：{type(e).__name__}: {e}")
            self.log_discord.info("CMD shot -> state=%s", self.state.value)

        elif cmd == "ability":
            # 遠端手動使用能力：輪詢執行緒只寫旗標＋回覆，輸入由主迴圈消費（鐵律：
            # _handle_discord_command 在 Discord 輪詢執行緒跑，絕不碰 input_control）。
            # 布林旗標指定在 GIL 下為原子，與既有 human_cleared 跨執行緒寫入同模式，不需鎖。
            # 暫停中主迴圈不走 _tick → 旗標等恢復後執行（回覆已註明，預期行為）。
            self._pending_ability = True
            notify.send_message(token, ch,
                f"⚡ 能力指令已排入（狀態: {self.state.value}"
                + ("，暫停中——恢復後才會執行" if self.paused else "")
                + "）→ 主迴圈將在遊戲內按一次 X")
            self.log_discord.info("CMD ability -> queued state=%s paused=%s",
                                  self.state.value, self.paused)

        elif cmd in ("轉", "rotate"):
            # 遠端手動轉 45°（H059）：回礦落地後 yaw 被遊戲隨機化，約一半是對角；
            # 自動視覺判定經六種特徵量測皆無法兩側夾（見 07-21 findings），改由使用者
            # 看畫面自行校正。**不排隊**——使用者是看著畫面調整，延遲數分鐘才轉比不轉
            # 更糟（比照 can_accept_manual_reentry 的「不排隊，避免舊指令補刀」）。
            direction = discord_commands.parse_rotate_direction(args)
            if direction is None:
                notify.send_message(token, ch,
                    "❌ 轉：方向看不懂 → `轉`（右轉一格）／`轉 左`／`轉 右`")
            elif not can_consume_rotate(self.state):
                notify.send_message(token, ch,
                    f"❌ 轉未接受：{'採集進行中' if self.state is State.HARVESTING else '回礦流程中'}"
                    "，該階段有視角記帳，插一格會讓收尾轉回錯位")
            else:
                self._pending_rotate = direction
                notify.send_message(token, ch,
                    f"🧭 已排入{'右' if direction > 0 else '左'}轉 45°"
                    f"（狀態: {self.state.value}）→ 主迴圈下個 tick 送鍵")
            self.log_discord.info("CMD 轉 %s -> dir=%s state=%s",
                                  args, direction, self.state.value)

        elif cmd in ("回礦", "reenter"):
            # 手動觸發回礦（H044 spec 第 3 節；用途不限卡死——蒐集面板樣本等皆可）。
            # 輪詢執行緒只寫旗標；狀態守門走純函式 can_accept_manual_reentry。
            ok, reason = can_accept_manual_reentry(self.state, self._reentry_active())
            if not ok:
                notify.send_message(token, ch, f"❌ 回礦未接受：{reason}")
            else:
                self._manual_reentry = True
                unpause = ""
                if self.paused:
                    self.paused = False           # 比照 resume：手動回礦隱含「動起來」
                    self._antiafk_last = 0.0
                    unpause = "（已解除暫停）"
                notify.send_message(token, ch,
                    f"⛏ 手動回礦已排入{unpause}（狀態: {self.state.value}）→ 下個 tick 進 REENTRY")
            self.log_discord.info("CMD 回礦 -> accepted=%s state=%s", ok, self.state.value)

        elif cmd in discord_commands.RADAR_COMMAND_KIND:
            which = discord_commands.RADAR_COMMAND_KIND[cmd]
            label = "掃描(D2 左鍵)" if which == "scan" else "削洞(D2 Z)"
            want = discord_commands.parse_radar_toggle(args)
            if want == "bad":
                notify.send_message(token, ch,
                    f"❓ 用法：`{cmd} 開` / `{cmd} 關`（不帶參數＝查詢目前狀態）")
                self.log_discord.info("CMD %s bad args=%r", cmd, args)
                return
            if want is not None:
                self._radar_toggle[which] = want
                self._save_radar_toggle()        # 持久化：重啟後保留，使用者關掉才退回預設
                if want:
                    # 剛開啟時清掉上次觸發時刻，讓它下一輪就能按（不必等 grace）
                    self._radar_last[which] = 0.0
                self.log_discord.info("CMD %s -> %s", cmd, "on" if want else "off")
            notify.send_message(token, ch,
                f"{'✅ 已更新' if want is not None else 'ℹ️ 目前設定'}｜{label}："
                f"{'開' if self._radar_toggle[which] else '關'}\n"
                + harvester.format_radar_status(self._radar_toggle["scan"],
                                                self._radar_toggle["cave"],
                                                self._radar_ocr_ok))

        elif cmd == "help":
            notify.send_message(token, ch,
                "**MiningBot 指令**（直接輸入即可，不需 `!` 前綴）\n"
                "`pause` — 遠距暫停（等同 Ctrl+Q；防掛機保持開啟；用 `resume` 恢復）\n"
                "`resume` — 遠距恢復採礦（清 NEEDS_HUMAN/RESET_WAIT/暫停；等同按 Q）\n"
                "`status` — 查詢目前狀態、統計、保留清單\n"
                "`shot` — 截圖目前畫面並傳送（遠端檢查用）\n"
                "`ability` — 遠端按一次 X（手動使用能力；採集/回礦中會等空檔執行）\n"
                "`轉 [左|右]` — 遠端轉 45°（預設右轉；手動校正回礦落地後的斜向面向；"
                "採集/回礦中不接受，不排隊）\n"
                "`回礦` — 手動觸發回礦（卡死自救/蒐集面板樣本；同 `reenter`）\n"
                "`削洞 [開|關]` — D2 的 Z（Cave Skim）連續使用：冷卻好就自動再按，"
                "削掉特殊洞穴的方塊（不帶參數＝查詢；同 `caveskim`）\n"
                "`掃描 [開|關]` — D2 左鍵（Cyberscan）連續使用：範圍自動採礦（同 `scan`）\n"
                "   ↳ ⚠ 掃描與採集流程搶同一條 D2 冷卻，開著可能讓 chill 採集掃不出追蹤框\n"
                "   ↳ 切換後會記住，下次啟動自動套用（刪 `radar_toggle.json` 才退回預設關）\n"
                "`校準 [挖礦|回礦]`：進俯仰校準卡（⬆️⬇️ 調角、🔁 幅度 1/5/10/50、💾 寫回 config；"
                "文字 `上|下 [px]`/`歸位`/`存檔`/`離開` 與反應等價）\n"
                "`list [世界]` — 列出事件 + keep 狀態（預設=偵測到的世界；可指定 `Aesteria`/`Lucernia`）\n"
                "   ↳ 點訊息下的表情 🌍/🌙 可切換世界分頁\n"
                "`keep <礦物名>` — 加入保留（可多個；支援部分名稱如 `hall`）\n"
                "`unkeep <礦物名>` — 取消保留\n"
                "`clear` — 清空保留清單\n"
                "`help` — 顯示此說明")
            self.log_discord.info("CMD help -> sent")

    def _handle_aim_reply(self, content: str):
        """NEEDS_HUMAN＋aim context 存活時，一般訊息當瞄準回覆解析（無前綴，2026-07-11 spec）。

        **此方法在 Discord 輪詢執行緒跑**：只做解析/回覆/寫 self._pending_aim，絕不碰
        input_control——輸入操作全部由主迴圈 _tick_remote_aim 消費（背景執行緒只發布意圖）。
        解析不出→回格式提示不動作；執行中→回「稍候」忽略（不排隊，避免舊指令補刀）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._aim_context
        if ctx is None:      # 競態：elif 檢查過到此期間主迴圈已作廢 context（回 MINING 等）
            notify.send_message(token, ch, "目前沒有待瞄準的採集（已回挖礦/作廢）")
            return
        layers = ("mid", "up", "down") if harvester.plan_pitch_layers(
            cfg.sweep_pitch_enabled, cfg.sweep_pitch_step_px,
            cfg.sweep_pitch_center_back_px) else ("mid",)
        reply = remote_aim.parse_reply(content, len(ctx.candidates), layers,
                                       awaiting_fine=ctx.awaiting_fine)
        if reply is None:
            notify.send_message(
                token, ch, remote_aim.aim_unknown_help(ctx.awaiting_fine))
            return
        if self._aim_busy:
            notify.send_message(token, ch, "⏳ 上一發還在執行，稍候")
            return
        self._pending_aim = reply          # skip/candidate/grid/manual：主迴圈消費
        notify.send_message(token, ch, f"✅ 收到（{reply.kind}），主迴圈執行中…")
        self.log_discord.info("AIM reply=%s -> pending", reply)

    def _queue_reentry_reply(self, raw: str, reply, *, source: str) -> bool:
        """排入主迴圈並立刻回 ACK；Discord poller 絕不執行遊戲輸入。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if self._rr_busy or self._pending_reentry is not None:
            notify.send_message(token, ch, "⏳ 上一則指令還在執行，稍候")
            self.log_discord.info("RR %s ignored（busy/pending, kind=%s）", source, reply.kind)
            return False
        self._pending_reentry = (raw, reply)
        _, detail = notify.send_message(token, ch, reentry_remote.format_pending_ack(reply))
        self.log_discord.info("RR %s reply=%s -> pending; ack=%s", source, reply, detail)
        return True

    def _handle_reentry_reply(self, content: str):
        """REENTRY(remote) 等待時，一般訊息當回礦指令解析（無前綴，2026-07-12 spec）。

        **此方法在 Discord 輪詢執行緒跑**：只做解析/回覆/寫 self._pending_reentry，絕不碰
        input_control、capture、ledger 檔案——輸入與寫檔全由主迴圈 _tick_reentry_remote 消費
        （比照 _handle_aim_reply／_pending_aim）。解析不出→回格式提示不動作；執行中→回「稍候」
        忽略（不排隊，避免舊指令補刀）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        reply = reentry_remote.parse_reply(content)
        if reply is None:
            notify.send_message(token, ch,
                "❓ 看不懂。可用：`3 C2`（方位 1-8+粗格）、`B3`／`B3 <層名>`（細格）、"
                "`放大 <細格>`、`遠 [n]`/`近 [n]`（鏡頭）、`上|下 [px]`/`歸位`（俯仰）、"
                "`掃`、`重骰`、`層 <層名>`、`好`、`作廢`、`跳過`（回挖礦）")
            return
        self._queue_reentry_reply(content, reply, source="text")

    def _web_url(self) -> str:
        """網頁 UI 對外網址（Discord 啟動訊息與 log 共用）。

        用**實際綁上的** host（_web_host）而不是設定值——退回 127.0.0.1 時，
        給玩家一個連不進去的 Tailscale 網址只會浪費他一輪嘗試。
        """
        thread = getattr(self, "_web_thread", None)
        port = getattr(thread, "actual_port", 0) or cfg.web_server_port
        return f"http://{getattr(self, '_web_host', cfg.web_server_host)}:{port}"

    def _format_web_status(self) -> str:
        """啟動 Discord 訊息用的網頁 UI 一行狀態。

        使用者反覆問「網址呢」——先前只有 miningbot.log 印 WebIPC URL，Discord 一個字都
        沒有，網頁到底通不通只能自己猜。三種情況各自講清楚：

        - 起來了 → 給網址（127.0.0.1，跨裝置要自己接 Tailscale serve）
        - 缺件降級 → 明說缺什麼，不然又是一次無聲失效（H061 的教訓）
        - 設定關掉 → 明說是設定
        """
        thread = getattr(self, "_web_thread", None)
        if thread is not None and getattr(thread, "actual_port", 0) > 0:
            url = self._web_url()
            bound = getattr(self, "_web_host", cfg.web_server_host)
            if bound == "127.0.0.1" and cfg.web_server_host != "127.0.0.1":
                return (f"🌐 網頁 UI：{url}　⚠ 綁不到 {cfg.web_server_host}"
                        "（Tailscale 沒起來？）——手機連不進來")
            return f"🌐 網頁 UI：{url}"
        if WEB_IMPORT_ERROR:
            return (f"🌐 網頁 UI：**停用**（缺 fastapi/uvicorn：{WEB_IMPORT_ERROR}）"
                    "——介入流程走 Discord")
        start_error = getattr(self, "_web_start_error", None)
        if start_error:
            return (f"🌐 網頁 UI：**啟動失敗**（{start_error}）"
                    "——挖礦不受影響，介入流程走 Discord")
        if not cfg.web_server_enabled:
            return "🌐 網頁 UI：停用（設定）——介入流程走 Discord"
        return "🌐 網頁 UI：啟動失敗（見 miningbot.log）——介入流程走 Discord"

    def _apply_startup_overrides(self) -> str:
        """P3 玩家設定面板（spec §6）：啟動時讀 config_overrides.json 套用 Config。

        覆蓋順序＝ Config default → .env → config_overrides.json（最高優先）。玩家在
        網頁改的值會在這裡讀回。檔案不存在/損壞時 load_overrides 回 {}（沿用 notify.py
        「失敗只回報不中斷」慣例），bot 用 default 開機。路徑放在 cfg.log_dir 底下
        （與其他 runtime 狀態檔同目錄；不污染 repo）。

        回 overrides_path 給 caller（WebIPCThread 要拿去做 HTTP POST /api/config 的
        持久化目標）；同時記在 self._overrides_path 供 _consume_web_pending 用。

        從 run() 抽出成獨立 method（2026-07-26）：run() 前半段是 focus/UI 檢查/歸位
        等整串實機 I/O，測試無法跑到這裡，這個區塊的整合行為因此從 P3 一路 skip。
        """
        overrides_path = os.path.join(cfg.log_dir, "config_overrides.json")
        self._overrides_path = overrides_path
        applied = web_config_persistence.apply_overrides_to_config(
            cfg, web_config_persistence.load_overrides(overrides_path))
        if applied:
            self.logger.info("config_overrides.json 套用 %d 欄: %s",
                             len(applied), applied)
        return overrides_path

    # ---- 主迴圈 -------------------------------------------------------------
    def run(self):
        # H061：web 模組的 import 已在模組層完成（見檔頭），這裡不再有 deferred import。
        # 舊的「run() 開頭 eager import」緩解（afcab21）其實沒生效——Bot.__init__ 早就
        # spawn 了 audio/snapshot/rapidocr/tesserocr 四個 worker，run() 開頭已經太晚。
        self._running = True
        self.logger.info("bot started (全域熱鍵 Ctrl+Q 只暫停 / Q 暫停↔繼續 / F12 結束 / "
                         "啟動檢查期間 Q=跳過檢查直接開挖, log_level=%s)", cfg.log_level)
        # 熱鍵執行緒提早啟動（spec 2026-07-10 第 1 節）：原本在 init 完成後才啟動，啟動期間
        # Q/Ctrl+Q/F12 全部無效；移到最前面讓環境檢查期間也能中斷。
        # _startup_phase 同步在此開啟：聚焦/量基準要 ~2-3s，跳過鍵（Q）在這段就按下也要記住
        # （太晚設 True 會把早按的 Q 丟掉、使用者以為沒生效）。
        self._startup_phase = True
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
        # 先確認 Roblox 在、聚焦它，完成初始化定位後才開始
        if not self._focus_roblox():
            self._alert("找不到/無法聚焦 Roblox，請先開好遊戲再啟動")
            self._running = False
            self._audio_cap.stop()
            return
        self.last_action = "初始化定位"
        time.sleep(0.4)
        # 記錄「已知正確」的視窗基準供跑位偵測（此時 Roblox 全螢幕且在前景）
        if cfg.window_check_enabled:
            base = window.query_window(cfg.window_title)
            if base.found and base.foreground:
                self._window_baseline = base
                self.logger.info("視窗基準: x=%d y=%d w=%d h=%d（跑位偵測啟用）",
                                 base.x, base.y, base.w, base.h)
            else:
                self.logger.warning("無法取得視窗基準（found=%s fg=%s）— 跑位偵測停用",
                                    base.found, base.foreground)
        # 啟動 UI 前置檢查（spec 2026-07-08-menu-preflight-boost-design.md 第 3 節）：
        # 先關右上角玩家列表（Tab toggle，遮右側點擊視線）→ 再確認聊天框（關著會讓整條 verify
        # OCR 鏈瞎眼）→ Movement Mode（不對會讓 W+左鍵挖礦序列失效）。
        # Q 跳過（spec 2026-07-10 第 2 節；原 F8 與 Roblox 內建功能衝突改 Q）：啟動期間按 Q
        # 設 _skip_env_check，三項檢查各自透過 _env_check_skip 判斷是否略過；init 完成後
        # _startup_phase=False（Q 回歸暫停/繼續語意）。
        # （_startup_phase 已在 run() 開頭設 True——聚焦期間按的 Q 也要收。）
        self.last_action = "環境檢查中…（按 Q 跳過）"
        if self._env_check_skip("玩家列表檢查"):
            pass
        else:
            self._ensure_player_list_closed()
        if self._env_check_skip("聊天框檢查"):
            pass
        else:
            self._ensure_chat_open()
        # Movement Mode 檢查不再於啟動跑（2026-07-11 需求）：回礦/傳送功能未完成 →
        # session 之間沒有東西會動到這個設定 → 啟動時不必跑。備而不用：只有
        # auto_reenter 實際啟用（config 開＋面板模板在）時，才在 session 內第一次
        # RESET_WAIT 結束、回 MINING 時跑一次（_on_enter 控制）。
        if self._auto_reenter_active():
            self.logger.info("Movement Mode 檢查延後到第一次礦坑重置後才跑（auto_reenter 啟用中）")
        else:
            self.logger.info("Movement Mode 檢查停用（備用：auto_reenter 未啟用，設定不會被動到）")
        self._startup_phase = False
        # 挖礦標準角歸位（spec 2026-07-17）：人啟動前留的角度不受控，進第一輪掃描前
        # 歸位；未校準（<=0）維持現狀只警告。不納入 Q 跳過——只要 2~3s，且跳過會讓
        # 「啟動角度不可靠」的動機靜默失效。
        # 鏡頭距離歸位（2026-07-19）：boost FOV 隨使用次數漂移，啟動時人留下的鏡頭
        # 距離不受控——先歸一距離再歸位俯仰（順序固定：zoom 進出第一人稱萬一擾動
        # 俯仰，後跑的俯仰歸位會蓋掉）。
        self.last_action = "鏡頭距離歸位（I 飽和→O 回拉）"
        self._zoom_normalize("啟動")
        self.last_action = "俯仰歸位（挖礦標準角）"
        homed = self._pitch_home_mining("啟動")
        # 啟動仰角顯示（2026-07-18 使用者要求）：log＋Discord 啟動訊息各一行
        self._startup_pitch_status = harvester.format_startup_pitch_status(
            cfg.sweep_pitch_center_back_px, homed, self._pitch_offset_px)
        self.logger.info("啟動仰角：%s", self._startup_pitch_status)
        miner.init_mining_sequence(rotate=self._rotate_verified)
        threading.Thread(target=self._banner_ocr_loop, daemon=True).start()
        threading.Thread(target=self._snapshot_cleanup_once, daemon=True).start()
        if cfg.discord_bot_token and cfg.discord_channel_id:
            threading.Thread(target=self._discord_poll_loop, daemon=True).start()
            self.logger.info("Discord 命令輪詢已啟用（每 %.0fs）", cfg.discord_poll_interval_s)
        overrides_path = self._apply_startup_overrides()
        # WebIPC server（2026-07-26 P1 spec §8）：比照 Discord polling thread 啟動 daemon；
        # 綁 127.0.0.1（Tailscale Serve 出 HTTPS 在外層做，spec §2）。EventLog 註冊
        # WebEventSink 跟 DiscordSink 平行（同一份事件，兩 sink 各自消化，互不影響）。
        # web_pending 在主迴圈 safe point（_tick 開頭 _consume_web_pending）消費；
        # fire_at / reentry_click 由 P4 各狀態處理器（NEEDS_HUMAN／awaiting_fine／
        # reentry 開場鏈）在它們的 tick 內 self._web_pending.pop(routing_key) 自取。
        # ⚠ 整段包 try/except（2026-07-26 實機）：網頁 UI 是**加值功能**，它壞掉絕不該
        # 讓整台 bot 停擺。實機第一次啟用就撞到 uvicorn 在 pythonw 下 dictConfig 失敗
        # （sys.stdout is None），例外一路穿出 run()、bot 執行緒直接死。那個 bug 本身
        # 已修（web_server.py log_config=None），但「web 出事就不能挖礦」這個結構性
        # 風險要一併堵掉——任何失敗都退回 Discord fallback，繼續挖。
        self._web_pending = None
        self._web_fallback = None
        self._web_thread = None
        self._web_start_error: str | None = None
        self._web_host: str = cfg.web_server_host
        if cfg.web_server_enabled:
            try:
                # 這三行只是把名字綁進 local scope——模組本身已在檔頭 import 完（H061），
                # 此處從 sys.modules 取，不會有任何 import 工作發生。
                from .web_server import WebIPCThread
                from .web_ipc import PendingReplies, FallbackState
                from .web_sink import WebEventSink
                self._web_pending = PendingReplies()
                self._web_fallback = FallbackState()
                # bind 位址退回鏈：先試設定的位址（預設＝Tailscale IP），失敗再試
                # 127.0.0.1。Tailscale 沒開機自啟時那個 IP 根本不存在，硬綁會讓整個
                # 網頁 UI 消失；退回本機至少在 bot 機器上還開得起來，而且 log 會說明。
                hosts = [cfg.web_server_host]
                if cfg.web_server_host != "127.0.0.1":
                    hosts.append("127.0.0.1")
                for attempt_host in hosts:
                    self._web_thread = WebIPCThread(
                        pending=self._web_pending,
                        fallback=self._web_fallback,
                        host=attempt_host,
                        port=cfg.web_server_port,
                        config=cfg,  # P3：給 HTTP endpoints 用
                        overrides_path=overrides_path,  # P3：持久化路徑
                        # P5：snapshot_index 與 fixtures 目錄必須顯式轉發——不傳的話
                        # create_app 預設 None，會讓 /api/history、/api/episode、
                        # /api/annotate、/history 四條 route 在 production 全回 503。
                        snapshot_index_path=os.path.join(cfg.log_dir,
                                                         "snapshot_index.jsonl"),
                        fixtures_dir=_AUTO_FIXTURE_ROOT,
                        # 沒有它 /snapshot 回 503 → 標註頁與歷史縮圖全是破圖
                        snapshots_root=os.path.join(cfg.log_dir, "snapshots"),
                        # 目標層與 Discord `層` 指令同步：設定頁顯示執行期有效層
                        # （sticky_layers[world] 優先），而不是 cfg 的 fallback 值。
                        layer_getter=self._effective_layer_info,
                        player_state_getter=self._player_state_snapshot,
                    )
                    self._web_thread.start()
                    if self._web_thread.actual_port > 0:
                        self._web_host = attempt_host
                        break
                    self.logger.warning("WebIPC 綁 %s 失敗", attempt_host)
                    try:
                        self._web_thread.stop()
                    except Exception:
                        pass
                self.log.add_sink(WebEventSink(
                    broadcast_callback=(
                        lambda msg: self._web_thread.app.state.broadcast(msg))
                ))
                # actual_port=0 代表 start() 5s 內 uvicorn 沒 bind 到 socket（已在
                # WebIPCThread.start() 警告並請求 thread 退出）。這裡守第二道防線：
                # 避免印出 http://...:0 讓操作者誤認啟動成功。
                if self._web_thread.actual_port > 0:
                    self.logger.info("WebIPC server 啟動：%s", self._web_url())
                    if self._web_host != cfg.web_server_host:
                        self.logger.warning(
                            "綁不到設定的 %s（Tailscale 沒起來？）——已退回 %s，"
                            "手機連不進來；等 Tailscale 起來後重啟 bot 即可。",
                            cfg.web_server_host, self._web_host)
                else:
                    self.logger.warning(
                        "WebIPC server 啟動失敗／逾期（actual_port=0）"
                        "——thread 已請求退出，broadcast 將 no-op"
                    )
            except Exception as e:
                self.logger.exception(
                    "WebIPC server 啟動失敗（%s）——網頁 UI 停用，挖礦繼續，"
                    "介入流程走 Discord fallback", e)
                # 三個都清成 None：每條 web 路徑都守它們是不是 None，清掉就自動
                # 全面退回 Discord。半死不活的 _web_thread 比沒有更危險。
                try:
                    if self._web_thread is not None:
                        self._web_thread.stop()
                except Exception:
                    pass
                self._web_pending = None
                self._web_fallback = None
                self._web_thread = None
                self._web_start_error = str(e)
        else:
            if WEB_IMPORT_ERROR:
                # 這是**降級**不是設定：使用者以為網頁開著，實際上跑不起來。
                # 講清楚缺什麼、缺在哪個直譯器，否則又變成一次無聲失效。
                self.logger.warning(
                    "網頁 UI 停用——web 模組 import 失敗：%s。"
                    "實機用的直譯器沒裝 fastapi/uvicorn（`uv sync` 只灌 .venv，"
                    "`pythonw -m miningbot` 走的是另一個 Python）。"
                    "所有介入流程自動退回 Discord fallback。", WEB_IMPORT_ERROR)
            else:
                self.logger.info("網頁 UI 停用（cfg.web_server_enabled=False）")
        self.logger.info("初始化完成，開始挖礦")
        # 啟動自檢（preflight）：背景執行緒——它依賴 rapidocr_available()（可能仍在暖機中，
        # 冪等等鎖不搶跑），且 markers/chill_refs/檔案 mtime 這些 I/O 沒必要卡住主迴圈啟動。
        # WARN 診斷寫進 logs/preflight_alerts.md 供後續 agent 巡檢，**不進即時 Discord 通知**
        # （使用者回饋 2026-07-07：降級診斷不該洗掉要即時閱讀的訊息）。啟動 Discord 通知
        # 只保留「已啟動＋保留事件」這種掛機者當下需要看的內容。
        # 雷達連續使用的就緒判定靠 OCR 讀效果列徽章；引擎不可用就退回定時後備。
        # 在這裡探測（非每輪）：tesserocr_available 是冪等有鎖的主動探測，同 preflight 慣例。
        try:
            self._radar_ocr_ok = ocr.tesserocr_available(cfg.tesseract_path)
        except Exception:
            self._radar_ocr_ok = False
        if (self._radar_toggle["scan"] or self._radar_toggle["cave"]):
            self.logger.info("D2 雷達連續使用：%s（OCR 就緒判定=%s）",
                             harvester.format_radar_status(
                                 self._radar_toggle["scan"], self._radar_toggle["cave"],
                                 self._radar_ocr_ok).splitlines()[0],
                             "可用" if self._radar_ocr_ok else "不可用→定時後備")

        def _preflight_and_notify():
            self._run_preflight()
            if cfg.discord_bot_token and cfg.discord_channel_id:
                from . import notify
                kept = game_data.format_keep_by_world(self._keep_ores)
                text = (f"🤖 Bot 已啟動｜仰角：{self._startup_pitch_status}\n"
                        f"{harvester.format_radar_status(self._radar_toggle['scan'], self._radar_toggle['cave'], self._radar_ocr_ok)}\n"
                        f"{self._format_web_status()}\n"
                        f"目前保留事件：\n{kept}")
                notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id, text)
                # 遙控器：啟動訊息貼完後清掉跨重啟殘留的舊遙控器、貼新的到頻道底。
                # 之後每輪 _poll_discord 偵測按鈕點擊、狀態變更原地編輯；被擠上去才重貼。
                self._ensure_remote_control()
                self._ensure_no_stale_calib()
        threading.Thread(target=_preflight_and_notify, daemon=True).start()
        # 啟動耗時不算「無進度」：_last_progress 在 __init__ 設定，啟動 3.5 分鐘曾被算成
        # 「無進度」→ 一進主迴圈就 STUCK 假警報（spec 2026-07-10 第 5 節）。
        self._last_progress = time.time()
        try:
            while self._running:
                if self._pending_calib_start is not None:
                    self._consume_calib_start()
                if self.paused:
                    if self._calib_session is not None:
                        self._tick_calibration()  # 校準動作只在 paused 分支消費（session 活著＝必暫停）
                    # 防掛機踢除：暫停中每 antiafk_interval_s 按一次 Space
                    self._antiafk_tick("暫停")
                    time.sleep(0.05); continue
                loop_started = time.perf_counter()
                tick_started = time.time()
                stage_started = time.perf_counter()
                frame = capture.grab()
                self._latency.observe("capture", time.perf_counter() - stage_started)
                self._latest_frame = frame       # 發佈給背景 banner OCR worker（唯讀共享）
                stage_started = time.perf_counter()
                # P2 Task 7 anchor C：補捉迭代起點 state，_tick 後用邊沿檢測 NEEDS_HUMAN 進入
                # （涵蓋 decide_transition 路徑＋_tick_mining 內部 self.state = NEEDS_HUMAN 路徑）。
                _pre_iter_state = self.state
                obs = self.observe(frame)
                self._latency.observe("observe", time.perf_counter() - stage_started)
                decided = decide_transition(self.state, obs)
                if obs.manual_reentry:
                    if decided is State.REENTRY:
                        self._rr_trigger = "manual"
                        self._evac_done = False   # 手動觸發沒有撤離步驟，footer 不得沿用上輪殘值
                    else:   # 競態：指令到消費之間狀態變了（如 chill 搶轉）→ 明講不動作
                        self._rr_notify(f"ℹ️ 回礦指令已忽略（{self.state.value} 優先轉 {decided.value}）")
                elif decided is State.REENTRY and self.state is not State.REENTRY:
                    self._rr_trigger = "reset"
                if decided != self.state:
                    self.log.log("STATE_CHANGE", from_=self.state.value, to=decided.value)
                    # _on_enter 回傳降級目標（例：MINING 入口重新聚焦失敗 → NEEDS_HUMAN），
                    # None = 接受 decided。commit 邏輯走純函式 resolve_state_transition
                    # （states.py；有測試覆蓋）——避免 inline 代碼再寫錯變數把 chill 觸發
                    # 的 HARVESTING 蓋回 MINING（曾經的修壞點，當時 decide_transition
                    # 正確但這層沒測到）。
                    entered = self._on_enter(decided, frame)
                    new_state = resolve_state_transition(self.state, decided, entered)
                    if entered is not None and entered != decided:   # 真的降級了 → 補一筆 log
                        self.log.log("STATE_CHANGE", from_=decided.value, to=entered.value,
                                     note="downgrade")
                else:
                    new_state = decided
                self.state = new_state
                self._check_spawn_chill(obs, frame)
                stage_started = time.perf_counter()
                self._tick(frame)
                self._latency.observe("tick", time.perf_counter() - stage_started)
                # P2 Task 7 anchor C：用邊沿檢測 NEEDS_HUMAN 進入（prev != NEEDS_HUMAN
                # && curr == NEEDS_HUMAN）發 PING。邊沿檢測可同時涵蓋 decide_transition
                # 路徑與 _tick_mining 內部直接寫 self.state = NEEDS_HUMAN 的路徑（兩種
                # 入口都會在 _tick 結束後被看到）。
                #
                # 2026-07-26：原本這裡還會每 tick 呼叫 _update_status_messenger() 更新
                # 一則獨立狀態訊息。狀態顯示已合併回遙控器卡（spec §7 A），改由 Discord
                # 輪詢執行緒在 (paused, state) 變動時 PATCH，主迴圈不再做 Discord I/O。
                if (_pre_iter_state is not State.NEEDS_HUMAN
                        and self.state is State.NEEDS_HUMAN):
                    try:
                        self._send_needs_human_ping(
                            harvest_id=self._needs_human_extra_meta.get("harvest_id"),
                            reason=self._human_reason,
                        )
                    except Exception as e:
                        self.log_discord.warning("_send_needs_human_ping 例外: %s", e)
                self._heartbeat()
                # 防掛機：NEEDS_HUMAN/RESET_WAIT 也是等待狀態，比照暫停保活（否則需人工
                # 期間閒置過久會被 Roblox 踢出）。恢復挖礦/採集時歸 0，下次等待重新計時。
                # 遠端回礦等待指令（rr_waiting）同理保活——使用者回覆以分鐘計。
                rr_waiting = (self.state is State.REENTRY and self._rr_ctx is not None
                              and not self._rr_busy and self._pending_reentry is None)
                if self.state in (State.NEEDS_HUMAN, State.RESET_WAIT) or rr_waiting:
                    self._antiafk_tick("需人工/重置等待" if not rr_waiting else "回礦等待指令")
                elif self._antiafk_last and not self.paused:
                    self._antiafk_last = 0.0
                self._latency.observe("loop", time.perf_counter() - loop_started)
                self._log_latency_if_due()
                # sleep 補償：tick 本身已花掉的時間（grab ~106ms 起跳）從 50ms 目標
                # 節奏裡扣掉，長 tick 後不再多睡滿 50ms；保留 10ms 下限讓出 GIL
                # 給音訊/熱鍵/OCR worker。
                time.sleep(max(0.01, 0.05 - (time.time() - tick_started)))
        finally:
            self._running = False
            self._audio_cap.stop()
            # P2 Task 7 anchor E：shutdown 不編輯 STOPPED——下次 ensure_posted 會 post 新卡，
            # 舊卡自然成為「上次狀態」留存（不需標示 STOPPED；規格接受此簡化）。
            # 早期版本會 edit 成 STOPPED，但每次重啟會累積舊 STOPPED 卡，故移除。
            ic.key_up("w"); ic.mouse_up()          # 任何結束都放開按鍵
            # WebIPC thread 收掉（比照 daemon thread 慣例：明確 stop + join，讓 socket
            # 關乾淨；不依賴 process exit 才釋放）
            if getattr(self, "_web_thread", None) is not None:
                self._web_thread.stop()
                self._web_thread.join(timeout=2.0)
            if not self._drain_snapshot_queue(cfg.snapshot_shutdown_drain_s):
                self.logger.warning(
                    "snapshot shutdown drain timed out: %d unfinished",
                    self._snap_q.unfinished_tasks)
            self.logger.info("bot stopped")

    def _log_latency_if_due(self):
        """定期輸出有界視窗的主迴圈分位數，供 profiler 前先定位真正熱點。"""
        now = time.monotonic()
        if now - self._last_perf_log < cfg.perf_log_interval_s:
            return
        self._last_perf_log = now
        for name, summary in sorted(self._latency.snapshot(reset=True).items()):
            self.log_hb.info(
                "latency stage=%s n=%d p50=%.1fms p95=%.1fms p99=%.1fms max=%.1fms",
                name, summary.count, summary.p50_ms, summary.p95_ms,
                summary.p99_ms, summary.max_ms)

    def _heartbeat(self):
        """長時間等待時定期記一筆，讓你知道它還在跑、目前音訊分數多少。

        欄位：state／audio／peak／rms 之外，補三個用於對照「W 突然放開／卡住」的訊號
        （2026-07-25 18:40-19:00 場才看出 audio 靜止，但當時缺這三個訊號無法直接歸因）：
        - fg：Roblox 是否前景（N＝失焦→可能凍結遊戲時間）
        - since_boost：距上次 boost 重上的秒數（>90s 通常意味遊戲凍結；boost 自然 ~50s 到期）
        - since_progress：距上次 frame diff 過門檻的秒數（持續高＝STUCK 偵測矇住）
        """
        now = time.time()
        if now - self._last_heartbeat >= cfg.heartbeat_interval_s:
            fg_label = "?"
            try:
                if self._window_baseline is not None:
                    fg_label = "Y" if window.query_window(cfg.window_title).foreground else "N"
            except Exception:
                pass
            self.log_hb.info(
                "heartbeat state=%s fg=%s audio=%.2f peak=%.2f rms=%.6f"
                " since_boost=%.0fs since_progress=%.0fs",
                self.state.value, fg_label, self.listener.latest_score(),
                self._peak_audio_since_hb, self.listener.latest_rms(),
                now - self._last_boost, now - self._last_progress)
            self._peak_audio_since_hb = 0.0
            self._last_heartbeat = now

    def _on_audio_event(self, score, rms, buf):
        """音訊明顯變動（score 升過 audio_event_threshold）時由音訊執行緒回呼：存音訊 + 記一筆。

        目的：chill 沒到觸發門檻（如 0.29 的小聲 chill）也留下證據可診斷，並累積乾淨樣本
        （buffer 在 score 算好的當下擷取，與分數同調，不像 _on_enter 晚 3s 已滾出 chill）。
        檔名帶 score/rms 一眼看出近觸發程度。在背景執行緒跑，存檔 ~5ms、失敗只記 log。
        """
        try:
            crossed = score >= cfg.audio_match_threshold
            ts = time.strftime("%Y%m%d_%H%M%S")
            tag = "TRIG" if crossed else "miss"
            adir = f"{cfg.log_dir}/snapshots/audio"; os.makedirs(adir, exist_ok=True)
            path = f"{adir}/audiochg_{ts}_s{int(round(score*100)):02d}_{tag}.wav"
            audio.save_wav(path, buf, self.listener.sample_rate)
            self.log_hb.info("AUDIO_EVENT score=%.2f rms=%.1f crossed=%s -> %s",
                             score, rms, crossed, path)
        except Exception as e:
            self.log_hb.error("音訊變動記錄失敗: %s", e)

    def _on_audio_chunk(self, chunk):
        """loopback 每 chunk 回呼（音訊執行緒）：餵 chill listener；active 時也餵 reset-chime。"""
        self.listener.feed(chunk)
        rec = self._reset_chime_recorder
        if rec is not None and self._reset_chime_active:
            rec.feed(chunk)

    def _on_reset_chime_saved(self, path, rms):
        """存下一個重置鈴聲候選片段時（音訊執行緒）記一筆到主 log。"""
        self.logger.info("🔔 重置鈴聲候選存檔 rms=%.1f -> %s", rms, path)

    def _reset_chime_diag(self, rms, baseline):
        """armed 期間每 chunk 回呼（音訊執行緒）：節流把 rms/baseline/ratio 寫 heartbeat，供校門檻。"""
        now = time.time()
        if now - self._last_chime_diag < cfg.audio_score_interval_s:
            return
        self._last_chime_diag = now
        ratio = rms / max(baseline, cfg.reset_chime_min_floor)
        self.log_hb.info("RESET_CHIME rms=%.1f base=%.1f ratio=%.2f", rms, baseline, ratio)

    def _save_needs_human_screenshot(self, frame, tag: str = "") -> str | None:
        """NEEDS_HUMAN 時跑 find_tracker 找最佳追蹤框候選，裁出該區域存檔。

        比存全螢幕更能當參考：直接看到「bot 認為最像外框的東西在哪、shape score 多少」。
        無候選時退回存全螢幕。回傳存檔路徑（或 None）。

        tag：採集編號（如 "007"），由採集放棄路徑傳入 → 檔名前綴與該輪其他截圖串連；
        非採集的 NEEDS_HUMAN（如重新聚焦失敗）傳空字串 → 不前綴（避免沿用上一輪殘留編號）。
        """
        import re, cv2
        pre = f"{tag}_" if tag else ""
        _cr = cfg.chat_region
        excl = [(_cr.x, _cr.y, _cr.x + _cr.w, _cr.y + _cr.h)]
        logs = []
        self._find_tracker(frame, excl, reference_bgr=None, log=logs.append)
        # 找最高 edge score 的 shape 候選（OK/soft/hard_rej 都算——rejected 的也要看）
        best = None       # (cx, cy, edge_score)
        for line in logs:
            m = re.search(r"\((\d+),(\d+)\).*edge=([\d.]+)", line)
            if m:
                edge = float(m.group(3))
                if best is None or edge > best[2]:
                    best = (int(m.group(1)), int(m.group(2)), edge)
        # fallback：無 shape 分析（無實機裁圖）時，取第一個 HSV 通過的候選
        if best is None:
            for line in logs:
                m = re.search(r"\((\d+),(\d+)\).*-> OK", line)
                if m:
                    best = (int(m.group(1)), int(m.group(2)), -1.0)
                    break
        if best is None:
            self.logger.info("NEEDS_HUMAN：無追蹤框候選，存全螢幕")
            return self._snapshot(frame, pre + "needs_human")
        cx, cy, edge = best
        r = 120                                        # 裁圖半徑（240×240，含追蹤框+周圍）
        h, w = frame.shape[:2]
        y0, y1 = max(0, cy - r), min(h, cy + r)
        x0, x1 = max(0, cx - r), min(w, cx + r)
        crop = frame[y0:y1, x0:x1].copy()
        label = ("edge=%.2f" % edge) if edge >= 0 else "HSV only"
        cv2.rectangle(crop, (cx - x0 - 35, cy - y0 - 35), (cx - x0 + 35, cy - y0 + 35),
                      (0, 255, 255), 2)
        cv2.putText(crop, label, (5, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
        self.logger.info("NEEDS_HUMAN 裁圖：最佳候選 (%d,%d) %s", cx, cy, label)
        return self._snapshot(crop, pre + "needs_human_%d_%d" % (cx, cy))

    def _save_tracker_screenshot(self, frame, marker, net_rotations) -> str | None:
        """以已知 marker 為中心裁圖、標示追蹤框、寫入旋轉提示——給人工接手看。

        在採集放棄（D3 階段失敗、_target_marker 已設）時呼叫：此時追蹤框仍在畫面上
        （在 restore_view 之前截），比 _save_needs_human_screenshot 重新 find_tracker
        更可靠——restore 後追蹤框可能已被轉出畫面，find_tracker 找不到會退回全螢幕。

        旋轉語意：net_rotations 為採集期間的淨轉動（., 各 45°；正=右轉 .、負=左轅 ,）。
        restore_view 會反向轉回；截圖是「轉回前面對追蹤框」的視角，附上 rotation 提示
        讓人工知道「從目前的回正視角，按 . 或 , 幾次可以面對此追蹤框」。
        """
        import cv2
        cx, cy = marker
        r = 180                                       # 裁圖半徑（比 needs_human 大，含更多上下文）
        h, w = frame.shape[:2]
        y0, y1 = max(0, cy - r), min(h, cy + r)
        x0, x1 = max(0, cx - r), min(w, cx + r)
        crop = frame[y0:y1, x0:x1].copy()
        cv2.rectangle(crop, (cx - x0 - 35, cy - y0 - 35), (cx - x0 + 35, cy - y0 + 35),
                      (0, 255, 255), 2)
        abs_rot = abs(net_rotations)
        if abs_rot == 0:
            rot_txt = "facing original view"
        else:
            key = "." if net_rotations > 0 else ","
            rot_txt = f"face: {key} x{abs_rot} (~{abs_rot*45}deg)"
        cv2.putText(crop, f"tracker ({cx},{cy})  {rot_txt}",
                    (5, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        self.logger.info("[%s] NEEDS_HUMAN tracker 截圖: (%d,%d) net_rot=%d %s",
                         self.harvest.harvest_id, cx, cy, net_rotations, rot_txt)
        return self._hsnap(crop, "needs_human_tracker_%d_%d" % (cx, cy))


    def _log_w_state(self, label):
        """診斷：記錄 W 鍵 + 左鍵 + 前景視窗（採集後 W 不按住 root cause 追蹤）。"""
        u = ctypes.windll.user32
        w = bool(u.GetAsyncKeyState(0x57) & 0x8000)       # virtual key W
        lmb = bool(u.GetAsyncKeyState(0x01) & 0x8000)      # left mouse button
        fg = u.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(fg, buf, 256)
        self.logger.info("[W診斷 %s] W=%s LMB=%s fg=%r", label, w, lmb, buf.value)

    # ---- D4 保留清單持久化 -------------------------------------------------
    def _keep_ores_path(self) -> str:
        import os
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "keep_ores.json")

    def _load_keep_ores(self) -> set:
        """啟動時從 keep_ores.json 載入 D4 保留清單（跨 session 持久化）。"""
        import json
        try:
            with open(self._keep_ores_path(), "r", encoding="utf-8") as f:
                ores = set(json.load(f))
            if ores:
                self.logger.info("keep_ores 載入：%s", sorted(ores))
            return ores
        except (FileNotFoundError, json.JSONDecodeError):
            return set()

    def _save_keep_ores(self):
        """將 D4 保留清單存到 keep_ores.json（Discord !keep/!unkeep/!clear 後呼叫）。"""
        import json
        try:
            with open(self._keep_ores_path(), "w", encoding="utf-8") as f:
                json.dump(sorted(self._keep_ores), f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error("keep_ores 存檔失敗: %s", e)

    # ---- D2 雷達連續使用開關持久化（2026-07-26 使用者要求） ------------------
    # 對稱於 keep_ores：Discord 改了 → 即時 save → 下次啟動 load。否則重啟退回 cfg 預設 False，
    # 使用者以為還開著卻沒在用。
    def _radar_toggle_path(self) -> str:
        import os
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "radar_toggle.json")

    def _load_radar_toggle(self) -> dict:
        """啟動時從 radar_toggle.json 載入 D2 連續使用開關（跨 session 持久化）。

        檔案不存在／損壞／缺欄位／非 bool → 退回 cfg 預設值（不拋例外，首輪與容錯路徑
        同 keep_ores）。只信任 {scan, cave} 兩個 key，其他忽略；非 bool 值（手編失誤）
        也退回預設——避免型別混淆讓後續 if 寫成 truthy 判定走歪。
        """
        import json
        defaults = {"scan": cfg.radar_scan_repeat_enabled,
                    "cave": cfg.radar_cave_skim_enabled}
        try:
            with open(self._radar_toggle_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return defaults
        loaded = dict(defaults)
        for k, default_v in defaults.items():
            v = data.get(k) if isinstance(data, dict) else None
            if isinstance(v, bool):
                loaded[k] = v
        if loaded != defaults:
            self.logger.info(
                "雷達連續使用開關載入：scan=%s cave=%s（cfg 預設 scan=%s cave=%s）",
                loaded["scan"], loaded["cave"],
                defaults["scan"], defaults["cave"])
        return loaded

    def _save_radar_toggle(self):
        """將 D2 連續使用開關存到 radar_toggle.json（Discord 切換後呼叫）。"""
        import json
        try:
            with open(self._radar_toggle_path(), "w", encoding="utf-8") as f:
                json.dump(self._radar_toggle, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error("雷達連續使用開關存檔失敗: %s", e)

    def _harvest_seq_path(self) -> str:
        """harvest_seq.json 路徑（與 keep_ores.json 同目錄：專案根）。"""
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "harvest_seq.json")

    def _load_harvest_seq(self) -> int:
        """啟動時載入上次最後用的採集編號（跨 session 不重複）。

        檔案不存在/損壞/非正整數 → 回 0（首輪 001）。比照 _load_keep_ores 容錯。
        修 2026-06-30：原 _harvest_seq 每次啟動歸 0，重啟後 001 重複，無法用編號
        一鍵搜出「該輪」證據（橫跨多次執行的截圖/log/Discord 會撞號）。
        """
        import json
        try:
            with open(self._harvest_seq_path(), "r", encoding="utf-8") as f:
                v = json.load(f)
            if isinstance(v, int) and v >= 0:
                if v > 0:
                    self.logger.info("harvest_seq 載入：上次到 %s，下次 %s",
                                     harvester.format_harvest_id(v),
                                     harvester.format_harvest_id(v + 1))
                return v
            self.logger.warning("harvest_seq.json 非正整數 (%r)，從 %s 重新起算",
                                v, harvester.format_harvest_id(1))
            return 0
        except (FileNotFoundError, json.JSONDecodeError):
            return 0

    def _save_harvest_seq(self):
        """把目前採集編號存到 harvest_seq.json（每次進 HARVESTING +1 後呼叫）。"""
        import json
        try:
            with open(self._harvest_seq_path(), "w", encoding="utf-8") as f:
                json.dump(self._harvest_seq, f)
        except Exception as e:
            self.logger.error("harvest_seq 存檔失敗: %s", e)

    def _on_enter(self, s, frame) -> State | None:
        """進入狀態 s 的副作用（screenshot / log / 按鍵）。

        回傳 None = 接受 s（外層正常提交）；回傳其他 State = 降級（外層改用回傳值）。
        降級用於「MINING 入口重新聚焦 Roblox 失敗」——避免 init_mining_sequence 的
        按鍵送到錯誤視窗，改交人工處理。
        """
        if s is State.MINING:
            # 從 NEEDS_HUMAN/RESET_WAIT/HARVESTING 回 MINING：等待期間焦點幾乎必失
            # （使用者點過別的視窗、或 HUD 從隱藏重顯時搶焦）。後續 init_mining_sequence
            # 會送 W / D1 / Shift / ., 視角鍵，必須先確認焦點在 Roblox，否則全被 GUI
            # 視窗（HUD/terminal/其他）吃掉——「偶爾挖到稀有礦回正不會動」的根因。
            # 聚焦失敗 → 跑 NEEDS_HUMAN 副作用 + 回傳降級信號（不寫 self.state）。
            if not self._focus_roblox():
                self.logger.warning("進入 MINING 但無法聚焦 Roblox -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法重新聚焦 Roblox，請確認遊戲視窗後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)  # screenshot + log + alert 副作用
                return State.NEEDS_HUMAN                  # 信號外層降級（不直接寫 self.state）
            self.human_cleared = False
            self._aim_context = None          # remote-aim context 作廢（回挖礦＝不再待瞄準）
            self._rr_ctx = None               # remote reentry episode 已收尾（_rr_success 已 finalize，保險清掃）
            self._pending_reentry = None
            # 清重置快取：OCR 已背景化，RESET_WAIT 期間快取凍在 True（worker 只在
            # MINING 跑）——不清的話回 MINING 第一個 tick 就讀到過期 True 又彈回
            # RESET_WAIT。worker ~2s 內會重驗，banner 真的還在會再次偵測到。
            self._mine_resetting = False
            # 同步清 Capacity 快取＋streak＋飽和 LOG 旗標：重置後殘留會誤導下一輪監看。
            self._capacity_pct = None
            self._capacity_streak = 0
            self._capacity_full_logged = False
            # Movement Mode 前置檢查（2026-07-11 需求）：只在 session 內第一次重置後跑一次。
            # 掛在「恢復挖礦」而非 RESET_WAIT 進場——重置等待期間人可能正在手動操作遊戲
            # （重新定位），選單鏈的 Esc/點擊會跟人搶輸入；人按 Q 表示定位完成、此時跑鏈
            # 安全，跑完才 init_mining_sequence。不傳 skip_event（Q 已用於「定位完成」語意）。
            if self._movement_check_due:
                self._movement_check_due = False
                self._movement_mode_checked = True
                ok = self._set_movement_mode(cfg.movement_mode_mining)
                if not ok:
                    self.logger.warning("Movement Mode 切換失敗，可能影響操作，請手動確認後繼續")
            # 鏡頭距離歸位（2026-07-19）：從 NEEDS_HUMAN/RESET_WAIT/REENTRY 回來，
            # 等待期間人可能滾輪動過鏡頭、且 boost FOV 隨次數漂移——每輪開挖前歸一。
            self._zoom_normalize("MINING 入口")
            miner.init_mining_sequence(rotate=self._rotate_verified)  # 從其他狀態回來，重新握住 W + 左鍵
        if s is State.HARVESTING:
            # 本輪採集配一個編號（001…），貫穿 log/快照檔名/Discord，供事後一鍵搜查誤判。
            # 先建 HarvestState 帶上編號，後續 _hsnap/_hsnap_crop 才能讀到本輪 id。
            self._harvest_seq += 1
            self._save_harvest_seq()              # 持久化：重啟後從這號繼續，不重複
            hid = harvester.format_harvest_id(self._harvest_seq)
            self.harvest = harvester.HarvestState(0, 0.0, harvest_id=hid)
            self.harvest.pitch_layers_left = harvester.plan_pitch_layers(
                cfg.sweep_pitch_enabled, cfg.sweep_pitch_step_px,
                cfg.sweep_pitch_center_back_px)
            # remote-aim：新一輪採集 episode 重置 context＋sweep 記錄（跨層/跨 RESWEEP 累積）
            self._aim_context = None
            self._sweep_shots = []
            self._target_observations = []
            self._target_recovery_attempts = 0
            chill_path = self._hsnap_crop(frame, cfg.chill_text_region, "chill_closeup")
            self._hsnap(frame, "rare_found")
            # 錄下 chill 音訊樣本（供分析/重錄參考 wav 用）；檔名帶編號與截圖對齊
            try:
                adir = f"{cfg.log_dir}/snapshots/audio"; os.makedirs(adir, exist_ok=True)
                audio_path = f"{adir}/{hid}_chill_audio_{time.strftime('%Y%m%d_%H%M%S')}.wav"
                self.listener.save_buffer_wav(audio_path)
                self.logger.info("chill 音訊已存: %s", audio_path)
            except Exception as e:
                self.logger.error("chill 音訊存檔失敗: %s", e)
            self.log.log("RARE_FOUND", harvest_id=hid, image_path=chill_path)
            self.logger.info("進入採集 HARVESTING [%s]: D2 掃描，全方位搜尋追蹤框", hid)
            harvester.prepare_scan()            # 停止移動、置中鏡頭（裝備位置穩定）
            # ★ boost 守門（H026）：reference 必須在「最終 FOV」下拍——若進場時 D5 已到期
            #   卻不補，之後守門補上時 FOV 展開，ref 與實況錯位、preexist 差分全失準。
            # 等 D2 冷卻放在拍 ref 之前：等待期間場景會變（其他玩家/光照），
            # 先拍 ref 再等 ~30s 會讓排除基準過期、反而製造假陽性。
            self._await_scan_ready("enter")
            gf = capture.grab()
            if self._harvest_boost_guard(gf):
                gf = capture.grab()             # 剛補 D5、FOV 已展開 → 必須重抓
            self._pre_scan_ref = gf             # 置中後截 reference（排除裝備假陽性）
            # giveup 前後對比圖的「前」基準只在這裡取一次（H020：_reharvest_sweep 會
            # 重拍 _pre_scan_ref——若 D3 其實已採到才 RESWEEP，重拍的已是「採完後」畫面
            # → 送人工的 before/after 兩張一模一樣、對比失去鑑別力）
            self._harvest_origin_ref = self._pre_scan_ref
            self._run_scan()            # 裝備 D2 + 點擊觸發掃描
            self._confirm_scan("enter")
            self._harvest_start = time.time()
            self._target_marker = None          # 尚未掃描，第一個 tick 將做全方位掃描
            # ★ 聊天基準提升到 episode 級（2026-07-04 H032 延伸對策）：進場拍一次、
            #   全程不作廢（RESWEEP 重取會把晚到的成功行吃進新基準 → 差分從此看不見
            #   → 白掃誤交人工）。開火前不可能有自己的 D3 成功行 → 進場基準天生乾淨；
            #   OCR 仍延到開火後才跑（H026 對策不變）。
            self._chat_baseline = None          # 開火後才 OCR（跨本 episode 全部 D3 嘗試共用）
            self._chat_baseline_crop = capture.crop(gf, cfg.chat_region)
            self._chat_last_crop = self._chat_baseline_crop
            self._chat_ledger = None            # episode 帳本（ocr.ChatLedger）：基準 OCR 完成時建立
        if s is State.REENTRY:
            # 入口聚焦失敗 → 降級 NEEDS_HUMAN（兩種模式共用）：REENTRY 全程都在
            # 送鍵/點擊，焦點不在 Roblox 上會全部送錯視窗、白白燒光 reroll 次數。
            if not self._focus_roblox():
                self.logger.warning("進入 REENTRY 但無法聚焦 Roblox -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法聚焦 Roblox（自動回礦前），請確認遊戲視窗後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)
                return State.NEEDS_HUMAN
            now = time.time()
            self._reentry_done = False
            self._reentry_failed = False
            self._reentry_ref = None
            self._reentry_panel_xy = None
            self._move_diffs = []
            self._last_nav_frame = None
            ic.key_up("w"); ic.mouse_up()            # RESET_WAIT 本已放開，保險再放一次
            if self._remote_reenter_active():
                # remote 模式（2026-07-12 spec）：開場鏈（按回到地表→傳送等待→俯仰歸位→
                # 八方位拍照→Discord 發送）由 _tick_reentry_remote → _rr_open_episode 在主迴圈
                # 同步跑（`走` 走位指令 2026-07-18 退役，Movement Mode 不再切換）。
                # 此處只建 ReentryState 佔位（共用路徑防禦性讀）＋清快取。
                self._reentry = reentry.ReentryState(phase_started=now, attempt_started=now)
                self._rr_ctx = None
                self._pending_reentry = None
                self._rr_busy = False
                self._rr_embed_mid = None        # episode embed 清乾淨（上輪 finalize 已刪訊息，保險清）
                self._rr_reactions_seen = {}
                self._rr_last_min = -1
                self.last_action = "重置完成，遠端回礦中（等待 Discord 指令）"
                self.log.log("REENTRY_START")
                self.logger.info("REENTRY(remote)：等主迴圈開場鏈")
                return
            # auto 模式（既有邏輯）：click-to-move 導航依賴 Movement Mode=Click to Move；
            # 切不過去導航無意義，reroll 也救不了 → 直接降級 NEEDS_HUMAN（比照聚焦失敗）。
            if not self._set_movement_mode(cfg.movement_mode_reentry):
                self.logger.warning("進入 REENTRY 但無法切換 Movement Mode -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法切換至 Click to Move（自動回礦前），請手動確認設定後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)
                return State.NEEDS_HUMAN
            self._reentry = reentry.ReentryState(phase_started=now, attempt_started=now)
            ic.click_at(*cfg.reentry_surface_button_xy)   # 按「回到地表」
            self.last_action = "重置完成，自動回礦中"
            self.log.log("REENTRY_START")
            self.logger.info("REENTRY：已按回到地表，開始自動回礦（上限 %d 輪）",
                             cfg.reentry_max_attempts)
        if s is State.NEEDS_HUMAN:
            # extra 先取出：採集放棄會帶 harvest_id（+ image_paths 前後兩張 / rotation_hint）；
            # 非採集 NEEDS_HUMAN（重新聚焦失敗等）extra 為空 → tag="" 不前綴。
            extra = self._needs_human_extra_meta
            self._needs_human_extra_meta = {}
            image_groups = extra.pop("image_groups", None)
            image_paths = extra.pop("image_paths", None)
            if image_groups:
                # 採集放棄（無框）：左側前後對比裁圖分組 → Discord 先聊天框、再背包，兩則分開發送
                self.log.log("NEEDS_HUMAN", reason=self._human_reason,
                             image_groups=image_groups, **extra)
            elif image_paths:
                # 採集放棄（有框，face_tracker）：單張追蹤框圖供人工手動採
                self.log.log("NEEDS_HUMAN", reason=self._human_reason,
                             image_paths=image_paths, **extra)
            else:
                # 非採集 / 採集沒走到 D3：單張截圖（原行為）
                if self._needs_human_extra_image is not None:
                    path = self._needs_human_extra_image
                    self._needs_human_extra_image = None
                else:
                    path = self._save_needs_human_screenshot(frame, tag=extra.get("harvest_id", ""))
                self.log.log("NEEDS_HUMAN", reason=self._human_reason, image_path=path, **extra)
            ic.key_up("w"); ic.mouse_up()
            self._alert("需要人工：" + self._human_reason)
            self.human_cleared = False
        if s is State.RESET_WAIT:
            self.log.log("MINE_RESET")
            self._snapshot(frame, "mine_reset")
            ic.key_up("w"); ic.mouse_up()            # 停止挖礦
            self.last_action = "礦坑重置，等待重新定位"
            self._alert("礦坑重置，請重新定位後按 Q 繼續")
            self.human_cleared = False
            self._aim_context = None          # remote-aim context 作廢（礦坑重置＝局勢已變）
            self._rr_ctx = None               # remote reentry context 作廢（_rr_abort_reset 已 finalize，保險清掃）
            self._pending_reentry = None
            self._reset_wait_since = time.time()
            self._chime_armed_at = 0.0               # H045：新一輪重置，容量錨重新觀測
            # Movement Mode 前置檢查延後到此：session 內第一次重置才標 due，
            # 等 _on_enter(MINING) 恢復挖礦時消費（2026-07-11 需求）。
            # 再閘一層 _auto_reenter_active（同日追加需求）：Movement Mode 只為回礦
            # click-to-move 服務，自動回礦（R 取樣校準＋auto_reenter）完成前「備而不用」
            # ——挖礦本身的設定不會被動到，跑選單鏈只是浪費 71-82s 還多一次搶輸入風險。
            if not self._movement_mode_checked and self._auto_reenter_active():
                self._movement_check_due = True
            # H043 對策「進場即撤離」改由 cfg.reentry_evac_on_banner 控制，H045 起預設關：
            # 撤離＝重置那一刻人在地表，遊戲不記錄坑內位置（記錄前提是重置當下人在礦坑內），
            # 臨時挖到的稀有礦回不去原位。留坑內的代價（墜虛空/重生凍結）由 H044 探測式
            # 開場吸收（點擊當探針、預算 300s 收口）。開回 True 即恢復 H043 行為。
            self._evac_done = False
            if (cfg.reentry_evac_on_banner and self._remote_reenter_active()
                    and not self.paused):
                if self._focus_roblox():
                    time.sleep(cfg.reentry_evac_settle_s)   # focus 後沉澱再點（輸入被吃家族教訓）
                    if self._click_surface_verified("重置撤離"):
                        self._evac_done = True
                        self.last_action = "重置撤離：已傳送至地表"
                        self.logger.info("重置撤離：已傳送至地表（REENTRY 開場會再按一次換重生點）")
                    else:
                        self.logger.warning("重置撤離：點擊全部失敗（可能已在虛空或按鈕無反應）")
                        snap = capture.grab()
                        path = self._rr_sync_write(snap, "evac_fail_reset_wait")
                        self._rr_notify("⚠ 重置撤離失敗：按「回到地表」畫面無變化"
                                        "（全黑＝已在虛空）。重置完成後 REENTRY 會再試一次",
                                        image_paths=[path])
                else:
                    self.logger.warning("重置撤離：無法聚焦 Roblox，放棄撤離（不擋 RESET_WAIT）")

    def _consume_pending_rotate(self):
        """主迴圈消費 Discord `轉` 指令（H059）。輪詢執行緒只寫旗標，送鍵一律在此。

        接收時已擋過狀態，但接收到消費之間仍可能變（chill 觸發 HARVESTING 等）——
        此時**丟棄不排隊**：使用者是看著畫面手動校正，隔幾分鐘才轉一格會讓他以為
        自己按錯，比不轉更糟。用 `_rotate_verified` 而非裸送鍵，被吃時才有得回報。
        """
        if not self._pending_rotate:
            return
        direction, self._pending_rotate = self._pending_rotate, 0
        if not can_consume_rotate(self.state):
            self.log_discord.info("轉 已丟棄：接收後狀態變為 %s（不排隊）", self.state.value)
            return
        side = "右" if direction > 0 else "左"
        if self._rotate_verified(direction):
            self.last_action = f"遠端{side}轉 45°"
            self.log_discord.info("轉 已執行：%s 45°（state=%s）", side, self.state.value)
        else:
            self.last_action = f"遠端{side}轉未生效"
            self.logger.warning("遠端 %s轉 45° 重試用盡未生效——視角未變，可再送一次", side)

    def _consume_web_pending(self):
        """主迴圈 safe point 消費 web_pending（WebSocket client 送的命令）。

        P1 Task 10 只鋪框架（spec §8「Bot 端整合」）：
        - 控制類（pause / resume / request_frame）：在這裡 pop；當前 P1 不接業務
          邏輯——_handle_web_control 與 self.paused 切換是 P4「即時介入面板」工作。
          只記 log 確認命令有進到主迴圈。
        - fire_at / reentry_click：**不在這裡消費**。各狀態處理器（NEEDS_HUMAN /
          awaiting_fine / reentry 開場鏈）在 P4 整合時會用 self._web_pending.pop(
          self._current_routing_key()) 自取；P1 留著不動。
        - 過期 reply：每輪 pop_any_expired 清一次，避免 TTL 60s 過期的舊 reply
          無限累積佔 slot（spec §8 race 規則：先到先贏，後到丟棄）。
        """
        if self._web_pending is None:
            return  # cfg.web_server_enabled=False
        # 網頁「跳過」按鈕（spec §4 回礦流程第 6 點）。走既有 reentry 指令路徑：
        # reentry_remote.parse_reply("跳過") → kind="skip" → _queue_reentry_reply，
        # 跟玩家在 Discord 打「跳過」完全同一條，主迴圈消費邏輯零改動。
        # 先前玩家在網頁點失敗後只能切回 Discord 打字，等於白做一半。
        if self._web_pending.pop("control:skip") is not None:
            reply = reentry_remote.parse_reply("跳過")
            if reply is not None and self._pending_reentry is None:
                self._queue_reentry_reply("跳過", reply, source="web")
                self.logger.info("web: 跳過（排入 reentry pending）")
            else:
                self.logger.info("web: 跳過被忽略（上一則指令還在執行或非回礦中）")
        # 網頁「好」／「作廢」按鈕（2026-07-28）：awaiting_confirm 階段（Depth 已確認
        # 下礦但 cfg.reentry_remote_auto_resume=False，安全預設一律等人工放行）原本
        # 只能回 Discord 打字——玩家人在網頁面板上，這步驟卻要切回 Discord，體驗上
        # 等於白做。同樣走既有 reentry 指令路徑，跟 `跳過` 那段一樣的接法。
        for cmd, raw in (("confirm", "好"), ("void", "作廢")):
            if self._web_pending.pop(f"control:{cmd}") is not None:
                reply = reentry_remote.parse_reply(raw)
                if reply is not None and self._pending_reentry is None:
                    self._queue_reentry_reply(raw, reply, source="web")
                    self.logger.info("web: %s（排入 reentry pending）", raw)
                else:
                    self.logger.info("web: %s 被忽略（上一則指令還在執行或非回礦中）", raw)
        # 網頁設定頁改目標層（2026-07-26）：走跟 Discord `層` 指令同一條路徑
        # （_apply_layer_change），才會真的寫進每世界黏性層 map。HTTP route 那邊
        # 只 push 不執行——寫檔與發 Discord 都必須在主迴圈執行緒做。
        reply = self._web_pending.pop("control:set_layer")
        if reply is not None:
            layer = reply.get("layer")
            if isinstance(layer, str) and layer.strip():
                self._apply_layer_change(layer.strip(), source="web")
                self.logger.info("web: 目標層改為 %s（已同步每世界黏性層）", layer.strip())
            else:
                self.logger.warning("web: set_layer 值不合法，忽略: %r", layer)
        # 2026-07-28：遙控器五顆鍵（▶️⏸️⚡📷🏠）網頁對應版——pause/resume/request_frame
        # 從 P1 就留著沒接（"P1 未接業務邏輯"），玩家在網頁完全無法暫停/繼續/看畫面。
        # 這裡直接照抄 _poll_remote_reactions 對應分支的邏輯（同樣是背景執行緒觸發，
        # 只是輪詢執行緒→主迴圈的差別；_pause/_resume 本身就已被 Discord 輪詢執行緒
        # 直接呼叫，同一顆函式讓網頁呼叫沒有新增風險）。
        if self._web_pending.pop("control:pause") is not None:
            self._pause()
            self.log_discord.info("web ⏸ pause")
        if self._web_pending.pop("control:resume") is not None:
            was_blocked = is_blocked_from_mining(self.state, self.paused)
            self.human_cleared = True
            self._rr_skip_on_pause_resume("web resume")
            if self.paused:
                self._resume()
            self.log_discord.info("web ▶️ resume（was_blocked=%s）", was_blocked)
        if self._web_pending.pop("control:ability") is not None:
            self._pending_ability = True
            self.log_discord.info("web ⚡ ability（queued state=%s）", self.state.value)
        if self._web_pending.pop("control:reenter") is not None:
            ok_re, reason = can_accept_manual_reentry(self.state, self._reentry_active())
            if not ok_re:
                self._broadcast_status_note(f"❌ 回礦未接受：{reason}")
            else:
                self._manual_reentry = True
                if self.paused:
                    self.paused = False
                    self._antiafk_last = 0.0
                self._broadcast_status_note("⛏ 手動回礦已排入 → 下個 tick 進 REENTRY")
            self.log_discord.info("web 🏠 reenter -> accepted=%s state=%s",
                                  ok_re, self.state.value)
        if self._web_pending.pop("control:request_frame") is not None:
            self._broadcast_frame_snapshot()
            self.log_discord.info("web 📷 request_frame")
        if self._web_pending.pop("control:request_status") is not None:
            # 新連線上來看不到歷史——常駐狀態只在 (paused, state) 變化時才廣播，
            # 剛連上的 client 得自己要一次，不然要等下次狀態變化才看得到東西。
            self._broadcast_status()
        # D2 連續使用開關（掃描/削洞，2026-07-28）：跟 Discord `掃描`/`削洞` 指令
        # 同一份持久化（radar_toggle.json）——照抄該指令的「開啟時清上次觸發時刻」
        # 邏輯，否則網頁剛開啟要等到舊冷卻時刻才會生效。
        reply = self._web_pending.pop("control:radar_toggle")
        if reply is not None:
            which = reply.get("which")
            value = reply.get("value")
            if which in ("scan", "cave") and isinstance(value, bool):
                self._radar_toggle[which] = value
                self._save_radar_toggle()
                if value:
                    self._radar_last[which] = 0.0
                self.logger.info("web: %s toggle -> %s", which, value)
                self._broadcast_status()   # 玩家馬上要看到切換生效
            else:
                self.logger.warning("web: radar_toggle 值不合法，忽略: %r", reply)
        # P3 玩家設定面板（spec §6）：WebSocket 命令 config_set 走 web_pending 異步處理
        # （HTTP POST /api/config 是同步路徑，由 web_server FastAPI route 直接處理；
        # 兩條路徑都呼叫同一個 setattr + save_overrides——重複是有意的，保持 web_server
        # 與 main.py 解耦，web_server 不需 bot 實例）。loop 處理多筆累積的 config_set。
        reply = self._web_pending.pop("control:config_set")
        while reply is not None:
            field = reply.get("field")
            value = reply.get("value")
            if field is not None and value is not None:
                if is_web_configurable(field) and validate_value(field, value):
                    setattr(cfg, field, value)
                    # 持久化失敗只回報不中斷 main loop（runtime 已生效，重啟會還原）
                    try:
                        web_config_persistence.save_overrides(
                            self._overrides_path, field, value)
                    except OSError as e:
                        if self.logger:
                            self.logger.warning(
                                "web config_set 持久化失敗（runtime 已生效，重啟會還原）: %s",
                                e)
                    self.logger.info("web config_set: %s=%r", field, value)
                else:
                    self.logger.warning(
                        "web config_set 拒絕（白名單或 validate 不過）: %s=%r",
                        field, value)
            reply = self._web_pending.pop("control:config_set")
        # 2026-07-27：harvest 採集放棄候選清單的 web 點擊——沒有專屬狀態處理器像
        # manual_survey/reentry 那樣自己 blocking 等，NEEDS_HUMAN 就是一般 tick 在跑，
        # 所以在這裡（safe point）順手取。awaiting_fine 期間跳過：那段還沒接 web，
        # ctx.candidates 是舊清單，取了也只會誤配對。
        ctx = getattr(self, "_aim_context", None)
        if (ctx is not None and self.state is State.NEEDS_HUMAN
                and not ctx.awaiting_fine):
            reply = self._web_pending.pop(f"harvest:{ctx.harvest_id}")
            if reply is not None:
                self._handle_web_aim_click(reply)
        # fire_at / reentry_click reply 留著等 P4 各狀態處理器自取（不在此清）
        expired = self._web_pending.pop_any_expired()
        if expired:
            self.logger.info("web: 清掉過期 reply %d 筆", len(expired))

    def _handle_web_aim_click(self, reply: dict) -> None:
        """網頁點候選疊圖（採集放棄候選清單，2026-07-28）→ 排進 `_pending_aim`，
        走跟 Discord 回編號完全同一條主迴圈尾段（`_tick_remote_aim` 的
        `kind == "point"` 分支 → `_execute_remote_fire`）。

        不在這裡直接開火：候選清單疊圖是掃描當下那一幀（`_render_aim_shots`
        的不變量），玩家可能過了好幾分鐘才點——這期間 D2 掃描效果／D5 boost FOV
        大機率已過期，盲點舊座標等於朝錯的畫面開槍。`_execute_remote_fire` 才有
        完整的「D5 守門→重按 D2→在新畫面重找目標」序列，跟 Discord 候選/格子
        兩條路徑共用，不能繞過。

        `reply` 是 `fire_at` payload：x/y 必有；dir（候選圖對應的方位，1-8 制）／
        layer（該圖俯仰層）缺了就退回當下姿態。**不比對候選標號**——疊圖上的編號
        只是 AI 自己猜的弱信號參考，玩家點哪就打哪才是「手動覆蓋自動偵測」該有的
        行為；早版做「點擊要落在候選 ±80px 內才算數」，玩家點在候選清單裡明明看
        得到但分數太低沒被 AI 選中的位置就會被忽略，等於白給了一個功能。

        `_aim_busy`／已有 `_pending_aim` 排隊中就丟棄本次（先到先贏，同 Discord
        поller 慣例）——不要讓 web 點擊覆蓋掉正在跑或排隊中的另一則回覆。
        """
        ctx = self._aim_context
        if ctx is None or self._aim_busy or self._pending_aim is not None:
            return
        x, y = int(reply.get("x", 0)), int(reply.get("y", 0))
        dir_field = reply.get("dir")
        dir_idx = (int(dir_field) - 1) % 8 if isinstance(dir_field, int) \
            else ctx.pose_net_rotations % 8
        layer = reply.get("layer")
        if not isinstance(layer, str) or not layer:
            layer = ctx.pose_pitch_layer
        self._pending_aim = remote_aim.AimReply(
            "point", dir_idx=dir_idx, layer=layer, pos=(x, y))
        self.log_discord.info(
            "[%s] web AIM 點擊 (%d,%d) -> pending（dir=%d layer=%s）",
            ctx.harvest_id, x, y, dir_idx, layer)

    # --- P4 Task 3：web_pending reply pop 整合（harvest manual_survey 進入點） ---

    def _encode_png(self, frame):
        """frame → PNG bytes；失敗回 None（只記 log，不炸主流程）。"""
        import cv2
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            self.log_discord.warning(
                "web intervention: PNG encode 失敗（frame shape=%r）",
                getattr(frame, "shape", None))
            return None
        return buf.tobytes()

    # --- 2026-07-28：遙控器/狀態網頁鏡射（廣播 helper，全部沒 web thread 就 no-op）---

    def _status_snapshot(self) -> dict:
        """跟 Discord `status` 指令讀同一批欄位——兩邊顯示的資料來源是同一份，
        不是各自組字串各自維護，天然不會有「網頁跟 Discord 顯示不一致」的問題。
        """
        try:
            audio_score = self.listener.latest_score()
        except Exception:
            audio_score = 0.0
        return {
            "state": self.state.value,
            "paused": self.paused,
            "last_action": self.last_action,
            "uptime_s": int(time.time() - self._started),
            "audio_score": audio_score,
            "stats": dict(self.stats),
            "radar": dict(getattr(self, "_radar_toggle", {})),
        }

    def _broadcast_status(self) -> None:
        """推 STATUS 事件給 web client——遙控器 embed 原地 PATCH 的網頁版。"""
        web_thread = getattr(self, "_web_thread", None)
        if web_thread is None:
            return
        from .web_protocol import WebMessage
        registry = web_thread.app.state.registry
        payload = {"event": "STATUS"}
        payload.update(self._status_snapshot())
        registry.broadcast(WebMessage(type="event", payload=payload))

    def _broadcast_status_note(self, text: str) -> None:
        """一次性文字提示（🏠 手動回礦接受/拒絕等）——不是常駐狀態，是單則訊息。"""
        web_thread = getattr(self, "_web_thread", None)
        if web_thread is None:
            return
        from .web_protocol import WebMessage
        registry = web_thread.app.state.registry
        registry.broadcast(WebMessage(
            type="event", payload={"event": "STATUS_NOTE", "text": text}))

    def _broadcast_frame_snapshot(self) -> None:
        """📷 遙控器反應的網頁版：抓當下畫面推給 web client，不落地存檔
        （對比 Discord 📷 用 sampler.save_sample 存編號樣本——那是校準素材用途，
        這裡純粹「讓玩家看一眼現在畫面」，不需要留檔）。
        """
        web_thread = getattr(self, "_web_thread", None)
        if web_thread is None:
            return
        frame = capture.grab()
        png = self._encode_png(frame)
        if png is None:
            return
        from .web_protocol import WebMessage
        registry = web_thread.app.state.registry
        registry.broadcast(WebMessage(type="event", payload={"event": "FRAME_SNAPSHOT"}))
        registry.broadcast_binary(png)

    def _send_web_intervention_frames(self, flow: str, routing_key: str,
                                      frames, ctx_summary: str,
                                      note: str = "") -> bool:
        """推**多張**幀 + INTERVENTION_NEEDED 給 web client（2026-07-26）。

        `frames`＝``[(dir_idx, png_bytes)]``，或 ``[(dir_idx, layer, png_bytes)]``
        （2026-07-27 harvest 候選清單多帶俯仰層——玩家點候選圖時 client 要把 layer
        一併回報，bot 才知道除了轉方位還要不要調俯仰）。每張圖前面先送一則
        INTERVENTION_FRAME meta（帶 index／dir／layer），client 據此把緊接著的
        binary 放進對應格子——WebSocket 同一條連線保證順序，所以「meta 後面那張
        就是它的圖」成立。全部送完才送 INTERVENTION_NEEDED，client 收到時所有張都已到齊。

        為什麼要多張：回礦開場站在地表，傳送板九成不在當下視野內。舊版只推一幀，
        玩家看著一張沒有目標的圖無從點起，只能等 120s 逾時（07-26 18:32 實錄）。

        回 True＝已推送；False＝沒有 web thread／一張都沒編碼成功。
        """
        if self._web_thread is None or not frames:
            return False
        registry = self._web_thread.app.state.registry
        # 2026-07-27：使用者是「有提醒才連進來」——開始記錄這輪序列，晚到的連線
        # 一上來就能靠 registry.replay_to 補到完整這批圖，而不是看到空白 idle。
        registry.begin_intervention_replay()
        from .web_protocol import WebMessage
        total = len(frames)
        for seq, item in enumerate(frames):
            if len(item) == 3:
                dir_idx, layer, png = item
            else:
                dir_idx, png = item
                layer = None
            meta = {"event": "INTERVENTION_FRAME", "flow": flow,
                    "routing_key": routing_key, "index": seq,
                    "total": total, "dir": int(dir_idx) + 1}
            if layer:
                meta["layer"] = layer
            registry.broadcast(WebMessage(type="event", payload=meta))
            registry.broadcast_binary(png)
        registry.broadcast(WebMessage(
            type="event",
            payload={"event": "INTERVENTION_NEEDED", "flow": flow,
                     "routing_key": routing_key, "summary": ctx_summary,
                     "mode": "sweep", "frame_count": total, "note": note},
        ))
        return True

    def _send_web_intervention_event(self, flow: str, routing_key: str,
                                     frame, ctx_summary: str) -> None:
        """推截圖 + INTERVENTION_NEEDED context 給 web client（透過 ConnectionRegistry）。

        P4 Task 3：manual_survey 進入點原本要發 Discord 八方位圖給玩家選方向+格；
        web 在線時改推一份當下截圖＋ context 給 web，玩家 pinch-zoom + tap 直接選點
        （滑掉整條 Discord 八方位→格→連鎖放大間接表達鏈，spec §4）。

        沒 web thread／registry 尚未注入 loop → no-op，呼叫端 fallback 到 Discord 流程。
        編碼失敗只回報不丟——網頁介入是加值路徑，失敗不能炸主流程。
        """
        if self._web_thread is None:
            return
        import cv2
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            self.log_discord.warning(
                "web intervention: PNG encode 失敗（frame shape=%r）",
                getattr(frame, "shape", None))
            return
        registry = self._web_thread.app.state.registry
        registry.begin_intervention_replay()
        registry.broadcast_binary(buf.tobytes())
        from .web_protocol import WebMessage
        registry.broadcast(WebMessage(
            type="event",
            payload={"event": "INTERVENTION_NEEDED", "flow": flow,
                     "routing_key": routing_key, "summary": ctx_summary},
        ))

    def _await_web_pointer_reply(self, routing_key: str,
                                 timeout_s: float) -> dict | None:
        """輪詢 web_pending 取玩家點擊 reply；timeout 回 None。

        與 Discord 反應按鈕輪詢平行——同一 routing key 兩條路徑都會推 reply，
        PendingReplies.push 同 key 第二筆拒絕（spec §8 first-wins）。500ms 輪詢間隔
        比照 _poll_discord 頻率，不過密卡 CPU、不過鬆讓玩家感覺 lag。
        """
        if self._web_pending is None:
            return None
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            reply = self._web_pending.pop(routing_key)
            if reply is not None:
                return reply
            time.sleep(0.5)
        return None

    # 網頁回礦面板上「不是點畫面」的那幾顆按鈕 → 既有回礦指令 kind。
    # 主迴圈此刻卡在 _reentry_await_player_click 裡，`_consume_web_pending`
    # 跑不到，所以這些 control key 必須由等待迴圈自己撿。
    _RR_WEB_CONTROLS = {"skip": "跳過", "reroll": "重骰", "sweep": "掃"}

    def _await_web_reentry_action(self, routing_key: str, timeout_s: float):
        """等玩家在回礦面板上做一件事；回 ``(kind, payload)``。

        kind："click"（payload＝reply dict）／"skip"／"reroll"／"sweep"／
        "force_discord"（玩家按了提醒訊息上的 🔀，不想再等 web）／
        None（逾時，payload 也是 None）。

        同時輪詢點擊 reply 與控制鍵，因為主迴圈整個卡在這裡——控制鍵若只靠
        `_consume_web_pending`，玩家按了「重骰」要等這輪逾時（最長 5 分鐘）才生效。
        """
        if self._web_pending is None:
            return None, None
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            reply = self._web_pending.pop(routing_key)
            if reply is not None:
                return "click", reply
            for cmd in self._RR_WEB_CONTROLS:
                if self._web_pending.pop(f"control:{cmd}") is not None:
                    return cmd, None
            if self._web_pending.pop(f"control:force_discord:{routing_key}") is not None:
                return "force_discord", None
            if self._mine_resetting:
                # 等待期間礦坑又重置：八方位圖已過時，別讓玩家對著舊圖點
                return None, None
            time.sleep(0.5)
        return None, None

    def _save_auto_fixture(
        self,
        flow: str,
        episode_id: str,
        frame,
        cell_crop,
        annotation_xy,
        verify_ok: bool,
        tier: str | None = None,
        variant: str | None = None,
        mineral: str | None = None,
    ) -> None:
        """P5 Task 5：玩家 web 介入 verify 結果自動收集素材（spec §5）。

        玩家在網頁介入是「真值材料的副產品」——verify 通過 = 高信心真框（symptom=null，
        當對照組）；verify 失敗 = 玩家可事後在 §5 標註工具分類（symptom="unknown"）。

        檔案位置（spec §5 素材庫結構）：
        - harvest:  tests/fixtures/aim/auto_<hid>_<result>.{png,json}（PNG = cell_crop）
        - reentry:  tests/fixtures/reentry/teleport_board/auto_<ep>_<result>.{png,json}
                    （PNG = frame 全幀；傳送板定位只需全幀座標，無 cell 概念）

        result = "success" if verify_ok else "fail"；symptom 同步：None / "unknown"。

        CJK path safety（CLAUDE.md memory）：PNG 經 cv2.imencode + numpy.tofile；
        JSON 經 tempfile + os.replace 原子寫（避免 Discord / web client 讀到半成品）。

        Best-effort：所有 I/O 失敗只記 log warning，不 raise——素材收集是加值路徑，
        不能炸主流程（spec §0、global constraints）。
        """
        import cv2
        from datetime import datetime
        from .web_annotation import build_annotation

        try:
            if flow == "harvest":
                if cell_crop is None:
                    self.logger.warning(
                        "_save_auto_fixture: harvest flow 收到 cell_crop=None，skip"
                        "（episode=%s）", episode_id)
                    return
                subdir = os.path.join(_AUTO_FIXTURE_ROOT, "aim")
                image_to_save = cell_crop
            elif flow == "reentry":
                if frame is None:
                    self.logger.warning(
                        "_save_auto_fixture: reentry flow 收到 frame=None，skip"
                        "（episode=%s）", episode_id)
                    return
                subdir = os.path.join(
                    _AUTO_FIXTURE_ROOT, "reentry", "teleport_board")
                image_to_save = frame
            else:
                self.logger.warning(
                    "_save_auto_fixture: 未知 flow=%r，skip", flow)
                return

            os.makedirs(subdir, exist_ok=True)
            result = "success" if verify_ok else "fail"
            base_name = f"auto_{episode_id}_{result}"
            png_path = os.path.join(subdir, base_name + ".png")
            json_path = os.path.join(subdir, base_name + ".json")

            # PNG via imencode + tofile（CJK path safety）
            ok, buf = cv2.imencode(".png", image_to_save)
            if not ok:
                self.logger.warning(
                    "_save_auto_fixture: cv2.imencode 失敗（shape=%r），skip",
                    getattr(image_to_save, "shape", None))
                return
            buf.tofile(png_path)

            # JSON via atomic write（tmpfile + os.replace）
            annotation = {
                "type": "square",
                "cx": int(annotation_xy[0]),
                "cy": int(annotation_xy[1]),
                "size": _AUTO_FIXTURE_DEFAULT_SIZE,
            }
            episode_result = "success" if verify_ok else "fail"
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            if flow == "harvest":
                verify_str = "passed" if verify_ok else "failed"
                source = {
                    "kind": "auto",
                    "harvest_id": str(episode_id),
                    "episode_result": episode_result,
                    "verify": verify_str,
                    "timestamp": timestamp,
                }
            else:  # reentry：verify 欄位語意 — descended（成功）/ 其他 verdict（失敗）
                verify_str = "descended" if verify_ok else "failed"
                source = {
                    "kind": "auto",
                    "episode_id": str(episode_id),
                    "episode_result": episode_result,
                    "verify": verify_str,
                    "timestamp": timestamp,
                }
            symptom = None if verify_ok else "unknown"
            ann = build_annotation(
                image=base_name + ".png",
                annotation=annotation,
                tier=tier,
                variant=variant,
                mineral=mineral,
                source=source,
                symptom=symptom,
                related_incident=None,
            )
            tmp_path = json_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(ann, f, indent=2, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_path, json_path)
            self.logger.info(
                "AUTO FIXTURE[%s] episode=%s result=%s -> %s + %s",
                flow, episode_id, result, png_path, json_path)
        except Exception as e:
            # best-effort：素材收集失敗不炸主流程
            self.logger.warning(
                "_save_auto_fixture(%s, %s) 失敗： %s", flow, episode_id, e)

    def _execute_remote_fire_from_web(self, ctx, x: int, y: int):
        """從 web 點擊 reply 直接走 fire+verify（跳過 Discord 八方位＋偵測）。

        P4 Task 3 minimum viable：玩家在介入面板 pinch-zoom + tap 點位置 → server 還原
        原生 (x, y) → 直接走 _aim_fire_and_verify 開火驗證（沿用 _execute_aim_fine_fire
        的尾段：chat_base_crop + _aim_fire_and_verify），不轉方位、不動俯仰、不偵測。
        玩家看的就是當下畫面、點的就是當下框位置——方位/俯仰/偵測對齊整段省略。

        只給 manual survey 用（單幀、剛重掃過，畫面新鮮，跳偵測安全）：候選清單
        多圖點擊（2026-07-28）改走 `_handle_web_aim_click` -> `_pending_aim`
        （kind="point"）-> `_tick_remote_aim` -> `_execute_remote_fire`，因為候選
        清單可能是好幾分鐘前掃的（玩家還沒看手機），D2 掃描效果/D5 boost FOV
        早就過期了，這裡的「不偵測」假設不成立——那條路要 D2/D5 都重新檢查、且用
        `_refind_tracker_near` 重找位置，不能盲點舊座標。

        回 (ok, detail)：confirmed=True 的成功路徑已在 _aim_fire_and_verify 內呼叫
        _remote_fire_success（俯仰歸位＋視角回正＋回挖礦）。

        2026-07-26 補完：四條出口（礦坑重置中／D3 冷卻未就緒／聚焦失敗／verify 結果）
        都會推 INTERVENTION_RESULT 回 web client。原本只有第一條有，網頁端點完沒下文
        ——spec 驗收 A 明列「verify 結果回傳網頁顯示（✅ 或 ❌）」。

        待補（實機驗收）：
        - 確認 _aim_busy／_aim_context 清理由 caller 負責（與 _execute_aim_fine_fire 慣例一致）。

        P4 Task 5 接線：玩家 reply 處理完成（不論 verify 是否通過）後呼叫
        _resolve_ping_if_any 結案 PING 訊息——玩家已介入、結案信號比 verify 結果優先。

        P5 Task 3（P4 final-review Important: frame-grab race）：reply pop 後立刻
        sanity-check `_mine_resetting`——60-120s 等 reply 期間 礦坑可能已開始重置，
        target tracker 已經 despawn；這時用過時 snapshot 的座標開火只會浪費 D3 + 留
        誤判證據。reject 並推 INTERVENTION_RESULT 告知 web client。完整 re-verify
        target visibility（FOV 漂移／tracker 是否仍在）留實機驗收後再評估。
        """
        hid = ctx.harvest_id
        # P5 Task 3：reply race sanity-check——必須在 _wait_for_d3_cooldown／focus 前，
        # 礦坑重置中不該消耗 D3 冷卻等待，也不該搶焦點。
        if getattr(self, "_mine_resetting", False):
            self.logger.info(
                "[%s] web fire reply 在 礦坑重置中，reject（避免對過時 snapshot 開火）",
                hid)
            self._broadcast_intervention_result(
                ctx, verdict="rejected_reset",
                summary=" 礦坑重置中，請 `重骰`／`跳過`", flow="harvest")
            self._resolve_ping_if_any(
                f"harvest:{hid}", "web", "web fire 失敗：礦坑重置中（reply race）")
            return False, "礦坑重置中"
        deadline = time.time() + cfg.remote_aim_budget_s
        ready, detail = self._wait_for_d3_cooldown(deadline)
        if not ready:
            self.log_discord.warning("[%s] web fire: D3 冷卻未就緒： %s", hid, detail)
            self._broadcast_intervention_result(
                ctx, verdict="fire_aborted",
                summary=f"D3 冷卻未就緒（{detail}），請稍後再點一次", flow="harvest")
            self._resolve_ping_if_any(
                f"harvest:{hid}", "web", f"web fire 失敗：D3 冷卻未就緒 ({detail})")
            return False, detail
        if not self._focus_roblox():
            self._broadcast_intervention_result(
                ctx, verdict="fire_aborted",
                summary="無法聚焦 Roblox，請確認遊戲視窗還開著", flow="harvest")
            self._resolve_ping_if_any(
                f"harvest:{hid}", "web", "web fire 失敗：無法聚焦 Roblox")
            return False, "無法聚焦 Roblox"
        pre_fire_frame = capture.grab()
        chat_base_crop = capture.crop(pre_fire_frame, cfg.chat_region)
        # 用當下姿態記錄觀測（_aim_fire_and_verify 內 _record_target_observation 用）
        tgt_dir = ctx.pose_net_rotations % 8
        tgt_layer = ctx.pose_pitch_layer
        self.logger.info("[%s] AIM web fire -> (%d, %d) dir=%d layer=%s",
                         hid, x, y, tgt_dir, tgt_layer)
        ok, verify_detail = self._aim_fire_and_verify(
            (int(x), int(y)), -1.0, tgt_layer, tgt_dir, ctx, hid, deadline,
            chat_base_crop)
        # P5 Task 5：自動收集素材（spec §5）——玩家介入 verify 結果 = 真值材料。
        # cell crop 以玩家 tap 為中心、沿用 coarse_cell 大小（320x270；與
        # reentry_remote.coarse_cell_region 同格尺寸；existing fixtures 270x320 對齊）。
        # annotation_xy = tap 在 cell_crop local 座標（crop 經 clamp 後 tap 可能不在正中心）。
        try:
            if pre_fire_frame is not None:
                # 裁切幾何抽到 web_annotation.cell_crop_box 共用：網頁手動標註
                # （POST /api/annotate）也要產出同形狀的裁圖，兩邊各寫一份的話
                # 同一個 fixtures 目錄會混進尺寸不一的素材。
                from .web_annotation import cell_crop_box
                cx0, cy0, cx1, cy1 = cell_crop_box(
                    cfg.screen_w, cfg.screen_h, int(x), int(y))
                cell_crop = pre_fire_frame[cy0:cy1, cx0:cx1]
                self._save_auto_fixture(
                    flow="harvest", episode_id=str(hid),
                    frame=pre_fire_frame, cell_crop=cell_crop,
                    annotation_xy=(int(x) - cx0, int(y) - cy0),
                    verify_ok=bool(ok))
        except Exception as e:
            self.logger.warning("[%s] 自動收集素材失敗： %s", hid, e)
        # 開火結果回報 web client（spec 驗收 A「verify 結果回傳網頁顯示（✅ 或 ❌）」）。
        # 原本這條路徑只 _resolve_ping_if_any 編輯 Discord PING，網頁端點完就沒下文——
        # 玩家在手機上看不出到底打中沒有，只能切回 Discord 看。
        self._broadcast_intervention_result(
            ctx,
            verdict="fire_ok" if ok else "fire_failed",
            summary=(f"✅ 已採集（點擊 {x},{y}）" if ok
                     else f"❌ 未確認採集（點擊 {x},{y}）：{verify_detail}"),
            flow="harvest")
        # 玩家 reply 已處理（不管 verify 結果）→ 結案 PING 訊息
        self._resolve_ping_if_any(
            f"harvest:{hid}", "web",
            f"玩家點擊 ({x},{y}) verify={'通過' if ok else '失敗'}")
        return ok, verify_detail

    def _summarize_survey_ctx(self, ctx) -> str:
        """給 web client 介入面板顯示的 context 摘要（純文字）。

        與 Discord 八方位圖標頭同義：harvest 編號 ＋ 當下絕對方位 ＋ 俯仰層。
        缺欄位就少顯示該欄，不丟例外（網頁面板壞資料不能炸主流程）。
        """
        parts = []
        if hasattr(ctx, "harvest_id"):
            parts.append(f"harvest={ctx.harvest_id}")
        if hasattr(ctx, "pose_net_rotations"):
            parts.append(f"dir={ctx.pose_net_rotations % 8}")
        if hasattr(ctx, "pose_pitch_layer"):
            parts.append(f"layer={ctx.pose_pitch_layer}")
        return " ".join(parts) or "manual_survey"

    def _tick(self, frame):
        self._update_reset_chime_active()
        self._consume_pending_rotate()
        self._consume_web_pending()  # web client 命令（P1 Task 10）
        # Discord `ability` 指令消費：可消費狀態才按 X（HARVESTING/REENTRY 插按鍵會
        # 干擾時序，旗標留著等回 MINING 再執行）。狀態閘走純函式 can_consume_ability。
        if self._pending_ability and can_consume_ability(self.state):
            self._pending_ability = False
            ic.key_press("x")
            self.last_action = "遠端能力：已按 X"
            self.log_discord.info("ability 已執行（state=%s）", self.state.value)
        if self.state is State.MINING:
            self._tick_mining(frame)
        elif self.state is State.HARVESTING:
            self._tick_harvest(frame)
        elif self.state is State.REENTRY:
            self._tick_reentry(frame)
        elif self.state is State.NEEDS_HUMAN and self._pending_aim is not None:
            # B3：遠端瞄準回覆由主迴圈消費（輪詢執行緒只寫 _pending_aim，輸入全在此跑）
            reply, self._pending_aim = self._pending_aim, None
            self._tick_remote_aim(frame, reply)
        # RESET_WAIT / 其餘 NEEDS_HUMAN: 等待熱鍵，不動作（chill 仍由 observe 監聽）

    # --- P2 Task 7：PingResolveMessenger 整合 helper ---
    # （狀態顯示已於 2026-07-26 合併回遙控器卡，_update_status_messenger 隨之移除；
    #   見 _build_remote_embed / _build_remote_metrics_line 與 _poll_discord 1b。）

    def _send_needs_human_ping(self, harvest_id: str | None, reason: str):
        """NEEDS_HUMAN 進入時呼叫：透過 PingResolveMessenger 推播 <@USER_ID> PING 訊息。

        回傳 message_id（失敗 None）。harvest_id 有值時同步寫入 _pending_ping_mid，
        供玩家 reply 完成時的 _resolve_ping_if_any 對照同則訊息編輯 ✅。
        fallback 由 _web_fallback 決定（網頁介入失敗退回 Discord 反應按鈕）。
        """
        if getattr(self, "_ping_messenger", None) is None:
            return None
        # _web_fallback 由 P1 web client 介入路徑設置（P4 接線）；本 task 階段
        # 屬性可能尚未存在 → 用 getattr 防 AttributeError，缺屬性視為 fallback=True
        # （網頁介入未啟用 → 一律走 Discord 反應按鈕）。
        web_state = getattr(self, "_web_fallback", None)
        fallback = (web_state is None
                    or web_state.is_fallback(
                        now=time.monotonic(), grace_s=cfg.web_fallback_grace_s))
        try:
            mid = self._ping_messenger.send_ping(
                harvest_id=harvest_id, reason=reason, fallback=fallback,
                now=time.monotonic(),
            )
        except Exception as e:
            self.log_discord.warning("PingResolveMessenger.send_ping 例外: %s", e)
            return None
        if mid and harvest_id:
            self._pending_ping_mid[f"harvest:{harvest_id}"] = mid
        return mid

    def _notify_web_intervention_pending(self, ctx, frame_count: int) -> None:
        """網頁開始等玩家點時，在 Discord 發一則帶網址的提醒（2026-07-26）。

        為什麼需要：網頁介入唯一的通知管道就是「玩家剛好開著面板」。實機 07-26
        18:32 白等 120s 逾時，網頁明明連著——人只是沒在看。Discord 有推播，
        提醒放這裡才叫得動人。

        訊息在本輪介入結束時由 `_resolve_web_intervention_ping` 刪掉，
        不留一串「等你點」的殭屍訊息。發送失敗只記 log（提醒是加值，不能擋回礦）。
        """
        from . import notify
        url = f"{self._web_url()}/intervention"
        text = (f"🌐 **網頁在等你點**：回礦 #{ctx.episode_id}"
                f"（attempt {ctx.attempt}）已拍好 {frame_count} 個方位\n"
                f"{url}\n"
                f"左右切方位 → 直接點傳送板；也可在面板上 ⟳ 重掃／🎲 重骰／⏭️ 跳過。"
                f"不理它會在 {int(cfg.web_intervention_budget_s / 60)} 分鐘後改用 Discord 八方位；"
                f"想現在就用 Discord 就按下面的 {_WEB_ESCALATE_EMOJI}。")
        try:
            ok, _detail, mid = notify.send_message_with_id(
                cfg.discord_bot_token, cfg.discord_channel_id, text)
        except Exception as e:
            self.log_discord.warning("web 介入提醒發送例外：%s", e)
            return
        self._web_intervention_mid = mid if ok else None
        if ok and mid:
            self._arm_web_escalate_reaction(f"reentry:{ctx.episode_id}", mid)

    def _arm_web_escalate_reaction(self, routing_key: str, mid: str) -> None:
        """在等待網頁介入的提醒訊息上加 🔀，讓玩家不必等滿 budget 就能手動切 Discord。

        2026-07-27 使用者要求：網頁等待期間 Discord 完全插不上手，玩家想現在
        就用 Discord 也只能乾等逾時。基線用 add_reaction 的結果建立（成功視為
        1，同遙控器既有慣例），避免額外一次 GET，也避免把機器人自己的反應誤判
        成玩家點擊。加反應失敗只記 log——這是加值路徑，不能擋主流程。
        """
        from . import notify
        added, detail = notify.add_reaction(
            cfg.discord_bot_token, cfg.discord_channel_id, mid, _WEB_ESCALATE_EMOJI)
        if not added:
            self.log_discord.warning("web escalate 反應加不上去（%s）：%s", routing_key, detail)
            return
        if getattr(self, "_web_escalate", None) is None:
            self._web_escalate = {}
        self._web_escalate[routing_key] = (mid, 1)

    def _poll_web_escalate_reactions(self) -> None:
        """輪詢所有等待中的 🔀 反應；有人多按一次就排 force_discord 給等待迴圈撿。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        for routing_key, (mid, baseline) in list(self._web_escalate.items()):
            reactions = notify.get_reactions(token, ch, mid, _WEB_ESCALATE_EMOJI)
            if len(reactions) > baseline:
                del self._web_escalate[routing_key]
                if self._web_pending is not None:
                    self._web_pending.push(f"control:force_discord:{routing_key}", True)
                self.log_discord.info(
                    "web escalate：%s 按了 %s，改用 Discord", routing_key, _WEB_ESCALATE_EMOJI)

    def _resolve_web_intervention_ping(self, ctx) -> None:
        """本輪 web 介入結束（成功／逾時／退回 Discord）→ 收掉那則提醒訊息。"""
        from . import notify
        getattr(self, "_web_escalate", {}).pop(f"reentry:{ctx.episode_id}", None)
        mid = getattr(self, "_web_intervention_mid", None)
        if not mid:
            return
        self._web_intervention_mid = None
        try:
            ok, detail = notify.delete_message(
                cfg.discord_bot_token, cfg.discord_channel_id, mid)
            self.log_discord.info("web 介入提醒收回 mid=%s -> %s", mid, detail)
        except Exception as e:
            self.log_discord.warning("web 介入提醒收回例外：%s", e)

    def _resolve_ping_if_any(self, routing_key: str, reply_source: str, detail: str = ""):
        """玩家 reply 完成時呼叫：把對應的 PING 訊息編輯成 ✅ 結案。

        routing_key 例如 "harvest:007"；對 _pending_ping_mid 找出 PING message_id，
        然後呼叫 PingResolveMessenger.resolve 編輯同一則。沒對應的 PING 則 no-op。

        P2 Task 7 只放 framework；具體 caller（fire_at / reentry_click 後）接線留 P4。
        """
        if getattr(self, "_ping_messenger", None) is None:
            return
        mid = self._pending_ping_mid.pop(routing_key, None)
        if not mid:
            return
        harvest_id = (routing_key.split(":", 1)[1]
                      if ":" in routing_key else None)
        try:
            self._ping_messenger.resolve(mid, harvest_id, reply_source, detail)
        except Exception as e:
            self.log_discord.warning("PingResolveMessenger.resolve 例外: %s", e)

    def _update_reset_chime_active(self):
        """依 state＋計時決定 reset-chime recorder 是否收音；窗外（含回 MINING）清空重錄。

        先把旗標設 False 再 reset() recorder，避免音訊執行緒在 reset 當下還餵 chunk
        （競態最壞＝邊界丟一個 chunk，對校準無害）。"""
        rec = self._reset_chime_recorder
        if rec is None:
            return
        # H045：容量錨開窗（_maybe_arm_chime 觀測到容量歸零才起算）、窗跨
        # RESET_WAIT/REENTRY（舊版離開 RESET_WAIT 即停錄＝實際窗僅 1~3s，鈴聲
        # 永遠在窗外）；上限 reset_chime_capture_max_s 收口。純決策在 audio。
        active = (self.state in (State.RESET_WAIT, State.REENTRY)
                  and audio.capture_window_active(
                      self._chime_armed_at, time.time(),
                      cfg.reset_chime_capture_max_s))
        if active and not self._reset_chime_active:
            self._reset_chime_active = True
            self.logger.info("🔔 重置鈴聲擷取啟動（容量錨，窗 %.0fs）",
                             cfg.reset_chime_capture_max_s)
        elif not active and self._reset_chime_active:
            self._reset_chime_active = False
            rec.reset()

    def _maybe_arm_chime(self, cap_pct):
        """H045 容量錨：重置流程中觀測到容量歸零→開鈴聲錄音窗（一輪只開一次）。

        兩個讀值來源共用：RESET_WAIT 的 banner worker、REENTRY 開場閘的容量 OCR。
        只在 RESET_WAIT/REENTRY 內生效——MINING 的容量讀值（例如剛開機容量本來
        就低）不該開窗。
        """
        if self._chime_armed_at != 0.0:
            return
        if self.state not in (State.RESET_WAIT, State.REENTRY):
            return
        if audio.chime_capacity_armed(cap_pct, cfg.reset_chime_capacity_arm_pct):
            self._chime_armed_at = time.time()
            self.logger.info("🔔 容量已歸零（%.0f%% ≤ %.0f%%）→ 鈴聲錄音窗開啟 %.0fs",
                             cap_pct, cfg.reset_chime_capacity_arm_pct,
                             cfg.reset_chime_capture_max_s)

    def _check_boost_stall(self, now: float):
        """MINING 中 boost 連續 > boost_stall_warn_s 沒重上 → 警告一次。

        不同於 STUCK 偵測（靠 frame diff，frame 還在動就 pass）：boost 自然 ~50s 到期，
        如果連續 >90s 沒重上又沒暫停，**最可能是遊戲時間凍結**——Roblox 視窗失焦時
        部分遊戲會暫停 server-side tick，UI 圖示還在但世界不動、W 在 Windows 按著
        但遊戲收不到。實機 2026-07-25 18:40-19:00 即此症狀（heartbeat audio 靜止 20 分）。

        警報帶 fg／boost_present／audio_peak 三個訊號協助對焦點／偵測／音訊三軸歸因。
        """
        if self.paused or self.state is not State.MINING:
            self._boost_stall_notified = False
            return
        elapsed = now - self._last_boost
        if elapsed > cfg.boost_stall_warn_s:
            if not self._boost_stall_notified:
                self.logger.warning(
                    "[boost-stall] MINING 已 %.0fs 未重上 boost（boost_present=%s "
                    "audio_peak=%.2f）——可能遊戲凍結／焦點丟失／偵測誤判",
                    elapsed, self._boost_present, self._peak_audio_since_hb)
                self._boost_stall_notified = True
        elif elapsed < cfg.boost_cooldown_s:
            # 恢復了（boost 又被重上）→ 解鎖，允許下次再警報
            self._boost_stall_notified = False

    def _tick_mining(self, frame):
        if getattr(self, '_post_harvest_watch', 0) > 0:
            self._log_w_state("MINING post-harvest tick")
            self._post_harvest_watch -= 1
        self._check_boost_stall(time.time())        # boost 久沒到期＝遊戲可能凍結
        flags = miner.EventFlags(
            boost_expired=self._boost_needs_refresh(frame),
            activity_event=self._activity_ready(frame),   # D4：冷卻好就右鍵刷新事件
            scan_event=self._radar_ready(frame, "scan"),  # D2 左鍵：連續使用（持久化 toggle，預設關）
            cave_event=self._radar_ready(frame, "cave"),  # D2 Z：連續使用（削洞穴方塊）
            window_unfocused=self._window_displaced(),    # item ④：視窗跑位（失焦/移動/縮放）
        )
        action = miner.dispatch_event(flags)
        if action == "REFOCUS":
            reason = self._window_displaced_reason
            self.logger.info("mining: 視窗跑位(%s) -> 重新聚焦+初始化", reason)
            self.last_action = f"視窗跑位({reason})"
            if reason == "window_missing" or not self._focus_roblox():
                # 視窗消失/抓不回焦點 → 交人工，避免空轉狂搶焦點
                self._human_reason = "Roblox 視窗消失或無法聚焦，請處理後按 Q"
                self.state = State.NEEDS_HUMAN
                self._on_enter(State.NEEDS_HUMAN, frame)
                return
            miner.init_mining_sequence(rotate=self._rotate_verified)
            # 重聚焦後給它時間穩定，先別馬上再判定，避免連續搶焦點
            self._window_bad = False
            self._last_window_check = time.time()
        elif action == "USE_D5":
            self.log_act.info("mining: boost 消失 -> 重上 D5")
            self.last_action = "boost 重上(D5)"
            self.stats["boosts"] += 1
            # FOV 前後幀對（2026-07-19）：到期收縮中的 frame 當 before，補瓶展開後
            # 再抓 after——依螢幕計數節流（~每 N 次一組），到期才 settle 等展開。
            screen = self._boost_screen_count(frame)
            pair_due = harvester.plan_boost_pair_due(
                screen, self._bc_last_pair_screen, cfg.boost_fov_pair_every_n)
            miner.use_boost()
            self._last_boost = time.time()           # 設冷卻，避免瓶子出現前重複按
            self._boost_press_pending = True         # 瓶子重現確認才算一次使用
            if pair_due:
                time.sleep(cfg.boost_fov_settle_s)   # 等 FOV 展開（僅取樣輪，~每 N 次一次）
                self._boost_fov_pair_save(frame, screen)
        elif action == "CAVE":
            self.log_act.info("mining: Cave Skim 冷卻好 -> D2 Z（削洞穴方塊）")
            self.last_action = "削洞穴(D2 Z)"
            self.stats["cave_skims"] = self.stats.get("cave_skims", 0) + 1
            miner.use_cave_skim()
            self._radar_last["cave"] = time.time()
            self._radar_check_at = 0.0                # 下輪立刻重讀徽章確認真的觸發
        elif action == "SCAN":
            self.log_act.info("mining: Cyberscan 冷卻好 -> D2 左鍵（範圍自動採礦）")
            self.last_action = "雷達掃描(D2 左鍵)"
            self.stats["radar_scans"] = self.stats.get("radar_scans", 0) + 1
            miner.use_radar_scan()
            self._radar_last["scan"] = self._radar_auto_scan_at = time.time()
            self._radar_check_at = 0.0
        elif action == "USE_D4":
            self._handle_use_d4(frame)
        elif action is None:
            self.last_action = "挖礦中"

        # 卡住偵測：用中央遊戲區判斷（避開左下狀態小窗）
        cur = capture.crop(frame, cfg.stuck_region)
        if self._prev_frame is not None:
            diff = vision.frame_mean_diff(cur, self._prev_frame)
            if diff >= cfg.stuck_frame_diff_threshold or action is not None:
                self._last_progress = time.time()
                self._stuck_notified = False
                self._stuck_alert_mid = None       # 進度恢復＝卡住解除，🏠 作廢
        self._prev_frame = cur
        if (not self._stuck_notified
                and time.time() - self._last_progress > cfg.stuck_timeout_s):
            self.log.log("STUCK", reason=f"{cfg.stuck_timeout_s}s 無進度")
            self.stats["stuck"] += 1
            self._snapshot(frame, "stuck")
            self._alert("腳本可能卡住了")
            self._notify_stuck(f"{cfg.stuck_timeout_s:.0f}s 無進度")
            self._stuck_notified = True

    def _tracker_log(self, msg):
        """find_tracker 候選 log 路由：per-candidate 細節→DEBUG，決策摘要→INFO。

        摘要（soft-filter 退回 HSV / 全數硬拒）是事後診斷誤判的關鍵，降到 INFO
        確保預設 level 就能從 harvest.log 看出「為何這幀被判有/無追蹤框」。
        """
        if msg.startswith("shape確認"):
            self.log_harvest.debug(msg)
        else:
            self.log_harvest.info(msg)

    def _harvest_boost_guard(self, frame) -> bool:
        """採集期間 boost 守門（H026 對策）：D5 到期會以畫面中心為錨收縮 FOV（~2.6x 縮放），
        所有螢幕座標整批外推——sweep 確認的框 (1084,744) 實測被推到底緣 (1288,1049)。
        MINING 的「到期即補」在 HARVESTING 不會跑 → 舊版採集全程凍在收縮後 FOV，ref/座標/
        偵測全部失準。此守門在採集每個關鍵點（tick 頂、sweep 每方位、輪詢中）跑既有的便宜
        瓶子檢查（單尺度 edge-match ~56ms、0.2s 節流），一消失立刻補 D5 → FOV 回到掃描時
        狀態、座標復原（buff 還在時按 D5 無效、無法提早續時，只能到期即補——2026-07-02 實測）。
        回傳 True＝剛補了 D5 且已等 FOV 展開（畫面已變，呼叫端必須重抓幀再偵測/開火）。
        """
        if not self._boost_needs_refresh(frame):
            return False
        self.log_act.info("[%s] harvest: boost 消失 -> 立即補 D5（FOV 守門）",
                          self.harvest.harvest_id if self.harvest else "?")
        self.stats["boosts"] += 1
        screen = self._boost_screen_count(frame)
        pair_due = harvester.plan_boost_pair_due(
            screen, self._bc_last_pair_screen, cfg.boost_fov_pair_every_n)
        miner.use_boost_harvest()
        self._last_boost = time.time()      # 冷卻 gate：瓶子出現前不重複按
        self._boost_present = True          # 樂觀更新快取；下個節流窗會重驗
        self._boost_press_pending = True    # 使用確認等偵測到瓶子重現（樂觀快取不算）
        time.sleep(cfg.boost_fov_settle_s)  # 等 FOV 展開，之後抓的幀才是最終座標
        if pair_due:
            self._boost_fov_pair_save(frame, screen)
        return True

    def _find_tracker(self, frame, exclude, reference_bgr=None, log=None, with_score=False,
                      collect_rejects=None):
        """採集偵測統一入口：HSV 快速定位 + 實機裁圖外框形狀確認（混合方案）。

        shape_templates 為空（無實機裁圖）時 find_tracker 自動退回純 HSV。
        with_score=True 時回傳 (x, y, edge)，供 sweep 早停判斷高吻合度。
        collect_rejects：傳 list 進來時收集「值得人工看的被拒候選」（remote-aim 用）。
        """
        return vision.find_tracker(
            frame, exclude=exclude, reference_bgr=reference_bgr, log=log,
            margin_frac=cfg.tracker_margin_frac,
            shape_templates=self._shape_templates,
            shape_threshold=cfg.tracker_shape_threshold,
            shape_hard_floor=cfg.tracker_shape_hard_floor,
            shape_scales=cfg.tracker_shape_scales,
            shape_roi_px=cfg.tracker_shape_roi_px, with_score=with_score,
            collect_rejects=collect_rejects,
            rescue_v_min=cfg.tracker_rescue_v_min,
            rescue_area_min=cfg.tracker_rescue_area_min,
            rescue_max=cfg.tracker_rescue_max_candidates,
            rescue_dedup_px=cfg.tracker_rescue_dedup_px)

    def _find_tracker_near(self, frame, center, exclude, reference_bgr=None):
        """verify 輪詢快路徑：只搜開火座標周圍 ROI（參數組與 _find_tracker 一致）。"""
        return vision.find_tracker_near(
            frame, center, cfg.verify_roi_radius_px,
            frame_margin_frac=cfg.tracker_margin_frac,
            exclude=exclude, reference_bgr=reference_bgr,
            shape_templates=self._shape_templates,
            shape_threshold=cfg.tracker_shape_threshold,
            shape_hard_floor=cfg.tracker_shape_hard_floor,
            shape_scales=cfg.tracker_shape_scales,
            shape_roi_px=cfg.tracker_shape_roi_px,
            rescue_v_min=cfg.tracker_rescue_v_min,
            rescue_area_min=cfg.tracker_rescue_area_min,
            rescue_max=cfg.tracker_rescue_max_candidates,
            rescue_dedup_px=cfg.tracker_rescue_dedup_px)

    def _rotate_verified(self, direction: int) -> bool:
        """送一次視角鍵（+1=右轉 .、-1=左轉 ,）並以前後幀驗證「真的轉了 45°」。

        視角回歸差 45° 的根治點（2026-07-05）：回歸靠 net_rotations 計數反轉，前提是
        每個 ,/. 都真的生效——pickup 動畫（1-2s 吃鍵）/焦點被搶都會吃掉旋轉鍵，被吃
        一次視角就停在 45° 斜角（挖礦視角 90° 倍數對齊，斜角直接影響效率）。
        驗證：旋轉讓中央場景帶劇變、被吃則幾乎逐位元相同 → rotation_looks_eaten 兩訊號
        （平均差＋有感變化像素佔比）都近零才判被吃（實際轉了卻重送＝直接製造 45° 偏移，
        比漏判更糟）→ 重新聚焦後重送（上限 rotation_max_retries）。回 False＝重試用盡
        仍沒轉，呼叫端**不可計入 net_rotations**——計數與實際角度保持一致，restore 才回
        得到原角。settle 已含在內（rotation_settle_s），呼叫端不需再 sleep。
        """
        key = "." if direction > 0 else ","
        for attempt in range(cfg.rotation_max_retries + 1):
            before = capture.crop(capture.grab(), cfg.rotation_verify_region)
            if direction > 0:
                ic.rotate_right()
            else:
                ic.rotate_left()
            time.sleep(cfg.rotation_settle_s)
            after = capture.crop(capture.grab(), cfg.rotation_verify_region)
            mean_diff = vision.frames_mean_diff(before, after)
            changed = vision.frames_changed_frac(
                before, after, cfg.rotation_changed_pixel_thresh)
            if not harvester.rotation_looks_eaten(
                    mean_diff, changed,
                    cfg.rotation_eaten_mean_diff, cfg.rotation_eaten_changed_frac):
                if attempt:
                    self.logger.info("旋轉鍵 %s 第 %d 次重送後確認生效（mean=%s frac=%s）",
                                     key, attempt, mean_diff, changed)
                else:
                    self.log_harvest.debug("旋轉 %s 確認生效 mean=%s frac=%s",
                                           key, mean_diff, changed)
                return True
            self.logger.warning("旋轉鍵 %s 疑似被吃（mean_diff=%s changed_frac=%s，"
                                "attempt %d/%d）→ 重新聚焦後重送",
                                key, mean_diff, changed,
                                attempt + 1, cfg.rotation_max_retries + 1)
            self._focus_roblox()
        self.logger.warning("旋轉鍵 %s 重試用盡仍未生效——不計入 net_rotations（視角未轉）", key)
        return False

    def _record_target_observation(self, *, layer, dir_idx, pos, score,
                                   status, source, snapshot_path):
        observation = remote_aim.TargetObservation(
            layer=layer, dir_idx=int(dir_idx) % 8,
            pos=(int(pos[0]), int(pos[1])), score=float(score),
            status=status, source=source, snapshot_path=snapshot_path or "")
        self._target_observations.append(observation)
        self.log_harvest.info(
            "[%s] target observation status=%s source=%s layer=%s dir=%d pos=%s score=%.3f image=%s",
            self.harvest.harvest_id, status, source, layer, observation.dir_idx,
            observation.pos, observation.score, observation.snapshot_path)
        return observation

    def _sweep_for_tracker(self, excl, ref):
        """Scan eight directions while retaining absolute-direction target evidence.

        H118（2026-07-28）：`_harvest_boost_guard` 補 D5 是「FOV 全域收縮/展開」，
        不只影響當下這一幀——`ref`（背景排除基準）是在補之前的舊 FOV 下拍的，
        補完之後每個座標都對不上，本輪剩下的方位偵測與掃完後的最終 verify
        會系統性全部錯位。118 實錄：01:07:45 補 D5、01:07:57 verify
        lost target、緊接著的重掃（`_reharvest_sweep`，H026 對策不重拍 ref）
        也全 8 方位落空——因為那次重掃仍沿用同一份已經對不上的舊 ref。

        這裡不敢當場重拍 ref（H026：拍到當下畫面裡的活框會把它排除掉、自我致盲），
        只記一個旗標讓 `_tick_harvest` 知道「這輪 sweep 失敗前 FOV 確實變過」，
        RESWEEP 分流時才有根據地選擇性重拍 ref（見 `_reharvest_sweep(refresh_ref=)`）。
        """
        hid = self.harvest.harvest_id
        num_dirs = 8
        candidates = []
        sweep_frames = []
        self._sweep_fov_shifted = False
        for local_index in range(num_dirs):
            abs_dir = self.harvest.net_rotations % num_dirs
            frame = capture.grab()
            if self._harvest_boost_guard(frame):
                frame = capture.grab()
                self._sweep_fov_shifted = True
            rejects = [] if cfg.remote_aim_enabled else None
            first = self._find_tracker(
                frame, excl, ref, log=self._tracker_log, with_score=True,
                collect_rejects=rejects)
            if cfg.sweep_empty_snapshot:
                sweep_frames.append((abs_dir, frame.copy(), rejects or []))
            if first:
                first_pos = (first[0], first[1])
                time.sleep(0.08)
                second_frame = capture.grab()
                second = self._find_tracker(
                    second_frame, excl, ref, log=self._tracker_log, with_score=True)
                second_pos = (second[0], second[1]) if second else None
                stable = (second_pos is not None
                          and abs(first_pos[0] - second_pos[0]) < 8
                          and abs(first_pos[1] - second_pos[1]) < 8)
                if stable:
                    if self._shape_templates and second[2] >= cfg.tracker_shape_early_exit:
                        path = self._hsnap(
                            second_frame,
                            "sweep_confirmed_dir%d_%d_%d" %
                            (abs_dir, second_pos[0], second_pos[1]))
                        self._record_target_observation(
                            layer=self.harvest.pitch_layer, dir_idx=abs_dir,
                            pos=second_pos, score=second[2], status="accepted",
                            source="sweep_early_exit", snapshot_path=path)
                        self.log_harvest.info(
                            "[%s] sweep abs_dir=%d(local=%d): high edge=%.2f, early accept %s",
                            hid, abs_dir, local_index, second[2], second_pos)
                        self.log.log("TRACKER_FOUND", harvest_id=hid,
                                     direction=abs_dir, pos=str(second_pos),
                                     image_path=path)
                        return second_pos, True
                    path = self._hsnap(
                        second_frame,
                        "sweep_accepted_dir%d_%d_%d" %
                        (abs_dir, second_pos[0], second_pos[1]))
                    self._record_target_observation(
                        layer=self.harvest.pitch_layer, dir_idx=abs_dir,
                        pos=second_pos, score=second[2], status="accepted",
                        source="sweep_stable", snapshot_path=path)
                    candidates.append((abs_dir, second_pos))
                    self.log_harvest.info(
                        "[%s] sweep abs_dir=%d(local=%d): stable %s edge=%.2f",
                        hid, abs_dir, local_index, second_pos, second[2])
                else:
                    path = self._hsnap(
                        frame, "sweep_seen_once_dir%d_%d_%d" %
                        (abs_dir, first_pos[0], first_pos[1]))
                    self._record_target_observation(
                        layer=self.harvest.pitch_layer, dir_idx=abs_dir,
                        pos=first_pos, score=first[2], status="seen_once",
                        source="double_frame_unstable", snapshot_path=path)
                    self.log_harvest.info(
                        "[%s] sweep abs_dir=%d(local=%d): seen once m1=%s m2=%s",
                        hid, abs_dir, local_index, first_pos, second_pos)
            else:
                self.log_harvest.info(
                    "[%s] sweep abs_dir=%d(local=%d): no tracker",
                    hid, abs_dir, local_index)
            if local_index < num_dirs - 1 and self._rotate_verified(+1):
                self.harvest.net_rotations += 1

        if not candidates:
            self.log_harvest.info("[%s] sweep: all directions lacked a stable tracker", hid)
            if cfg.sweep_empty_snapshot and sweep_frames:
                for abs_dir, frame, rejects in sweep_frames:
                    path = self._hsnap(
                        frame, harvester.sweep_snapshot_label(
                            self.harvest.pitch_layer, abs_dir))
                    self._sweep_shots.append(remote_aim.SweepShot(
                        layer=self.harvest.pitch_layer, dir_idx=abs_dir,
                        snapshot_path=path or "", rejects=rejects))
                self.log_harvest.info(
                    "[%s] sweep empty: queued %d absolute-direction frames",
                    hid, len(sweep_frames))
            return None, False

        best_dir, best_pos = harvester.pick_sweep_candidate(candidates, cfg.screen_w)
        current_dir = self.harvest.net_rotations % num_dirs
        delta = harvester.plan_return_rotations(current_dir, best_dir, num_dirs)
        self.log_harvest.info(
            "[%s] sweep best abs_dir=%d pos=%s; current=%d rotate=%+d",
            hid, best_dir, best_pos, current_dir, delta)
        for _ in range(abs(delta)):
            direction = 1 if delta > 0 else -1
            if self._rotate_verified(direction):
                self.harvest.net_rotations += direction

        time.sleep(0.2)
        verify_frame = capture.grab()
        verified = self._find_tracker(
            verify_frame, excl, ref, log=self._tracker_log, with_score=True)
        if verified:
            verified_pos = (verified[0], verified[1])
            verified_dir = self.harvest.net_rotations % num_dirs
            path = self._hsnap(
                verify_frame, "sweep_confirmed_dir%d_%d_%d" %
                (verified_dir, verified_pos[0], verified_pos[1]))
            self._record_target_observation(
                layer=self.harvest.pitch_layer, dir_idx=verified_dir,
                pos=verified_pos, score=verified[2], status="accepted",
                source="sweep_verify", snapshot_path=path)
            self.log_harvest.info(
                "[%s] sweep verify accepted abs_dir=%d %s (desired=%d prior=%s)",
                hid, verified_dir, verified_pos, best_dir, best_pos)
            self.log.log("TRACKER_FOUND", harvest_id=hid, direction=verified_dir,
                         pos=str(verified_pos), image_path=path)
            return verified_pos, True
        self.log_harvest.info(
            "[%s] sweep verify lost target at abs_dir=%d prior=%s",
            hid, best_dir, best_pos)
        return None, True

    def _recover_historical_target(self, excl) -> bool:
        """Try one bounded D2/ROI recovery at the best retained absolute target."""
        if self._target_recovery_attempts >= cfg.harvest_target_recovery_max:
            return False
        observation = remote_aim.pick_recovery_observation(
            self._target_observations)
        if observation is None:
            return False
        self._target_recovery_attempts += 1
        hid = self.harvest.harvest_id
        self.log_harvest.info(
            "[%s] historical recovery %d/%d: status=%s layer=%s dir=%d pos=%s",
            hid, self._target_recovery_attempts,
            cfg.harvest_target_recovery_max, observation.status,
            observation.layer, observation.dir_idx, observation.pos)
        if not self._focus_roblox() or self._mine_resetting:
            return False

        current_dir = self.harvest.net_rotations % 8
        steps = harvester.plan_return_rotations(
            current_dir, observation.dir_idx, 8)
        moved = 0
        for _ in range(abs(steps)):
            direction = 1 if steps > 0 else -1
            if self._rotate_verified(direction):
                self.harvest.net_rotations += direction
                moved += direction
        if moved != steps:
            self.log_harvest.warning(
                "[%s] historical recovery yaw incomplete %d/%d", hid, moved, steps)
            return False

        if observation.layer != self.harvest.pitch_layer:
            if cfg.sweep_pitch_center_back_px <= 0:
                self.log_harvest.info(
                    "[%s] historical recovery skipped: pitch calibration unavailable", hid)
                return False
            nudge = {"mid": 0, "up": -cfg.sweep_pitch_step_px,
                     "down": cfg.sweep_pitch_step_px}[observation.layer]
            self.harvest.pitch_touched = True
            ok = self._pitch_drag_verified(
                f"[{hid}] recovery pitch reset",
                lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                       cfg.sweep_pitch_center_back_px))
            if ok and nudge:
                ok = self._pitch_drag_verified(
                    f"[{hid}] recovery pitch nudge {nudge}px",
                    lambda: ic.pitch_nudge(nudge))
            if not ok:
                return False
            self.harvest.pitch_layer = observation.layer

        harvester.prepare_scan()
        self._await_scan_ready("historical-recovery")   # 等冷卻要在拍 ref 之前
        scan_reference = capture.grab()
        if self._harvest_boost_guard(scan_reference):
            scan_reference = capture.grab()
        self._run_scan()
        self._confirm_scan("historical-recovery")
        reference = getattr(self, "_pre_scan_ref", None)
        if reference is None:
            reference = scan_reference
        recovered = None
        recovered_score = 0.0
        for threshold in (cfg.tracker_shape_threshold, 0.0):
            current = capture.grab()
            result = vision.find_tracker_near(
                current, observation.pos, cfg.harvest_target_recovery_radius_px,
                frame_margin_frac=0.0, exclude=excl,
                reference_bgr=reference,
                shape_templates=self._shape_templates,
                shape_threshold=threshold, shape_hard_floor=0.0,
                shape_scales=cfg.tracker_shape_scales,
                shape_roi_px=cfg.tracker_shape_roi_px, with_score=True)
            if result:
                recovered = (result[0], result[1])
                recovered_score = result[2]
                break
        if recovered is None:
            self.log_harvest.info("[%s] historical recovery found no fresh tracker", hid)
            return False
        path = self._hsnap(
            current, "sweep_accepted_recovery_dir%d_%d_%d" %
            (observation.dir_idx, recovered[0], recovered[1]))
        self._record_target_observation(
            layer=observation.layer, dir_idx=observation.dir_idx,
            pos=recovered, score=recovered_score, status="accepted",
            source="historical_recovery", snapshot_path=path)
        self._target_marker = recovered
        self._harvest_start = time.time()
        self.harvest.elapsed_s = 0.0
        self.last_action = "歷史目標方位復原成功"
        self.logger.info(
            "[%s] historical recovery restored tracker at dir=%d pos=%s",
            hid, observation.dir_idx, recovered)
        return True

    def _harvest_giveup(self, reason: str, *, face_tracker: bool = False):
        """採集放棄 → 依「有無追蹤框」決定視角處置 + 截圖，交人工（需求 A+C）。

        face_tracker=True（D3 階段失敗、追蹤框仍在畫面）：**保持面對追蹤框、不轉回**，tracker
          群給追蹤框裁圖（人工可據此手動採；不附 rotation_hint，因已正對著框）。
        face_tracker=False（沒找到框/掃描超時/採到但重新聚焦失敗）：**轉回原視角**。

        兩條路徑都附聊天/背包前後對比裁圖（H015 對策：D3 超時時框可能已消失，框裁圖上空無
        一物；前後對比才判得出「礦其實已採到」的好假警報）。
        視角/截圖決策抽在 harvester.plan_giveup（純函式、有測試）；本方法只做 I/O glue。
        """
        # NEEDS_HUMAN 事件一律帶本輪編號（Discord 顯示 [Hxxx]，與截圖/log 串連，事後一鍵搜查）
        self._needs_human_extra_meta = {"harvest_id": self.harvest.harvest_id}
        # face_tracker 需真的有 marker 才成立（防呼叫端誤傳；D3 超時路徑 marker 必已設）
        plan = harvester.plan_giveup(face_tracker and self._target_marker is not None)

        if plan.restore_view:
            self._pitch_restore_if_touched()  # 先俯仰歸位（face_tracker=False 分支才歸位；保持面對框則不動）
            if self.harvest.net_rotations:
                self.logger.info("[%s] 採集放棄 -> 轉回原方位 net=%d",
                                 self.harvest.harvest_id, self.harvest.net_rotations)
                harvester.restore_view(self.harvest.net_rotations, rotate=self._rotate_verified)
                self.harvest.net_rotations = 0

        self._human_reason = reason
        frame = capture.grab()              # 轉回後重抓（tracker_view 路徑沒轉回＝面對框現況）

        # 兩條路徑都附「聊天/背包前後對比」分組（H015：D3 超時只送框裁圖、而框已消失＝圖上
        # 空無一物，人工無從判斷「礦是否其實已採到」；左側 UI 是螢幕覆蓋層、與視角無關）。
        # 有框路徑另加 tracker 群排最前＝追蹤框現況（人工可據此手動採）。
        # before＝**本輪採集開始時**的 _harvest_origin_ref（不是最近一次 sweep 的
        # _pre_scan_ref——RESWEEP 會重拍它，若礦其實已採到，重拍的是「採完後」畫面，
        # before/after 會一模一樣、對比失去鑑別力，H020 實錄）、after＝現在（放棄時）。
        groups = []
        if plan.tracker_view:
            p = self._save_tracker_screenshot(frame, self._target_marker, 0)  # net_rot=0：正對著框，免旋轉提示
            if p:
                groups.append(("tracker", [p]))
        region_map = {"chat": cfg.chat_review_region, "backpack": cfg.backpack_review_region}
        before_ref = getattr(self, "_harvest_origin_ref", None)
        if before_ref is None:                  # 舊路徑後備（理論上進 HARVESTING 必已設）
            before_ref = getattr(self, "_pre_scan_ref", None)
        src_map = {"before": before_ref, "after": frame}
        for region, crops in harvester.giveup_send_groups(plan.review_crops):
            paths = []
            for c in crops:
                src = src_map[c.source]
                if src is None:             # 首輪還沒 _pre_scan_ref → 跳過該來源
                    continue
                p = self._hsnap_crop(src, region_map[c.region], c.label)
                if p:
                    paths.append(p)
            if paths:
                groups.append((region, paths))
        # 遠端瞄準 context（2026-07-11 spec）：記「giveup 收尾後」的絕對姿態——
        # restore_view 路徑歸位完 net=0/mid；face_tracker 路徑保持面對框（net/層照舊）
        self._aim_context = None
        if (cfg.remote_aim_enabled
                and (self._sweep_shots or self._target_observations)):
            ctx = remote_aim.build_aim_context(
                self._sweep_shots, self.harvest.net_rotations,
                self.harvest.pitch_layer, self.harvest.harvest_id,
                now=time.time(), max_candidates=cfg.remote_aim_max_candidates,
                observations=self._target_observations,
                dedup_radius_px=cfg.remote_aim_dedup_radius_px)
            rendered = self._render_aim_shots(ctx)   # 疊圖＋落盤
            self._aim_context = ctx
            if rendered:
                # 全候選圖都發（4 張/組批次）；caption 由純函式組（群標題＋總表）。
                # 組名即 caption——走 format_group_messages 的 fallback。
                summary = remote_aim.format_candidate_summary(ctx.candidates)
                groups = remote_aim.build_aim_groups(rendered, summary) + groups
                self._push_web_aim_candidates(ctx, rendered, summary)
        if groups:
            self._needs_human_extra_meta["image_groups"] = groups

        # H051（092 實錄）：重置倒數中 chill 搶先採集，掃描期間礦坑清場 → 掃描全空
        # 是重置的正常結果，不是「礦被挖走」。NEEDS_HUMAN 會卡死（banner worker 不在
        # 該狀態跑、無人清旗標、reset_complete 永不成立）——回 RESET_WAIT 讓既有
        # reset_complete → REENTRY 鏈接手（比照 _rr_abort_reset）。
        if self._mine_resetting:
            self._needs_human_extra_meta = {}
            self.logger.info("[%s] 採集放棄但礦坑重置 pending -> 回 RESET_WAIT（不交人工）",
                             self.harvest.harvest_id)
            self.state = State.RESET_WAIT
            self._on_enter(State.RESET_WAIT, frame)
            return

        self.state = State.NEEDS_HUMAN
        self._on_enter(State.NEEDS_HUMAN, frame)

    def _draw_aim_header(self, img, text: str) -> None:
        """疊圖上緣黑條＋大字標頭——縮圖牆也能辨認 DIR（2026-07-19 spec §3）。"""
        import cv2
        cv2.rectangle(img, (0, 0), (img.shape[1], 56), (0, 0, 0), -1)
        cv2.putText(img, text, (12, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    (0, 215, 255), 3)

    def _render_aim_shots(self, ctx):
        """Render direction-labelled overlays after async source snapshots are ready.

        回 [(候選編號 tuple, dir_idx, layer, 疊圖路徑)]；排序、批次與 caption
        交給 remote_aim.build_aim_groups（純函式）。候選圖一律用偵測當下原幀
        （D2 效果保證，spec 核心不變量）。
        """
        import cv2
        out = []
        deadline = time.monotonic() + cfg.remote_aim_snapshot_wait_s
        for shot in ctx.shots:
            exact = [candidate for candidate in ctx.candidates
                     if candidate.snapshot_path
                     and candidate.snapshot_path == shot.snapshot_path]
            legacy = [candidate for candidate in ctx.candidates
                      if not candidate.snapshot_path
                      and (candidate.layer, candidate.dir_idx) ==
                      (shot.layer, shot.dir_idx)]
            candidates = exact or legacy
            if not candidates or not shot.snapshot_path:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            if not self._wait_snapshot_ready(shot.snapshot_path, remaining):
                self.logger.warning("AIM source snapshot missing: %s", shot.snapshot_path)
                continue
            image = cv2.imread(shot.snapshot_path)
            if image is None:
                self.logger.warning("AIM source snapshot unreadable: %s", shot.snapshot_path)
                continue
            overlaid = remote_aim.draw_overlay(image, candidates, grid=True)
            statuses = ",".join(dict.fromkeys(c.status for c in candidates))
            self._draw_aim_header(
                overlaid,
                # H056：標頭數字＝使用者要輸入的方位號（1-8），與回礦介面一致
                f"DIR {remote_aim.dir_label(shot.dir_idx)} | "
                f"{shot.layer.upper()} | {statuses.upper()}")
            path = os.path.splitext(shot.snapshot_path)[0] + "_aim.png"
            if not cv2.imwrite(path, overlaid):
                self.logger.warning("AIM overlay write failed: %s", path)
                continue
            label = (f"{ctx.harvest_id}_aim_overlay_dir{shot.dir_idx}_"
                     f"{shot.layer}_{statuses}")
            try:
                diagnostics.append_snapshot_index(cfg.log_dir, label, path)
            except Exception as exc:
                self.logger.warning("AIM overlay index failed (%s): %s", path, exc)
            numbers = tuple(sorted(c.number for c in candidates))
            out.append((numbers, shot.dir_idx, shot.layer, path))
        return out

    def _push_web_aim_candidates(self, ctx, rendered, summary: str) -> None:
        """把 `_render_aim_shots` 疊好的候選圖也推給 web client（2026-07-27）。

        原本這批圖只發 Discord——web 在線也沒接線，玩家連著網頁只能切回 Discord
        打編號。疊圖本身跟 Discord 那份完全一樣（同一批 `rendered` 檔案），差別只
        在 dir/layer meta（web 點擊要回報這兩個，bot 才知道除了轉方位還要不要調
        俯仰——見 `_handle_web_aim_click`）。目前只有 giveup 進點呼叫；開火失敗
        重建候選（`_tick_remote_aim` 的 fire_failed 分支）跟 Discord 一樣不重推
        整批圖，只送簡短失敗截圖——web 那邊沿用上一批圖的 dir/layer 繼續點即可。
        """
        if not self._web_client_online():
            return
        import cv2
        web_frames = []
        for _numbers, dir_idx, layer, path in rendered:
            img = cv2.imread(path)
            if img is None:
                continue
            png = self._encode_png(img)
            if png:
                web_frames.append((dir_idx, layer, png))
        if web_frames:
            self._send_web_intervention_frames(
                flow="harvest", routing_key=f"harvest:{ctx.harvest_id}",
                frames=web_frames, ctx_summary=summary,
                note="點候選框位置開火；也可在 Discord 回編號/`跳過`/`手動`")

    # ---- B3：遠端瞄準回覆消費 + fire 執行（主迴圈執行緒）-------------------
    def _tick_remote_aim(self, frame, reply):
        """消費一則瞄準回覆（主迴圈執行緒）。skip→回挖礦；manual→重掃＋全方位圖；
        candidate/grid→對齊+重掃+開火+驗證。

        一發＝一次 D3＋一個 verify 窗口，不自動 RETRY/RESWEEP（spec：要不要再射由使用者決定，
        每次回報附最新截圖）。全程 remote_aim_budget_s 預算防卡死。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._aim_context
        if reply.kind == "skip":
            self.logger.info("AIM skip -> 回挖礦")
            self._broadcast_intervention_result(
                ctx, "skip", "▶️ 已跳過，回挖礦", flow="harvest")
            self._aim_context = None
            self.human_cleared = True          # 下 tick decide_transition 回 MINING（同 resume）
            notify.send_message(token, ch, "▶️ 跳過這顆，回挖礦")
            return
        if reply.kind == "manual":
            ctx.awaiting_fine = False          # 離開退路、重走 8 方位 survey
            self._aim_busy = True
            try:
                self._execute_manual_survey(ctx)
            finally:
                self._aim_busy = False
            return
        if reply.kind in ("fine", "magnify", "back"):
            # 放大手選退路（harvest 101 §5）：細格點擊／再放大／退層
            self._aim_busy = True
            try:
                if reply.kind == "fine":
                    self._execute_aim_fine_fire(ctx, reply.cell)
                elif reply.kind == "magnify":
                    self._aim_magnify(ctx, reply.cell)
                else:
                    self._aim_back(ctx)
            finally:
                self._aim_busy = False
            return
        # 解目標 (層, 方位, 位置先驗)
        if reply.kind == "candidate":
            c = ctx.candidates[reply.number - 1]
            tgt_layer, tgt_dir, prior = c.layer, c.dir_idx, c.pos
        elif reply.kind == "point":
            # web 候選清單點擊（2026-07-28）：玩家給的是原生像素，不是候選編號／
            # 格代碼——候選清單疊圖可能是好幾分鐘前掃的（D2/D5 早過期），跟 candidate
            # 分支一樣交給 _execute_remote_fire 走完整對齊＋重掃＋_refind_tracker_near，
            # 不能假設這個座標現在還準。
            tgt_layer, tgt_dir, prior = reply.layer, reply.dir_idx, reply.pos
        else:
            tgt_layer, tgt_dir = reply.layer, reply.dir_idx
            prior = remote_aim.grid_cell_center(reply.cell)
        self._aim_busy = True
        try:
            ok, detail = self._execute_remote_fire(ctx, tgt_layer, tgt_dir, prior,
                                                   cell=reply.cell)
        finally:
            self._aim_busy = False
        if ok is None:
            return                             # 進入放大手選退路（_enter_aim_fine 已發圖＋設狀態）
        if ok:
            self._broadcast_intervention_result(
                ctx, "fire_ok", "✅ 已採集", flow="harvest")
            self._aim_context = None           # 成功收尾（_execute 內已切 MINING）
        else:
            # 失敗：把這次 fired observation 納入下一輪候選，再附當下截圖。
            self._broadcast_intervention_result(
                ctx, "fire_failed", f"❌ 未確認命中（{detail}），重新整理候選中…",
                flow="harvest")
            ctx = remote_aim.build_aim_context(
                ctx.shots, ctx.pose_net_rotations, ctx.pose_pitch_layer,
                ctx.harvest_id, now=time.time(),
                max_candidates=cfg.remote_aim_max_candidates,
                observations=self._target_observations)
            self._aim_context = ctx
            cur = capture.grab()
            p1 = self._snapshot(cur, "aim_fail_scene")
            p2 = self._snapshot_crop(cur, cfg.chat_review_region, "aim_fail_chat")
            paths = self._ready_snapshot_paths([p for p in (p1, p2) if p])
            msg = f"❌ 未確認命中（{detail}）。可再回編號/格子重試，或 `跳過` 回挖礦"
            if paths:
                notify.send_images_message(token, ch, msg, paths)
            else:
                notify.send_message(token, ch, msg)

    def _execute_manual_survey(self, ctx):
        """手動最後手段（2026-07-19 spec §4）：現場重按 D2＋確認生效 → 8 方位各拍一張
        （效果窗內＝手動圖的 D2 保證）→ 疊網格＋DIR 標頭 → 4 張/則發送＋格子瞄準說明。

        只拍 mid 層（`5U C3`/`5D C3` 盲射語法仍可用）、不開火；失敗回報後不自動重試
        （有界），_aim_context 保留等下一則回覆。姿態記帳走 ctx.pose_net_rotations，
        旋轉被吃不計（同 fire 路徑慣例）——轉滿 8 次回原方位。

        P4 Task 3：進入時先檢查 web_pending 在線與否——web 在線則推截圖給 web client、
        等玩家 pinch-zoom + tap 直接點位置（60s 預算＝remote_aim_budget_s），reply 直接
        走 _execute_remote_fire_from_web 開火+驗證（跳過底下整段 Discord 八方位圖）；
        無 reply（timeout）或無 web 連線 → fall through 既有 Discord 八方位流程（fallback）。
        """
        # P4 Task 3：web 在線 → 先走 web 介入面板（pinch-zoom + tap 取代 Discord 八方位）
        web_state = getattr(self, "_web_fallback", None)
        if (self._web_pending is not None and web_state is not None
                and not web_state.is_fallback(
                    now=time.monotonic(), grace_s=cfg.web_fallback_grace_s)):
            routing_key = f"harvest:{ctx.harvest_id}"
            if self._focus_roblox():
                frame = capture.grab()
                if frame is not None:
                    self._send_web_intervention_event(
                        flow="harvest", routing_key=routing_key,
                        frame=frame, ctx_summary=self._summarize_survey_ctx(ctx),
                    )
                reply = self._await_web_pointer_reply(
                    routing_key=routing_key, timeout_s=cfg.remote_aim_budget_s,
                )
                if reply is not None:
                    self.log_discord.info(
                        "[%s] MANUAL survey: 收到 web reply %r，跳過 Discord 八方位",
                        ctx.harvest_id, reply)
                    return self._execute_remote_fire_from_web(
                        ctx,
                        x=int(reply.get("x", 0)),
                        y=int(reply.get("y", 0)),
                    )
                self.log_discord.info(
                    "[%s] MANUAL survey: web reply timeout，fall through Discord 八方位",
                    ctx.harvest_id)
                self._broadcast_intervention_result(
                    ctx, "web_timeout", "網頁逾時未回應，已改用 Discord 八方位",
                    flow="harvest")
            else:
                self.log_discord.info(
                    "[%s] MANUAL survey: 無法聚焦 Roblox，跳過 web 介入走 Discord",
                    ctx.harvest_id)
        # 既有 Discord 八方位圖流程（fallback）
        from . import notify
        import cv2
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        hid = ctx.harvest_id
        deadline = time.time() + cfg.remote_aim_budget_s
        if not self._focus_roblox():
            notify.send_message(token, ch, "❌ 無法聚焦 Roblox，可再回 `手動` 重試或 `跳過`")
            return
        if self._mine_resetting:
            notify.send_message(token, ch, "❌ 礦坑重置中，`跳過` 回挖礦")
            return
        if ctx.pose_pitch_layer != "mid":
            ok = self._pitch_drag_verified(
                f"[{hid}] MANUAL 俯仰歸位",
                lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                       cfg.sweep_pitch_center_back_px))
            ctx.pose_pitch_layer = "mid"   # reset 至少跑過，保守記歸位（同 fire 路徑）
            if not ok:
                notify.send_message(token, ch, "❌ 俯仰歸位被吃，可再回 `手動` 重試或 `跳過`")
                return
        harvester.prepare_scan()
        self._await_scan_ready("remote-aim-manual")
        self._run_scan()           # 重按 D2：手動圖必須在掃描效果窗內拍
        if not self._confirm_scan("remote-aim-manual"):
            notify.send_message(token, ch, "❌ 掃描未生效，可再回 `手動` 重試或 `跳過`")
            return
        snaps = {}                          # {abs_dir: 原幀快照路徑}；被吃重拍同方位保留最新
        for _ in range(8):
            if time.time() > deadline:
                self.logger.warning("[%s] MANUAL survey 預算用盡（拍到 %d 方位）",
                                    hid, len(snaps))
                break
            abs_dir = ctx.pose_net_rotations % 8
            frame = capture.grab()
            path = self._hsnap(frame, f"manual_survey_dir{abs_dir}")
            if path:
                snaps[abs_dir] = path
            if self._rotate_verified(1):
                ctx.pose_net_rotations += 1
        rendered = []
        wait_deadline = time.monotonic() + cfg.remote_aim_snapshot_wait_s
        for abs_dir in sorted(snaps):
            path = snaps[abs_dir]
            remaining = max(0.0, wait_deadline - time.monotonic())
            if not self._wait_snapshot_ready(path, remaining):
                self.logger.warning("MANUAL snapshot missing: %s", path)
                continue
            image = cv2.imread(path)
            if image is None:
                self.logger.warning("MANUAL snapshot unreadable: %s", path)
                continue
            remote_aim.draw_grid(image)
            self._draw_aim_header(
                image, f"DIR {remote_aim.dir_label(abs_dir)} | MID")
            out_path = os.path.splitext(path)[0] + "_manual.png"
            if not cv2.imwrite(out_path, image):
                self.logger.warning("MANUAL overlay write failed: %s", out_path)
                continue
            try:
                diagnostics.append_snapshot_index(
                    cfg.log_dir, f"{hid}_manual_survey_dir{abs_dir}", out_path)
            except Exception as exc:
                self.logger.warning("MANUAL overlay index failed (%s): %s", out_path, exc)
            rendered.append(out_path)
        if not rendered:
            notify.send_message(token, ch, "❌ 全方位快照失敗，可再回 `手動` 重試或 `跳過`")
            return
        for i in range(0, len(rendered), 4):
            caption = (remote_aim.MANUAL_SURVEY_HELP if i == 0
                       else "🧭 手動瞄準（續）")
            notify.send_images_message(token, ch, caption, rendered[i:i + 4])
        self.log_discord.info("MANUAL survey -> %d 方位圖已發", len(rendered))

    def _execute_remote_fire(self, ctx, tgt_layer, tgt_dir, prior, cell: str = ""):
        """對齊姿態 → 重新 D2 掃描 → 找框 → 開火 → 聊天驗證。回 (confirmed, 說明)。

        姿態記帳在 ctx（絕對姿態，與 self.harvest 的 net_rotations 分開——勿混用兩個來源）；
        對齊轉動的「被吃不計」規則比照 _sweep_for_tracker：只計實際轉成的步數。

        cell（harvest 101）：grid 路徑（玩家回 `方位 格子`）帶粗格代碼→限縮該格跑
        detect_tracker_core 找框真正中心、命中即自動開火；抓不到不盲打（101 病灶），
        記素材＋回報（放大手選退路見 _execute_remote_aim_fine）。candidate 路徑（回編號）
        cell 空→沿用既有 find_tracker_near 整幀重找（近失候選位置已精修，非本次目標）。
        """
        from . import notify
        deadline = time.time() + cfg.remote_aim_budget_s
        hid = ctx.harvest_id
        ready, detail = self._wait_for_d3_cooldown(deadline)
        if not ready:
            return False, detail
        if not self._focus_roblox():
            return False, "無法聚焦 Roblox"
        if self._mine_resetting:
            return False, "礦坑重置中"
        # 1. 對齊：yaw（驗證式）＋俯仰層（reset→nudge，同 pitch-sweep 慣例）
        steps, pitch = remote_aim.plan_alignment(
            ctx.pose_net_rotations, ctx.pose_pitch_layer, tgt_dir, tgt_layer)
        self.logger.info("[%s] AIM 對齊：rot=%+d pitch=%s（目標 dir=%d layer=%s）",
                         hid, steps, pitch, tgt_dir, tgt_layer)
        done = 0
        for _ in range(abs(steps)):
            if self._rotate_verified(1 if steps > 0 else -1):
                done += 1 if steps > 0 else -1
        ctx.pose_net_rotations += done         # 姿態記帳＝實際轉動（被吃不計）
        if done != steps:
            return False, f"轉向被吃（{done}/{steps}），姿態已記帳，可重試"
        if pitch is not None:
            nudge = {"up": -cfg.sweep_pitch_step_px, "down": cfg.sweep_pitch_step_px,
                     "mid": 0}[pitch]
            ok = self._pitch_drag_verified(
                f"[{hid}] AIM 俯仰歸位",
                lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                       cfg.sweep_pitch_center_back_px))
            if ok and nudge:
                ok = self._pitch_drag_verified(
                    f"[{hid}] AIM nudge {nudge}px", lambda: ic.pitch_nudge(nudge))
            if not ok:
                ctx.pose_pitch_layer = "mid"   # reset 至少跑過，保守記歸位
                return False, "俯仰對齊被吃，可重試"
            ctx.pose_pitch_layer = pitch
        # 2. 重新 D2 掃描（框早已到期；新 episode 語意，重拍 ref 正確——非 H026 情境）
        _cr = cfg.chat_region
        _excl = [(_cr.x, _cr.y, _cr.x + _cr.w, _cr.y + _cr.h)]   # 同 _tick_harvest 聊天排除組法
        chat_base_crop = capture.crop(capture.grab(), cfg.chat_region)   # 開火前基準（截圖先、OCR 後）
        harvester.prepare_scan()
        self._await_scan_ready("remote-aim")            # 等冷卻要在拍 ref 之前
        gf = capture.grab()
        if self._harvest_boost_guard(gf):
            gf = capture.grab()
        ref = gf
        self._run_scan()
        self._confirm_scan("remote-aim")
        # 3. 找框：grid 路徑走限縮偵測（harvest 101），candidate 路徑走既有 find_tracker_near
        if cell:
            pos, pos_score, detail = self._detect_core_in_cell(
                cell, tgt_dir, deadline, hid)
            if pos is None:
                if "未命中" in detail:
                    # 限縮偵測未命中（非綠色框/框不在格內）→ 放大手選退路（§5 步驟 5）
                    self._enter_aim_fine(ctx, cell, tgt_dir, tgt_layer, hid)
                    return None, "entered awaiting_fine"
                return False, detail             # 預算用盡／格無效
        else:
            pos, pos_score, detail = self._refind_tracker_near(
                prior, _excl, ref, deadline, hid)
            if detail:
                return False, detail
            if pos is None:
                pos = prior                    # candidate 路徑：直接朝先驗點開火（miss 代價＝一發）
                self.logger.info("[%s] AIM 重找全滅 -> 直接朝先驗點開火 %s", hid, pos)
        pos = (int(pos[0]), int(pos[1]))
        # 4-5. 開火＋驗證（grid 命中/candidate 共用尾段）
        return self._aim_fire_and_verify(
            pos, pos_score, tgt_layer, tgt_dir, ctx, hid, deadline, chat_base_crop)

    def _refind_tracker_near(self, prior, excl, ref, deadline, hid):
        """candidate 路徑既有 find_tracker_near 邏輯（自 _execute_remote_fire 拆出，純重構）。

        先正常門檻，再 shape_threshold=0（colored 過即收、edge 排序）。回 (pos, score, detail)：
        命中 (pos, score, "")；預算用盡 (None, -1.0, "預算用盡")；都沒命中 (None, -1.0, "")
        （呼叫端據 detail 決定 abort 或退回先驗盲打）。

        ROI 兩輪都全滅後還有 H056 全畫面兜底（見下方註解）——2026-07-21 合併 main 時，
        把 main 寫在未重構版 `_execute_remote_fire` 裡的那段搬進這裡（同一行為、換位置）。
        """
        for thr in (cfg.tracker_shape_threshold, 0.0):
            if time.time() > deadline:
                return None, -1.0, "預算用盡"
            f2 = capture.grab()
            pos = vision.find_tracker_near(
                f2, prior, cfg.remote_aim_refind_radius_px,
                frame_margin_frac=0.0, exclude=excl,
                reference_bgr=ref, shape_templates=self._shape_templates,
                shape_threshold=thr, shape_hard_floor=0.0,
                shape_scales=cfg.tracker_shape_scales,
                shape_roi_px=cfg.tracker_shape_roi_px, with_score=True)
            if pos:
                self.logger.info("[%s] AIM 重找命中 (thr=%.2f) -> %s", hid, thr, pos)
                return ((int(pos[0]), int(pos[1])), pos[2], "")
        if cfg.remote_aim_fullframe_fallback:
            # H056：ROI 全滅 -> 全畫面再找一次（**不帶 ref**：此時的替代方案是朝空地盲開，
            # 而 preexist 差分會把「掃描前就在畫面上的真框」剔掉——097 開火幀實測真框 edge=0.586）。
            # 安全靠形狀 confirmed 門檻（0.42）獨撐：不放寬、不吃 survivor，找不到就照舊盲開。
            if time.time() > deadline:
                return None, -1.0, "預算用盡"
            full = self._find_tracker(capture.grab(), excl, with_score=True)
            if full:
                self.logger.info("[%s] AIM 全畫面兜底命中 edge=%.2f -> %s（距先驗點 %.0fpx）",
                                 hid, full[2], (full[0], full[1]),
                                 math.hypot(full[0] - prior[0], full[1] - prior[1]))
                return ((int(full[0]), int(full[1])), full[2], "")
        return None, -1.0, ""

    def _detect_core_in_cell(self, cell, tgt_dir, deadline, hid):
        """grid 路徑限縮偵測（harvest 101 §5 步驟 3-4）：裁玩家選的粗格→detect_tracker_core
        找框真正中心→命中即回絕對座標。回 (pos, score, detail)；pos None 時 detail 說明原因。

        命中即自動開火路徑（偵測幀→開火背靠背，FOV 天然一致，不需 boost 閘）。
        未命中不盲打（101 病灶＝粗格中心可差半格）：記 cell_crop 素材（aim_cell＋放大圖；
        miss 另記 aim_core_miss label 當補新色系 profile 的直接 fixture 來源），回報退路。
        座標相對 region 由 detect_tracker_core 算好後 +region 原點映射回全幀。
        """
        if time.time() > deadline:
            return None, -1.0, "預算用盡"
        region = remote_aim.grid_cell_region(cell, cfg.remote_aim_zoom_margin_frac)
        if region is None:
            return None, -1.0, f"粗格 {cell} 無效"
        rx, ry, rw, rh = region
        frame = capture.grab()
        cell_crop = frame[ry:ry + rh, rx:rx + rw]
        # 【LOG 素材】裁格＋放大圖（非同步佇列，不卡開火路徑）
        self._hsnap_crop(frame, region, f"aim_cell_dir{tgt_dir}_{cell}")
        try:
            big = reentry_remote.render_zoom(
                frame, region, scale=cfg.reentry_remote_zoom_scale,
                cols=cfg.remote_aim_fine_grid, rows=cfg.remote_aim_fine_grid)
            self._hsnap(big, f"aim_cell_dir{tgt_dir}_{cell}_zoom")
        except Exception as exc:
            self.logger.warning("[%s] AIM 放大圖 log 失敗: %s", hid, exc)
        hit = vision.detect_tracker_core(
            cell_crop, cfg.tracker_core_profiles,
            min_area=cfg.tracker_core_min_area,
            max_area=cfg.tracker_core_max_area,
            ar_lo=cfg.tracker_core_ar_lo, ar_hi=cfg.tracker_core_ar_hi,
            extent_min=cfg.tracker_core_extent_min,
            border_margin=cfg.tracker_core_border_margin,
            border_dark_max=cfg.tracker_core_border_dark_max,
            border_dark_frac_min=cfg.tracker_core_border_dark_frac_min)
        if not hit:
            # 未覆蓋色系／框不在格內：另記 miss label（補色系 profile 的 fixture 來源）
            self._hsnap_crop(frame, region, f"aim_core_miss_dir{tgt_dir}_{cell}")
            self.logger.info("[%s] AIM 限縮偵測 None cell=%s（待補色系 profile）", hid, cell)
            return None, -1.0, f"限縮偵測未命中 {cell}（可能非綠色框），未開火——可 `手動` 或回編號重試"
        pos = (rx + hit[0], ry + hit[1])
        self.logger.info("[%s] AIM 限縮偵測命中 cell=%s -> %s (border=%.2f)",
                         hid, cell, pos, hit[3])
        return pos, float(hit[3]), ""

    def _aim_fire_and_verify(self, pos, pos_score, tgt_layer, tgt_dir, ctx, hid,
                             deadline, chat_base_crop):
        """開火 pos → 聊天驗證（grid 命中＋fine 細格命中共用尾段，harvest 101）。回 (ok, detail)。

        開火前基準 OCR → fire D3 → 記 fired 觀測 → 幀差閘輪詢驗證 → 窗口到期最終確認。
        confirmed 即 _remote_fire_success（俯仰歸位＋視角回正＋回挖礦）。
        """
        fire_frame = capture.grab()
        fire_path = self._hsnap(fire_frame, "aim_fire_%dx%d" % pos)
        if not self._fire_d3_at(*pos):
            return False, f"D3 冷卻尚餘 {self._d3_cooldown_remaining():.1f}s"
        self._record_target_observation(
            layer=tgt_layer, dir_idx=tgt_dir, pos=pos, score=pos_score,
            status="fired", source="remote_d3", snapshot_path=fire_path)
        common = game_data.common_ore_names()
        rare_names = game_data.rare_ore_names()
        chat_before = ocr.read_text_multi(chat_base_crop, cfg.tesseract_path)
        last_crop = chat_base_crop
        fired_at = time.time()
        while time.time() - fired_at < cfg.harvest_verify_window_s:
            if time.time() > deadline:
                break
            time.sleep(0.5)
            cur = capture.crop(capture.grab(), cfg.chat_region)
            if vision.frames_differ(last_crop, cur, cfg.chat_change_mean_diff):
                chat_after, confirmed, special = self._verify_chat_ocr(
                    cur, chat_before, common, rare_names, hid, "remote-aim")
                last_crop = cur
                if confirmed:
                    self._remote_fire_success(ctx, hid)
                    return True, "confirmed"
        # 窗口到期最終確認（H020 慣例）
        cur = capture.crop(capture.grab(), cfg.chat_region)
        _, confirmed, _ = self._verify_chat_ocr(
            cur, chat_before, common, rare_names, hid, "remote-aim-final")
        if confirmed:
            self._remote_fire_success(ctx, hid)
            return True, "confirmed(final)"
        return False, "verify 窗口內聊天未確認"

    def _detect_boost_present(self, frame) -> bool:
        """偵測 boost 瓶子是否在場（fresh、不限流）。FOV 一致性守門用（harvest 101 §4）。

        _boost_present 是節流快取（_tick_harvest 才更新；NEEDS_HUMAN 期間不更新→會過期），
        退路 FOV 守門需要「當下」狀態，故直接跑偵測（單尺度 ~56ms，不卡）。
        """
        t = self._templates.get("boost_active")
        if t is None or frame is None:
            return False
        return vision.find_template_edges(
            capture.crop(frame, cfg.boost_indicator_region), t,
            cfg.boost_edge_threshold, cfg.boost_buff_scales) is not None

    def _render_aim_zoom_image(self, frame, region, tgt_dir, cell, layer=0, scale=None):
        """裁 region 放大＋細網格 → 非同步存圖 → 等待落盤 → 回路徑（退路發圖用）。

        layer=0 首層（粗格放大）；>0 連鎖放大層（檔名帶 _zN 避免覆蓋）。落盤等待走
        remote_aim_snapshot_wait_s 預算；逾時回 None（呼叫端退回純文字通知）。
        """
        sc = scale if scale is not None else cfg.reentry_remote_zoom_scale
        zoom = reentry_remote.render_zoom(
            frame, region, scale=sc,
            cols=cfg.remote_aim_fine_grid, rows=cfg.remote_aim_fine_grid)
        suffix = "" if layer == 0 else f"_z{layer}"
        path = self._hsnap(zoom, f"aim_fine_dir{tgt_dir}_{cell}{suffix}")
        if path and self._wait_snapshot_ready(path):
            return path
        return None

    def _enter_aim_fine(self, ctx, cell, tgt_dir, tgt_layer, hid):
        """限縮偵測未命中 → 放大手選退路（harvest 101 §5 步驟 5）。

        裁玩家選的粗格放大＋細網格 → 發圖＋記 FOV 狀態（boost）。玩家回細格點擊／
        再放大／退／跳過。發圖時 boost 狀態錄為 fov_state0，玩家回細格開火前重讀對比，
        不一致即作廢重發（boost 到期/作用變 FOV → 框位移，§4）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        region = remote_aim.grid_cell_region(cell, cfg.remote_aim_zoom_margin_frac)
        if region is None:
            notify.send_message(token, ch, f"❌ 粗格 {cell} 無效，請重選或 `跳過`")
            return
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試或 `跳過`")
            return
        frame = capture.grab()
        path = self._render_aim_zoom_image(frame, region, tgt_dir, cell, layer=0)
        ctx.awaiting_fine = True
        ctx.fine_tgt_layer = tgt_layer
        ctx.fine_tgt_dir = tgt_dir
        ctx.fine_cell = cell
        ctx.zoom_region = region
        ctx.zoom_stack = []
        ctx.zoom_scale = cfg.reentry_remote_zoom_scale
        ctx.fov_state0 = self._detect_boost_present(frame)
        ctx.fov_rechecks = 0
        self.logger.info("[%s] AIM 限縮未命中 -> 放大手選 cell=%s dir=%d fov0=%s",
                         hid, cell, tgt_dir, ctx.fov_state0)
        caption = (f"🔍 沒自動抓到框（可能非綠色框），已放大 DIR{tgt_dir + 1} 的 {cell}——"
                   f"回細格（如 `B3`）打中心、`放大 B3` 再放大、`退` 退一層、`跳過`／`手動`")
        if path:
            notify.send_images_message(token, ch, caption, [path])
        else:
            notify.send_message(token, ch, caption + "（放大圖寫檔逾時，請依記憶回細格或 `手動`）")

    def _execute_aim_fine_fire(self, ctx, fine_cell, hid):
        """玩家回細格 → FOV 一致性守門 → 開火該細格中心 → 驗證（harvest 101 §5）。

        FOV 不一致（boost 變動）→ 重發當下放大圖請玩家重選（bounded by fov_recheck_max）。
        一致 → fine_cell_to_screen 算細格中心絕對座標 → _aim_fire_and_verify 開火驗證。
        未確認命中留在 awaiting_fine 讓玩家重選／跳過（不自動重試，同 grid 路徑慣例）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        pos = reentry_remote.fine_cell_to_screen(
            ctx.zoom_region, fine_cell,
            cols=cfg.remote_aim_fine_grid, rows=cfg.remote_aim_fine_grid)
        if pos is None:
            notify.send_message(token, ch, "❓ 細格代碼不合法（A1–F6）")
            return
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試")
            return
        frame = capture.grab()
        state1 = self._detect_boost_present(frame)
        if (not remote_aim.fov_state_consistent(ctx.fov_state0, state1)
                and ctx.fov_rechecks < cfg.remote_aim_fov_recheck_max):
            ctx.fov_state0 = state1
            ctx.fov_rechecks += 1
            path = self._render_aim_zoom_image(
                frame, ctx.zoom_region, ctx.fine_tgt_dir, ctx.fine_cell,
                layer=len(ctx.zoom_stack))
            self.logger.info("[%s] AIM FOV 不一致（->%s）-> 重發放大圖 #%d/%d",
                             hid, state1, ctx.fov_rechecks, cfg.remote_aim_fov_recheck_max)
            notify.send_images_message(
                token, ch, "📷 畫面變了（boost 變動），重發當下放大圖，請重選細格",
                [path] if path else [])
            return
        # FOV 一致（或重發達上限）：開火該細格中心
        deadline = time.time() + cfg.remote_aim_budget_s
        ready, detail = self._wait_for_d3_cooldown(deadline)
        if not ready:
            notify.send_message(token, ch, f"❌ {detail}")
            return
        chat_base_crop = capture.crop(capture.grab(), cfg.chat_region)
        ok, detail = self._aim_fire_and_verify(
            (int(pos[0]), int(pos[1])), -1.0, ctx.fine_tgt_layer, ctx.fine_tgt_dir,
            ctx, hid, deadline, chat_base_crop)
        if ok:
            self._aim_context = None           # confirmed（_aim_fire_and_verify 內已切 MINING）
        else:
            notify.send_message(
                token, ch,
                f"❌ 未確認命中（{detail}）。可重選細格、`放大 <細格>`、`退` 或 `跳過`")

    def _aim_magnify(self, ctx, cell, hid):
        """再放大（連鎖）：細格子區域變成新 zoom_region，重放大重發（逐層逼近，§5）。

        子格寬 <細網格數＝位圖極限（<1px/格）拒絕；scale 補償貼齊首層輸出寬。
        上一層 push 進 zoom_stack（退層用）；FOV 狀態重錄（新幀）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        sub = reentry_remote.fine_cell_subregion(
            ctx.zoom_region, cell,
            cols=cfg.remote_aim_fine_grid, rows=cfg.remote_aim_fine_grid)
        if sub is None:
            notify.send_message(token, ch, "❓ 細格代碼不合法（A1–F6）")
            return
        if sub[2] < cfg.remote_aim_fine_grid or sub[3] < cfg.remote_aim_fine_grid:
            notify.send_message(token, ch, "⚠ 已到放大極限（子格不足 1px），直接回細格點擊")
            return
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試")
            return
        frame = capture.grab()
        scale = reentry_remote.magnify_scale(
            sub[2], cfg.screen_w // 6 * cfg.reentry_remote_zoom_scale,
            cfg.reentry_remote_zoom_scale)
        ctx.zoom_stack.append({"region": ctx.zoom_region, "scale": ctx.zoom_scale})
        ctx.zoom_region = sub
        ctx.zoom_scale = scale
        ctx.fov_state0 = self._detect_boost_present(frame)
        path = self._render_aim_zoom_image(
            frame, sub, ctx.fine_tgt_dir, ctx.fine_cell,
            layer=len(ctx.zoom_stack), scale=scale)
        self.logger.info("[%s] AIM 再放大 %s (×%d, layer=%d)", hid, cell, scale, len(ctx.zoom_stack))
        notify.send_images_message(
            token, ch,
            f"🔍 已再放大 {cell}（×{scale}）。回細格（如 `B3`）打中心；可再 `放大 <細格>`、`退` 退一層",
            [path] if path else [])

    def _aim_back(self, ctx, hid):
        """退一層（§5）：pop zoom_stack 上一層重渲染重發；已在首層 → 回等格子。

        退層不轉向、不重掃、不動鏡頭——只回溯放大鏈。退到的那層用當下現場幀重渲染
        （畫面可能已漂移），FOV 狀態重錄。退過首層＝回等粗格（awaiting_fine 關閉）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if not ctx.zoom_stack:
            ctx.awaiting_fine = False
            ctx.zoom_region = ()
            ctx.zoom_scale = 0
            self.logger.info("[%s] AIM 退過首層 -> 回等格子", hid)
            notify.send_message(token, ch, "↩ 已退回等格子，重新 `方位 格子`（如 `5 C3`）或 `跳過`")
            return
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試")
            return
        layer = ctx.zoom_stack.pop()
        frame = capture.grab()
        ctx.zoom_region = layer["region"]
        ctx.zoom_scale = layer["scale"]
        ctx.fov_state0 = self._detect_boost_present(frame)
        path = self._render_aim_zoom_image(
            frame, ctx.zoom_region, ctx.fine_tgt_dir, ctx.fine_cell,
            layer=len(ctx.zoom_stack), scale=ctx.zoom_scale)
        self.logger.info("[%s] AIM 退一層 (layer=%d, ×%d)", hid, len(ctx.zoom_stack), ctx.zoom_scale)
        notify.send_images_message(
            token, ch,
            f"↩ 已退一層（×{ctx.zoom_scale}）。回細格（如 `B3`）；可再 `退` 或 `放大 <細格>`",
            [path] if path else [])

    def _remote_fire_success(self, ctx, hid):
        """遠端開火確認成功：通知＋俯仰歸位＋視角回正＋回挖礦。

        與 _harvest_resume_mining 共用 _resume_mining_tail（yaw 回正+MINING+init+W/D1 保險段）；
        姿態來源是 ctx（不是 self.harvest.net_rotations——兩個記帳來源勿混）。
        俯仰歸位條件與正常路徑不同：遠端 fire 可能動過 ctx 的層，一律 reset 回置中標準角
        （center_back_px>0 才動；未校準=0 絕不動——同 _pitch_restore_if_touched 的守門）。
        """
        from . import notify
        notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
                            f"🎉 [{hid}] 遠端瞄準採集成功！視角歸位、回挖礦")
        self.logger.info("[%s] AIM 採集成功 -> 歸位回 MINING", hid)
        if cfg.sweep_pitch_center_back_px > 0:   # 俯仰未校準（=0）絕不動；歸位冪等、多做無害
            self._pitch_drag_verified(
                f"[{hid}] AIM 收尾俯仰歸位",
                lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                       cfg.sweep_pitch_center_back_px))
        self._resume_mining_tail(ctx.pose_net_rotations)

    def _tick_harvest(self, frame):
        self.harvest.elapsed_s = time.time() - self._harvest_start
        hid = self.harvest.harvest_id          # 本輪編號；harvest 里程碑 log 前綴 [Hxxx]

        # ★ boost 守門（H026）：採集中 D5 一到期就補回，FOV 全程釘在「有 buff」狀態，
        #   sweep 座標/reference/開火重定位才自洽。剛補完＝這幀已過期，下個 tick 重抓。
        if self._harvest_boost_guard(frame):
            return

        _cr = cfg.chat_region
        _excl = [(_cr.x, _cr.y, _cr.x + _cr.w, _cr.y + _cr.h)]
        _ref = getattr(self, '_pre_scan_ref', None)

        # ---- 階段一：全方位掃描（找追蹤框；_target_marker 尚未設定時執行）----
        if self._target_marker is None:
            # ★ 重掃路徑先聽聊天（晚到確認）：誤判 RESWEEP 後，成功行常在 D2 重掃描/
            #   守門 settle 期間才抵達——先於重掃檢查，接得住就不必白掃一輪（首掃未開火
            #   時 _late_chat_confirm 直接 False、零成本）
            if self._late_chat_confirm(frame, hid, "pre-sweep"):
                return
            # sweep 階段超時（sweep 固定 8 方位約 19s，30s 已是 1.5x 餘裕）
            if self.harvest.elapsed_s > cfg.sweep_timeout_s:
                if self.harvest.extra_targets > 0:
                    # 續採途中超時（incident 072）：bonus 框可能已淡出/跑位出視野，
                    # episode 已有成功入帳 → 正常收尾回 MINING，不交人工
                    self.logger.info("[%s] 續採 sweep 超時（bonus 框已淡出）-> 正常收尾回 MINING (t=%.1f)",
                                     hid, self.harvest.elapsed_s)
                    self._harvest_resume_mining()
                    return
                self.logger.info("[%s] sweep 超時 -> 歷史目標復原/人工 (t=%.1f)", hid, self.harvest.elapsed_s)
                if self._recover_historical_target(_excl):
                    return
                self._harvest_giveup("全方位掃描超時，請手動處理")
                return
            self.last_action = "全方位掃描（8方位）"
            self._target_marker, had_candidates = self._sweep_for_tracker(_excl, _ref)
            if self._target_marker is None:
                # ★ 掃完全空再聽一次聊天（晚到確認）：sweep 一輪數秒，成功行可能這期間
                #   才抵達；frame 已舊 → 重抓當下幀
                if self._late_chat_confirm(capture.grab(), hid, "post-sweep"):
                    return
                # 依「掃描過程是否看過穩定框」分流（H019）：
                # - 全 8 方位都沒看到 → 人工（偵測已準；再掃也不會更好，2026-06-29 決策）。
                #   先轉回原視角，人工可一眼判斷「礦已被挖走」的好假警報。
                # - 看到過但轉回後 verify 失敗 → 框確實存在（D5 到期 FOV 位移把它推進畫面
                #   邊緣排除帶/短暫遮擋）→ 重掃一次，在新 FOV 下重新定位（上限 1 次）。
                verdict = harvester.decide_sweep_failure(
                    had_candidates, self.harvest.verify_fail_resweeps,
                    pitch_layers_left=len(self.harvest.pitch_layers_left),
                    extra_mode=self.harvest.extra_targets > 0)
                if verdict == "RESWEEP":
                    self.harvest.verify_fail_resweeps += 1
                    fov_shifted = getattr(self, "_sweep_fov_shifted", False)
                    self.logger.info("[%s] sweep 看過穩定框但 verify 失敗（FOV 位移/邊緣裁切）"
                                     "-> 重掃一次 (%d/1)%s", hid, self.harvest.verify_fail_resweeps,
                                     "（本輪掃描中補過 D5，重拍 ref）" if fov_shifted else "")
                    self._reharvest_sweep(refresh_ref=fov_shifted)
                    return
                if verdict == "EXIT_SUCCESS":
                    # 續採途中 sweep 全空/預算用盡（incident 072）：bonus 框已淡出，
                    # episode 已有成功入帳 → 正常收尾回 MINING，不交人工/換層
                    self.logger.info("[%s] 續採 sweep 全空（bonus 框已淡出）-> 正常收尾回 MINING", hid)
                    self._harvest_resume_mining()
                    return
                if verdict == "NEXT_LAYER":
                    # yaw 只改 x 不改 y（H026）：標準層看不到的框，換俯仰層才有機會。
                    # 只在本來就要 giveup 的案例多花 ~30-40s，換少一次遠端介入。
                    self.last_action = "俯仰層掃描"
                    if self._pitch_layer_transition():
                        return          # 下個 tick 在新層重跑 8 方位（sweep 計時已重置）
                    # 層全部被吃/重置中 → 落到 giveup
                self.logger.info("[%s] sweep 未找到追蹤框（俯仰層剩 %d）-> 歷史目標復原/人工",
                                 hid, len(self.harvest.pitch_layers_left))
                if self._recover_historical_target(_excl):
                    return
                self._harvest_giveup("全方位掃描未找到追蹤框（礦可能已被挖走），請手動處理")
                return
            # ★ 聊天基準是 episode 級（2026-07-04 起在進場時拍、RESWEEP 不作廢，見 _on_enter）：
            #   舊版在此每輪 sweep 重取——誤判失敗 RESWEEP 後重取會把晚到的成功行吃進新基準，
            #   差分從此看不見（H015 對策只護到同輪 D3 嘗試、護不到跨 RESWEEP）。
            #   這裡只防禦性補拍（理論上進 HARVESTING 必已拍）。
            # ★ 基準只截「像素」不 OCR（H026 對策）：3-pass OCR ~10s 若卡在確認→開火之間，
            #   D5 到期的 FOV 位移正好落在這空窗（H015 幀齡 12s、H026 卡 12s 期間到期都是它）。
            #   文字版基準延到「開火之後」才 OCR（見 stage 2）——裁圖已凍結、何時 OCR 結果相同，
            #   開火不必等它。確認→開火從 ~13s 縮到 ~1.5s。
            base_frame = capture.grab()
            if self._chat_baseline is None and getattr(self, "_chat_baseline_crop", None) is None:
                self._chat_baseline_crop = capture.crop(base_frame, cfg.chat_region)
                self._chat_last_crop = self._chat_baseline_crop
            self._hsnap_crop(base_frame, cfg.chat_region, "d3_chat_before")
            # ★ sweep 完成：重置計時器，D3 階段從 0 開始算（基準 OCR 的 ~10s 不吃 D3 預算）
            # （否則 sweep 吃掉全部預算，D3 永遠超時——對應 2026-06-27 那次「判斷錯誤」）
            self._harvest_start = time.time()
            self.harvest.elapsed_s = 0.0
            self.logger.info("[%s] sweep 完成 -> 進入 D3 階段 (target=%s)", hid, self._target_marker)
            return  # 讓主迴圈抓新 frame 再進 D3

        # ---- 階段二：D3 開火 + 驗證（sweep 完成後才計時）----
        if self.harvest.elapsed_s > cfg.harvest_verify_timeout_s:
            # ★ 交人工前最後聽一次聊天（晚到確認）：poll 的 final-check 之後、走到這裡
            #   之間仍可能有成功行抵達
            if self._late_chat_confirm(frame, hid, "d3-timeout"):
                return
            self.logger.info("[%s] D3 階段超時 -> 人工 (t=%.1f)", hid, self.harvest.elapsed_s)
            self._harvest_giveup("稀有礦採集失敗（D3 階段超時），請手動處理", face_tracker=True)
            return

        # 看到追蹤框 → 裝 D3、直接點選它的位置（不需精準置中；右鍵微調難控）
        cx, cy = self._target_marker
        self.last_action = "D3 採集"
        # 反轉策略：比對聊天「has found X」，X 不在「低稀有度排除清單」(common_ore_names) → 稀有礦。
        # chat 基準（chat_before）在進場時已截（episode 級、跨嘗試與 RESWEEP 共用；
        # H015 對策 + 2026-07-04 延伸）。
        common = game_data.common_ore_names()
        if self._chat_baseline is None and getattr(self, "_chat_baseline_crop", None) is None:
            # 防禦：sweep 完成必已截基準裁圖，缺了就補（截圖瞬間完成、不擋開火）
            bf = capture.grab()
            self._chat_baseline_crop = capture.crop(bf, cfg.chat_region)
            self._chat_last_crop = self._chat_baseline_crop

        # ★ 開火前重定位（H015 第一槍對策）：D5 boost 到期會收縮 FOV，畫面上所有座標整批位移
        #   （H015：sweep 座標 (1564,433) 到實際點擊時已是不同牆面 → 點空牆 miss）。開火永遠用
        #   「當下」幀重新偵測的座標；找不到＝框已消失/跑位出視野 → 立即重掃，不浪費一發。
        cooldown_left = self._d3_cooldown_remaining()
        if cooldown_left > 0:
            self.last_action = f"D3 冷卻 {cooldown_left:.1f}s"
            self.log_harvest.info("[%s] D3 cooldown %.2fs; defer refind/fire",
                                  hid, cooldown_left)
            return
        aim_frame = capture.grab()
        refind = self._find_tracker(
            aim_frame, _excl, reference_bgr=_ref, with_score=True)
        if refind is None:
            self.logger.info("[%s] 開火前重定位失敗（框已消失/FOV 變動）-> 重新 D2 掃描＋全方位重掃", hid)
            self._reharvest_sweep()
            return
        if abs(refind[0] - cx) >= 8 or abs(refind[1] - cy) >= 8:
            self.log_harvest.info("[%s] 開火前重定位: (%d,%d) -> (%d,%d)（FOV/視角位移已吸收）",
                                  hid, cx, cy, refind[0], refind[1])
        cx, cy, refind_score = refind
        self._target_marker = (cx, cy)
        self.log_harvest.info("[%s] 採集: 追蹤框當下位置 (%d,%d) -> D3 點選 (attempt=%d)",
                              hid, cx, cy, self.harvest.d3_attempts + 1)
        fire_path = self._hsnap(
            aim_frame, "d3_fire_dir%d_%dx%d" %
            (self.harvest.net_rotations % 8, cx, cy))
        if not self._fire_d3_at(cx, cy):
            return
        self._record_target_observation(
            layer=self.harvest.pitch_layer,
            dir_idx=self.harvest.net_rotations % 8,
            pos=(cx, cy), score=refind_score, status="fired",
            source="normal_d3", snapshot_path=fire_path)

        # ★ 輪詢驗證（H015 第二槍對策）：實機追蹤框是擊中後 2~10s 才消失、聊天成功行更晚到
        #   （且聊天無新訊息 ~15s 會整個淡出、唯有新訊息會讓它重新顯示）→ 舊「固定等 0.5s 抓
        #   一幀判生死」必然踩在空窗上（gone=False + no-new → RETRY → 超時誤交人工，礦其實採到了）。
        #   窗口內每輪：框未消失則再查一次；聊天裁圖像素有變（frames_differ 省 OCR 閘，滿版文字
        #   3-pass OCR ~10s 不能每輪跑）才重 OCR 差分。confirmed 隨時早退。
        #   確認信號不變：任一前處理 pass 內「稀有礦 has-found 數量增加，或底部新出現稀有礦行」
        #   （底部新行是抗捲動主信號；逐 pass 自洽比對，H014 對策），或特殊變體（Ionized/Spectral，
        #   綁 found 行＋排除清單）。
        rare_names = game_data.rare_ore_names()  # fuzzy 兜底詞彙表（H020 對策；檔缺→空＝停用）
        fire_t = time.time()
        # ★ 基準 OCR 移到「開火之後」跑（H026 對策，見 stage 1）：裁圖在 sweep 完成時已凍結，
        #   開火後這 ~10s 正好蓋掉「等命中/框淡出/聊天行抵達」的死時間。驗證窗口從 OCR 完成
        #   起算（fired_at）——否則 10s OCR 一結束窗口已過期，輪詢一次都輪不到。
        #   RETRY 第二槍時基準已是文字（跨嘗試共用，H015 對策不變）→ 不重跑。
        if self._chat_baseline is None:
            t0 = time.time()
            self._chat_baseline = ocr.read_text_multi(self._chat_baseline_crop, cfg.tesseract_path)
            self.log_harvest.info("[%s] 基準 OCR（開火後補跑）%.1fs", hid, time.time() - t0)
            self._log_rapid_diag(hid, "baseline")
            # episode 帳本起點：之後每次 verify OCR 鏈式對齊、累積新增行（跨 RESWEEP 存活）
            self._chat_ledger = ocr.ChatLedger(self._chat_baseline)
        chat_before = self._chat_baseline
        rare_before = [ocr.count_rare_found(t, common, cfg.found_keywords) for t in chat_before]
        fired_at = time.time()
        gone = confirmed = special = False
        first_poll = True
        after = None
        chat_after = chat_before
        roi_center = (cx, cy)   # ROI 快路徑起點＝開火座標；命中即漂移吸收，miss 才落全幀後備
        while True:
            if not self._running or self.paused:
                # 協作式中斷（HANDOFF §7 已知限制）：F12/Ctrl+Q/Q 期間不再困在
                # 最長 ~8s 輪詢＋~10s final-check 裡；鍵盤已由 _pause/_quit 清掉，
                # 直接棄本輪驗證，run() 的暫停/結束分支接手。
                self.log_harvest.info("[%s] verify 輪詢中斷（%s）", hid,
                                      "quit" if not self._running else "pause")
                return
            after = capture.grab()
            if self._harvest_boost_guard(after):   # H026：到期即補，gone 檢查才在正確 FOV 下跑
                after = capture.grab()
            if first_poll:
                self._hsnap(after, "d3_after")   # 首輪全幀診斷截圖（與 d3_fire 對比，事後追蹤是否命中）
                first_poll = False
            if not gone:
                # ★ ROI 快路徑（Task 1.1/1.2）：開火座標已知，全幀掃描（~2s）浪費九成——
                #   只搜 verify_roi_radius_px 內（~0.3s）。miss 不等於 gone（H026：FOV 位移
                #   可能超出 ROI）→ 全幀後備確認一次，維持與舊版「全幀每輪」等價的判定。
                hit = self._find_tracker_near(after, roi_center, _excl, reference_bgr=_ref)
                if hit is not None:
                    roi_center = hit[:2]           # 微漂移吸收，下一輪仍走快路徑
                else:
                    full = self._find_tracker(after, _excl, reference_bgr=_ref)
                    if full is not None:
                        roi_center = full           # 大漂移：更新中心回快路徑
                    gone = full is None
            cur_crop = capture.crop(after, cfg.chat_region)
            mean_diff = vision.frames_mean_diff(self._chat_last_crop, cur_crop)
            # 每輪都留一行 DEBUG（H020 事後排錯需求）：沒觸發 OCR 的輪也要能回答
            # 「當時像素差多少、離門檻多遠」
            self.log_harvest.debug("[%s] verify poll t=%.1f gone=%s chat_diff=%s thr=%.1f",
                                   hid, time.time() - fired_at, gone,
                                   "None" if mean_diff is None else f"{mean_diff:.2f}",
                                   cfg.chat_change_mean_diff)
            if mean_diff is None or mean_diff > cfg.chat_change_mean_diff:
                chat_after, confirmed, special = self._verify_chat_ocr(
                    cur_crop, chat_before, common, rare_names, hid,
                    f"poll@{time.time() - fired_at:.1f}s diff={mean_diff}")
                self._chat_last_crop = cur_crop
                confirmed = confirmed or special
            verdict = harvester.decide_verify_poll(gone, confirmed, time.time() - fired_at,
                                                   cfg.harvest_verify_window_s)
            if verdict != "POLL":
                break
            time.sleep(cfg.harvest_verify_poll_interval_s)
        # ★ 窗口到期最終確認（H020 對策）：幀差閘可能在「聊天淡入中」就觸發 OCR 並把
        #   _chat_last_crop 更新成與最終畫面幾乎相同的幀 → 之後像素「不再有變」、不再
        #   重 OCR，而那次 OCR 讀的是半透明/未定稿文字（必歪）。且一次 3-pass OCR
        #   實測 7~11s ≈ 整個 8s 窗口 → 窗口內只有一次機會、失敗即出局。
        #   判 RESWEEP/RETRY 前強制對最新幀再 OCR 一次（只在失敗路徑多花 ~10s，
        #   換掉「其實採到了卻誤交人工」——H020 的直接死因）。
        if verdict != "SUCCESS" and not confirmed:
            after = capture.grab()
            chat_after, confirmed, special = self._verify_chat_ocr(
                capture.crop(after, cfg.chat_region), chat_before, common, rare_names,
                hid, "final-check")
            confirmed = confirmed or special
            if confirmed:
                verdict = "SUCCESS"
                self.log_harvest.info("[%s] 窗口到期最終確認救回：聊天確認已採到（原判 %s）",
                                      hid, "RESWEEP" if gone else "RETRY")
        rare_after = [ocr.count_rare_found(t, common, cfg.found_keywords) for t in chat_after]
        chat_after_path = self._hsnap_crop(after, cfg.chat_region, "d3_chat_after")
        # 一律落盤（檔名帶 verdict）：失敗查假陰性（H020 需求）、成功查誤判成功
        # （RapidOCR 觀察期裁決素材，2026-07-04）
        self._dump_chat_ocr(hid, chat_before, chat_after, verdict)
        # 成功只認「新增的稀有礦名/特殊階」（confirmed）；框消失但未確認 = 礦被掃描到期/雷達拿走 → 重掃。
        # （舊邏輯 `gone or confirmed` 把 gone 當成功；2026-06-29 trace 20260629_022126：
        #  真框疊角色身上 D3 打不到、D2 掃描到期框自己淡掉 → gone=True 誤報成功，稀有礦名 5→5 沒變。）
        self.log_harvest.info("[%s] verify harvest: gone=%s rare %s->%s %s special=%s poll=%.1fs 距開火=%.1fs -> %s",
                         hid, gone, rare_before, rare_after,
                         "NEW" if confirmed else "no-new", special,
                         time.time() - fired_at, time.time() - fire_t, verdict)
        if verdict == "SUCCESS":
            self._harvest_success(hid, after, chat_before, chat_after,
                                  confirmed=confirmed, gone=gone, special=special,
                                  rare_before=rare_before, rare_after=rare_after,
                                  chat_after_path=chat_after_path)
        elif verdict == "RESWEEP":
            # 框消失但聊天無 has found → 多半是 D2 掃描到期框自己淡掉（或雷達搶採），原地再射也射不到 → 立即重掃。
            self._hsnap(after, "d3_gone_unconfirmed")  # 關鍵截圖：框沒了卻沒採到（掃描到期/被搶）
            self.logger.info("[%s] 採集: 追蹤框消失但聊天未確認（掃描到期/被雷達搶採）-> 重新 D2 掃描＋全方位重掃", hid)
            self._reharvest_sweep()
        else:  # RETRY：框還在、D3 沒打中 → 原地重試，連續未命中達上限才重掃
            self._hsnap(after, "d3_miss_%d" % (self.harvest.d3_attempts + 1))  # 關鍵截圖：未命中
            self.harvest.d3_attempts += 1
            if self.harvest.d3_attempts >= cfg.max_harvest_attempts:
                self.logger.info("[%s] 採集: D3 連 %d 次未命中 -> 重新 D2 掃描＋全方位重掃",
                                 hid, self.harvest.d3_attempts)
                self._reharvest_sweep()
            else:
                self.log_harvest.info("[%s] 採集: D3 未命中 (attempt %d/%d rare %s->%s)，下次繼續",
                                 hid, self.harvest.d3_attempts, cfg.max_harvest_attempts,
                                 rare_before, rare_after)

    def _harvest_success(self, hid, after_frame, chat_before, chat_after, *,
                         confirmed, gone, special, rare_before, rare_after,
                         chat_after_path=None):
        """採集成功收尾（通知標注/統計/聚焦/回正/續挖）。

        poll 驗證路徑與晚到確認路徑（_late_chat_confirm）共用：晚到路徑的確認行可能
        已被後續訊息推到「對 episode 基準差分抓不到」的位置，故通知行以差分抽取結果
        聯集 episode 帳本的稀有行（帳本在入帳當下留了原文）。
        """
        common = game_data.common_ore_names()
        rare_names = game_data.rare_ore_names()
        # 抽出 D3 後聊天「新增的 has found 行」原文，給 Discord 通知秀實際採到什麼
        # （rare_before/after 只是數字，使用者難判斷是哪顆 礦）。
        # ★ 基準淡出（H064）時集合差集會把「重顯示的整段舊歷史」全列成本次新增
        #   → 通知謊報採到五顆。基準沒有 has-found 歷史時不用差集，只信帳本入帳的行。
        new_lines = (ocr.extract_new_found_lines_multi(chat_before, chat_after,
                                                      cfg.found_keywords)
                     if ocr.baseline_saw_found_history(chat_before, cfg.found_keywords)
                     else [])
        ledger = getattr(self, "_chat_ledger", None)
        if ledger is not None:
            seen_lg = {l.lower() for l in new_lines}
            for line in ledger.rare_lines:
                if line.lower() not in seen_lg:
                    new_lines.append(line)
        # 三態分類標注：白名單高階→附階級；未知→標注請人核對（OCR 誤讀或遊戲更新
        # 的清單漂移自己浮出來，不靜默失效）；common（低階被動 find 混入）→原樣。
        annotated, has_unknown = [], False
        for line in new_lines:
            kind, info = game_data.classify_found_ore(
                ocr.found_ore_name(line, cfg.found_keywords) or "")
            if kind == "rare":
                annotated.append(f"{line} 〔{info['tier']} 1/{info['rarity']:,}〕")
            elif kind == "rare_fuzzy":
                # 近失拼字兜底（H033：RapidOCR 把 Essentium 讀成 Essentlum，i/l 同形）
                # ——標 ≈白名單礦名＋相似度讓人工可核對，不再誤標「⚠ 未知礦名」
                annotated.append(f"{line} 〔≈{info['ore']} {info['fuzzy_ratio']:.2f}，"
                                 f"{info['tier']} 1/{info['rarity']:,}〕")
            elif kind == "unknown":
                annotated.append(f"{line} 〔⚠ 未知礦名〕")
                has_unknown = True
            else:
                annotated.append(line)
        # fuzzy 命中行（H020：關鍵字被 OCR 讀歪 → 精確抽取抓不到）另列，
        # 標注「≈匹配到的白名單礦名＋相似度」讓人工可核對是不是誤配
        seen = {l.lower() for l in new_lines}
        fuzzy_pairs = (zip(chat_before, chat_after)
                       if ocr.baseline_saw_found_history(chat_before, cfg.found_keywords)
                       else [])           # H064：同上，淡出基準的差集不可信
        for b, a in fuzzy_pairs:
            for line, ore_name, ratio in ocr.new_fuzzy_rare_lines(b, a, common, rare_names):
                if line.lower() in seen:
                    continue
                seen.add(line.lower())
                kind, info = game_data.classify_found_ore(ore_name.lower())
                tier = (f"，{info['tier']} 1/{info['rarity']:,}"
                        if kind in ("rare", "rare_fuzzy") and info else "")
                annotated.append(f"{line} 〔≈{ore_name} {ratio:.2f}{tier}〕")
        if has_unknown:
            annotated.append("⚠ 有未知礦名：可能 OCR 誤讀或遊戲更新，"
                             "請核對；可跑 python -m miningbot.fetch_ores 同步清單")
        new_lines = annotated
        if new_lines:
            self.log_harvest.info("[%s] 採集新增聊天行: %s", hid, new_lines)
        self.log.log("HARVEST_SUCCESS", harvest_id=hid, confirmed=confirmed, tracker_gone=gone,
                     special=special, rare_before=rare_before, rare_after=rare_after,
                     new_found_lines=new_lines, image_path=chat_after_path)
        self.stats["rares"] += 1
        self.last_action = "採集成功！" + ("（特殊階！）" if special else "")
        self._hsnap(after_frame, "harvest_success" + ("_special" if special else ""))
        # 採集全程數十秒（sweep ~19s + 多次 D3 嘗試），期間焦點可能被搶走
        # （HUD 從隱藏重顯、系統通知、使用者點別視窗）。後續 restore_view +
        # init_mining_sequence 會送視角鍵 / W / D1 / Shift，必須先確認焦點在
        # Roblox，否則全被 GUI 視窗吃掉——「偶爾挖到稀有礦回正不會動」的根因。
        # 聚焦失敗 → 走 _harvest_giveup（會先轉回視角再交人工，使用者可一眼判斷）。
        if not self._focus_roblox():
            self.logger.warning("採集成功但無法重新聚焦 Roblox -> 交人工（已採到，僅回正+續挖失敗）")
            self._harvest_giveup("採集成功但無法重新聚焦 Roblox，請處理後按 Q")
            return
        self.logger.info("採集成功（gone=%s rare=%s->%s special=%s）net=%d -> 等 pickup 動畫後轉回原方位",
                         gone, rare_before, rare_after, special, self.harvest.net_rotations)
        # 採集後遊戲有 pickup 動畫（1-2s），期間送鍵被吃掉（keyDown/center/D1 皆實測中招）。
        # 舊版 restore_view 的旋轉鍵就在這窗口內送出＝「視角偶爾停在 45° 斜角」的直接根因
        # （2026-07-05）→ 動畫等待挪到 restore 之前，回轉/init 都在動畫結束後跑。
        self._log_w_state("採集成功→動畫等待前")
        # ★ 續採檢查（incident 072）：同一 chill episode 可能同畫面有第二顆礦的追蹤框。
        #   剛採掉的框 2~10s 才淡出 → 距離閘擋殘影（decide_post_success）。雙幀穩定同 sweep 慣例。
        time.sleep(1.0)   # 等 pickup 動畫（原本就有，挪到 recheck 前——也讓已採框多淡 1s）
        _cr = cfg.chat_region
        _excl = [(_cr.x, _cr.y, _cr.x + _cr.w, _cr.y + _cr.h)]
        _ref = getattr(self, '_pre_scan_ref', None)
        recheck = None
        r1 = self._find_tracker(capture.grab(), _excl, reference_bgr=_ref)
        if r1 is not None:
            time.sleep(0.08)
            r2 = self._find_tracker(capture.grab(), _excl, reference_bgr=_ref)
            if r2 is not None and abs(r1[0] - r2[0]) < 8 and abs(r1[1] - r2[1]) < 8:
                recheck = r2
        verdict2 = harvester.decide_post_success(
            recheck, self._target_marker, self.harvest.extra_targets,
            cfg.harvest_extra_targets_max, cfg.harvest_extra_target_min_dist_px)
        if verdict2 == "CONTINUE":
            self.harvest.extra_targets += 1
            self.harvest.d3_attempts = 0
            self.harvest.verify_fail_resweeps = 0
            self.logger.info("[%s] 採集成功但畫面仍有另一追蹤框 (%d,%d) -> 續採（第 %d 顆額外目標）",
                             hid, recheck[0], recheck[1], self.harvest.extra_targets)
            self.last_action = "續採第%d顆" % (self.harvest.extra_targets + 1)
            # 重開聊天差分基準：上一顆的成功行已確認入帳，續採的差分要以「現在」為起點。
            # （「episode 基準不作廢」規則護的是誤判失敗時晚到的成功行；確認成功後重取語意正確，
            #   否則上一顆的成功行會讓第二發 D3 未命中也被判 confirmed＝假成功。）
            fresh = capture.grab()
            self._chat_baseline = None
            self._chat_baseline_crop = capture.crop(fresh, cfg.chat_region)
            self._chat_last_crop = self._chat_baseline_crop
            self._chat_ledger = None   # 下次開火後的基準 OCR 會重建
            self._reharvest_sweep()    # 重新 D2 掃描（掃描可能將到期）；保 _pre_scan_ref、重置計時器
            return                     # 留在 HARVESTING；net_rotations 繼續累計，最後一次轉回
        self._harvest_resume_mining()

    def _harvest_resume_mining(self):
        """採集成功後的視角回正 + 恢復挖礦（從 _harvest_success 抽出，incident 072 續採共用）。

        含俯仰歸位（動過才回）、yaw 回正、切 MINING、init_mining_sequence、鎬子/W 保險段。
        pickup 動畫等待（time.sleep 1.0）由呼叫端在 recheck 前先跑過，這裡不重睡。
        """
        self._pitch_restore_if_touched()  # 先俯仰歸位（動過才回置中標準角）、再 yaw 回正
        self._resume_mining_tail(self.harvest.net_rotations)

    def _resume_mining_tail(self, net_rotations: int):
        """採集成功（正常/遠端 fire）後的共用收尾：yaw 回正→切 MINING→init→鎬子/W 保險段。

        從 _harvest_resume_mining 抽出，讓遠端 fire 收尾（姿態在 ctx.pose_net_rotations）
        與正常採集收尾（姿態在 self.harvest.net_rotations）共用同一份，不複製兩份維護。
        俯仰歸位由呼叫端先跑（兩路徑條件不同：正常路徑用 _pitch_restore_if_touched，
        遠端 fire 用 _pitch_drag_verified 直跑）。pickup 動畫等待也由呼叫端先跑。
        """
        harvester.restore_view(net_rotations, rotate=self._rotate_verified)
        # H051：重置 pending（RESET_WAIT/MINING 因 chill 搶先採集）時採到了也不回
        # MINING——礦坑倒數中/已清場，init_mining 會對著重置後畫面空挖且 _on_enter(MINING)
        # 會清 _mine_resetting 旗標、重置回礦鏈斷頭。回 RESET_WAIT 等 reset_complete。
        if self._mine_resetting:
            self.logger.info("採集收尾但礦坑重置 pending -> 回 RESET_WAIT（不 init 挖礦）")
            self.state = State.RESET_WAIT
            self._on_enter(State.RESET_WAIT, capture.grab())
            return
        self.state = State.MINING
        self._post_harvest_watch = 3     # 進入 MINING 後前 3 tick 記錄 W 狀態
        miner.init_mining_sequence(log=self.logger.info, rotate=self._rotate_verified)
        # init 已在動畫後執行；仍保留 release→置中→鎬子→re-press 保險：動畫偶爾拖過 1s，
        # 且遊戲會認為 W「已按著」不觸發移動（log 實測 W=True 但角色不動）。
        self._log_w_state("採集成功→init 後")
        ic.key_up("w"); ic.mouse_up()
        time.sleep(0.15)
        ic.center_crosshair()            # 重新雙擊 Shift 置中（遊戲已 settle）
        time.sleep(0.2)
        # 再確認鎬子：pickup 動畫拖過 1s 時 init 期的切換仍可能被吃，導致 D3 沒切回 D1
        # → 按住 W 卻拿著 D3 無法前進（使用者實機回報）。settle 後條件式補按 D1。
        if miner.ensure_pickaxe():
            self.logger.info("採集後補按 D1 切回鎬子（init 期切換被吃）")
        ic.key_down("w"); ic.mouse_down()
        self._log_w_state("採集成功→置中+鎬子+W重按後")

    def _late_chat_confirm(self, frame, hid, why) -> bool:
        """失敗/重掃路徑上聽聊天（2026-07-04 H032 延伸對策）：晚到成功行抵達 → 直接成功收尾。

        誤判失敗 → RESWEEP 期間（D2 重掃描/D5 守門 settle/8 方位重掃）成功行才抵達的情境，
        舊版這段路上沒人在看聊天、之後該行又被一般礦行推到捲出裁圖 → 白掃一輪誤交人工。
        對策：失敗路徑的關鍵決策點先跑既有 frames_mean_diff 便宜閘（聊天是螢幕覆蓋層，
        不受旋轉/FOV 影響），像素有變才 OCR——episode 帳本鏈式對齊接住晚到行。
        只在開過火後有意義（基準 OCR 前不可能有自己的成功行）→ 未開火直接 False。
        回 True 時已走完成功收尾，呼叫端應立即 return。
        """
        if self._chat_baseline is None or getattr(self, "_chat_ledger", None) is None:
            return False
        cur = capture.crop(frame, cfg.chat_region)
        mean_diff = vision.frames_mean_diff(self._chat_last_crop, cur)
        if mean_diff is not None and mean_diff <= cfg.chat_change_mean_diff:
            return False
        common = game_data.common_ore_names()
        chat_after, confirmed, special = self._verify_chat_ocr(
            cur, self._chat_baseline, common, game_data.rare_ore_names(), hid,
            f"late@{why}")
        self._chat_last_crop = cur
        if not (confirmed or special):
            return False
        self.logger.info("[%s] 晚到確認（%s）：聊天確認已採到（誤判失敗轉成功）", hid, why)
        self._dump_chat_ocr(hid, self._chat_baseline, chat_after, "late-success")
        rare_before = [ocr.count_rare_found(t, common, cfg.found_keywords)
                       for t in self._chat_baseline]
        rare_after = [ocr.count_rare_found(t, common, cfg.found_keywords) for t in chat_after]
        self._harvest_success(
            hid, frame, self._chat_baseline, chat_after,
            confirmed=True, gone=True, special=special,
            rare_before=rare_before, rare_after=rare_after,
            chat_after_path=self._hsnap_crop(frame, cfg.chat_region, "late_chat_after"))
        return True

    # ---- REENTRY：重置後自動回礦 --------------------------------------------
    # ---- Discord 遠端回礦（2026-07-12 spec）----------------------------------
    # 輪詢執行緒只寫 _pending_reentry（_handle_reentry_reply）；開場鏈／指令執行／寫檔
    # 全在主迴圈（_tick_reentry_remote 及其 helpers）。比照 _pending_aim／_tick_remote_aim。

    def _tick_reentry_remote(self, frame):
        """REENTRY 遠端模式主迴圈（2026-07-12 spec）：首 tick 開場，之後消費 pending 指令。

        等待回覆無硬超時（使用者延遲以分鐘計）；防踢由 run() 主迴圈的 antiafk 分支保活。
        """
        if self._mine_resetting:
            self._rr_abort_reset(frame)
            return
        if self._rr_ctx is None:
            self._rr_busy = True
            try:
                self._rr_open_episode()
            finally:
                self._rr_busy = False
            return
        # H044 開場探測：上一擊未傳送（first_ts 非 0）→ 依節奏重探/放棄。使用者指令優先
        #（重骰/跳過照常走 pending 消費；重骰失敗會回到這裡繼續計預算）。
        if self._rr_open_first_ts and self._pending_reentry is None:
            act = reentry_remote.plan_open_retry(
                self._rr_open_first_ts, time.time(),
                cfg.reentry_open_retry_wait_s, cfg.reentry_open_budget_s,
                self._rr_open_last_ts)
            if act == "probe":
                self._rr_busy = True
                try:
                    self._rr_open_episode(reroll=True)
                finally:
                    self._rr_busy = False
                return
            if act == "give_up":
                self._rr_open_first_ts = 0.0
                snap = capture.grab()
                path = self._rr_sync_write(
                    snap, f"reentry_ep{self._rr_ctx.episode_id}_open_nochange")
                self._rr_notify(
                    f"⚠ 回礦 #{self._rr_ctx.episode_id}：開場探了 "
                    f"{int(cfg.reentry_open_budget_s)}s 仍未全過驗證。\n"
                    f"最後一探：{reentry_remote.format_gate_readings(*self._rr_last_probe)}\n"
                    "（depth=NNNm/讀不到＋pitch 有動＝虛空；pitch 0.00/0.0000＝凍結；"
                    "Surface＋容量未歸零＝重置未完成或按鈕失效）。回 `重骰` 重試或 `跳過`",
                    image_paths=[path])
                return
            # act == "wait" → 落到下方等待分支更新 HUD
        if self._pending_reentry is not None:
            (raw, reply), self._pending_reentry = self._pending_reentry, None
            reentry_remote.log_command(self._rr_ctx, raw, reply, time.time())
            self._rr_busy = True
            try:
                self._rr_execute(reply)
            finally:
                self._rr_busy = False
        else:
            # 等待指令：更新 HUD 顯示（last_action 進 status_hud 的「動作」欄）
            ctx = self._rr_ctx
            mins = int((time.time() - ctx.created_at) // 60)
            if self._rr_open_first_ts:
                self.last_action = f"回礦開場探測中 #{ctx.episode_id}（畫面可能凍結，已 {mins} 分）"
            else:
                self.last_action = f"回礦等待指令 #{ctx.episode_id}（已等 {mins} 分）"
            # Task 4：分鐘數變了才 edit embed（每分鐘最多 1 次 PATCH，防 rate limit）
            if self._rr_embed_mid and mins != self._rr_last_min:
                self._rr_edit_embed()

    def _rr_abort_reset(self, frame):
        """等待/執行間礦坑又重置：收尾 ledger、作廢 context、回 RESET_WAIT。"""
        if self._rr_ctx is not None:
            self._rr_finalize("reset_interrupt")
        self._rr_notify("🔄 礦坑重置中，本輪回礦作廢、重來")
        self.state = State.RESET_WAIT
        self._on_enter(State.RESET_WAIT, frame)

    def _rr_finalize(self, outcome):
        """episode 收尾：刪 embed 卡片、寫 ledger 一行、清 context/pending。"""
        # 收尾主動立遙控器重貼旗標（2026-07-19 spec）：完成訊息若在狀態仍是 REENTRY
        # 的輪次被輪詢消費，解凍後頻道再無新訊息、「看到新訊息才重貼」永不成立——
        # 遙控器一直埋在上面。旗標制不依賴輪詢看到哪則訊息，競態消失。
        self._remote_repin.mark_pending()
        self._rr_open_first_ts = 0.0             # episode 收尾清探測狀態
        # Task 4：episode 結束收走 embed 卡片（避免殘留一堆死卡）。放在 ctx 清除前，
        # 即使 ctx 已 None（防禦性呼叫）也能清掉殘留 embed。
        if self._rr_embed_mid:
            from . import notify
            ok, detail = notify.delete_message(
                cfg.discord_bot_token, cfg.discord_channel_id, self._rr_embed_mid)
            self.log_discord.info("RR embed delete mid=%s -> %s", self._rr_embed_mid, detail)
        self._rr_embed_mid = None
        self._rr_reactions_seen = {}
        self._rr_last_min = -1
        ctx, self._rr_ctx = self._rr_ctx, None
        self._pending_reentry = None
        # 2026-07-20：脫離 REENTRY 立刻補挖礦遙控器到頻道底——不再只立旗標等 quiet_s
        # （完成通知／補瓶通知會讓 last_activity 持續刷近，due() 不成立，遙控器遲遲不回底）。
        # 上面的 mark_pending 留作保險：repost 失敗時下輪 _repin_tick 仍會重試。
        self._repost_remote_control()
        if ctx is None:
            return
        self._zoom_restore_if_touched(ctx)
        world = game_data.current_world_name()   # 已鎖定世界才記；未鎖回 None
        self._rr_ledger_append(reentry_remote.ledger_entry(
            ctx, outcome, world, time.time() - ctx.created_at))

    def _rr_skip_on_pause_resume(self, source: str):
        """REENTRY 遠端 episode 進行中收到 暫停/繼續 → 視同 `跳過`（2026-07-18 需求）。

        遠端回礦本就是人工操作，暫停/繼續＝人要收回控制權。只排入 pending skip
        （指令/熱鍵執行緒鐵律：不碰遊戲輸入、不 finalize），主迴圈下個 tick 消費後
        finalize 直接回正常挖礦。暫停中主迴圈不 tick → skip 等恢復後才執行，
        整體行為＝「恢復即回挖礦」。布林/tuple 指派在 GIL 下原子，與既有旗標同模式。
        """
        if self._rr_ctx is None:
            return
        self._pending_reentry = (f"({source})", reentry_remote.RemoteReply("skip"))
        self.log_discord.info("RR %s -> queued skip (episode #%s)",
                              source, self._rr_ctx.episode_id)

    def _rr_ledger_append(self, d):
        """append-only JSONL：一行一筆（episode 收尾行／void 作廢行）。"""
        os.makedirs(os.path.dirname(cfg.reentry_remote_ledger), exist_ok=True)
        with open(cfg.reentry_remote_ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _adopt_sticky_for_world(self, world):
        """世界底定後套用持久黏性層（2026-07-20）：未釘時查 map，與現值不同才更新＋log。

        使用者本 session `層` 釘過（_rr_layer_user_pinned=True）則不覆寫——擋住「誤偵測世界
        甩掉使用者剛設的層」。新 session pinned=False，首次世界偵測即套用該世界的持久層。
        """
        if self._rr_layer_user_pinned or not world:
            return
        want = reentry_remote.effective_sticky_layer(
            world, self._rr_sticky_layers, cfg.reentry_target_layer)
        if want != self._rr_sticky_layer:
            self.logger.info("世界 %s 套用持久黏性層：%s → %s",
                             world, self._rr_sticky_layer, want)
            self._rr_sticky_layer = want

    def _apply_layer_change(self, layer: str, source: str = "discord"):
        """套用目標層變更；Discord `層` 指令與網頁設定頁**共用同一條路徑**。

        2026-07-26 抽出來的原因：網頁設定頁先前只改 `cfg.reentry_target_layer`
        （fallback 預設值），完全沒碰每世界黏性層 map——而執行期優先序是
        `sticky_layers[world] > cfg.reentry_target_layer`，所以網頁上改的層根本不會
        生效，兩邊各講各的。要真的同步，網頁就必須做跟 `層` 指令一模一樣的事。

        與舊 `_rr_execute` 版本的唯一差別：**ctx 允許是 None**。`層` 指令一定在回礦
        episode 內下達（ctx 必有），網頁則可以在任何狀態改層——直接寫 `ctx.sticky_layer`
        會 AttributeError 打死主迴圈。

        呼叫端必須是主迴圈執行緒（會寫檔 + 發 Discord）；網頁走
        `control:set_layer` → `_consume_web_pending` 進來。
        """
        self._rr_sticky_layer = layer
        if self._rr_ctx is not None:
            self._rr_ctx.sticky_layer = layer
        self._rr_layer_user_pinned = True     # 2026-07-20：釘住，後續世界偵測不再覆寫使用者選擇
        world = game_data.current_world_name()
        new_map = reentry_remote.remember_layer(self._rr_sticky_layers, world, layer)
        via = "（來自網頁）" if source == "web" else ""
        if new_map is not None:
            self._rr_sticky_layers = new_map
            self._write_sticky_layers()
            self._rr_notify(f"✅ 目標層改為：{layer}（已記住 {world} → {layer}）{via}")
        else:
            self._rr_notify(f"✅ 目標層改為：{layer}"
                            f"（世界尚未偵測到，僅本次有效；偵測到後請再設一次以記住）{via}")

    def _effective_layer_info(self) -> dict:
        """網頁設定頁用：bot **當下真正會用的**目標層 + 這個值的出處。

        在 WebIPC 執行緒上被呼叫（web_server 的 layer_getter），所以只做純讀取：
        兩個屬性讀 + 一個 dict.get，都是 CPython 原子操作，不 mutate 任何狀態。

        from_world_map 用「map 裡該世界的值 == 現行值」判定，而不是只看 world 在不在
        map 裡——這樣使用者剛釘完但世界還沒偵測到時，提示文字不會謊稱是記憶值。
        """
        world = game_data.current_world_name()
        mapping = self._rr_sticky_layers
        return {
            "effective": self._rr_sticky_layer,
            "world": world,
            "from_world_map": bool(world) and mapping.get(world) == self._rr_sticky_layer,
        }

    def _player_state_snapshot(self) -> dict:
        """網頁設定頁用：雷達開關現值（2026-07-28；保留清單已從網頁移除，
        Discord `keep`/`unkeep`/`clear` 仍是唯一入口，用量太低不值得放網頁）。

        在 WebIPC 執行緒上被呼叫（web_server 的 player_state_getter）——比照
        `_effective_layer_info`，只做純讀取。`_radar_toggle` 是 Discord 執行緒
        也會直接寫的既有欄位（見 `_handle_discord_command`），跨執行緒讀取沒有
        新增風險，是既有慣例的延伸。
        """
        return {"radar": dict(self._radar_toggle)}

    def _write_sticky_layers(self):
        """寫穿式落盤黏性層 map（2026-07-20）；照 _rr_ledger_append 的目錄建立慣例。"""
        path = cfg.reentry_remote_sticky_layers_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(reentry_remote.serialize_sticky_layers(self._rr_sticky_layers))

    def _rr_snap_dir(self) -> str:
        """遠端回礦快照目錄（logs/snapshots/reentry）。"""
        return os.path.join(cfg.log_dir, "snapshots", "reentry")

    def _rr_sync_write(self, img, label: str) -> str:
        """同步寫快照（發送前檔案必須存在，比照 _render_aim_shots 的 cv2.imwrite）。"""
        import cv2
        snap_dir, path = diagnostics.snapshot_path(cfg.log_dir, label)
        os.makedirs(snap_dir, exist_ok=True)
        cv2.imwrite(path, img)
        return path

    def _rr_notify(self, text: str, image_paths: list | None = None):
        """RR 專用發送＋log 稽核：有圖走 send_images_message，無圖走 send_message。

        過去 notify.send_message/send_images_message 回 (ok, detail) 在 _rr_* 各處被丟棄、不記
        log——警告是否送達 Discord 無從稽核（背景 4）。此 helper 統一記一筆 discord.log。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if image_paths:
            ok, detail = notify.send_images_message(token, ch, text, image_paths)
        else:
            ok, detail = notify.send_message(token, ch, text)
        self.log_discord.info("RR TXT %s -> %s", text[:30], detail)
        return ok, detail

    def _click_surface_verified(self, tag: str) -> bool:
        """按「回到地表」並以幀差驗證傳送；未達門檻則重試。

        RESET_WAIT 撤離與 REENTRY 開場共用。重試前 ic.move_to 中央再移回按鈕——多一次真實
        滑鼠移動事件（虛空下偶發成功的案例前面都有背包開關等真實輸入，成本 0）。

        不查 _mine_resetting（RESET_WAIT 本就 resetting；REENTRY 開場若 reset，幀差暴增被判
        teleported，下一 tick _rr_abort_reset 收尾）。只查 _running／paused（關閉或暫停即中止）。

        H044 起量 reentry_game_region（全幀會被覆蓋視窗重繪灌爆＝凍結中假傳送）；frac 雙訊號
        補「夜空大片黑稀釋 mean」的地表↔地表傳送。
        """
        for attempt in range(1, cfg.reentry_click_retries + 1):
            if not self._running or self.paused:
                return False
            ref = capture.crop(capture.grab(), cfg.reentry_game_region)
            ic.click_at(*cfg.reentry_surface_button_xy)
            deadline = time.time() + cfg.reentry_teleport_wait_s
            max_diff = 0.0
            while time.time() < deadline:
                time.sleep(0.4)
                if not self._running or self.paused:
                    return False
                cur = capture.crop(capture.grab(), cfg.reentry_game_region)
                d = vision.frame_mean_diff(ref, cur)
                fr = vision.frames_changed_frac(ref, cur) or 0.0
                if d > max_diff:
                    max_diff = d
                if d >= cfg.reentry_teleport_diff or fr >= cfg.reentry_teleport_frac:
                    self.logger.debug("[RR] %s click attempt %d/%d: max_diff=%.1f frac=%.3f -> teleported",
                                      tag, attempt, cfg.reentry_click_retries, max_diff, fr)
                    return True
            # 未達門檻：游標移中央再移回按鈕，重試
            ic.move_to(960, 540)
            ic.move_to(*cfg.reentry_surface_button_xy)
            self.logger.debug("[RR] %s click attempt %d/%d: max_diff=%.1f frac=%.3f -> retry",
                              tag, attempt, cfg.reentry_click_retries,
                              max_diff, fr)
        return False

    # ---- Task 4：REENTRY 互動 embed（比照遙控器四件套，但作用域是單一 episode）-----
    def _rr_post_embed(self):
        """貼 REENTRY episode embed + 反應鈕 + 建基線（照抄 _post_remote_control）。

        成功時用 add_reaction 結果建立 count 基線，避免額外三次 GET，並防首輪把 bot
        自己的反應當成新點擊。失敗靜默（下輪重試）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._rr_ctx
        if ctx is None:
            return
        embed = reentry_remote.build_reentry_embed(
            ctx, self._rr_sticky_layer, time.time(), self._evac_done,
            pitch_offset_px=self._pitch_offset_px)
        ok, detail, mid = notify.send_embed(token, ch, embed)
        if not (ok and mid):
            self.log_discord.info("RR embed post FAIL -> %s", detail)
            return
        seen = {}
        for em in reentry_remote.REENTRY_REACTIONS:
            added, _ = notify.add_reaction(token, ch, mid, em)
            seen[em] = 1 if added else 0
        self._rr_embed_mid = mid
        self._rr_reactions_seen = seen
        self._rr_last_min = int((time.time() - ctx.created_at) // 60)
        self._rr_repin.clear()       # 已貼到頻道底：清殘留 pending（同 _post_remote_control）
        self.log_discord.info("RR embed posted -> mid=%s (ep=%s)", mid, ctx.episode_id)

    def _rr_repost_embed(self):
        """刪舊回礦卡、貼新的到頻道底（REENTRY 中的釘底；照抄 _repost_remote_control）。

        在 Discord 輪詢執行緒跑，只做 Discord I/O 不碰遊戲輸入。與主迴圈 finalize 的
        競態無害：刪除失敗只記 log，_rr_post_embed 內 ctx 已 None 會直接 return。
        """
        from . import notify
        mid = self._rr_embed_mid
        if mid:
            ok, detail = notify.delete_message(
                cfg.discord_bot_token, cfg.discord_channel_id, mid)
            self.log_discord.info("RR embed repost：刪舊 mid=%s -> %s", mid, detail)
        self._rr_embed_mid = None
        self._rr_post_embed()

    def _rr_edit_embed(self):
        """原地 PATCH REENTRY embed（不推播）。404/10008 → 重貼（照抄 _edit_remote_control）。"""
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        mid = self._rr_embed_mid
        ctx = self._rr_ctx
        if not mid or ctx is None:
            return
        embed = reentry_remote.build_reentry_embed(
            ctx, self._rr_sticky_layer, time.time(), self._evac_done,
            pitch_offset_px=self._pitch_offset_px)
        ok, detail = notify.edit_message(token, ch, mid, embed=embed)
        if ok:
            self._rr_last_min = int((time.time() - ctx.created_at) // 60)
            return
        self.log_discord.info("RR embed edit FAIL -> mid=%s %s", mid, detail)
        # 訊息被人手動刪掉（HTTP 404 / 10008）→ 重貼一則
        if "HTTP 404" in detail or "10008" in detail:
            self.log_discord.info("RR embed 消失（已刪）-> 重貼")
            self._rr_embed_mid = None
            self._rr_post_embed()

    def _poll_rr_reactions(self):
        """輪詢 REENTRY embed 反應：偵測新點擊 → 轉 RemoteReply → 寫 _pending_reentry。

        單次抓 Message Object reaction count；偵測後與文字回覆共用 _queue_reentry_reply，
        先回「已收到」再由主迴圈執行，避免 H044 的八方位掃完才第一次回覆。
        只在 _rr_embed_mid 非 None 且 state 是 REENTRY 時跑（呼叫端已閘）。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        mid = self._rr_embed_mid
        if not mid:
            return
        message = notify.fetch_message(token, ch, mid)
        if message is None:
            return
        self._rr_reactions_seen, increments = notify.find_reaction_increments(
            message, self._rr_reactions_seen, reentry_remote.REENTRY_REACTIONS)
        for emoji, delta in increments:
            reply = reentry_remote.reaction_to_reentry_reply(emoji)
            if reply is None:
                continue
            self._queue_reentry_reply(
                f"reaction:{emoji}", reply, source=f"reaction:{emoji}+{delta}")
            # 2026-07-26：按完歸零，同一顆（📷 重掃／🎲 重骰…）可以連按。
            # 清不掉就維持舊語意（使用者自行取消反應再點）——回礦卡不做刪貼降級，
            # 它的釘底另有 _rr_repost_embed 管，這裡刪貼會跟釘底防抖打架。
            self._reset_reaction_button(mid, emoji, self._rr_reactions_seen)
            break                                # 一次輪詢只處理一個

    def _notify_stuck(self, reason: str):
        """STUCK Discord 警告＋🏠 手動回礦反應鈕（H044 spec 第 3 節）。

        取代舊 STUCK 事件模板（notify._TEMPLATES 已移除，避免雙發）。回礦未啟用＝純文字。
        在主迴圈跑（與舊 sink 同步發送同成本）；失敗只記 log。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        active = self._reentry_active()
        text = f"⚠️ 腳本可能卡住：{reason}"
        if active:
            text += "\n點 🏠 或回 `回礦` ＝手動回礦自救（回地表→傳圖→你指揮）"
        ok, detail, mid = notify.send_message_with_id(token, ch, text)
        self.log_discord.info("STUCK alert -> %s (mid=%s)", detail, mid)
        if not (ok and mid and active):
            return
        added, _ = notify.add_reaction(token, ch, mid, "🏠")
        self._stuck_alert_mid = mid
        self._stuck_seen = {"🏠": 1 if added else 0}

    def _poll_stuck_reaction(self):
        """輪詢 STUCK 警告的 🏠：新點擊＝手動回礦（與 `回礦` 指令同一旗標）。

        Discord 輪詢執行緒：只寫旗標/回覆，絕不碰 input_control。
        單次抓 Message Object reaction count；fetch 失敗時保留舊基線。
        """
        if self._calib_session is not None:
            return  # 校準中不消費 STUCK 🏠——防殘留卡點擊繞過守門
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        mid = self._stuck_alert_mid
        if not mid:
            return
        message = notify.fetch_message(token, ch, mid)
        if message is None:
            return
        self._stuck_seen, increments = notify.find_reaction_increments(
            message, self._stuck_seen, ("🏠",))
        if not increments:
            return
        _, delta = increments[0]
        ok, reason = can_accept_manual_reentry(self.state, self._reentry_active())
        if not ok:
            notify.send_message(token, ch, f"❌ 回礦（🏠）未接受：{reason}")
            return
        self._manual_reentry = True
        if self.paused:
            self.paused = False
            self._antiafk_last = 0.0
        self._stuck_alert_mid = None       # 一次性：觸發後按鈕作廢（訊息留著）
        notify.send_message(token, ch, "⛏ 手動回礦已排入（🏠）→ 下個 tick 進 REENTRY")
        self.log_discord.info("STUCK 🏠 反應 +%d -> manual_reentry", delta)

    def _rr_open_episode(self, reroll: bool = False):
        """按回到地表 →（狀態閘）→ 俯仰歸位 → 八方位拍照 → Discord 發送 → 建/續 context。

        同步阻塞主迴圈 ~20-30s（比照 _sweep_for_tracker 慣例）；步驟間查 _mine_resetting。
        點擊用 _click_surface_verified（會重試；虛空下單發點擊幾乎無效——2026-07-13 實機），
        但其幀差結果只是**輔助訊號**：人已在地表時再點「回到地表」畫面可能毫無變化，
        轉移式驗證會把真成功判成失敗、卡死重骰（H046(b) 2026-07-17 ep2 實錄）。
        開場成立與否全看狀態錨（plan_opening_gate）：凍結探針＋Depth=Surface＋容量歸零。
        H058：reset 觸發時先過容量預檢（capacity_blocks_opening）——重置第二階段（容量 60~76%
        排到 ≤門檻）收尾中不點擊、不拖曳，避免卡頓吃輸入；≤門檻才進入上面的點擊→閘鏈。
        """
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，回 `重骰` 重試或 `跳過`")
            self._rr_ensure_ctx(reroll)
            return
        now = time.time()
        if self._rr_open_first_ts == 0.0:
            self._rr_open_first_ts = now         # 探測預算起算（episode 首擊）
        # H058：預檢需要 ctx（trigger＋episode_id）；首 tick 先建（不 increment attempt）
        if self._rr_ctx is None:
            self._rr_ensure_ctx(reroll=False)
        ctx = self._rr_ctx
        # H058 開場前容量預檢：重置收尾中（容量 > 門檻）不點擊「回到地表」、不拖曳俯仰——
        # 遊戲卡頓會吃掉這些輸入（RR#8~12 實錄：REENTRY 起跑時容量 60~76%，每 20s 一輪
        # click+pitch+OCR 持續 ~90s 到容量自然排到門檻才放行），且動作對「等容量排掉」無益。
        # 被動觀測到容量 ≤ 門檻才開始真正的回礦行動。手動回礦（trigger!="reset"）不擋。
        if ctx is not None and ctx.trigger == "reset":
            pre_cap = ocr.read_capacity_pct(
                capture.crop(capture.grab(), cfg.capacity_region), cfg.tesseract_path)
            if reentry_remote.capacity_blocks_opening(
                    ctx.trigger, pre_cap, cfg.reentry_open_capacity_max_pct):
                self._maybe_arm_chime(pre_cap)   # 預檢路徑也推進鈴聲錨（容量 ≤10 即開窗、冪等）
                self._rr_open_last_ts = time.time()
                remain = max(0.0, cfg.reentry_open_budget_s
                             - (time.time() - self._rr_open_first_ts))
                cap_s = "讀不到" if pre_cap is None else f"{pre_cap:.0f}%"
                self.logger.info(
                    "[RR#%s] 開場前容量 %s > %.0f%%（重置收尾中）——不點擊不拖曳，"
                    "%.0fs 後再探（預算剩 %.0fs）",
                    ctx.episode_id, cap_s, cfg.reentry_open_capacity_max_pct,
                    cfg.reentry_open_retry_wait_s, remain)
                self.last_action = (
                    f"等重置收尾：容量 {cap_s}"
                    f"（降至 ≤{cfg.reentry_open_capacity_max_pct:.0f}% 才開始回礦）")
                return
        # 容量 OK（或 manual／讀不到）：reroll increment（若適用）→ 點擊 → 拖曳 → 閘
        if reroll:
            self._rr_ensure_ctx(reroll=True)
        teleported = self._click_surface_verified("開場")
        self._rr_open_last_ts = time.time()
        if teleported:
            time.sleep(1.0)                      # 傳送落地沉澱
        # H045/H046 開場狀態閘（點擊幀差不在條件內）：
        # (1) 凍結探針＝俯仰拖曳前後幀「逐位元相同」（probe_frozen 專用門檻；
        #     ⚠ 不可用 pitch_eaten_*——H046(a) 夜間地表拖曳 mean 0.93~5.13 被它鎖 300s）；
        # (2) Depth=Surface＝人真的在地表（NNNm＝礦內/虛空墜落中→繼續探測點擊）；
        # (3) 容量歸零＝重置真完成（凍結舊幀 78% vs 重置後 0%；僅 reset 觸發）。
        # 讀值全與俯仰結果解耦（H046(a)：耦合造成 capacity=None 十一連發）。
        # 任一未過→不拍照不發圖，回 H044 探測迴圈（預算 300s 收口）。
        # 俯仰「被吃但沒凍結」只警告不擋拍照（可回 `仰角` 指令遠端修正）。
        # H048：開場鏈俯仰歸位比照其他俯仰路徑——prepare（聚焦＋游標進畫面＋settle）
        # ＋被吃重試一次（歸位冪等，重做無害）。凍結判定取末次量測（凍結＝兩次都 0.00）。
        # 回拉量帶 session 記帳值（2026-07-19：重骰/重探不可洗掉 `上|下` 已調好的仰角）。
        back_px = reentry_remote.effective_pitch_back(
            self._rr_pitch_back_px, cfg.reentry_pitch_back_px,
            cfg.reentry_pitch_clamp_px)
        self._sampler_pitch_prepare()
        # H052（RR#7 實錄 mean=4.64/2.34 誤判）：重試與成敗只認凍結探針，不用 eaten
        # 門檻——eaten 是白天礦內兩側夾（被吃 ≤3.29 vs 生效 ≥32.5），夜間地表真動
        # 只有 0.93~5.13 落在「被吃」區間；且歸位冪等，生效後重做畫面必然不變，
        # eaten 判定對歸位無意義。誤判的實害＝白拖一輪 ~20s、「角度可能偏」誤導
        # 警告、_pitch_offset_px 記帳脫鉤（卡面俯仰行/`存檔` 讀它）。
        frozen, p_mean, p_frac = True, 0.0, 0.0
        for attempt in (1, 2):
            _eaten_ok, p_mean, p_frac = self._pitch_drag_measured(
                f"[RR#{self._rr_ctx.episode_id}] 俯仰歸位(attempt {attempt})",
                lambda: ic.pitch_reset(cfg.reentry_pitch_clamp_px, back_px))
            frozen = reentry_remote.probe_frozen(
                p_mean, p_frac, cfg.reentry_frozen_mean_max, cfg.reentry_frozen_frac_max)
            if not frozen:                   # 非凍結＝歸位生效（凍結 0.00 vs 活著 ≥0.09）
                break
            self._sampler_pitch_prepare()
        if not frozen:
            self._pitch_offset_px = back_px  # 記帳同步：回礦卡俯仰行/快照 sidecar 讀它
        on_surface = None
        cap_pct = None
        if not frozen:
            state_frame = capture.grab()
            on_surface = ocr.read_depth_is_surface(
                capture.crop(state_frame, cfg.depth_region), cfg.tesseract_path)
            if self._rr_ctx.trigger == "reset":
                cap_pct = ocr.read_capacity_pct(
                    capture.crop(state_frame, cfg.capacity_region),
                    cfg.tesseract_path)
                self._maybe_arm_chime(cap_pct)   # H045：REENTRY 中 worker 不跑，錨靠這裡的讀值
        self._rr_last_probe = (on_surface, cap_pct, p_mean, p_frac)
        gate = reentry_remote.plan_opening_gate(
            frozen, on_surface, self._rr_ctx.trigger, cap_pct,
            cfg.reentry_open_capacity_max_pct)
        if gate != "proceed":
            self.logger.info(
                "[RR#%s] 開場閘未過（%s：teleported=%s pitch=%.2f/%.4f surface=%s capacity=%s）"
                "——%.0fs 後再探（預算剩 %.0fs）",
                self._rr_ctx.episode_id, gate, teleported, p_mean, p_frac,
                on_surface, cap_pct, cfg.reentry_open_retry_wait_s,
                max(0.0, cfg.reentry_open_budget_s
                    - (time.time() - self._rr_open_first_ts)))
            self.last_action = f"回礦開場閘未過（{gate}），等畫面活過來"
            return
        self._rr_open_first_ts = 0.0             # 全閘通過才清探測狀態
        # H052：舊「俯仰歸位疑似被吃」警告已移除——非凍結＝生效（誤報來源），
        # 真凍結由 plan_opening_gate 擋在拍照前，不會走到這裡。
        # 先掃八方位，再問 web（2026-07-26 改）。
        #
        # 舊順序是「先問 web，逾時才掃」，而問 web 時推的是**當下這一幀**——但回礦
        # 開場站在地表，傳送板九成不在視野內，玩家看著一張沒有目標的圖根本無從點起。
        # 實機 07-26 18:32 就是這樣白等 120s：log 有 `reply timeout（attempt 1/3）`，
        # 網頁明明連著（不是 fallback），只是沒東西可點。掃完再推，玩家才有得選。
        #
        # 掃描本身兩條路徑共用（_rr_sweep_capture），不會為了 web 多轉一圈。
        captured = self._rr_sweep_capture(encode_for_web=self._web_client_online())
        if captured is None:
            return                                # 掃到一半遇到重置：下一輪 tick 處理
        pairs, rot_missed, web_pngs = captured
        if self._reentry_await_player_click(self._rr_ctx, web_pngs, rot_missed):
            return
        # web 沒接手（沒連線／逾時／放棄）→ 發同一批圖到 Discord 走既有流程
        self._rr_sweep_send_discord(pairs, rot_missed)
        # Task 4：sweep 發圖後貼 embed 卡片（首次貼；reroll 時 edit 同一則）
        if self._rr_embed_mid:
            self._rr_edit_embed()
        else:
            self._rr_post_embed()

    def _rr_ensure_ctx(self, reroll: bool):
        """建新 context 或 reroll 續用（同 episode 號、attempt+1、面向/快照歸零）。"""
        if reroll and self._rr_ctx is not None:
            ctx = self._rr_ctx
            ctx.attempt += 1
            ctx.cur_dir = 0
            ctx.phase = "awaiting_cmd"
            ctx.shots = []
            ctx.zoom_region = ()
            ctx.zoom_base = ""
            return
        lines = []
        try:
            with open(cfg.reentry_remote_ledger, "rb") as f:
                lines = f.read().splitlines()
        except OSError:
            pass
        episode_id = reentry_remote.next_episode_id_from_ledger(lines)
        self._rr_ctx = reentry_remote.RemoteReentryContext(
            episode_id=episode_id,
            created_at=time.time(), sticky_layer=self._rr_sticky_layer,
            trigger=self._rr_trigger)
        # 立刻佔號（2026-07-26）：舊版只在 _rr_finalize 寫 ledger，於是**沒收尾的
        # episode 完全不佔號**——13:15 與 18:34 兩場都拿到 #26，快照撞名成
        # `reentry_ep26_dir1..8` ×2，網頁歷史併成一個 episode、時間軸整組重複。
        # 佔號行先寫，取號改掃全檔 max（next_episode_id_from_ledger），兩層一起才擋得住。
        # 寫檔失敗不能擋回礦（ledger 是記帳、不是流程）——只記 log 照跑。
        try:
            self._rr_ledger_append(reentry_remote.episode_reservation_entry(
                episode_id, self._rr_trigger, time.time()))
        except OSError as e:
            self.logger.warning("[RR#%s] ledger 佔號寫入失敗（編號可能重複）：%s",
                                episode_id, e)
        self._rr_pitch_back_px = None        # 新 episode：session 仰角記帳歸零（用 config 標準角）

    def _rr_sweep_and_send(self, prefix_msg: str = ""):
        """八方位拍照 → 疊粗網格 → 發 Discord（原本的整條路徑，維持不變）。"""
        captured = self._rr_sweep_capture()
        if captured is None:
            return                                # 重置中：上層 tick 下一輪處理
        pairs, rot_missed, _ = captured
        self._rr_sweep_send_discord(pairs, rot_missed, prefix_msg)

    def _web_client_online(self) -> bool:
        """現在有沒有 WebSocket client 可以接手介入（grace period 內算有）。"""
        web_state = getattr(self, "_web_fallback", None)
        if web_state is None or getattr(self, "_web_pending", None) is None:
            return False
        return not web_state.is_fallback(
            now=time.monotonic(), grace_s=cfg.web_fallback_grace_s)

    def _rr_sweep_capture(self, encode_for_web: bool = False):
        """八方位拍照（`,`×8 驗證式，轉滿一圈回原向）→ 疊粗網格（同步寫檔）。

        回 ``(pairs, rot_missed, web_pngs)``；``pairs`` 是 ``[(dir_idx, grid_path)]``，
        ``web_pngs`` 是 ``[(dir_idx, png_bytes)]``（``encode_for_web=False`` 時為空）。
        重置中途中斷回 ``None``（上層 tick 下一輪處理 reset）。

        2026-07-26 從 `_rr_sweep_and_send` 拆出來：web 介入需要**同一批**八方位圖，
        但不該順便發一輪 Discord（8 張圖洗版）。拆開之後兩條路徑共用一次實際旋轉
        ——絕不能為了 web 再掃一圈，那是 ~15s 的遊戲輸入且會改變面向。

        web 用的是**沒有網格線的原始幀**：Discord 要格子是因為玩家只能用文字說
        「C2」；網頁可以直接點像素，格線只會擋住畫面。
        PNG 就地編碼而不是事後從檔案讀回——`self._snapshot` 是非同步寫檔，
        推送當下檔案可能還沒落盤。
        """
        ctx = self._rr_ctx
        # 鏡頭距離歸位（2026-07-19）：每次 sweep（開場/📷 重掃/重骰）前無條件歸一，
        # 快照之間才可比對；使用者 `遠`/`近` 調過的距離會被重置（刻意——快照一致性
        # 優先），net_zoom 同步歸零＝收尾 _zoom_restore_if_touched 不再重複歸位。
        if self._zoom_normalize(f"[RR#{ctx.episode_id}] sweep 前") and ctx.net_zoom:
            ctx.net_zoom = 0
        # 對齊座標系：sweep 內部標號固定 0-7＝相對開場面向（cur_dir=0）。zoom 後 cur_dir
        # 可能非 0，先轉回 dir 0 再掃——否則「方位 N」標籤與之後 `N 粗格` 的轉向計畫錯位。
        back = harvester.plan_return_rotations(ctx.cur_dir % 8, 0)
        for _ in range(abs(back)):
            if self._rotate_verified(1 if back > 0 else -1):
                ctx.cur_dir += 1 if back > 0 else -1
        if ctx.cur_dir % 8 != 0:
            self.logger.warning("[RR#%s] sweep 前對齊 dir0 未完成（cur_dir=%d）——方位標籤可能偏",
                                ctx.episode_id, ctx.cur_dir)
        ctx.shots = []
        pairs = []                                # [(dir_idx, grid_path)]
        web_pngs = []                             # [(dir_idx, png_bytes)]
        zs = f"_z{ctx.net_zoom:+d}" if ctx.net_zoom else ""
        rot_missed = 0
        for i in range(8):
            if self._mine_resetting:
                return None                       # 上層 tick 下一輪處理 reset
            f = capture.grab()
            # 檔名/標籤一律 1 起算（2026-07-18 使用者要求；ctx.shots 內部仍 0-based）
            path = self._snapshot(f, f"reentry_ep{ctx.episode_id}_dir{i + 1}{zs}")
            ctx.shots.append((i, path or ""))
            if encode_for_web:
                png = self._encode_png(f)
                if png is not None:
                    web_pngs.append((i, png))
            grid_img = f.copy()
            remote_aim.draw_grid(grid_img, 6, 4)
            gpath = self._rr_sync_write(grid_img,
                                        f"reentry_ep{ctx.episode_id}_dir{i + 1}_grid{zs}")
            pairs.append((i, gpath))
            # 8 次右轉＝轉滿一圈回原向；cur_dir 座標系不變。H050：重試用盡仍沒轉時
            # 之後的 dir 標籤全部錯位、收尾面向≠開場面向（`方位 粗格` 會轉錯）——
            # 拍照照拍（至少有圖可看），但記數警告，讓使用者知道標籤不可信。
            if not self._rotate_verified(1):
                rot_missed += 1
        if rot_missed:
            self.logger.warning("[RR#%s] 八方位拍照有 %d 次旋轉重試用盡未生效——方位標籤已錯位",
                                ctx.episode_id, rot_missed)
        return pairs, rot_missed, web_pngs

    def _rr_sweep_send_discord(self, pairs, rot_missed: int, prefix_msg: str = ""):
        """把 `_rr_sweep_capture` 拍好的八方位網格圖分兩則發到 Discord。"""
        ctx = self._rr_ctx
        head = (prefix_msg or
                f"⛏ 回礦 #{ctx.episode_id}（attempt {ctx.attempt}）｜目標層：{ctx.sticky_layer}\n"
                f"回 `方位 粗格`（如 `3 C2`，方位 1-8）指位；`重骰` 換重生點；"
                f"`歸位`/`上|下 [px]` 調視角；`層 <名>` 改目標層；`跳過` 回挖礦")
        if rot_missed:
            head = (f"⚠ 八方位拍照中有 {rot_missed} 次旋轉未生效——方位標籤可能偏，"
                    f"建議 📷 重掃\n") + head
        batch = [p for _, p in pairs if p]
        self._rr_notify(head + "\n方位 1-4", image_paths=batch[:4])
        if len(batch) > 4:
            self._rr_notify("方位 5-8", image_paths=batch[4:8])

    # ---- Task 5：指令執行鏈（主迴圈執行緒，輸入全在此）-----------------------
    def _rr_execute(self, reply):
        """主迴圈消費一則回礦指令（輸入操作全在此執行緒）。"""
        ctx = self._rr_ctx
        k = reply.kind
        prev_phase = ctx.phase if ctx is not None else None
        if k == "layer":
            self._apply_layer_change(reply.layer, source="discord")
        elif k == "void":
            self._rr_void_last(ctx)
        elif k == "skip":
            # 2026-07-18：遠端已是人工，跳過不再交 NEEDS_HUMAN——直接回正常挖礦
            self._rr_finalize("skip")
            self._reentry_done = True             # decide_transition → MINING → init 序列
            self._rr_notify("⏭ 跳過，回正常挖礦")
        elif k == "reroll":
            self._rr_open_episode(reroll=True)
            # 2026-07-19：重骰無上限不變，每 N 次提醒一次「可跳過/先調視角」
            if self._rr_ctx is not None and reentry_remote.should_warn_attempts(
                    self._rr_ctx.attempt, cfg.reentry_attempt_warn_every):
                self._rr_notify(
                    f"🎲 已重骰 {self._rr_ctx.attempt} 次——重生點一直不理想可 `跳過` "
                    f"回挖礦，或先 `上|下 [px]`/`遠|近` 調視角再 📷 重掃")
        elif k == "sweep":
            self._rr_sweep_and_send(prefix_msg=f"🔁 回礦 #{ctx.episode_id} 重新八方位掃描")
        elif k == "pitch_save":
            self._rr_pitch_save(ctx)
        elif k in ("pitch_reset", "pitch"):
            self._rr_pitch(ctx, reply)
        elif k in ("zoom_out", "zoom_in"):
            self._rr_zoom_cam(ctx, reply)
        elif k == "magnify":
            if ctx.phase != "awaiting_fine":
                self._rr_notify("❓ 先 `方位 粗格`（如 `3 C2`）放大後才能 `放大 <細格>`")
                return
            self._rr_magnify(ctx, reply.cell)
        elif k == "back":
            self._rr_back(ctx)
        elif k == "coarse":
            self._rr_zoom(ctx, reply.dir_idx, reply.cell)
        elif k == "fine":
            if ctx.phase != "awaiting_fine":
                self._rr_notify("❓ 現在不是等細格的時候，先回 `方位 粗格`（如 `3 C2`）")
                return
            self._rr_click(ctx, reply.cell, reply.layer)
        elif k == "confirm":
            if ctx.phase != "awaiting_confirm":
                self._rr_notify("❓ 目前沒有待確認的點擊")
                return
            self._rr_success(ctx, "confirmed_by_user")
        # Task 4：每個指令執行完原地 edit embed（反映新 phase/attempt/分鐘數）。
        # skip/success 已 finalize（embed 刪除、_rr_embed_mid=None）→ _rr_edit_embed 會直接 return；
        # reroll 已在 _rr_open_episode 內 edit 過 → 這裡再 edit 一次同資料，無害的 no-op PATCH。
        if k not in ("skip", "reroll"):
            self._rr_edit_embed()
        # 2026-07-20：退出精細選擇（fine/confirm → awaiting_cmd）立刻要求回礦卡重貼到頻道底，
        # 不等 quiet_s——精細選擇期間卡被擠上去沒重貼，退回指令時要立刻可見。
        if (prev_phase in ("awaiting_fine", "awaiting_confirm")
                and ctx is not None and ctx.phase == "awaiting_cmd"):
            self._rr_repin.mark_pending_now()

    def _rr_pitch(self, ctx, reply):
        """Discord 仰角指令（2026-07-17：R 取樣視窗退役，俯仰控制移進回礦流程）。

        歸位＝拖到夾限飽和再回拉（冪等，被吃重試一次安全）；微調沿用取樣視窗
        語意（上=dy<0、下=dy>0；不重送——40px 幀差天然偏小，誤重送＝角度脫鉤）。
        _pitch_offset_px 記帳照舊（快照檔名/校準流程讀它）。
        """
        self._sampler_pitch_prepare()
        if reply.kind == "pitch_reset":
            # H052：成敗只認凍結探針（與開場鏈同語意）——歸位冪等，eaten 門檻在
            # 夜間地表/已歸位重做時必誤判「被吃」，✅/⚠ 回覆與記帳曾因此反向。
            for attempt in (1, 2):
                _eaten_ok, p_mean, p_frac = self._pitch_drag_measured(
                    f"[RR#{ctx.episode_id}] 仰角歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.reentry_pitch_clamp_px,
                                           cfg.reentry_pitch_back_px))
                if not reentry_remote.probe_frozen(
                        p_mean, p_frac, cfg.reentry_frozen_mean_max,
                        cfg.reentry_frozen_frac_max):
                    self._pitch_offset_px = cfg.reentry_pitch_back_px
                    self._rr_pitch_back_px = None   # 歸位＝回 config 標準角，重骰改用現值
                    self._rr_notify(f"✅ 仰角已歸位（夾限上 {self._pitch_offset_px}px；"
                                    f"附當前畫面，📷 可八方位重掃）",
                                    image_paths=self._rr_pitch_shot(ctx))
                    return
                self._sampler_pitch_prepare()
            self._rr_notify("⚠ 仰角歸位疑似被吃（已重試）；再回一次 `仰角 歸位` 或 📷 看現況",
                            image_paths=self._rr_pitch_shot(ctx))
            return
        px = reply.steps or cfg.sample_pitch_step_px
        dy = px if reply.cell == "down" else -px
        ok = self._pitch_drag_verified(f"[RR#{ctx.episode_id}] 仰角微調 dy={dy}",
                                       lambda: ic.pitch_nudge(dy))
        self._pitch_offset_px -= dy
        self._rr_pitch_back_px = self._pitch_offset_px  # 重骰/重探開場沿用（不被標準角洗掉）
        arrow = "▼ 下" if dy > 0 else "▲ 上"
        self._rr_notify((f"✅ 仰角{arrow} {px}px" if ok
                         else f"⚠ 仰角{arrow} {px}px 疑似被吃（記帳照調；懷疑沒動就 `仰角 歸位`）")
                        + f"；目前=夾限上 {self._pitch_offset_px}px；附當前畫面，"
                        + "`存檔` 可寫回標準角",
                        image_paths=self._rr_pitch_shot(ctx))

    def _rr_pitch_shot(self, ctx):
        """仰角指令後的單張確認截圖（2026-07-19：免手動 📷 八方位重掃就能看角度）。

        只拍當前面向、不轉向；失敗回 None（訊息照發不附圖，不能因截圖擋仰角回覆）。
        """
        try:
            path = self._rr_sync_write(capture.grab(),
                                       f"reentry_ep{ctx.episode_id}_pitch_check")
        except Exception as e:
            self.logger.warning("[RR#%s] 仰角確認截圖失敗：%s", ctx.episode_id, e)
            return None
        return [path] if path else None

    def _rr_pitch_save(self, ctx, path: str | None = None):
        """`存檔`：把目前 session 仰角寫回 config `reentry_pitch_back_px`（2026-07-19 需求）。

        校準卡在 REENTRY 中被拒，回礦裡調出的好角度過去只能事後重校。沿用校準卡
        寫檔路徑（rewrite_config_value 錨點恰一次才寫；任何失敗不動記憶體 cfg——
        檔案與記憶體不分岔）。值 clamp [0, 夾限] 與 effective_pitch_back 同語意；
        寫回後 session 記帳交還標準角（config 現值＝期望值）。
        """
        from . import config as config_module
        fld = "reentry_pitch_back_px"
        val = max(0, min(self._pitch_offset_px, cfg.reentry_pitch_clamp_px))
        path = path or config_module.__file__
        try:
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
            new_text = calibrate_pitch.rewrite_config_value(text, fld, val)
            if new_text is None:
                self._rr_notify(f"❌ 存檔失敗：config.py 找不到唯一 `{fld}` 錨點——"
                                f"請手抄 `{fld} = {val}`")
                return False
            # newline="" 保行尾 byte-level 不變（比照 _calib_save）
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new_text)
        except OSError as e:
            self._rr_notify(f"❌ 存檔失敗：{e}——請手抄 `{fld} = {val}`")
            return False
        old = getattr(cfg, fld)
        setattr(cfg, fld, val)
        self._rr_pitch_back_px = None
        self._rr_notify(f"💾 已寫回 `{fld}`：{old} → {val}（重骰/下次回礦即用此角）")
        self.logger.info("RR 仰角存檔 %s: %d -> %d", fld, old, val)
        return True

    def _rr_zoom(self, ctx, tgt_dir, cell):
        """轉到目標方位、裁粗格放大＋細網格回傳，進「等細格」。"""
        import cv2
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，稍後重試")
            return
        steps = harvester.plan_return_rotations(ctx.cur_dir % 8, tgt_dir % 8)
        for _ in range(abs(steps)):
            if self._rotate_verified(1 if steps > 0 else -1):
                ctx.cur_dir += 1 if steps > 0 else -1
        if ctx.cur_dir % 8 != tgt_dir % 8:
            self._rr_notify("⚠ 轉向被吃，目前面向可能偏；重下一次 `方位 粗格` 即重對齊")
            return
        f = capture.grab()
        region = reentry_remote.coarse_cell_region(cell)
        x, y, rw, rh = region
        # 漂移守門（H050）：sweep 快照（使用者選格的依據）vs 現場同格。八方位轉滿
        # 一圈的殘差/斜坡滑移可讓面向偏 ~6°（ep7 實錄：E2 的傳送板在現場跑出格外，
        # 「放大圖不是指定的放大圖」）。放大圖仍發現場畫面——點擊座標以現況為準，
        # 裁快照反而會點錯——但要讓使用者知道格線可能對不上、可 📷 重掃。
        drift_note = ""
        snap_path = next((p for i, p in ctx.shots if i == tgt_dir % 8), "")
        snap = cv2.imread(snap_path) if snap_path else None
        snap_crop = snap[y:y + rh, x:x + rw] if snap is not None else None
        if reentry_remote.zoom_drifted(snap_crop, f[y:y + rh, x:x + rw],
                                       cfg.reentry_remote_drift_diff):
            drift_note = ("⚠ 畫面已偏離八方位圖（掃描後鏡頭殘差/滑動），"
                          "放大圖以現況為準；格線對不上可 📷 重掃\n")
        zoom = reentry_remote.render_zoom(
            f, region, scale=cfg.reentry_remote_zoom_scale,
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        zs = f"_z{ctx.net_zoom:+d}" if ctx.net_zoom else ""
        # 檔名帶時間戳（H050）：同格重複放大不可互相覆蓋（ep7 實錄 E2 重放大只剩
        # 一份，事後無從比對）；_rr_click/_rr_magnify 讀 ctx.zoom_base 值，不受影響。
        base = os.path.join(
            self._rr_snap_dir(),
            f"ep{ctx.episode_id}_zoom_{tgt_dir + 1}{cell}{zs}_{int(time.time())}")
        os.makedirs(self._rr_snap_dir(), exist_ok=True)
        cv2.imwrite(base + "_src.png", f[y:y + rh, x:x + rw])   # 漂移守門基準（同步寫）
        cv2.imwrite(base + ".png", zoom)
        ctx.zoom_stack.append(None)               # 2026-07-20：首層之前＝awaiting_cmd（退層 pop None 回指令）
        ctx.phase = "awaiting_fine"
        ctx.zoom_dir = tgt_dir
        ctx.zoom_region = region
        ctx.zoom_base = base                      # _rr_click 讀回（不重組字串）
        ctx.zoom_scale = cfg.reentry_remote_zoom_scale
        self._rr_notify(
            drift_note
            + f"🔍 方位 {tgt_dir + 1} 的 {cell} 格放大。回細格（如 `B3`）點擊；"
            f"要換層回 `B3 <層名>`；太小回 `放大 <細格>` 再放大；選錯格回 `退` 退一層",
            image_paths=[base + ".png"])

    def _rr_magnify(self, ctx, cell):
        """再放大（2026-07-18 需求）：細格子區域變成新的 zoom_region 重裁重發，可連鎖。

        點擊解析度每層 ×fine 格數——D5 傳送板在首層放大仍太小點不準時逐層逼近。
        scale 依子區域寬自動補償（輸出貼齊首次放大尺寸）；子格小於 1px＝位圖極限，拒絕。
        漂移守門基準（_src）同步換成子區域，_rr_click 沿用不變。
        """
        import cv2
        sub = reentry_remote.fine_cell_subregion(
            ctx.zoom_region, cell,
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        if sub is None:
            self._rr_notify("❓ 細格代碼不合法（A1–F6）")
            return
        if sub[2] < cfg.reentry_remote_fine_cols or sub[3] < cfg.reentry_remote_fine_rows:
            self._rr_notify("⚠ 已到放大極限（子格不足 1px），直接回細格點擊或 `重骰`")
            return
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，稍後重試")
            return
        f = capture.grab()
        scale = reentry_remote.magnify_scale(
            sub[2], cfg.screen_w // 6 * cfg.reentry_remote_zoom_scale,
            cfg.reentry_remote_zoom_scale)
        zoom = reentry_remote.render_zoom(
            f, sub, scale=scale,
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        zs = f"_z{ctx.net_zoom:+d}" if ctx.net_zoom else ""
        base = os.path.join(
            self._rr_snap_dir(),
            f"ep{ctx.episode_id}_zoom_{ctx.zoom_dir + 1}{cell}_x{scale}{zs}_{int(time.time())}")
        os.makedirs(self._rr_snap_dir(), exist_ok=True)
        x, y, rw, rh = sub
        cv2.imwrite(base + "_src.png", f[y:y + rh, x:x + rw])
        cv2.imwrite(base + ".png", zoom)
        ctx.zoom_stack.append({                   # 2026-07-20：連鎖放大前 push 上一層（退層用）
            "region": ctx.zoom_region, "base": ctx.zoom_base, "scale": ctx.zoom_scale})
        ctx.zoom_region = sub
        ctx.zoom_base = base
        ctx.zoom_scale = scale
        self._rr_notify(
            f"🔍 已再放大 {cell}（×{scale}）。回細格（如 `B3`）點擊；"
            f"可再 `放大 <細格>`；`退` 退一層；重掃回 📷",
            image_paths=[base + ".png"])

    def _rr_back(self, ctx):
        """退一層（2026-07-20）：連鎖放大時 pop 上一層 zoom_region；退過首層回 awaiting_cmd。

        退層不轉向、不重掃、不動鏡頭距離——只回溯放大鏈。退到的那層用當下現場幀
        重渲染（畫面可能已漂移），漂移守門基準 _src 同步更新，_rr_click 邏輯零改動。
        focus 失敗不 pop（避免丟層）；grab/imwrite 罕見失敗則記 log（已 pop，重下即可）。
        """
        import cv2
        if ctx.phase != "awaiting_fine":
            self._rr_notify("❓ 現在不是等細格，無層可退")
            return
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，稍後重試")
            return
        result = reentry_remote.pop_zoom_layer(ctx)
        if result[0] == "awaiting_cmd":
            ctx.phase = "awaiting_cmd"
            ctx.zoom_region = ()
            ctx.zoom_base = ""
            ctx.zoom_scale = 0
            self._rr_notify("↩ 已退回等指令，重新 `方位 粗格`（如 `3 C2`）")
            return
        layer = result[1]
        ctx.zoom_region = layer["region"]
        ctx.zoom_base = layer["base"]
        ctx.zoom_scale = layer["scale"]
        f = capture.grab()
        zoom = reentry_remote.render_zoom(
            f, layer["region"], scale=layer["scale"],
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        x, y, rw, rh = layer["region"]
        try:
            os.makedirs(self._rr_snap_dir(), exist_ok=True)
            cv2.imwrite(layer["base"] + "_src.png", f[y:y + rh, x:x + rw])
            cv2.imwrite(layer["base"] + ".png", zoom)
        except OSError as e:
            self.logger.warning("[RR#%s] 退層寫檔失敗（%s）——已 pop，使用者重下即可",
                                ctx.episode_id, e)
        self._rr_notify(
            f"↩ 已退一層（×{layer['scale']}）。回細格（如 `B3`）點擊；"
            f"可再 `退` 或 `放大 <細格>`",
            image_paths=[layer["base"] + ".png"])

    def _rr_click(self, ctx, fine_cell, layer_override):
        """細格點擊：漂移守門 → 左鍵點傳送按鈕 → 三態（成功/等確認/無反應）。"""
        import cv2
        pos = reentry_remote.fine_cell_to_screen(
            ctx.zoom_region, fine_cell,
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        if pos is None:
            self._rr_notify("❓ 細格代碼不合法（A1–F6）")
            return
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，稍後重試")
            return
        # 漂移守門（H026 家族）：粗格區域現況 vs 放大圖來源幀
        x, y, rw, rh = ctx.zoom_region
        cur = capture.grab()
        base = ctx.zoom_base
        src = cv2.imread(base + "_src.png") if base else None
        if src is not None and vision.frame_mean_diff(
                src, cur[y:y + rh, x:x + rw]) >= cfg.reentry_remote_drift_diff:
            zoom = reentry_remote.render_zoom(cur, ctx.zoom_region,
                                              scale=cfg.reentry_remote_zoom_scale,
                                              cols=cfg.reentry_remote_fine_cols,
                                              rows=cfg.reentry_remote_fine_rows)
            cv2.imwrite(base + ".png", zoom)
            cv2.imwrite(base + "_src.png", cur[y:y + rh, x:x + rw])
            self._rr_notify(
                "⚠ 畫面已漂移（buff 到期/保活跳動），沒有點。這是更新後的放大圖，請重指細格",
                image_paths=[base + ".png"])
            return
        layer = layer_override or ctx.sticky_layer
        marker = reentry_remote.draw_click_marker(cur, pos)
        os.makedirs(self._rr_snap_dir(), exist_ok=True)
        zs = f"_z{ctx.net_zoom:+d}" if ctx.net_zoom else ""
        mpath = os.path.join(self._rr_snap_dir(),
                             f"ep{ctx.episode_id}_click{len(ctx.clicks)}_marker{zs}.png")
        cv2.imwrite(mpath, marker)
        fpath = os.path.join(self._rr_snap_dir(),
                             f"ep{ctx.episode_id}_click{len(ctx.clicks)}_full{zs}.png")
        cv2.imwrite(fpath, cur)                  # 點擊瞬間全幀（ground truth 樣本）
        reentry_remote.record_click(ctx, pos, layer, ctx.zoom_region, time.time())
        self._rr_click_and_verify(ctx, pos, cur, layer, mpath, zs)

    def _rr_click_and_verify(self, ctx, pos, cur, layer, mpath, zs):
        """點擊 pos + post-click 三態驗證（still_surface / no_change /
        moved_unconfirmed / descended）。

        H046(c) 狀態錨輪詢：Depth 從 Surface 翻成 NNNm＝真下礦；幀差降為輔助訊號
        （重複點已成功的傳送板畫面可能不動＝假失敗、地表→地表換重生點畫面大動
        ＝假成功，轉移式驗證兩頭都會判錯）。

        P4 Task 4 抽出給 _rr_click／_rr_click_from_web 共用——前置作業（focus、
        漂移守門、marker snapshot、record_click）由 caller 各自處理：_rr_click 走
        Discord 細格→pos＋zoom_region 漂移守門；_rr_click_from_web 拿玩家原生 (x, y)
        直接定位、無 zoom_region（傳 () 給 record_click）。兩者點擊後的驗證邏輯相同。

        zs：snapshot 檔名用的 zoom 後綴（_z{N} 或空字串）。

        回 verdict（still_surface / no_change / moved_unconfirmed / descended）：
        P4 Task 5 接線讓 _rr_click_from_web 用 verdict 組 _resolve_ping_if_any 的 detail。
        _rr_click（Discord 路徑）忽略回傳值，沿用既有 awaiting_fine/awaiting_confirm 行為。
        """
        import cv2
        ic.click_at(int(pos[0]), int(pos[1]))
        deadline = time.time() + cfg.reentry_teleport_wait_s
        frame_changed = False
        while True:
            time.sleep(0.4)
            now_f = capture.grab()
            if not frame_changed and vision.frame_mean_diff(
                    cur, now_f) >= cfg.reentry_teleport_diff:
                frame_changed = True
            on_surface = ocr.read_depth_is_surface(
                capture.crop(now_f, cfg.depth_region), cfg.tesseract_path)
            verdict = reentry_remote.plan_click_verdict(
                on_surface, frame_changed, time.time() >= deadline)
            if verdict != "wait":
                break
        self.logger.info("[RR#%s] 點擊驗證：%s（depth_surface=%s frame_changed=%s）",
                         ctx.episode_id, verdict, on_surface, frame_changed)
        if verdict == "still_surface":
            self._rr_notify(
                "❌ 點了但 Depth 仍是 Surface＝沒下礦"
                + ("（畫面有動，可能只換了重生點）" if frame_changed else "")
                + "（紅圈＝實際點擊處）。重指細格、`放大 <細格>` 或 `重骰`",
                image_paths=[mpath])
            return verdict                        # 留在 awaiting_fine
        if verdict == "no_change":
            self._rr_notify(
                "❌ 點了畫面無變化、Depth 也讀不到（紅圈＝實際點擊處）。"
                "重指細格、`放大 <細格>` 或 `重骰`",
                image_paths=[mpath])
            return verdict                        # 留在 awaiting_fine
        time.sleep(1.5)                          # 傳送落地
        land = capture.grab()
        lpath = os.path.join(self._rr_snap_dir(),
                             f"ep{ctx.episode_id}_click{len(ctx.clicks) - 1}_landing{zs}.png")
        cv2.imwrite(lpath, land)
        # 落地實測層別（ledger ground truth）：遊戲畫面不顯示「在第幾層」，唯一可
        # 機讀的位置訊號是頂部 Depth 數值，(世界, 深度) 可反推層別。只寫紀錄、
        # **不參與任何決策**——底下的 verdict 分支與開挖流程完全不看這兩個值。
        depth_m = ocr.read_depth_meters(
            capture.crop(land, cfg.depth_region), cfg.tesseract_path)
        layer_seen = game_data.layer_for_depth(game_data.current_world_name(), depth_m)
        reentry_remote.record_landing(ctx, depth_m, layer_seen)
        self.logger.info("[RR#%s] 落地實測：depth=%s 層=%s（宣告層=%s）",
                         ctx.episode_id, depth_m, layer_seen, layer)
        if verdict == "moved_unconfirmed":
            # 降級路徑：Depth OCR 讀不到（區域被蓋/引擎故障）退回舊幀差訊號，
            # 一律交人工確認、不自動開挖（寧問勿假成功）；警告讓故障浮上來
            self.logger.warning("[RR#%s] Depth OCR 讀不到，點擊驗證退回幀差＋人工確認",
                                ctx.episode_id)
            ctx.phase = "awaiting_confirm"
            self._rr_notify(
                f"❓ 畫面有變化但 Depth 讀不到、無法確認下礦（層標籤：{layer}）。"
                f"左圖紅圈＝點擊處、右圖＝落點。沒問題回 `好` 開挖；點錯回 `重骰`；"
                f"資料要作廢回 `作廢`",
                image_paths=[mpath, lpath])
            self._broadcast_intervention_result(
                ctx, verdict="awaiting_confirm",
                summary="❓ 畫面有變化但 Depth 讀不到，無法確認下礦。沒問題按「好」開挖；"
                        "點錯「重骰」；資料有問題「作廢」",
                flow="reentry")
            return verdict
        # verdict == "descended"：Depth=NNNm 已直接證明在礦內；礦內亮度檢查退役
        # （夜間暗景會騙亮度——H046(a) 同源誤判；狀態錨嚴格更強）
        if cfg.reentry_remote_auto_resume:
            self._rr_notify(
                f"✅ 回礦 #{ctx.episode_id} 下礦成功（Depth 已離開 Surface；層：{layer}）。"
                f"紅圈＝點擊處；自動開挖",
                image_paths=[mpath, lpath])
            self._broadcast_intervention_result(
                ctx, verdict="descended",
                summary=f"✅ 下礦成功（層：{layer}），自動開挖", flow="reentry")
            self._rr_success(ctx, "success")
        else:
            ctx.phase = "awaiting_confirm"
            self._rr_notify(
                f"❓ 已下礦（層標籤：{layer}）。左圖紅圈＝點擊處、右圖＝落點。"
                f"沒問題回 `好` 開挖；點錯回 `重骰`；資料要作廢回 `作廢`",
                image_paths=[mpath, lpath])
            self._broadcast_intervention_result(
                ctx, verdict="awaiting_confirm",
                summary=f"❓ 已下礦（層：{layer}）。沒問題按「好」開挖；點錯「重骰」；"
                        "資料有問題「作廢」",
                flow="reentry")
        return verdict

    def _rr_click_from_web(self, ctx, x: int, y: int, dir_idx=None):
        """從 web 介入面板的玩家 tap 直接點擊＋驗證（跳過 Discord 方位+格+連鎖放大）。

        `dir_idx`（2026-07-26，1 起算的介面值）＝玩家點的是八方位裡的第幾張。
        給了就先轉到該方位再點——面板顯示的是 sweep 當下的畫面，不轉過去點下去
        會落在完全不同的地方。轉向被吃時放棄本次點擊（回 None），絕不硬點。

        P4 Task 4 minimum viable：玩家在介入面板 pinch-zoom + tap 點位置 → server 還原
        原生 (x, y) → 沿用 _rr_click_and_verify 的「點擊 → plan_click_verdict」尾段，
        不走 Discord 細格代碼、不做 zoom_region 漂移守門（web 點擊沒有 zoom 來源幀）。

        與 _rr_click 差異：
        - 無 fine_cell→pos 轉換（玩家直接給原生座標）
        - 無 zoom_region 漂移守門（無 zoom_base；pinch-zoom 是 web client 端顯示用，
          不影響 bot 端的螢幕座標）
        - record_click 收到的 region=()（與 _rr_click 收 zoom_region 對齊語意：
          該次點擊的「來源區域」對 web 是整個螢幕，沒有放大來源可記）
        - 快照檔名加 _web 後綴以便事後分析區分 Discord／web 點擊來源

        失敗時（still_surface / no_change）只發 _rr_notify，不 fall through 到
        Discord 八方位——玩家可改用文字指令 `重骰`／`跳過`（_handle_reentry_reply
        不靠 embed 也能解析），或等下一輪 web 介入。

        P4 Task 5 接線：玩家 reply 處理完成（不論 verdict 結果）後呼叫
        _resolve_ping_if_any 結案 PING 訊息——玩家已介入、結案信號比 verdict 優先。

        P5 Task 2：回傳 verdict（still_surface / no_change / moved_unconfirmed /
        descended），讓 _reentry_await_player_click 可據此判斷 retry；座標超界／
        聚焦失敗回 None（caller 視為不可 retry 的硬失敗）。

        P5 Task 3（P4 final-review Important: frame-grab race）：reply pop 後立刻
        sanity-check `_mine_resetting`——60-120s 等 reply 期間 礦坑可能已開始重置，
        傳送板／landing snapshot 都已過時；這時用過時座標點擊只會落在錯位置。
        reject 並推 INTERVENTION_RESULT 告知 web client。完整 re-verify（FOV 漂移、
        landing 是否仍可見）留實機驗收後再評估。
        """
        # P5 Task 3：reply race sanity-check——必須在座標驗證／focus／cv2 import 前。
        # 即便 caller retry 預算會消耗一次，也勝過對過時 snapshot 點擊。
        if getattr(self, "_mine_resetting", False):
            self.logger.info(
                "[RR#%s] web click reply 在 礦坑重置中，reject（避免對過時 snapshot 點擊）",
                getattr(ctx, "episode_id", "?"))
            self._broadcast_intervention_result(
                ctx, verdict="rejected_reset",
                summary=" 礦坑重置中，請 `重骰`／`跳過`", flow="reentry")
            self._resolve_ping_if_any(
                f"reentry:{ctx.episode_id}", "web",
                "web click 失敗：礦坑重置中（reply race）")
            return None
        import cv2
        if not (0 <= int(x) < cfg.screen_w and 0 <= int(y) < cfg.screen_h):
            self._rr_notify(
                f"❌ web 點擊座標超出螢幕範圍 (x={x}, y={y}；"
                f"screen={cfg.screen_w}x{cfg.screen_h})，`重骰` 重試或回 Discord 八方位")
            self._resolve_ping_if_any(
                f"reentry:{ctx.episode_id}", "web",
                f"web 點擊座標超出螢幕範圍 ({x},{y})")
            return None
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，web 點擊取消；可 `重骰` 重試")
            self._resolve_ping_if_any(
                f"reentry:{ctx.episode_id}", "web", "web 點擊失敗：無法聚焦 Roblox")
            return None
        # 玩家點的是八方位裡的某一張 → 先轉到那個方位（沿用 _rr_zoom 的轉向慣例）。
        # 不轉就點＝對著別的方向的畫面座標開槍。轉向被吃時寧可放棄本次，
        # 讓 caller 重掃一圈重推——硬點的後果是點在地形上，白費一次 attempt。
        if dir_idx is not None:
            tgt = (int(dir_idx) - 1) % 8          # 介面 1-8 → 內部 0-7
            steps = harvester.plan_return_rotations(ctx.cur_dir % 8, tgt)
            for _ in range(abs(steps)):
                if self._rotate_verified(1 if steps > 0 else -1):
                    ctx.cur_dir += 1 if steps > 0 else -1
            if ctx.cur_dir % 8 != tgt:
                self.logger.warning(
                    "[RR#%s] web 點擊轉向被吃（想去 dir%d，實際 dir%d）——放棄本次點擊",
                    ctx.episode_id, tgt + 1, ctx.cur_dir % 8 + 1)
                self._broadcast_intervention_result(
                    ctx, "轉向被吃", f"轉不到方位 {tgt + 1}，重掃一次再試")
                return None
        pos = (int(x), int(y))
        layer = ctx.sticky_layer
        cur = capture.grab()
        marker = reentry_remote.draw_click_marker(cur, pos)
        os.makedirs(self._rr_snap_dir(), exist_ok=True)
        zs = f"_z{ctx.net_zoom:+d}" if ctx.net_zoom else ""
        mpath = os.path.join(
            self._rr_snap_dir(),
            f"ep{ctx.episode_id}_click{len(ctx.clicks)}_marker_web{zs}.png")
        cv2.imwrite(mpath, marker)
        fpath = os.path.join(
            self._rr_snap_dir(),
            f"ep{ctx.episode_id}_click{len(ctx.clicks)}_full_web{zs}.png")
        cv2.imwrite(fpath, cur)                  # 點擊瞬間全幀（ground truth 樣本）
        # region=() 標記 web 點擊沒有 zoom 來源區域（有別於 _rr_click 收 zoom_region）
        reentry_remote.record_click(ctx, pos, layer, (), time.time())
        verdict = self._rr_click_and_verify(ctx, pos, cur, layer, mpath, zs)
        # P5 Task 5：自動收集素材（spec §5）——玩家介入 verdict = 真值材料。
        # frame = 點擊瞬間已抓的 cur（全幀）；reentry 無 cell_crop（傳送板定位用全幀座標）。
        # verify_ok ⇔ verdict=="descended"（H046(c) 狀態錨嚴格判定真下礦）。
        try:
            self._save_auto_fixture(
                flow="reentry", episode_id=str(ctx.episode_id),
                frame=cur, cell_crop=None,
                annotation_xy=(int(x), int(y)),
                verify_ok=(verdict == "descended"))
        except Exception as e:
            self.logger.warning(
                "[RR#%s] 自動收集素材失敗： %s", ctx.episode_id, e)
        # 玩家 reply 已處理（不管 verdict 結果）→ 結案 PING 訊息
        self._resolve_ping_if_any(
            f"reentry:{ctx.episode_id}", "web",
            f"玩家點擊 ({x},{y}) verdict={verdict}")
        return verdict

    def _reentry_await_player_click(self, ctx, web_pngs, rot_missed: int = 0) -> bool:
        """八方位掃完之後先問 web：把 8 張圖推給玩家，讓他直接點傳送板。

        `web_pngs`＝``[(dir_idx, png_bytes)]``（`_rr_sweep_capture(encode_for_web=True)`
        產出）。玩家在面板上左右切方位、在圖上點下去 → reply 帶 ``dir`` + ``x/y`` →
        `_rr_click_from_web` 先轉到該方位再點該像素，整條 Discord「方位 粗格 → 放大
        → 細格」的間接表達鏈就不必走了。

        **2026-07-26 的順序修正**：舊版在 sweep **之前**問 web，而且只推「當下這一
        幀」。回礦開場人站在地表，傳送板九成不在視野內——玩家看著一張沒有目標的圖
        根本無從點起，只能眼睜睜等 120s 逾時。實機 log 就是這樣：
        `[RR#26] 回礦 web 介入：reply timeout（attempt 1/3）`，網頁明明連著。
        改成掃完再推之後，玩家看到的是完整一圈，傳送板必在其中一張裡。

        面板上的 ⟳重掃／🎲重骰／⏭️跳過 也在這裡收（主迴圈此刻卡在本函式，
        `_consume_web_pending` 跑不到）——重掃就地再掃一圈重推，重骰/跳過排進
        既有 `_pending_reentry` 由主迴圈下個 tick 消費。

        回 True＝web 已接手（caller 不發 Discord 八方位圖、不貼 embed 卡片）；
        回 False＝無 web 連線／逾時／聚焦失敗 → caller fall through Discord 流程。

        attempt_id（wire protocol 對 reentry flow 的 id 欄位名）＝ episode_id：
        每集唯一、與 Discord 卡片標題 #ep{episode_id} 一致，玩家可對照。
        """
        if not self._web_client_online() or not web_pngs:
            return False
        routing_key = f"reentry:{ctx.episode_id}"
        if not self._focus_roblox():
            self.log_discord.info(
                "[RR#%s] 回礦 web 介入：無法聚焦 Roblox，跳過走 Discord 八方位",
                ctx.episode_id)
            return False

        max_attempts = 3
        note = ("⚠ 掃描時有 %d 次旋轉未生效，方位標籤可能偏——建議先 ⟳ 重掃"
                % rot_missed) if rot_missed else ""
        summary = f"回礦 #{ctx.episode_id}（attempt {ctx.attempt}）｜目標層：{ctx.sticky_layer}"
        if not self._send_web_intervention_frames(
                flow="reentry", routing_key=routing_key, frames=web_pngs,
                ctx_summary=summary, note=note):
            return False
        # 網頁在等你點——Discord 發一則提醒（玩家不必剛好開著面板盯著）
        self._notify_web_intervention_pending(ctx, len(web_pngs))

        try:
            for attempt in range(1, max_attempts + 1):
                timeout = (cfg.web_intervention_budget_s if attempt == 1
                           else cfg.web_intervention_retry_budget_s)
                kind, reply = self._await_web_reentry_action(
                    routing_key=routing_key, timeout_s=timeout)
                if kind is None or kind == "force_discord":
                    escalated = kind == "force_discord"
                    self.log_discord.info(
                        "[RR#%s] 回礦 web 介入：%s，fall through Discord 八方位",
                        ctx.episode_id,
                        "玩家按 🔀 選擇改用 Discord" if escalated else
                        f"逾時無回應（attempt {attempt}/{max_attempts}，等了 {timeout:.0f}s）")
                    # 2026-07-27：這裡原本沒有任何 INTERVENTION_RESULT——面板連著的人
                    # 只會看到畫面停在原地，之後才連進來的人（使用者是「有提醒才連」）
                    # 靠重播緩衝也會看到一份早就作廢的等待畫面。補一則結果訊息，順便
                    # 清掉重播緩衝（呼叫內含 end_intervention_replay）。
                    self._broadcast_intervention_result(
                        ctx, "web_escalate" if escalated else "web_timeout",
                        "你選擇改用 Discord，已切換八方位圖" if escalated else
                        "網頁逾時未回應，已改用 Discord 八方位", flow="reentry")
                    return False
                if kind in self._RR_WEB_CONTROLS and kind != "sweep":
                    # 重骰／跳過：排進既有 reentry 指令佇列，主迴圈下個 tick 消費
                    return self._queue_web_reentry_control(ctx, kind)
                if kind == "sweep":
                    captured = self._rr_sweep_capture(encode_for_web=True)
                    if captured is None:
                        return False              # 重置中：上層 tick 處理
                    _pairs, rot_missed, web_pngs = captured
                    if not web_pngs:
                        return False
                    self._send_web_intervention_frames(
                        flow="reentry", routing_key=routing_key, frames=web_pngs,
                        ctx_summary=summary,
                        note=("⚠ 重掃後仍有 %d 次旋轉未生效" % rot_missed) if rot_missed else "")
                    self.log_discord.info("[RR#%s] 回礦 web 介入：玩家按 ⟳ 重掃",
                                          ctx.episode_id)
                    continue                      # 不算掉一次 attempt 預算之外的事
                # kind == "click"
                dir_idx = reply.get("dir")
                self.log_discord.info(
                    "[RR#%s] 回礦 web 介入：收到點擊 dir=%s (%s,%s)（attempt %d/%d）",
                    ctx.episode_id, dir_idx, reply.get("x"), reply.get("y"),
                    attempt, max_attempts)
                verdict = self._rr_click_from_web(
                    ctx, x=int(reply.get("x", 0)), y=int(reply.get("y", 0)),
                    dir_idx=dir_idx)
                if verdict == "descended":
                    return True
                # verdict 為 None（座標超界／聚焦失敗／轉向被吃）或 still_surface／
                # no_change／moved_unconfirmed——都視為可 retry 的非 descended 結果
                verdict_label = verdict if verdict else "硬失敗"
                if attempt < max_attempts:
                    self._broadcast_intervention_result(
                        ctx, verdict_label, "沒下去，重新掃一圈給你再點一次")
                    # 點完面向已變、畫面也可能不同——重掃一圈再推，不要讓玩家對舊圖點
                    captured = self._rr_sweep_capture(encode_for_web=True)
                    if captured is None:
                        return False
                    _pairs, rot_missed, web_pngs = captured
                    if not web_pngs:
                        return False
                    self._send_web_intervention_frames(
                        flow="reentry", routing_key=routing_key, frames=web_pngs,
                        ctx_summary=f"{summary}｜第 {attempt + 1}/{max_attempts} 次",
                        note="上一次沒下去，再挑一次")
                    continue
                # 3 次都未 descended：不要再獨佔玩家，退回 Discord 讓兩邊都能操作
                self.log_discord.warning(
                    "[RR#%s] 回礦 web 介入：%d 次都未 descended（最後 verdict=%s），"
                    "退回 Discord 八方位",
                    ctx.episode_id, max_attempts, verdict_label)
                self._broadcast_intervention_result(
                    ctx, "放棄",
                    f"{max_attempts} 次未成功，已改用 Discord 八方位；也可按 🎲 重骰")
                return False
            return False
        finally:
            self._resolve_web_intervention_ping(ctx)

    def _queue_web_reentry_control(self, ctx, kind: str) -> bool:
        """把面板的 🎲重骰／⏭️跳過 排進既有 reentry 指令佇列（主迴圈下個 tick 消費）。

        走 `reentry_remote.parse_reply` 同一條路，跟玩家在 Discord 打字完全等價。
        回 True＝已排入（caller 不必再發 Discord 八方位）。
        """
        raw = self._RR_WEB_CONTROLS[kind]
        reply = reentry_remote.parse_reply(raw)
        if reply is None or self._pending_reentry is not None:
            self.log_discord.info(
                "[RR#%s] 回礦 web %s 被忽略（解析失敗或上一則指令還在執行）",
                ctx.episode_id, raw)
            return False
        self._queue_reentry_reply(raw, reply, source="web")
        self._broadcast_intervention_result(ctx, kind, f"已收到「{raw}」，處理中…")
        self.log_discord.info("[RR#%s] 回礦 web 介入：玩家按 %s", ctx.episode_id, raw)
        return True

    def _broadcast_intervention_result(
            self, ctx, verdict: str, summary: str, flow: str = "reentry") -> None:
        """推 INTERVENTION_RESULT event 給 web client（P5 Task 2）。

        verdict 非 descended 時呼叫，讓 web client UI 顯示「未成功，再點一次」
        或最終「放棄，請用文字指令」訊息；玩家不需 Discord embed 卡片也能反應。

        P5 Task 3：flow 參數讓 harvest 路徑（_execute_remote_fire_from_web）與
        reentry 路徑（_rr_click_from_web）都能標對 flow——web client 可據此顯示
        「採集流程被中斷」 vs 「回礦流程被中斷」。

        沒 web thread／無 registry → no-op（防護）；廣播失敗只記 log 不丟——
        網頁介入是加值路徑，失敗不能炸主流程。
        """
        web_thread = getattr(self, "_web_thread", None)
        if web_thread is None:
            return
        from .web_protocol import WebMessage
        registry = web_thread.app.state.registry
        registry.broadcast(WebMessage(
            type="event",
            payload={"event": "INTERVENTION_RESULT", "flow": flow,
                     "verdict": verdict, "summary": summary},
        ))
        # 2026-07-27：任何結果訊息都代表這輪推播已經作廢——不論是真的結束了
        # （fire_ok/descended/放棄），還是緊接著要重推新一輪（retry/重骰，caller
        # 會馬上再呼叫 _send_web_intervention_frames 重新 begin）。清掉重播緩衝，
        # 之後才連上的 client 不會看到「還在等你點」的過期畫面。
        registry.end_intervention_replay()

    def _rr_yaw_sample(self, ctx):
        """成功收尾後原地拍八方位，收 yaw 分類語料（H059；cfg.reentry_yaw_sample_sweep）。

        為什麼要這批圖：回礦每輪 attempt 都按「回到地表」換重生點＝遊戲隨機化
        yaw，`restore_view` 轉回的是那個隨機基底，直角/對角各約一半。根治要靠
        視覺校正，但目前**只有沿軸的正樣本、沒有斜挖負樣本**，依 H040/H054 慣例
        無法兩側夾、不得寫門檻。八方位取樣的相鄰幀固定差 45°⇒偶數組與奇數組必
        分屬兩類，分類器可用「指標是否以週期 2 交替」自洽驗證，不需絕對標籤。

        必須排在 `restore_view` 之後——語料要反映 bot 實際開挖的那個面向。
        8 次同向旋轉＝轉滿一圈回原向（同 `_rr_sweep` 的 H050 慣例），取樣結束
        面向不變。旋轉被吃只記數警告、照拍不中止（至少留圖），比照 H050。
        """
        if not cfg.reentry_yaw_sample_sweep:
            return
        rot_missed = 0
        for i in range(8):
            if self._mine_resetting or not self._running or self.paused:
                # reset 會重生、關機不再送鍵——兩者 yaw 都已作廢，停手即可。
                # 但殘留旋轉會讓面向偏 (i%8)*45°，明講免得事後誤判成別的 bug。
                self.logger.warning(
                    "[RR#%s] yaw 取樣中止於第 %d/8 張——面向可能偏 %d°（reset/暫停）",
                    ctx.episode_id, i + 1, (i % 8) * 45)
                return
            self._snapshot(capture.grab(), harvester.yaw_sample_label(ctx.episode_id, i))
            if not self._rotate_verified(1):
                rot_missed += 1
        if rot_missed:
            self.logger.warning(
                "[RR#%s] yaw 取樣有 %d 次旋轉重試用盡未生效——方位標籤已錯位，"
                "該輪語料不可信（收尾面向亦偏 %d°）",
                ctx.episode_id, rot_missed, (rot_missed % 8) * 45)

    def _rr_success(self, ctx, outcome):
        """成功收尾：挖礦標準角歸位 → yaw 回正 → ledger → 回 MINING。"""
        self._pitch_home_mining(f"[RR#{ctx.episode_id}] 回礦收尾")
        # yaw 回正（2026-07-20 使用者反映：回礦中 `方位` 指令累積的 ctx.cur_dir
        # 不回轉＝下礦後視角停在斜向、W 往斜向走、後續挖礦座標系偏）。比照採集
        # 收尾 _resume_mining_tail 的 restore_view——teleport 保留 yaw（實機確認），
        # 把淨旋轉反向送鍵轉回；cur_dir=0 時 restore_actions 回空、零作用。
        harvester.restore_view(ctx.cur_dir, rotate=self._rotate_verified)
        self._rr_yaw_sample(ctx)                  # H059 語料（cfg 預設關；須在回正之後）
        self._rr_finalize(outcome)
        self._reentry_done = True                 # decide_transition → MINING → init 序列
        self._rr_notify("⛏ 回礦完成，開挖")

    def _rr_void_last(self, ctx):
        """作廢最後一筆點擊（ledger 追加 void 行＋ctx 標 invalid）。"""
        if not ctx.clicks:
            self._rr_notify("❓ 本輪還沒有點擊記錄")
            return
        idx = len(ctx.clicks) - 1
        ctx.clicks[idx]["invalid"] = True
        self._rr_ledger_append(reentry_remote.void_entry(ctx.episode_id, idx, time.time()))
        self._rr_notify(f"🗑 已作廢本輪第 {idx + 1} 筆點擊資料")

    def _rr_zoom_cam(self, ctx, reply):
        """`遠`/`近`：I/O 鍵逐步驗證式 zoom → 其餘方位快照過期、重拍當前面向回傳。

        只在 awaiting_cmd 收（等細格時鏡頭一動放大圖必然作廢）；未校準整組停用。
        """
        if cfg.zoom_reset_pullback_steps <= 0:
            self._rr_notify("⚠ zoom 未校準（zoom_reset_pullback_steps=0），`遠`/`近` 不可用")
            return
        if ctx.phase != "awaiting_cmd":
            self._rr_notify("❓ 現在不能動鏡頭；先完成細格點擊/確認，或重下 `方位 粗格`")
            return
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，稍後重試")
            return
        out = reply.kind == "zoom_out"
        key, sign = ("o", 1) if out else ("i", -1)
        steps = reentry_remote.effective_zoom_steps(
            reply.steps, cfg.reentry_zoom_step_default, cfg.reentry_zoom_max_steps)
        done = 0
        for _ in range(steps):
            if self._zoom_key_verified(key):
                ctx.net_zoom += sign
                done += 1
        f = capture.grab()
        grid_img = f.copy()
        remote_aim.draw_grid(grid_img, 6, 4)
        gpath = self._rr_sync_write(
            grid_img, f"reentry_ep{ctx.episode_id}_zoomcam_z{ctx.net_zoom:+d}")
        ctx.zoom_region = ()
        ctx.zoom_base = ""
        self._rr_notify(
            f"🔭 鏡頭{'拉遠' if out else '拉近'} {done}/{steps} 步（淨 {ctx.net_zoom:+d}；"
            f"其餘方位圖已過期）。回 `{ctx.cur_dir % 8 + 1} 粗格` 指位、`掃` 重掃、`遠`/`近` 微調",
            image_paths=[gpath])

    def _tick_reentry(self, frame):
        """REENTRY 每 tick 一步。決策純函式在 reentry.py，這裡只做 I/O。

        remote 模式（2026-07-12 spec）在最頂端分流到 _tick_reentry_remote，不跑 auto 版相位機。
        auto 模式：任一步失敗統一走 _reentry_reroll（按回到地表換重生點）；
        attempts 用盡 → _reentry_failed=True（decide_transition → NEEDS_HUMAN）。
        """
        if self._remote_reenter_active():
            self._tick_reentry_remote(frame)
            return
        st = self._reentry
        now = time.time()
        if now - st.attempt_started > cfg.reentry_attempt_timeout_s:
            self._reentry_reroll("attempt timeout"); return

        if st.phase == reentry.SURFACE_WAIT:
            # 等傳送完成：與按下瞬間的參考幀比，大變化＝到地表了
            if self._reentry_ref is None:
                self._reentry_ref = frame.copy(); return
            if vision.frame_mean_diff(self._reentry_ref, frame) >= cfg.reentry_teleport_diff:
                self._set_reentry_phase(reentry.PITCH_RESET)
            elif now - st.phase_started > cfg.reentry_teleport_wait_s:
                self._reentry_reroll("teleport not detected")
            return

        if st.phase == reentry.PITCH_RESET:
            ic.pitch_reset(cfg.reentry_pitch_clamp_px, cfg.reentry_pitch_back_px)
            self._pitch_offset_px = cfg.reentry_pitch_back_px
            self._set_reentry_phase(reentry.SWEEP)
            return

        if st.phase == reentry.SWEEP:
            # 8 方位一次掃完（同 _sweep_for_tracker 的旋轉節奏，非逐 tick）
            scores = []
            for i in range(8):
                f = capture.grab()
                v, loc = vision.best_template_match_scored(
                    f, self._panel_templates, cfg.reentry_panel_scales)
                scores.append((i, v, loc))
                self.log_act.debug("reentry sweep dir=%d score=%.3f", i, v)
                if i < 7:
                    self._rotate_verified(+1)
            self._rotate_verified(+1)      # 第 8 轉回原位（8×45°=360°）
            best = reentry.pick_panel_direction(scores, cfg.reentry_panel_threshold)
            if best is None:
                top = max((s[1] for s in scores), default=-1.0)
                self._reentry_reroll(f"panel not found in sweep (best={top:.3f})")
                return
            # plan_return_rotations 回帶號步數（正=右轉、負=左轉）——不可直接 range()
            # （負數 range 為空＝根本不轉，落點方位就錯了）
            n = harvester.plan_return_rotations(0, best[0])
            for _ in range(abs(n)):
                self._rotate_verified(+1 if n > 0 else -1)
            self.log_act.info("reentry sweep 選定 dir=%d score=%.3f center=%s",
                              best[0], best[1], best[2])
            self._reentry_panel_xy = best[2]
            self._set_reentry_phase(reentry.NAVIGATE)
            self._reentry_nav_click()
            return

        if st.phase == reentry.NAVIGATE:
            self._move_diffs.append(
                vision.frame_mean_diff(self._last_nav_frame, frame)
                if self._last_nav_frame is not None else 99.0)
            self._last_nav_frame = frame.copy()
            status = reentry.movement_status(
                self._move_diffs, cfg.reentry_move_diff, cfg.reentry_move_stable_ticks)
            if status == "stopped":
                self._set_reentry_phase(reentry.READ_PANEL)
            elif now - st.phase_started > cfg.reentry_nav_timeout_s:
                self._set_reentry_phase(reentry.READ_PANEL)   # 超時也去讀——可能早就到了
            return

        if st.phase == reentry.READ_PANEL:
            recs = ocr.read_text_boxes(frame)
            target = reentry.pick_layer_button(
                recs, cfg.reentry_target_layer, cfg.reentry_decoy_buttons,
                cfg.reentry_button_min_ratio)
            if target is not None:
                self._snapshot(frame, "reentry_click")
                self._reentry_ref = frame.copy()
                ic.click_at(*target)
                self.log_act.info("reentry 點擊層按鈕 %s @%s", cfg.reentry_target_layer, target)
                self._set_reentry_phase(reentry.CLICK_VERIFY)
                return
            act = reentry.next_occlusion_action(st.occlusion_tried)
            st.occlusion_tried += (act,)
            self.log_act.info("reentry 遮擋階梯: %s（OCR %d 行無目標）", act, len(recs))
            if act == "orbit":
                self._rotate_verified(-1)
            elif act == "renavigate":
                self._reentry_nav_click()
                self._set_reentry_phase(reentry.NAVIGATE)
            else:
                self._reentry_reroll("panel text unreadable")
            return

        if st.phase == reentry.CLICK_VERIFY:
            if vision.frame_mean_diff(self._reentry_ref, frame) >= cfg.reentry_teleport_diff:
                r = cfg.stuck_region
                crop = frame[r.y:r.y + r.h, r.x:r.x + r.w]
                if float(np.mean(crop)) <= cfg.reentry_mine_max_brightness:
                    # 進礦已驗證成功——切回 Default (Keyboard) 才能安全 init_mining_sequence
                    # （Click to Move 模式下按住 W+左鍵的挖礦序列不可信）。切失敗不可帶病開挖，
                    # 直接交人工（比照 _harvest_giveup：此刻在 tick 內，不走 decide_transition）。
                    if not self._set_movement_mode(cfg.movement_mode_mining):
                        self.logger.warning("REENTRY 進礦成功但切回 Movement Mode 失敗 -> NEEDS_HUMAN")
                        self._human_reason = "自動回礦成功但無法切回 Default (Keyboard)，請手動確認設定後按 Q"
                        self.state = State.NEEDS_HUMAN
                        self._on_enter(State.NEEDS_HUMAN, frame)
                        return
                    self._pitch_home_mining("REENTRY(auto) 回礦收尾")
                    self._reentry_done = True
                    self._snapshot(frame, "reentry_success")
                    self.log.log("REENTRY_SUCCESS", attempts=st.attempts + 1)
                    self.logger.info("REENTRY 成功（第 %d 輪）→ 恢復挖礦", st.attempts + 1)
                    return
            if now - st.phase_started > cfg.reentry_teleport_wait_s:
                self._reentry_reroll("click did not teleport into mine")

    def _set_reentry_phase(self, phase):
        self._reentry.phase = phase
        self._reentry.phase_started = time.time()
        self._move_diffs = []
        self._last_nav_frame = None

    def _reentry_nav_click(self):
        ic.click_at(*self._reentry_panel_xy, button="right")   # click-to-move

    def _reentry_reroll(self, reason: str):
        """單輪失敗：再按「回到地表」換重生點重來；attempts 用盡交人工。

        用盡時只設旗標＋_human_reason——NEEDS_HUMAN 的 event log／Discord alert
        統一由 _on_enter(NEEDS_HUMAN) 發（比照採集放棄），這裡再發一次會重複通知。
        """
        st = self._reentry
        st.attempts += 1
        self.log_act.info("reentry reroll #%d：%s", st.attempts, reason)
        if reentry.should_giveup(st.attempts, cfg.reentry_max_attempts):
            self._reentry_failed = True
            self._human_reason = f"自動回礦失敗×{st.attempts}（{reason}），請手動回礦後按 Q"
            self._needs_human_extra_image = self._snapshot(capture.grab(), "reentry_giveup")
            # best-effort 切回 Default (Keyboard)：人工接手時鍵鼠模式對才好操作，
            # 但失敗不擋 NEEDS_HUMAN 通知（人工本來就會检查/修正設定）。
            if not self._set_movement_mode(cfg.movement_mode_mining):
                self.log_act.warning("REENTRY 放棄時切回 Movement Mode 失敗（best-effort，不擋通知）")
            return
        self._reentry = reentry.ReentryState(
            attempts=st.attempts, phase_started=time.time(), attempt_started=time.time())
        self._reentry_ref = None
        self._move_diffs = []
        self._last_nav_frame = None
        self._focus_roblox()
        ic.click_at(*cfg.reentry_surface_button_xy)             # 再按回到地表

    def _confirm_scan(self, where: str) -> bool:
        """D2 掃描確認（scan_confirm_mode 控制）。回傳 False 表示 enforce 模式下已重試仍失敗。"""
        if cfg.scan_confirm_mode == "off":
            return True
        ok = self._scan_local_badge_present()
        self.log_harvest.info("[scan-confirm] %s ok=%s mode=%s", where, ok, cfg.scan_confirm_mode)
        if ok or cfg.scan_confirm_mode == "observe":
            return True
        self.logger.warning("[scan-confirm] %s 未見 Local → 重新聚焦＋重掃一次", where)
        self._focus_roblox()
        # 沒見到 Local 的最常見原因就是冷卻中（連續使用剛用掉）——重掃前先等，
        # 否則重試會用同樣的無效點擊再撞一次。
        self._await_scan_ready(f"{where}-retry")
        self._run_scan()
        ok = self._scan_local_badge_present()
        self.log_harvest.info("[scan-confirm] %s retry ok=%s", where, ok)
        return True   # 重試後不論成敗都繼續 sweep（寧多掃勿誤棄；失敗已留 WARNING）

    def _scan_local_badge_present(self) -> bool:
        """效果列裡有沒有「Local」徽章＝D2 左鍵掃描是否真的觸發。

        逐格 OCR（非整條一次讀）：格位由 vision.find_effect_slots 現場定位，因為徽章疊加時
        Local 會被推到不同格；整條一次 OCR 在 psm=6 下會讀成亂碼（見 config 註解）。
        `Cave Skim`（D2 的 Z）同樣是雷達徽章但文字不同，實測不會被 scan_succeeded 誤判成 Local。
        """
        band = capture.crop(capture.grab(), cfg.scan_confirm_region)
        texts = [ocr.read_text(band[y:y + h, x:x + w], cfg.tesseract_path)
                 for (x, y, w, h) in vision.find_effect_slots(band)]
        return harvester.scan_succeeded(texts)

    def _reharvest_sweep(self, refresh_ref: bool = False):
        """重置目標、重新 D2 掃描並回到 sweep 階段（D3 連續未命中或框被搶走時呼叫）。

        `refresh_ref`（H118，2026-07-28）：預設 False＝沿用既有 H026 對策（見下）。
        只有呼叫端已經確認「上一輪 sweep 中途補過 D5」（`_sweep_fov_shifted`）才傳
        True——這種情況下 ref 是在補之前的舊 FOV 下拍的，不重拍等於繼續用錯位的
        排除基準再掃一次，保證再落空（118 實錄：verify 失敗才重掃，重掃仍 8 方位
        全空，因為 ref 從沒被修正過）。重拍時機比照進場（`_on_enter` HARVESTING）：
        先等冷卻／守門把 FOV 校正好，在**按下 D2 之前**拍——這一刻畫面上不會有
        D2 高亮的追蹤框，跟入口邏輯一樣安全，不是隨便挑一幀。
        """
        self.harvest.d3_attempts = 0
        self._target_marker = None              # 下次 tick 重掃
        # ★ 聊天基準/帳本不作廢（2026-07-04 H032 延伸對策）：若其實已採到才誤判 RESWEEP，
        #   成功行常在重掃期間才抵達——作廢重取會把它吃進新基準、差分永遠看不見。
        #   episode 基準＋ChatLedger 鏈式錨點跨 RESWEEP 存活，晚到行照樣算「新增」。
        harvester.prepare_scan()
        # ★ 不重拍 _pre_scan_ref（H026 對策）：重掃時追蹤框往往已在畫面上，重拍會把「活框」
        #   寫進排除基準 → 之後每方位偵測都 rej(preexist)、自我致盲（H026 dir=0 實錄：
        #   真框 (1288,1049) fill=0.57 ref_fill=0.57＝ref 裡就是它自己）。沿用進場時
        #   「框出現前」拍的 reference：靜態 UI（熱鍵列/面板）不隨視角/FOV 變、排除效果不減；
        #   世界內容錯位漏放的假陽性交給 colored_frac＋形狀確認擋。
        self._await_scan_ready("resweep")
        if refresh_ref:
            gf = capture.grab()
            if self._harvest_boost_guard(gf):
                gf = capture.grab()             # 剛補 D5、FOV 已展開 → 必須重抓
            self._pre_scan_ref = gf             # H118：FOV 已變過，捨棄舊 ref 重拍
        elif getattr(self, "_pre_scan_ref", None) is None:
            self._pre_scan_ref = capture.grab()  # 防禦：理論上進 HARVESTING 必已拍
        self._run_scan()
        self._confirm_scan("resweep")
        self._sweep_fov_shifted = False          # 這輪已處理，下次 sweep 重新判定
        # 重掃 = 回到 sweep 階段，重置計時器讓 sweep_timeout_s 重新計算
        self._harvest_start = time.time()
        self.harvest.elapsed_s = 0.0

    def _verify_chat_ocr(self, crop, chat_before, common, rare_names, hid, why):
        """輪詢驗證的一次聊天 OCR：multi 讀取＋差分判定＋詳細 log（H020 排錯需求）。

        回傳 (chat_after, confirmed, special)。log 內容：觸發原因/耗時/逐 pass 稀有計數
        與末行原文；未確認且有白名單時再印 fuzzy 診斷（疑似 found 行的收/拒與分數）——
        「讀到行但關鍵字歪了」這類假陰性從此直接可見，不用重跑 OCR 猜。
        """
        t0 = time.time()
        chat_after = ocr.read_text_multi(crop, cfg.tesseract_path)
        self._log_rapid_diag(hid, why)
        confirmed = ocr.any_new_rare_found(chat_before, chat_after, common,
                                           cfg.found_keywords, rare_names=rare_names)
        special = ocr.any_new_special_found(chat_before, chat_after, common,
                                            cfg.found_keywords, cfg.special_keywords)
        # ★ 基準閘（H054 對策，2026-07-20 harvest 094）：上面兩個都是**無錨點的計數差**，
        #   前提是「基準與 after 看的是同一個聊天視圖」。基準沒讀到任何 has-found 歷史
        #   ＝開火前聊天整窗淡出隱藏 → 之後舊行連同新行一起重新顯示，計數增加分不出是
        #   本次採到還是舊紀錄重現 → 不可採信（094 實錄：基準只讀到面板 "NORMAL"、
        #   rare 0→2 判成功，但框未消失且前後聊天裁圖逐位元相同＝這一發沒產生任何新行）。
        #   方向照「寧漏勿假成功」：擋掉後 gone=False 走 RETRY 再射一次，礦還在、不損失。
        #   只擋這兩個信號——帳本有等效規則且自帶錨點，照常生效（H032 晚到行仍救得回）。
        if not ocr.baseline_saw_found_history(chat_before, cfg.found_keywords):
            if confirmed or special:
                self.log_harvest.warning(
                    "[%s] H054 基準閘：基準無 has-found 歷史（開火前聊天淡出隱藏）"
                    "→ 忽略計數差確認 rare=%s special=%s（不認定成功）",
                    hid, confirmed, special)
            confirmed = special = False
        # episode 帳本（H032 延伸對策）：鏈式對齊累積新增行——基準底行已捲出裁圖時，
        # 上面的單次差分全滅，帳本以「上一次讀取」為錨仍接得住晚到/被推走的成功行。
        # confirmed 一旦入帳全 episode 有效（誤判失敗後的任何 OCR 都會把它撈回來）。
        ledger = getattr(self, "_chat_ledger", None)
        if ledger is not None:
            got = ledger.update(chat_after, common, cfg.found_keywords, rare_names=rare_names)
            if got:
                self.log_harvest.info("[%s] 帳本入帳新稀有行: %s", hid, got)
            # 世界偵測餵「全部新增行」（ledger.new_lines，含被動 Surreal/Mythic 低階礦）——
            # 那些礦名才在 common_ores 裡、才是 detect_world_from_ore 的比對來源。got 只有
            # 稀有行（依定義不在 common_ores）永遠對不上、且只在稀有入帳時觸發＝原本形同不生效。
            self._maybe_detect_world_from_ore_lines(ledger.new_lines)
            confirmed = confirmed or ledger.confirmed
        counts = [ocr.count_rare_found(t, common, cfg.found_keywords) for t in chat_after]
        self.log_harvest.info("[%s] verify OCR(%s) %.1fs rare/pass=%s confirmed=%s special=%s",
                              hid, why, time.time() - t0, counts, confirmed, special)
        labels = ocr.pass_labels(chat_after)
        for i, t in enumerate(chat_after):
            last = t.strip().splitlines()[-1] if t.strip() else ""
            self.log_harvest.info("[%s]   pass%d(%s) 末行=%r", hid, i,
                                  labels[i], last[-90:])
        if not confirmed and rare_names:
            for i, t in enumerate(chat_after):
                for d in ocr.fuzzy_found_diagnostics(t, common, rare_names):
                    self.log_harvest.info(
                        "[%s]   pass%d fuzzy %s: %r token=%r cand=%r rare=%s(%.2f) common=%s(%.2f)",
                        hid, i, "收" if d["accepted"] else "拒", d["line"][:70],
                        d["token"], d["candidate"],
                        d["best_rare"][0], d["best_rare"][1],
                        d["best_common"][0], d["best_common"][1])
        return chat_after, confirmed, special

    def _log_rapid_diag(self, hid, why):
        """RapidOCR 裁決輸出（2026-07-04 引擎切換的實機觀察期）：逐行信心分數記 DEBUG、
        「found 行但信心低於門檻」記 WARNING——grep harvest.log 的 WARNING 即收集
        疑似讀歪樣本，之後裁決引擎去留/調 RAPID_LOW_CONF_THRESHOLD。tesseract 後備
        路徑無診斷（pop 回 None）＝零成本。"""
        d = ocr.pop_rapid_diagnostics()
        if not d:
            return
        self.log_harvest.debug("[%s]   rapid(%s) %.2fs 共 %d 行", hid, why,
                               d["elapse"], len(d["lines"]))
        for t, s in d["lines"]:
            self.log_harvest.debug("[%s]     conf=%.2f %r", hid, s, t[:90])
        for t, s in ocr.low_confidence_found_lines(d["lines"], cfg.found_keywords):
            self.log_harvest.warning("[%s]   rapid(%s) found行低信心 conf=%.2f %r"
                                     "（疑似讀歪，裁決素材）", hid, why, s, t[:90])

    def _dump_chat_ocr(self, hid, chat_before, chat_after, verdict="unconfirmed"):
        """把逐 pass OCR 全文落盤 trace/*.txt（檔名帶 verdict）。

        H020 調查時只有截圖、沒有「當時 OCR 實際讀到什麼」——得事後重跑 10s OCR 且
        引擎版本/前處理一改就不可重現。文字檔很小，直接同步寫。
        RapidOCR 觀察期（2026-07-04）起成功路徑也落盤：裁決「誤判成功」（confirmed
        但其實沒採到）同樣需要當時全文，只靠失敗落盤看不見這一類。
        """
        try:
            d = os.path.join(cfg.log_dir, "snapshots", "trace")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(
                d, f"{time.strftime('%Y%m%d_%H%M%S')}_{hid}_chat_ocr_{verdict.lower()}.txt")
            parts = []
            for tag, texts in (("before", chat_before), ("after", chat_after)):
                labels = ocr.pass_labels(texts)
                for i, t in enumerate(texts):
                    parts.append(f"==== {tag} pass{i} ({labels[i]}) ====\n{t}\n")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(parts))
            self.log_harvest.info("[%s] OCR 全文已落盤: %s", hid, path)
        except Exception as e:                    # 診斷輔助，失敗不擋主迴圈
            self.log_harvest.warning("[%s] OCR 全文落盤失敗: %s", hid, e)

    def _snapshot_crop(self, frame, region, label: str) -> str | None:
        """存畫面指定區域截圖（非同步）。crop 很便宜，在主線裁好後把小圖丟背景寫檔。"""
        if not cfg.save_snapshots or frame is None:
            return None
        return self._enqueue_snapshot(capture.crop(frame, region), label)

    def _hlabel(self, label: str) -> str:
        """把本輪採集編號前綴到快照 label（無編號時原樣回傳，給非採集快照用）。

        結果檔名形如 20260629_022126_H007_d3_fire_960x540.png——grep H007 即可撈出該輪所有
        截圖。label 內原有的分類關鍵字（d3_fire/sweep_confirmed…）仍在 → snapshot_subdir
        分流不受影響（仍走子字串比對）。
        """
        hid = self.harvest.harvest_id
        return f"{hid}_{label}" if hid else label

    def _hsnap(self, frame, label: str) -> str | None:
        """採集用全幀快照：檔名自動帶本輪編號（見 _hlabel）。"""
        return self._snapshot(frame, self._hlabel(label))

    def _hsnap_crop(self, frame, region, label: str) -> str | None:
        """採集用區域快照：檔名自動帶本輪編號（見 _hlabel）。"""
        return self._snapshot_crop(frame, region, self._hlabel(label))

    # ---- 控制權熱鍵（全域輪詢）---------------------------------------------
    def _check_hotkeys(self):
        self._hk.tick()

    def _antiafk_tick(self, context: str):
        """等待狀態（暫停/需人工/重置等待）防踢除：每 antiafk_interval_s 保活一次。

        _antiafk_last=0 代表剛進入等待 → 設成 now 開始計時；累積逾時則保活並重置計時。
        Roblox 閒置過久會被踢。保活兩步：先把視窗切回 Roblox（等待期間使用者可能 alt-tab
        走、或別的視窗搶走焦點——不先聚焦，Space 會送到錯誤視窗等於沒保活），再按 Space
        （原地跳，最不打擾畫面）。已在前景就不重抓（_focus_roblox 含 ~1.3s sleep，不必每輪
        都付）。恢復活動時呼叫端把 _antiafk_last 歸 0（見主迴圈 elif 分支），下次等待才重新
        從 0 計時。
        """
        now = time.time()
        if self._antiafk_last == 0:
            self._antiafk_last = now
            return
        if now - self._antiafk_last < cfg.antiafk_interval_s:
            return
        # 切回 Roblox：等待期間可能失焦，不先聚焦 Space 會送錯視窗
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, cfg.window_title)
        refocused = False
        if not (hwnd and u.GetForegroundWindow() == hwnd):
            self._focus_roblox()
            refocused = True
        ic.key_press("space")
        # H060：原地跳的音效會被 chill 偵測器認成 chill → 從**真的按下**這刻起開靜音窗
        # （now 是進函式時取的，_focus_roblox 可能已花掉 ~1.3s，用它會少遮一段）。
        self._antiafk_pressed_at = time.time()
        self._antiafk_mute_logged = False
        self.logger.info("防掛機：%s按 Space（%s中等超過 %.0f 分鐘）",
                         "已失焦→重聚焦 Roblox 後" if refocused else "",
                         context, cfg.antiafk_interval_s / 60)
        self._antiafk_last = now

    def _pause(self):
        """暫停：放開所有按鍵、停住。idempotent（已暫停再呼叫無副作用）。

        Ctrl+Q 與 Q 的暫停走同一條路徑——兩者暫停行為完全一致，差別只在 Q 能再按一次
        繼續、Ctrl+Q 只暫停（見 _toggle_pause / on_stop 接線）。不再有獨立的「強制停止」。
        """
        self._rr_skip_on_pause_resume("pause")     # 回礦中暫停＝跳過（恢復後直接回挖礦）
        if not self.paused:
            self.paused = True
            ic.key_up("w"); ic.mouse_up()
            self._antiafk_last = time.time()       # 開始防掛機計時
            self.log.log("PAUSED")
            self.logger.info("PAUSED — 按 Q 繼續")

    def _resume(self):
        """繼續：清除暫停、重新置中準心、重新握住 W + 左鍵。

        輕量恢復（2026-07-20；2026-07-25 修正 center）：MINING 暫停恢復不跑
        zoom_normalize（I×30+O×4）與 init_mining_sequence 的 rotate(.,)——角度／
        遠近只在稀有礦重追、回礦、啟動時才會被動到，那些路徑各自歸位；單純暫停
        期間相機未動，歸位是白做工。但 center_crosshair（雙擊 Shift）仍要做：相機
        不動≠游標不動，使用者切去 Discord／瀏覽器、_focus_roblox 重聚焦都不會把
        準心拉回中心，不重置會讓後續瞄準偏移計算歪（使用者實機回報）。動過相機的
        場合（手動碰過、或暫停跨過 boost 到期）由後續 reentry／採集收尾歸位接手。
        """
        if self._calib_session is not None:
            # 校準中不准恢復挖礦（▶️/resume 只記離場後意圖；_calib_exit 先清 session 再
            # 呼叫 _resume 所以離場路徑不受此擋）。
            self.logger.info("RESUMED 被忽略：校準中（校準卡 ❌ 離開後才恢復）")
            return
        self._rr_skip_on_pause_resume("resume")    # 回礦中繼續＝跳過，直接回正常挖礦
        self.paused = False
        self._antiafk_last = 0.0                   # 重置防掛機計時（下次暫停重新從 0 開始）
        self.log.log("RESUMED")
        self.logger.info("RESUMED")
        if self.state is State.MINING:
            # 暫停期間焦點可能飄走（使用者切去別視窗看 Discord/瀏覽器）；恢復挖礦前
            # 先重新聚焦 Roblox。失敗不交人工——使用者正在按 Q 注視著，下次 mining
            # tick 的視窗跑位偵測會接手（REFOCUS action；那條路徑失敗才交人工）。
            self._focus_roblox()
            # 輕量恢復：暫停期間相機角度／遠近不動（只在稀有礦重追／回礦／啟動變動，
            # 那些路徑各自歸位）——zoom_normalize 與 init 的 rotate(.,) 仍跳過。
            # 但游標會飄：使用者切去 Discord／瀏覽器、_focus_roblox 重聚焦都不會把
            # 準心拉回中心，故放開→雙擊 Shift 置中→確認鎬子（沒拿才按 D1）→重握 W+左鍵。
            ic.key_up("w"); ic.mouse_up()
            ic.center_crosshair()        # 雙擊 Shift 重新置中準心（相機不動≠游標不動）
            miner.ensure_pickaxe()
            ic.key_down("w"); ic.mouse_down()

    def _toggle_pause(self):
        """Q：開關 暫停 ↔ 繼續（也用於人工介入/礦坑重置定位後重新啟動；
        啟動環境檢查階段＝跳過剩餘檢查，見 _skip_env_requested）。

        Ctrl+Q 已在 _check_hotkeys 分開處理（只會呼叫 _pause），這裡進來的一定是單獨 Q。
        行為分派走純函式 toggle_pause_action（states.py；有測試覆蓋），避免 inline
        if/elif 條件寫錯（例如漏掉 RESET_WAIT 或啟動階段誤觸發暫停）。
        """
        action = toggle_pause_action(self.paused, self.state,
                                     startup_phase=self._startup_phase)
        if action == "skip_env":
            self._skip_env_requested()
        elif action == "resume":
            self._resume()
        elif action == "clear_human":
            self.human_cleared = True
            self.logger.info("human cleared (Q) — 恢復挖礦 (from %s)", self.state.value)
        else:  # "pause"
            self._pause()

    def _quit(self):
        self.logger.info("QUIT (%s) — 結束程式", cfg.hotkey_quit)
        self._running = False

    # ---- Q 跳過啟動環境檢查（spec 2026-07-10 第 2 節；原 F8 與 Roblox 內建功能衝突改 Q）--
    def _skip_env_requested(self):
        """啟動階段按 Q（toggle_pause_action='skip_env' 進來）：跳過環境檢查（單向，非 toggle）。"""
        if not self._startup_phase or self._skip_env_check.is_set():
            return
        self._skip_env_check.set()
        self.logger.info("Q — 跳過環境檢查（剩餘 UI 前置檢查將略過，直接開挖）")
        self.last_action = "Q 跳過環境檢查"

    def _env_check_skip(self, name: str) -> bool:
        """啟動環境檢查的統一跳過判斷：Q（跳過）已按或程式要結束 → True（略過該步）。"""
        if not self._running:
            return True
        if self._skip_env_check.is_set():
            self.logger.info("環境檢查略過（Q）：%s", name)
            return True
        return False

    # ---- 俯仰拖曳共用前置（原 R 取樣視窗家族；視窗已退役，前置留給 仰角 指令）----
    def _sampler_pitch_prepare(self):
        """俯仰拖曳共用前置：聚焦回遊戲＋游標移進畫面＋沉澱。

        滑鼠事件送到「游標所在」視窗（鍵盤才看焦點）→ 先把游標移進遊戲畫面。
        settle（2026-07-11 實機）：log 三次「聚焦成功」但俯仰全沒生效——焦點剛
        切回遊戲就送右鍵拖曳會被吃（與旋轉鍵在焦點切換後被吃同家族）→
        拖曳前必須沉澱 sampler_pitch_focus_settle_s。
        """
        self._focus_roblox()
        ic.move_to(cfg.screen_w // 2, cfg.screen_h // 2)
        ic.settle(cfg.sampler_pitch_focus_settle_s)

    def _pitch_layer_transition(self) -> bool:
        """失敗路徑俯仰層轉換：pitch_reset 絕對基準 → nudge 到下一層（2026-07-11 spec）。

        回 True＝已切到新層（呼叫端 return，下個 tick 在新層重跑 8 方位）；False＝層用盡
        或礦坑重置中（呼叫端走 giveup）。拖曳被吃 → 整組（reset→nudge）重來一次——reset
        冪等（飽和→回拉）使重試安全、nudge 單獨重送會過量（sampler 微調不重送的教訓）；
        再失敗跳過該層試下一層（寧可少掃一層，不可角度不明硬掃——45° 斜角事故同族）。
        """
        hid = self.harvest.harvest_id
        while self.harvest.pitch_layers_left:
            if self._mine_resetting:
                self.logger.info("[%s] 俯仰層轉換前偵測到礦坑重置 -> 放棄掃層", hid)
                return False
            layer = self.harvest.pitch_layers_left.pop(0)
            self.harvest.pitch_touched = True
            for attempt in (1, 2):
                ok = self._pitch_drag_verified(
                    f"[{hid}] 俯仰層 {layer.name} 歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                           cfg.sweep_pitch_center_back_px))
                if ok:
                    ok = self._pitch_drag_verified(
                        f"[{hid}] 俯仰層 {layer.name} nudge {layer.nudge_px}px(attempt {attempt})",
                        lambda: ic.pitch_nudge(layer.nudge_px))
                if ok:
                    break
                self._focus_roblox()
                ic.settle(cfg.sampler_pitch_focus_settle_s)
            if not ok:
                self.logger.warning("[%s] 俯仰層 %s 拖曳兩輪皆疑似被吃 -> 跳過該層",
                                    hid, layer.name)
                continue
            self.harvest.pitch_layer = layer.name
            self._harvest_start = time.time()   # 每層獨立 sweep_timeout_s 預算（比照 sweep 完成後重置）
            self.logger.info("[%s] 俯仰層切換 -> %s（重新 8 方位掃描）", hid, layer.name)
            return True
        return False

    # ---- Discord 俯仰校準 session（2026-07-18 spec；paused 底下的旗標模式）----
    def _consume_calib_start(self):
        """消費校準進場 pending（主迴圈）。消費點重驗 REENTRY——驗收（輪詢執行緒）與
        消費之間可能剛好開了回礦 episode，直接進場會把它 skip 掉（比照 _pending_ability
        在消費點過 can_consume_ability 的慣例）。"""
        from . import notify
        target, self._pending_calib_start = self._pending_calib_start, None
        if self.state is State.REENTRY:
            notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
                                "❌ 校準取消：回礦 episode 已開始——結束後再下 `校準`")
            self.log_discord.info("校準 pending 消費點拒絕：state=REENTRY")
            return
        self._calib_start(target)

    def _calib_start(self, target: str):
        """進校準模式（主迴圈）：記原 paused → 強制暫停 → 歸位到 config 現值 → 發卡＋首圖。

        從現值起算（不從夾限歸零）：微調通常是「現值附近找更好」，歸零反而每次重校。
        進場歸位被吃只在卡上警告不擋（🧭 可重新絕對定位；比照 H046 慣例）。
        """
        fld, clamp_fld = calibrate_pitch.calib_field_names(target)
        cur = getattr(cfg, fld)
        sess = calibrate_pitch.CalibSession(target=target, offset=cur,
                                            prev_paused=self.paused)
        self._pause()                             # idempotent；放開 W/左鍵
        self._calib_session = sess
        self._stuck_alert_mid = None               # 進校準＝卡住語境失效，STUCK 🏠 作廢
                                                     # （比照「離開 MINING＝作廢」語意；否則
                                                     # 🏠 會繞過校準守門直接改 paused）
        self._sampler_pitch_prepare()
        warn = ""
        if not self._pitch_drag_verified(
                f"[校準] 進場歸位 {fld}={cur}",
                lambda: ic.pitch_reset(getattr(cfg, clamp_fld), cur)):
            warn = "進場歸位疑似被吃——🧭 可重新絕對定位"
        self._pitch_offset_px = cur
        self._post_calib_embed(warn)
        self._calib_snapshot()
        self.logger.info("校準開始 target=%s 現值=%d prev_paused=%s",
                         target, cur, sess.prev_paused)

    def _calib_exit(self, sess):
        """❌ 離場：不寫檔；有未存變更附最終值供手抄；恢復進場前 paused 狀態。

        先清 session 再 _resume——_resume 的校準守門靠 session 判斷，順序反了會被擋。
        """
        from . import notify
        fld, _ = calibrate_pitch.calib_field_names(sess.target)
        unsaved = sess.offset != getattr(cfg, fld)
        if sess.message_id:
            notify.delete_message(cfg.discord_bot_token, cfg.discord_channel_id,
                                  sess.message_id)
        self._calib_session = None
        self._pending_calib_action = None
        msg = "🏁 校準結束"
        if unsaved:
            msg += f"（⚠ 未存檔：最終 夾限上 {sess.offset}px；要保留請手動改 `{fld}`）"
        if not sess.prev_paused:
            msg += "｜恢復挖礦"
            self._resume()
        else:
            msg += "｜維持暫停（進場前即暫停）"
        notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id, msg)
        self.logger.info("校準結束 unsaved=%s prev_paused=%s", unsaved, sess.prev_paused)

    def _calib_save(self, sess, path: str | None = None) -> bool:
        """💾 寫回 config.py＋記憶體 cfg（spec 第 3 節）。

        錨點恰一次才寫（rewrite_config_value 回 None＝不硬寫）；任何失敗都不動記憶體
        cfg——檔案與記憶體不分岔。成功後挖礦標準角本次執行立即生效（>0 解鎖啟動歸位
        /mid 層），回礦標準角下次 episode 生效。
        """
        from . import notify
        from . import config as config_module
        fld, _ = calibrate_pitch.calib_field_names(sess.target)
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        path = path or config_module.__file__
        try:
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
            new_text = calibrate_pitch.rewrite_config_value(text, fld, sess.offset)
            if new_text is None:
                notify.send_message(token, ch,
                    f"❌ 寫檔失敗：config.py 找不到唯一 `{fld}` 錨點——"
                    f"請手抄 `{fld} = {sess.offset}`")
                return False
            # newline="" 保行尾 byte-level 不變——預設轉換會把整檔 LF 洗成 CRLF
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new_text)
        except OSError as e:
            notify.send_message(token, ch,
                f"❌ 寫檔失敗：{e}——請手抄 `{fld} = {sess.offset}`")
            return False
        old = getattr(cfg, fld)
        setattr(cfg, fld, sess.offset)
        notify.send_message(token, ch,
            f"💾 已寫回 `{fld}`：{old} → {sess.offset}（記憶體同步，本次執行立即生效）")
        self.logger.info("校準存檔 %s: %d -> %d", fld, old, sess.offset)
        return True

    def _post_calib_embed(self, warn: str = ""):
        """貼校準卡＋全套反應、記 count 基線（照抄 _post_remote_control 模式）。"""
        from . import notify
        sess = self._calib_session
        fld, _ = calibrate_pitch.calib_field_names(sess.target)
        embed = calibrate_pitch.build_calib_embed(
            sess.target, sess.offset, getattr(cfg, fld), sess.step, warn)
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ok, detail, mid = notify.send_embed(token, ch, embed)
        if not (ok and mid):
            self.log_discord.info("calib post FAIL -> %s", detail)
            return
        seen = {}
        for em in calibrate_pitch.CALIB_EMOJIS:
            added, _ = notify.add_reaction(token, ch, mid, em)
            seen[em] = 1 if added else 0
        sess.message_id = mid
        sess.reactions_seen = seen

    def _repost_calib_embed(self, warn: str = ""):
        """刪舊卡貼新卡（校準卡刻意維持刪貼，不改走 2026-07-26 的清反應路徑）。

        理由：⬆️⬇️🧭 每按一次都會 `_calib_snapshot` 往頻道貼一張新截圖，卡片必然被
        擠上去；而卡片內容（offset／幅度）本身也每次都變。刪貼一次同時解決「內容更新」
        與「回到頻道底」，換成 edit＋清反應反而要多做一次釘底。
        校準是短暫的互動 session，這裡的訊息量本來就有限。"""
        from . import notify
        old = self._calib_session.message_id
        if old:
            notify.delete_message(cfg.discord_bot_token, cfg.discord_channel_id, old)
        self._post_calib_embed(warn)

    def _poll_calib_reactions(self):
        """輪詢校準卡反應（**Discord 輪詢執行緒**）：只寫 _pending_calib_action。

        pending 佔用中不覆蓋（一次一動作；主迴圈消費完才收下一個）——快速連點不會
        疊加成失控的連環拖曳。
        """
        from . import notify
        sess = self._calib_session
        if sess is None or not sess.message_id or self._pending_calib_action is not None:
            return
        message = notify.fetch_message(cfg.discord_bot_token, cfg.discord_channel_id,
                                       sess.message_id)
        if message is None:
            return
        sess.reactions_seen, increments = notify.find_reaction_increments(
            message, sess.reactions_seen, calibrate_pitch.CALIB_EMOJIS)
        for emoji, delta in increments:
            self._pending_calib_px = 0            # 反應無像素參數（文字指令才有）
            self._pending_calib_action = calibrate_pitch.CALIB_ACTIONS[emoji]
            self.log_discord.info("calib %s -> action=%s (+%d)",
                                  emoji, self._pending_calib_action, delta)
            break                                 # 一次輪詢只收一個動作

    def _handle_calib_text(self, content: str):
        """校準卡活躍時的文字指令（Discord 輪詢執行緒）：只寫 pending，主迴圈消費。

        與反應等價（2026-07-19 使用者反映只有反應可點、`上|下 [px]` 沒反應）；
        px 未給用現行幅度。pending 佔用中回「稍候」不覆蓋（一次一動作，與反應
        輪詢同語意）。
        """
        from . import notify
        parsed = calibrate_pitch.parse_calib_text(content)
        if parsed is None:
            return                                # 普通聊天：忽略
        if self._pending_calib_action is not None:
            notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
                                "⏳ 上一個校準動作處理中，稍候再送")
            return
        action, px = parsed
        self._pending_calib_px = px               # 先寫 px 再寫 action（action＝就緒旗標）
        self._pending_calib_action = action
        self.log_discord.info("calib text %r -> action=%s px=%d", content, action, px)

    def _maybe_pitch_guidance(self, content: str):
        """挖礦中收到俯仰指令回指引不靜默（2026-07-19 使用者反映打了沒反應、以為壞掉）。

        只認 pitch/pitch_reset 型輸入（`上|下 [px]`、`仰角 …`、`歸位`），其他一般
        聊天照舊忽略——避免誤嘴。
        """
        from . import notify
        reply = reentry_remote.parse_reply(content)
        if reply is None or reply.kind not in ("pitch", "pitch_reset"):
            return
        notify.send_message(
            cfg.discord_bot_token, cfg.discord_channel_id,
            "⚠ 俯仰指令只在回礦流程或校準卡中有效。要調角度請下 `校準 挖礦` 或 "
            "`校準 回礦`（會發專屬校準卡：⬆️⬇️ 反應或文字 `上|下 [px]`/`歸位` 皆可，"
            "💾 寫回 config）")
        self.log_discord.info("pitch guidance for %r", content)

    def _tick_calibration(self):
        """消費校準動作（主迴圈、paused 分支）。⬆️⬇️🧭 執行後重貼卡＋附新截圖。"""
        if self._pending_calib_action is None:
            return
        action, self._pending_calib_action = self._pending_calib_action, None
        px, self._pending_calib_px = self._pending_calib_px, 0
        sess = self._calib_session
        _, clamp_fld = calibrate_pitch.calib_field_names(sess.target)
        if action == "step":
            sess.step = calibrate_pitch.next_step(sess.step)
            self._repost_calib_embed()
        elif action in ("up", "down"):
            self._sampler_pitch_prepare()
            step = px if px > 0 else sess.step    # 文字指令可帶像素覆寫（`上 12`）
            dy = -step if action == "up" else step   # 上＝dy<0（取樣視窗語意）
            ok = self._pitch_drag_verified(f"[校準] {action} {step}px",
                                           lambda: ic.pitch_nudge(dy))
            sess.offset = calibrate_pitch.apply_calib_step(sess.offset, action, step)
            self._pitch_offset_px = sess.offset
            self._repost_calib_embed(
                "" if ok else "拖曳疑似被吃（記帳照調；懷疑沒動就 🧭 重新絕對定位）")
            self._calib_snapshot()
        elif action == "home":
            self._sampler_pitch_prepare()
            ok = self._pitch_drag_verified(
                "[校準] 歸位到夾限",
                lambda: ic.pitch_reset(getattr(cfg, clamp_fld), 0))
            sess.offset = 0
            self._pitch_offset_px = 0
            self._repost_calib_embed("" if ok else "歸位疑似被吃——再按一次 🧭")
            self._calib_snapshot()
        elif action == "snap":
            self._calib_snapshot()
        elif action == "save":
            self._calib_save(sess)
            self._repost_calib_embed()
        elif action == "exit":
            self._calib_exit(sess)

    def _calib_snapshot(self):
        """校準截圖：落編號樣本（sidecar 記俯仰偏移）＋回傳 Discord（含 offset/幅度標註）。"""
        from . import notify
        sess = self._calib_session
        frame = capture.grab()
        stem = sampler.save_sample(frame, cfg.manual_snapshot_dir, self._pitch_offset_px)
        path = os.path.join(cfg.manual_snapshot_dir, f"{stem}.png")
        ok, detail = notify.send_images_message(
            cfg.discord_bot_token, cfg.discord_channel_id,
            f"🎯 校準 #{stem}｜夾限上 {sess.offset}px｜幅度 {sess.step}px", [path])
        self.log_discord.info("calib snapshot #%s -> %s", stem, detail)

    def _pitch_home_mining(self, label: str) -> bool:
        """歸位到挖礦標準角（sweep_pitch_center_back_px；spec 2026-07-17 兩套具名標準俯角）。

        未校準（<=0）跳過並警告、維持現狀角度（「未校準＝停用」慣例，缺校準不
        靜默改變行為）；被吃重試一次後只警告不擋流程（比照 H046「俯仰被吃不擋
        拍照」——歸位失敗頂多回到「角度不受控」的現狀，不值得為它擋掛機）。
        """
        if not harvester.mining_pitch_home_enabled(cfg.sweep_pitch_center_back_px):
            self.logger.warning(
                "%s：挖礦標準角未校準（sweep_pitch_center_back_px<=0）——跳過歸位", label)
            return False
        self._sampler_pitch_prepare()
        for attempt in (1, 2):
            if self._pitch_drag_verified(
                    f"{label} 挖礦標準角歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                           cfg.sweep_pitch_center_back_px)):
                self._pitch_offset_px = cfg.sweep_pitch_center_back_px
                return True
            self._sampler_pitch_prepare()
        self.logger.warning("%s：挖礦標準角歸位兩輪皆疑似被吃——視角可能非標準角，人工留意",
                            label)
        return False

    def _pitch_restore_if_touched(self):
        """採集收尾俯仰歸位：動過俯仰層（含轉換失敗——reset 可能已改角度）才歸位到置中標準角。

        使用者挖礦視角習慣＝置中（2026-07-11 確認），center_back_px 即校準成置中 → 歸位＝
        回到平常挖礦角度。沒動過（絕大多數採集）零成本零風險。重試/警告收斂進
        _pitch_home_mining（pitch_touched 只在 sweep_pitch 已校準時可能為 True，
        歸位閘在此路徑必過）。
        """
        if not self.harvest.pitch_touched:
            return
        self._pitch_home_mining(f"[{self.harvest.harvest_id}] 收尾")

    def _pitch_drag_verified(self, label: str, drag) -> bool:
        ok, _, _ = self._pitch_drag_measured(label, drag)
        return ok

    def _pitch_drag_measured(self, label: str, drag) -> tuple:
        """執行俯仰拖曳並用前後幀驗證是否生效（量測與 _rotate_verified 同一套）。

        回 (生效與否, mean_diff, changed_frac)——H046 起開場閘要拿原始量測值判
        「凍結」（0.00 逐位元相同）；「被吃」與「凍結」是不同門檻不可混用。

        俯仰改變會讓中央場景帶整片位移；被吃則幾乎逐位元相同。回 True＝有生效。
        前後全幀落盤 snapshots/trace/（2026-07-11 使用者要求）：上次只有「聚焦成功」
        log 沒畫面，查不出「沒作用」是完全沒動/動一半/被選單彈窗擋——落盤後下次
        失效直接看 pitch_*_before/after 兩張圖。

        用獨立 pitch_eaten_* 門檻而非旋轉的 rotation_eaten_*（2026-07-11 實機）：
        地表粒子特效讓無效拖曳的 frac 也有 0.022~0.045，超過旋轉門檻 0.02 → 全部
        誤判「生效」、歸位重試從未觸發。俯仰歸位是冪等操作（拖到夾限飽和再回拉），
        誤判被吃而重做無害 → 門檻可比旋轉激進。旋轉門檻不可共用不可動。
        """
        before_full = capture.grab()
        before = capture.crop(before_full, cfg.rotation_verify_region)
        drag()
        after_full = capture.grab()
        after = capture.crop(after_full, cfg.rotation_verify_region)
        mean_diff = vision.frames_mean_diff(before, after)
        changed = vision.frames_changed_frac(
            before, after, cfg.rotation_changed_pixel_thresh)
        eaten = harvester.rotation_looks_eaten(
            mean_diff, changed,
            cfg.pitch_eaten_mean_diff, cfg.pitch_eaten_changed_frac)
        verdict = "eaten" if eaten else "ok"
        self._snapshot(before_full, f"pitch_{verdict}_before")   # _snapshot 內部 copy，安全
        self._snapshot(after_full, f"pitch_{verdict}_after")
        self.logger.info("%s：前後幀 mean=%s frac=%s -> %s（前後全幀已落盤 trace/pitch_%s_*）",
                         label, mean_diff, changed,
                         "疑似被吃" if eaten else "生效", verdict)
        return (not eaten, mean_diff, changed)

    def _zoom_key_verified(self, key: str) -> bool:
        """I/O 一步＋前後幀驗證被吃（獨立 zoom_eaten_* 門檻）；被吃重聚焦重送一次。

        誤判被吃而重送＝實際多 zoom 一步、net_zoom 記帳偏一步——只影響 ledger
        標注與回傳圖，歸位走絕對基準不受害（與旋轉「寧漏判勿誤重送」取捨相反）。
        """
        for attempt in (1, 2):
            before = capture.crop(capture.grab(), cfg.rotation_verify_region)
            ic.key_press(key)
            ic.settle()
            after = capture.crop(capture.grab(), cfg.rotation_verify_region)
            eaten = harvester.rotation_looks_eaten(
                vision.frames_mean_diff(before, after),
                vision.frames_changed_frac(before, after,
                                           cfg.rotation_changed_pixel_thresh),
                cfg.zoom_eaten_mean_diff, cfg.zoom_eaten_changed_frac)
            if not eaten:
                return True
            self.logger.info("zoom 鍵 %s 疑似被吃（attempt %d/2），重聚焦重送", key, attempt)
            self._focus_roblox()
        return False

    def _zoom_normalize(self, label: str) -> bool:
        """鏡頭距離歸位：I 飽和進第一人稱（冪等、量多無妨）→ O 回拉 K 步＝標準距離。

        boost FOV 隨使用次數累積漂移（作用中變大/到期變小、重進伺服器才重製——
        2026-07-19 使用者確認），鏡頭距離是唯一可歸一的相機自由度：啟動、回礦
        sweep 拍照前、回 MINING、暫停恢復都跑一次，讓偵測幀的鏡頭距離一致。
        未校準（pullback<=0）跳過回 False。回拉段逐步驗證被吃、誤判重送無害
        （歸位冪等，同俯仰歸位 attempt-2 語意）。
        """
        plan = reentry_remote.plan_zoom_normalize(
            cfg.zoom_reset_saturate_presses, cfg.zoom_reset_pullback_steps)
        if not plan:
            return False
        for key, count in plan:
            for _ in range(count):
                if key == "i":
                    ic.key_press(key)                    # 飽和段不驗證（冪等）
                else:
                    self._zoom_key_verified(key)         # 回拉段逐步驗證
            ic.settle(0.4)
        self.logger.info("%s：鏡頭距離歸位完成（I 飽和→O 回拉 %d 步）",
                         label, cfg.zoom_reset_pullback_steps)
        return True

    def _zoom_restore_if_touched(self, ctx):
        """碰過 zoom（net_zoom≠0）才歸位；執行段共用 _zoom_normalize。

        掛在 _rr_finalize＝三個出口（成功回 MINING/跳過交人工/重置作廢）的共同漏斗。
        sweep 前已無條件歸位過的 episode 這裡 net_zoom 已是 0＝直接跳過。
        """
        if ctx.net_zoom == 0:
            return
        self._focus_roblox()
        if self._zoom_normalize(f"[RR#{ctx.episode_id}] zoom 歸位"):
            ctx.net_zoom = 0


def _set_dpi_aware():
    """先把行程設成 DPI-aware（同 mss 之後會做的）。

    否則：啟動量視窗基準時行程還是「未感知」(GetWindowRect 回縮放前值)，
    主迴圈第一次 mss 截圖把行程變「感知」(回縮放後值) → 視窗跑位偵測誤判 resized；
    輸入座標也會在截圖前後不一致。提早設好讓全程一致。
    """
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE（與 mss 一致）
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    _set_dpi_aware()
    # pythonw 無 console，crash 時使用者完全看不到 → 補錯誤對話框 + 寫進 log
    try:
        _run_bot()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        logging.getLogger(diagnostics.LOGGER_NAME).fatal("bot crashed:\n%s", tb)
        try:
            import tkinter.messagebox as mb
            mb.showerror("MiningBot 啟動失敗", tb)
        except Exception:
            pass


def _run_bot():
    bot = Bot()
    if not cfg.hud_enabled:
        bot.run()
        return
    # 機器人跑背景執行緒，狀態小窗在主執行緒（tkinter 需在主執行緒）
    # HUD 先倒數（同一個左下角視窗），倒數結束才啟動 bot.run —— 給使用者時間切到 Roblox
    from .status_hud import StatusHUD
    hud = StatusHUD(bot, cfg.hud_x, cfg.hud_y)
    try:
        hud.run(countdown_s=cfg.launch_countdown_s)
    finally:
        # HUD 關閉（使用者關視窗）或主迴圈結束 → 停止 bot；明確標示是使用者關閉，避免誤會成當機
        if bot._running:
            bot.logger.info("使用者關閉（HUD 視窗關閉）— 停止 bot")
        bot._running = False


if __name__ == "__main__":
    main()
