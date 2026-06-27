import os
import time
import ctypes
import threading
import winsound

from .config import DEFAULT as cfg
from .events import EventLog, make_file_sink
from .states import State, Observation, decide_transition
from . import capture, vision, ocr, audio, miner, harvester, diagnostics, window
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
        self.log = EventLog()
        self.log.add_sink(make_file_sink(f"{cfg.log_dir}/events.log"))
        self.log.add_sink(lambda rec: self.logger.info("EVENT %s %s", rec.type, rec.meta))
        # Discord 事件通知（有設 token+channel 才啟用；失敗只記 log，不影響挖礦）
        if cfg.discord_bot_token and cfg.discord_channel_id:
            from . import notify
            self.log.add_sink(notify.make_discord_sink(
                cfg.discord_bot_token, cfg.discord_channel_id,
                on_error=lambda d: self.logger.error("Discord 通知失敗: %s", d)))
            self.logger.info("Discord 通知已啟用 (channel=%s)", cfg.discord_channel_id)
        else:
            self.logger.info("Discord 通知未啟用（.env 未設 token/channel）")
        ref, sr = audio.load_reference(cfg.chill_audio_path)
        # 用音檔實際的取樣率，避免 WAV 非 48kHz 時視窗長度不符
        self.listener = audio.ChillListener(ref, sr, cfg.audio_window_seconds)
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
        self._last_boost = 0.0                       # 上次按 D5 的時間（冷卻用）
        self._last_activity = 0.0                    # 上次按 D4 刷新的時間（定時用）
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
            self._emergency_stop,
            self._toggle_pause,
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

    def _load_marker_templates(self) -> dict:
        import glob
        templates = {}
        for p in sorted(glob.glob(os.path.join(cfg.marker_dir, "*.png"))):
            name = os.path.splitext(os.path.basename(p))[0]
            templates[name] = vision.load_template(p)
        if not templates and os.path.exists("assets/marker.png"):
            templates["marker"] = vision.load_template("assets/marker.png")
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

    def _snapshot(self, frame, label: str):
        """關鍵事件存畫面，方便事後查機器人「當下看到什麼」。"""
        if not cfg.save_snapshots or frame is None:
            return
        try:
            path = diagnostics.save_snapshot(frame, cfg.log_dir, label)
            self.logger.info("SNAPSHOT %s -> %s", label, path)
        except Exception as e:                       # 存圖失敗不該中斷主流程
            self.logger.error("snapshot failed (%s): %s", label, e)

    # ---- 觀察 ---------------------------------------------------------------
    def observe(self, frame) -> Observation:
        score = self.listener.latest_score()
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
        return Observation(chill_audio=chill_audio, chill_text=chill_text,
                           harvest_done=False, harvest_failed=False,
                           human_cleared=self.human_cleared,
                           mine_resetting=self._check_reset(frame))

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

    # ---- 主迴圈 -------------------------------------------------------------
    def run(self):
        self._running = True
        self.logger.info("bot started (全域熱鍵 Ctrl+Q 停 / Q 暫停繼續 / F12 結束, log_level=%s)",
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
            self.logger.info("heartbeat state=%s audio=%.2f",
                             self.state.value, self.listener.latest_score())
            self._last_heartbeat = now

    def _on_enter(self, s, frame):
        if s is State.MINING:
            self.human_cleared = False
            miner.init_mining_sequence()             # 從其他狀態回來，重新握住 W + 左鍵
        if s is State.HARVESTING:
            self.log.log("RARE_FOUND")
            self._snapshot(frame, "rare_found")
            self.logger.info("進入採集 HARVESTING: D2 掃描，全方位搜尋追蹤框")
            harvester.prepare_scan()            # 停止移動、置中鏡頭（裝備位置穩定）
            self._pre_scan_ref = capture.grab() # 置中後截 reference（排除裝備假陽性）
            harvester.execute_scan()            # 裝備 D2 + 點擊觸發掃描
            self.harvest = harvester.HarvestState(0, 0.0)
            self._harvest_start = time.time()
            self._target_marker = None          # 尚未掃描，第一個 tick 將做全方位掃描
        if s is State.NEEDS_HUMAN:
            self.log.log("NEEDS_HUMAN", reason=self._human_reason)
            self._snapshot(frame, "needs_human")
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
            self.logger.info("mining: boost 消失 -> 重上 D5")
            self.last_action = "boost 重上(D5)"
            self.stats["boosts"] += 1
            miner.use_boost()
            self._last_boost = time.time()           # 設冷卻，避免瓶子出現前重複按
        elif action == "USE_D4":
            self.logger.info("mining: 定時刷新事件 -> D4 右鍵")
            self.last_action = "刷新事件(D4)"
            self.stats["rerolls"] += 1
            miner.use_activity()
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

    def _sweep_for_tracker(self, excl, ref):
        """全 8 方位掃描：rotate_right×7 → 每方位雙幀穩定偵測 → 旋轉回最佳方位。
        回傳最佳追蹤框螢幕座標 (cx, cy)；找不到回 None。
        """
        NUM_DIRS = 8
        candidates = []  # [(dir_idx, position)]
        for i in range(NUM_DIRS):
            f = capture.grab()
            m1 = vision.find_tracker(f, exclude=excl, reference_bgr=ref,
                                     log=self.logger.debug)
            if m1:
                time.sleep(0.08)
                m2 = vision.find_tracker(capture.grab(), exclude=excl, reference_bgr=ref)
                if m2 and abs(m1[0] - m2[0]) < 8 and abs(m1[1] - m2[1]) < 8:
                    self.logger.info("sweep dir=%d: 穩定追蹤框 %s", i, m2)
                    candidates.append((i, m2))
                else:
                    self.logger.info("sweep dir=%d: 不穩定 m1=%s m2=%s", i, m1, m2)
            else:
                self.logger.info("sweep dir=%d: 未偵測到追蹤框", i)
            if i < NUM_DIRS - 1:
                ic.rotate_right()
                self.harvest.net_rotations += 1
                time.sleep(0.35)

        if not candidates:
            self.logger.info("sweep: 全 8 方位均未找到追蹤框")
            return None

        best_dir, best_pos = candidates[0]  # 取第一個穩定候選（colored_frac 最高的）
        # 目前在 dir 7（rotate_right × 7）→ 需往左轉 (7 - best_dir) 次回到 best_dir
        lefts = (NUM_DIRS - 1) - best_dir
        self.logger.info("sweep: 最佳方位 dir=%d pos=%s，往左轉 %d 次對齊", best_dir, best_pos, lefts)
        for _ in range(lefts):
            ic.rotate_left()
            self.harvest.net_rotations -= 1
            time.sleep(0.35)

        # 對齊後驗證追蹤框仍在
        time.sleep(0.2)
        verify_f = capture.grab()
        vm = vision.find_tracker(verify_f, exclude=excl, reference_bgr=ref)
        if vm and abs(vm[0] - best_pos[0]) < 30 and abs(vm[1] - best_pos[1]) < 30:
            self.logger.info("sweep: 驗證成功 %s", vm)
            self._snapshot(verify_f, "sweep_confirmed_%d_%d" % vm)
            return vm
        elif vm:
            self.logger.info("sweep: 位置偏移 %s→%s，用新位置", best_pos, vm)
            self._snapshot(verify_f, "sweep_confirmed_%d_%d" % vm)
            return vm
        else:
            self.logger.info("sweep: 驗證時追蹤框消失，用掃描時位置 %s", best_pos)
            return best_pos

    def _tick_harvest(self, frame):
        self.harvest.elapsed_s = time.time() - self._harvest_start
        # 超時 → 交人工
        if self.harvest.elapsed_s > cfg.harvest_verify_timeout_s:
            self._human_reason = "稀有礦採集失敗（超時），請手動處理"
            self.logger.info("採集超時 -> 人工 (t=%.1f)", self.harvest.elapsed_s)
            self.state = State.NEEDS_HUMAN
            self._on_enter(State.NEEDS_HUMAN, frame)
            return

        _cr = cfg.chat_region
        _excl = [(_cr.x, _cr.y, _cr.x + _cr.w, _cr.y + _cr.h)]
        _ref = getattr(self, '_pre_scan_ref', None)

        # 全方位掃描（還沒有目標時執行）
        if self._target_marker is None:
            self.last_action = "全方位掃描（8方位）"
            self._target_marker = self._sweep_for_tracker(_excl, _ref)
            if self._target_marker is None:
                self._human_reason = "全方位掃描未找到追蹤框，請手動處理"
                self.state = State.NEEDS_HUMAN
                self._on_enter(State.NEEDS_HUMAN, frame)
            return  # 不管找沒找到，先 return，讓主迴圈抓新 frame

        # 看到追蹤框 → 裝 D3、直接點選它的位置（不需精準置中；右鍵微調難控）
        cx, cy = self._target_marker
        self.last_action = "D3 採集"
        # D3 前先讀聊天框（差分確認用：只有「新增」的 has found 才算成功，舊訊息不再偽造）
        chat_before = self._read_chat(frame)
        found_before = ocr.count_found(chat_before, cfg.found_keywords)
        self.logger.info("採集: 找到追蹤框 (%d,%d) -> D3 點選 (attempt=%d found_before=%d)",
                         cx, cy, self.harvest.d3_attempts + 1, found_before)
        self._snapshot(frame, "d3_fire_%dx%d" % (cx, cy))      # 關鍵截圖：D3 發動瞬間（含追蹤框）
        self._snapshot_crop(frame, cfg.chat_region, "d3_chat_before")
        ic.key_press("2")           # 先切回 D2，確保 D3 不在裝備狀態（再按 3 是切入非 toggle）
        time.sleep(0.15)
        ic.key_press("3")
        time.sleep(0.6)          # 等 D3 裝備動畫（太快點會被吃掉）
        ic.click_at(cx, cy, hold=0.4)  # hold click 才能觸發 D3（實測瞬間點無效）
        time.sleep(1.0)          # 等伺服器回應追蹤框消失（太快截圖可能追蹤框還在）
        after = capture.grab()
        gone = vision.find_tracker(after, exclude=_excl,
                                   reference_bgr=getattr(self, '_pre_scan_ref', None)) is None
        chat_after = self._read_chat(after)
        found_after = ocr.count_found(chat_after, cfg.found_keywords)
        # 差分確認：count diff 或最後一行出現新訊息（chat 捲動時 count 可能下降，
        # has_new_found_last_line 只看底部最新一行，不受捲動影響）
        confirmed = (found_after > found_before
                     or ocr.has_new_found_last_line(chat_before, chat_after, cfg.found_keywords))
        # 特殊階（ionized/Spectral）：同樣用差分——這類礦物進別的背包，只能靠聊天字樣辨識
        special = ocr.has_new_found(chat_before, chat_after, cfg.special_keywords)
        self._snapshot_crop(after, cfg.chat_region, "d3_chat_after")
        self.logger.info("verify harvest: gone=%s found %d->%d %s special=%s",
                         gone, found_before, found_after,
                         "NEW" if confirmed else "no-new", special)
        if gone or confirmed:
            self.log.log("HARVEST_SUCCESS", confirmed=confirmed, tracker_gone=gone,
                         special=special, found_before=found_before, found_after=found_after)
            self.stats["rares"] += 1
            self.last_action = "採集成功！" + ("（特殊階！）" if special else "")
            self._snapshot(after, "harvest_success" + ("_special" if special else ""))
            self.logger.info("採集成功（gone=%s chat=%d->%d special=%s）-> 轉回原方位 net=%d",
                             gone, found_before, found_after, special, self.harvest.net_rotations)
            harvester.restore_view(self.harvest.net_rotations)
            self.state = State.MINING
            miner.init_mining_sequence()
        else:
            self._snapshot(after, "d3_miss_%d" % (self.harvest.d3_attempts + 1))  # 關鍵截圖：未命中
            self.harvest.d3_attempts += 1
            if self.harvest.d3_attempts >= 3:
                # D3 連 3 次未命中 → 重置目標，重新 D2 掃描 + 全方位重掃
                self.logger.info("採集: D3 連 %d 次未命中 -> 重新 D2 掃描＋全方位重掃",
                                 self.harvest.d3_attempts)
                self.harvest.d3_attempts = 0
                self._target_marker = None      # 下次 tick 重掃
                harvester.prepare_scan()
                self._pre_scan_ref = capture.grab()
                harvester.execute_scan()
            else:
                self.logger.info("採集: D3 未命中 (attempt %d/3 found %d->%d)，下次繼續",
                                 self.harvest.d3_attempts, found_before, found_after)

    def _read_chat(self, frame) -> str:
        """讀聊天框區域 OCR 文字（採集差分確認用）。

        用 min_channel 預處理：紅色 "has found" 文字在 min(R,G,B) 後對比度佳，
        標準灰階會把紅字讀成亂碼（實測 "has found" → "ines ounce!"）。
        """
        return ocr.read_text(capture.crop(frame, cfg.chat_region),
                             cfg.tesseract_path, preprocess="min_channel")

    def _snapshot_crop(self, frame, region, label: str):
        """存畫面指定區域的截圖（如聊天框 crop），方便事後盤別採集成敗。"""
        if not cfg.save_snapshots or frame is None:
            return
        try:
            path = diagnostics.save_snapshot(capture.crop(frame, region), cfg.log_dir, label)
            self.logger.info("SNAPSHOT %s -> %s", label, path)
        except Exception as e:                       # 存圖失敗不中斷主流程
            self.logger.error("snapshot failed (%s): %s", label, e)

    # ---- 控制權熱鍵（全域輪詢）---------------------------------------------
    def _check_hotkeys(self):
        self._hk.tick()

    def _emergency_stop(self):
        """Ctrl+Q：緊急停止（不結束程式），放開所有按鍵，停住等待 Q 重新啟動。"""
        if not self.paused:
            self.paused = True
            ic.key_up("w"); ic.mouse_up()
            self.log.log("EMERGENCY_STOP")
            self.logger.warning("EMERGENCY STOP (Ctrl+Q) — 已停止並放開按鍵，按 Q 重新啟動")

    def _toggle_pause(self):
        """Q：手動切換 暫停 ↔ 繼續（也用於緊急停止/人工介入後重新啟動）。

        Ctrl+Q 已在 _check_hotkeys 分開處理，這裡進來的一定是單獨 Q。
        """
        if self.paused:                              # 目前停著 → 繼續
            self.paused = False
            self.log.log("RESUMED")
            self.logger.info("RESUMED (Q)")
            if self.state is State.MINING:
                miner.init_mining_sequence()
        elif self.state in (State.NEEDS_HUMAN, State.RESET_WAIT):   # 人工/重置定位後 → 繼續
            self.human_cleared = True
            self.logger.info("human cleared (Q) — 恢復挖礦 (from %s)", self.state.value)
        else:                                        # 正在跑 → 暫停
            self.paused = True
            ic.key_up("w"); ic.mouse_up()
            self.log.log("PAUSED")
            self.logger.info("PAUSED (Q) — 再按 Q 繼續")

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
    bot = Bot()
    if not cfg.hud_enabled:
        bot.run()
        return
    # 機器人跑背景執行緒，狀態小窗在主執行緒（tkinter 需在主執行緒）
    import threading
    from .status_hud import StatusHUD
    threading.Thread(target=bot.run, daemon=True).start()
    try:
        StatusHUD(bot, cfg.hud_x, cfg.hud_y).run()
    finally:
        # HUD 關閉（使用者關視窗）或主迴圈結束 → 停止 bot；明確標示是使用者關閉，避免誤會成當機
        if bot._running:
            bot.logger.info("使用者關閉（HUD 視窗關閉）— 停止 bot")
        bot._running = False


if __name__ == "__main__":
    main()
