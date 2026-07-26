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
         if ln.startswith("    from . import web_server as ")), None)
    assert preload_idx is not None, (
        "main.py 檔頭找不到 web_server 預載 import——H061 修復被移除了？")

    class_idx = next((i for i, ln in enumerate(lines)
                      if ln.startswith("class Bot")), None)
    assert class_idx is not None, "main.py 找不到 class Bot"

    assert preload_idx < class_idx, (
        f"web 預載 import 在 line {preload_idx + 1}，跑到 class Bot（line {class_idx + 1}）"
        "之後了——必須在模組層、任何 thread spawn 之前完成（H061）")
