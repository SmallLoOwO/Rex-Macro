import os
import time
import logging
import ctypes
import threading
import winsound

from .config import DEFAULT as cfg
from .events import EventLog, make_file_sink
from .states import State, Observation, decide_transition
from . import capture, vision, ocr, audio, miner, harvester, diagnostics, window, game_data
from . import input_control as ic


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
        ref, sr = audio.load_reference(cfg.chill_audio_path)
        # 用音檔實際的取樣率，避免 WAV 非 48kHz 時視窗長度不符
        self.listener = audio.ChillListener(ref, sr, cfg.audio_window_seconds,
                                            cfg.audio_score_interval_s)
        # 啟動喇叭 loopback 擷取，持續餵音訊給 listener（chill 偵測的核心）
        self._audio_cap = audio.LoopbackCapture(self.listener.feed)
        try:
            self._audio_cap.start()
            self.logger.info("audio loopback capture started (ref sr=%d)", sr)
        except Exception as e:
            self.logger.error("音訊擷取啟動失敗，chill 偵測停用: %s", e)
        self.harvest = harvester.HarvestState(rotations=0, elapsed_s=0.0)
        self._harvest_start = 0.0
        self._prev_frame = None
        self._last_progress = time.time()
        self._stuck_notified = False
        self._last_heartbeat = time.time()
        self._peak_audio_since_hb = 0.0           # 上次 heartbeat 至今的最高音訊分數（捕捉 30s 取樣漏掉的 chill 尖峰）
        self._last_boost = 0.0                       # 上次按 D5 的時間（冷卻用）
        self._last_activity = 0.0                    # 上次按 D4 刷新的時間（定時用）
        self._keep_ores: set[str] = set()            # D4 保留清單（Discord 指定；空=全部刷新）
        self._last_discord_msg_id: str | None = None  # Discord 命令輪詢基準（首次只記錄不處理）
        # 狀態小窗用的即時資訊
        self._started = time.time()
        self.last_action = "—"
        self.stats = {"boosts": 0, "rerolls": 0, "rares": 0, "stuck": 0}
        self._human_reason = "需要人工介入"
        self._last_reset_check = 0.0
        self._mine_resetting = False
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

    def _boost_needs_refresh(self, frame) -> bool:
        """boost 邏輯：瓶子（buff）消失 → 該重上 D5。

        無模板時停用；剛按過 D5（冷卻內）不重按，避免瓶子出現前狂按。
        """
        t = self._templates.get("boost_active")
        if t is None:
            return False
        # 在整條效果列裡用「形狀/邊緣 + 多尺度」找瓶子（忽略顏色與會變的數字、容忍疊加位移）
        present = vision.find_template_edges(
            capture.crop(frame, cfg.boost_indicator_region), t,
            cfg.boost_edge_threshold, cfg.marker_scales) is not None
        if present:
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
        # 在整條效果/冷卻列裡用「形狀/邊緣 + 多尺度」找 D4 冷卻圖示（與 boost 同一列）
        present = vision.find_template_edges(
            capture.crop(frame, cfg.boost_indicator_region), t,
            cfg.activity_cooldown_edge_threshold, cfg.marker_scales) is not None
        return miner.cooldown_ready(present, time.time() - self._last_activity,
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
        """關鍵事件存畫面，方便事後查機器人「當下看到什麼」。回傳存檔路徑（或 None）。"""
        if not cfg.save_snapshots or frame is None:
            return None
        try:
            path = diagnostics.save_snapshot(frame, cfg.log_dir, label)
            self.logger.info("SNAPSHOT %s -> %s", label, path)
            return path
        except Exception as e:                       # 存圖失敗不該中斷主流程
            self.logger.error("snapshot failed (%s): %s", label, e)
            return None

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
                           mine_resetting=mine_resetting)

    def _check_reset(self, frame) -> bool:
        """節流 OCR 頂部訊息列，偵測「mine will reset in」。只在 MINING 檢查。"""
        if self.state is not State.MINING:
            return False
        now = time.time()
        if now - self._last_reset_check < cfg.reset_check_interval_s:
            return self._mine_resetting
        self._last_reset_check = now
        text = ocr.read_text(capture.crop(frame, cfg.chill_text_region), cfg.tesseract_path)
        self._mine_resetting = ocr.contains_any(text, cfg.reset_phrases)
        if self._mine_resetting:
            self.logger.info("偵測到礦坑重置: %r", text.strip()[:60])
            self._human_reason = "礦坑重置，請重新定位後按 Q 繼續"
        return self._mine_resetting

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
        time.sleep(1.0)
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
        """讀 Discord 新訊息，處理 ! 開頭的命令。"""
        from . import notify
        msgs = notify.fetch_messages(
            cfg.discord_bot_token, cfg.discord_channel_id,
            after=self._last_discord_msg_id, limit=10)
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
            if content.startswith("!"):
                self._handle_discord_command(content)

    def _handle_discord_command(self, content: str):
        """解析並執行 Discord ! 命令，更新 _keep_ores 並回覆結果。"""
        from . import notify
        token = cfg.discord_bot_token
        ch = cfg.discord_channel_id
        parts = content.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "!list":
            embed = game_data.format_event_list_embed(self._keep_ores)
            notify.send_embed(token, ch, embed)
            self.log_discord.info("CMD !list -> embed (%d events)", len(game_data.EVENTS))

        elif cmd == "!keep":
            added, not_found = [], []
            for a in args:
                ore = game_data.fuzzy_match_ore(a)
                if ore:
                    self._keep_ores.add(ore)
                    added.append(ore)
                else:
                    not_found.append(a)
            kept = ", ".join(sorted(self._keep_ores)) or "（空）"
            msg = f"✅ 新增保留：{', '.join(added) or '（無）'}\n目前保留：{kept}"
            if not_found:
                msg += f"\n⚠️ 找不到：{', '.join(not_found)}（用 `!list` 看 礦物名）"
            notify.send_message(token, ch, msg)
            self.log_discord.info("CMD !keep %s -> added=%s keep=%s", args, added, self._keep_ores)

        elif cmd == "!unkeep":
            removed = []
            for a in args:
                ore = game_data.fuzzy_match_ore(a)
                if ore and ore in self._keep_ores:
                    self._keep_ores.discard(ore)
                    removed.append(ore)
            kept = ", ".join(sorted(self._keep_ores)) or "（空）"
            notify.send_message(token, ch,
                f"❌ 取消保留：{', '.join(removed) or '（無）'}\n目前保留：{kept}")
            self.log_discord.info("CMD !unkeep %s -> removed=%s keep=%s", args, removed, self._keep_ores)

        elif cmd == "!clear":
            self._keep_ores.clear()
            notify.send_message(token, ch, "🗑️ 保留清單已清空（所有事件都會刷新）")
            self.log_discord.info("CMD !clear -> keep set cleared")

        elif cmd == "!help":
            notify.send_message(token, ch,
                "**MiningBot 指令**\n"
                "`!list` — 列出所有事件 + keep 狀態\n"
                "`!keep <礦物名>` — 加入保留（可多個；支援部分名稱如 `hall`）\n"
                "`!unkeep <礦物名>` — 取消保留\n"
                "`!clear` — 清空保留清單\n"
                "`!help` — 顯示此說明")
            self.log_discord.info("CMD !help -> sent")

    # ---- 主迴圈 -------------------------------------------------------------
    def run(self):
        self._running = True
        self.logger.info("bot started (全域熱鍵 Ctrl+Q 只暫停 / Q 暫停↔繼續 / F12 結束, log_level=%s)",
                         cfg.log_level)
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
        miner.init_mining_sequence()
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
        if cfg.discord_bot_token and cfg.discord_channel_id:
            threading.Thread(target=self._discord_poll_loop, daemon=True).start()
            self.logger.info("Discord 命令輪詢已啟用（每 %.0fs）", cfg.discord_poll_interval_s)
        self.logger.info("初始化完成，開始挖礦")
        try:
            while self._running:
                if self.paused:
                    time.sleep(0.05); continue
                frame = capture.grab()
                obs = self.observe(frame)
                new_state = decide_transition(self.state, obs)
                if new_state != self.state:
                    self.log.log("STATE_CHANGE", from_=self.state.value, to=new_state.value)
                    self._on_enter(new_state, frame)
                self.state = new_state
                self._tick(frame)
                self._heartbeat()
                time.sleep(0.05)
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

    def _save_needs_human_screenshot(self, frame) -> str | None:
        """NEEDS_HUMAN 時跑 find_tracker 找最佳追蹤框候選，裁出該區域存檔。

        比存全螢幕更能當參考：直接看到「bot 認為最像外框的東西在哪、shape score 多少」。
        無候選時退回存全螢幕。回傳存檔路徑（或 None）。
        """
        import re, cv2
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
            return self._snapshot(frame, "needs_human")
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
        return self._snapshot(crop, "needs_human_%d_%d" % (cx, cy))

    def _on_enter(self, s, frame):
        if s is State.MINING:
            self.human_cleared = False
            miner.init_mining_sequence()             # 從其他狀態回來，重新握住 W + 左鍵
        if s is State.HARVESTING:
            chill_path = self._snapshot_crop(frame, cfg.chill_text_region, "chill_closeup")
            self._snapshot(frame, "rare_found")
            # 錄下 chill 音訊樣本（供分析/重錄參考 wav 用）
            try:
                audio_path = f"{cfg.log_dir}/snapshots/chill_audio_{time.strftime('%Y%m%d_%H%M%S')}.wav"
                self.listener.save_buffer_wav(audio_path)
                self.logger.info("chill 音訊已存: %s", audio_path)
            except Exception as e:
                self.logger.error("chill 音訊存檔失敗: %s", e)
            self.log.log("RARE_FOUND", image_path=chill_path)
            self.logger.info("進入採集 HARVESTING: D2 掃描，全方位搜尋追蹤框")
            harvester.prepare_scan()            # 停止移動、置中鏡頭（裝備位置穩定）
            self._pre_scan_ref = capture.grab() # 置中後截 reference（排除裝備假陽性）
            harvester.execute_scan()            # 裝備 D2 + 點擊觸發掃描
            self.harvest = harvester.HarvestState(0, 0.0)
            self._harvest_start = time.time()
            self._target_marker = None          # 尚未掃描，第一個 tick 將做全方位掃描
        if s is State.NEEDS_HUMAN:
            path = self._save_needs_human_screenshot(frame)
            self.log.log("NEEDS_HUMAN", reason=self._human_reason, image_path=path)
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

    def _tick(self, frame):
        if self.state is State.MINING:
            self._tick_mining(frame)
        elif self.state is State.HARVESTING:
            self._tick_harvest(frame)
        # NEEDS_HUMAN / RESET_WAIT: 等待熱鍵，不動作（chill 仍由 observe 監聽）

    def _tick_mining(self, frame):
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
            miner.init_mining_sequence()
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
            # D4 前先讀事件文字，判斷該保留（左鍵）還是刷新（右鍵）
            event_text = ocr.read_text(capture.crop(frame, cfg.chill_text_region),
                                       cfg.tesseract_path).strip()
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

    def _find_tracker(self, frame, exclude, reference_bgr=None, log=None):
        """採集偵測統一入口：HSV 快速定位 + 實機裁圖外框形狀確認（混合方案）。

        shape_templates 為空（無實機裁圖）時 find_tracker 自動退回純 HSV。
        """
        return vision.find_tracker(
            frame, exclude=exclude, reference_bgr=reference_bgr, log=log,
            shape_templates=self._shape_templates,
            shape_threshold=cfg.tracker_shape_threshold,
            shape_hard_floor=cfg.tracker_shape_hard_floor,
            shape_scales=cfg.tracker_shape_scales,
            shape_roi_px=cfg.tracker_shape_roi_px)

    def _sweep_for_tracker(self, excl, ref):
        """全 8 方位掃描：rotate_right×7 → 每方位雙幀穩定偵測 → 旋轉回最佳方位。
        回傳最佳追蹤框螢幕座標 (cx, cy)；找不到回 None。
        """
        NUM_DIRS = 8
        candidates = []  # [(dir_idx, position)]
        for i in range(NUM_DIRS):
            f = capture.grab()
            m1 = self._find_tracker(f, excl, ref, log=self._tracker_log)
            if m1:
                time.sleep(0.08)
                m2 = self._find_tracker(capture.grab(), excl, ref, log=self._tracker_log)
                if m2 and abs(m1[0] - m2[0]) < 8 and abs(m1[1] - m2[1]) < 8:
                    self.log_harvest.info("sweep dir=%d: 穩定追蹤框 %s", i, m2)
                    candidates.append((i, m2))
                else:
                    self.log_harvest.info("sweep dir=%d: 不穩定 m1=%s m2=%s", i, m1, m2)
            else:
                self.log_harvest.info("sweep dir=%d: 未偵測到追蹤框", i)
            if i < NUM_DIRS - 1:
                ic.rotate_right()
                self.harvest.net_rotations += 1
                time.sleep(0.35)

        if not candidates:
            self.log_harvest.info("sweep: 全 8 方位均未找到追蹤框")
            return None

        best_dir, best_pos = candidates[0]  # 取第一個穩定候選（colored_frac 最高的）
        # 目前在 dir 7（rotate_right × 7）→ 需往左轉 (7 - best_dir) 次回到 best_dir
        lefts = (NUM_DIRS - 1) - best_dir
        self.log_harvest.info("sweep: 最佳方位 dir=%d pos=%s，往左轉 %d 次對齊", best_dir, best_pos, lefts)
        for _ in range(lefts):
            ic.rotate_left()
            self.harvest.net_rotations -= 1
            time.sleep(0.35)

        # 對齊後驗證追蹤框仍在
        time.sleep(0.2)
        verify_f = capture.grab()
        vm = self._find_tracker(verify_f, excl, ref, log=self._tracker_log)
        if vm and abs(vm[0] - best_pos[0]) < 30 and abs(vm[1] - best_pos[1]) < 30:
            self.log_harvest.info("sweep: 驗證成功 %s", vm)
            path = self._snapshot(verify_f, "sweep_confirmed_%d_%d" % vm)
            self.log.log("TRACKER_FOUND", pos=str(vm), image_path=path)
            return vm
        elif vm:
            self.log_harvest.info("sweep: 位置偏移 %s→%s，用新位置", best_pos, vm)
            path = self._snapshot(verify_f, "sweep_confirmed_%d_%d" % vm)
            self.log.log("TRACKER_FOUND", pos=str(vm), image_path=path)
            return vm
        else:
            self.log_harvest.info("sweep: 驗證時追蹤框消失，用掃描時位置 %s", best_pos)
            return best_pos

    def _tick_harvest(self, frame):
        self.harvest.elapsed_s = time.time() - self._harvest_start

        _cr = cfg.chat_region
        _excl = [(_cr.x, _cr.y, _cr.x + _cr.w, _cr.y + _cr.h)]
        _ref = getattr(self, '_pre_scan_ref', None)

        # ---- 階段一：全方位掃描（找追蹤框；_target_marker 尚未設定時執行）----
        if self._target_marker is None:
            # sweep 階段超時（sweep 固定 8 方位約 19s，30s 已是 1.5x 餘裕）
            if self.harvest.elapsed_s > cfg.sweep_timeout_s:
                self._human_reason = "全方位掃描超時，請手動處理"
                self.logger.info("sweep 超時 -> 人工 (t=%.1f)", self.harvest.elapsed_s)
                self.state = State.NEEDS_HUMAN
                self._on_enter(State.NEEDS_HUMAN, frame)
                return
            self.last_action = "全方位掃描（8方位）"
            self._target_marker = self._sweep_for_tracker(_excl, _ref)
            if self._target_marker is None:
                self.harvest.sweep_attempts += 1
                if self.harvest.sweep_attempts >= 2:
                    self._human_reason = "全方位掃描兩次未找到追蹤框，請手動處理"
                    self.state = State.NEEDS_HUMAN
                    self._on_enter(State.NEEDS_HUMAN, frame)
                    return
                # 重試一次：重新 D2 掃描 + 下次 tick 重掃
                self.logger.info("sweep 未找到追蹤框，重試 (%d/2)", self.harvest.sweep_attempts)
                harvester.prepare_scan()
                self._pre_scan_ref = capture.grab()
                harvester.execute_scan()
                self._harvest_start = time.time()
                self.harvest.elapsed_s = 0.0
                return    # 下次 tick 重新 sweep
            # ★ sweep 完成：重置計時器，D3 階段從 0 開始算
            # （否則 sweep 吃掉全部預算，D3 永遠超時——對應 2026-06-27 那次「判斷錯誤」）
            self._harvest_start = time.time()
            self.harvest.elapsed_s = 0.0
            self.logger.info("sweep 完成 -> 進入 D3 階段 (target=%s)", self._target_marker)
            return  # 讓主迴圈抓新 frame 再進 D3

        # ---- 階段二：D3 開火 + 驗證（sweep 完成後才計時）----
        if self.harvest.elapsed_s > cfg.harvest_verify_timeout_s:
            self._human_reason = "稀有礦採集失敗（D3 階段超時），請手動處理"
            self.logger.info("D3 階段超時 -> 人工 (t=%.1f)", self.harvest.elapsed_s)
            self.state = State.NEEDS_HUMAN
            self._on_enter(State.NEEDS_HUMAN, frame)
            return

        # 看到追蹤框 → 裝 D3、直接點選它的位置（不需精準置中；右鍵微調難控）
        cx, cy = self._target_marker
        self.last_action = "D3 採集"
        # D3 前先讀聊天框（差分確認用：只有「新增」的 has found 才算成功，舊訊息不再偽造）
        chat_before = self._read_chat(frame)
        found_before = ocr.count_found(chat_before, cfg.found_keywords)
        self.log_harvest.info("採集: 找到追蹤框 (%d,%d) -> D3 點選 (attempt=%d found_before=%d)",
                         cx, cy, self.harvest.d3_attempts + 1, found_before)
        self._snapshot(frame, "d3_fire_%dx%d" % (cx, cy))      # 關鍵截圖：D3 發動瞬間（含追蹤框）
        self._snapshot_crop(frame, cfg.chat_region, "d3_chat_before")
        ic.key_press("2")           # 先切回 D2，確保 D3 不在裝備狀態（再按 3 是切入非 toggle）
        time.sleep(0.15)
        ic.key_press("3")
        time.sleep(0.3)          # 等 D3 裝備動畫（實測 0.3s 即足夠，原 0.6s 過長）
        ic.click_at(cx, cy, hold=0.4)  # hold click 才能觸發 D3（實測瞬間點無效）
        time.sleep(0.5)          # 等伺服器回應追蹤框消失（實測 0.5s 即足夠，原 1.0s 過長）
        after = capture.grab()
        gone = self._find_tracker(after, _excl,
                                  reference_bgr=getattr(self, '_pre_scan_ref', None)) is None
        chat_after = self._read_chat(after)
        found_after = ocr.count_found(chat_after, cfg.found_keywords)
        # 差分確認：count diff 或最後一行出現新訊息（chat 捲動時 count 可能下降，
        # has_new_found_last_line 只看底部最新一行，不受捲動影響）
        confirmed = (found_after > found_before
                     or ocr.has_new_found_last_line(chat_before, chat_after, cfg.found_keywords))
        # 特殊階（ionized/Spectral）：同樣用差分——這類礦物進別的背包，只能靠聊天字樣辨識
        special = ocr.has_new_found(chat_before, chat_after, cfg.special_keywords)
        chat_after_path = self._snapshot_crop(after, cfg.chat_region, "d3_chat_after")
        self.log_harvest.info("verify harvest: gone=%s found %d->%d %s special=%s",
                         gone, found_before, found_after,
                         "NEW" if confirmed else "no-new", special)
        if gone or confirmed:
            self.log.log("HARVEST_SUCCESS", confirmed=confirmed, tracker_gone=gone,
                         special=special, found_before=found_before, found_after=found_after,
                         image_path=chat_after_path)
            self.stats["rares"] += 1
            self.last_action = "採集成功！" + ("（特殊階！）" if special else "")
            self._snapshot(after, "harvest_success" + ("_special" if special else ""))
            self.logger.info("採集成功（gone=%s chat=%d->%d special=%s）-> 轉回原方位 net=%d",
                             gone, found_before, found_after, special, self.harvest.net_rotations)
            harvester.restore_view(self.harvest.net_rotations)
            self.state = State.MINING
            # 採集後用與 Q 恢復/啟動完全相同的完整序列（清鍵→視角→置中→確認鎬子→W+左鍵）。
            # 舊的精簡 resume_mining 常漏按住 W（採集後鍵盤殘留狀態讓 key_down("w") 失效）。
            miner.init_mining_sequence()
        else:
            self._snapshot(after, "d3_miss_%d" % (self.harvest.d3_attempts + 1))  # 關鍵截圖：未命中
            self.harvest.d3_attempts += 1
            if self.harvest.d3_attempts >= cfg.max_harvest_attempts:
                # D3 連續未命中達上限 → 重置目標，重新 D2 掃描 + 全方位重掃
                self.logger.info("採集: D3 連 %d 次未命中 -> 重新 D2 掃描＋全方位重掃",
                                 self.harvest.d3_attempts)
                self.harvest.d3_attempts = 0
                self._target_marker = None      # 下次 tick 重掃
                harvester.prepare_scan()
                self._pre_scan_ref = capture.grab()
                harvester.execute_scan()
                # 重掃 = 回到 sweep 階段，重置計時器讓 sweep_timeout_s 重新計算
                self._harvest_start = time.time()
                self.harvest.elapsed_s = 0.0
            else:
                self.log_harvest.info("採集: D3 未命中 (attempt %d/%d found %d->%d)，下次繼續",
                                 self.harvest.d3_attempts, cfg.max_harvest_attempts,
                                 found_before, found_after)

    def _read_chat(self, frame) -> str:
        """讀聊天框區域 OCR 文字（採集差分確認用）。

        用 min_channel 預處理：紅色 "has found" 文字在 min(R,G,B) 後對比度佳，
        標準灰階會把紅字讀成亂碼（實測 "has found" → "ines ounce!"）。
        """
        return ocr.read_text(capture.crop(frame, cfg.chat_region),
                             cfg.tesseract_path, preprocess="min_channel")

    def _snapshot_crop(self, frame, region, label: str) -> str | None:
        """存畫面指定區域的截圖（如聊天框 crop），方便事後盤別採集成敗。回傳路徑（或 None）。"""
        if not cfg.save_snapshots or frame is None:
            return None
        try:
            path = diagnostics.save_snapshot(capture.crop(frame, region), cfg.log_dir, label)
            self.logger.info("SNAPSHOT %s -> %s", label, path)
            return path
        except Exception as e:                       # 存圖失敗不該中斷主流程
            self.logger.error("snapshot failed (%s): %s", label, e)
            return None

    # ---- 控制權熱鍵（全域輪詢）---------------------------------------------
    def _check_hotkeys(self):
        self._hk.tick()

    def _pause(self):
        """暫停：放開所有按鍵、停住。idempotent（已暫停再呼叫無副作用）。

        Ctrl+Q 與 Q 的暫停走同一條路徑——兩者暫停行為完全一致，差別只在 Q 能再按一次
        繼續、Ctrl+Q 只暫停（見 _toggle_pause / on_stop 接線）。不再有獨立的「強制停止」。
        """
        if not self.paused:
            self.paused = True
            ic.key_up("w"); ic.mouse_up()
            self.log.log("PAUSED")
            self.logger.info("PAUSED — 按 Q 繼續")

    def _resume(self):
        """繼續：清除暫停並重新握住 W + 左鍵（與啟動/_on_enter(MINING) 相同的完整序列）。"""
        self.paused = False
        self.log.log("RESUMED")
        self.logger.info("RESUMED")
        if self.state is State.MINING:
            miner.init_mining_sequence()

    def _toggle_pause(self):
        """Q：開關 暫停 ↔ 繼續（也用於人工介入/礦坑重置定位後重新啟動）。

        Ctrl+Q 已在 _check_hotkeys 分開處理（只會呼叫 _pause），這裡進來的一定是單獨 Q。
        """
        if self.paused:                              # 目前停著 → 繼續
            self._resume()
        elif self.state in (State.NEEDS_HUMAN, State.RESET_WAIT):   # 人工/重置定位後 → 繼續
            self.human_cleared = True
            self.logger.info("human cleared (Q) — 恢復挖礦 (from %s)", self.state.value)
        else:                                        # 正在跑 → 暫停
            self._pause()

    def _quit(self):
        self.logger.info("QUIT (%s) — 結束程式", cfg.hotkey_quit)
        self._running = False


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
