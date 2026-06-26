# 接手 Handoff — 重點：解決「稀有礦自動採集」

> 先讀 `CLAUDE.md`（含實機踩過的坑）、`docs/game-mechanics.md`。本檔記錄**目前進度**與**下一步**。
> 程式碼在分支 `feature/window-discord-controls`（多個 commit，`python -m pytest -q` 全綠）。

## 1. 現況：挖礦主流程穩定，採集已打通，偵測仍有誤判需修

實機跑得起來、會穩定挖礦/補 boost/刷 D4/聽 chill/重置等人工，Discord 會通知。
採集端到端已驗證（D2 掃→旋轉找框→D3 hold click → 礦物取得），但 `find_tracker`
在真實截圖中有誤判需修。

### 已完成並驗證
- **視窗/輸入基礎修復**：`_focus_roblox` 改 SW_MAXIMIZE；啟動先設 DPI-aware。
- **全域熱鍵**：GetAsyncKeyState 輪詢，Ctrl+Q/Q/F12 焦點在遊戲也有效。
- **D4 冷卻偵測**：偵測右下角「Used」圖示。
- **Discord 通知**：RARE_FOUND/HARVEST_SUCCESS/NEEDS_HUMAN/STUCK/MINE_RESET。
- **音訊門檻 0.30**（真實 chill ≈ 0.4）。
- **★ D3 採集端到端驗證（2026-06-27）**：`start_scan()` 按 2 + click 觸發 D2 →
  旋轉找 tracker → 按 3 等 0.6s → hold click 0.4s 在 tracker 螢幕座標 →
  框立即消失 = 成功，聊天框出現「has found」，礦物數量增加。
- **★ 多色 tracker 偵測結構（2026-06-27）**：`_TRACKER_COLORS` 涵蓋
  橘/黃/綠（H18-78）、藍（H88-130）、紫（H118-165）、暗紅（H153-179）四段，
  每段**獨立** findContours + 獨立計算 frame_fill（關鍵！見下一節）。
  77 個單元測試全綠（含 Exotic 橘、Transcendent 藍的新測試）。

## 2. ★ 多色偵測的核心踩坑（必讀）

### 背景情況

此遊戲礦坑環境是**大片高飽和粉紅背景**（H≈168，S≈251，V≈213），約佔畫面 77%。

```
rot_3.png 統計：
  range3 (H=153-179, S>100, V>50): 1,590,338 / 2,073,600 px (77%)
  range0 (H=18-78, S>80, V>50):       18,150 px (只有 tracker 框的綠)
```

### 已修正：per-range hollow check

舊寫法：把所有 `_TRACKER_COLORS` 合併成一個 `frame_mask`，用合併 mask 算 frame_fill。  
→ range3（H=153-179）把礦物填色（H=168）也抓進去 → bounding rect 裡 frame_fill=1.0 → hollow 檢查失敗。

**新寫法（現行）**：每個顏色範圍獨立跑 findContours，用**該顏色的 mask** 算 frame_fill：
```python
for lo, hi in _TRACKER_COLORS:
    color_mask = cv2.inRange(hsv, lo, hi)
    cnts, _ = cv2.findContours(color_mask, ...)
    ...
    frame_fill = float(np.mean(color_mask[y:y+bh, x:x+bw] > 0))
    # ↑ 只算這個顏色，不含其他顏色範圍的干擾
```

Exquisite 偵測結果：green mask frame_fill≈0.57 ✓（pink fill 在 H=168，不在綠色 mask）

### 仍存在的誤判（留給下個 session 修）

真實截圖 `logs/rot_3.png` 跑 `find_tracker(log=...)` 的輸出：

```
tracker候選 (1347,254) area=624  fill=0.57 dark=0.00 colored=1.00  -> OK  ← 真正的 tracker
tracker候選 (257,933)  area=2246 fill=0.43 dark=0.69 colored=0.00  -> OK  ← 左側 UI 面板誤判
tracker候選 (1004,693) area=975  fill=0.48 dark=0.00 colored=0.75  -> OK  ← 角色裝備區誤判
tracker候選 (955,684)  area=719  fill=0.41 dark=0.00 colored=0.88  -> OK  ← 角色裝備區誤判
```

目前程式選**最大 area**（2246），所以回傳的是 UI 面板，而非真正的 tracker（624）。

### 下個 session 要修的兩件事

**修 1：accept 條件過濾 UI 面板**  
左側面板（257,933）特徵：dark=0.69（有暗色文字背景）但 colored=0.00（沒有礦物填色）。
```python
# 現行（過寬）
accept = ... and (dark > 0.10 or colored_frac > 0.04)

# 改為（更嚴格）
accept = ... and ((dark > 0.10 and colored_frac > 0.04) or colored_frac > 0.50)
# → UI 面板：(0.69 AND 0.00<0.04)=False, 0.00<0.50=False → 排除 ✓
# → 真正 tracker：1.00>0.50=True → 通過 ✓
# → 合成測試 tracker：(0.65>0.10 AND 0.16>0.04)=True → 通過 ✓
```

**修 2：排名改用 colored_frac（最高優先）**
```python
# 現行（最大 area 優先）
if accept and (best is None or area > best[0]):
    best = (area, (cx, cy))

# 改為（最高 colored_frac 優先）
if accept and (best is None or colored_frac > best[0]):
    best = (colored_frac, (cx, cy))
return best[1] if best else None
```
→ 真正 tracker colored=1.00 > 角色裝備誤判 0.75-0.88 → 選對 ✓

**range3（暗紅 H=153-179）注意**：礦坑背景就是 H≈168，range3 在此環境幾乎無法可靠偵測
Otherworldly 階級。per-range 修完後 range3 的 contour 都被 area/shape 過濾掉，但若
未來礦坑換場景顏色，Otherworldly 才有機會偵測。目前不用特別處理。

## 3. 修完後要驗證的項目

1. `python -m pytest -q` 77 個測試全綠（修 accept 條件後合成測試要過）
2. 用 `logs/rot_3.png` 跑偵測，應回傳 (1347, 254)，不是 (257, 933)
3. 用 `logs/d3test_rot1.png` 跑偵測，應回傳 None（沒有 tracker 在畫面裡）
4. 用 `logs/rescan_init.png` 跑偵測，應回傳約 (1352, 256)

測試腳本：
```python
import cv2
from miningbot import vision
for label, path, expected in [
    ('rot_3', 'logs/rot_3.png', (1347, 254)),
    ('d3test_rot1', 'logs/d3test_rot1.png', None),
    ('rescan_init', 'logs/rescan_init.png', (1352, 256)),
]:
    img = cv2.imread(path)
    results = []
    m = vision.find_tracker(img, log=results.append)
    ok = (m is None) if expected is None else (m is not None and abs(m[0]-expected[0])<20)
    print('[' + ('OK' if ok else 'FAIL') + '] ' + label + ': ' + str(m))
    for r in results:
        if 'OK' in r: print('   ' + r)
```

## 4. 排錯工具
- **mss 截圖**：`python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/x.png', grab())"` → Read `logs/x.png`。
- **find_tracker 候選印出**：`vision.find_tracker(img, log=print)` 把每個候選的指標全印出來。
- **log**：採集流程已加 INFO log（`_tick_harvest`），`config.log_level="DEBUG"` 看更細。

## 5. 其他待辦（優先序較低）
- **掃描 8 幀無 tracker → NEEDS_HUMAN + Discord**：`harvest.rotations > max_aim_rotations` 已觸發 NEEDS_HUMAN，Discord 送通知，但需實機驗證流程。
- **D2 冷卻偵測**：可參考 D4 冷卻偵測（右下角模板），避免 D2 冷卻中又按 2。
- **垂直方向追蹤框**：目前只水平旋轉，仰角礦需滑鼠右鍵垂直拖曳（已有 `aim_move`，未整合）。
- **D4 加強事件（左鍵）**：使用者說之後再做。
