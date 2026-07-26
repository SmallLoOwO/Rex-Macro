"""H061 回歸：web 模組必須在模組層 import，不可 deferred 到 thread 啟動之後。

事故（2026-07-26）：`from .web_server import WebIPCThread` 原本寫在 `Bot.run()` 裡，
位置在 `Bot.__init__` spawn 的四個 worker（PyAudioWPatch / cv2 snapshot /
`ocr.rapidocr_available` 內 `from rapidocr import RapidOCR` / `ocr.tesserocr_available`
內 `import tesserocr`）**之後**。三個執行緒同時 import 不同 C 擴展 → Python import
lock 死結 → 實機三次啟動全部卡死，連 worker thread 一起靜默。

修復把 import 移到 `miningbot/main.py` 檔頭，`__main__.py` 的
`from miningbot.main import main` 期間就跑完（那時只有 Tk splash、零個 bot thread）。

這兩個測試鎖住這個不變式——有人把 import 搬回 `run()` 或改回 lazy 就會紅燈。
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_web_modules_imported_at_module_level():
    """import miningbot.main 之後，web_server 必須已經在 sys.modules。

    用 subprocess 跑乾淨直譯器：同一個 pytest session 裡別的測試可能已經 import 過
    web_server，在本行程內斷言會假綠。
    """
    from miningbot.config import Config
    if not Config().web_server_enabled:
        pytest.skip("web_server_enabled=False：檔頭 import 區塊被跳過，本不變式不適用")

    code = (
        "import sys; import miningbot.main; "
        "print('YES' if 'miningbot.web_server' in sys.modules else 'NO')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"import miningbot.main 失敗：{proc.stderr[-2000:]}"
    assert "YES" in proc.stdout, (
        "miningbot.web_server 沒有在 import miningbot.main 時一起載入——"
        "H061：web 模組被搬回 deferred import 了，thread 啟動後才 import 會撞 import lock 死結。"
        f"（stdout={proc.stdout!r}）"
    )


def test_web_preload_block_precedes_bot_class():
    """main.py 原始碼層：web 預載區塊必須在 `class Bot` 之前。

    比上面那個測試更直接指出「位置」錯在哪；subprocess 測試若因環境問題 skip，
    這個純文字掃描仍然守得住。
    """
    src = (REPO_ROOT / "miningbot" / "main.py").read_text(encoding="utf-8")
    lines = src.splitlines()

    preload_idx = next(
        (i for i, ln in enumerate(lines)
         if ln.strip().startswith("from . import web_server as ")), None)
    assert preload_idx is not None, (
        "main.py 檔頭找不到 web_server 預載 import——H061 修復被移除了？")

    class_idx = next((i for i, ln in enumerate(lines)
                      if ln.startswith("class Bot")), None)
    assert class_idx is not None, "main.py 找不到 class Bot"

    assert preload_idx < class_idx, (
        f"web 預載 import 在 line {preload_idx + 1}，跑到 class Bot（line {class_idx + 1}）"
        "之後了——必須在模組層、任何 thread spawn 之前完成（H061）")


# ---------------------------------------------------------------------------
# H061 真根因（2026-07-26 實機重現才查到）：不是 hang，是**無聲死亡**。
#
# `啟動挖礦bot.bat` 走 `pythonw -m miningbot` ＝ Microsoft Store 版 Python，跟
# `uv sync` 灌的 .venv 是兩個環境——前者沒有 fastapi/uvicorn。舊碼在 Bot.run()
# 裡 deferred import，於是 daemon thread 丟 ModuleNotFoundError；`pythonw` 沒有
# console，Python 預設的 threading.excepthook 把 traceback 印到不存在的 stderr →
# 整個失敗蒸發。HUD 主執行緒還活著、init_mining_sequence 已經按下 W＋左鍵，看起來
# 就是「只挖 D1、主迴圈沒進、遙控器沒出來、log 停住不動」。
#
# 當初的 mini repro 用 `uv run` 跑（venv 有 uvicorn）所以永遠重現不了，整條調查
# 比對了錯的直譯器。這兩個測試守住修復。
# ---------------------------------------------------------------------------


def test_bot_thread_crash_is_not_silent():
    """bot 執行緒丟例外時必須留下痕跡：log fatal + HUD 顯示 + 收掉 _running。"""
    import logging
    import types
    from miningbot.status_hud import StatusHUD

    class _Boom:
        _running = True
        last_action = "—"
        logger = logging.getLogger("tests.hud_crash")

        def run(self):
            raise ModuleNotFoundError("No module named 'uvicorn'")

    fatal = []
    bot = _Boom()
    bot.logger = types.SimpleNamespace(
        fatal=lambda fmt, *a: fatal.append(fmt % a if a else fmt))

    hud = StatusHUD.__new__(StatusHUD)
    hud.bot = bot
    hud._run_bot_guarded()

    assert fatal, "例外必須寫進 log——pythonw 無 console，不寫 log 就等於沒發生過"
    assert "uvicorn" in fatal[0] and "Traceback" in fatal[0], fatal[0]
    assert "uvicorn" in bot.last_action, f"HUD 要看得到原因，實際：{bot.last_action}"
    assert bot._running is False, "_running 要收掉，否則 HUD 留一個假裝還活著的視窗"
    assert "uvicorn" in hud._thread_crash


def test_missing_web_deps_degrade_instead_of_crashing_import():
    """缺 fastapi/uvicorn 時 main.py 必須降級（關掉 web），不可讓整個 import 炸掉。

    模組層 import 是 H061 的修復，但若直接讓 ImportError 往上拋，實機直譯器缺件就
    變成「連 bot 都開不起來」——比原本的問題更糟。這裡驗降級路徑存在且會留下原因。
    """
    src = (REPO_ROOT / "miningbot" / "main.py").read_text(encoding="utf-8")
    assert "WEB_IMPORT_ERROR" in src, "缺件降級的旗標不見了"
    assert "except ImportError" in src, "web 預載區塊必須吞掉 ImportError 並降級"
    # 降級後要關掉 web，否則後面 WebIPCThread 區塊會再炸一次
    assert "cfg.web_server_enabled = False" in src

    import miningbot.main as main_mod
    assert hasattr(main_mod, "WEB_IMPORT_ERROR")
    # 本測試環境（.venv）有裝 fastapi/uvicorn，所以應該是 None
    assert main_mod.WEB_IMPORT_ERROR is None, (
        f"這個環境的 web 依賴應該齊全，卻回報：{main_mod.WEB_IMPORT_ERROR}")


def test_web_status_line_reports_each_case():
    """啟動 Discord 訊息的網頁狀態行三種情況都要講清楚。"""
    import miningbot.main as main_mod
    from miningbot.config import DEFAULT as cfg
    from tests.fake_bot import make_fake_bot

    bot = make_fake_bot(bind=["_format_web_status"], _web_thread=None)

    # 1) 起來了
    bot._web_thread = type("T", (), {"actual_port": 8765})()
    assert "http://127.0.0.1:8765" in bot._format_web_status()

    # 2) 缺件降級
    bot._web_thread = None
    old = main_mod.WEB_IMPORT_ERROR
    try:
        main_mod.WEB_IMPORT_ERROR = "No module named 'uvicorn'"
        line = bot._format_web_status()
        assert "停用" in line and "uvicorn" in line and "Discord" in line
    finally:
        main_mod.WEB_IMPORT_ERROR = old

    # 3) 設定關掉
    old_enabled = cfg.web_server_enabled
    try:
        cfg.web_server_enabled = False
        line = bot._format_web_status()
        assert "設定" in line
    finally:
        cfg.web_server_enabled = old_enabled
