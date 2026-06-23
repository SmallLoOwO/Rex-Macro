import time
import winsound
import numpy as np
import keyboard

from .config import DEFAULT as cfg
from .events import EventLog
from .states import State, Observation, decide_transition
from . import capture, vision, ocr, audio, miner, harvester
from . import input_control as ic

def alert(message: str):
    """本機提醒：嗶聲 + 終端訊息（NEEDS_HUMAN / STUCK 用）。"""
    print(f"[ALERT] {message}")
    try:
        winsound.Beep(880, 400); winsound.Beep(660, 400)
    except RuntimeError:
        pass

class Bot:
    def __init__(self):
        self.state = State.MINING
        self.paused = False
        self.human_cleared = False
        self.log = EventLog()
        ref, sr = audio.load_reference(cfg.chill_audio_path)
        self.listener = audio.ChillListener(ref, cfg.audio_sample_rate, cfg.audio_window_seconds)
        self.harvest = harvester.HarvestState(rotations=0, elapsed_s=0.0)
        self._harvest_start = 0.0
        self._prev_frame = None
        self._last_progress = time.time()
        self._stuck_notified = False
        # 模板只在啟動時讀一次（避免每幀讀檔）
        self._templates = {
            name: vision.load_template(f"assets/{name}.png")
            for name in ("marker", "boost_expired", "activity_event",
                         "scan_event", "cave_event")
        }

    def observe(self, frame) -> Observation:
        chill_audio = self.listener.latest_score() >= cfg.audio_match_threshold
        chill_text = False
        if chill_audio:
            region = capture.crop(frame, cfg.chill_text_region)
            text = ocr.read_text(region, cfg.tesseract_path)
            chill_text = ocr.contains_any(text, cfg.chill_phrases)
        return Observation(chill_audio=chill_audio, chill_text=chill_text,
                           harvest_done=False, harvest_failed=False,
                           human_cleared=self.human_cleared)

    def run(self):
        keyboard.add_hotkey(cfg.hotkey_pause, self._toggle_pause)
        keyboard.add_hotkey(cfg.hotkey_resume_human, self._clear_human)
        keyboard.add_hotkey(cfg.hotkey_quit, self._quit)
        self._running = True
        miner.init_mining_sequence()
        while self._running:
            if self.paused:
                time.sleep(0.1); continue
            frame = capture.grab()
            obs = self.observe(frame)
            new_state = decide_transition(self.state, obs)
            if new_state != self.state:
                self.log.log("STATE_CHANGE", from_=self.state.value, to=new_state.value)
                self._on_enter(new_state)
            self.state = new_state
            self._tick(frame)
            time.sleep(0.05)

    def _on_enter(self, s):
        if s is State.HARVESTING:
            self.log.log("RARE_FOUND")
            harvester.start_scan()
            self.harvest = harvester.HarvestState(0, 0.0)
            self._harvest_start = time.time()
        if s is State.NEEDS_HUMAN:
            self.log.log("NEEDS_HUMAN", reason="harvest aim/verify failed")
            ic.key_up("w"); ic.mouse_up()
            alert("需要人工介入：稀有礦採集失敗，請手動處理後按 F9 恢復")
            self.human_cleared = False

    def _tick(self, frame):
        if self.state is State.MINING:
            self._tick_mining(frame)
        elif self.state is State.HARVESTING:
            self._tick_harvest(frame)
        # NEEDS_HUMAN: 等待熱鍵，不動作

    def _tick_mining(self, frame):
        flags = miner.EventFlags(
            boost_expired=vision.template_present(
                capture.crop(frame, cfg.boost_indicator_region),
                self._templates["boost_expired"], threshold=0.7),
            activity_event=vision.template_present(
                capture.crop(frame, cfg.chill_text_region),
                self._templates["activity_event"], threshold=0.7),
            scan_event=vision.template_present(
                capture.crop(frame, cfg.boost_indicator_region),
                self._templates["scan_event"], threshold=0.7),
            cave_event=vision.template_present(
                frame, self._templates["cave_event"], threshold=0.7),
            window_unfocused=not vision.pixel_matches(
                frame, cfg.window_focus_pixel, cfg.window_focus_color, tol=12),
        )
        action = miner.dispatch_event(flags)
        if action == "REFOCUS":
            miner.init_mining_sequence()
        elif action == "CAVE":
            miner.handle_cave()
        elif action == "SCAN":
            miner.use_scan()
        elif action == "USE_D5":
            miner.use_boost()
        elif action == "USE_D4":
            miner.use_activity()

        # 卡住偵測：連續無畫面變化超過 stuck_timeout_s
        if self._prev_frame is not None:
            diff = vision.frame_mean_diff(frame, self._prev_frame)
            if diff >= cfg.stuck_frame_diff_threshold or action is not None:
                self._last_progress = time.time()
                self._stuck_notified = False
        self._prev_frame = frame
        if (not self._stuck_notified
                and time.time() - self._last_progress > cfg.stuck_timeout_s):
            self.log.log("STUCK", reason=f"{cfg.stuck_timeout_s}s 無進度")
            alert("腳本可能卡住了")
            self._stuck_notified = True

    def _tick_harvest(self, frame):
        self.harvest.elapsed_s = time.time() - self._harvest_start
        marker = vision.find_template(frame, self._templates["marker"], threshold=0.7)
        step = harvester.next_harvest_step(marker, self.harvest, cfg)
        if step.action == "HUMAN":
            self.state = State.NEEDS_HUMAN; self._on_enter(State.NEEDS_HUMAN); return
        if step.action == "ROTATE_LEFT":
            ic.rotate_left(); self.harvest.rotations += 1
        elif step.action == "ROTATE_RIGHT":
            ic.rotate_right(); self.harvest.rotations += 1
        elif step.action == "MOUSE_AIM":
            ic.mouse_move_rel(step.dx, step.dy)
        elif step.action == "FIRE_D3":
            harvester.fire_d3()
            if self._verify_success(frame):
                self.log.log("HARVEST_SUCCESS")
                self.state = State.MINING; miner.init_mining_sequence()

    def _verify_success(self, frame) -> bool:
        chat = capture.crop(frame, cfg.chat_region)
        text = ocr.read_text(chat, cfg.tesseract_path)
        return ocr.contains_any(text, cfg.found_keywords)

    def _toggle_pause(self):
        self.paused = not self.paused

    def _clear_human(self):
        self.human_cleared = True

    def _quit(self):
        self._running = False

def main():
    Bot().run()

if __name__ == "__main__":
    main()
