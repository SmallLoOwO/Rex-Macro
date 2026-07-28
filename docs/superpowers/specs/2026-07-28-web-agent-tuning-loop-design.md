# 2026-07-28 網頁 × agent 微調迴圈：語料止血、ledger 資料集、預測點、標註回饋

> **狀態**：設計，未實作。由 2026-07-28 grilling session 產出，逐題與使用者確認。
> **一句話**：網頁該補的不是更多操作介面，是**把已經在收的東西接起來變成 agent 能吃的資料**——
> 而且要先止血，因為語料正在被保留機制刪掉。

## 0. 委派注意（實作者必讀）

- **不要目視讀 PNG**；座標／尺寸量測用 `cv2.imread` 計算斷言。
- 不 commit、不切 branch、不刪 runtime 證據、不操作 Roblox/Discord（除非玩家明確要求）。
- 完成過：`uv run pytest -q`、`uv run ruff check . --no-cache`、`uv lock --check`。
- 座標／門檻／間隔只放 `miningbot/config.py`；純決策不做 I/O。
- 玩家可改的 Config 欄位只有 `WEB_CONFIGURABLE_FIELDS` 四個；門檻/ROI 不上網頁。
- 素材 `.json` 只存症狀，不存根因（根因屬 `docs/incidents.md`）。
- **本檔每個 D 區塊可獨立實作**，但 D0 有時效性（見 §3）。

## 1. 背景與量測證據

### 1.1 網頁介入命中率 1/4，且不是通知問題

`logs/discord.log`（MSIX LocalCache）實測：

```
07-26 18:34  RR#26  web 介入：reply timeout            → fall through Discord
07-27 19:00  RR#26  web 介入：逾時無回應（等了 300s）  → fall through Discord
07-28 00:39  RR#27  web 介入：收到點擊 dir=3           ✅
07-28 15:47  RR#28  web 介入：逾時無回應（等了 300s）  → fall through Discord
```

**四次介入、三次逾時，每次白燒 300 秒。**

先前假設是「沒有通知管道」——**錯的**。`main.py:_notify_web_intervention_pending`
（07-26 就上線）已經在 Discord 發帶網址的提醒，附 🔀 立即切 Discord 反應，介入結束
自動收回訊息；15:47 那次 log 有 `web 介入提醒收回 mid=1531567562150903948 -> HTTP 204`，
證明提醒確實發出去了。

**結論：逾時的原因是人不在，不是通知不到。**任何新增通知管道（Web Push／ntfy）
都改善不了「人在睡覺」。唯二有效的方向是拉長預算（D5）與降低單次介入的操作成本（D2）。

### 1.2 自動回礦的語料正在流失（本檔最急的一項）

`logs/reentry_remote/ledger.jsonl` 每筆回礦 attempt 記的東西，本身就是完整的
監督式資料集：

```json
{"episode": 27, "world": "Lucernia", "outcome": "confirmed_by_user", "attempt": 2,
 "shots":  [[0,"…ep27_dir1.png"], [1,"…dir2.png"], …, [7,"…dir8.png"]],
 "clicks": [{"pos":[1604,450], "dir":2, "layer":"Shamrock",
             "invalid":false, "depth_m":7100, "layer_seen":"Shamrock"}]}
```

八個方位的圖 + 傳送板真實座標 + 哪個方位才是對的 + 最終結果，全在同一行。
同一筆裡另外 7 張是**天然負樣本**——玩家看過八張才選那一張。

實測產出（`uv run python` 掃 ledger + 檔案存在檢查）：

```
ledger rows       30
shots total       200   resolvable 58     ← 142 張已被刪
rows with clicks  19    clicks total 22
usable positives  1     usable negatives 7  ← 能配成 (圖, 座標) 的只剩這些
```

**帳還在，圖沒了。**根因是 `config.snapshot_max_total_mb=1024`
（`diagnostics.plan_snapshot_cleanup`）到頂之後從最舊開始刪，
**不分那張圖有沒有 click ground truth**。1080p PNG 每張 1-3MB，
八方位一輪就吃掉 10-16MB，撐不了多久。

`_save_auto_fixture`（`main.py:7138`）雖然會在回礦結束時存素材，但**一次只存玩家點的那一張**，
另外 7 張負樣本直接丟。`tests/fixtures/reentry/teleport_board/` 至今只有 1 個檔。

**每多過一天，就少一組不可再生的語料。**（`docs/superpowers/specs/2026-07-21-reentry-yaw-investigation-findings.md`
當時就記過「landing 快照一小時內被保留機制從 14 清到 10，要留語料先備份」，
記下來了但沒有做防護，於是三個月後只剩 1 組可用配對。）

### 1.3 標註迴圈斷在「沒有消費者」

```
bot 出事 → diagnostics 存快照 + snapshot_index.jsonl
   → /history 按 tier 排序（tier0 = 掃描全空／框被拒／瞄準失敗）
   → /annotate 選症狀 → 寫 tests/fixtures/<類>/<名>.{png,json}
   → ??? ← 沒有任何程式讀那些 .json
```

成果：**兩張**（`aim/auto_118_fail.json`、`reentry/teleport_board/auto_27_success.json`）。

標註對玩家零回報（標完看不到任何結果），所以沒人標；標了也沒有東西吃，
所以標了也沒用。兩頭都斷。

### 1.4 MSIX 路徑重導（任何讀 ledger 的程式都會踩）

ledger 裡記的快照路徑**不存在**：

```
記錄值  C:\Users\puppy\AppData\Local\RexMacro\logs\snapshots\reentry\…png   → Test-Path False
實體    C:\Users\puppy\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0
        \LocalCache\Local\RexMacro\logs\snapshots\reentry\…png              → Test-Path True
```

`pythonw -m miningbot`（`.bat` 啟動路徑）跑的是 Store 版 Python，寫入被 MSIX 虛擬化重導。
`uv run` 啟動則落 repo `logs/`。**同一份 ledger 裡可能兩種路徑混存**（依當時用哪個直譯器啟動）。

## 2. 已解，勿重做

grilling 過程中查證發現下列先前的「缺口」其實已經修掉，實作者不要再動：

| 項目 | 狀態 |
|---|---|
| 網頁點候選要落在候選 ±80px 內才算數 | **已拆**（`main.py:3522` 改「點哪就打哪」，07-28）。log 裡 `附近沒有候選，忽略` 是 07-27 的舊行為，字串已不在原始碼 |
| `sweep_pitch` 未校準導致開關無效 | **已校準**（`sweep_pitch_step_px=185`，config.py:435）。設定頁那條 ⚠ 警告現在會顯示 ✅ |
| 網頁沒有 Discord 介入提醒 | **已有**（`_notify_web_intervention_pending`，含網址 + 🔀 escalate + 自動收回） |

## 3. 範圍

**做**（依相依順序）：

| # | 項目 | 動到哪 | 急迫性 |
|---|---|---|---|
| D0 | 語料止血：有 click 的整組八方位落到不受 retention 管的語料夾 | `main.py` + `config.py` | **每天流失，最急** |
| D1 | ledger → 傳送板資料集離線 script + 評估報告 | 新檔，不碰網頁 | 高（D0 之後） |
| D2 | 預測點：偵測器的猜測畫在八方位圖上推給玩家確認 | `main.py` + `web_static.py` | 中（依賴 D1） |
| D3 | 標註即時回判決 + tier0 批次標註 | `web_server.py` + `web_static.py` | 中 |
| D4 | agent 面板：失敗佇列 + 「什麼最常爆」統計 | `web_server.py` + `web_static.py` | 中 |
| D5 | 介入預算拉長 | `config.py` 一行 | 低，順手做 |

**明確不做**（本次已與使用者確認，寫下來免得下次又被提案）：

- **auth／token**：暴露面只有使用者自己的 tailnet。守門規則：**不可綁 `0.0.0.0`、
  不可開 Tailscale Funnel**。哪天要改網路設定，先回來做 auth。
- **Web Push / ntfy 推播**：§1.1 已證明逾時是人不在，不是通知不到。
- **即時畫面串流**：📷 單張夠用，串流吃主迴圈截圖預算。
- **把 Discord 的 `仰角`／`放大 <細格>`／粗細格代碼移植上網頁**：網頁的 pinch-zoom 8x
  本來就比格子鏈精確，移植等於把 Discord 的表達限制搬到不需要它的地方。
- **`reentry_mode=auto` 全自動**：使用者明確不要。D2 的預測點是終點，不是中繼站——
  bot 永遠只「建議」，人點下去才動。H043 虛空墜落是這條路的代價。
- **annotation-driven pytest 迴歸**：延後。現在只有 2 張標註，迴歸沒有意義；
  等 D1+D3 把量做到 ~20 張再開。屆時要先決定「已知未修」怎麼標（xfail 名單），
  否則 `aim/auto_118_fail` 會讓那支測試從第一天就紅。

---

## D0. 語料止血

### 目標

有 ground truth 的回礦八方位圖，永遠不被 snapshot retention 刪掉。

### 做法

**不要改 retention 規則**（放寬上限會讓總量無界，OneDrive 同步夾實測 632MB 已經是痛點）。
正確做法是**在刪之前把有價值的那一組搬走**。

改 `main.py` 回礦收尾寫 ledger 的地方（`_rr_finalize` 附近，現在呼叫
`_save_auto_fixture(flow="reentry", …)` 那處，`main.py:7138`）：

當這一輪 `clicks` 非空且 `invalid` 為 False 時，把 **整組八張** 複製到
`<log_root>/corpus/reentry/ep<N>_attempt<M>/`，同時寫一份 `meta.json`：

```json
{"episode": 27, "attempt": 2, "world": "Lucernia", "sticky_layer": "Shamrock",
 "outcome": "confirmed_by_user", "t": 1785170168.8,
 "shots": [{"dir": 1, "file": "dir1.png"}, …, {"dir": 8, "file": "dir8.png"}],
 "clicks": [{"dir": 2, "pos": [1604, 450], "layer_seen": "Shamrock", "depth_m": 7100}]}
```

要點：

- **`meta.json` 存相對檔名，不存絕對路徑**——語料夾要能整包搬到別台機器，
  絕對路徑一搬就死（且會踩 §1.4 的 MSIX 重導）。
- 語料夾**不進 snapshot retention 的掃描範圍**。確認 `diagnostics` 的清理只掃
  `snapshots/`，`corpus/` 在它之外；若不是，加排除。
- 語料夾**必須 gitignored**。八張 1080p PNG ≈ 10-16MB，20 組就 300MB，
  進 git 是災難。`tests/fixtures/` 只放精選的少數當迴歸素材，兩者是不同東西。
- **best-effort**：複製失敗只記 log 不炸主流程（沿用 `_save_auto_fixture` 既有慣例）。
- `outcome` 為 `skip`／無 click 的那些**也存**，但 `clicks: []`。
  「玩家看完八張決定跳過」本身就是資訊（可能傳送板真的都不在視野內）。
  給語料夾一個獨立的容量上限（`corpus_max_total_mb`），到頂時**優先刪無 click 的**。

### 順手補：現有 58 張的一次性搶救

寫一支 `--rescue` 模式（或獨立小 script），把 ledger 裡**現在還讀得到**的那些
（58 張、含 1 正 7 負）先倒進 `corpus/`。這批是三個月的殘骸，倒完就不會再少。
路徑解析必須處理 §1.4 的雙路徑。

### 驗收

- 跑一輪回礦（或用 fake ledger + 假 PNG）後，`corpus/reentry/ep*/` 有 8 張 + meta.json。
- `meta.json` 內路徑是相對的。
- 語料夾在 retention 掃描範圍外（單元測試斷言 `plan_snapshot_cleanup` 的 entries
  收集不含 corpus）。
- 複製失敗（唯讀目錄）時主流程不受影響。

---

## D1. ledger → 傳送板資料集（離線 script）

### 形態

`uv run python -m miningbot.build_reentry_dataset`。**不碰網頁**（使用者明確選擇：
bot 沒跑也要能用，且 agent 直接 `uv run` 就拿得到）。

### 輸入

1. `corpus/reentry/*/meta.json`（D0 之後的主要來源）
2. `logs/reentry_remote/ledger.jsonl` + snapshots（D0 之前的殘骸，走 §1.4 路徑重導）

兩個來源合併，以 `(episode, attempt)` 去重。

### 輸出

`corpus/reentry/dataset.jsonl`，每張圖一行：

```json
{"image": "ep27_attempt2/dir2.png", "dir": 2, "world": "Lucernia",
 "layer_seen": "Shamrock", "depth_m": 7100,
 "label": "positive", "xy": [1604, 450],
 "episode": 27, "attempt": 2, "outcome": "confirmed_by_user"}
{"image": "ep27_attempt2/dir1.png", "dir": 1, …, "label": "negative", "xy": null}
```

**正負樣本定義**（寫死在 script，不給參數——定義漂移比資料少更危險）：

- `positive`：該 `(episode, attempt)` 有 click、`invalid=False`、
  `outcome ∈ {confirmed_by_user, descended}`，且 click 的 `dir` 對上這張圖。
- `negative`：同一組裡**其他七個方位**。理由：玩家看過全部八張才選那一張。
- **排除**（不進資料集，記在報告的 skipped 欄）：
  - `outcome=skip`／`started`／`None`（沒有玩家判斷可依）
  - `invalid=True` 的 click（玩家自己標作廢）
  - 同一組有多次 click 且落在不同 dir（表示前幾次點錯，語意不明確）
  - 圖檔讀不到

### 評估報告

同一支 script 的 `--eval`：把現行偵測器跑過整份資料集，輸出

```
positives 20  hit 13 (65.0%)   miss 7
negatives 140 clean 131        false-positive 9
中位誤差 34px（命中者）
按 world/layer 分組明細
逐張明細 → corpus/reentry/eval_<timestamp>.jsonl
```

「hit」定義：偵測器最高分預測落在真實座標 `reentry_dataset_hit_radius_px`（新 Config 欄位，
預設 80）內。這個半徑要能調——傳送板本身有大小，像素級精確沒有意義。

### 已知的資料偏誤（報告要印出來，不要讓 agent 自己踩）

- **100% Lucernia、幾乎 100% Shamrock、100% 夜晚**（Lucernia 設定上恆夜）。
  單一世界單一層的語料讓「名牌＝當前層」這類假說不可否證。
- **每輪 attempt 都會「回到地表」換重生點 = 隨機化 yaw**，所以 `dir=1` 不是固定方向，
  只有 attempt 1 例外。詳見 `2026-07-21-reentry-yaw-investigation-findings.md`。
- **ledger 的 `layer` 欄位是玩家宣告字串，20 筆錯過 5 筆**；已改用 `(世界, Depth)`
  反推的 `layer_seen`（`8d2432a`）。資料集一律用 `layer_seen`，舊筆缺這欄就標 `null`，
  不要退回 `layer`。
- **LIMIT 徽章／層名牌是螢幕空間 UI**，不是世界物件，不可拿來判朝向。

### 驗收

- 對 `tests/fixtures/` 裡的合成 ledger + 假 PNG 跑得出正確的正負分類（單元測試）。
- 路徑重導雙路徑都能解析（單元測試，不需真檔）。
- `--eval` 在零命中與全命中兩端都不會除以零。

---

## D2. 預測點

### 目標

把 D1 訓練/調校出來的偵測器**掛回介入流程**，但只做建議、不自動點。
使用者明確選擇：**不切 `reentry_mode=auto`，只做「預測點」**。

### 做法

`_rr_sweep_capture` 拍完八張之後、推網頁之前，對每張跑一次傳送板偵測，
把最高分預測畫成一個圈 + 分數疊在圖上再推送。玩家看到的是「bot 猜這裡，你確認」。

- 疊圖只在**推給網頁的那份 PNG** 上畫，不改原始快照——原始快照是語料，不可污染。
- 分數低於 `reentry_predict_min_score` 就不畫（畫一個亂猜的圈比不畫更糟）。
- 面板上加一顆「採用建議」鍵：直接送出預測座標，玩家不必自己點準。
  這是降低單次介入操作成本的主要手段（§1.1 的另一條有效路徑）。
- 玩家**點在別的地方 = 否定了預測**。這一筆要記進 D0 的 `meta.json`
  （`predicted_xy` + `actual_xy`），**迴圈自己就會長大**：每確認一次，
  資料集就多一筆帶「模型當時怎麼想」的樣本。

### 為什麼這是終點而不是中繼站

使用者不要全自動。預測點的價值不在「省掉那一下點擊」，在於**它把標註成本降到零**：
玩家為了回礦本來就要點，順手就產生了一筆「預測 vs 真實」的比對。
D3 的手動標註是它的備援，不是主線。

### 驗收

- 偵測器回空／低分時，面板行為與現在完全一致（不畫圈、不加鍵）。
- 「採用建議」送出的座標與圈心一致（座標鏈已驗到 native 級，不要重新發明換算）。
- `meta.json` 同時有 `predicted_xy` 與 `actual_xy`。

---

## D3. 標註即時回判決 + tier0 批次

### D3a 回判決

`POST /api/annotate` 寫完檔之後，就地跑現行偵測器對那張 crop，回應多帶：

```json
{"ok": true, "verdict": {"detector": "rejected", "score": {"edge": 0.19, "colored": 0.44},
                          "your_label": "false_negative", "agree": false}}
```

前端顯示「現行判：拒絕（edge 0.19）／你標：漏判 → ❌ 不一致」。

**這是 D3 存在的理由**：現在標註對玩家零回報，所以只標了 2 張。有了回判決，
玩家標的當下就知道這張圖是不是真的暴露 bug、還是偵測器其實已經修好了。

注意：`web_server` 要 import `vision`，這會把偵測相依拉進 web 路徑。
用 deferred import（函式內 import）+ try/except，缺件時退回「不附 verdict」，
**不可讓 web 因為偵測模組出問題而掛掉**（H061 的教訓）。

### D3b tier0 批次標註

`/annotate` 加佇列模式：`?queue=tier0` 進來時，
按 `web_history.annotation_tier` 撈全部 tier0 快照，一張一張走，
底部顯示「第 3 / 47 張」，鍵盤 `j`/`k` 上下張、數字鍵選症狀、`Enter` 送出下一張。

沒有這個就永遠停在 2 張。tier 排序邏輯已經寫好（`web_history.py:37`），只差前端。

### 驗收

- 回判決在偵測模組 import 失敗時仍能存檔（降級不靜默：log 一行）。
- 佇列模式下送出後自動跳下一張，且不會重複給已標過的。
- 鍵盤操作不干擾表單輸入框。

---

## D4. agent 面板

使用者原話：「這些資料對我來說沒有意義，對 AI agent 比較有價值，讓他去處理微調的問題」。
所以這一頁的讀者是 agent，不是玩家——**排版可以醜，資料要全**。

### D4a 偵測失敗佇列

`/failures`：tier0 快照集中一頁，每張附「現行偵測器判什麼 + 分數明細」。
agent 不用挖 log 就能直接看到候選案例。等於 D3a 的批次唯讀版。

### D4b 「什麼最常爆」統計

`/stats`：按 `snapshot_index.jsonl` 的 label 聚合，
今日／本週各出現幾次；`sweep_empty` 幾次、交人工幾次、採到幾顆、回礦逾時幾次。

**先知道哪條最痛，才知道該修哪條。**現在這個判斷完全靠印象。

### D4c JSON 端點

`/api/failures`、`/api/stats` 回同樣的資料。agent 用 `curl` 抓，不必解析 HTML。

### 驗收

- 三條路徑在 `snapshot_index.jsonl` 不存在／損壞時回 503 而不是 500。
- 統計的時間分組用檔案的 `written_at`，**不用目錄 mtime**
  （MSIX LocalCache 的目錄 metadata 會過期數小時，見 `AGENTS.md` LIVE-RUN TROUBLESHOOTING）。

---

## D5. 介入預算

`web_intervention_budget_s: 300.0 → 900.0`（config.py:542）。

§1.1 證明逾時是人不在。300s 抓不到離開座位的人，900s 有機會。
代價是沒人時 bot 停更久——但逾時之後掉回 Discord 八方位**也一樣要等人**，
所以「停更久」的實際成本比看起來小。

一行改動。若實測發現 900s 太久再往回調。

---

## 4. 相依與衝突

```
D0（止血，動 main.py）
 └→ D1（離線 script，不碰 main.py）
     └→ D2（動 main.py + web_static.py）
D3（動 web_server.py + web_static.py）      ← 與 D0/D1 無衝突，可並行
D4（動 web_server.py + web_static.py）      ← 與 D3 同檔，不可並行
D5（config.py 一行）                        ← 隨時
```

**`main.py` 是所有任務的共用戰場**（`AGENTS.md`：`main.py` 與 `config.py`
幾乎每個任務都會碰，平行做是 merge 打架不是加速）。D0 與 D2 都動 `main.py`，
必須序列。D3 與 D4 都動 `web_server.py`／`web_static.py`，也必須序列。

可並行的只有一組：**{D0→D1→D2} 與 {D3→D4}** 兩條線。

另注意：本 repo 會有另一個 session 同時在改同一批檔。開工前 `git status --short`，
staging 時只 stage 自己寫的 hunk。

## 5. 新增 Config 欄位

```python
corpus_max_total_mb: int = 4096            # 語料夾容量上限（到頂優先刪無 click 的）
reentry_dataset_hit_radius_px: int = 80    # D1 評估「命中」半徑；傳送板有大小，像素級無意義
reentry_predict_min_score: float = 0.0     # D2 預測分數低於此不畫圈（待實機定值）
web_intervention_budget_s: float = 900.0   # 300 → 900（D5）
```

`reentry_predict_min_score` 的預設值**必須等 D1 的評估報告出來才能填**，
在那之前留 0.0 並在註解標「待 D1 實測」。憑空猜門檻正是本 repo 一再犯的錯。

## 6. 測試要求

- 純函式優先：正負樣本分類、路徑重導、tier 佇列排序、統計聚合都是純函式，
  不需要 Roblox/Discord/真檔。
- 需要 PNG 的測試用**合成圖**或 `tests/fixtures/` 既有的**兩張**真素材，
  不可依賴機器本地的 `corpus/`（fresh checkout 沒有）。
- 不放寬任何偵測門檻、不刪任何事故迴歸。
- D1 的 `--eval` 報告本身不是測試——它是給 agent 看的觀測值，
  不可拿它的數字當斷言（語料會長大，數字會變）。

## 7. 一句話總結

**先止血（D0），再把已經收到的用掉（D1），然後讓迴圈自己長大（D2）。**
D3/D4 是給 agent 的工具與備援。網頁不缺操作介面，缺的是把三個月的實機證據
變成 agent 能吃的東西。
