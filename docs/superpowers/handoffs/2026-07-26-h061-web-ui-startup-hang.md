# H061 Web UI 啟動 hang — handoff 給下個 session

> ⚠ **已結案，本檔為歷史資料，且其根因判定是錯的。**
> 這份寫於調查途中，全篇建立在「多執行緒 deferred import C 擴展 → import lock 死結」
> 之上——**那個結論已被推翻**（`de1f4c4`）。真根因是「web import 在 daemon thread 內
> 失敗、pythonw 沒有 stderr → traceback 蒸發 → 執行緒無聲死亡」，因為實機 Store 版
> Python 沒裝 uvicorn，而所有 mini repro 都用 `uv run`（venv 有）＝比對了錯的直譯器。
> **正確版本見 `docs/incidents.md` H061。** 本檔只保留當時的證據鏈與排除清單。

## 一句話現況

P1-P5 web UI 整合後實機啟動卡死，**根因精確定位**（deferred import 在 worker thread 啟動後 race），**修復已 commit**（`afcab21` eager import），**等使用者實機重啟驗證**。下個 session 第一件事：確認驗證結果，走路徑 A（清理 + 補測試）或路徑 B（替換策略）。

## 症狀（使用者回報 + log 證實）

P1-P5 web UI 整合後，2026-07-26 10:31 / 10:43 / 11:19 三次啟動都卡死。實機觀察：

- 只挖 D1（`init_mining_sequence` line 78/90 已 `key_down('w')+mouse_down()` 持續挖）
- D2/D4/D5 常駐效果沒了（main thread 沒進主迴圈 tick 切換裝備）
- 遇到稀有礦物不進稀有挖礦流程（chill audio worker 觸發沒人處理）
- 動作卡在俯仰歸位（HUD `last_action` 停在 line 2340 設的「俯仰歸位（挖礦標準角）」）
- 遙控器消失（`_preflight_and_notify` thread 在 line 2463 啟動，**比 line 2430「初始化完成」晚**；main thread 卡在 2430 之前 → preflight thread 從未啟動 → StatusMessenger.ensure_posted / _ensure_remote_control 沒跑）
- 沒傳 web URL（spec 從未設計 Discord 推 web URL；web URL 只進 miningbot.log）

## 證據鏈

### ⚠ log 位置（MSIX LocalCache trap）

`啟動挖礦bot.bat` 用 `pythonw -m miningbot` 啟動 → MSIX 重導 → log 寫：
```
%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\Local\RexMacro\logs\
├ miningbot.log
├ discord.log
├ events.log
├ actions.log
└ heartbeat.log
```

⚠ LocalCache 目錄列表 mtime/size 會過期數小時（CLAUDE.md 已記）——判斷「跑到幾點」一律 `Get-Content -Tail` 看內容時間戳。

### 精確卡點（[T-DBG] 標記抓到）

`4806ef2` commit 加時間戳 debug log 到 `miningbot/main.py` line 2346-2409 區間。11:19 啟動的 log 印到：

```
2026-07-26 11:20:34 [T-DBG] pre-deferred imports (web_server/web_ipc/web_sink)
2026-07-26 11:20:36 快照清理：刪 2 檔、釋出 4MB      ← worker thread 印的，不是主流程
```

**主流程下一行 `from .web_server import WebIPCThread` 卡 12 分鐘**（直到使用者按 Q 關閉）。worker thread 也跟著停（discord.log 11:20:35「首次輪詢」之後完全靜默；heartbeat.log 11:20 之後完全靜默）→ **process-level 卡死，不是 main thread 獨自卡**。

### mini repro 不卡 vs production 卡

- standalone `uv run python -c "from miningbot.web_server import WebIPCThread"`：5.72s 完成
- standalone + 純 Python worker thread（sleep + print）：4.56s 完成，worker 全程繼續 tick
- production：worker 跑 cv2 OCR / PyAudioWPatch / Tk HUD poll / Discord HTTP → 12 分鐘卡死

→ deferred import 在 worker thread 啟動後跑、跟 cv2/PyAudio/Tk race 卡死。root cause 細節（哪個 C 擴展 init 不釋放 GIL）未釐清，但**worker 啟動之前完成 import** 可避開這個 race。

### 已排除的非根因

- ✘ port 8765 衝突：未佔用
- ✘ `cfg.web_server_enabled` 設 False：實機 cfg 是 True
- ✘ `cfg.discord_channel_id` 沒改：已是 `1530630370234732654`
- ✘ WebIPCThread constructor bug：standalone 正常
- ✘ fastapi/uvicorn import 重配置 logging：spy 驗證 `basicConfig`/`dictConfig` 在 import 時 0 calls
- ✘ import lock 循環：web_server / web_ipc / web_sink import 鏈無循環
- ✘ logger buffer 問題：`RotatingFileHandler` 每次 emit 都 flush
- ✘ unhandled exception：`__main__.py` line 41-49 用 Tk 彈窗接 exception；process 沒彈窗 → 不是 crash

## 已 commit（在 `feature/optimization-roadmap` branch）

| Commit | 內容 | 測試 |
|---|---|---|
| `4806ef2` | 加 `[T-DBG]` 時間戳 debug log 到 main.py line 2346-2409 + line 2440-2475 區間（30 行，臨時） | 1542 passed + 8 skipped |
| `afcab21` | **H061 修復**：Bot.run() 開頭（worker thread 啟動前）eager import web 模組 | 1542 passed + 8 skipped |

兩 commit 都已 push 到 `origin/feature/optimization-roadmap`。

## 未驗證

使用者**還沒用 `afcab21` 重啟驗證**。下個 session 第一件事就是確認這個。

## 後續路徑

### 路徑 A：修復有效（log 跑到「主迴圈 tick #2 進入」）

1. **清理 `[T-DBG]` 標記**（30 行 debug log）— commit
2. **寫 H061 incident** 到 `docs/incidents.md`（症狀/量測/根因/修復）
3. **更新 CLAUDE.md / AGENTS.md**：加 hard rule「web UI 模組（web_server/web_ipc/web_sink）必須在 worker thread 啟動前 eager import」+ miningbot/AGENTS.md 加 threading rule
4. **補測試 gap**（見下節）
5. **遙控器 / WebIPC URL 啟動推播**：使用者要求「啟動時傳 web URL 到 Discord」。spec 沒設計這個，要新增（_preflight_and_notify 內把 web URL 加進啟動訊息文字）。但這要等 web UI 修復確認有效才能加。

### 路徑 B：修復无效（log 仍卡在 `post-eager-import`）

替換策略（風險遞增）：

1. **top-level eager import**：把 web 模組 import 移到 `miningbot/main.py` top-level（line 20-24 區塊），跟 `miningbot.main` 一起載入。worker thread 還沒 spawn，最乾淨。
2. **process 隔離**：WebIPCThread.start() 改 spawn subprocess 跑 uvicorn（IPC 走 socket）。複雜但隔離 race。
3. **臨時 disable**：`Config.web_server_enabled` default 改 False（cfg.py line 482），讓 bot 先能跑；web UI 留後續修。
4. **裝 py-spy dump stack**：`uv pip install py-spy`，下次卡住時 `py-spy dump --pid <pythonw PID>` 抓精確卡點 stack。

### 路徑 C：eager import 有效但要找真根因

`afcab21` 是 race workaround，不是真根因修復。如果時間允許，裝 py-spy 對 deferred import race 重現的 process dump stack，找出哪個 C 擴展 init 不釋放 GIL。把 finding 寫進 H061 incident。

## 測試 gap 分析（這次 hang 沒被測試抓到的根因）

### 為什麼 P1-P5 沒抓到

8 個 `pytest.skip` 全是「main.py 整合需 fake bot；下階段補」從未補回：

```
tests/test_web_server.py:275         test_main_loop_consumes_web_pending_at_safe_point
tests/test_web_server_p3.py:133      main.py 整合 smoke test 留 P4 補
tests/test_web_server_p3.py:141      具體 fake bot 結構依 main.py；留 P4 補
tests/test_web_intervention.py:57    main.py manual_survey 整合需 fake bot；P5 或實機驗收補
tests/test_web_intervention.py:68    main.py _execute_remote_fire 整合需 fake bot；P5 或實機驗收補
tests/test_web_intervention.py:81    main.py reentry click 整合需 fake bot；P5 或實機驗收補
```

每階段都把 fake-bot harness 往下推。所有 web 測試都是 standalone WebIPCThread constructor + start()（`port=0` 隨機、`config=None`），**從未測「Bot.run() 跑到 WebIPCThread 區塊」的整合路徑**。

P5 final review parked finding 4 已經提到「3 個 P4 skeleton skip tests 仍在 test_web_intervention.py（main.py↔web 完整整合需 fake-bot harness）——未來補」——優先級壓低，這次實機證明它是 critical。

### 補測試規劃（路徑 A 必做）

寫 `tests/test_main_startup_integration.py`：

1. mock `_focus_roblox` / `capture.grab` / `audio.LoopbackCapture` / `ic.*` 等 I/O
2. 用 timeout thread 包住 `Bot.run()`
3. 等「初始化完成」log 出現或 30s timeout
4. 驗證：
   - WebIPCThread.actual_port > 0
   - 主迴圈進入（看 actions.log 第一筆）
   - `_preflight_and_notify` thread 啟動（看 discord.log 或 miningbot.log）
   - `_ensure_remote_control` 跑過（看 discord.log）

這個 fake-bot harness 也可以同時覆蓋 P1-P5 留下的 8 個 skip。

## 相關檔案 / line number

| 檔案 | 區間 | 內容 |
|---|---|---|
| `miningbot/main.py` | line 2279-2475 | `Bot.run()` 啟動流程（含 [T-DBG] 標記） |
| `miningbot/main.py` | line 2279-2291 | **H061 修復**：eager import 區塊（`afcab21`） |
| `miningbot/main.py` | line 2372-2408 | WebIPCThread 區塊（原 deferred import race 點） |
| `miningbot/main.py` | line 2428-2463 | `_preflight_and_notify` thread + `_ensure_remote_control` |
| `miningbot/web_server.py` | line 431-547 | `WebIPCThread` class |
| `miningbot/status_hud.py` | line 7432（main.py） | HUD 在 main thread；Bot.run() 在 daemon thread |
| `miningbot/__main__.py` | line 11-49 | pythonw 啟動入口 + Tk exception 彈窗 |

## 工具指令

```powershell
# 看實機 log（路徑切勿假設，必看內容時間戳勿信目錄 mtime）
Get-Content "$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\Local\RexMacro\logs\miningbot.log" -Tail 50 | Select-String "T-DBG|初始化完成|WebIPC|ERROR|Traceback"

# 重啟驗證
cd "C:\Users\puppy\OneDrive\Desktop\無聊的挖礦遊戲"
.\啟動挖礦bot.bat

# 終結卡住的 process（pythonw PID 從 tasklist 找）
Stop-Process -Name pythonw3.11 -Force

# 全測試（約 4 分鐘）
uv run pytest -q
```

## Git 狀態

- branch: `feature/optimization-roadmap`
- HEAD: `afcab21`
- 遠端 `origin/feature/optimization-roadmap` 已同步至 `afcab21`
- 工作目錄乾淨（除了 handoff 文件本身未 commit、`.omc/` untracked operational artifacts）

## 給下個 session 的起手式

1. **讀本 handoff 完整內容**（特別是「路徑 A/B/C」與「測試 gap 分析」）
2. **問使用者**：「`afcab21` 是否已重啟驗證？log 結果？」
3. **如未驗證**：提示使用者用 `.\啟動挖礦bot.bat` 重啟，提供 log 觀察指令
4. **如已驗證且修復有效**：走路徑 A
5. **如已驗證但修復无效**：走路徑 B（top-level eager import 是首選，比 subprocess/disable 風險低）
6. **如懷疑 root cause 細節**：走路徑 C，裝 py-spy dump stack

⚠ **不要**：
- 不要把 H061 修復當作「root cause 已知」——這是 race workaround，真根因（哪個 C 擴展 race）未釐清
- 不要急著刪 [T-DBG] 標記——等修復確認有效再清
- 不要把 web URL Discord 推播跟 H061 修復混在同一 commit（不同責任）
- 不要直接重啟 bot 驗證——bot 啟動會自動挖礦干擾使用者遊戲，要等使用者授權
