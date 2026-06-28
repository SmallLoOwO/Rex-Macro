# 接手 Handoff — REX 挖礦自動化

> 先讀 `CLAUDE.md`（含實機踩過的坑），再看本檔。
> 分支：`feature/window-discord-controls`（`python -m pytest -q` → 123 passed）

---

## 0. 快覽

| 項目 | 狀態 |
|---|---|
| 穩定挖礦 / 補 boost / D4 事件保留 / Discord 通知 / 重置等人工 | ✅ 正常 |
| 全 8 方位掃描採集 稀有 礦（HARVESTING 流程） | ✅ 實機驗證成功 |
| find_tracker 三層過濾（ring_score + reference_bgr + 雙幀穩定） | ✅ 123 測試綠 |
| chill 音訊偵測（節流 + FFT 加速，延遲 ~1s） | ✅ 修復（原 6s 延遲） |
| D3 採集驗證（聊天差分 has_new_found） | ✅ 正常 |
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
_tick_harvest — 階段二：D3 開火（harvest_verify_timeout_s=15s）
    ├─ key_press("2") → sleep(0.15) → key_press("3") → sleep(0.3)
    ├─ click_at(cx, cy, hold=0.4) → sleep(0.5)
    ├─ 驗證：find_tracker(after) is None + 聊天差分
    ├─ 成功 → Discord HARVEST_SUCCESS（附聊天截圖）→ resume_mining()
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

### resume_mining()（採集成功後恢復挖 礦）

不呼叫 `init_mining_sequence()`（太重且靠 pixel check），改用精簡的 `resume_mining()`：
直接按 "1"（D3→D1 安全切換）→ settle(0.4s) → key_down("w") → mouse_down()。

---

## 2. find_tracker（2026-06-28 改混合方案：HSV 定位 + 實機裁圖形狀確認）

`vision.find_tracker(frame_bgr, margin_frac, exclude, log, reference_bgr, shape_templates, shape_threshold, shape_scales, shape_roi_px)`

> **本次大改（修 very_rare.png「有礦卻沒發現」）**
> - **根因**：舊 colored 確認 `(S>90)&(V>90)&((H<35)|(H>95))` 排除 H35-95 黃綠帶 → 黃綠中心礦（Ionized）colored=0 漏抓。**已修為色相無關** `(S>90)&(V>90)`（純 HSV 即命中 (1231,644)）。
> - **混合偵測**：HSV 快速找候選（~246ms）後，在候選周圍小 ROI 跑「實機裁圖外框」形狀比對（+~65ms）確認，拒「有色但非追蹤框形狀」假陽性（如裝備誤射 (990,665)）。`cfg.tracker_shape_confirm` 控制；無實機裁圖時自動退回純 HSV。
> - **模板要用實機裁圖、非 wiki**：wiki 透明圖（alpha 外框）向量邊緣在合理尺度配不到遊戲內渲染框（實測全 miss，只在 scale 0.2 噪點假命中）；實機裁圖 edge≈0.91 且跨階通用（顏色無關，色相位移仍命中）。形狀確認集 = `assets/markers` 內無 alpha 的裁圖（自動篩）。已有 `transcendent_tracker_real.png`、`exotic_tracker_real.png`；其餘階級從 `logs/snapshots` 裁框補上。
> - 全幀模板比對太慢（2 張 5.7s／9 張 23.5s 每幀）→ 只在小 ROI 跑。

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

### 自動錄音

每次 chill 觸發時，自動存 1.5s 音訊緩衝到 `logs/snapshots/chill_audio_*.wav`。
用途：累積樣本 → 比較環境差異 → 重錄更準的 reference WAV。

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

### 🔴 偵測可靠性（直接影響採集成功率）

**A. 缺少其他階級的實機裁圖**
- 目前只有 Exotic (26×25) + Transcendent (32×32) 兩張模板
- 缺：Enigmatic / Exquisite / Exclusive / Unfathomable / Otherworldly
- Soft filter 已確保不漏抓（shape 不過退回 HSV），但精度降低
- **解法**：每次採集時從 `sweep_confirmed_*.png` 截圖手動裁新模板 → 放入 `assets/markers/<tier>_tracker_real.png`

**B. Shape ROI 過大（160px）**
- D3 採集瞬間 ROI 內充滿角色身體 / 礦塊稜線 / 動畫特效 → Canny 產生數十條雜訊邊緣
- signal-to-noise 比低，shape score 被稀釋
- **解法**：縮小 `shape_roi_px` 到 80px，或在 ROI 內先做 HSV mask 隔離追蹤框區域再跑 Canny

**C. 採集時追蹤框被部分遮擋**
- 角色 / 礦塊可能擋住追蹤框的箭頭尖端 → shape score 下降
- 目前靠 soft filter 緩解（遮擋嚴重時退回 HSV）
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
