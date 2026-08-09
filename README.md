# 🪦 無聊的挖礦遊戲 — Roblox REX 全自動挖礦

> **這個遊戲，把你的 Roblox 視窗綁架了。**
>
> 你掛著挖礦，就不能玩別的。你想去玩 Blade Ball？不行，REX 還在挖。
> 你想跟朋友去 Brookhaven？不行，礦還沒挖完。你離開一下，回來發現
> 角色卡住了、boost 過期了、稀有礦跑掉——三個小時白掛。
>
> 那有沒有辦法讓它自己挖、自己顧、出事了還會叫你？然後你可以用
> 手機在 Discord 上按個按鈕就好了？
>
> **這就是這個專案。** 你把這台電腦開著跑 bot，它幫你挖、幫你補 buff、
> 幫你採稀有礦，聽到 chill 音效自動掃描八方位，採到了還會截圖傳 Discord
> 跟你說。你甚至可以從手機網頁直接點畫面開火。
>
> 然後你就可以去玩別的遊戲了。因為 Roblox 只能開一個視窗——但誰說
> 那個視窗裡的礦，得你自己挖？
>
> ⚠ **這個專案我已經不再維護了。** 程式碼留在這裡，給所有被 REX 綁架
> 的人。想改就用，想接手就 fork。座標是 1920×1080 全螢幕的，你自己
> 的解析度不一樣就得重校——但至少邏輯都寫好了，不用從零開始。

---

## 這是什麼

Windows 專用 Python 3.11+ 自動化程式，主要流程包含挖礦、D5 boost、
D4 活動刷新、chill 音訊偵測、稀有礦掃描/瞄準/採集、聊天驗證、
Discord 遙控，以及手動／遠端／實驗性自動回礦。

`miningbot/main.py` 是狀態機與 I/O 編排核心；純決策邏輯拆在
`states.py`、`harvester.py`、`miner.py`、`game_data.py` 等模組裡。

## 安裝

1. 安裝 Python 3.11+、Tesseract OCR，並讓 Roblox 以 **1920×1080 全螢幕** 執行
   （2026-07-28 起的座標基準；舊版基準是「工作列可見的最大化視窗」，兩者版面差
   頂部 29px／底部 50px，換回去要重新校準偵測區域）。
2. 安裝 [uv](https://docs.astral.sh/uv/) 後，在專案根目錄執行：

   ```powershell
   uv sync --locked
   ```

   `ocr-native` 會安裝已鎖定 hash 的 Windows/Python 3.11 tesserocr wheel；無法使用時程式仍會
   回退 pytesseract。舊環境可使用 `pip install -r requirements.txt`，但該檔只保留 runtime
   相依；完整可重現環境以 `pyproject.toml + uv.lock` 為準。
3. 複製 `.env.example` 為 `.env`，填入 Discord token/channel；不用 Discord 可留空。
4. 準備 chill 參考與本機模板：

   ```powershell
   uv run python -m miningbot.convert_audio "你的chill.mp3"
   uv run python -m miningbot.fetch_trackers
   uv run python -m miningbot.calibrate
   ```

5. 啟動：雙擊 `啟動挖礦bot.bat`，或執行 `uv run python -m miningbot`。有主控台需求時可用
   `uv run python -m miningbot.main`。

## 熱鍵

- **Ctrl+Q**：只暫停並放開按鍵。
- **Q**：暫停／恢復；在啟動檢查期間代表跳過目前檢查。
- **F12**：結束程式。

（R 取樣視窗已於 2026-07-17 退役：截圖走遙控器 📷、俯仰走回礦 `仰角` 指令。）

## Discord 與回礦

支援 `pause`、`resume`、`status`、`shot`、`ability`、`list`、`keep`、`unkeep`、`clear`、
`回礦`／`reenter` 等命令。`reentry_mode` 可設為 `off`、`remote`、`auto`；預設為 `remote`，
`auto` 必須先完成本機 surface template 校準。

## 網頁 UI

bot 內建網頁介面（`web_server_enabled`，預設開；綁 `web_server_host`＝這台機器的
Tailscale IP，Tailscale 沒起來時自動退回 `127.0.0.1`）。四個頁面：`/intervention`
（即時介入：遙控器五鍵＋常駐狀態＋pinch-zoom 點畫面直接開火／點傳送板）、`/`
（玩家設定：白名單欄位＋保留清單＋D2 開關）、`/history`、`/annotate`。

網頁沒人連著（或斷線超過 `web_fallback_grace_s`）就自動退回既有的 Discord 反應按鈕流程，
兩邊**先到先贏**。操作說明、Tailscale 設定與排錯見 [`docs/web-ui-guide.md`](docs/web-ui-guide.md)。

⚠ 網頁 UI 需要 `fastapi`／`uvicorn`／`websockets` 裝在**實際啟動 bot 的那顆直譯器**上
（`啟動挖礦bot.bat` 走 `pythonw` ＝ Store 版 Python，跟 `.venv` 是兩個環境）。缺件時
bot 照常挖礦、只關掉網頁 UI 並在 `miningbot.log` 與 Discord 啟動訊息說明——見
`docs/incidents.md` H061。

## 記錄、效能與除錯

新安裝預設把執行期資料放在 `%LOCALAPPDATA%\RexMacro\logs`，避免 OneDrive 同步大量 PNG。
可在 `.env` 設 `REX_MININGBOT_LOG_DIR` 覆寫。舊的 repo `logs/` 不會被自動搬動或刪除。

- `miningbot.log`：狀態切換、警告、里程碑。
- `actions.log`／`harvest.log`／`discord.log`：子系統細節。
- `heartbeat.log`：心跳以及 capture/observe/tick/loop 的 p50、p95、p99。
- `snapshots/`：依 trace、review、events、reentry、trackers 分類；trace 預設保留 7 天／256MB，
  全部快照總量上限 1GB。

真實 session 的取樣 profiler：

```powershell
uv run py-spy record -o profile.svg -- python -m miningbot.main
```

先讀 `heartbeat.log` 的分位數與 `profile.svg`，再決定是否 A/B 測試其他 capture backend；不要直接
替換 `mss`。

## 開發驗證

```powershell
uv run ruff check .
uv run pytest -q
```

GitHub Actions 使用 `windows-latest + Python 3.11` 執行同一組 locked checks。OCR、座標或視覺門檻
變更必須以真實 fixture 做正反兩側回歸；預設測試不會操作 Roblox、Discord 或實體音訊裝置。

## 專案結構

```
miningbot/        核心程式碼（狀態機、採集、視覺、音訊、回礦、網頁 UI）
tests/            單元測試 + 追蹤 fixture 回歸
assets/           JSON 資料集 + 文件
docs/             參考文件、事故記錄、歷史設計
*.mcr             原始人工錄製的 Roblox 巨集
```

開發者請先讀 `AGENTS.md`（唯一操作契約）與 `CLAUDE.md`。

## 授權

本專案僅供學習與個人使用。Roblox 自動化可能違反遊戲服務條款，後果自負。
