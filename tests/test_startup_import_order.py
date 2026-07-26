"""H061 回歸測試集：實機啟動路徑的四道防線。

事故（2026-07-26）：P1-P5 網頁 UI 整合後三次啟動全部「卡死」——只挖 D1、主迴圈沒進、
遙控器沒出來、log 停住不動。

**真根因不是 hang，是無聲死亡。** `啟動挖礦bot.bat` 走 `pythonw -m miningbot` ＝
Microsoft Store 版 Python，跟 `uv sync` 灌的 `.venv` 是兩個環境，前者沒有
fastapi/uvicorn。舊碼在 `Bot.run()` 裡 deferred import → daemon thread 丟
`ModuleNotFoundError` → `pythonw` 沒有 console，預設的 `threading.excepthook` 把
traceback 印到不存在的 stderr → 整個失敗蒸發。HUD 主執行緒還活著、
`init_mining_sequence` 早已按下 W＋左鍵，看起來就像卡住。

⚠ 調查期間曾誤判成「多執行緒 import lock 死結」。之所以能自圓其說，是因為 mini repro
用 `uv run` 跑（那個環境有 uvicorn）——**整條調查比對了錯的直譯器**。查實機問題第一件事
是確認 production 跟重現環境是不是同一顆 Python。

本檔守四件事：

1. web 模組在**模組層** import（`__main__.py` splash 期間跑完、零 bot thread）
2. bot 執行緒 crash **不得無聲**（log fatal + HUD + 彈框）
3. 缺 fastapi/uvicorn 時**降級**而不是讓整個 module import 炸掉
4. `uvicorn.Config` 必須 `log_config=None`（pythonw 無 stdout），且 WebIPC 起不來時
   退回 Discord、**不可停止挖礦**
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


# ---------------------------------------------------------------------------
# 2026-07-26 實機第二輪：web 依賴裝好之後，第一次真的走到 WebIPCThread.start()
# 就炸了——uvicorn 預設 log_config 的 DefaultFormatter.__init__ 無條件呼叫
# `sys.stdout.isatty()`，而實機用 `pythonw` 啟動、**沒有 stdout**（sys.stdout is
# None）→ AttributeError → dictConfig 失敗 → `ValueError: Unable to configure
# formatter 'default'` 從 uvicorn.Config(...) 拋出，bot 執行緒當場死。
#
# ⚠ 這發生在 **Config 建構時**，不是 import 時——所以先前「import 時 dictConfig
# 0 calls」的檢查看起來乾淨卻毫無保護力。
# ---------------------------------------------------------------------------


def test_uvicorn_config_disables_log_config():
    """web_server 必須傳 log_config=None，否則 pythonw（無 stdout）下起不來。"""
    src = (REPO_ROOT / "miningbot" / "web_server.py").read_text(encoding="utf-8")
    assert "log_config=None" in src, (
        "uvicorn.Config 必須帶 log_config=None——它預設的 DefaultFormatter 會呼叫 "
        "sys.stdout.isatty()，pythonw 下 sys.stdout is None 直接炸")


def test_web_server_starts_without_stdout(monkeypatch):
    """行為驗證：把 sys.stdout 換成 None（模擬 pythonw）仍要能 bind。"""
    from miningbot.web_server import WebIPCThread
    from miningbot.web_ipc import PendingReplies, FallbackState

    monkeypatch.setattr(sys, "stdout", None)
    t = WebIPCThread(pending=PendingReplies(), fallback=FallbackState(), port=0)
    try:
        t.start()
        assert t.actual_port > 0, (
            "sys.stdout=None（pythonw）時 uvicorn 仍必須起得來")
    finally:
        t.stop()
        t.join(timeout=3)


def test_web_start_failure_does_not_stop_mining():
    """WebIPCThread 起不來時：清成 None 退回 Discord fallback，run() 不得往外拋。

    網頁 UI 是加值功能。實機那次是例外一路穿出 run()、bot 執行緒直接死——挖礦
    整個停擺。這裡驗結構性防護：失敗後三個 web 屬性都是 None（每條 web 路徑都守
    它們），且錯誤原因留在 _web_start_error 供 Discord 狀態行顯示。
    """
    import miningbot.main as main_mod
    from miningbot.config import DEFAULT as cfg
    from tests.fake_bot import make_fake_bot

    src = (REPO_ROOT / "miningbot" / "main.py").read_text(encoding="utf-8")
    assert "_web_start_error" in src, "WebIPC 啟動失敗要留下原因"
    # run() 裡的 WebIPC 區塊必須包在 try/except 內
    run_src = src[src.index("        # WebIPC server"):]
    run_src = run_src[:run_src.index("        self.logger.info(\"初始化完成")]
    assert "try:" in run_src and "except Exception" in run_src, (
        "WebIPC 啟動區塊必須包 try/except——web 壞掉不可以讓 bot 停止挖礦")

    # 狀態行要能講出「啟動失敗」
    bot = make_fake_bot(bind=["_format_web_status"], _web_thread=None,
                        _web_start_error="uvicorn boom")
    old = main_mod.WEB_IMPORT_ERROR
    old_enabled = cfg.web_server_enabled
    try:
        main_mod.WEB_IMPORT_ERROR = None
        cfg.web_server_enabled = True
        line = bot._format_web_status()
        assert "啟動失敗" in line and "uvicorn boom" in line and "Discord" in line
    finally:
        main_mod.WEB_IMPORT_ERROR = old
        cfg.web_server_enabled = old_enabled
