# 網頁 UI 使用指南

給**操作者**（用手機介入的人）與**接手的 AI agent** 各一半。設計理由與硬規則在
`docs/superpowers/specs/2026-07-26-web-ui-design.md`；這份只講怎麼用、怎麼設定、
壞掉時看哪裡。

## 這東西解決什麼問題

bot 遇到「稀有礦掃到了但自動瞄不準」或「回礦要點傳送板」時需要人介入。以前只能在
Discord 用連鎖放大：bot 發八方位圖 → 你回 `3 C2` → bot 發那格放大圖 → 你回 `B3` →
再放大…… 一次介入來回四五則訊息，而且你是在**用文字描述位置**。

網頁改成直接看畫面、雙指放大、點下去。座標直達 bot。

Discord **沒有被取代**——見下面的分工表。

## 分工

| 事情 | Discord | 網頁 |
|---|---|---|
| 遙控器（暫停／繼續／能力／即時畫面／手動回礦） | ✅ 主用 | ✅ 同步（2026-07-28）——`/intervention` 頁頂常駐控制列，任何時候都能按，不必等介入事件 |
| 常駐狀態（狀態／運行時間／音訊／統計／D2 開關） | ✅ 遙控器 embed | ✅ 同步——`/intervention` 頁的狀態列，`(paused, state)` 一變就推播 |
| 保留清單（keep/unkeep/clear） | ✅ 唯一 | ❌ 用量太低不值得放網頁（2026-07-28 移除）——選定事件後幾乎不再改，改用 Discord 文字指令 |
| D2 連續使用開關 | ✅ 主用 | ✅ 同步（2026-07-28）——設定頁 `/` 新增區塊 |
| 校準（俯仰） | ✅ 唯一 | ❌ 刻意不做——精細連續微調＋即時視覺回饋，Discord 反應鈕比另建網頁 UI 划算 |
| 手動轉 45°／回礦中 `層`/`遠|近`/`仰角`/`放大`/`退` 等文字指令 | ✅ 主用 | 未覆蓋——這些是「看畫面即時微調」，Discord 文字反應快 |
| 採集／回礦事件通知、手機推播 | ✅ 保留 | 也顯示，但推播靠 Discord |
| 需要人工時的 PING | ✅ 唯一 | — |
| **手動瞄準（harvest awaiting_fine）** | 網頁沒人時才用 | ✅ 主用 |
| **回礦點傳送板** | 網頁沒人時才用 | ✅ 主用 |
| **看歷史紀錄、標註素材** | ❌ | ✅ 唯一 |
| **改玩家設定（4 個欄位＋D2 開關）** | 部分（D2 開關可用文字指令） | ✅ 主用 |

「網頁沒人時」= WebSocket 一個 client 都沒連著，且已過 `web_fallback_grace_s`
（預設 30s）。grace 是為了讓你手機切背景／重新整理時不會立刻掉回 Discord。

## 設定（一次性）

網頁伺服器跟 bot **同一個 process**（daemon thread）。

預設**直接綁這台機器的 Tailscale IP**，手機在同一個 tailnet 開
`http://100.110.130.17:8765` 就進得去，不必再跑 `tailscale serve`。

相關設定（`miningbot/config.py`）：

| 欄位 | 預設 | 意思 |
|---|---|---|
| `web_server_enabled` | `True` | 關掉的話整個網頁子系統不啟動，所有流程自動退回 Discord |
| `web_server_host` | `100.110.130.17` | 綁定位址＝本機 Tailscale IP |
| `web_server_port` | `8765` | port |
| `web_fallback_grace_s` | `30.0` | 最後一個 client 斷線後，等多久才判定「網頁沒人」 |

啟動成功時 `miningbot.log` 有一行 `WebIPC server 啟動：http://100.110.130.17:8765`，
Discord 啟動訊息也會帶同一個網址。

**Tailscale 沒開機自啟怎麼辦**：那個 IP 不存在 → bind 失敗 → bot 自動退回
`127.0.0.1` 重試，log 與 Discord 都會明說「綁不到 …，手機連不進來」。等 Tailscale
起來後重啟 bot 即可，網頁 UI 不會整個消失。

**為什麼不綁 `0.0.0.0`**：介入面板**沒有任何認證**，能直接驅動遊戲。綁 `0.0.0.0`
等於把它開給所在區網（咖啡廳 Wi-Fi 也算）。綁在 Tailscale 那張網卡，tailnet 的裝置
授權就是唯一的門，這是刻意的取捨。

想改回 spec 原設計（綁 `127.0.0.1` + Tailscale 代理出 HTTPS）也可以：

```powershell
tailscale serve https / http://localhost:8765
tailscale serve status
```

## 四個頁面

頁面頂端有導覽列（設定／介入／歷史）互相跳，不必記網址。

| 路徑 | 做什麼 |
|---|---|
| `/intervention` | **介入面板**——回礦時收到八方位整組截圖，左右切方位、雙指放大後直接點傳送板；另有 ⟳重掃／🎲重骰／⏭️跳過 |
| `/` | 玩家設定（4 個欄位） |
| `/history` | 歷史紀錄：episode 列表（編號帶類型前綴 `採#114`／`回#26`），依類型／結果／**日期**／關鍵字篩選 |
| `/episode?id=<key>` | **episode 詳細頁**：事件時間軸 + 快照縮圖（按標註優先序分組）+ 標註歷程。`key` 是 `harvest:114`／`reentry:26`；裸編號的舊網址仍相容 |
| `/annotate?episode=<id>&snapshot=<path>` | 標註工具：拖方形、填礦名／稀有度／症狀 |
| `/snapshot?path=<abs path>` | 把快照 PNG 送給瀏覽器（縮圖與標註頁的圖都靠它） |
| `/health` | 給人確認 server 活著（不是給玩家看的） |

一般流程是 `/history` → 點 episode → 詳細頁看時間軸與縮圖 → 點縮圖進標註。

### 介入面板怎麼用

**頁頂常駐控制列（2026-07-28）**：▶️繼續／⏸️暫停／⚡能力／📷即時畫面／🏠手動回礦，
跟 Discord 遙控器同一組，任何時候都能按，不必等 bot 發介入事件。📷 即時畫面只是
「看一眼現在畫面」，看到的圖**點下去沒作用**（不會誤送開火/點擊，跟候選圖分開處理）。
狀態列（頁頂控制列下方那條）常駐顯示狀態／運行時間／音訊／統計／D2 開關現況，
狀態一變就自動更新；剛連上時面板會自己要一次現況，不必重新整理。

**回礦（八方位模式）**

1. bot 需要你的時候有三個提醒：Discord 發一則帶網址的「網頁在等你點」、
   瀏覽器**分頁標題閃紅點**、還有一聲提示音。你不必一直開著面板盯著。
2. bot 已經先轉一圈拍好**八個方位**才問你——傳送板九成不在開場視野內，
   所以面板給的是完整一圈，不是單一張。
3. 用 `◀ ▶`（或鍵盤左右鍵）切方位，上方圓點顯示總共幾張、看到第幾張。
   找到有傳送板的那一張，雙指放大後**直接點它**。
4. 點下去 bot 會**先轉到那個方位**再點該像素——所以務必在你正在看的那張圖上點。
5. **綠圈＝bot 猜的傳送板位置**（2026-07-28）。圈上方有分數，覺得對就按
   `🎯 採用建議`一鍵送出圈心，不必自己點準；覺得不對就照舊直接點你要的位置
   （那等於否定了預測，bot 會把「預測 vs 你實際點的」一起記進語料）。
   偵測不到或分數太低就不會有圈、也不會有那顆按鈕，操作與以前完全一樣。
   bot **永遠只建議、不自動點**——要不要下去仍然是你按的。
6. 另外三顆按鈕（等同 Discord 文字指令）：
   - `⟳ 重掃`：原地重拍一圈（旋轉被吃、方位標籤對不上時用）
   - `🎲 重骰`：換一個重生點重來
   - `⏭️ 跳過`：放棄回礦，回正常挖礦
7. 沒下去就自動重掃一圈讓你再挑一次，最多 3 次；3 次都不成會退回 Discord 八方位，
   兩邊都還能操作。

**採集（單幀模式）**

畫面出現當下的遊戲截圖，**點在礦物追蹤框的中心**即可。沒成功要回 Discord 用
`重骰` / `跳過`。

共通：拖曳畫面不會被當成點擊（移動超過 5px 就算拖曳）。

⚠ 等待預算：回礦首輪 `web_intervention_budget_s`（預設 15 分鐘），retry 輪
`web_intervention_retry_budget_s`（2 分鐘）；採集仍用 `remote_aim_budget_s`。
逾時就退回 Discord——逾時代表「人不在」，不是「人來不及」。
礦坑如果在你猶豫時開始重置，bot 會拒絕這次點擊並告訴你——那不是 bug，是防止對著
過期畫面開一發 D3。

### 玩家設定：4 個 Config 欄位 + D2 開關

`reentry_mode`（off／remote／auto）、`reentry_target_layer`、`reentry_yaw_sample_sweep`、
`sweep_pitch_enabled`。每個欄位在頁面上都有白話說明（做什麼用、代價是什麼）。

**D2 連續使用開關**（2026-07-28）：`_radar_toggle` 不是 Config 欄位（是 Bot
執行期可變狀態），走獨立的 `/api/radar`（HTTP POST，異步排進主迴圈執行，跟
Discord `掃描`/`削洞` 共用同一份持久化檔案）而不是 `/api/config`。頁面載入時
`GET /api/player` 撈 D2 開關現值；勾選框失敗會自動復原（不留假象）。

保留清單（keep/unkeep/clear）曾短暫上過網頁（同日又撤下）——選定事件後幾乎不再
變動，長駐一個網頁區塊不划算，改回 Discord 文字指令唯一入口。

`sweep_pitch_enabled` 勾了就會動（2026-07-28 起）：`sweep_pitch_step_px` 已填校準值
（一層約 45°，實際數字與推導寫在 `config.py` 該欄位旁，別在這裡複製），設定頁的狀態條
顯示「✅ 已校準」並印出現值。代價是每次八方位撲空多花約 90-100 秒多掃上下兩層，
任一層拖曳被吃重試再 +15 秒。這個值**尚未實機驗證**——若快照顯示上層視野抬得太多/
太少或方向相反，只改 `sweep_pitch_step_px` 的大小或正負，不動任何程式邏輯；換世界重校同理。
改回 `0`（或 `sweep_pitch_center_back_px<=0`）時 `harvester.plan_pitch_layers` 回空 list、
整個功能靜默停用，設定頁退回警示條。

**偵測門檻、ROI、座標一律不開放**——那些要看實機素材兩側夾才能動，屬於 AI agent 的
CLI 工作（spec §12）。想改的話跟 agent 說，不是在網頁找。

改完即時生效，並寫進 `<log_dir>/config_overrides.json`，下次啟動自動讀回。優先序是
Config default → `.env` → `config_overrides.json`（最高）。

### 標註是介入的副產品

你每次在網頁點一次，bot 就把那格裁圖存進 `tests/fixtures/aim/auto_<id>_{success,fail}.png`
加一份 `.json`。你在 `/annotate` 補礦名、稀有度、症狀就好；**根因描述不要寫在這裡**，
那是 agent 寫進 `docs/incidents.md` 的事。

素材庫的分類規則見 [`tests/fixtures/README.md`](../tests/fixtures/README.md)。

## 壞掉時看哪裡

| 症狀 | 先查 |
|---|---|
| 手機連不上 | `miningbot.log` 的 `WebIPC server 啟動：` 那行是不是 `100.110.130.17`；若寫 `127.0.0.1` 代表 Tailscale 沒起來、已自動退回本機 |
| 網頁開得起來但沒反應 | 狀態列是不是「WebSocket 斷線」。斷線會每 5s 自動重連 |
| 一直走 Discord 八方位圖 | 網頁沒連著，或斷線後還沒過 30s grace；`discord.log` 會記 `fall through Discord 八方位` |
| 點了沒下文 | 看 `miningbot.log` 的 `AIM web fire` / `回礦 web 介入`；逾時會明寫 timeout |
| `/history` 或 `/annotate` 回 503 | `snapshot_index.jsonl` 或 fixtures 目錄沒傳進 `WebIPCThread`（production 應該都有） |
| 啟動就卡死、Discord 什麼都沒出來 | **H061**：見下 |

⚠ log 路徑不要用猜的。`pythonw -m miningbot`（Microsoft Store 版 Python）會被 MSIX
重導到
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\Local\RexMacro\logs`；
`uv run` 才落在 repo 的 `logs/`。而且 LocalCache 那份的**目錄列表 mtime／size 會過期
數小時**——判斷「最新一場跑到幾點」一律 `Get-Content -Tail` 看內容時間戳。

## 給接手的 AI agent

### 安全邊界

`/snapshot` 讓外部指定要讀哪個檔，防護是 **realpath 必須落在 `snapshots_root` 底下**
＋只放行 `.png`。改這條 route 時別退化成字串比對——`..` 與 symlink 要在 realpath
階段攤平才擋得住（同 `_is_safe_category` 的教訓）。

### 千萬別做的事

**不要把 web 模組改成 deferred import。** `miningbot/main.py` 檔頭那段

```python
if cfg.web_server_enabled:
    from . import web_server as _web_server_preload
```

看起來像可以延後載入的東西，實際上是 **H061 的修復**。原本這行寫在 `Bot.run()` 裡，
而 `run()` 跑在 daemon thread；實機直譯器當時沒裝 uvicorn → `ModuleNotFoundError` →
`pythonw` 沒有 console，預設的 `threading.excepthook` 把 traceback 印到不存在的
stderr → **整個失敗蒸發**。HUD 還活著、`init_mining_sequence` 已按下 W＋左鍵，看起來
就是「只挖 D1、主迴圈沒進、log 停住」。三次實機啟動都這樣，事後查了一整輪才定位。

⚠ 調查期間曾誤判成「多執行緒 import lock 死結」——那個結論**是錯的**。之所以能自圓其
說，是因為重現用 `uv run`（venv 有 uvicorn），**整條調查比對了錯的直譯器**。查實機
問題第一件事是確認 production 跟你手上的重現環境是不是同一顆 Python。

通則仍然成立：**重型 import 放模組層**，不要放在 thread 已啟動之後的路徑。另外兩道
防線也別拆——`status_hud._run_bot_guarded`（執行緒 crash 必留 log + 彈框）與
`run()` 裡 WebIPC 區塊的 try/except（web 壞掉不可停止挖礦）。
`tests/test_startup_import_order.py` 守著這幾條。

### 架構要點

三條資料流刻意分開（spec §3）：

- **事件流**（bot → web）：`EventLog` + `WebEventSink`，跟 `DiscordSink` 並存
- **命令流**（web → bot）：網頁丟進 `web_pending` queue，**主迴圈在 safe point 取用**。
  絕不在 web thread 內直接呼叫 bot method
- **截圖流**：WebSocket binary 推原生 1920×1080 PNG，client 端自己用
  `canvas.width / rect.width` 換算原生座標；server 只做 thin validator

Race 規則是**先到先贏**：Discord 與網頁同時有人回，第一個進 `PendingReplies` 的贏，
後到的丟棄（`routing_key` 例如 `harvest:007` / `reentry:3`）。

### 測試

- `tests/fake_bot.py`：不啟動整台 bot 的 harness。要驗 `Bot` 上的整合方法就用它。
- 純函式測試在 `test_web_protocol.py` / `test_web_ipc.py` / `test_web_config_*.py` /
  `test_web_annotation.py` / `test_web_history.py`
- HTTP／WS 在 `test_web_server*.py`；main.py 整合在 `test_web_intervention.py`

⚠ **後端測試驗「有廣播」抓不到「前端沒接」**。`INTERVENTION_RESULT` 就吃過這個虧：
bot 廣播了、測試也綠了，但 `render_intervention_html` 的 JS 根本沒處理，玩家點完永遠
沒下文。改事件協定時記得同步掃 `web_static.py`。

### 已知未做

- 校準（俯仰）、手動轉 45°、回礦中的 `層`/`遠|近`/`仰角`/`放大`/`退` 文字指令——
  刻意留 Discord-only（見上面分工表理由），不是遺漏。
- harvest 候選清單的「放大手選退路」（`awaiting_fine`/`fine`/`magnify`/`back`）：
  這條退路本來是給候選都抓不準時用的；2026-07-28 候選清單改成點哪打哪
  （`_execute_remote_fire` 全套 D2/D5 重掃）之後，網頁端直接點候選圖精確度已經
  夠高，這條退路的必要性下降，先沒接網頁——還是 Discord-only。
- `/history` 的「結果」欄目前永遠是 `—`：`load_episodes` 還沒有結果來源
  （harvest.log 尚未接進去）。篩選 UI 保留著，接上就會動。
- 素材庫沒有按色系分子目錄。原因見
  [`tests/fixtures/aim/README.md`](../tests/fixtures/aim/README.md)：自動收集的 `auto_*`
  無從判斷色系。
