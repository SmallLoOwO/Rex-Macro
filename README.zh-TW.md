[English](README.md) | **繁體中文**

# 🪦 無聊的挖礦遊戲 — REx: Reincarnated 全自動挖礦

> **這個遊戲，把你的 Roblox 視窗綁架了。**
>
> REx: Reincarnated 是一個挖礦遊戲。嚴格說起來，Roblox 有個 bug 可以讓你掛機
> 挖——按著 W 走開就好，角色會繼續敲。但 D5 boost？它不會自己按。沒有人主動
> 補 D5，你就是用基礎速度在挖——零加成、零 FOV 擴展。那個 bug 給你的是揮鎬的
> 動作，不是挖礦的效益。而且稀有礦還是要手動掃描、瞄準、開火——離開太久稀有礦
> 就消失了。你掛著就不能玩別的，想去玩 Grow a Garden？不行，REx 還佔著你的視窗。
> 想去 Brookhaven 找朋友？不行，礦還沒挖完。
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

Windows 專用 Python 3.11+ 自動化程式， target 是 [REx: Reincarnated](https://www.roblox.com/games/8549934015/REx-Reincarnated)。
主要流程包含挖礦、D5 boost 維護、D4 活動刷新、chill 音訊偵測、稀有礦
掃描/瞄準/採集、聊天驗證、Discord 遙控，以及手動／遠端／實驗性自動回礦。

`miningbot/main.py` 是狀態機與 I/O 編排核心；純決策邏輯拆在
`states.py`、`harvester.py`、`miner.py`、`game_data.py` 等模組裡。

## 必備遊戲內物品（後期限定）

**這個 bot 是寫給後期玩家的。** 「後期」是什麼意思？你應該已經：

- 知道 **chill** 是什麼——遊戲在稀有礦出現時播放的特殊音效
- 已經做出 **Tier 6 十字鎬**
- 有足夠材料**合成**下列四件工具（或已經有了）
- 了解遊戲的 boost、掃描器和事件機制

如果你還在前期，這個 bot 幫不了你——等你進度夠深、四件都合成完了再來。

裝備到 D2–D5 快捷鍵上才能運作：

| 快捷鍵 | 物品 | 功能 | Wiki |
|---|---|---|---|
| **D2** | Cybernetium Radar | 掃描範圍內的稀有礦追蹤框 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Cybernetium_Radar) |
| **D3** | Laser Scope | 瞄準並射擊偵測到的追蹤框，採集稀有礦 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Laser_Scope) |
| **D4** | Lucidium Locator | 事件雷達——bot 用它決定隨機事件的保留/重骰 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Lucidium_Locator) |
| **D5** | Bucket of Sealed Whispers | 挖礦 boost——提升速度與視野，bot 到期自動補 | [Wiki](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers) |

這些全部都買不到——每一件都是合成配方，需要深層挖礦的材料和稀有
掉落物。這就是重點：等你四件都有了，這遊戲除了繼續挖礦也沒別的事
能做了，而那正好就是這個 bot 幫你省掉的部分。

> **想換成別的物品，或直接移除某些功能？** 程式碼是你的，隨你改。你可以
> 把不需要的 D2–D5 子系統整個拿掉（例如沒有 Lucidium Locator 就移除 D4
> 的保留/重骰邏輯），也可以換成弱化版替代品。例如 D5（[Bucket of Sealed
> Whispers](https://rex-reincarnated.fandom.com/wiki/Bucket_of_Sealed_Whispers)）
> 可以換成弱化版的 [Reaper Bucket](https://rex-reincarnated.fandom.com/wiki/Reaper_Bucket)，
> 只需要調整 `config.py` 和 `miner.py` 裡的 boost 冷卻與持續時間參數。這個
> bot 夠模組化，少幾件也能跑。**但預設程式碼假設四件全裝**，所以要移除或
> 替換物品的話，需要自己去 `miningbot/` 裡找到相關邏輯來改——不是改個設定
> 就好的事。

## ⚠ 介面是中文的

**所有遊戲內互動文字、Discord 訊息、網頁 UI 標籤、log 和通知都是
繁體中文。** 包括：

- Discord 指令回覆和 embed 卡片
- 網頁 UI 按鈕、標籤、狀態文字
- log 訊息和警告文字
- 說明文字和玩家可見的指示

要換成英文（或其他語言）的話，需要自己找中文字串改。相關檔案：

| 區域 | 要改的檔案 |
|---|---|
| Discord 訊息 | `miningbot/notify.py`, `miningbot/reentry_remote.py`, `miningbot/remote_aim.py` |
| 網頁 UI HTML | `miningbot/web_static.py` |
| log 文字 | 整個 `miningbot/*.py`（搜尋中文字） |
| 說明文字 | `miningbot/main.py`（`_poll_discord` 指令說明） |
| Config 註解 | `miningbot/config.py` |

**程式邏輯、識別字和 log key 是英文的**——只有玩家可見的文字是中文。

## 安裝

> ⚠ **這不是一鍵安裝的 app。** 你需要 Python 3.11+、終端機、以及基本的
> 命令列操作能力。如果你從沒用過命令列，安裝過程會很痛苦。

1. 安裝 Python 3.11+、Tesseract OCR，Roblox 以 **1920×1080 全螢幕** 執行。
2. 安裝 [uv](https://docs.astral.sh/uv/) 後執行：

   ```powershell
   uv sync --locked
   ```

3. 複製 `.env.example` 為 `.env`，填入 Discord token/channel；不用 Discord 可留空。
4. 準備 chill 參考與模板：

   ```powershell
   uv run python -m miningbot.convert_audio "你的chill.mp3"
   uv run python -m miningbot.fetch_trackers
   uv run python -m miningbot.calibrate
   ```

5. 啟動：雙擊 `啟動挖礦bot.bat`，或 `uv run python -m miningbot`。

## 熱鍵

- **Ctrl+Q**：只暫停並放開按鍵。
- **Q**：暫停／恢復。
- **F12**：結束程式。

## Discord 與回礦

支援 `pause`、`resume`、`status`、`shot`、`ability`、`list`、`keep`、`unkeep`、
`clear`、`回礦`／`reenter` 等命令。`reentry_mode` 可設為 `off`、`remote`、`auto`；
預設為 `remote`，`auto` 必須先完成本機 surface template 校準。

## 網頁 UI

內建網頁介面（`web_server_enabled`，預設開）。透過 Tailscale IP 連線，
沒起來自動退回 `127.0.0.1`。四個頁面：`/intervention`（即時介入）、
`/`（玩家設定）、`/history`、`/annotate`。沒人連著就自動退回 Discord
按鈕流程。詳見 [`docs/web-ui-guide.md`](docs/web-ui-guide.md)。

## 授權

僅供學習與個人使用。Roblox 自動化可能違反遊戲服務條款，後果自負。
