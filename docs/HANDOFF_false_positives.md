# 追蹤框誤判問題 — 技術調查報告

> 本文聚焦單一問題：`find_tracker` 將「不是追蹤框的東西」判定為追蹤框，導致 D3 對著空氣開火。
> 完整調查發現 **三層獨立 root cause** 疊加，每一層都讓誤判漏到下一層。
> 最後更新：2026-06-29（153 tests passed；hard_floor 0.25→0.30 擋 borderline 裝備誤射；補 exquisite 綠框實機模板）

---

## 0. 快覽：三層 Root Cause

| # | Root Cause | 影響 | 發現方式 | 修法 |
|---|---|---|---|---|
| 1 | **模板檔案本身錯誤** | shape-confirm 用錯誤模板比對 → 精度歸零 | vision-debugger 逐張看圖 + pairwise MSE | 換成正確實機裁圖 |
| 2 | **Soft filter 翻盤** | shape-confirm 正確拒絕（edge=0.16）→ soft filter 卻退回 HSV 救回來 | `_diag_tracker.py` 印出 edge score | 加 `hard_floor` 三區判定 |
| 3 | **Sweep verify fallback** | verify return None（正確拒絕）→ code 卻回傳掃描時舊位置 | harvest.log 比對「shape全數<硬下限」vs「用掃描時位置」 | return None 取代 return best_pos |

---

## 1. 防線架構（當前狀態）

追蹤框偵測是一條 **六層管線**，每一層都可能漏掉或放行誤判。以下是修復後的完整架構：

```
D2 掃描後的遊戲幀
    │
    ▼
┌─ 層 1：HSV 顏色定位 ─────────────────────────────────────────┐
│  4 個 hue range 獨立偵測（range0: H18-78, range1: H88-130,  │
│  range2: H118-165, range3: H153-179）                        │
│  每個 contour 過濾：area 400-5000、bbox 18-80px、長寬比 < 1.5 │
│  → 通過的進入層 2                                            │
└───────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 層 2：ring_score 環形結構 ────────────────────────────────┐
│  ring_score = frame_fill - inner_fill（縮 30% 取中心區）     │
│  ring_score < 0.15 → reject（not_ring）                     │
│  → 排除實心 blob（礦石本體、岩壁色塊）                       │
└───────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 層 3：reference_bgr 差分 ────────────────────────────────┐
│  ref_fill = 掃描前 reference 幀同位置的顏色覆蓋率             │
│  ref_fill > 0.15 → reject（preexist）                       │
│  → 排除掃描前就存在的彩色物件（角色裝備、UI 元素）            │
│  注意：reference_bgr=None 時此層跳過（NEEDS_HUMAN 裁圖等）    │
└───────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 層 4：colored 中心確認（色相無關）─────────────────────────┐
│  colored = (S > 90) & (V > 90)                              │
│  colored_frac > 0.50 → accept                               │
│  或 dark > 0.10 且 colored_frac > 0.04 → accept              │
│  → 排除暗色 UI 面板（dark 高但 colored≈0）                    │
│  → 2026-06-28 修：舊版排除 H35-95 黃綠帶 → Ionized 漏抓       │
└───────────────────────────────────────────────────────────┘
    │ HSV 候選（candidates list）
    ▼
┌─ 層 5：Shape 確認三區判定（hard_floor）─────────────────────┐
│  對每個 HSV 候選，在其周圍 shape_roi_px(160) 的 ROI 上跑      │
│  best_outline_score（Canny 邊緣 vs 實機裁圖模板，多尺度）     │
│                                                              │
│  edge ≥ threshold(0.45)         → confirmed（返回此候選）     │
│  hard_floor(0.25) ≤ edge < thr  → survivor（退回 HSV 安全校） │
│  edge < hard_floor(0.25)        → hard_rej（完全移除，不救）  │
│                                                              │
│  → confirmed 有 → 返回最高 edge 的                           │
│  → 無 confirmed 但有 survivor → soft filter 退回純 HSV       │
│  → 全部 hard_rej → return None（判定無追蹤框）               │
└───────────────────────────────────────────────────────────┘
    │ find_tracker 返回 (x,y) 或 None
    ▼
┌─ 層 6：Sweep verify + 雙幀穩定（呼叫端）───────────────────┐
│  掃描時 m1 = find_tracker(grab())                            │
│  sleep(0.08)                                                 │
│  m2 = find_tracker(grab())                                   │
│  abs(m1-m2) < 8 → 穩定候選                                   │
│                                                              │
│  旋回最佳方位後驗證：                                         │
│  vm = find_tracker(grab())                                   │
│  vm ≈ best_pos → TRACKER_FOUND                               │
│  vm 有但偏移 → 用新位置                                       │
│  vm = None → return None（重試或交人工）← 2026-06-28 修       │
└───────────────────────────────────────────────────────────┘
```

---

## 2. Root Cause #1：模板檔案本身錯誤

### 發現過程

vision-debugger 逐張檢查 `assets/markers/` 內的 PNG 後發現：

| 檔案 | 問題 | 證據 |
|---|---|---|
| `transcendent_tracker_real.png`（32×32） | **L 角框 + 右箭頭**——不是追蹤框的形狀 | 使用者確認；正確版本是 `_old_61x57.png`（四向星）|
| `exotic_tracker_real.png`（26×25, 342b） | **合成佔位圖**——純色塊、無抗鋸齒、無輪廓 | pairwise MSE vs `exotic_real_big.png` corr=**0.998**（同一張圖的縮圖）|

### 驗證方法

1. **Pairwise MSE + 相關係數**（80×80 正規化）：
   - `current_real` vs `exotic_real_big`（合成圖）：MSE=17.8, corr=**0.998** → 幾乎相同 → current 就是 synth_big 的縮圖
   - `exotic_ref_120` vs `current_real`：MSE=11199, corr=0.361 → 完全不同 → ref 不是從合成圖來的
2. **內容統計**：synth_big/current_real 的 purple%=44%、yellow%=55%、darkred_bg%=**0%**（純色塊填滿、無背景）；ref_120/ref_80 有紅色洞穴背景（真實裁圖）
3. **Canny hard_edge_ratio**：synth_big **0.822**（硬邊=合成）；ref ~0.46-0.60 vs tran_real 0.43（同為真實渲染區間）
4. **look_at 視覺確認**：ref_80 有紋理背景+抗鋸齒+漸層框（真實遊戲渲染）

### 修法

- `transcendent_tracker_real.png`：刪除錯誤 32×32 → rename `_old_61x57.png` 為正式檔名
- `exotic_tracker_real.png`：用 `logs/exotic_ref_120.png`（真實 120×120 切角方框+紫心）覆蓋

### 影響範圍

模板錯誤時，shape-confirm 的 `best_outline_score` 用錯誤模板比對 → 分數不可信。但因為 soft filter 的存在（見 RC#2），即使 shape 分數全錯，HSV 候選仍會被退回 HSV 救回來——**模板錯誤不會直接造成漏抓，但會讓 shape-confirm 完全失去過濾能力**。

---

## 3. Root Cause #2：Soft filter 翻盤

### 發現過程

用升級後的 `_diag_tracker.py` 對 015044 裝備誤射幀跑完整診斷：

```
015044 裝備 @(990,665):
  HSV 階段:  colored=0.84 in_area=True -> OK（通過）
  shape階段: edge=0.16 -> rej（正確拒絕，遠低於 0.45 門檻）
  soft filter: shape全部不過，退回純 HSV（candidates=1）← 翻盤
  ==> selected: (990,665)  ← 最終誤判
```

**shape-confirm 運作正確**（edge=0.16 → rej），**但 soft filter 把拒絕推翻了**。

### 根因分析

舊版 `vision.py` shape 確認是**二區判定**：
```
edge ≥ threshold → confirmed
edge < threshold → 全部退回 HSV（soft filter）
```

設計意圖：「shape 全不過但 HSV 有候選 → 可能是未見過的階級（模板配不到）→ 退回 HSV 怕漏抓」。

問題：這個安全網同時放行了「HSV 強但形狀完全錯」的裝備誤判。裝備的 `colored=0.84`（HSV 很強）但 `edge=0.16`（形狀全錯）→ soft filter 救回來 → 誤判。

### 實證分離

測量多個合成模板對 `_draw_tracker`（30px 合成追蹤框）的 edge score：

| 模板 | score | 區間 |
|---|---|---|
| circle_ring_14 | **0.175** | ← hard_reject（跟裝備 0.16 幾乎相同）|
| square_outline_30 | **0.358** | survivor（borderline，未見階級的合理代理）|
| square_outline_20 | 0.466 | confirmed |
| square_filled | 0.706 | confirmed |

**關鍵發現**：circle 對真追蹤框的 score（0.175）幾乎等於裝備誤判的 score（0.16）。兩者無法用 hard_floor 區分。但這沒關係——circle 是「幾何形狀全錯」的代理，**真未見階級的追蹤框**（同屬追蹤框形狀家族）會 scored ~0.3-0.5（如 square_outline_30 = 0.358），遠高於裝備的 0.16。

### 修法：三區判定

`config.py` 加 `tracker_shape_hard_floor: float = 0.25`

`vision.py` find_tracker shape 確認改三區：

```python
edge ≥ threshold(0.45)          → confirmed
hard_floor(0.25) ≤ edge < thr   → survivor → soft filter 退回 HSV
edge < hard_floor(0.25)         → hard_rej（完全移除，soft filter 不救）
```

- confirmed 有 → 返回最高 edge
- 無 confirmed 但有 survivor → soft filter（保留未見階級安全網）
- 全部 hard_rej → return None

### 測試

- `test_find_tracker_hybrid_hard_floor_rejects_wrong_shape`：circle（0.175 < 0.25）→ None ✅
- `test_find_tracker_hybrid_shape_soft_filter_falls_back_to_hsv`：square_outline_30（0.358 ≥ 0.25）→ HSV fallback ✅
- `test_find_tracker_hybrid_rejects_equipment_false_positive`：015044 實機幀 → None ✅

---

## 4. Root Cause #3：Sweep Verify Fallback

### 發現過程

兩次 chill 事件（20:50、22:42）的 HARVEST_SUCCESS 都 `confirmed=False`：

| 時間 | target | found_before→after | 問題 |
|---|---|---|---|
| 20:50 | (965, 960) | 2→0 | 數字減少 = 假成功 |
| 22:42 | (907, 949) | 2→2 | 不變 = 假成功 |

harvest.log 的關鍵兩行：

```
22:42:50  shape全數 < 硬下限 0.25，判定無追蹤框          ← hard floor 正確拒絕（RC#2 生效）
22:42:50  sweep: 最佳方位追蹤框消失，用掃描時位置 (907, 949)  ← 但 code 還是用舊位置 D3！
```

### 根因

`_sweep_for_tracker` 的 verify step（`main.py:762-777`）：

```python
vm = self._find_tracker(verify_f, excl, ref, log=self._tracker_log)
if vm and abs(vm[0] - best_pos[0]) < 30 ...:   # 驗證成功
    return vm
elif vm:                                        # 位置偏移
    return vm
else:                                           # vm = None（驗證失敗）
    return best_pos   # ← BUG：回傳掃描時舊位置
```

verify 的 find_tracker return None（hard floor 正確拒絕所有候選），但 `else` branch 回傳 `best_pos`（掃描時的位置）→ D3 射向不存在的外框。

### 修法

```python
else:
    self.log_harvest.info("sweep: 驗證時追蹤框消失（掃描位置 %s 未通過 verify），重試", best_pos)
    return None   # 不再用 best_pos → 觸發 sweep_attempts++ → 2 次失敗 → NEEDS_HUMAN
```

### 影響

修前：verify 拒絕 → 仍 D3 開火 → 假成功（角色對著空氣採集）
修後：verify 拒絕 → return None → 重試 → 2 次失敗 → **NEEDS_HUMAN**（交人工）

---

## 5. 三層防線如何疊加漏掉誤判

RC#1 + RC#2 + RC#3 的疊加效應：

```
裝備誤判產生 HSV 候選（colored=0.84）
    │
    ├─ 層 5 shape 確認：
    │    ├─ RC#1：模板錯誤 → best_outline_score 不可信（可能偏高或偏低）
    │    └─ RC#2：即使 score 偏低被 rej → soft filter 翻盤 → HSV 候選救回來
    │
    ├─ 層 6 sweep verify：
    │    └─ RC#3：verify 拒絕 → 但 code 用舊位置 → D3 開火
    │
    └─ 結果：D3 射向裝備 → 假成功
```

**修復後**：
- RC#1 修 → shape-confirm 用正確模板 → score 可信
- RC#2 修 → hard_floor 擋下 edge<0.25 的裝備候選
- RC#3 修 → 萬一前兩層都漏了，verify 拒絕 → return None → 不 D3 → 重試/交人工

三層修復形成 **defense in depth**：即使某一層失效，下層仍能攔截。

---

## 6. 診斷工具與工作流程

### `_diag_tracker.py`（logs/ 內，已升級）

事後對任何 snap shot 幀重跑 find_tracker 完整候選 log：

```bash
# 預設幀（Exotic 驗證幀）
python logs/_diag_tracker.py

# 指定幀 + 載入實機模板
python logs/_diag_tracker.py logs/snapshots/<file>.png

# 只看 HSV 階段（不跑 shape）
python logs/_diag_tracker.py logs/snapshots/<file>.png --no-shape
```

輸出格式：
```
tracker候選 (1238,232) area=787 fill=0.27 dark=0.15 colored=0.84 in_area=True -> OK
shape確認 (1238,232) colored=0.84 edge=0.81 floor=0.25 thr=0.45 -> OK
==> selected: (1238, 232)
```

### harvest.log 關鍵欄位

```
shape確認 (x,y) colored=C edge=E floor=0.25 thr=0.45 -> OK/soft/hard_rej
shape全數 < 硬下限 0.25，判定無追蹤框           ← 所有候選被 hard_rej
shape未確認但 edge≥0.25，退回純 HSV（survivors=N）← soft filter
sweep: 驗證時追蹤框消失（掃描位置 (x,y) 未通過 verify），重試  ← RC#3 修後
```

### NEEDS_HUMAN 裁圖

NEEDS_HUMAN 時自動跑 find_tracker → 找最高 edge 候選 → 裁 240×240 + 黃框標註 + edge 分數 → 存檔 + Discord。比全螢幕更能當參考：直接看到「bot 認為最像外框的東西是什麼」。

### 診斷步驟（未來誤判發生時）

1. 看 miningbot.log 的 `HARVEST_SUCCESS confirmed=? found_before→after`：confirmed=False 或 found 減少 = 可疑
2. 找對應的 `sweep_confirmed_*.png` 或 `d3_fire_*.png`
3. 跑 `python logs/_diag_tracker.py logs/snapshots/<file>.png` 看 shape score
4. 如果 edge 在 [0.25, 0.45) → borderline survivor（考慮調 hard_floor 或加模板）
5. 如果 verify 有/無 → 看 harvest.log 的「驗證成功/消失」訊息

---

## 7. 已知殘餘風險

### A. Borderline edge score（0.25-0.30 區間）— ✅ 2026-06-28 已處理

夜間兩次裝備誤射都落在此邊界帶：

| 時間 | 誤射位置 | edge | colored | 命中物 |
|---|---|---|---|---|
| 20:50 | (965,960) | **0.25**（正好＝floor）| 0.44 | 角色橘紅裝備 |
| 22:42 | (907,949) | **0.26** | 0.71 | 角色橘紅裝備 |

對照同期真追蹤框：19:38 (953,529) edge=**0.44**、20:21 (794,532) edge=**0.57-0.63**（皆 colored=1.00）。
→ 裝備帶 ≤0.26 與真追蹤框帶 ≥0.44 之間有 0.18 的大空隙。

**修法**：`tracker_shape_hard_floor` 由 0.25 → **0.30**（落在空隙中）。擋下 0.25/0.26 裝備誤射，
保留真追蹤框（≥0.44）與未見階級外框代理（square_outline_30=0.358）。
回歸測試 `test_hard_floor_separates_equipment_band_from_real_trackers` 鎖定 `floor ∈ (0.26, 0.358]`。

**成因＝sweep 漏抓真框、誤收裝備（非彈窗）**：兩次誤射幀雖都有「Affement [1/2]」craft 彈窗開著，
但**已量測排除彈窗為因**——D2 掃描固定點擊**螢幕正中心 (960,540)**（`harvester.execute_scan`），
而彈窗在畫面左側右緣 ≲x=520，裁 x=520→960 帶狀區內無彈窗、中心點落在角色臉部，彈窗**沒蓋到掃描點擊**。
真實成因：該事件真礦物不在 sweep 範圍內 → 8 方位都沒掃到真追蹤框 → 只剩角色自身高飽和橘紅裝備
當候選 → edge 0.25/0.26 被舊 soft filter 救回 → 誤射。hard_floor 0.30 直接擋下此裝備帶，對症。

### B. 缺少其他階級實機裁圖（部分補齊）

**追蹤框外框 = 中央方框 + 各階獨特彩色星芒/暈**（wiki 圖可見 7 階形狀各不同；shape 確認顏色無關，
比的是 Canny 外框）。實機目前只拍到 3 階，皆已有實機裁圖模板（2026-06-29）：

| 階級 | 外框形狀 | 模板 | 實機驗證 edge |
|---|---|---|---|
| Exotic（金黃）| 正方形混菱形（方框＋菱形柔光暈）| `exotic_tracker_real.png`(120²) | 0.63-0.81 |
| Exquisite（綠）| 方框 + 四角綠芒（內凹四尖角，**非純方框**）| `exquisite_tracker_real.png`(68²，2026-06-29 補) | 0.55-1.00 |
| Transcendent（藍）| 4 角星 | `transcendent_tracker_real.png`(61×57) | 0.54 |

補 exquisite 後，綠階真框由 survivor(0.42-0.46) 升 confirmed(0.55-1.00)，EQUIP_990 維持 0.163 hard_rej。

仍缺 4 階實機裁圖（**wiki 圖配不到遊戲渲染框，無法當模板**，須等實機拍到從 sweep_confirmed 裁）：
Enigmatic（黃綠 8 角芒）/ Exclusive（紫 6 角星）/ Otherworldly（暗紅花瓣）/ Unfathomable（藍 8 角羅盤星）。
這 4 階出現時 shape 確認配不到 → 退回純 HSV（hard_floor 0.30 仍擋裝備誤判）。新階補法：
`grep sweep_confirmed` 找該階座標 → 從幀裁 ~68px 緊框 → 存 `assets/markers/<tier>_tracker_real.png`（3 通道無 alpha 即自動載入）。

### C. Shape ROI 過大（160px）

D3 採集瞬間 ROI 內充滿角色身體/ 礦塊稜線/動畫特效 → Canny 雜訊邊緣多 → shape score 被稀釋。可能讓真追蹤框的 score 降到 borderline 區間。

**解法（未實施）**：縮小 `shape_roi_px` 到 80px，或在 ROI 內先做 HSV mask 隔離追蹤框區域再跑 Canny。

### D. reference_bgr=None 時層 3 跳過

NEEDS_HUMAN 裁圖、_diag_tracker.py 預設等情境不傳 reference_bgr → 掃描前已存在的彩色物件（裝備）不被差分過濾。生產 sweep 有傳 reference_bgr 所以不受影響。

---

## 8. 相關設定一覽

| 設定 | 預設 | 位置 | 說明 |
|---|---|---|---|
| `tracker_shape_confirm` | True | config.py | 開啟形狀確認（需 assets/markers 內有實機裁圖）|
| `tracker_shape_threshold` | 0.45 | config.py | confirmed 門檻（edge ≥ 此值 → 確認）|
| `tracker_shape_hard_floor` | 0.30 | config.py | 硬下限（edge < 此值 → 硬拒不救）；2026-06-28 由 0.25→0.30 擋 borderline 裝備誤射 |
| `tracker_shape_scales` | (0.7, 1.0, 1.4) | config.py | 多尺度比對 |
| `tracker_shape_roi_px` | 160 | config.py | 候選周圍裁 ROI 大小 |
| `audio_match_threshold` | 0.30 | config.py | chill 觸發門檻 |
| `sweep_timeout_s` | 30.0 | config.py | 全方位掃描階段時限 |
| `max_harvest_attempts` | 5 | config.py | D3 連續未命中上限 |

---

## 9. 測試覆蓋

| 測試 | 鎖定的不變量 |
|---|---|
| `test_find_tracker_hybrid_detects_real_marker` | very_rare.png（真 Transcendent）→ 命中 (1230,643) ±40 |
| `test_find_tracker_hybrid_rejects_equipment_false_positive` | 015044 裝備幀 → None（hard floor 擋下）|
| `test_find_tracker_hybrid_hard_floor_rejects_wrong_shape` | circle（edge≈0.18 < floor）→ None |
| `test_find_tracker_hybrid_shape_soft_filter_falls_back_to_hsv` | square_outline（edge≈0.36 ≥ floor）→ HSV fallback |
| `test_find_tracker_no_shape_templates_is_pure_hsv` | 無模板 → 純 HSV（向後相容）|
| `test_hard_floor_separates_equipment_band_from_real_trackers` | hard_floor ∈ (0.26, 0.358]：擋裝備帶(≤0.26)、保真追蹤框帶(≥0.44) |
| `test_find_tracker_hybrid_detects_exquisite_green_marker` | exquisite 綠框（方框+四角綠芒）→ 命中 (918,305)（補 exquisite 模板後）|
