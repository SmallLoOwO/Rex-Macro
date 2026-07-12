# Capacity 監看＋近門檻加速的礦坑重置偵測

日期：2026-07-11　狀態：**已修訂（2026-07-12 addendum，見文末）**——capacity 觸發停機已移除

## Addendum 2026-07-12：機制事實修正——capacity 降級為加速/記錄信號

**本文件「Capacity 到 100% 觸發重置」的機制事實不成立**：玩家有 **Mine Capacity
升級（實機 300%）** 時，顯示值飽和在 100% 而礦坑遠未填滿。Capacity 是 bot 自己
挖出來的（單人）→ cap_trigger 在顯示 100% 就停挖＝容量永遠不再累積＝**死鎖在
RESET_WAIT**（2026-07-12 實錄：20:47 cap_trigger 停機後卡 1h47m+，礦坑始終未重置；
log `偵測到礦坑重置（Capacity 100% ≥ 100，連續2次）`）。這正是本文件自己警告過的
「提早停＝死鎖」，只是門檻被升級搬離了顯示 100%。

使用者裁決（2026-07-12）：**reset 橫幅是唯一停機條件**；capacity 只保留兩個角色：

1. **加速器**：≥`capacity_fast_from`（95→**99**）→ banner 輪詢 2.0s 加速到 0.5s，
   橫幅一出現 ~0.5-1s 內停（倒數 26s，綽綽有餘）＝「提高 reset 訊息優先級」的實作。
2. **記錄**：連續 2 次 ≥100 記一次 INFO（不停機）；飽和確認後跳過 capacity OCR
   （值已釘死，省一半 worker 開銷——飽和期間可能持續很久，不像原設計只撐幾秒）。

`update_capacity_streak` 純函式保留（消費者改為 log 去抖＋OCR 跳過閘）。
安全方向：移除假陽性觸發、banner 路徑不動＝最壞退回 2026-07-11 前行為，無新誤判面。

---

（以下為 2026-07-11 原設計，「觸發」一節已被 addendum 取代）

## 問題

現行重置偵測＝背景 worker（`main._banner_ocr_loop`）每 2s OCR 頂部橫幅找
`reset_phrases`。橫幅出現後最壞 ~2s＋OCR 不確定性才進 RESET_WAIT，倒數期間
bot 仍在挖 → 剛好挖出稀有礦觸發 chill → 採集一輪 ~30-60s，倒數內常來不及。

## 機制事實（使用者確認 2026-07-11＋實機快照證實）

- 頂部橫幅下方常駐一條「`Capacity: NNN% | Depth: NNNNm | $...`」文字列，
  位置固定（挖礦中與重置中皆在同位置）。
- Capacity 由玩家挖礦累積，**到 100% 觸發重置**，但實際重置在 100% 後
  一段時間（倒數期間仍可挖，Capacity 可過 100）。三張重置快照 Capacity
  皆 100-101% → 橫幅出現 ≈ Capacity 過 100。
- **Capacity 是 bot 自己填的（單人）**：<100% 就暫停＝杯子永遠不滿、
  重置永遠不來 → 死鎖。**不可做「提早暫停」**，只能「貼著 100% 瞬間停」。
- chill 優先級維持現狀（重置臨近 chill 照樣採，使用者選擇）。

## 已驗證的視覺事實（Claude 實測 2026-07-11，勿重推）

- 區域 `Region(715, 92, 200, 45)` 裁「Capacity: NNN%」段，真實 tesseract
  4/4 全對（101/14/101/100），暖機後 ~130-270ms/次。
- OCR 尾端會帶雜訊（`|` 或 `[`，pill 分隔線），解析要容忍。
- fixtures：`tests/fixtures/capacity/`（4 張實機裁圖）。

## 設計

全部掛在既有 `_banner_ocr_loop` worker（不動主迴圈節奏）：

1. **每輪多讀 Capacity**：裁 `capacity_region` → tesserocr →
   `ocr.parse_capacity_pct(text)`（純函式）→ 快取 `_capacity_pct`（HUD 顯示）。
2. **近門檻加速**：`_capacity_pct ≥ capacity_fast_from`(95) → 該 worker 的
   節流間隔從 `reset_check_interval_s`(2.0) 降為 `capacity_fast_interval_s`(0.5)
   （banner＋capacity 同輪加速）。
3. **觸發**：連續 2 次讀值 ≥ `capacity_reset_threshold`(100) → 與橫幅同效
   （`_mine_resetting=True` → MINING 中轉 RESET_WAIT）。**同輪與橫幅訊號 OR
   合併**（worker 對 `_mine_resetting` 是無條件賦值，不 OR 會被下一輪
   banner=False 蓋掉）。
4. **防誤觸**（假 RESET_WAIT＝停機成本高，寧漏勿誤）：
   - 連續 2 次 ≥ 門檻才觸發（雙次確認慣例）；解析失敗（None）沿用上次
     快取、streak 不推進不歸零（單次讀失敗不重計）。
   - 讀值 sanity range 0-150，超出視同解析失敗（防把 Depth/$ 誤讀成 pct）。
   - 回 MINING 入口（`_on_enter(MINING)` 清 `_mine_resetting` 處）同步清
     `_capacity_pct` 與 streak——重置後快取殘留 ≥100 會立即假觸發。
5. **橫幅路徑完全保留**：capacity OCR 全滅時行為與今日相同（純加法）。

### 新 config

```python
capacity_region: Region = Region(715, 92, 200, 45)  # Capacity: NNN% 段（2026-07-11 實測 4/4）
capacity_reset_threshold: float = 100.0   # ≥此值連續2次 → 視同重置
capacity_fast_from: float = 95.0          # ≥此值 worker 輪詢加速
capacity_fast_interval_s: float = 0.5     # 加速後間隔（平時沿用 reset_check_interval_s）
```

### 純邏輯（TDD）

- `ocr.parse_capacity_pct(text) -> float | None`：regex 抓 `(\d+(?:\.\d+)?)\s*%`，
  容忍尾端 `|`/`[` 雜訊；range 檢查 0-150。
- `states.update_capacity_streak(streak, pct, threshold) -> (new_streak, triggered)`：
  pct None → streak 原樣、不觸發；≥threshold → streak+1、達 2 觸發；<threshold → 歸零。
- fixture 測試比照 `tests/test_ocr_fixtures.py`：4 張裁圖過真實引擎鎖讀值。

### 不做（YAGNI）

- chill 壓制／倒數秒數解析（無消費者）／<100% 提早暫停（死鎖）。

## 效果

「倒數期間還在挖」窗口：最壞 ~2s＋橫幅 OCR 單點故障 → ~0.5-1s 且雙信號
互為後備（capacity 數字先到或橫幅先到都停）。
