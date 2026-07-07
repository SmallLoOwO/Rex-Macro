"""置頂狀態小窗：即時顯示機器人目前狀態/動作，不用猜它在幹嘛。

放左下角（避開頂部 chill 區與右下 boost 區）；採集（HARVESTING，全畫面找標記）時
自動隱藏，避免擋住偵測。在主執行緒跑 tkinter，機器人跑在背景執行緒。
"""
import ctypes
import time
import tkinter as tk

_STATE_ZH = {"MINING": "挖礦中", "HARVESTING": "採集稀有礦",
             "NEEDS_HUMAN": "需要人工", "RESET_WAIT": "礦坑重置·待定位"}

# Win32：做成「不搶焦點的置頂浮層」，才不會把焦點從 Roblox 偷走（偷走輸入就停）
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TOPMOST = 0x00000008
_HWND_TOPMOST = -1
_SWP = 0x0001 | 0x0002 | 0x0010 | 0x0040  # NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW


def _make_no_activate_topmost(root):
    """把 tkinter 視窗設成置頂且不搶焦點。回傳 hwnd（失敗回 None）。"""
    try:
        u = ctypes.windll.user32
        root.update_idletasks()
        hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
        style = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, _GWL_EXSTYLE,
                         style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST)
        u.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP)
        return hwnd
    except Exception:
        return None


class StatusHUD:
    def __init__(self, bot, x: int = 12, y: int = 905):
        self.bot = bot
        self._countdown_remaining = 0              # >0 = 倒數中（bot 尚未啟動）
        self._bot_thread_started = False
        self.root = tk.Tk()
        self.root.title("MiningBot")
        self.root.attributes("-topmost", True)         # 置頂（一般視窗比無邊框可靠）
        self.root.resizable(False, False)
        try:
            self.root.attributes("-alpha", 0.88)
        except tk.TclError:
            pass
        self.root.geometry(f"+{x}+{y}")
        self.lbl = tk.Label(self.root, justify="left", anchor="w",
                            font=("Consolas", 14), fg="#00ff88", bg="#0b0b0b",
                            padx=12, pady=8)
        self.lbl.pack()
        self._hidden = False
        self._hwnd = _make_no_activate_topmost(self.root)   # 置頂不搶焦點

    def run(self, countdown_s: int = 0):
        """啟動 mainloop。countdown_s>0 時先在原視窗倒數（bot 在倒數結束後才啟動）。"""
        if countdown_s > 0:
            self._countdown_remaining = countdown_s
            self._countdown_tick()
        else:
            self._begin_operation()
        self.root.mainloop()

    def _countdown_tick(self):
        """倒數階段：同一個左下角視窗顯示倒數，倒數完啟動 bot 並切換到正常輪詢。"""
        if self._countdown_remaining <= 0:
            self._begin_operation()
            return
        self.lbl.config(text=(
            "● MiningBot 啟動中\n"
            "\n"
            f"     {self._countdown_remaining}\n"
            "\n"
            "請確認 Roblox 已開啟"
        ))
        self._countdown_remaining -= 1
        self.root.after(1000, self._countdown_tick)

    def _begin_operation(self):
        """倒數結束（或無倒數）：啟動 bot 背景執行緒，開始 HUD 正常輪詢。"""
        if not self._bot_thread_started:
            self._bot_thread_started = True
            import threading
            threading.Thread(target=self.bot.run, daemon=True).start()
        self.root.after(200, self._poll)

    def _poll(self):
        b = self.bot
        if not getattr(b, "_running", True):
            self.root.destroy()
            return
        state = b.state.value
        # 採集時隱藏（全畫面找標記，別讓小窗入鏡）
        if state == "HARVESTING" and not self._hidden:
            self.root.withdraw(); self._hidden = True
        elif state != "HARVESTING" and self._hidden:
            self.root.deiconify(); self._hidden = False
            self._hwnd = _make_no_activate_topmost(self.root)

        try:
            audio = b.listener.latest_score()
        except Exception:
            audio = 0.0
        up = int(time.time() - b._started)
        tag = _STATE_ZH.get(state, state) + ("（暫停）" if b.paused else "")
        self.lbl.config(text=(
            f"● {tag}\n"
            f"動作: {b.last_action}\n"
            f"音訊: {audio:.2f}    運行: {up // 3600}h{(up % 3600) // 60:02d}m{up % 60:02d}s"
        ))
        if not self._hidden and self._hwnd:
            # 重新確保置頂，但不搶焦點（SWP_NOACTIVATE）
            try:
                ctypes.windll.user32.SetWindowPos(self._hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP)
            except Exception:
                pass
        self.root.after(300, self._poll)
