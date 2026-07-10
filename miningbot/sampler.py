"""R 鍵手動取樣：編號截圖＋俯仰校準小視窗。

用途：使用者在遊戲裡看到「值得當樣本的畫面」（傳送面板視角、漏抓的追蹤框、
新背景的聊天框）按 R 留檔，之後直接以編號指名「用 007 當模板」。
sidecar json 記俯仰偏移量——這讓「合適的仰角」變成可重現的數字（寫回 config）。

視窗生命週期：status_hud 的 Tk 佔著主執行緒跑 HUD，sampler 是隨開隨關的臨時視窗
→ 自己開執行緒跑獨立 Tk root＋mainloop，所有 widget 操作只留在該執行緒；
外部（熱鍵執行緒的再按 R）只設 close flag，由 Tk 執行緒輪詢自行收掉。
按鈕 callback 在 Tk 執行緒執行——callback（Bot 掛入）內先 _focus_roblox 再送
pydirectinput，因為點按鈕當下焦點必在小視窗上，不聚焦按鍵會送錯視窗。
"""
import json
import os
import re
import threading
import time

_NUM_RE = re.compile(r"^(\d{3})\.png$")


def sync_action(want_open: bool, panel_alive: bool):
    """HUD 輪詢同步決策：回 'open' / 'close' / None（純函式，有單元測試）。

    want_open=True 但視窗不在 → 開；want_open=False 但視窗還在 → 關；
    其餘（已對齊）→ None。熱鍵執行緒只翻 want_open 旗標，HUD Tk 主執行緒
    每 300ms 呼叫本函式決定要不要建/銷 Toplevel（見 SamplerPanel）。
    """
    if want_open and not panel_alive:
        return "open"
    if not want_open and panel_alive:
        return "close"
    return None


def next_manual_index(existing_names) -> int:
    nums = [int(m.group(1)) for n in existing_names for m in [_NUM_RE.match(n)] if m]
    return max(nums, default=0) + 1


def save_sample(frame_bgr, out_dir: str, pitch_offset_px: int) -> str:
    """存編號截圖＋sidecar。回傳編號字串（如 "007"）。"""
    import cv2
    os.makedirs(out_dir, exist_ok=True)
    stem = f"{next_manual_index(os.listdir(out_dir)):03d}"
    cv2.imwrite(os.path.join(out_dir, f"{stem}.png"), frame_bgr)
    with open(os.path.join(out_dir, f"{stem}.json"), "w", encoding="utf-8") as f:
        json.dump({"pitch_offset_px": pitch_offset_px,
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)
    return stem


class SamplerWindow:
    """取樣小視窗：俯仰歸位/微調＋截圖，顯示目前俯仰偏移量。

    ⚠ 警告：主執行緒已有 Tk mainloop（HUD 模式，hud_enabled=True）時，本類別的
    視窗不會顯示——背景執行緒建第二個 tk.Tk() 會靜默失敗（after 回呼有跑、
    alive=True，但 OS 層視窗從未建立，實機驗證 2026-07-10）。HUD 模式一律走
    SamplerPanel（掛在 HUD root 上的 Toplevel）。本類別僅作無 HUD 後備。

    callbacks（由 Bot 掛入，皆在 Tk 執行緒執行）：
      on_capture() -> str            截圖存檔，回編號（顯示用）
      on_pitch_reset() -> int        俯仰歸位，回新偏移量（px）
      on_pitch_nudge(dy) -> int      微調一步（dy>0 向下），回新偏移量
    """

    def __init__(self, on_capture, on_pitch_reset, on_pitch_nudge,
                 step_px: int, initial_offset: int = 0):
        self._on_capture = on_capture
        self._on_pitch_reset = on_pitch_reset
        self._on_pitch_nudge = on_pitch_nudge
        self._step = step_px
        self._offset = initial_offset
        self._last_stem = ""
        self._closing = False
        self._alive = True
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def alive(self) -> bool:
        return self._alive

    def close(self):
        """跨執行緒安全：只設 flag，Tk 執行緒的輪詢負責 destroy。"""
        self._closing = True

    # ---- 以下只在 Tk 執行緒跑 ----
    def _run(self):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.title("取樣 (R)")
            root.attributes("-topmost", True)
            root.resizable(False, False)
            root.geometry("+12+700")
            lbl = tk.Label(root, font=("Consolas", 12), justify="left",
                           anchor="w", padx=10, pady=6)

            def show():
                extra = f"   最近截圖 #{self._last_stem}" if self._last_stem else ""
                lbl.config(text=f"俯仰偏移: {self._offset}px{extra}")

            def guarded(fn):
                # callback 內是 focus+送鍵 I/O，失敗（視窗不見等）不可炸掉 Tk 執行緒
                def inner():
                    try:
                        fn()
                    except Exception:
                        pass
                    show()
                return inner

            def do_reset():
                self._offset = self._on_pitch_reset()

            def do_up():
                self._offset = self._on_pitch_nudge(-self._step)

            def do_down():
                self._offset = self._on_pitch_nudge(self._step)

            def do_capture():
                self._last_stem = self._on_capture()

            row = tk.Frame(root); row.pack(padx=6, pady=4)
            tk.Button(row, text="俯仰歸位", command=guarded(do_reset)).pack(side="left", padx=2)
            tk.Button(row, text="▲ 上", command=guarded(do_up)).pack(side="left", padx=2)
            tk.Button(row, text="▼ 下", command=guarded(do_down)).pack(side="left", padx=2)
            # 按鈕文字不可用 astral emoji（📸 U+1F4F8）：Tcl/Tk 8.6 遇非 BMP 字元
            # 整個事件迴圈無聲卡死（實機二分驗證 2026-07-10）；◉ 是 BMP 安全替代
            tk.Button(row, text="◉ 截圖", command=guarded(do_capture)).pack(side="left", padx=2)
            lbl.pack(fill="x")
            show()
            root.protocol("WM_DELETE_WINDOW", self.close)

            def poll():
                if self._closing:
                    root.destroy()
                    return
                root.after(100, poll)

            poll()
            root.mainloop()
        finally:
            self._alive = False


class SamplerPanel:
    """取樣小視窗（HUD 模式專用）：掛在 HUD 的 Tk root 上的 Toplevel，不開執行緒。

    與 SamplerWindow 相同的 UI 與 callback 介面，但必須在 Tk 主執行緒
    （HUD 的 _poll）建立/銷毀——背景執行緒建第二個 tk.Tk() 會靜默失敗
    （實機驗證 2026-07-10），故熱鍵只翻 want 旗標，由 HUD 輪詢 sync_action
    決定何時建/銷本物件。

    callbacks（由 Bot 掛入，皆在 Tk 執行緒執行）：
      on_capture() -> str            截圖存檔，回編號（顯示用）
      on_pitch_reset() -> int        俯仰歸位，回新偏移量（px）
      on_pitch_nudge(dy) -> int      微調一步（dy>0 向下），回新偏移量
      on_user_close()                使用者按視窗 X 關閉（Bot 歸位 want 旗標）
    """

    def __init__(self, tk_root, on_capture, on_pitch_reset, on_pitch_nudge,
                 step_px: int, initial_offset: int = 0, on_user_close=None):
        self._on_capture = on_capture
        self._on_pitch_reset = on_pitch_reset
        self._on_pitch_nudge = on_pitch_nudge
        self._on_user_close = on_user_close
        self._step = step_px
        self._offset = initial_offset
        self._last_stem = ""

        import tkinter as tk
        self._top = tk.Toplevel(tk_root)
        self._top.title("取樣 (R)")
        self._top.attributes("-topmost", True)
        self._top.resizable(False, False)
        self._top.geometry("+12+700")

        self._lbl = tk.Label(self._top, font=("Consolas", 12), justify="left",
                             anchor="w", padx=10, pady=6)

        def guarded(fn):
            # callback 內是 focus+送鍵 I/O，失敗（視窗不見等）不可炸掉 Tk 執行緒
            def inner():
                try:
                    fn()
                except Exception:
                    pass
                self._show()
            return inner

        def do_reset():
            self._offset = self._on_pitch_reset()

        def do_up():
            self._offset = self._on_pitch_nudge(-self._step)

        def do_down():
            self._offset = self._on_pitch_nudge(self._step)

        def do_capture():
            self._last_stem = self._on_capture()

        row = tk.Frame(self._top); row.pack(padx=6, pady=4)
        tk.Button(row, text="俯仰歸位", command=guarded(do_reset)).pack(side="left", padx=2)
        tk.Button(row, text="▲ 上", command=guarded(do_up)).pack(side="left", padx=2)
        tk.Button(row, text="▼ 下", command=guarded(do_down)).pack(side="left", padx=2)
        # 按鈕文字不可用 astral emoji（📸 U+1F4F8）：Tcl/Tk 8.6 遇非 BMP 字元
        # 整個事件迴圈無聲卡死（實機二分驗證 2026-07-10）；◉ 是 BMP 安全替代
        tk.Button(row, text="◉ 截圖", command=guarded(do_capture)).pack(side="left", padx=2)
        self._lbl.pack(fill="x")
        self._show()
        self._top.protocol("WM_DELETE_WINDOW", self._on_delete)

    def _show(self):
        extra = f"   最近截圖 #{self._last_stem}" if self._last_stem else ""
        self._lbl.config(text=f"俯仰偏移: {self._offset}px{extra}")

    def _on_delete(self):
        # 先讓 Bot 歸位 want 旗標，否則下一輪 poll 會把視窗重開
        try:
            if self._on_user_close is not None:
                self._on_user_close()
        except Exception:
            pass
        try:
            self._top.destroy()
        except Exception:
            pass

    @property
    def alive(self) -> bool:
        try:
            return bool(self._top.winfo_exists())
        except Exception:   # root 被銷毀後 winfo_exists 丟 TclError
            return False

    def close(self):
        """在 Tk 執行緒呼叫（由 HUD _poll 走 sync_action close 分支）。"""
        try:
            self._top.destroy()
        except Exception:
            pass
