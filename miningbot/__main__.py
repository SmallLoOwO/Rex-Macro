"""啟動入口：先顯示載入視窗，再 import 主程式。

pythonw -m miningbot.main 會在重型 import（numpy/cv2/scipy ~2-3s）期間什麼都看不到。
改用 pythonw -m miningbot 走本檔：splash 先出 → import 在 splash 顯示期間跑 → 完成後進主程式。
"""
import ctypes
import os
import sys


def main():
    # DPI-aware 必須在任何 GUI 之前（同 main.py _set_dpi_aware）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # 立刻顯示載入視窗（tkinter 是 stdlib，import ~0.1s）
    import tkinter as tk
    splash = tk.Tk()
    splash.title("MiningBot")
    splash.geometry("280x70")
    splash.resizable(False, False)
    splash.update_idletasks()
    w, h = 280, 70
    sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
    splash.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    tk.Label(splash, text="載入中，請稍候…",
             font=("Microsoft JhengHei", 13)).pack(expand=True)
    splash.update()                       # 強制繪製（不呼叫 mainloop）

    # 重型 import 在此發生（splash 可見）——numpy/cv2/scipy 等。pyaudiowpatch 不在
    # 此列：它延後到 audio.LoopbackCapture._run() 才 import（背景音訊執行緒首次呼叫時），
    # splash 階段完全沒載到它（2026-08-08 tesserocr 主執行緒 bug 排查時順手核對到）。
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from miningbot.main import main as bot_main
        splash.destroy()                  # 關閉載入視窗
        bot_main()                        # 進入正式啟動流程（HUD 倒數 → bot.run）
    except Exception:
        splash.destroy()
        import traceback
        tb = traceback.format_exc()
        err = tk.Tk()
        err.title("MiningBot 錯誤")
        tk.Label(err, text=tb, justify="left",
                 font=("Consolas", 9)).pack(padx=10, pady=10)
        err.mainloop()


if __name__ == "__main__":
    main()
