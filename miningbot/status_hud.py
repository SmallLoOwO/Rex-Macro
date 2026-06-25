"""置頂狀態小窗：即時顯示機器人目前狀態/動作，不用猜它在幹嘛。

放左下角（避開頂部 chill 區與右下 boost 區）；採集（HARVESTING，全畫面找標記）時
自動隱藏，避免擋住偵測。在主執行緒跑 tkinter，機器人跑在背景執行緒。
"""
import time
import tkinter as tk

_STATE_ZH = {"MINING": "挖礦中", "HARVESTING": "採集稀有礦", "NEEDS_HUMAN": "需要人工"}


class StatusHUD:
    def __init__(self, bot, x: int = 12, y: int = 905):
        self.bot = bot
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
                            font=("Consolas", 11), fg="#00ff88", bg="#0b0b0b",
                            padx=12, pady=8)
        self.lbl.pack()
        self._hidden = False
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

        try:
            audio = b.listener.latest_score()
        except Exception:
            audio = 0.0
        up = int(time.time() - b._started)
        s = b.stats
        tag = _STATE_ZH.get(state, state) + ("（暫停）" if b.paused else "")
        self.lbl.config(text=(
            f"● {tag}\n"
            f"動作: {b.last_action}\n"
            f"音訊: {audio:.2f}    運行: {up // 60}m{up % 60:02d}s\n"
            f"boost {s['boosts']} · 刷新 {s['rerolls']} · 稀有 {s['rares']} · 卡住 {s['stuck']}"
        ))
        if not self._hidden:
            try:
                self.root.lift(); self.root.attributes("-topmost", True)
            except tk.TclError:
                pass
        self.root.after(300, self._poll)

    def run(self):
        self.root.mainloop()
