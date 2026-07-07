# 接手 Handoff — REX 挖礦自動化

> 先讀 `CLAUDE.md`（含實機踩過的坑），再看本檔。
> 分支：`main`（`python -m pytest -q` → 133 passed）

---

## 0. 快覽

| 項目 | 狀態 |
|---|---|
| 穩定挖礦 / 補 boost / D4 事件保留 / Discord 通知 / 重置等人工 | ✅ 正常 |
| 全 8 方位掃描採集 稀有 礦（HARVESTING 流程） | ✅ 實機驗證成功 |
| find_tracker 混合偵測（HSV 定位 + 實機裁圖形狀確認 + hard_floor 三區判定） | ✅ 全套 401 測試綠 |
| chill 音訊偵測（節流 + FFT 加速，延遲 ~1s） | ✅ 修復（原 6s 延遲） |
| heartbeat log（rms=%.6f + peak 追蹤，不再漏 chill 尖峰） | ✅ 修復（原 rms=%.0f 把所有音量殺成 0） |
| 採集後恢復挖礦統一走 init_mining_sequence（修漏按住 W） | ✅ 修復 |
| NEEDS_HUMAN 裁圖（跑 find_tracker 找最佳候選 → 240×240 標註裁圖） | ✅ 正常 |
| Discord 圖片通知（chill 特寫 / 追蹤框 / 成功證據） | ✅ 正常 |
| Discord 命令控制（!keep/!list/!clear 事件保留） | ✅ 正常 |
| D4 事件保留邏輯（OCR 讀事件 → keep/reroll） | ✅ 正常 |
| pythonw 無 console 啟動 + HUD 倒數合併 | ✅ 正常 |
| Log 分檔分流（heartbeat/actions/harvest/discord） | ✅ 正常 |
| chill 觸發自動錄音（累積訓練樣本） | ✅ 正常 |

---

## 1. 採集架構（完整流程）

```
chill 觸發 HARVESTING（音訊 score ≥ 0.30）
    │
    ▼
_on_enter(HARVESTING)：
    ├─ 截 chill 特寫 crop + rare_found 全圖
    ├─ 錄 chill 音訊 WAV（logs/snapshots/chill_audio_*.wav）
    ├─ Discord 通知 RARE_FOUND（附 chill 特寫圖）
    ├─ prepare_scan()（停移動、置中鏡頭）
    ├─ 截 pre_scan_ref（裝備位置穩定後）
    └─ execute_scan()（裝備 D2、click 中央、wait 1.5s）
    │
    ▼
_tick_harvest — 階段一：sweep（sweep_timeout_s=30s）
    ├─ _sweep_for_tracker()：全 8 方位旋轉掃描
    │   ├─ 每方位：find_tracker（三層過濾）→ 雙幀穩定確認
    │   └─ 旋回最佳方位 → 驗證仍在 → Discord TRACKER_FOUND（附圖）
    ├─ 找不到 → sweep_attempts++，重試一次（重新 D2 掃描）
    └─ 兩次都找不到 → NEEDS_HUMAN（最後保障）
    │
    ▼ （sweep 完成，重置 _harvest_start 計時器）
    │
_tick_harvest — 階段二：D3 開火（harvest_verify_timeout_s=45s；一次 D3 嘗試實測 ~20s，見 docs/incidents.md H015）
    ├─ key_press("2") → sleep(0.15) → key_press("3") → sleep(0.3)
    ├─ click_at(cx, cy, hold=0.4) → sleep(0.5)
    ├─ 驗證：find_tracker(after) is None + 聊天差分
    ├─ 成功 → Discord HARVEST_SUCCESS（附聊天截圖）→ init_mining_sequence()
    ├─ 未命中 → d3_attempts++（max_harvest_attempts=5 次後重掃）
    └─ 超時 → NEEDS_HUMAN
```

### D3 timing（2026-06-28 實測調整）

| 動作 | 舊值 | 新值 | 理由 |
|---|---|---|---|
| D3 裝備動畫等待 | 0.6s | **0.3s** | 實測 0.3s 即足夠 |
| 伺服器回應等待 | 1.0s | **0.5s** | 實測 0.5s 即足夠 |
| D3 重試上限 | 3 | **5** | 更多機會命中 |
| sweep 重試 | 無 | **1 次** | 第一次找不到重試一次才交人工 |

### 採集成功後恢復挖礦（2026-06-28 統一走 init_mining_sequence）

採集成功後呼叫 `miner.init_mining_sequence()`——與 Q 暫停恢復、啟動**完全相同**的完整序列
（清鍵→視角→置中→確認鎬子→W+左鍵）。舊的精簡 `resume_mining()` 常**漏按住 W**
（採集後鍵盤殘留狀態讓 `key_down("w")` 失效，角色不走），已移除統一走 init，避免兩條恢復路徑行為分歧。

---

## 2. find_tracker（2026-06-28 改混合方案：HSV 定位 + 實機裁圖形狀確認）

`vision.find_tracker(frame_bgr, margin_frac, exclude, log, reference_bgr, shape_templates, shape_threshold, shape_hard_floor, shape_scales, shape_roi_px)`

> **本次大改（修 very_rare.png「有礦卻沒發現」）**
> - **根因**：舊 colored 確認 `(S>90)&(V>90)&((H<35)|(H>95))` 排除 H35-95 黃綠帶 → 黃綠中心礦（Ionized）colored=0 漏抓。**已修為色相無關** `(S>90)&(V>90)`（純 HSV 即命中 (1231,644)）。
> - **混合偵測**：HSV 快速找候選（~246ms）後，在候選周圍小 ROI 跑「實機裁圖外框」形狀比對（+~65ms）確認，拒「有色但非追蹤框形狀」假陽性（如裝備誤射 (990,665)）。`cfg.tracker_shape_confirm` 控制；無實機裁圖時自動退回純 HSV。
> - **模板要用實機裁圖、非 wiki**：wiki 透明圖（alpha 外框）向量邊緣在合理尺度配不到遊戲內渲染框（實測全 miss，只在 scale 0.2 噪點假命中）；實機裁圖 edge≈0.91 且跨階通用（顏色無關，色相位移仍命中）。形狀確認集 = `assets/markers` 內無 alpha 的裁圖（自動篩）。已有 `transcendent_tracker_real.png`、`exotic_tracker_real.png`；其餘階級從 `logs/snapshots` 裁框補上。
> - 全幀模板比對太慢（2 張 5.7s／9 張 23.5s 每幀）→ 只在小 ROI 跑。

### 形狀確認三區判定（shape_hard_floor，2026-06-28 加）

舊版 soft filter 兩區（edge≥threshold=確認，否則全退回 HSV）會把「HSV 強但形狀全錯」的裝備誤判救回來（015044 實測 edge=0.16 被 soft filter 翻盤）。改成三區：

```
edge ≥ threshold (0.42)         → confirmed（返回此候選；0.45→0.42 見 docs/incidents.md H019/H026）
hard_floor (0.30) ≤ edge < thr  → survivor → 退回純 HSV（容忍未見階級外框配不到模板）
edge < hard_floor (0.30)        → hard_rej（完全移除，soft filter 不救）
```

實測分離：裝備誤判 edge≈0.16（擋下）、真追蹤框 edge≈0.81（不受影響）、borderline（square outline vs synth tracker ≈0.36 → survivor 仍退回 HSV）。`cfg.tracker_shape_hard_floor` 控制。

以下「三層過濾」描述 HSV 候選階段（仍有效）：

`vision.find_tracker(frame_bgr, margin_frac, exclude, log, reference_bgr)`

### 層一：ring_score 環形結構
```python
ring_score = frame_fill - inner_fill  # inner = 縮 30% 中心區
if ring_score < 0.15: reject          # cave wall blob ≈ 0；真 tracker ≈ 0.5
```

### 層二：reference_bgr 差分
```python
ref_fill = mean(ref_mask[bbox])
if ref_fill > 0.15: reject  # 掃描前就已存在 → 非追蹤框
```

### 層三：雙幀穩定（調用端實作）
```python
m1 = find_tracker(grab())
sleep(0.08)
m2 = find_tracker(grab())
if abs(m1-m2) < 8: accept  # 動畫/特效位置飄 → 拒；tracker 固定 → 通過
```

### 顏色範圍（per-range 獨立計算，不合併）
| 代號 | H 範圍 | 對應階級 |
|------|--------|---------|
| range0 | H 18–78 | Exotic（H≈23）、Enigmatic（H≈34）、Exquisite（H≈64） |
| range1 | H 88–130 | Transcendent（H≈105）、Unfathomable（H≈109） |
| range2 | H 118–165 | Exclusive（H≈142） |
| range3 | H 153–179 | Otherworldly（H≈167）；**紅色 礦坑環境效果差** |

---

## 3. Log 分檔結構

```
logs/
├── miningbot.log     ← 主敘事：啟動/狀態切換/里程碑/alert/error
├── heartbeat.log     ← 純心跳（含 audio score + RMS 診斷）
├── actions.log       ← boost/D4 重複動作 + D4 事件保留/刷新
├── harvest.log       ← sweep 逐步 + D3 verify 細節（採集除錯重點）
├── discord.log       ← Discord 送出記錄（哪些事件送了、成敗、命令執行）
├── events.log        ← 結構化 TSV（機器可解析）
└── snapshots/        ← 關鍵時刻截圖 + chill 音訊 WAV
```

子 logger 用 `propagate=False` 隔離——心跳/動作/採集細節不會污染主 log。

---

## 4. Discord 整合

### 圖片通知（3 個里程碑）

| 里程碑 | 事件 | 附圖 |
|---|---|---|
| 🔔 chill 偵測 | RARE_FOUND | chill_text_region 特寫 crop |
| 📍 sweep 確認追蹤框 | TRACKER_FOUND | 追蹤框可見的全畫面 |
| ✅ 採集成功 | HARVEST_SUCCESS | 聊天框 crop（has found 證據） |

使用 multipart/form-data 上傳（stdlib urllib，無 requests 依賴）。

### 命令控制（背景執行緒，每 10s 輪詢）

| 指令 | 功能 |
|---|---|
| `!list` | embed 列出 16 個事件 + ✅/❌ keep 狀態 |
| `!keep < 礦名>` | 加入保留清單（fuzzy match，支援部分名稱） |
| `!unkeep < 礦名>` | 取消保留 |
| `!clear` | 清空保留清單 |
| `!help` | 顯示指令說明 |

### D4 事件保留邏輯

```
D4 ready → 讀頂部事件列 OCR → match_event(text)
    ├─ 在 keep 清單 → use_activity_keep()（左鍵確認）
    └─ 不在 / 未知 → use_activity()（右鍵刷新）
```

事件資料庫在 `miningbot/game_data.py`（16 個事件，含 match phrase / 礦名 / 稀有度 / 效果）。

---

## 5. Chill 音訊偵測

### 延遲修復（2026-06-28）

**根因**：`match_score`（cross-correlation）每 chunk（85ms）算一次，但計算本身要 150ms → 音訊執行緒永遠跟不上 → WASAPI 緩衝持續積壓 → 6s 延遲。

**修復**：
1. **節流**：score 每 0.3s 算一次（`audio_score_interval_s`），緩衝每 chunk 照常更新（~1ms）
2. **加速**：normalization 用 cumsum O(N) 取代 correlate；主相關指定 `method="fft"`
3. **RMS 診斷**：heartbeat 加印 `rms=` 值（RMS≈0 → loopback 死；RMS 高但 score≈0 → 參考 wav 不符）

效果：6s 延遲 → ~1s（cross-correlation 本質限制：需 ~1s 的 chill 音訊填入緩衝才能跨門檻）。

### 偵測機制（cross-correlation，scale-invariant）

`assets/chill_reference.wav`（1.0s）是「chill 長怎樣」的模板。`LoopbackCapture` 背景擷取喇叭輸出
（WASAPI loopback，4096-frame≈85ms/chunk，int16→float32 單聲道）餵 `ChillListener`；listener
滾動 1.5s 緩衝，每 0.3s 算一次 `match_score`（正規化 FFT 交叉相關，滑動參考過緩衝取最大值 0..1）。
**正規化＝scale-invariant**：分數比的是波形「形狀」相符度、非絕對音量，故小聲也偵測得到，但 chill
相對背景挖礦聲的 SNR 低時分數會掉。主迴圈讀快取 score ≥ `audio_match_threshold` → HARVESTING。

### 門檻 0.30 → 0.25（2026-06-28）

實測同一場 chill 越來越小聲：`0.39→0.87→0.41→0.36→0.33→0.29(漏抓)`。0.29 差 0.01 沒過 0.30。
真 chill 0.29-0.87、靜音 0.01，中間是空鴻溝 → 降到 0.25 抓得到又不誤觸。

### 多參考集 + decimate（2026-06-28，根治「清楚 chill 卻漏抓」）

**根因（用錄音器實證）**：錄到 5 個都是**清楚**的 chill，對單一 `chill_reference.wav` 卻分到
`0.87/0.43/0.15/0.22/0.20`——交叉比對發現至少 **3 種不同的 chill 音效**（s87、s43、s15 群彼此
只 0.2x）。單一參考檔本質代表性不足，必漏其他種。

**解法**：`match_score_multi(buf, references)` 對多個參考取最高分——命中任一已知 chill 即可。
- `assets/chill_refs/*.wav`：各種 chill 的實錄裁片（`loudest_window` 抽 1.0s）。實測 3 個 distinct
  參考讓全部 5 個 chill 都 →1.000。**新 chill 漏抓時**：把 `logs/snapshots/audiochg_*.wav` 裁片丟進此夾即可擴充。
- 夾為空 → 退回單一 `chill_audio_path`（向後相容）。機器相依，不進版控（同 chill_reference.wav）。
- **decimate 加速**：`match_score` 對 buf+ref 同步 stride 抽樣（k=4）→ 分數不變、單次 118→22ms。
  多參考才不會重新引發音訊積壓（103ms×3 會爆 0.3s 預算；22ms×3=66ms 安全）。`audio_match_decimate`。
- 多參考取 max 後門檻意義變成「對自己的參考 ~1.0 vs 靜音 0.01」，0.25 門檻更穩。

### 音訊變動記錄器（2026-06-28，取代壞掉的觸發錄音）

`ChillListener(event_threshold=0.15, on_event=...)`：score 升過 0.15（去抖動 `RisingEdgeDetector`，
回落到一半才 re-arm）就在**音訊執行緒、分數算好的當下**回呼，存
`logs/snapshots/audiochg_<time>_s<score>_<TRIG|miss>.wav`。
- **比舊的觸發錄音準**：舊 `save_buffer_wav` 在 `_on_enter` 晚 ~3s 存（chill 已滾出 1.5s 窗）→ 存到
  chill 之後的音；新的在 rising-edge 當下擷取，與分數同調，含 chill 本體。
- **連沒觸發的 chill 也留證**（檔名 `miss`），可診斷「為何沒觸發」+ 累積乾淨樣本重錄 reference。
- **修 `*32767` 溢位**：buffer 已是 int16 值域，舊版再乘 32767 → 溢位繞回成雜訊（實測 RMS≈18900
  均勻 garbage）。改 `audio.save_wav`（直接 `clip→astype(int16)`），存出忠實波形。

---

## 6. 啟動方式

### pythonw 無 console 啟動

`啟動挖礦bot.bat`（純 ASCII，避免 cmd codepage 問題）：
```bat
@echo off
cd /d "%~dp0"
start "" pythonw -m miningbot.main
```

- `pythonw` = 無 console 視窗（log 全寫進檔案）
- `diagnostics.setup_logging` 在 `sys.stdout is None` 時跳過 stdout handler
- crash 時 `main()` 有 try/except → 彈 tkinter錯誤框 + 寫 log

### HUD 倒數合併

StatusHUD 在左下角原地倒數（不另開視窗），倒數完啟動 bot 背景執行緒 + 切換到正常輪詢。
`config.launch_countdown_s`（預設 3 秒）控制倒數時長。

---

## 7. 已知限制

- **「 礦已被自動挖走」無法自動偵測**：聊天只顯示 礦物名（不帶 tier），背包數字持續變動。sweep 兩次失敗仍走 NEEDS_HUMAN（最後保障），reason 無法自動判斷是否已被挖走。
- **chill OCR 模式 (`chill_require_ocr=True`) 會觸發不想要的階級**：若遊戲設定不播音效但畫面有 chill 文字，OCR 會偵測到並進入採集。目前維持 `False`（純音訊），靠遊戲端音效開關做天然階級過濾。
- **D3 階段超時檢查有 blocking 問題**：D3 fire 序列（sleep 多次）阻塞主迴圈，超時檢查只在下個 tick 生效。實測可能延遲數秒才觸發超時。

---

## 8. 排錯工具

```bash
# 截圖（設 DPI-aware）
python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/x.png', grab())"

# 手動跑全方位掃描（不跑整個 bot）
python -c "
import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2)
import time, cv2
from miningbot.capture import grab
from miningbot import vision, input_control as ic, harvester
from miningbot.config import DEFAULT as cfg
_cr = cfg.chat_region
excl = [(_cr.x, _cr.y, _cr.x+_cr.w, _cr.y+_cr.h)]
harvester.prepare_scan()
ref = grab()
harvester.execute_scan()
# 之後用 vision.find_tracker(grab(), exclude=excl, reference_bgr=ref, log=print) 確認
"

# 讀 log（避免 codepage 亂碼）
Get-Content logs\miningbot.log -Encoding UTF8 -Tail 50

# Discord 連線測試
python -c "from miningbot.config import DEFAULT as cfg; from miningbot.notify import send_message; print(send_message(cfg.discord_bot_token, cfg.discord_channel_id, 'test'))"
```

- log 檔：`miningbot.log`（主敘事）、`events.log`（結構化）、`discord.log`（通知記錄）
- `config.log_level="DEBUG"` 看每幀細節
- Exotic 追蹤框實機截圖：`assets/markers/exotic_tracker_real.png`（本機，不進版控）

---

## 9. 待改進與未來方向

### ✅ 已解決（2026-06-28）

- **Soft filter hard floor**：015044 裝備誤射根因——shape-confirm 正確拒絕（edge=0.16）但舊版 soft filter 翻盤退回 HSV。加 `tracker_shape_hard_floor=0.25` 三區判定後擋下。
- **模板修復**：`exotic_tracker_real.png` 原為合成佔位圖（342b）→ 換成真實裁圖（18035b）；`transcendent_tracker_real.png` 原為錯誤 32×32 L 角框 → 換成正確 61×57 四向星。
- **採集後角色不走（漏按住 W）**：精簡的 `resume_mining()` 即使先 `key_up("w")` 清空仍常漏按住 W → 直接移除，採集後統一改呼叫 `init_mining_sequence()`（與 Q 恢復、啟動同一條完整序列），杜絕兩條恢復路徑分歧。
- **熱鍵語意統一**：移除獨立的「強制停止」（EMERGENCY_STOP）——Ctrl+Q 與 Q 暫停走同一條 `_pause()`，Ctrl+Q 只暫停（idempotent）、Q 開關。避免暫停時誤按 Ctrl+Q 觸發更重動作。
- **heartbeat rms 格式**：`rms=%.0f` 把所有正常音訊 RMS（0.001-0.6）四捨五入成 0 → 誤判 loopback 死了。改 `%.6f` + 加 `peak=%.2f`（追蹤 30s 取樣漏掉的 chill 尖峰）。
- **NEEDS_HUMAN 裁圖**：原存全螢幕看不到重點 → 改跑 find_tracker 找最佳 edge score 候選 → 裁 240×240 + 黃框標註 + 分數 → 存檔 + Discord。
- **_tracker_log 路由**：sweep 的 3 個 find_tracker call 全接 log=（per-candidate→DEBUG、soft-filter/全數硬拒摘要→INFO），預設 level 可診斷。
- **logs/ 清理**：刪 175 張開發測試圖；`_diag_tracker.py` 升級為可帶路徑參數 + 自動載模板的事後診斷工具。

### ✅ 已解決（2026-07-07 更新——完整敘事見 `docs/incidents.md`）

- **遠距控制已完備**：`pause`/`resume`/`status`/`shot`/`keep` 系列 Discord 命令均已實作（本文件舊版只記到 keep）。
- **邊緣排除帶收窄 margin 0.02**：H019 右緣 / H026 底緣真框被 0.10 帶擋掉 → main 傳入 `tracker_margin_frac=0.02`，回歸 fixture 已鎖。
- **A 缺其他階級裁圖（部分）**：H039 的 enigmatic 尖刺太陽框已補進 `assets/markers`（首個新框形案例）；仍缺的階級照 A 的解法從 snapshots 補。
- **驗證式旋轉 / episode 聊天帳本＋晚到確認 / boost 守門 / RapidOCR 首選 / banner OCR 背景化 / 最短路徑旋回**：均已落地（見 `docs/incidents.md`）。
- **F D2 掃描成功確認**：2026-07-07 roadmap Phase 2 立案處理（`scan_succeeded` + 觀察期）。

### 🔴 偵測可靠性（直接影響採集成功率）

**A. 缺少其他階級的實機裁圖**（部分緩解）
- Exotic (120×120) + Transcendent (61×57) 兩張模板已修正為真實裁圖
- 缺：Enigmatic / Exquisite / Exclusive / Unfathomable / Otherworldly
- Hard floor 確保裝備誤判被擋（不再靠 soft filter 放行）；無實機裁圖時仍退回 HSV
- **解法**：每次採集時從 `sweep_confirmed_*.png` 截圖手動裁新模板 → 放入 `assets/markers/<tier>_tracker_real.png`

**B. Shape ROI 過大（160px）**
- D3 採集瞬間 ROI 內充滿角色身體 / 礦塊稜線 / 動畫特效 → Canny 產生數十條雜訊邊緣
- signal-to-noise 比低，shape score 被稀釋
- **解法**：縮小 `shape_roi_px` 到 80px，或在 ROI 內先做 HSV mask 隔離追蹤框區域再跑 Canny

**C. 採集時追蹤框被部分遮擋**
- 角色 / 礦塊可能擋住追蹤框的箭頭尖端 → shape score 下降
- 目前靠 survivor 區（hard_floor ≤ edge < threshold）緩解（退回 HSV）
- **解法**：部分輪廓匹配（≥60% 邊緣命中即接受），或採集前先微調鏡頭避開遮擋

**D. 跨階級形狀通用性未驗證**
- 兩張模板結構相同（4 向箭頭 + lime 中心），但不同階級在不同尺度下的 anti-aliasing 程度不同
- **解法**：實測 Exotic 模板能否偵測 Transcendent 礦（反之亦然），確認一張能否通配

### 🟡 功能缺口（不影響現有流程，但限制能力）

**E. 垂直追蹤框（仰角 礦）**
- 目前只水平旋轉掃描（8 方位 × 45°），仰角出現的 礦追蹤框會漏抓
- **解法**：加入垂直旋轉（右鍵拖曳 `aim_move`），或增加仰角掃描步驟

**F. D2 冷卻偵測**
- 目前 D2 掃描後直接等 1.5s，不知道掃描是否真的成功（左下 "Local" 標籤）
- 若 D2 冷卻中或被 UI 吃掉點擊 → sweep 全空 → 浪費時間
- **解法**：掃描後 OCR 確認 "Local" 文字；仿 D4 冷卻模板做 D2 冷卻圖示偵測

**G. 背包滿了無法自動處理**
- 礦物採集持續累積，背包滿後新 礦無法收入
- **解法**：監控背包容量（`Capacity: X%`），到閾值時自動走到 NPC 賣 礦
- 參考：Repo 2 (Machina) 用 `Remotes.SellOre` + tierNum 門檻實作自動賣

**H. 只支援 World 1**
- REX 有 5 個世界：natura / lucernia / luna_refuge / aesteria / caverna
- 目前座標 / 礦層設定只適用 World 1
- **解法**：加世界選擇 + 各世界座標 profile

### 🟢 優化項（現有功能可改進）

**I. tier-specific 模式（可選切換）**
- REX 預設各階級有獨立文字 + 音效（如 Transcendent = "You hear a ringing in your ears..."）
- 目前用 unified chill 簡化（一段文字 + 一個音效通吃）
- 若切換回 tier-specific：OCR 抓 tier 文字 → 得知階級 → 選對的 HSV range + 模板 → 更精準
- **代價**：需為 7 個階級各收集文字片段 + 音效參考 wav + HSV 範圍（28 項資料），任一缺失即漏抓
- **評估**：目前 unified chill + soft filter 已足夠，除非 false positive 嚴重才值得切換

**J. chill 音訊樣本分析**
- 每次觸發自動存 WAV 到 `logs/snapshots/chill_audio_*.wav`
- 可分析：不同環境的音效差異、onset detection（比 cross-correlation 更快偵測）、頻譜特徵
- **目標**：將偵測延遲從 ~1s 降到 <0.5s

**K. anti-detection 隨機化**
- 目前採集流程固定（8 方位旋轉 → D3 點擊）
- Repo 1 (cryolator) 在採集時加入隨機 WASD 移動模式池
- **解法**：在 sweep 之間加入隨機延遲 + 偶發跳躍，讓行為更「像人」

**L. 自動賣 礦 + 自動裝備**
- 長時間掛機需要定期清背包 + 更換裝備
- 目前完全手動
- 參考：Repo 2 的 `mainHandOrder` / `offHandOrder` 裝備系統

### 📊 兩個參考 repo 的借鑑

| 來源 | 功能 | 我們能用？ | 備註 |
|---|---|---|---|
| Repo 1 (cryolator) | 音量峰值 `> 0.0005` 偵測 | ❌ 太粗暴 | 我們的 cross-correlation 更精確 |
| Repo 1 | FindText OCR 偵測 礦坑重置 | ✅ 已有 | 我們的做法相同 |
| Repo 1 | `EquipAll()` 按 2-9 → 1 循環 | 🔜 可參考 | 若加自動裝備切換 |
| Repo 1 | 隨機移動模式池（anti-detect） | 🔜 可參考 | 採集時加入隨機性 |
| Repo 2 (Machina) | `Mine.ChildAdded` 記憶體偵測 | ❌ 需 exploit | 外部 bot 無法使用 |
| Repo 2 | tier 優先序 supernatural→common | ✅ 可參考 | 若加 礦物優先級排序 |
| Repo 2 | 自動賣 礦（tierNum 門檻） | 🔜 可參考 | 需 game UI 互動 |
| Repo 2 | 5 世界支援 | 🔜 可參考 | 各世界座標 profile |
