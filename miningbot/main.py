import os
import time
import logging
import ctypes
import threading
import queue
import winsound

import numpy as np

from .config import DEFAULT as cfg
from .events import EventLog, make_file_sink
from .states import (State, Observation, decide_transition, resolve_state_transition,
                     toggle_pause_action, is_blocked_from_mining, can_consume_ability,
                     should_notify_spawn_chill, update_capacity_streak)
from . import capture, vision, ocr, audio, miner, harvester, diagnostics, window, game_data
from . import sampler, reentry, roblox_menu, remote_aim
from . import input_control as ic
from .preflight import PreflightFacts, run_checks

# Discord 命令清單（小寫）。第一個詞比對此集合才觸發——讓一般聊天訊息不致誤判為命令。
# 不需 ! 前綴：使用者直接打 `status` 即觸發（打 `!status` 也相容，見 _handle_discord_command）。
_DISCORD_COMMANDS = frozenset({
    "list", "keep", "unkeep", "clear", "pause", "resume", "status", "help", "shot",
    "ability",
})

# 遙控器（持久控制訊息）— 反應按鈕。▶️ 繼續挖礦（等同 Q / !resume），⏸️ 暫停（等同 Ctrl+Q / !pause）。
# 用 emoji 而非 Discord Components 按鈕：本專案全程 stdlib urllib，無 Websocket/interaction 基礎建設；
# 反應輪詢模式已由 !list 分頁驗證可行（_poll_list_reactions），沿用同一條路徑最簡。
_REMOTE_RESUME_EMOJI = "▶️"
_REMOTE_PAUSE_EMOJI = "⏸️"
_REMOTE_ABILITY_EMOJI = "⚡"   # 遠端使用能力（遊戲內按一次 X；等同 `ability` 指令）
# 遙控器 embed 標題——啟動時靠它掃頻道「認領」跨重啟殘留的遙控器（find_remote_messages），
# 故字串必須與 _build_remote_embed 的 "title" 一字不差（含中間那個空格）。
_REMOTE_TITLE = "🎮 挖 礦機器人遙控器"


class _HotkeyController:
    """熱鍵邊緣觸發邏輯。down_fn 由外部注入（生產用 GetAsyncKeyState，測試用 mock）。"""

    def __init__(self, down_fn, on_stop, on_toggle, on_quit, on_sample=None):
        self._down = down_fn
        self._on_stop = on_stop
        self._on_toggle = on_toggle
        self._on_quit = on_quit
        self._on_sample = on_sample        # 'R' 手動取樣視窗（未掛＝功能停用）
        self._prev_ctrlq = False
        self._prev_q = False
        self._prev_r = False

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
        r = self._down(0x52)               # 'R'：手動取樣視窗
        if r and not self._prev_r and self._on_sample:
            self._on_sample()
        self._prev_r = r
        # 跳過環境檢查不設專用鍵：F 系多被 Roblox 內建佔用（F8 實測有遊戲功能、
        # 會誤觸），改由 Q 在啟動階段語意分派（states.toggle_pause_action 的 skip_env）
        if f12:
            self._on_quit()


class Bot:
    def __init__(self):
        self.state = State.MINING
        self.paused = False
        self.human_cleared = False
        self.logger = diagnostics.setup_logging(cfg.log_dir, cfg.log_level)
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
                    log=self.log_discord),
                log=self.log_discord))
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
        self._reset_wait_since = 0.0
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
        self._snap_q: queue.Queue = queue.Queue(maxsize=64)
        threading.Thread(target=self._snapshot_worker, daemon=True).start()
        self._prev_frame = None
        self._last_progress = time.time()
        # Q 跳過啟動環境檢查（spec 2026-07-10 第 2 節；原 F8 與 Roblox 內建功能衝突改 Q）：
        # _skip_env_check 由啟動階段的 Q（toggle_pause_action='skip_env'）設定，
        # 只在 _startup_phase=True（run() 環境檢查階段）有效；init 完成後 _startup_phase=False。
        self._skip_env_check = threading.Event()
        self._startup_phase = False
        self._stuck_notified = False
        self._spawn_chill_notified = False        # spawn chill 去抖動：同一波 chill 只通知一次（_check_spawn_chill 在 chill 回落時重新武裝）
        self._last_heartbeat = time.time()
        self._peak_audio_since_hb = 0.0           # 上次 heartbeat 至今的最高音訊分數（捕捉 30s 取樣漏掉的 chill 尖峰）
        self._antiafk_last = 0.0                   # 防掛機：上次按 Space 的時間（0=未在計時；暫停中才啟用）
        self._last_boost = 0.0                       # 上次按 D5 的時間（冷卻用）
        self._last_activity = 0.0                    # 上次按 D4 刷新的時間（定時用）
        self._last_boost_check = 0.0                 # boost 偵測節流：上次真的 edge-match 的時間
        self._boost_present = False                  # 上次偵測到的 boost 瓶子在否（節流間沿用，避免每幀掃）
        self._last_activity_check = 0.0              # D4 冷卻偵測節流：上次真的 edge-match 的時間
        self._activity_present = False               # 上次偵測到的 D4 冷卻圖示在否（節流間沿用）
        self._keep_ores: set[str] = self._load_keep_ores()  # D4 保留清單（持久化；Discord !keep 修改）
        self._last_discord_msg_id: str | None = None  # Discord 命令輪詢基準（首次只記錄不處理）
        # Discord !list 表情分頁追蹤（都在 poll 執行緒上讀寫，無跨執行緒競爭）
        self._list_message_id: str | None = None        # 最新一則 !list 訊息 ID（表情分頁標的）
        self._list_current_world: str | None = None     # 該訊息目前顯示的世界（None=全世界聯集）
        self._list_reactions_seen: dict[str, set[str]] = {}  # 每表情已見使用者 ID（偵測「新點擊」）
        # 遙控器（釘底控制訊息 + 反應按鈕，混合設計 2026-07-09）：狀態變更/按鈕點擊一律
        # edit_message 原地編輯（不產生新訊息、不推播），**只有**被其他訊息擠上去時才刪舊
        # 重貼回頻道底（_repost_remote_control）。啟動時 _ensure_remote_control 先清跨重啟
        # 殘留的舊遙控器（舊設計 id 只在記憶體、重啟後永遠刪不到的根因）再貼新的。
        # 反應 ▶️/⏸️ 由 _poll_remote_reactions 偵測新點擊（seen 採同步語意：使用者取消可再點）。
        self._remote_message_id: str | None = None
        self._remote_reactions_seen: dict[str, set[str]] = {}
        self._remote_last_shown: tuple | None = None    # 上次 PATCH 時的 (paused, state)，避免重複 PATCH
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
        # B3：輪詢執行緒寫 pending、主迴圈讀清；_aim_busy 擋執行中再回覆（不排隊）
        self._pending_aim = None                 # AimReply（輪詢解析結果、主迴圈消費）
        self._aim_busy = False                   # fire 執行中（主迴圈設、輪詢執行緒讀）
        # Discord `ability` 指令／遙控器 ⚡（2026-07-12 spec）：輪詢執行緒寫旗標、
        # 主迴圈消費後按 X。布林於 GIL 下原子（同 human_cleared 跨執行緒寫入模式）。
        self._pending_ability = False
        self._last_reset_check = 0.0
        self._mine_resetting = False
        # Capacity 監看（重置偵測第二信號，2026-07-11）：背景 worker 每輪多讀 Capacity%
        # 快取於此（HUD 顯示）；連續 2 次 ≥100 → 與橫幅訊號 OR 觸發 RESET_WAIT。
        self._capacity_pct = None
        self._capacity_streak = 0
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
            on_sample=self._toggle_sampler,   # R：手動取樣視窗（校準素材收集）
        )
        self._sampler = None                  # SamplerWindow（無 HUD 後備；開著時非 None）
        self._sampler_want = False            # R 熱鍵請求開/關（HUD Tk 執行緒依此同步建/銷 Toplevel）
        self._sampler_ui = None               # SamplerPanel（只在 HUD Tk 執行緒碰）
        self._pitch_offset_px = 0             # 目前俯仰距夾限偏移（歸位後＝reentry_pitch_back_px）
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

    def _load_panel_templates(self) -> list:
        import glob
        tmpls = [vision.load_template(p)
                 for p in sorted(glob.glob(os.path.join(cfg.reentry_panel_dir, "*.png")))]
        if cfg.auto_reenter:
            if tmpls:
                self.logger.info("auto_reenter 啟用，面板模板 %d 張（%s）",
                                 len(tmpls), cfg.reentry_panel_dir)
            else:
                self.logger.warning("auto_reenter 開著但 %s 無面板模板——自動回礦視同關閉；"
                                    "先用 R 鍵截圖＋calibrate_surface --import 裁模板",
                                    cfg.reentry_panel_dir)
        return tmpls

    def _auto_reenter_active(self) -> bool:
        """auto_reenter 的有效值：config 開關＋面板模板存在（缺模板視同關閉）。"""
        return cfg.auto_reenter and bool(self._panel_templates)

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
            doomed = diagnostics.plan_snapshot_cleanup(
                entries, time.time(), cfg.snapshot_max_age_days, cfg.snapshot_max_total_mb)
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
        if self._boost_present:
            return False
        return (time.time() - self._last_boost) > cfg.boost_cooldown_s

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

    # ---- 提醒與快照 ---------------------------------------------------------
    def _alert(self, message: str):
        """本機提醒：嗶聲 + WARNING log。"""
        self.logger.warning("ALERT %s", message)
        try:
            winsound.Beep(880, 400); winsound.Beep(660, 400)
        except RuntimeError:
            pass

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
        try:
            # frame.copy()：主迴圈會覆寫 buffer，背景寫檔前須複製避免讀到髒資料
            self._snap_q.put_nowait((frame.copy(), snap_dir, path, label))
            self.logger.info("SNAPSHOT %s -> %s (async)", label, path)
        except queue.Full:
            self.logger.warning("snapshot 佇列滿，丟棄 %s", label)
        return path

    def _snapshot_worker(self):
        """背景執列緒：從佇列取出畫面寫檔（PNG 編碼+磁碟 I/O 不卡主線）。"""
        import cv2                                  # lazy（同 _save_needs_human_screenshot）
        while True:
            item = self._snap_q.get()
            if item is None:                         # 收到哨兵 → 結束
                break
            frame, snap_dir, path, label = item
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
            except Exception as e:
                self.logger.error("async snapshot failed (%s): %s", label, e)
                # 清掉可能殘留的 .part（imwrite 失敗或例外中斷時避免堆積）
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass

    # ---- 觀察 ---------------------------------------------------------------
    def observe(self, frame) -> Observation:
        score = self.listener.latest_score()
        if score > self._peak_audio_since_hb:
            self._peak_audio_since_hb = score       # 捕捉 30s heartbeat 取樣漏掉的 chill 尖峰
        chill_audio = score >= cfg.audio_match_threshold
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
        return Observation(chill_audio=chill_audio, chill_text=chill_text,
                           harvest_done=False, harvest_failed=False,
                           human_cleared=self.human_cleared,
                           mine_resetting=mine_resetting,
                           reset_complete=self._update_reset_complete(),
                           reentry_done=self._reentry_done,
                           reentry_failed=self._reentry_failed,
                           auto_reenter=self._auto_reenter_active())

    def _update_reset_complete(self) -> bool:
        """RESET_WAIT 中追蹤「banner reset 字樣已消失＋沉澱夠久」（REENTRY 觸發條件）。

        banner 快取由背景 worker 更新（auto_reenter 下 RESET_WAIT 也跑）；字樣一回來
        計時歸零重來——重置訊息可能閃爍，沉澱期就是為了吃掉這種抖動。
        """
        if self.state is not State.RESET_WAIT or not self._auto_reenter_active():
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
                return

    def _check_reset(self, frame) -> bool:
        """讀重置偵測快取。OCR 本體已移背景 worker（_banner_ocr_loop），不再卡主迴圈。"""
        if self.state is not State.MINING:
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
                           or (self._auto_reenter_active()
                               and self.state is State.RESET_WAIT))
                if frame is None or self.paused or not allowed:
                    continue
                now = time.time()
                # 近門檻加速（2026-07-11）：Capacity ≥95 → worker 輪詢加速到 0.5s，
                # 貼著 100% 瞬間停（平時仍 2.0s）。capacity OCR 全滅時沿用 reset_check_interval_s。
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
                # Capacity 監看（重置偵測第二信號）：同輪裁 capacity_region → parse → 快取＋streak
                cap_pct_this = ocr.parse_capacity_pct(
                    ocr.read_text(capture.crop(frame, cfg.capacity_region),
                                  cfg.tesseract_path))
                if cap_pct_this is not None:
                    self._capacity_pct = cap_pct_this       # 讀成功才更新（失敗沿用舊值）
                self._capacity_streak, cap_trigger = update_capacity_streak(
                    self._capacity_streak, cap_pct_this, cfg.capacity_reset_threshold)
                # 訊號合併：worker 對 _mine_resetting 無條件賦值，不 OR 會被下一輪
                # banner=False 蓋掉（關鍵正確性細節）。
                resetting = banner_resetting or cap_trigger
                if resetting and not self._mine_resetting:
                    if banner_resetting:
                        self.logger.info("偵測到礦坑重置: %r", text.strip()[:60])
                    elif cap_pct_this is not None:
                        self.logger.info(
                            "偵測到礦坑重置（Capacity %.0f%% ≥ %.0f，連續2次）",
                            cap_pct_this, cfg.capacity_reset_threshold)
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

    def _ensure_chat_open(self):
        """啟動 UI 前置檢查：聊天框關著就點圖示開啟；複檢仍關 → 重新聚焦再點（最多 chat_open_max_retries 次）。

        點擊被吃的既有對策＝重新聚焦後重送（_focus_roblox；OCR 複檢即驗證，不必如 _rotate_verified 比對幀差）。
        重試用盡仍關 → 保留 WARNING + HUD，另存快照（snapshots/trace/，label chat_open_fail）供診斷，照常啟動
        （不發 Discord：啟動時人在旁邊，比照 preflight 警訊分流慣例，見 CLAUDE.md）。
        """
        t0 = time.perf_counter()
        frame = capture.grab()
        text = ocr.read_text(capture.crop(frame, cfg.chat_input_region), cfg.tesseract_path)
        ocr_ms = (time.perf_counter() - t0) * 1000
        if ocr.contains_any(text, cfg.chat_input_phrases):
            self.logger.info("UI 前置檢查：聊天框已開啟（OCR %.0fms）", ocr_ms)
            return
        self.logger.info("UI 前置檢查：聊天框關閉，點擊圖示開啟（OCR %.0fms）", ocr_ms)
        ic.click_at(*cfg.chat_icon_xy)
        time.sleep(cfg.chat_open_settle_s)
        if self._env_check_skip("聊天框複檢"):   # Q 已按 → 省下 ~2-8s 第二次 OCR
            return
        t0 = time.perf_counter()
        frame = capture.grab()
        text = ocr.read_text(capture.crop(frame, cfg.chat_input_region), cfg.tesseract_path)
        ocr_ms = (time.perf_counter() - t0) * 1000
        if ocr.contains_any(text, cfg.chat_input_phrases):
            self.logger.info("UI 前置檢查：聊天框已開啟（點擊後確認，OCR %.0fms）", ocr_ms)
            return
        # 首次點擊仍關 → 重新聚焦再點（輸入被吃的既有對策）；最多 chat_open_max_retries 次
        for attempt in range(1, cfg.chat_open_max_retries + 1):
            if self._env_check_skip("聊天框重試"):
                return
            self._focus_roblox()
            self.logger.info("UI 前置檢查：聊天框仍未開啟，第 %d 次重試（重新聚焦再點）", attempt)
            ic.click_at(*cfg.chat_icon_xy)
            time.sleep(cfg.chat_open_settle_s)
            t0 = time.perf_counter()
            frame = capture.grab()
            text = ocr.read_text(capture.crop(frame, cfg.chat_input_region), cfg.tesseract_path)
            ocr_ms = (time.perf_counter() - t0) * 1000
            if ocr.contains_any(text, cfg.chat_input_phrases):
                self.logger.info("UI 前置檢查：聊天框第 %d 次重試後開啟（OCR %.0fms）", attempt, ocr_ms)
                return
        self.logger.warning("UI 前置檢查：聊天框仍未開啟，可能影響採集確認；請手動開啟（OCR %.0fms）",
                            ocr_ms)
        self.last_action = "⚠ 聊天框未開啟，採集確認可能失效"
        self._snapshot(frame, "chat_open_fail")   # label 無 reentry/sweep/d3/chill 關鍵字 → snapshots/trace/

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
                time.sleep(cfg.discord_poll_interval_s)
                if self._running:
                    self._poll_discord()
            except Exception:
                pass                                     # 輪詢失敗不中斷主迴圈

    def _poll_discord(self):
        """讀 Discord 新訊息，處理命令；並輪詢 list 分頁與遙控器的反應點擊。"""
        from . import notify
        # 1. 表情輪詢（list 分頁 + 遙控器按鈕；獨立於新訊息，沒新訊息時也要檢查）
        if self._list_message_id:
            self._poll_list_reactions()
        if self._remote_message_id:
            self._poll_remote_reactions()       # 觸發動作時內部 _edit_remote_control 會原地更新
        # 1b. 狀態同步：暫停/挖 礦狀態變了就原地編輯遙控器（PATCH，不推播）。
        # 只用 (paused, state) 當觸發條件避免高頻 PATCH 撞 rate limit；last_action 只在真的
        # PATCH 時順帶刷新（不在觸發條件內，否則每次 last_action 變都會 PATCH）。
        if self._remote_message_id and self._remote_last_shown != (self.paused, self.state.value):
            self._edit_remote_control()
        # 2. 新訊息命令輪詢
        msgs = notify.fetch_messages(
            cfg.discord_bot_token, cfg.discord_channel_id,
            after=self._last_discord_msg_id, limit=10)
        if not msgs:
            return
        # 2a. 釘底（混合設計 2026-07-09）：狀態更新/按鈕點擊都原地編輯（不產生新訊息），
        # **只有**被其他訊息擠上去時才刪舊重貼回頻道底——重貼次數從「每次狀態變」降到
        # 「每次頻道有新訊息」，兼顧「滑到最底就是遙控器」與不洗版。
        if self._remote_message_id and msgs[0]["id"] != self._remote_message_id:
            self._repost_remote_control()
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
            first = content.split()[0].lower() if content else ""
            if first.lstrip("!") in _DISCORD_COMMANDS:
                self._handle_discord_command(content)
            elif self._aim_context is not None and self.state is State.NEEDS_HUMAN:
                # B3：NEEDS_HUMAN 且 aim context 存活時，一般訊息當瞄準回覆（無前綴，spec 第 2 節）
                self._handle_aim_reply(content)

    def _poll_list_reactions(self):
        """輪詢 list 訊息的表情：偵測「新點擊」→ 切換到該世界分頁（編輯同一則訊息）。

        每個表情維護「已見使用者 ID」集合；本次輪詢出現、但不在集合內 = 新點擊 → 切換。
        機器人自己貼表情時已在 list 基線記錄（含自己 ID），故首輪不會誤觸發。
        一次輪詢最多切一頁（避免連續 PATCH）；點到「目前頁」的同行表情為 no-op。

        注意：WORLD_EMOJI = {世界名: 表情}，items() 解包成 (world, emoji)——
        早期版本寫成 ``for emoji, world``（變數對調），導致 get_reactions 傳入世界名
        而非表情 → Discord 永遠查無此反應 → 點表情永遠不翻頁（2026-07-05 修復）。
        """
        from . import notify
        token = cfg.discord_bot_token
        ch = cfg.discord_channel_id
        mid = self._list_message_id
        for world, emoji in game_data.WORLD_EMOJI.items():   # key=世界名, value=表情
            users = notify.get_reactions(token, ch, mid, emoji)
            if not users:
                continue
            user_ids = {u.get("id") for u in users if u.get("id")}
            seen = self._list_reactions_seen.setdefault(emoji, set())
            new_clickers = user_ids - seen
            if not new_clickers:
                continue
            seen.update(user_ids)                  # 標記本次所有按過者為已見
            if world != self._list_current_world:
                embed = game_data.format_event_list_embed(self._keep_ores, world=world)
                notify.edit_message(token, ch, mid, embed=embed)
                self._list_current_world = world
                self.log_discord.info("list 分頁切換 -> %s（%d 個新點擊）", world, len(new_clickers))
                return                              # 一次輪詢只切一頁

    # ---- 遙控器（單一持久訊息 + 反應按鈕）--------------------------------------
    def _build_remote_embed(self) -> dict:
        """組遙控器 embed。狀態欄同步顯示當前挖 礦狀態 + 暫停旗標，每次編輯都更新。"""
        running = not self.paused
        status_text = (f"{'🟢 挖礦中' if running else '🔴 已暫停'}"
                       f"　{self.state.value}"
                       + (f"（{self.last_action}）" if self.last_action and self.last_action != "—" else ""))
        return {
            "title": _REMOTE_TITLE,
            "description": (
                f"**狀態**：{status_text}\n"
                f"\n"
                f" 點 **{_REMOTE_RESUME_EMOJI}** 繼續挖礦（等同按 Q / `resume`）\n"
                f" 點 **{_REMOTE_PAUSE_EMOJI}** 暫停（等同按 Ctrl+Q / `pause`）\n"
                f" 點 **{_REMOTE_ABILITY_EMOJI}** 使用能力（在遊戲內按一次 X；等同 `ability`）\n"
                f"\n"
                f"_狀態變更會直接更新此訊息；被其他通知擠上去時會重貼回頻道底_"
            ),
            "color": 0x57F287 if running else 0xED4245,
            "footer": {"text": "遙控器會維持在頻道最底部"},
        }

    def _post_remote_control(self):
        """貼一則新的遙控器到頻道底，貼 ▶️/⏸️ 反應，記基線。失敗靜默（下輪重試）。

        成功時更新 _remote_message_id 與 _remote_reactions_seen 基線（含機器人自己），
        避免首輪把自己的反應當成新點擊。沿用 !list 已驗證的 send_embed + add_reaction 模式。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        embed = self._build_remote_embed()
        ok, detail, mid = notify.send_embed(token, ch, embed)
        if not (ok and mid):
            self.log_discord.info("remote post FAIL -> %s", detail)
            return
        for em in (_REMOTE_RESUME_EMOJI, _REMOTE_PAUSE_EMOJI, _REMOTE_ABILITY_EMOJI):
            notify.add_reaction(token, ch, mid, em)
        # 基線：機器人自己貼的反應記成「已見」，避免首輪誤觸發
        seen = {}
        for em in (_REMOTE_RESUME_EMOJI, _REMOTE_PAUSE_EMOJI, _REMOTE_ABILITY_EMOJI):
            users = notify.get_reactions(token, ch, mid, em)
            seen[em] = {u.get("id") for u in users if u.get("id")}
        self._remote_message_id = mid
        self._remote_reactions_seen = seen
        # 狀態同步基線：剛貼的 embed 已反映當前 (paused, state)，記下避免下輪重複 PATCH
        self._remote_last_shown = (self.paused, self.state.value)
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

        兩個呼叫路徑：(1) 被其他訊息擠上去時重新釘底（_poll_discord 2a）；(2) 按鈕觸發後刪舊貼新——
        DM 無法移除他人表情（HTTP 403 code 50003），repost 讓新訊息表情歸零、使用者可立即再點。
        刪除結果必記 log（舊設計不記，刪除失敗無從診斷）；刪失敗不擋重貼。
        """
        from . import notify
        old = self._remote_message_id
        if old:
            ok, detail = notify.delete_message(
                cfg.discord_bot_token, cfg.discord_channel_id, old)
            self.log_discord.info("remote repost delete mid=%s -> %s", old, detail)
        self._post_remote_control()

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

    def _poll_remote_reactions(self):
        """輪詢遙控器反應：偵測 ▶️/⏸️ 新點擊 → 觸發 resume/pause，並刪舊貼新遙控器。

        動作觸發後刪舊貼新（DM 無法清除他人表情 HTTP 403 code 50003，repost 是等效方案：
        新訊息表情歸零可立即再點）；代價＝每次點擊 DM 多一則訊息（使用者已接受）。

        seen 集合採「同步語意」（每輪覆寫成當前反應名單，而非累加 update）：使用者自己取消
        反應會被移出 seen，下次再點即可再次觸發。

        守門 ``if not users: continue`` 不可省：get_reactions 失敗回空 list，若照樣同步會把
        seen 清空、下一輪把所有既有反應誤判成新點擊（假觸發）。必須 fetch 有結果才同步。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        mid = self._remote_message_id
        action_taken = None
        for emoji, action in ((_REMOTE_RESUME_EMOJI, "resume"),
                              (_REMOTE_PAUSE_EMOJI, "pause"),
                              (_REMOTE_ABILITY_EMOJI, "ability")):
            users = notify.get_reactions(token, ch, mid, emoji)
            if not users:
                continue                            # get_reactions 失敗→不可同步（見 docstring）
            user_ids = {u.get("id") for u in users if u.get("id")}
            seen = self._remote_reactions_seen.setdefault(emoji, set())
            new_clickers = user_ids - seen
            # 同步成當前名單（取代累加）：使用者取消反應會移出 seen，再點可再次觸發；
            # 沒有新點擊的輪次也要同步，確保取消狀態即時反映。
            self._remote_reactions_seen[emoji] = set(user_ids)
            if not new_clickers:
                continue
            action_taken = action
            if action == "resume":
                # 等同 !resume：清人工旗標 + 解暫停；非阻塞狀態下也是 no-op 安全
                was_blocked = is_blocked_from_mining(self.state, self.paused)
                self.human_cleared = True
                if self.paused:
                    self._resume()
                self.log_discord.info("remote ▶️ resume by %s（was_blocked=%s）",
                                      ",".join(sorted(new_clickers)), was_blocked)
            elif action == "ability":
                # 等同 !ability：只寫旗標（輪詢執行緒鐵律——此方法在 Discord 輪詢執行緒跑，
                # 不碰 input_control），主迴圈 _tick 開頭消費 → 在遊戲內按一次 X。
                self._pending_ability = True
                self.log_discord.info("remote ⚡ ability by %s（queued state=%s）",
                                      ",".join(sorted(new_clickers)), self.state.value)
            else:  # pause
                already = self.paused
                self._pause()
                self.log_discord.info("remote ⏸️ pause by %s（already=%s）",
                                      ",".join(sorted(new_clickers)), already)
            break                              # 一次輪詢只處理一個動作
        if action_taken:
            # 動作觸發後刪舊貼新：表情歸零＝使用者可立即再點
            # （DM 不能 remove_reaction HTTP 403 code 50003，repost 是等效方案）
            self._repost_remote_control()

    def _handle_discord_command(self, content: str):
        """解析並執行 Discord 命令，更新 _keep_ores 並回覆結果。

        命令不需 ! 前綴（`status` 即觸發）；打 `!status` 仍相容——cmd 會 lstrip("!")。
        """
        from . import notify
        token = cfg.discord_bot_token
        ch = cfg.discord_channel_id
        parts = content.split()
        cmd = parts[0].lower().lstrip("!")               # 接受 list 或 !list
        args = parts[1:]

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
                    notify.add_reaction(token, ch, mid, em)
                # 基線：把自己貼的表情記成「已見」，避免首輪把自己的反應當成新點擊
                for em in game_data.WORLD_EMOJI.values():
                    users = notify.get_reactions(token, ch, mid, em)
                    self._list_reactions_seen[em] = {u.get("id") for u in users if u.get("id")}
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
                f"📈 boost {s['boosts']} · 刷新 {s['rerolls']} · 稀有 {s['rares']} · 卡住 {s['stuck']}\n"
                f"📝 保留：{kept}")
            self.log_discord.info("CMD status -> state=%s", self.state.value)

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

        elif cmd == "help":
            notify.send_message(token, ch,
                "**MiningBot 指令**（直接輸入即可，不需 `!` 前綴）\n"
                "`pause` — 遠距暫停（等同 Ctrl+Q；防掛機保持開啟；用 `resume` 恢復）\n"
                "`resume` — 遠距恢復採礦（清 NEEDS_HUMAN/RESET_WAIT/暫停；等同按 Q）\n"
                "`status` — 查詢目前狀態、統計、保留清單\n"
                "`shot` — 截圖目前畫面並傳送（遠端檢查用）\n"
                "`ability` — 遠端按一次 X（手動使用能力；採集/回礦中會等空檔執行）\n"
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
        input_control——輸入操作全部由主迴圈 _tick_remote_aim 消費（比照 _sampler_want 旗標）。
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
        reply = remote_aim.parse_reply(content, len(ctx.candidates), layers)
        if reply is None:
            notify.send_message(token, ch,
                "❓ 看不懂。可用：`2`（射候選②）、`5 C3` / `5U C3`（方位+格子）、"
                "`跳過`（回挖礦）、`全部`（補發其餘方位圖）")
            return
        if self._aim_busy:
            notify.send_message(token, ch, "⏳ 上一發還在執行，稍候")
            return
        if reply.kind == "all":
            sent = 0
            for s in ctx.shots:
                if s.snapshot_path and sent < 8:
                    notify.send_images_message(token, ch,
                        f"方位{s.dir_idx}（層 {s.layer}）", [s.snapshot_path])
                    sent += 1
            self.log_discord.info("AIM all -> 補發 %d 張", sent)
            return
        self._pending_aim = reply          # skip/candidate/grid：主迴圈消費
        notify.send_message(token, ch, f"✅ 收到（{reply.kind}），主迴圈執行中…")
        self.log_discord.info("AIM reply=%s -> pending", reply)

    # ---- 主迴圈 -------------------------------------------------------------
    def run(self):
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
        miner.init_mining_sequence(rotate=self._rotate_verified)
        threading.Thread(target=self._banner_ocr_loop, daemon=True).start()
        threading.Thread(target=self._snapshot_cleanup_once, daemon=True).start()
        if cfg.discord_bot_token and cfg.discord_channel_id:
            threading.Thread(target=self._discord_poll_loop, daemon=True).start()
            self.logger.info("Discord 命令輪詢已啟用（每 %.0fs）", cfg.discord_poll_interval_s)
        self.logger.info("初始化完成，開始挖礦")
        # 啟動自檢（preflight）：背景執行緒——它依賴 rapidocr_available()（可能仍在暖機中，
        # 冪等等鎖不搶跑），且 markers/chill_refs/檔案 mtime 這些 I/O 沒必要卡住主迴圈啟動。
        # WARN 診斷寫進 logs/preflight_alerts.md 供後續 agent 巡檢，**不進即時 Discord 通知**
        # （使用者回饋 2026-07-07：降級診斷不該洗掉要即時閱讀的訊息）。啟動 Discord 通知
        # 只保留「已啟動＋保留事件」這種掛機者當下需要看的內容。
        def _preflight_and_notify():
            self._run_preflight()
            if cfg.discord_bot_token and cfg.discord_channel_id:
                from . import notify
                kept = game_data.format_keep_by_world(self._keep_ores)
                text = f"🤖 Bot 已啟動\n目前保留事件：\n{kept}"
                notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id, text)
                # 遙控器：啟動訊息貼完後清掉跨重啟殘留的舊遙控器、貼新的到頻道底。
                # 之後每輪 _poll_discord 偵測按鈕點擊、狀態變更原地編輯；被擠上去才重貼。
                self._ensure_remote_control()
        threading.Thread(target=_preflight_and_notify, daemon=True).start()
        # 啟動耗時不算「無進度」：_last_progress 在 __init__ 設定，啟動 3.5 分鐘曾被算成
        # 「無進度」→ 一進主迴圈就 STUCK 假警報（spec 2026-07-10 第 5 節）。
        self._last_progress = time.time()
        try:
            while self._running:
                if self.paused:
                    # 防掛機踢除：暫停中每 antiafk_interval_s 按一次 Space
                    self._antiafk_tick("暫停")
                    time.sleep(0.05); continue
                tick_started = time.time()
                frame = capture.grab()
                self._latest_frame = frame       # 發佈給背景 banner OCR worker（唯讀共享）
                obs = self.observe(frame)
                decided = decide_transition(self.state, obs)
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
                self._tick(frame)
                self._heartbeat()
                # 防掛機：NEEDS_HUMAN/RESET_WAIT 也是等待狀態，比照暫停保活（否則需人工
                # 期間閒置過久會被 Roblox 踢出）。恢復挖礦/採集時歸 0，下次等待重新計時。
                if self.state in (State.NEEDS_HUMAN, State.RESET_WAIT):
                    self._antiafk_tick("需人工/重置等待")
                elif self._antiafk_last and not self.paused:
                    self._antiafk_last = 0.0
                # sleep 補償：tick 本身已花掉的時間（grab ~106ms 起跳）從 50ms 目標
                # 節奏裡扣掉，長 tick 後不再多睡滿 50ms；保留 10ms 下限讓出 GIL
                # 給音訊/熱鍵/OCR worker。
                time.sleep(max(0.01, 0.05 - (time.time() - tick_started)))
        finally:
            self._running = False
            self._audio_cap.stop()
            ic.key_up("w"); ic.mouse_up()          # 任何結束都放開按鍵
            self.logger.info("bot stopped")

    def _heartbeat(self):
        """長時間等待時定期記一筆，讓你知道它還在跑、目前音訊分數多少。"""
        now = time.time()
        if now - self._last_heartbeat >= cfg.heartbeat_interval_s:
            self.log_hb.info("heartbeat state=%s audio=%.2f peak=%.2f rms=%.6f",
                             self.state.value, self.listener.latest_score(),
                             self._peak_audio_since_hb, self.listener.latest_rms())
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
            # 清重置快取：OCR 已背景化，RESET_WAIT 期間快取凍在 True（worker 只在
            # MINING 跑）——不清的話回 MINING 第一個 tick 就讀到過期 True 又彈回
            # RESET_WAIT。worker ~2s 內會重驗，banner 真的還在會再次偵測到。
            self._mine_resetting = False
            # 同步清 Capacity 快取＋streak：重置後殘留 ≥100 會立即假觸發（設計文件第 4 點）。
            self._capacity_pct = None
            self._capacity_streak = 0
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
            gf = capture.grab()
            if self._harvest_boost_guard(gf):
                gf = capture.grab()             # 剛補 D5、FOV 已展開 → 必須重抓
            self._pre_scan_ref = gf             # 置中後截 reference（排除裝備假陽性）
            # giveup 前後對比圖的「前」基準只在這裡取一次（H020：_reharvest_sweep 會
            # 重拍 _pre_scan_ref——若 D3 其實已採到才 RESWEEP，重拍的已是「採完後」畫面
            # → 送人工的 before/after 兩張一模一樣、對比失去鑑別力）
            self._harvest_origin_ref = self._pre_scan_ref
            harvester.execute_scan()            # 裝備 D2 + 點擊觸發掃描
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
            # 入口聚焦失敗 → 降級 NEEDS_HUMAN（比照 MINING 入口）：REENTRY 全程都在
            # 送鍵/點擊，焦點不在 Roblox 上會全部送錯視窗、白白燒光 reroll 次數。
            if not self._focus_roblox():
                self.logger.warning("進入 REENTRY 但無法聚焦 Roblox -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法聚焦 Roblox（自動回礦前），請確認遊戲視窗後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)
                return State.NEEDS_HUMAN
            # click-to-move 導航依賴 Movement Mode=Click to Move；切不過去導航無意義，
            # reroll 也救不了 → 直接降級 NEEDS_HUMAN（比照聚焦失敗的既定模式）。
            if not self._set_movement_mode(cfg.movement_mode_reentry):
                self.logger.warning("進入 REENTRY 但無法切換 Movement Mode -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法切換至 Click to Move（自動回礦前），請手動確認設定後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)
                return State.NEEDS_HUMAN
            now = time.time()
            self._reentry = reentry.ReentryState(phase_started=now, attempt_started=now)
            self._reentry_done = False
            self._reentry_failed = False
            self._reentry_ref = None
            self._reentry_panel_xy = None
            self._move_diffs = []
            self._last_nav_frame = None
            ic.key_up("w"); ic.mouse_up()            # RESET_WAIT 本已放開，保險再放一次
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
            self._reset_wait_since = time.time()     # reset-chime 擷取的 arm 計時起點
            # Movement Mode 前置檢查延後到此：session 內第一次重置才標 due，
            # 等 _on_enter(MINING) 恢復挖礦時消費（2026-07-11 需求）。
            # 再閘一層 _auto_reenter_active（同日追加需求）：Movement Mode 只為回礦
            # click-to-move 服務，自動回礦（R 取樣校準＋auto_reenter）完成前「備而不用」
            # ——挖礦本身的設定不會被動到，跑選單鏈只是浪費 71-82s 還多一次搶輸入風險。
            if not self._movement_mode_checked and self._auto_reenter_active():
                self._movement_check_due = True

    def _tick(self, frame):
        self._update_reset_chime_active()
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

    def _update_reset_chime_active(self):
        """依 state＋計時決定 reset-chime recorder 是否收音；離開 RESET_WAIT 清空重錄。

        先把旗標設 False 再 reset() recorder，避免音訊執行緒在 reset 當下還餵 chunk
        （競態最壞＝邊界丟一個 chunk，對校準無害）。"""
        rec = self._reset_chime_recorder
        if rec is None:
            return
        active = (self.state is State.RESET_WAIT
                  and self._reset_wait_since > 0.0
                  and time.time() - self._reset_wait_since >= cfg.reset_chime_arm_delay_s)
        if active and not self._reset_chime_active:
            self._reset_chime_active = True
            self.logger.info("🔔 重置鈴聲擷取啟動（RESET_WAIT 滿 %.0fs）", cfg.reset_chime_arm_delay_s)
        elif not active and self._reset_chime_active:
            self._reset_chime_active = False
            rec.reset()

    def _tick_mining(self, frame):
        if getattr(self, '_post_harvest_watch', 0) > 0:
            self._log_w_state("MINING post-harvest tick")
            self._post_harvest_watch -= 1
        flags = miner.EventFlags(
            boost_expired=self._boost_needs_refresh(frame),
            activity_event=self._activity_ready(frame),   # D4：冷卻好就右鍵刷新事件
            scan_event=False,                             # D2 只在採集流程用
            cave_event=False,                             # Z 雷達擱置
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
            miner.use_boost()
            self._last_boost = time.time()           # 設冷卻，避免瓶子出現前重複按
        elif action == "USE_D4":
            # D4 前先讀事件文字，判斷該保留（左鍵）還是刷新（右鍵）。
            # 背景 worker（_banner_ocr_loop）每 2s 已 OCR 同一區——快取夠新就直接用，
            # 免再付 ~400ms 同步 OCR 卡主迴圈；過舊（worker 剛好沒跑到）才同步後備。
            if time.time() - self._banner_text_at <= cfg.reset_check_interval_s * 2:
                event_text = self._banner_text.strip()
            else:
                event_text = ocr.read_text(capture.crop(frame, cfg.chill_text_region),
                                           cfg.tesseract_path).strip()
                self._maybe_detect_world(event_text)
            ev = game_data.match_event(event_text)
            if ev and game_data.is_kept(event_text, self._keep_ores):
                self.logger.info("D4: 保留事件 %s（在 keep 清單中）", ev["ore"])
                self.last_action = f"保留事件: {ev['ore']}"
                miner.use_activity_keep()
            else:
                self.log_act.info("mining: 刷新事件 -> D4 右鍵 (%s)",
                                  ev["ore"] if ev else "未知/無事件")
                self.last_action = "刷新事件(D4)"
                miner.use_activity()
            self.stats["rerolls"] += 1
            self._last_activity = time.time()
        elif action is None:
            self.last_action = "挖礦中"

        # 卡住偵測：用中央遊戲區判斷（避開左下狀態小窗）
        cur = capture.crop(frame, cfg.stuck_region)
        if self._prev_frame is not None:
            diff = vision.frame_mean_diff(cur, self._prev_frame)
            if diff >= cfg.stuck_frame_diff_threshold or action is not None:
                self._last_progress = time.time()
                self._stuck_notified = False
        self._prev_frame = cur
        if (not self._stuck_notified
                and time.time() - self._last_progress > cfg.stuck_timeout_s):
            self.log.log("STUCK", reason=f"{cfg.stuck_timeout_s}s 無進度")
            self.stats["stuck"] += 1
            self._snapshot(frame, "stuck")
            self._alert("腳本可能卡住了")
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
        miner.use_boost_harvest()
        self._last_boost = time.time()      # 冷卻 gate：瓶子出現前不重複按
        self._boost_present = True          # 樂觀更新快取；下個節流窗會重驗
        time.sleep(cfg.boost_fov_settle_s)  # 等 FOV 展開，之後抓的幀才是最終座標
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
            collect_rejects=collect_rejects)

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
            shape_roi_px=cfg.tracker_shape_roi_px)

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

    def _sweep_for_tracker(self, excl, ref):
        """全 8 方位掃描：rotate_right×7 → 每方位雙幀穩定偵測 → 旋轉回最佳方位。
        回傳 (最佳追蹤框螢幕座標 (cx, cy) | None, 掃描過程是否看過穩定候選)。
        had_candidates 讓呼叫端分流 sweep 失敗（H019）：全程沒看到→人工；
        看到過但 verify 失敗（FOV 位移/邊緣裁切）→ 重掃一次。

        早停：某方位雙幀穩定且 edge ≥ tracker_shape_early_exit（遠高於裝備上限）→ 人已在
        該方位，直接確定、免掃完剩餘方位也免轉回 verify。分數不夠高者仍收集，掃完選
        「x 最居中」的候選（pick_sweep_candidate，H019 對策）+ verify（保留「不確定就繼續掃」）。
        """
        hid = self.harvest.harvest_id   # 本輪編號；sweep 偵測敘事行前綴 [Hxxx]（誤判常源於此階段）
        NUM_DIRS = 8
        candidates = []  # [(dir_idx, position)]
        sweep_frames = []  # 各方位全幀（.copy——grab buffer 會被下一幀覆寫）；全空→交人工時落盤診斷
        sweep_rejects_by_dir = {}  # remote-aim：各方位近失候選（collect_rejects 收集）
        for i in range(NUM_DIRS):
            f = capture.grab()
            # ★ boost 守門（H026）：sweep 一輪 ~10-19s，D5 常在中段到期。到期即補則各方位
            #   都在同一（有 buff）FOV 下偵測，候選座標彼此一致、也與稍後開火時一致。
            if self._harvest_boost_guard(f):
                f = capture.grab()
            if cfg.sweep_empty_snapshot:
                sweep_frames.append((i, f.copy()))
            rejs = [] if cfg.remote_aim_enabled else None
            r1 = self._find_tracker(f, excl, ref, log=self._tracker_log, with_score=True,
                                    collect_rejects=rejs)
            sweep_rejects_by_dir[i] = rejs or []
            if r1:
                m1 = (r1[0], r1[1])
                time.sleep(0.08)
                gf = capture.grab()
                r2 = self._find_tracker(gf, excl, ref, log=self._tracker_log, with_score=True)
                m2 = (r2[0], r2[1]) if r2 else None
                if m2 and abs(m1[0] - m2[0]) < 8 and abs(m1[1] - m2[1]) < 8:
                    # ★ 高吻合度早停：雙幀穩定 + edge 很高 → 直接確定（人已在 dir i，net=i）
                    # 僅在有實機模板時早停（此時 r2[2] 是 edge 分數）；純 HSV 的 colored_frac
                    # 尺度不同（裝備可達 0.75-0.88），不可用同門檻，故 gate 在 shape_templates。
                    if self._shape_templates and r2[2] >= cfg.tracker_shape_early_exit:
                        self.log_harvest.info(
                            "[%s] sweep dir=%d: 高吻合 edge=%.2f ≥%.2f，早停確定 %s（免掃完/免轉回）",
                            hid, i, r2[2], cfg.tracker_shape_early_exit, m2)
                        path = self._hsnap(gf, "sweep_confirmed_%d_%d" % m2)
                        self.log.log("TRACKER_FOUND", harvest_id=hid, pos=str(m2), image_path=path)
                        return m2, True
                    self.log_harvest.info("[%s] sweep dir=%d: 穩定追蹤框 %s (edge=%.2f)", hid, i, m2, r2[2])
                    candidates.append((i, m2))
                else:
                    self.log_harvest.info("[%s] sweep dir=%d: 不穩定 m1=%s m2=%s", hid, i, m1, m2)
            else:
                self.log_harvest.info("[%s] sweep dir=%d: 未偵測到追蹤框", hid, i)
            if i < NUM_DIRS - 1:
                # 驗證式旋轉：settle 含在內；沒轉成不計數（計數＝實際角度，restore 才準）。
                # 沒轉成時 dir 索引會與實際方位錯一格——頂多重看同方位，偵測不受影響。
                if self._rotate_verified(+1):
                    self.harvest.net_rotations += 1

        if not candidates:
            self.log_harvest.info("[%s] sweep: 全 8 方位均未找到追蹤框", hid)
            if cfg.sweep_empty_snapshot and sweep_frames:
                # 每個方位落盤全幀：這類交人工的真框常薄/暗/被遮、shape-edge 低到 hard_rej，
                # 過去只有觸發幀可查（看不到 sweep 各方位實況）→ 存下來供事後跑 find_tracker
                # 診斷、或裁成模板補進 assets/markers（見 project_sweep_all_empty_giveups）。
                for di, fr in sweep_frames:
                    path = self._hsnap(fr, harvester.sweep_snapshot_label(self.harvest.pitch_layer, di))
                    self._sweep_shots.append(remote_aim.SweepShot(
                        layer=self.harvest.pitch_layer, dir_idx=di,
                        snapshot_path=path or "", rejects=sweep_rejects_by_dir.get(di, [])))
                self.log_harvest.info("[%s] sweep 全空：已存 %d 張各方位全幀供診斷",
                                      hid, len(sweep_frames))
            return None, False

        # 同一顆框常橫跨相鄰 2~3 個方位（45° 視野重疊）→ 選 x 最居中者（H019 對策）：
        # 舊版 candidates[0]（最先看到的方位）可能離中心 500px+，轉回期間 D5 到期 FOV
        # 收縮把框往外推 → 撞進 find_tracker 邊緣 10% 排除帶 → verify 整幀找不到。
        best_dir, best_pos = harvester.pick_sweep_candidate(candidates, cfg.screen_w)
        # 目前在 dir 7（rotate_right × 7）→ 走最短方向回 best_dir（plan_return_rotations，
        # 正=右轉 wrap 360°、負=左轉）：舊版一律左轉 (7-best_dir) 次，best_dir=0 要白轉
        # 7 次 ~2.4s；右轉 1 次 wrap 就到。net_rotations 照實累計（restore_actions 會再
        # normalize 取最短，淨 8 ≡ 回原角不轉）。
        delta = harvester.plan_return_rotations(NUM_DIRS - 1, best_dir, NUM_DIRS)
        self.log_harvest.info("[%s] sweep: 最佳方位 dir=%d pos=%s，往%s轉 %d 次對齊（最短路徑）",
                              hid, best_dir, best_pos, "右" if delta > 0 else "左", abs(delta))
        for _ in range(abs(delta)):
            d = 1 if delta > 0 else -1
            # 驗證式旋轉（settle 含在內）；沒轉成不計數。轉不到 best_dir 時下方 verify
            # 會失敗 → 走既有「看過框但 verify 失敗」重掃分流，不會誤射。
            if self._rotate_verified(d):
                self.harvest.net_rotations += d

        # 對齊後驗證追蹤框仍在
        time.sleep(0.2)
        verify_f = capture.grab()
        vm = self._find_tracker(verify_f, excl, ref, log=self._tracker_log)
        if vm and abs(vm[0] - best_pos[0]) < 30 and abs(vm[1] - best_pos[1]) < 30:
            self.log_harvest.info("[%s] sweep: 驗證成功 %s", hid, vm)
            path = self._hsnap(verify_f, "sweep_confirmed_%d_%d" % vm)
            self.log.log("TRACKER_FOUND", harvest_id=hid, pos=str(vm), image_path=path)
            return vm, True
        elif vm:
            self.log_harvest.info("[%s] sweep: 位置偏移 %s→%s，用新位置", hid, best_pos, vm)
            path = self._hsnap(verify_f, "sweep_confirmed_%d_%d" % vm)
            self.log.log("TRACKER_FOUND", harvest_id=hid, pos=str(vm), image_path=path)
            return vm, True
        else:
            self.log_harvest.info("[%s] sweep: 驗證時追蹤框消失（掃描位置 %s 未通過 verify），重試",
                                 hid, best_pos)
            return None, True

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
        if cfg.remote_aim_enabled and self._sweep_shots:
            ctx = remote_aim.build_aim_context(
                self._sweep_shots, self.harvest.net_rotations,
                self.harvest.pitch_layer, self.harvest.harvest_id,
                now=time.time(), max_candidates=cfg.remote_aim_max_candidates)
            self._aim_context = ctx
            aim_paths = self._render_aim_shots(ctx)      # 疊圖＋落盤，回 [(caption, path)]
            if aim_paths:
                groups.insert(0, ("aim", [p for _, p in aim_paths[:4]]))
        if groups:
            self._needs_human_extra_meta["image_groups"] = groups

        self.state = State.NEEDS_HUMAN
        self._on_enter(State.NEEDS_HUMAN, frame)

    def _render_aim_shots(self, ctx):
        """把有候選的 SweepShot 疊圖（候選編號＋網格）另存，回 [(caption, path)]。

        只發「有候選的方位」防洗版（spec）；讀快照→疊圖→寫檔都在 giveup 當下同步做
        （一次性、非熱路徑）。讀檔失敗跳過該張（快照是非同步寫檔，極端下可能還沒落盤）。
        依「該方位最高分候選」排序，最像框的方位先發；最多 4 張。
        """
        import cv2
        by_shot = {}
        for c in ctx.candidates:
            by_shot.setdefault((c.layer, c.dir_idx), []).append(c)
        out = []
        for shot in ctx.shots:
            key = (shot.layer, shot.dir_idx)
            cands = by_shot.get(key)
            if not cands or not shot.snapshot_path:
                continue
            img = cv2.imread(shot.snapshot_path)
            if img is None:
                continue
            overlaid = remote_aim.draw_overlay(img, cands, grid=True)
            path = shot.snapshot_path.replace(".png", "_aim.png")
            cv2.imwrite(path, overlaid)
            best = max(c.score for c in cands)
            out.append((best, f"方位{shot.dir_idx}（層 {shot.layer}）", path))
        out.sort(key=lambda t: -t[0])
        return [(caption, path) for _, caption, path in out[:4]]

    # ---- B3：遠端瞄準回覆消費 + fire 執行（主迴圈執行緒）-------------------
    def _tick_remote_aim(self, frame, reply):
        """消費一則瞄準回覆（主迴圈執行緒）。skip→回挖礦；candidate/grid→對齊+重掃+開火+驗證。

        一發＝一次 D3＋一個 verify 窗口，不自動 RETRY/RESWEEP（spec：要不要再射由使用者決定，
        每次回報附最新截圖）。全程 remote_aim_budget_s 預算防卡死。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        ctx = self._aim_context
        if reply.kind == "skip":
            self.logger.info("AIM skip -> 回挖礦")
            self._aim_context = None
            self.human_cleared = True          # 下 tick decide_transition 回 MINING（同 resume）
            notify.send_message(token, ch, "▶️ 跳過這顆，回挖礦")
            return
        # 解目標 (層, 方位, 位置先驗)
        if reply.kind == "candidate":
            c = ctx.candidates[reply.number - 1]
            tgt_layer, tgt_dir, prior = c.layer, c.dir_idx, c.pos
        else:
            tgt_layer, tgt_dir = reply.layer, reply.dir_idx
            prior = remote_aim.grid_cell_center(reply.cell)
        self._aim_busy = True
        try:
            ok, detail = self._execute_remote_fire(ctx, tgt_layer, tgt_dir, prior)
        finally:
            self._aim_busy = False
        if ok:
            self._aim_context = None           # 成功收尾（_execute 內已切 MINING）
        else:
            # 失敗：留在 NEEDS_HUMAN、context 續命，附當下截圖讓使用者再決定
            cur = capture.grab()
            p1 = self._snapshot(cur, "aim_fail_scene")
            p2 = self._snapshot_crop(cur, cfg.chat_review_region, "aim_fail_chat")
            paths = [p for p in (p1, p2) if p]
            msg = f"❌ 未確認命中（{detail}）。可再回編號/格子重試，或 `跳過` 回挖礦"
            if paths:
                notify.send_images_message(token, ch, msg, paths)
            else:
                notify.send_message(token, ch, msg)

    def _execute_remote_fire(self, ctx, tgt_layer, tgt_dir, prior):
        """對齊姿態 → 重新 D2 掃描 → ROI 放寬重找 → 開火 → 聊天驗證。回 (confirmed, 說明)。

        姿態記帳在 ctx（絕對姿態，與 self.harvest 的 net_rotations 分開——勿混用兩個來源）；
        對齊轉動的「被吃不計」規則比照 _sweep_for_tracker：只計實際轉成的步數。
        """
        from . import notify
        deadline = time.time() + cfg.remote_aim_budget_s
        hid = ctx.harvest_id
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
        gf = capture.grab()
        if self._harvest_boost_guard(gf):
            gf = capture.grab()
        ref = gf
        harvester.execute_scan()
        self._confirm_scan("remote-aim")
        # 3. ROI 放寬重找：先正常門檻，再 shape_threshold=0（colored 過即收、edge 排序）
        pos = None
        for thr in (cfg.tracker_shape_threshold, 0.0):
            if time.time() > deadline:
                return False, "預算用盡"
            f2 = capture.grab()
            pos = vision.find_tracker_near(
                f2, prior, cfg.remote_aim_refind_radius_px,
                frame_margin_frac=0.0, exclude=_excl,
                reference_bgr=ref, shape_templates=self._shape_templates,
                shape_threshold=thr, shape_hard_floor=0.0,
                shape_scales=cfg.tracker_shape_scales,
                shape_roi_px=cfg.tracker_shape_roi_px)
            if pos:
                self.logger.info("[%s] AIM 重找命中 (thr=%.2f) -> %s", hid, thr, pos)
                break
        if not pos:
            pos = prior                        # 4c. 直接朝先驗點開火（miss 代價＝一發）
            self.logger.info("[%s] AIM 重找全滅 -> 直接朝先驗點開火 %s", hid, pos)
        # 4. 開火（既有 D3 序列：2 → 0.15s → 3 → 0.3s → click hold 0.4 → 0.5s）
        self._hsnap(capture.grab(), "aim_fire_%dx%d" % tuple(pos[:2]))
        ic.key_press("2"); time.sleep(0.15)
        ic.key_press("3"); time.sleep(0.3)
        ic.click_at(int(pos[0]), int(pos[1]), hold=0.4)
        time.sleep(0.5)
        # 5. 驗證：基準 OCR（開火後才跑）＋窗口輪詢（幀差閘）＋最終確認
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
                self.logger.info("[%s] sweep 超時 -> 人工 (t=%.1f)", hid, self.harvest.elapsed_s)
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
                    self.logger.info("[%s] sweep 看過穩定框但 verify 失敗（FOV 位移/邊緣裁切）"
                                     "-> 重掃一次 (%d/1)", hid, self.harvest.verify_fail_resweeps)
                    self._reharvest_sweep()
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
                self.logger.info("[%s] sweep 未找到追蹤框（俯仰層剩 %d）-> 人工",
                                 hid, len(self.harvest.pitch_layers_left))
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
        aim_frame = capture.grab()
        refind = self._find_tracker(aim_frame, _excl, reference_bgr=_ref)
        if refind is None:
            self.logger.info("[%s] 開火前重定位失敗（框已消失/FOV 變動）-> 重新 D2 掃描＋全方位重掃", hid)
            self._reharvest_sweep()
            return
        if abs(refind[0] - cx) >= 8 or abs(refind[1] - cy) >= 8:
            self.log_harvest.info("[%s] 開火前重定位: (%d,%d) -> (%d,%d)（FOV/視角位移已吸收）",
                             hid, cx, cy, refind[0], refind[1])
        cx, cy = refind
        self._target_marker = (cx, cy)
        self.log_harvest.info("[%s] 採集: 追蹤框當下位置 (%d,%d) -> D3 點選 (attempt=%d)",
                         hid, cx, cy, self.harvest.d3_attempts + 1)
        self._hsnap(aim_frame, "d3_fire_%dx%d" % (cx, cy))  # 關鍵診斷截圖：開火用的「當下」幀（含追蹤框）
        ic.key_press("2")           # 先切回 D2，確保 D3 不在裝備狀態（再按 3 是切入非 toggle）
        time.sleep(0.15)
        ic.key_press("3")
        time.sleep(0.3)          # 等 D3 裝備動畫（實測 0.3s 即足夠，原 0.6s 過長）
        ic.click_at(cx, cy, hold=0.4)  # hold click 才能觸發 D3（實測瞬間點無效）
        time.sleep(0.5)          # 等伺服器初步回應（後續交給輪詢，不再單幀判生死）

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
        new_lines = ocr.extract_new_found_lines_multi(chat_before, chat_after, cfg.found_keywords)
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
        for b, a in zip(chat_before, chat_after):
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
    def _tick_reentry(self, frame):
        """REENTRY 每 tick 一步。決策純函式在 reentry.py，這裡只做 I/O。

        任一步失敗統一走 _reentry_reroll（按回到地表換重生點）；
        attempts 用盡 → _reentry_failed=True（decide_transition → NEEDS_HUMAN）。
        """
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
        crop = capture.crop(capture.grab(), cfg.scan_confirm_region)
        ok = harvester.scan_succeeded([ocr.read_text(crop, cfg.tesseract_path)])
        self.log_harvest.info("[scan-confirm] %s ok=%s mode=%s", where, ok, cfg.scan_confirm_mode)
        if ok or cfg.scan_confirm_mode == "observe":
            return True
        self.logger.warning("[scan-confirm] %s 未見 Local → 重新聚焦＋重掃一次", where)
        self._focus_roblox()
        harvester.execute_scan()
        crop = capture.crop(capture.grab(), cfg.scan_confirm_region)
        ok = harvester.scan_succeeded([ocr.read_text(crop, cfg.tesseract_path)])
        self.log_harvest.info("[scan-confirm] %s retry ok=%s", where, ok)
        return True   # 重試後不論成敗都繼續 sweep（寧多掃勿誤棄；失敗已留 WARNING）

    def _reharvest_sweep(self):
        """重置目標、重新 D2 掃描並回到 sweep 階段（D3 連續未命中或框被搶走時呼叫）。"""
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
        if getattr(self, "_pre_scan_ref", None) is None:
            self._pre_scan_ref = capture.grab()  # 防禦：理論上進 HARVESTING 必已拍
        harvester.execute_scan()
        self._confirm_scan("resweep")
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
        self.logger.info("防掛機：%s按 Space（%s中等超過 %.0f 分鐘）",
                         "已失焦→重聚焦 Roblox 後" if refocused else "",
                         context, cfg.antiafk_interval_s / 60)
        self._antiafk_last = now

    def _pause(self):
        """暫停：放開所有按鍵、停住。idempotent（已暫停再呼叫無副作用）。

        Ctrl+Q 與 Q 的暫停走同一條路徑——兩者暫停行為完全一致，差別只在 Q 能再按一次
        繼續、Ctrl+Q 只暫停（見 _toggle_pause / on_stop 接線）。不再有獨立的「強制停止」。
        """
        if not self.paused:
            self.paused = True
            ic.key_up("w"); ic.mouse_up()
            self._antiafk_last = time.time()       # 開始防掛機計時
            self.log.log("PAUSED")
            self.logger.info("PAUSED — 按 Q 繼續")

    def _resume(self):
        """繼續：清除暫停並重新握住 W + 左鍵（與啟動/_on_enter(MINING) 相同的完整序列）。"""
        self.paused = False
        self._antiafk_last = 0.0                   # 重置防掛機計時（下次暫停重新從 0 開始）
        self.log.log("RESUMED")
        self.logger.info("RESUMED")
        if self.state is State.MINING:
            # 暫停期間焦點可能飄走（使用者切去別視窗看 Discord/瀏覽器）；恢復挖礦前
            # 先重新聚焦 Roblox。失敗不交人工——使用者正在按 Q 注視著，下次 mining
            # tick 的視窗跑位偵測會接手（REFOCUS action；那條路徑失敗才交人工）。
            self._focus_roblox()
            miner.init_mining_sequence(rotate=self._rotate_verified)

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

    # ---- R 鍵手動取樣（校準素材收集；docs/superpowers/specs/2026-07-08-mine-reentry-design.md）--
    def _toggle_sampler(self):
        """R：開/關取樣視窗。開啟時若正在挖礦先自動暫停——取樣的俯仰拖曳/截圖
        不能跟挖礦的 W+左鍵互搶輸入。關閉不自動 resume（使用者取樣完自己按 Q，
        視角多半已被拖歪，直接恢復挖礦反而糟）。

        HUD 模式（hud_enabled=True）：本方法跑在熱鍵執行緒，只翻 _sampler_want 旗標，
        實際建/銷窗由 HUD 的 Tk 主執行緒 _poll→sync_sampler_ui 負責（背景執行緒建
        第二個 tk.Tk() 會靜默失敗，OS 層無窗，實機驗證 2026-07-10）。
        無 HUD 模式：沿用執行緒版 SamplerWindow（主執行緒沒有別的 Tk root）。
        """
        if cfg.hud_enabled:
            self._sampler_want = not self._sampler_want
            if self._sampler_want:
                if not self.paused and self.state not in (State.NEEDS_HUMAN, State.RESET_WAIT):
                    self._pause()
                self.logger.info("取樣視窗開啟請求 (R)：HUD 執行緒將建窗（≤0.3s）")
            else:
                self.logger.info("取樣視窗關閉請求 (R)")
            return
        if self._sampler is not None and self._sampler.alive:
            self._sampler.close()
            self._sampler = None
            self.logger.info("取樣視窗關閉 (R)")
            return
        if not self.paused and self.state not in (State.NEEDS_HUMAN, State.RESET_WAIT):
            self._pause()
        self._sampler = sampler.SamplerWindow(
            on_capture=self._sampler_capture,
            on_pitch_reset=self._sampler_pitch_reset,
            on_pitch_nudge=self._sampler_pitch_nudge,
            step_px=cfg.sample_pitch_step_px,
            initial_offset=self._pitch_offset_px)
        self.logger.info("取樣視窗開啟 (R)：俯仰歸位/微調＋編號截圖")

    def sync_sampler_ui(self, tk_root):
        """HUD _poll 每 300ms 在 Tk 主執行緒呼叫：把取樣視窗實際狀態同步到 R 熱鍵請求。

        為何不能在熱鍵執行緒直接開窗：主執行緒已有 HUD 的 Tk mainloop 時，
        背景執行緒建第二個 tk.Tk() 的視窗永遠不會出現在 OS 層（實機驗證 2026-07-10），
        所以 Tk 物件只能由 HUD 執行緒建立/銷毀，熱鍵只翻 _sampler_want 旗標。
        """
        alive = self._sampler_ui is not None and self._sampler_ui.alive
        act = sampler.sync_action(self._sampler_want, alive)
        if act == "open":
            self._sampler_ui = sampler.SamplerPanel(
                tk_root,
                on_capture=self._sampler_capture,
                on_pitch_reset=self._sampler_pitch_reset,
                on_pitch_nudge=self._sampler_pitch_nudge,
                step_px=cfg.sample_pitch_step_px,
                initial_offset=self._pitch_offset_px,
                on_user_close=self._sampler_user_closed)
            self.logger.info("取樣視窗開啟 (R)：俯仰歸位/微調＋編號截圖")
        elif act == "close":
            self._sampler_ui.close()
            self._sampler_ui = None
            self.logger.info("取樣視窗關閉 (R)")

    def _sampler_user_closed(self):
        """使用者按視窗 X 關閉（Tk 執行緒進來）：旗標歸位，避免下一輪 poll 重開。"""
        self._sampler_want = False

    def _sampler_pitch_prepare(self):
        """R 視窗俯仰鈕共用前置：聚焦回遊戲＋游標移進畫面＋沉澱。

        滑鼠事件送到「游標所在」視窗（鍵盤才看焦點）：點按鈕當下游標還停在
        取樣小視窗上，右鍵拖曳會落在 Tk 視窗、Roblox 收不到 → 先把游標移進遊戲畫面。
        settle（2026-07-11 實機）：log 三次「聚焦成功」但俯仰全沒生效——焦點剛從
        小視窗切回遊戲就送右鍵拖曳會被吃（與旋轉鍵在焦點切換後被吃同家族）→
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

    def _pitch_restore_if_touched(self):
        """採集收尾俯仰歸位：動過俯仰層（含轉換失敗——reset 可能已改角度）才歸位到置中標準角。

        使用者挖礦視角習慣＝置中（2026-07-11 確認），center_back_px 即校準成置中 → 歸位＝
        回到平常挖礦角度。沒動過（絕大多數採集）零成本零風險。
        """
        if not self.harvest.pitch_touched:
            return
        for attempt in (1, 2):
            if self._pitch_drag_verified(
                    f"[{self.harvest.harvest_id}] 收尾俯仰歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.sweep_pitch_clamp_px,
                                           cfg.sweep_pitch_center_back_px)):
                return
            self._focus_roblox()
            ic.settle(cfg.sampler_pitch_focus_settle_s)
        self.logger.warning("[%s] 收尾俯仰歸位兩輪皆疑似被吃——視角可能非置中，人工留意",
                            self.harvest.harvest_id)

    def _pitch_drag_verified(self, label: str, drag) -> bool:
        """執行俯仰拖曳並用前後幀驗證是否生效（量測與 _rotate_verified 同一套）。

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
        return not eaten

    def _sampler_pitch_reset(self) -> int:
        """俯仰歸位（Tk 執行緒進來）：聚焦＋游標移入＋settle 後拖，前後幀驗證。

        歸位＝拖到夾限飽和再回拉固定量 → 冪等，被吃可安全重做一次（不會過轉）。
        """
        self._sampler_pitch_prepare()
        for attempt in (1, 2):
            if self._pitch_drag_verified(
                    f"俯仰歸位(attempt {attempt})",
                    lambda: ic.pitch_reset(cfg.reentry_pitch_clamp_px,
                                           cfg.reentry_pitch_back_px)):
                self.last_action = "▲ 俯仰歸位完成"
                break
            self._sampler_pitch_prepare()        # 重新聚焦＋沉澱後重試
        else:
            self.last_action = "⚠ 俯仰歸位疑似沒生效，點一下遊戲畫面再按一次"
        self._pitch_offset_px = cfg.reentry_pitch_back_px
        return self._pitch_offset_px

    def _sampler_pitch_nudge(self, dy: int) -> int:
        """微調一步。dy>0 向下拖＝靠近夾限→偏移量減少（偏移＝距夾限的回拉量）。

        微調不自動重試：40px 位移的幀差可能天然偏小，誤判被吃而重送＝多拖一步、
        記帳跟實際角度脫鉤（與旋轉「誤重送比漏判糟」同取捨）——只記 log＋HUD 警示，
        懷疑沒生效就按「俯仰歸位」重新對齊。
        """
        self._sampler_pitch_prepare()
        ok = self._pitch_drag_verified(f"俯仰微調 dy={dy}",
                                       lambda: ic.pitch_nudge(dy))
        self.last_action = ("▼ 俯仰微調生效" if ok
                            else "⚠ 俯仰微調疑似沒生效（記帳照減，可按歸位重對齊）")
        self._pitch_offset_px -= dy
        return self._pitch_offset_px

    def _sampler_capture(self) -> str:
        frame = capture.grab()
        stem = sampler.save_sample(frame, cfg.manual_snapshot_dir, self._pitch_offset_px)
        self.logger.info("📸 手動截圖 #%s pitch=%d", stem, self._pitch_offset_px)
        # last_action 會進 HUD 的 Tk label：不可含 astral emoji（📸 會卡死 Tk
        # 事件迴圈，見 status_hud._bmp_safe）；HUD 端已有防線，這裡源頭也不放
        self.last_action = f"◉ 手動截圖 #{stem}"
        return stem


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
