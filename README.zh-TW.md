[English](README.md) | **繁體中文**

# 🪦 無聊的挖礦遊戲 — Roblox REX 全自動挖礦

> **這個遊戲，把你的 Roblox 視窗綁架了。**
>
> REX 是一個純手動的挖礦遊戲。沒有自動挖礦、沒有掛機模式、沒有離線進度。
> 每一塊礦、每一下敲——都是你手指按著的。你掛著挖就不能玩別的，想去玩
> Blade Ball？不行，REX 還在挖。想去 Brookhaven 找朋友？不行，礦還沒挖完。
> 上個廁所離開一下？你不在的時間零產出——遊戲不會幫你挖。離開超過 20 分鐘？
> Roblox 直接把你踢出去。回來發現角色卡住了、boost 過期了、稀有礦跑掉了
> ——好幾個小時全部白費。
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
> 幫你採稀有礦，聽到 chill 音效自動掃描八方位，採到了還會截圖傳 Discord
> 跟你說。你甚至可以從手機網頁直接點畫面開火。
>
> 然後你就可以去玩別的遊戲了。因為 Roblox 只能開一個視窗——但誰說
> 那個視窗裡的礦，得你自己挖？
>
> 說真的，等到你已經在 REX 裡砸了好幾百個小時，這遊戲除了挖礦之外
> 已經沒什麼好玩的了。任務解完了、進度到頂了、新鮮感沒了，唯一剩下
> 的事就是對著牆壁發呆然後多擠出幾顆稀有礦。這個 bot 就是寫給那種
> 玩家的——什麼都看過了、什麼都玩過了，只想要礦、不想要那個折磨人
> 的過程。
>
> ⚠ **這個專案我已經不再維護了。** 程式碼留在這裡，給所有被 REX 綁架
> 的人。想改就用，想接手就 fork。座標是 1920×1080 全螢幕的，你自己
> 的解析度不一樣就得重校——但至少邏輯都寫好了，不用從零開始。

---

## 這是什麼

Windows 專用 Python 3.11+ 自動化程式，主要流程包含挖礦、D5 boost
維護、D4 活動刷新、chill 音訊偵測、稀有礦掃描/瞄準/採集、聊天驗證、
Discord 遙控，以及手動／遠端／實驗性自動回礦。

`miningbot/main.py` 是狀態機與 I/O 編排核心；純決策邏輯拆在
`states.py`、`harvester.py`、`miner.py`、`game_data.py` 等模組裡。

## 必備遊戲內物品（後期限定）

**這個 bot 是寫給後期玩家的。** 它自動操作的工具——D2 到 D5——不是
入門裝備，是終局物品，必須用稀有材料**合成**，而那些材料只有進度
夠深才拿得到。如果你還在前期，這個 bot 幫不了你——等你四件都合成
完了再來。

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
