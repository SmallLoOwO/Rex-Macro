# 接手 Handoff — REX 挖礦自動化

> 先讀 `CLAUDE.md`（含實機踩過的坑），再看本檔。  
> 分支：`feature/window-discord-controls`（`python -m pytest -q` → 105 passed）

---

## 0. 快覽

| 項目 | 狀態 |
|---|---|
| 穩定挖礦 / 補 boost / D4 / Discord 通知 / 重置等人工 | ✅ 正常 |
| 全 8 方位掃描採集 稀有礦（HARVESTING 流程） | ✅ 實機驗證成功（2026-06-27） |
| find_tracker 三層過濾（ring_score + reference_bgr + 雙幀穩定） | ✅ 105 測試綠 |
| chill 音訊偵測（bot 進入 HARVESTING 的觸發） | ⚠️ 尚未重新驗證（見 §3） |
| D2 掃描成功驗證（"Local" 標籤出現） | ⚠️ 尚未實作 |

---

## 1. 採集架構（完整流程）

```
chill 觸發 HARVESTING
    │
    ▼
prepare_scan()         ← 停止移動、置中鏡頭
    │
    ▼
截 pre_scan_ref        ← reference！置中後才截（裝備位置穩定）
    │                    在 execute_scan 前截——排除「D2 光效假陽性」
    ▼
execute_scan()         ← 裝備 D2、click 中央觸發掃描、wait 1.5s
    │
    ▼
_sweep_for_tracker()   ← 全 8 方位旋轉掃描
    ├─ rotate_right × 7（0→7，共 315°）
    ├─ 每方位：find_tracker（含三層過濾）→ 雙幀穩定確認（0.08s，誤差<8px）
    ├─ 記錄所有穩定候選 → 選最佳（第一個）
    └─ rotate_left 旋回該方位 → 驗證仍在 → 回傳座標
    │
    ▼
D3 射擊
    ├─ key_press("2")   ← toggle 防呆（避免 D3 已裝備再按 3 = 卸下）
    ├─ sleep(0.15)
    ├─ key_press("3")   ← 裝備 D3
    ├─ sleep(0.6)       ← 等裝備動畫（不等 = 被吃掉）
    ├─ click_at(cx, cy, hold=0.4)  ← D3 以點選位置瞄準（非 crosshair）
    └─ sleep(1.0)       ← 等伺服器回應（< 1.0s 截圖 = 框還在消失動畫中）
    │
    ▼
確認
    ├─ gone:      find_tracker(after) is None
    ├─ confirmed: 聊天差分（has_new_found / has_new_found_last_line）
    └─ 成功 → restore_view(net_rotations) 轉回原視角
```

---

## 2. find_tracker 三層過濾

`vision.find_tracker(frame_bgr, margin_frac, exclude, log, reference_bgr)`

### 層一：ring_score 環形結構
```python
ring_score = frame_fill - inner_fill  # inner = 縮 30% 中心區
if ring_score < 0.15: reject          # cave wall blob ≈ 0；真 tracker ≈ 0.5
```
**Why:** cave wall（紫色/暗色均勻色塊）`inner_fill ≈ frame_fill → ring_score ≈ 0`。  
真實追蹤框的中心是黑色或礦物填色（不在當前顏色 range），`inner_fill ≈ 0 → ring_score ≈ 0.5`。

### 層二：reference_bgr 差分
```python
ref_fill = mean(ref_mask[bbox])
if ref_fill > 0.15: reject  # 掃描前就已存在 → 非追蹤框
```
**Why:** 礦石本體在 D2 掃描前就可見，裝備（D2 裝備後才出現光效）要靠 prepare/execute 分離排除。  
**reference 截取時機**：`prepare_scan()` 置中後、`execute_scan()` 裝備 D2 前。

### 層三：雙幀穩定（調用端實作）
```python
# 在 _sweep_for_tracker 和 _tick_harvest 內
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
| range3 | H 153–179 | Otherworldly（H≈167）；**紅色礦坑環境效果差** |

**Exotic 實測（外框是唯一絕對依據）**：H=23, S=189, V=230（wiki 與實機完全一致）。  
中心色隨礦物種類而變，礦坑背景色也會變——兩者均不可作為偵測依據。

---

## 3. ⚠️ 尚未解決的問題

### 3.1 chill 音訊偵測（最高優先）
- **症狀**：heartbeat 顯示 `audio=0.01`，但畫面正顯示 chill 提示 → bot 不進 HARVESTING
- **診斷方法**：heartbeat 加印原始 RMS（`np.sqrt(np.mean(buf**2))`）
  - RMS≈0 → loopback 死（裝置問題）
  - RMS 高但 score≈0 → 參考 wav 不符此環境
- **快速止血**：`cfg.chill_require_ocr=True` → 改用 OCR 抓「A chill goes down your spine」觸發
- **根本修法**：重錄此環境的 chill 音效 → `python -m miningbot.convert_audio "chill.mp3"`

> **注意**：本 session 採集測試是手動執行掃描腳本，**不是 bot 正常從 chill 觸發的路徑**。
> bot 主流程的 chill→HARVESTING 尚未端到端驗證。

### 3.2 D2 掃描成功驗證
- `execute_scan()` 之後目前沒有確認「Local」標籤是否出現
- 若掃描失敗（無彈窗時點到 UI，或 D2 冷卻中），bot 會傻乎乎地繼續掃 8 方位卻掃不到任何框
- **建議**：掃描後 OCR 確認左下 "Local" 文字；若沒出現 → 重試或 NEEDS_HUMAN

---

## 4. 驗證項目

1. `python -m pytest -q` → 105 passed（全部要綠）
2. **實機完整流程**：bot 正常跑 → 聽到 chill → 進 HARVESTING → 全方位掃 → 找到框 → D3 命中 → 採集成功
3. **chill 音訊**：heartbeat 的 `audio` score 在 chill 播放時應 ≥ 0.30

---

## 5. 排錯工具

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

# find_tracker 候選除錯（對已有截圖）
python -c "
import cv2
from miningbot.vision import find_tracker
img = cv2.imread('logs/x.png')
loc = find_tracker(img, log=print)
print('result:', loc)
"
```

- log：`logs/miningbot.log`（動作/狀態）、`logs/events.log`（結構化事件）、`logs/snapshots/`
- `config.log_level="DEBUG"` 看每幀細節
- Exotic 追蹤框實機截圖（25×26px）：`assets/markers/exotic_tracker_real.png`（本機，不進版控）

---

## 6. 其他待辦（低優先）

- D2 冷卻偵測（仿 D4 冷卻模板）
- 垂直追蹤框（仰角礦，目前只水平旋轉）
- 庫存數量 diff 驗證（需玩家提供礦物清單）
- D4 加強事件（左鍵）
