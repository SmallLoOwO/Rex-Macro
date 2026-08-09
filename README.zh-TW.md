[English](README.md) | **繁體中文**

# 🪦 無聊的挖礦遊戲 — REx: Reincarnated 全自動挖礦

> **這個遊戲，把你的 Roblox 視窗綁架了。**
>
> REx: Reincarnated 是一個挖礦遊戲。嚴格說起來，Roblox 有個 bug 可以讓你掛機
> 挖——按著 W 走開就好，角色會繼續敲。但 boost？它不會自己按。沒有人主動
> 補 boost，你就是用基礎速度在挖——零加成。那個 bug 給你的是揮鎬的動作，
> 不是挖礦的效益。而且稀有礦還是要手動掃描、瞄準、開火——離開太久稀有礦
> 就消失了。你掛著就不能玩別的，想去玩 Grow a Garden？不行，REx 還佔著你的
> 視窗。想去 Brookhaven 找朋友？不行，礦還沒挖完。
>
> 還有合成系統。後期物品需要的材料，要你**連續不間斷地挖數十到上百小時**
> 才湊得齊。一件終局裝備——就那麼一件——可能代表你要連續好幾個禮拜什麼
> 都不做，就只是按著 W 然後點滑鼠。這已經不是遊戲了，這是一份沒有薪水
> 的第二份工作。
>
> 那有沒有辦法讓它自己挖、自己顧、出事了還會叫你？然後你可以用
> 手機在 Discord 上按個按鈕就好了？
>
> **這就是這個專案。** 你把這台電腦開著跑 bot，它幫你挖、幫你補 buff、
> 幫你採稀有礦，聽到 **chill**（遊戲在稀有礦出現時播放的特殊音效）自動
> 掃描八方位，採到了還會截圖傳 Discord 跟你說。你甚至可以從手機網頁
> 直接點畫面開火。
>
> 然後你就可以去玩別的遊戲了。因為 Roblox 只能開一個視窗——但誰說
> 那個視窗裡的礦，得你自己挖？
>
> 說真的，等到你已經在 REx 裡砸了好幾百個小時，這遊戲除了挖礦之外
> 已經沒什麼好玩的了。任務解完了、進度到頂了、新鮮感沒了，唯一剩下
> 的事就是對著牆壁發呆然後多擠出幾顆稀有礦。這個 bot 就是寫給那種
> 玩家的——什麼都看過了、什麼都玩過了，只想要礦、不想要那個折磨人
> 的過程。
>
> ⚠ **這個專案我已經不再維護了。** 程式碼留在這裡，給所有被 REx 綁架
> 的人。想改就用，想接手就 fork。座標是 1920×1080 全螢幕的，你自己
> 的解析度不一樣就得重校——但至少邏輯都寫好了，不用從零開始。
>
> ⚠⚠ **這個專案還沒做完。** 它有已知的 bug、沒測過的邊界情況、還有我
> 停手時仍在開發中的功能。有些偵測邏輯很脆弱，有些流程太常退化成
> 「叫人來處理」，有些東西我根本沒機會在實機上驗證過。完整的已知問題
> 清單見 `docs/incidents.md` 和 `docs/open-detection-issues.md`。
> **把它當起點，不要當成品。**

---

## 快速了解

| 問題 | 回答 |
|---|---|
| **掛著睡覺行嗎？** | **不行。** 這是輔助工具，不是全自動駕駛。它讓你可以離開鍵盤，但每 20–30 分鐘應該檢視一次。 |
| **多常需要我介入？** | 每 20–30 分鐘——確認採集結果、處理礦坑重置、注意突發狀況。 |
| **出事了怎麼辦？** | 全部記 log、截圖存證、Discord 通知你。最壞情況就是暫停等你回來。 |
| **需要會寫程式嗎？** | **視情況。** 如果你的設定跟原作者一樣，開箱即用。如果需要改物品、座標或行為，就要改 Python 程式碼。 |

<!-- TODO: 加截圖 — bot 挖礦中、Discord 採集通知、網頁 UI 介入面板 -->

---

## 這是什麼

Windows 專用 Python 3.11+ 自動化程式，target 是 [REx: Reincarnated](https://www.roblox.com/games/8549934015/REx-Reincarnated)。
負責挖礦、boost 維護、稀有礦偵測與採集、Discord 遙控、以及礦坑重置後的回礦。

## 必備遊戲內物品（後期限定）

**這個 bot 是寫給後期玩家的。** 「後期」是什麼意思？你應該已經：

- 知道 **chill** 是什麼——遊戲在稀有礦出現時播放的特殊音效
- 已經做出 **Tier 6 十字鎬**
- 有足夠材料**合成**下列四件工具（或已經有了）
- 了解遊戲的 boost、掃描器和事件機制

如果你還在前期，這個 bot 幫不了你——等你進度夠深、四件都合成完了再來。

### 鍵位設定——很重要

原作者把這四件物品放在遊戲內的**快捷鍵 2、3、4、5** 上。bot 會直接按
這些數字鍵。**你必須用一樣的鍵位**，或者去 `miningbot/config.py` 改成你
自己的按鍵對應。

| 按鍵 | 物品 | 功能 | Wiki |
|---|---|---|---|
| **鍵 2** | Cybernetium Radar | 掃描範圍內的稀有礦追蹤框 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Cybernetium_Radar) |
| **鍵 3** | Laser Scope | 瞄準並射擊偵測到的追蹤框，採集稀有礦 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Laser_Scope) |
| **鍵 4** | Lucidium Locator | 事件雷達——bot 用它決定隨機事件的保留/重骰 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Lucidium_Locator) |
| **鍵 5** | Bucket of Sealed Whispers | 挖礦 boost——bot 到期自動補 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers) |

這些全部都買不到——每一件都是合成配方，需要深層挖礦的材料和稀有
掉落物。這就是重點：等你四件都有了，這遊戲除了繼續挖礦也沒別的事
能做了，而那正好就是這個 bot 幫你省掉的部分。

> **想換成別的物品，或直接移除某些功能？** 程式碼是你的，隨你改。你可以
> 把不需要的子系統整個拿掉（例如沒有 Lucidium Locator 就移除事件保留/重骰
> 邏輯），也可以換成弱化版替代品。例如 [Bucket of Sealed
> Whispers](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers)
> 可以換成弱化版的 [Reaper Bucket](https://rex-reincarnated.fandom.com/wiki/Reaper_Bucket)，
> 只需要調整 `config.py` 和 `miner.py` 裡的 boost 冷卻與持續時間參數。
> **但預設程式碼假設四件都放在鍵 2–5 上**，所以要移除或替換物品的話，
> 需要自己去 `miningbot/` 裡找到相關邏輯來改。

## ⚠ 介面是中文的

**所有遊戲內互動文字、Discord 訊息、網頁 UI 標籤、log 和通知都是
繁體中文。**

要換成英文（或其他語言），需要自己找中文字串改。程式邏輯和識別字是
英文的——只有玩家可見的文字是中文。要改哪些檔案見下面的[開發者指南](#開發者指南)。

---

# 玩家指南

## 安裝

> ⚠ **這不是一鍵安裝的 app。** 你需要 Python 3.11+ 和基本的命令列操作能力。
> 如果你從沒用過命令列，安裝過程會很痛苦。

1. 安裝 **Python 3.11+** 和 **Tesseract OCR**。Roblox 以 **1920×1080 全螢幕** 執行。
2. 安裝 [uv](https://docs.astral.sh/uv/) 後執行：

   ```powershell
   uv sync --locked
   ```

3. 複製 `.env.example` 為 `.env`，填入 Discord token 和頻道 ID。不用 Discord 可留空。
4. 在遊戲內設好快捷鍵——把四件物品放在**鍵 2、3、4、5** 上（見上方[鍵位設定](#鍵位設定很重要)）。
5. 準備 chill 參考音檔與遊戲模板：

   ```powershell
   uv run python -m miningbot.convert_audio "你的chill.mp3"
   uv run python -m miningbot.fetch_trackers
   uv run python -m miningbot.calibrate
   ```

6. 啟動：雙擊 `啟動挖礦bot.bat`，或執行 `uv run python -m miningbot`。

## 熱鍵（控制 bot）

- **Ctrl+Q**：暫停並放開所有按鍵。
- **Q**：暫停／恢復。
- **F12**：結束程式。

## Discord 指令

bot 會在你設定的 Discord 頻道回應訊息：

- `pause`／`resume`——控制挖礦
- `status`——查看 bot 正在做什麼
- `shot`——截圖
- `list`／`keep`／`unkeep`——管理礦物保留清單
- `clear`——清空背包篩選
- `回礦`／`reenter`——礦坑重置後重新進入

回礦有三種模式：`off`（不動）、`remote`（等你的 Discord 指令，預設）、
`auto`（自動回礦，需先校準）。

## 網頁 UI

bot 內建網頁介面，可以從手機瀏覽器遙控——點畫面開火、點傳送板、調設定。

透過 Tailscale IP 連線（沒起來自動退回 `127.0.0.1`）。沒人連著就自動退回
Discord 按鈕流程。詳見 [`docs/web-ui-guide.md`](docs/web-ui-guide.md)。

⚠ 網頁 UI 需要跟 bot 同一個 Python 環境裝了 `fastapi`、`uvicorn`、
`websockets`。缺件的話 bot 照常挖礦，只是沒有網頁介面。

---

# 開發者指南

> 這一段是給想修改 bot 的人看的——改物品、座標、門檻或行為。如果預設
> 設定就能用，整段可以跳過。

## 專案結構

```
miningbot/
  main.py          bot 編排與執行期狀態
  config.py        所有座標、門檻、按鍵對應、模式
  states.py        狀態機
  harvester.py     採集決策與工具操作
  miner.py         挖礦迴圈、boost 維護
  vision.py        追蹤框偵測與形狀仲裁
  ocr.py           聊天驗證與 OCR
  audio.py         chill/重置音訊評分
  game_data.py     礦物分類、階級門檻、世界資料
  reentry*.py      回礦邏輯（自動與遠端）
  remote_aim.py    Discord 輔助採集瞄準
  web_*.py         網頁 UI：FastAPI、WebSocket IPC、HTML
tests/             單元測試 + fixture 回歸
assets/            JSON 資料集 + 文件
docs/              參考文件、事故記錄
```

從 `config.py` 開始——所有座標、門檻、時間間隔、按鍵對應、模式都在那裡。
操作慣例和不可違反的執行期規則見 `AGENTS.md`。

## 改按鍵對應

bot 透過 `pydirectinput` 發送按鍵。要改哪個鍵觸發哪件物品，改 `config.py`
裡的按鍵常數（搜尋 slot/tool key 定義）。注意：Roblox 的工具鍵是
**toggle**——已裝備再按會卸下，所以 bot 有邏輯確認正確的 slot 已選才動作。

## 改介面語言

所有中文玩家可見文字分布在：

| 區域 | 檔案 |
|---|---|
| Discord 訊息 | `notify.py`、`reentry_remote.py`、`remote_aim.py` |
| 網頁 UI HTML | `web_static.py` |
| log 文字 | 整個 `miningbot/*.py`（搜尋 CJK 字元） |
| 說明文字 | `main.py`（`_poll_discord` 指令說明） |

## 開發

```powershell
uv run ruff check .
uv run pytest -q
```

OCR、座標或視覺門檻變更需用真實 fixture 做兩側回歸——預設測試不會
操作 Roblox、Discord 或實體音訊裝置。

## Log

執行期資料預設在 `%LOCALAPPDATA%\RexMacro\logs`。可用 `.env` 裡的
`REX_MININGBOT_LOG_DIR` 覆寫。

- `miningbot.log`——狀態切換、警告、里程碑
- `actions.log`／`harvest.log`／`discord.log`——子系統細節
- `heartbeat.log`——延遲分位數（p50/p95/p99）
- `snapshots/`——分類診斷截圖

## 致謝

使用 [FastAPI](https://github.com/fastapi/fastapi)、[OpenCV](https://github.com/opencv/opencv-python)、
[RapidOCR](https://github.com/RapidAI/RapidOCR)、[Tesseract](https://github.com/tesseract-ocr/tesseract)、
[NumPy](https://github.com/numpy/numpy)、[SciPy](https://github.com/scipy/scipy)、
[mss](https://github.com/BoboTiG/python-mss)、[pydirectinput](https://github.com/learncodebygaming/pydirectinput)、
[PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) 等開源專案打造。

## 授權

僅供學習與個人使用。Roblox 自動化可能違反遊戲服務條款，後果自負。
