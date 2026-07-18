# CLAUDE.md — Roblox REX 挖礦自動化

先讀根目錄 `AGENTS.md`。它是唯一的專案操作契約；本檔只提供 Claude
相容入口，不複製會隨程式變動的門檻、數量、預設值或事故全文。

## 專案定位

這是 Windows 專用的 Python 3.11+ Roblox REX 自動化程式。核心是
`miningbot/main.py` 的狀態機與 I/O 編排，純決策分散在 `states.py`、
`harvester.py`、`game_data.py`、`reentry*.py`、`remote_aim.py` 等模組。

目前行為以程式、測試與 `miningbot/config.py` 為準：

- 世界清單讀 `miningbot.game_data.WORLDS`；wiki 同步工具會排除已移除或
  合併的世界。
- 回礦由 `Config.reentry_mode` 控制：`off`、`remote`、`auto`。
- D3 必須使用 `2 → 0.15s → 3 → 0.3s → hold-click 0.4s → 0.5s`。
- 採集成功只認 episode 內新增的稀有／特殊聊天證據。追蹤框消失但未確認
  時必須重掃。
- 容量 100% 只加速 reset banner 輪詢；不能自行進入 `RESET_WAIT`。
- Discord 背景執行緒只能發布 pending/cache；遊戲輸入由主迴圈消費。

上述規則的完整版本與其他硬限制都在 `AGENTS.md`。

## 常用命令

```powershell
uv sync --locked
uv run pytest --collect-only -q
uv run pytest -q
uv run ruff check . --no-cache
uv lock --check

uv run python -m miningbot.main
pythonw -m miningbot

uv run python -m miningbot.fetch_ores
uv run python -m miningbot.fetch_trackers
uv run python -m miningbot.capture_template boost
uv run python -m miningbot.calibrate_surface --import NNN
uv run python -m miningbot.calibrate_pitch
```

## 修改前查閱順序

| 修改範圍 | 先讀 | 驗證重點 |
|---|---|---|
| 狀態／reset | `states.py`、對應 H 事故 | transition、direct assignment、pause/resume |
| tracker | H039/H040、`tests/test_vision.py` | 真陽性與裝備/UI 負樣本兩側夾門檻 |
| OCR／聊天 | H014/H020/H032/H041 | pass 自洽、`ChatLedger`、晚到確認、引擎降級 |
| D3／掃描 | `harvester.py`、原始 `.mcr` | toggle、settle、固定按鍵與 hold 時序 |
| 世界／礦物 | `game_data.py`、`fetch_ores.py` | active registry、低高階衝突、JSON 同步 |
| 回礦／remote aim | 最新已實作 spec 與純測試 | bounded failure、ledger、pitch/zoom 復原 |
| UI／取樣 | `docs/manual-sampling.md` | Tk BMP-safe 文字、主執行緒 UI |

## 相容與 fail-safe 邊界

- RapidOCR 是聊天 OCR 首選；初始化失敗時可退回既有 tesseract 路徑。
- 小型 banner/menu OCR 仍使用既有 tesserocr/pytesseract 適配層。
- 缺少機器本地 PNG/WAV 時必須有 preflight 或 log 警告，不能靜默改變
  行為。測試需要的素材應放在追蹤的 `tests/fixtures/`。
- 這些降級路徑是外部引擎／素材邊界的安全措施；修改時要保留主路徑與
  降級路徑測試。

## 實機排錯

- 日誌根目錄讀 `Config.log_dir`；不要假設一定是 repo 內的 `logs/`。
- ⚠ 用 `pythonw -m miningbot`（Microsoft Store/MSIX Python）跑時，寫
  `%LOCALAPPDATA%\RexMacro\logs` 會被 MSIX 虛擬化重導到
  `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\Local\RexMacro\logs`
  ——log 內印的路徑直接 Test-Path 會撲空，查實機證據去 LocalCache 這份；
  `uv run` 啟動則不受影響。
- 先看 `miningbot.log`，再依問題查看 `actions.log`、`harvest.log`、
  `discord.log` 與分類快照。
- 門檻或座標只根據實機 frame／crop 與對應 H 事故調整；不可用目測猜值。
- 不得因為單一失敗 fixture 就放寬保守判定或刪除事故回歸。

## 工作慣例

- 開始前執行 `git status --short`，保留所有不相關的既有修改。
- 使用 `rg` 找符號，不依賴文件中的歷史行號。
- 座標、門檻、間隔與模式只放在 `Config`。
- 每一次任務製作完成都**必須 commit**：先跑全測試綠，只納入該任務動到
  的檔案，訊息用中文描述變更（涉及事故附 Hxxx 編號）。
- 不主動 push、切 branch、刪除 runtime 證據或操作 Roblox/Discord。
- 舊的強制 opencode 委派流程已退役；使用目前的 Codex 執行面，只有在
  工作可獨立切分且不會造成共享檔衝突時才使用原生子代理。

## 文件地圖

- 現行操作契約：`AGENTS.md`
- 套件／測試局部規則：`miningbot/AGENTS.md`、`tests/AGENTS.md`
- 實機事故證據：`docs/incidents.md`
- 遊戲機制與取樣：`docs/game-mechanics.md`、`docs/manual-sampling.md`
- 素材契約：`assets/README.md`
- 文件狀態與歷史資料說明：`docs/README.md`

`docs/HANDOFF*.md`、`docs/superpowers/**` 與
`docs/opencode-delegation-manual.md` 都是歷史資料，不得用來覆蓋現行程式與
測試。
