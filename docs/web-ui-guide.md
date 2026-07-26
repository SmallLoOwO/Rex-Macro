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
| 遙控器（暫停／繼續／能力／截圖／回礦） | ✅ 主用 | 不接手 |
| 採集／回礦事件通知、手機推播 | ✅ 保留 | 也顯示，但推播靠 Discord |
| 需要人工時的 PING | ✅ 唯一 | — |
| **手動瞄準（harvest awaiting_fine）** | 網頁沒人時才用 | ✅ 主用 |
| **回礦點傳送板** | 網頁沒人時才用 | ✅ 主用 |
| **看歷史紀錄、標註素材** | ❌ | ✅ 唯一 |
| **改玩家設定（4 個欄位）** | ❌ | ✅ 唯一 |

「網頁沒人時」= WebSocket 一個 client 都沒連著，且已過 `web_fallback_grace_s`
（預設 30s）。grace 是為了讓你手機切背景／重新整理時不會立刻掉回 Discord。

## 設定（一次性）

網頁伺服器跟 bot **同一個 process**（daemon thread），綁 `127.0.0.1:8765`——
不對外開，所以不必動 Windows 防火牆。

要用手機連，靠 Tailscale 出 HTTPS：

```powershell
# 1. Bot 主機裝好 Tailscale 並登入（手機也加入同一個 tailnet）
# 2. 開一條 serve
tailscale serve https / http://localhost:8765
# 3. 看網址
tailscale serve status
```

手機開 `https://<machine>.<tailnet>.ts.net` 就是介入面板。

**不需要再加帳號密碼或 token**——tailnet 的設備授權就是認證，只有你自己的裝置連得進來。

相關設定（`miningbot/config.py`）：

| 欄位 | 預設 | 意思 |
|---|---|---|
| `web_server_enabled` | `True` | 關掉的話整個網頁子系統不啟動，所有流程自動退回 Discord |
| `web_server_port` | `8765` | 綁 `127.0.0.1` 的 port |
| `web_fallback_grace_s` | `30.0` | 最後一個 client 斷線後，等多久才判定「網頁沒人」 |

啟動成功時 `miningbot.log` 會有一行 `WebIPC server 啟動：http://127.0.0.1:8765`。

## 四個頁面

| 路徑 | 做什麼 |
|---|---|
| `/intervention` | **介入面板**——收到 bot 的截圖，雙指放大後點位置 |
| `/` | 玩家設定（4 個欄位） |
| `/history` | 歷史紀錄：episode 列表，可依類型／關鍵字篩選 |
| `/annotate?episode=<id>` | 標註工具：在快照上拖方形、填礦名／稀有度／症狀 |
| `/health` | 給人確認 server 活著（不是給玩家看的） |

### 介入面板怎麼用

1. bot 需要你的時候，Discord 會 PING 你，網頁狀態列同時變成「需要介入：…」。
2. 畫面出現當下的遊戲截圖。手機雙指 pinch-zoom + 拖曳；桌機滾輪縮放 + 拖曳。
3. **點在礦物追蹤框的中心**。點下去就送出，不用再按確認。
4. 狀態列會變成「已送出點擊 (x, y)」，接著等 bot 回覆：
   - 綠色 ✅ ＝ 採集／下礦成功，這一輪結束
   - 紅色 ❌ ＝ 沒成功。回礦流程可以**再點一次**（最多 3 次）；採集流程要回 Discord 用
     `重骰` / `跳過`
5. 拖曳畫面不會被當成點擊（移動超過 5px 就算拖曳）。

⚠ 你點的是**當下這一幀**。等太久（採集 60s、回礦 retry 30s）就會逾時退回 Discord。
另外礦坑如果在你猶豫時開始重置，bot 會拒絕這次點擊並告訴你——那不是 bug，是防止對著
過期畫面開一發 D3。

### 玩家設定只有 4 個欄位

`reentry_mode`（off／remote／auto）、`reentry_target_layer`、`reentry_yaw_sample_sweep`、
`sweep_pitch_enabled`。

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
| 手機連不上 | `tailscale serve status`；再確認 `miningbot.log` 有沒有 `WebIPC server 啟動` |
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

### 千萬別做的事

**不要把 web 模組改成 deferred import。** `miningbot/main.py` 檔頭那段

```python
if cfg.web_server_enabled:
    from . import web_server as _web_server_preload
```

看起來像可以延後載入的東西，實際上是 **H061 的修復**。`Bot.__init__` 在 `run()` 之前
就已經 spawn 了四個 worker thread，其中 `ocr.rapidocr_available` 與
`ocr.tesserocr_available` 各自在 thread 裡跑 C 擴展的 deferred import。主執行緒這時再
deferred import fastapi 鏈就是**三方 import lock 死結**——實機三次啟動全部卡死，連
worker thread 一起靜默。

通則：**這個 repo 任何新的重型 import 都放模組層**，不要放在 thread 已啟動之後的路徑。
`tests/test_startup_import_order.py` 守著這條。

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

- 網頁的 `control:pause` / `resume` / `request_frame` 管線通了但**兩邊都沒接 UI**——
  這是設計（spec §2：遙控器 Discord 主用、網頁不接手），不是半成品。
- 素材庫沒有按色系分子目錄。原因見
  [`tests/fixtures/aim/README.md`](../tests/fixtures/aim/README.md)：自動收集的 `auto_*`
  無從判斷色系。
