# 2026-07-26 網頁 UI：人工介入操作 + 被動素材收集 + Discord 精簡通知

> **版本沿革**
> - **v1**：初次設計。把 Discord 連鎖放大／八方位那條間接表達鏈，塌縮成網頁
>   pinch-zoom + tap 一次到位；玩家介入時自動收集素材供 AI agent 離線分析；Discord
>   退回精簡通知角色（遙控器保留、狀態用 edit_message、需介入才 PING）。
> - 設計 session：本檔由 brainstorming 流程產出，逐段與使用者確認後落地。實作前必讀。
> - **v2（2026-07-27／28，實機與瀏覽器實測後的演進）**：P1-P5 落地後改了四處設計，
>   **以下述為準，v1 對應段落已就地標註**。硬規則版本見 `AGENTS.md` 規則 13／14。
>   1. **回礦介入改「先掃八方位再問網頁」**（`3d3cc41`）：傳送板幾乎不在開場視野內，
>      v1 的「推當下一幀請玩家點」讓玩家無從點起。現在 `_rr_sweep_capture` 跑**一次**、
>      同時餵網頁（推 8 張）與 Discord（發圖），web `reentry_click` 帶 `dir`(1-8) 先轉向
>      再點、轉向被吃就放棄不盲點；面板加 ⟳ 重掃／🎲 重骰／⏭️ 跳過三鍵（在等待迴圈內
>      取用，不是 `_consume_web_pending`——主迴圈那時被擋在等待裡）；獨立預算
>      `web_intervention_budget_s`(300s)／`web_intervention_retry_budget_s`(120s)，
>      用盡回 False 退 Discord。
>   2. **harvest 改推「採集候選清單」且點哪打哪**（`20479c8`／`baf74cb`）：不是只在
>      `awaiting_fine` 才介入；候選圖點下去＝走 `_execute_remote_fire` 全套（含 D2/D5
>      重掃檢查，H062），不是盲打粗格心。`awaiting_fine`／`放大`／`退` 放大退路維持
>      Discord-only（必要性下降，見 `docs/web-ui-guide.md`「已知未做」）。另加晚到
>      重播緩衝與 🔀 立即切 Discord。
>   3. **遙控器鏡射上網頁**（`20c5a93`／`d5fac93`）：▶️⏸️⚡📷🏠 五鍵＋常駐狀態＋保留
>      清單＋D2 開關都在 `/intervention` 與 `/`，與 Discord 雙向同步；§7 A 的「合併狀態
>      顯示」在網頁側＝頁頂常駐控制列，任何時候可按，不必等介入事件。
>   4. **依賴**：`uvicorn` 必須配 `websockets`（裸 uvicorn 無 WebSocket 實作 → `GET /ws`
>      回 404、fallback 恆 True），且要裝在**實際啟動 bot 的直譯器**上。見 `incidents.md` H061。

## 0. 委派注意（實作者必讀）

- **不要目視讀 PNG**；座標／尺寸量測用 `cv2.imread` 計算斷言。
- 不 commit、不切 branch、不刪 runtime 證據、不操作 Roblox/Discord（除非玩家明確要求）。
- 完成過：`uv run pytest -q`、`uv run ruff check . --no-cache`、`uv lock --check`。
- 座標／門檻／間隔只放 `miningbot/config.py`；純決策不做 I/O。
- 沿用既有測試慣例：純函式優先、I/O 邊界不交叉、不放寬偵測門檻、不刪事故回歸。
- 玩家可改的 Config 欄位**只有 §6 白名單四個**——門檻/ROI 是 AI agent 在 Claude session
  改 code 的事，**不暴露在網頁**。
- 素材根因描述屬於 `docs/incidents.md` 範疇——素材 `.json` **不存根因**，只存症狀標籤。

## 1. 背景（為什麼要這個）

目前人工介入流程（harvest 101 awaiting_fine、回礦傳送板定位）走 Discord：

1. bot 偵測失敗 → 發八方位圖
2. 玩家回方位+格（如 `B3`）
3. 該格偵測還是失敗 → 連鎖 `放大 B3` → `放大 C2` 逼近目標
4. 玩家回細格 → bot 開火 → verify

**根因**：Discord 反應只能回 emoji，**結構性做不到「玩家回傳一個 (x,y)」**。八方位→格→
連鎖放大是這個限制下的間接表達。`RepinDebouncer`、reactions 同步、刪舊貼新、seen 集合
這整套複雜度都是 Discord 元件模型的副作用。

**網頁的價值**：pinch-zoom + tap 直接收原生 (x,y)，整條間接鏈塌縮成「玩家在截圖上點一下」。
同時：

- 玩家介入時**自動收集素材**（verify 通過 = 真框確認），不需額外標註操作。
- Discord 退回精簡通知角色（被動收 NEEDS_HUMAN 推播），不再承擔操作介面。
- 玩家**只玩遊戲 + 抱怨**；門檻/ROI 調整是 AI agent 在 Claude session 改 code 的事。

## 2. 範圍邊界（保留 vs 新增）

```
            ┌─────────────────────────── 人工介入 / 資料分析 ───────────────────┐
            │   ★ 新增：網頁 UI（http://localhost:port，Tailscale Serve 出 HTTPS）│
            │                                                                  │
            │   ┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
            │   │ 即時介入面板    │  │ 歷史/標註面板    │  │ 玩家設定面板  │  │
            │   │ • awaiting_fine │  │ • harvest_id 列表│  │ • 4 個白名單  │  │
            │   │   點選截圖      │  │ • reentry attempt│  │   欄位        │  │
            │   │ • 回礦傳送板定位│  │ • 症狀標籤       │  │ • 寫回        │   │
            │   └────────┬────────┘  └────────┬─────────┘  └───────┬────────┘  │
            └────────────┼────────────────────┼───────────────────┼───────────┘
                         │  WebSocket（雙向） │  HTTP             │ HTTP POST
                         ▼                    ▼                   ▼
            ╔═══════════════════════════════════════════════════════════════╗
            ║         Bot 主程序（miningbot/main.py + 狀態機）             ║
            ║                                                              ║
            ║   ┌──────────────┐  ┌─────────────────┐  ┌──────────────┐    ║
            ║   │ WebIPC thread│  │ Discord polling │  │ 主迴圈       │    ║
            ║   │ （新）       │  │ thread（保留）  │  │ 狀態機       │    ║
            ║   │              │  │                 │  │              │    ║
            ║   │ • 事件 sink  │  │ • 挖礦遙控器    │  │ • 挖礦       │    ║
            ║   │ • pending Q  │  │ • 通知推播      │◀─│ • 採集       │    ║
            ║   │ • 座標快取   │  │   (notify.py)   │  │ • 回礦       │    ║
            ║   └──────┬───────┘  └─────────────────┘  └──────────────┘    ║
            ╚══════════╪═══════════════════════════════════════════════════╝
                       ▼
                   Roblox + Windows（pydirectinput 注射輸入）
```

### Discord 保留 vs 網頁接手

| 流程 | Discord | 網頁 |
|---|---|---|
| 挖礦中遙控器（暫停、轉、採樣開關、status、校準卡） | ✅ 主用 | 不接手 |
| 採集/回礦事件通知 + 推播手機 | ✅ 保留 | 網頁也顯示，但推播用 Discord |
| **harvest 101 awaiting_fine 手動瞄準** | fallback 才用 | ✅ 點選截圖 |
| **回礦傳送板定位** | fallback 才用 | ✅ 點選截圖 |
| **看歷史紀錄 + 標註素材** | ❌ | ✅ 唯一介面 |
| **改玩家設定（4 個白名單欄位）** | ❌ | ✅ 唯一介面 |

### 部署模型（Tailscale）

- Bot 主機（Windows）：`miningbot/main.py` 跑 bot + 內嵌 web server，**綁 `127.0.0.1:port`**。
- `tailscale serve https://<machine>.<tailnet>.ts.net → http://localhost:port` 出 HTTPS。
- **不需要 Tailscale 之上再加 token 認證**——tailnet 自己用，設備授權已足夠。
- 不動 Windows 防火牆（Tailscale 走自己介面）。
- **網頁伺服器跟 bot 同 process**（不另開 process），daemon thread。理由：bot 狀態機記憶體共享，
  跨 process 會逼出 IPC 地獄；既有 Discord polling thread 已驗證 thread 模式可行。

## 3. 三條資料流（架構最關鍵的決定）

**1. 事件流（bot → web）**：沿用既有 `EventLog` + sink 模式，新增 `WebEventSink` 廣播給所有
連線中的 WebSocket client。跟 `DiscordSink` **並存**——同一份事件來源，兩個 sink 各自消化。

**2. 命令流（web → bot）**：網頁 server 收到玩家動作 → 丟進 `web_pending` queue → bot 主迴圈
在 safe point（狀態切換之間）取出消費。沿用既有 Discord polling thread 的 `pending` queue
模式。**不在 web thread 內直接呼叫 bot method**——避免 race。

**3. 截圖流（bot → web，按需）**：網頁要點選時，bot 抓當下 frame → encode PNG → WebSocket
binary 推給 client → 玩家點 → 座標回傳。座標系：**遊戲原生解析度**（1920×1080），client 端
用 CSS scale 顯示，點擊座標 server 端還原。**不流經 Discord multipart 那套**（直接 WebSocket binary）。

## 4. 即時介入面板

### 點選 UI（pinch-zoom + tap，一次到位）

```
bot 發 1920×1080 全畫面截圖
      ↓
玩家在 canvas 上 pinch/scroll 縮放、拖曳平移
      ↓
tap 點選 → client 算原生座標 → server → bot 點擊
      ↓
bot 走既有 verify / 漂移守門 / plan_click_verdict
```

不放反應按鈕、不走八方位→格→連鎖放大。pinch-zoom 在手機/平板是原生手勢，桌機用滾輪也直覺。

### 兩條流程

⚠ **以下兩條流程是 v1 版本，實作已演進**（見開頭 v2 第 1、2 點）：harvest 改成推
候選清單、點哪打哪；回礦改成先掃八方位再問網頁。保留原文供對照設計意圖。

**harvest 101 awaiting_fine**（v1）：
1. bot 進 NEEDS_HUMAN（manual_survey 觸發）
2. WebSocket push：事件 + 全畫面截圖 +「harvest 101 手動瞄準」context
3. 網頁面板跳出 toast + 自動展開截圖
4. 玩家 pinch-zoom 找到追蹤框 → tap 框中心
5. 座標送 bot → **跳過偵測**（玩家已給精確座標），直接走既有「漂移守門 → fire (x,y) → verify」尾段
6. verify 結果 → 事件流回網頁（綠色 ✅ 或 紅色重試）

**回礦傳送板定位**（v1；現況見 v2 第 1 點）：
1. bot 開場鏈跑完，準備點傳送板
2. WebSocket push：事件 + 全畫面截圖 +「回礦：點傳送板」context
3. 玩家 pinch-zoom 找到傳送板 → tap 板中心
4. 座標送 bot → 走既有 `_rr_click` 的「漂移守門 → 點擊 → plan_click_verdict」
5. 三態結果（成功/等確認/無反應）→ 事件流回網頁
6. 失敗時玩家可重新點；可選「跳過」按鈕走 bot 既有跳過路徑

### 與既有邏輯的接合

- **不刪既有 Discord 反應按鈕邏輯**——它保留為**網頁掛掉時的 fallback**。
- **新增「web pending」queue 跟 Discord 的 polling 並存**。Bot 主迴圈先檢查 web queue
  （點擊座標），沒有再檢查 Discord 命令。
- **既有 `AimContext` / `reentry_remote.Context` 不變**——網頁只是「另一個產生 reply 的來源」。
- 漂移守門（FOV state0/state1）、`plan_click_verdict` 三態、verify 路徑**完全不動**——網頁
  送進來的座標跟 Discord 連鎖放大送進來的最終細格座標，走同一條後處理。

### Fallback 觸發規則

判斷「網頁有沒有人在線」= WebSocket 是否有任何 client 連著。

- 有人連著 → 走網頁路徑：bot 不發八方位圖、不發連鎖放大圖；Discord 只推狀態變動與關鍵事件。
- 沒人連著 → 走 fallback：恢復現況 Discord 行為（八方位圖、反應按鈕、zoom_stack）。
- bot 進 NEEDS_HUMAN / awaiting_fine / 點傳送板 時，主迴圈檢查 `web online clients > 0` 決定走哪邊。
- 兩邊都沒人 → 等到有人介入（Web 連線 / Discord reaction 任一）。
- 已經有 reply 進來 → 另一邊 timeout 自動放棄（先到先贏，§8 詳述）。

## 5. 歷史紀錄與標註面板

### 三層資料模型

```
[Episode 層]      每次採集 / 回礦 attempt 一筆
  episode_id      hid + 種類（harvest / reentry）
  結果             ✅ 成功 / ❌ 失敗 / ⚠️ 未確認 / 🤝 人工
  時間             起 / 迄
  關鍵座標         命中位置、點擊位置、開火位置
  事件流           縮時列表（chill 偵測 → survey → fire → verify → ...）

  [Snapshot 層]   該 episode 內所有 snapshot_index.jsonl 的快照
    label          needs_human_*, aim_cell_*, aim_core_miss_*, spawn_chill, ...
    PNG 路徑       logs/snapshots/<file>
    時間戳

  [標註層]        對單張快照的「真值」描述（手動或自動產出）
    框 / 點        正方形 (cx, cy, size)
    tier + 變體    Mythic / Spectral / Ionized（從 game_data 撈）
    症狀           漏判 FN / 誤判 FP / 該拒沒拒 / 不確定
    匯出目標        tests/fixtures/<category>/<name>.png
```

### UI 三區塊

**A. 列表 + 篩選**：按 harvest/reentry、結果、日期、關鍵字篩選。

**B. 詳細頁**：事件時間軸 + 該 episode 所有快照縮圖（按 label 分組）+ 玩家介入歷程。

**C. 標註工具**：
- 顯示原圖（pinch-zoom 友善）
- **正方形標註**：點中心 + 拖曳出 1:1 比例方形（限制比例）
- **Rarity 快選 toolbar**（從 `game_data.py` 的 `tier` 動態生成）+ 變體（Spectral / Ionized 可疊加）
- **症狀標籤**：[ 漏判 FN ] [ 誤判 FP ] [ 該拒沒拒 ] [ 不確定 ]（單選，預設「不確定」）
- `related_incident`（可選）：玩家覺得跟某 H 事故像才填，否則 null

### 素材格式（每張 2 檔）

**`<name>.png`** — 裁好的 crop（檢測函式輸入格式）

**`<name>.json`** — 結構化 metadata：
```json
{
  "image": "auto_007_terrain_fp.png",
  "category": "aim/terrain_false_positive",
  "annotation": {"type": "square", "cx": 211, "cy": 189, "size": 50},
  "tier": null,
  "variant": null,
  "mineral": null,
  "source": {
    "kind": "auto",
    "harvest_id": "007",
    "episode_result": "fail",
    "verify": "failed",
    "timestamp": "2026-07-26T14:23:00+08:00"
  },
  "symptom": "false_positive",
  "related_incident": null
}
```

**重要原則**：
- 玩家只給**症狀**（漏判/誤判），不給**根因**——根因是 AI agent 後續分析的事，沿用既有
  `tuning-from-incidents` skill + `docs/incidents.md` 流程。
- 沒問題的素材（confirmed true positive）`symptom` 留 `null`，當對照組。
- 不寫 `.md` 描述檔——根因描述屬於 `docs/incidents.md`，素材只是「證據」。

### 自動收集（標註 = 介入的副產品）

```
玩家在 harvest 101 點擊 (851, 189)
  ↓ bot 開火 → verify 通過 → 採集成功
  ↓
自動寫入：
  tests/fixtures/aim/auto_<hid>_success.png     ← 該格 crop
  tests/fixtures/aim/auto_<hid>_success.json    ← {cx, cy, size, tier, source: "auto", symptom: null}
```

- 玩家**不需額外操作**——正常介入就產出標註
- verify 通過 = 真框確認（高信心素材）
- verify 失敗 = 玩家可事後在 §5 手動分類（`symptom` 標籤）

### 素材庫結構

```
tests/fixtures/                              ← 既有，已 gitignore
├── README.md                                # 頂層索引：分類規則、命名規則、給 AI 的話
├── aim/
│   ├── README.md
│   ├── green/                               # 按色系分（detect_tracker_core 用）
│   ├── terrain_false_positive/              # 負樣本
│   └── ...
├── reentry/
│   └── teleport_board/
└── negative/                                # 通用 UI / 地形負樣本
```

每個子目錄有 README.md 解釋該類別（AI agent 友善索引）。

### 修正後的分工

| 工作 | 誰做 | 在哪做 |
|---|---|---|
| 標註座標 + rarity + 症狀 | 玩家 | 網頁 |
| 自動收集（玩家介入的副產品） | 系統 | 網頁 |
| 維護素材庫 README 索引 | 網頁（自動更新） | — |
| 找共通點 + 分析根因 | **AI agent** | CLI / Claude session |
| 寫根因描述 | **AI agent** | `docs/incidents.md` |
| 跑 pytest + 調門檻 | **AI agent** | CLI |

## 6. 玩家設定面板（不是 Config 編輯器）

### 角色定位

```
玩家做的事                       AI agent 做的事
─────────────                    ─────────────
玩遊戲                            讀素材 + 症狀
抱怨「這裡有問題」（給症狀）       找根因
在網頁介入（點選截圖）             調門檻 / ROI / 寫測試
                                ↑
                       全在 CLI / Claude session 改 code
```

**玩家在網頁改的只有「遊戲 play style 選擇」**——不是演算法參數。

### 可改欄位（白名單，就這四個）

| 欄位 | 型別 | 為什麼玩家會改 |
|---|---|---|
| `reentry_mode` | dropdown (off/remote/auto) | 遊戲進度切換 |
| `reentry_target_layer` | dropdown（從 game_data 撈層名） | 換挖的層 |
| `reentry_yaw_sample_sweep` | toggle | 收語料的場次才開 |
| `sweep_pitch_enabled` | toggle | 校準好才開 |

**門檻、ROI、偵測參數完全不暴露**——AI agent 改 code，不在網頁。

### 持久化

玩家可改的東西少 + 都是「下次也想這樣」的設定，直接寫 `logs/config_overrides.json`（沒有
「未持久化」中間態）：

```
玩家改 reentry_mode: remote → auto
  ↓
立即 runtime 生效 + 寫入 logs/config_overrides.json
  ↓
Bot 重啟時讀回
```

Bot 啟動套用順序：dataclass default → .env 覆蓋 → `config_overrides.json` 覆蓋（最高優先）。

**不動 config.py**（程式碼，事故根因記錄）。**不動 .env**（機密）。

不需要 diff 預覽、二次確認、備份——玩家能改的東西不會讓 bot 壞掉。

### 白名單協議

```python
WEB_CONFIGURABLE_FIELDS = frozenset({
    "reentry_mode", "reentry_target_layer",
    "reentry_yaw_sample_sweep", "sweep_pitch_enabled",
})
```

白名單外的欄位 → WebIPC 直接拒絕 + 回 `{"type": "error", "reason": "field not web-configurable"}`。

## 7. Discord 訊息角色（精簡）

Discord 頻道兩種訊息角色：

### A. 遙控器卡（合併狀態顯示，1 則常駐）

跟現在的遙控器卡一樣的位置、一樣的反應按鈕、一樣的釘底（`RepinDebouncer` 保留）。**新增
混合更新策略**：

| 內容類型 | 觸發時機 | 機制 |
|---|---|---|
| **重要：狀態 transition**（MINING→HARVESTING→NEEDS_HUMAN 等） | 狀態值變動的瞬間 | **立刻 `edit_message`** |
| **重要：關鍵動作**（命中座標、verify 結果、進入 awaiting_fine） | 動作字串變動 | **立刻 `edit_message`** |
| 不重要（運行時間、音訊分數、容量微變） | 不主動觸發 | **靠 repin 重發時順帶刷新** |

降頻上限：`edit_message` 最快每 `discord_status_edit_min_interval_s` 秒一次（預設 3.0，避免
狀態機快速擺盪洗版）。

### B. 需介入訊息（PING + 結案編輯）

```
[觸發]   <@373438562940747776> ⚠️ [007] 需要人工：稀有礦未自動命中
         [fallback 模式：附八方位圖 + 反應按鈕（玩家在 Discord 操作）]
         [非 fallback 模式：純文字，提示「在網頁處理」]

[結案]   ✅ [007] 已在網頁處理（玩家點擊 (851,189)，verify 通過）
```

同一則訊息編輯，頻道看起來是「⚠️ PING → ✅ 結案」一則。

`PING_USER_ID = "373438562940747776"` 寫死在 `notify.py`（個人 bot，不做 Config 欄位）。

### C. 關鍵事件（純文字、不發圖、不 PING）

例：`✅ [007] 採集成功 Mythic Tin` / `🔄 重置中` / `⛏️ 開始回礦（attempt 2）`

不編輯、不 PING；玩家看到是錦上添花，沒看到也沒事。

### 砍掉的東西

| 移除 | 原因 |
|---|---|
| 八方位 8 張圖 | 網頁 pinch-zoom 點選取代（fallback 才發） |
| 連鎖放大逐層圖 | 同上 |
| 採集放棄多圖分組（聊天/背包/追蹤框 4-6 張） | 簡化為一張全畫面；細節在網頁歷史紀錄看 |
| `discord_commands.py` 文字命令 | **保留**——出門沒網頁時的備援 |

### `.env` 變動（玩家自行改）

```
DISCORD_CHANNEL_ID=1530630370234732654   # 新伺服器頻道（從私訊搬過來，享用編輯訊息等功能）
```

## 8. IPC 協議與 bot 整合

### 拓撲

```
                  WebSocket（單一 port，雙向）
                  │
                  ▼
   ┌─ WebIPC thread（新；daemon thread）─────────────────┐
   │  • 接受多 client 連線（追蹤 count = fallback 開關） │
   │  • 收 client 命令 → push web_pending queue          │
   │  • 接 EventLog 事件 → 廣播給所有連線 client         │
   │  • 按需抓 frame → encode PNG → push binary          │
   └─────────────────────┬──────────────────────────────┘
                         │
            ┌────────────┴───────────┐
            │                        │
       web_pending           WebEventSink
       (Queue)              (EventLog sink)
            │                        ▲
            ▼                        │
   ┌─ Bot 主迴圈 safe point ─────────┴────────────────┐
   │  每 tick 之間：                                   │
   │    1. 檢查 web_pending → 有就消費                │
   │    2. 檢查 discord_pending → 有就消費            │
   │    3. 沒命令就繼續狀態機                         │
   └───────────────────────────────────────────────────┘
```

WebIPC thread 跟既有 Discord polling thread **平行**——兩者都是「外部輸入 → pending queue
→ 主迴圈 safe point 消費」。沒有共享 mutable state，沒有 cross-thread method call。

### 三條資料流的協議

**1. 事件流（bot → web，WebSocket text frame）**
```json
{
  "type": "event",
  "event": "NEEDS_HUMAN",
  "harvest_id": "007",
  "flow": "harvest",
  "ts": "2026-07-26T14:23:00+08:00",
  "meta": { "reason": "...", "image_pending": true }
}
```

**2. 截圖流（bot → web，WebSocket binary frame）**
- 事件帶 `image_pending: true` → bot 接著 push binary PNG
- 或 web client 主動 request：`{"type": "request_frame"}` → bot 抓當下 frame 回傳
- 1920×1080 PNG 約 1-2MB，WebSocket 直接傳 OK（不切片）

**3. 命令流（web → bot，WebSocket text frame）**
```json
{
  "type": "command",
  "cmd": "fire_at",
  "flow": "harvest",
  "harvest_id": "007",
  "payload": { "x": 851, "y": 189 }
}
```

命令種類：`fire_at`（點擊開火）/ `reentry_click`（點傳送板）/ `config_set`（限 §6 白名單）/
`pause` / `resume` / `request_frame` / ...

### Race 規則：先到先贏，後到丟棄 + 通知

每個 reply 用 `flow + episode_id` 當 routing key（例如 `harvest:007` 或 `reentry:attempt_3`）：

```
Bot 等玩家介入（特定 flow + episode_id）
  ↓
第一個 reply 進來（web 或 discord 任一）→ 鎖定該 reply，處理
  ↓
其他 reply（同 routing key）進來 → 已過期，丟棄 + log「late reply ignored」
  ↓
處理結果 → 事件流推給所有 client（讓另一邊知道「已被處理」）
```

特殊情況：

| 場景 | 處理 |
|---|---|
| Web 點擊 + Discord 反應同時到 | queue FIFO，第一個贏 |
| 玩家 web 連點多次（手滑） | 第一個處理；其餘 debounced 或 routing key 已過期 |
| Web 連線中斷（玩家關分頁） | pending reply 保留 N 秒，client 重連可恢復；過期就走 fallback |
| Web 命令在 bot 不期待的狀態下到 | WebIPC 拒絕 + 回 `{"type": "error", "reason": "bot not awaiting for flow:X"}` |
| Config 改動 race | runtime 改 instance 是 atomic（單一指派）；玩家可改的只有 §6 白名單四個無危險欄位，race 也無致命影響 |

### Fallback 切換規則

WebIPC thread 追蹤 `connected_clients`：
- `0 → ≥1`：bot 進入 NEEDS_HUMAN / awaiting_fine 時走 web 路徑（不發八方位圖）
- `≥1 → 0`：30 秒 grace period（防玩家分頁重新整理）；過後走 fallback

### Bot 端整合（最小侵入）

新增：
- `miningbot/web_server.py`：WebIPC thread + WebSocket server
- `miningbot/web_ipc.py`：純函式（命令解析、race routing key 計算）+ WebEventSink
- `miningbot/web_config.py`：玩家可改欄位白名單 + 持久化
- `miningbot/web_annotation.py`：標註工具純函式（症狀標籤、JSON 結構）
- `tests/test_web_ipc.py`、`tests/test_web_config.py`、`tests/test_web_annotation.py`

修改：
- `main.py` 啟動 WebIPC thread（比照 Discord polling thread 的啟動位置）
- `main.py` 主迴圈 safe point 加 `web_pending` 消費
- `main.py` `EventLog.add_sink(WebEventSink(...))`（跟 DiscordSink 並列）
- `notify.py` 加 `PING_USER_ID` 常數、`should_edit_for_state`、`EditThrottle`
- `config.py` 加新欄位（§11）

**不動**：
- `discord_commands.py`（fallback 仍用）
- `notify.py` 的 Discord sink（並存）
- `reentry_remote.py` / `remote_aim.py` 的純函式（web reply 走同一條解析路徑）

### Framework 選擇

**FastAPI + uvicorn**：
- WebSocket + HTTP 一條龍
- pydantic 型別檢查適合 IPC 協議
- async 適合事件流
- 主流、文件完整、PyPI 月下載極高

新增依賴：`fastapi`、`uvicorn`。要過 `uv lock --check` 跟既有「依賴替代方案調查」原則。

## 9. 測試策略

### 測試分層

| 層級 | 對象 | 工具 | 重點 |
|---|---|---|---|
| **L1 純函式** | `web_ipc.py`、`web_protocol.py`、`web_config.py`、`web_annotation.py` | pytest | 命令解析、race routing key、白名單、座標還原、症狀標籤 |
| **L2 整合（fake bot）** | WebIPC thread + mock bot | pytest + `monkeypatch` | queue 消費、事件 sink 廣播、fallback 切換 |
| **L3 端到端（headless browser，可選）** | 網頁 UI + bot | pytest + playwright | 點擊→fire→verify 完整 flow |
| **L4 實機驗收** | 真實 bot + Roblox | 掛機跑 + 看 log | harvest + reentry 各一場 |

L3 可選——如果 playwright 太重，L2 用 mocked WebSocket client 模擬也行。

### L1 純函式測試重點

- **Race routing key**：`harvest:007` vs `harvest:008` 不匹配；同 key 第二個 reply一棄
- **座標還原**：canvas CSS 顯示 960×540（縮小 2x），玩家點 (480, 270) → 原生 (960, 540)；
  pinch-zoom 平移後座標仍要正確還原
- **Config 白名單**：`reentry_mode` 通過、`tracker_core_min_area` / `reentry_game_region` 拒絕；
  值型別驗證（`reentry_mode` 只接 off/remote/auto）
- **素材標註 JSON schema**：`symptom` 只接四值；不存 `problem` 欄位（根因不在素材）
- **症狀標籤正規化**：`漏判` → `false_negative`、`誤判` → `false_positive`
- **Discord 編輯觸發規則**：狀態 transition 觸發 edit；同狀態不觸發；3 秒 throttle

### L2 整合測試重點

- WebIPC 在 safe point 消費 web_pending
- Fallback 切換（0 client → ≥1 → 0 + grace expire）
- Web + Discord reply 先到先贏
- 事件 sink 並存（Discord + Web 各收到一份）

### L4 實機驗收

**驗收 A：harvest 101 完整介入**
- 掛機跑一場，等 NEEDS_HUMAN 觸發
- 從平板/手機開網頁（驗 Tailscale Serve 通）
- pinch-zoom 找框 → tap 點中心
- bot 接到座標 → 開火 → verify
- **驗收點**：
  - [ ] 網頁 toast 即時彈出（< 1s 延遲）
  - [ ] 截圖 WebSocket 傳輸完整（無破圖）
  - [ ] 座標還原正確（點哪打哪）
  - [ ] verify 結果回傳網頁顯示（✅ 或 ❌）
  - [ ] Discord 同時收到狀態編輯（不是新訊息）
  - [ ] 自動收集素材到 `tests/fixtures/aim/auto_*` 含 `.json`

**驗收 B：回礦傳送板定位**
- 觸發 reentry 流程
- 網頁點傳送板中心
- bot 走 `_rr_click` → `plan_click_verdict` 三態
- **驗收點**：
  - [ ] 點擊座標正確
  - [ ] `plan_click_verdict` 結果透過事件流回網頁
  - [ ] 失敗時玩家可在網頁重選

**驗收 C：Discord 新角色**
- bot 啟動 → 狀態訊息 post + edit 測試
- **驗收點**：
  - [ ] 狀態訊息用 `edit_message` 更新（不是刪舊貼新）
  - [ ] NEEDS_HUMAN 觸發 PING `<@373438562940747776>`
  - [ ] 結案編輯把 ⚠️ 改成 ✅（同一則）
  - [ ] 遙控器卡釘底（`RepinDebouncer`）仍正常

**驗收 D：Fallback 切換**
- bot 啟動 + 無網頁連線 → 走 fallback（八方位圖 + 反應按鈕）
- 開網頁連線 → bot 不再發八方位圖
- 關網頁 → 30s grace 後切回 fallback
- **驗收點**：
  - [ ] 無 web 連線時 fallback 完整功能
  - [ ] 有 web 連線時不洗 Discord 頻道
  - [ ] Grace period 內不切回 fallback（防 reload 抖動）

## 10. 風險與守門

| 風險 | 對策 |
|---|---|
| 動到既有 Discord 反應按鈕邏輯（fallback） | 測試要先驗證 fallback 路徑沒退化 |
| 點擊座標 race（bot 狀態切換中收到 reply） | routing key 比對 + safe point 消費 |
| 截圖 PNG 過大塞爆 WebSocket | 量測後決定要不要切片；預估 1-2MB OK |
| Config overrides 跟 .env / config.py 順序錯亂 | 啟動時 audit log 印出「最終採用值」+ 來源 |
| Tailscale Serve 斷線 | 網頁本身仍可本機 127.0.0.1 連——Tailscale 斷只影響跨裝置 |
| 玩家手機網頁重新整理導致 fallback 抖動 | 30s grace period |
| 無視覺 AI agent 驗收偵測誤判 | 沿用 `feedback_verify_vision_blind_agent_thresholds`：撈實機素材、掃所有格所有幀、肉眼看每個命中 |

### 不變的硬規則（沿用既有）

- 不放寬偵測門檻
- 不刪事故回歸測試（H001~H060）
- 純函式優先、I/O 邊界不交叉
- 實機驗收 = log 確認，不是測試綠
- 任何視覺路徑改動要撈實機素材兩側夾

## 11. Config 變動

新增欄位（`miningbot/config.py`）：

```python
# 網頁 UI（2026-07-26 spec）
web_server_enabled: bool = True              # 啟用網頁伺服器（綁 127.0.0.1）
web_server_port: int = 8765                  # 網頁 port（Tailscale Serve 出 HTTPS）
web_fallback_grace_s: float = 30.0           # WebSocket 0 client 後等多久才切 fallback

# Discord 訊息角色精簡（2026-07-26 spec）
discord_status_edit_min_interval_s: float = 3.0  # 狀態訊息 edit_message 降頻（秒）
```

`PING_USER_ID` 寫死在 `notify.py`（個人 bot，不做 Config 欄位）。

`discord_channel_id` 從 `.env` 讀，玩家自行改成 `1530630370234732654`。

## 12. 非目標（這次不做）

- 不修 D5 / 掃描主路徑
- 不動 `_execute_remote_fire` / `_rr_click` 內部邏輯（web reply 走同一條後處理）
- 不刪既有 Discord 反應按鈕邏輯（fallback 保留）
- 不暴露門檻 / ROI / 偵測參數給玩家（AI agent 改 code）
- 不在網頁跑 pytest / 調門檻（CLI 工作）
- 不在素材 `.json` 存根因描述（屬 `docs/incidents.md`）

## 13. 教學文件

完成後寫一份 `docs/web-ui-guide.md`：
- 如何 `tailscale serve` 設定
- 網頁 vs Discord 各自適用場景
- 玩家不用學：介入、標註都靠直覺（pinch-zoom + tap）
- AI agent 怎麼讀素材庫（README.md 索引、.json schema）
