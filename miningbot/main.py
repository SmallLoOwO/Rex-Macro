import os
import time
import ctypes
import winsound

from .config import DEFAULT as cfg
from .events import EventLog, make_file_sink
from .states import State, Observation, decide_transition
from . import capture, vision, ocr, audio, miner, harvester, diagnostics, window
from . import input_control as ic


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
        # 全域熱鍵邊緣偵測用（GetAsyncKeyState 輪詢，不靠 keyboard 庫，焦點在遊戲也有效）
        self._hk_ctrlq = False
        self._hk_q = False
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

    # ---- 主迴圈 -------------------------------------------------------------
    def run(self):
        # 熱鍵改用主迴圈裡 GetAsyncKeyState 全域輪詢（見 _check_hotkeys），
        # 不再用 keyboard 庫——焦點在 Roblox 時 keyboard 庫常收不到，導致按了停不下來。
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
        self.logger.info("初始化完成，開始挖礦")
        try:
            while self._running:
                self._check_hotkeys()           # 全域熱鍵（暫停時也要能偵測 Q 恢復）
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
            harvester.start_scan()
            self.harvest = harvester.HarvestState(0, 0.0)
            self._harvest_start = time.time()
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

    def _tick_harvest(self, frame):
        self.harvest.elapsed_s = time.time() - self._harvest_start
        # 多階級標記：形狀/邊緣比對（忽略顏色）+ 多尺度 + 多模板，順便知道是哪一級
        result = vision.find_best_marker(
            frame, self._marker_templates, cfg.marker_edge_threshold, cfg.marker_scales)
        if result is not None:
            tier, marker = result
            self.logger.debug("marker tier=%s at %s", tier, marker)
        else:
            marker = None
        step = harvester.next_harvest_step(marker, self.harvest, cfg)
        self.logger.debug("harvest marker=%s step=%s rot=%d net=%d t=%.1f",
                          marker, step.action, self.harvest.rotations,
                          self.harvest.net_rotations, self.harvest.elapsed_s)
        if step.action == "HUMAN":
            self._human_reason = "稀有礦採集失敗，請手動處理"
            self.state = State.NEEDS_HUMAN
            self._on_enter(State.NEEDS_HUMAN, frame)
            return
        if step.action == "ROTATE_LEFT":
            ic.rotate_left(); self.harvest.rotations += 1; self.harvest.net_rotations -= 1
        elif step.action == "ROTATE_RIGHT":
            ic.rotate_right(); self.harvest.rotations += 1; self.harvest.net_rotations += 1
        elif step.action == "MOUSE_AIM":
            # 先把準心置中（連按兩次 Shift），偏移才是相對中心；再用 gain 縮放成滑鼠位移
            ic.center_crosshair()
            ic.mouse_move_rel(int(step.dx * cfg.mouse_aim_gain),
                              int(step.dy * cfg.mouse_aim_gain))
        elif step.action == "FIRE_D3":
            harvester.fire_d3()
            if self._verify_success(frame):
                self.log.log("HARVEST_SUCCESS")
                self.stats["rares"] += 1
                self.last_action = "採集成功！"
                self._snapshot(frame, "harvest_success")
                harvester.restore_view(self.harvest.net_rotations)  # 轉回採集前的原角度
                self.state = State.MINING
                miner.init_mining_sequence()

    def _verify_success(self, frame) -> bool:
        chat = capture.crop(frame, cfg.chat_region)
        text = ocr.read_text(chat, cfg.tesseract_path)
        ok = ocr.contains_any(text, cfg.found_keywords)
        self.logger.info("verify harvest: %s (chat=%r)", "SUCCESS" if ok else "not yet",
                         text.strip()[:80])
        return ok

    # ---- 控制權熱鍵（全域輪詢）---------------------------------------------
    def _check_hotkeys(self):
        """每幀用 GetAsyncKeyState 全域偵測熱鍵；不管焦點在不在遊戲都有效。

        邊緣觸發（按一下做一次），避免按住時連續觸發。
        """
        u = ctypes.windll.user32
        def down(vk):
            return bool(u.GetAsyncKeyState(vk) & 0x8000)
        ctrl = down(0x11); q = down(0x51); f12 = down(0x7B)   # VK_CONTROL / Q / F12
        if ctrl and q:                               # Ctrl+Q：緊急停止
            if not self._hk_ctrlq:
                self._emergency_stop()
            self._hk_ctrlq = True
            self._hk_q = True                        # 別讓放開時又觸發單獨 Q
            return
        self._hk_ctrlq = False
        if q and not ctrl:                           # 單獨 Q：暫停/繼續
            if not self._hk_q:
                self._toggle_pause()
            self._hk_q = True
        else:
            self._hk_q = False
        if f12:                                      # F12：結束（觸發乾淨關閉）
            self._quit()

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
