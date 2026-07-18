# 2026-07-18 聊天框開啟檢查改版（H047）：圖示實心/空心信號＋toggle 安全

## 0. 委派注意（實作者必讀）

- **不要嘗試讀取任何 PNG 圖片內容**。所有 fixture 的量測數字都在本規格的表格
  裡；測試用 `cv2.imread` 載入後計算數字斷言即可，不需要目視。
- 不 commit、不切 branch、不刪 runtime 證據、不操作 Roblox/Discord。
- 完成後執行並確保通過：`uv run pytest -q`、`uv run ruff check . --no-cache`。
- 座標與門檻只放 `miningbot/config.py`；純決策不做 I/O。

## 1. 背景（一句話根因）

現行 `_ensure_chat_open`（`miningbot/main.py`）以 `chat_input_region` 的
placeholder 文字 OCR（"To chat click here / press / key"）判斷聊天框開關。但
REX 聊天框**開著且過久沒有訊息會把整個視窗自動隱藏**，placeholder 消失、該
區域只剩背包面板標題 → OCR 假陰性「關閉」→ 對 toggle 圖示連點奇數次，反而
把開著的聊天框關掉，之後整條聊天 verify 鏈瞎眼（2026-07-17 14:47 與
2026-07-18 02:15 兩場實機，聚焦成功 log＋終幀快照＋奇偶推理證實）。

## 2. 新信號（實機兩側夾）

左上聊天圖示（中心 `chat_icon_xy=(174,71)`）外觀隨狀態改變，且**任何狀態都
看得到**（不像輸入列會隱藏）：

- 開啟（含自動隱藏）＝**實心白**泡泡
- 關閉＝**空心白邊**泡泡，可能帶右上白色未讀數字徽章

判定量：40×40 裁圖（全幀座標左上 `(154,51)`）內取「泡泡內部補丁」
（crop 相對座標 `x∈[6,18)`、`y∈[21,28)`，位於泡泡左下內部，避開中央文字
筆劃與右上徽章區）的灰階平均值：

| 狀態 | 樣本 | 補丁 gray mean |
|---|---|---|
| 開啟 | 42 張已知開啟全幀（07-17 16:44~20:14、20:17~07-18 02:14） | 238..255 |
| 關閉 | 17 張已知關閉全幀＋2 張失敗終幀＋徽章「11」樣本 | 81..87（徽章樣本 83） |

Gap `[87, 238]`。門檻取：**≥180 判開、≤130 判關、中間 unknown**。

安全方向（比照 `_ensure_player_list_closed` 的「絕不按第二次 Tab」）：
**unknown 絕不點擊**。誤判開＝不點＝最多維持現狀；誤判關＝點下去會把開著
的聊天框關掉——後者才是破壞性動作，所以只在明確判「關」時才點。全白畫面
（重置白閃，實測開啟樣本出現過 255）會判「開」＝不點，方向安全。

## 3. Fixtures（已在 repo，40×40 BGR PNG）

| 檔案 | 狀態 | 預期分類 | 補丁 gray mean 實測 |
|---|---|---|---|
| `tests/fixtures/chat_icon/h047_icon_open_solid.png` | 開（自動隱藏中） | `"open"` | 239 |
| `tests/fixtures/chat_icon/h047_icon_closed_hollow.png` | 關（02:15 失敗終幀） | `"closed"` | 83 |
| `tests/fixtures/chat_icon/h047_icon_closed_hollow_badge11.png` | 關＋未讀徽章 11 | `"closed"` | 83 |

## 4. 變更清單

### 4.1 `miningbot/config.py`

新增（放在現有聊天框前置檢查欄位旁，附註解說明 H047 與兩側夾數據）：

```python
chat_icon_state_region: Region = field(default_factory=lambda: Region(154, 51, 40, 40))
    # 左上聊天圖示狀態判定框（H047：開=實心白泡泡、關=空心白邊；40x40 含整個圖示）
chat_icon_probe: tuple = (6, 21, 18, 28)
    # 泡泡內部補丁（crop 相對 x0,y0,x1,y1；左下內部，避開中央筆劃與右上未讀徽章）
    # 實測 gray mean：開 238..255（n=42）、關 81..87（n=19 含徽章）→ 兩側夾如下
chat_icon_open_min_gray: float = 180.0   # >= 判開
chat_icon_closed_max_gray: float = 130.0  # <= 判關；中間 unknown（白閃/亮景防呆，絕不點擊）
```

移除 `chat_input_region` 與 `chat_input_phrases`（舊 placeholder 信號退役，
全 repo 只有 `_ensure_chat_open` 引用；先 `rg chat_input_` 確認再刪，測試若
有引用一併更新）。保留 `chat_icon_xy`、`chat_open_settle_s`、
`chat_open_max_retries`（語意不變）。

### 4.2 `miningbot/vision.py` — 純函式：圖示狀態分類

```python
def chat_icon_state(icon_bgr, probe, open_min_gray, closed_max_gray) -> str:
    """聊天圖示開關判定（H047）。回 'open' | 'closed' | 'unknown'。

    icon_bgr：chat_icon_state_region 裁圖（BGR）。probe=(x0,y0,x1,y1) crop 相對。
    取 probe 補丁灰階平均：>=open_min_gray 開（實心白泡泡）、
    <=closed_max_gray 關（空心、內部暗）、其間 unknown（呼叫端不得點擊）。
    兩側夾：開 238..255 / 關 81..87（docs/incidents.md H047）。
    """
```

實作即灰階轉換＋補丁切片＋mean 比較，無其他相依。

### 4.3 `miningbot/roblox_menu.py` — 純函式：動作規劃

```python
def plan_chat_open_action(state: str, clicks_done: int, reads_done: int,
                          max_clicks: int, max_reads: int) -> str:
    """聊天框開啟檢查的下一步（H047）。回 'done' | 'click' | 'reread' | 'give_up'。

    state=='open'                                  -> 'done'
    state=='closed' and clicks_done < max_clicks   -> 'click'
    state=='closed'（點擊額度用盡）                 -> 'give_up'
    state=='unknown' and reads_done < max_reads    -> 'reread'（重抓幀再判，不點擊）
    state=='unknown'（重讀額度用盡）                -> 'give_up'
    其他 state 值                                   -> 'give_up'（防禦）
    """
```

### 4.4 `miningbot/main.py` — 改寫 `_ensure_chat_open`

I/O 編排（純決策全在上面兩個函式）：

```
clicks = reads = 0
while True:
    if self._env_check_skip("聊天框檢查"): return      # Q 跳過語意保留
    frame = capture.grab()
    crop = capture.crop(frame, cfg.chat_icon_state_region)
    state = vision.chat_icon_state(crop, cfg.chat_icon_probe,
                                   cfg.chat_icon_open_min_gray,
                                   cfg.chat_icon_closed_max_gray)
    action = roblox_menu.plan_chat_open_action(
        state, clicks, reads,
        max_clicks=cfg.chat_open_max_retries + 1, max_reads=3)
    'done'    -> log INFO「聊天框已開啟（圖示實心，probe=NNN）」return
    'click'   -> clicks >= 1 時先 self._focus_roblox()（重試前重新聚焦，現行對策保留）
                 ic.click_at(*cfg.chat_icon_xy); time.sleep(cfg.chat_open_settle_s)
                 clicks += 1; log INFO（第幾擊）
    'reread'  -> reads += 1; time.sleep(0.3); log DEBUG（unknown，重讀）
    'give_up' -> log WARNING（含 state 與 probe 值）；
                 self.last_action = "⚠ 聊天框未開啟，採集確認可能失效"
                 self._snapshot(frame, "chat_open_fail")；return
```

log 訊息帶上 probe 實測值（浮點一位）供事後 grep。通知分流**維持現狀**：
log＋HUD＋trace 快照，不上 Discord（使用者 2026-07-18 決定）。不再做任何
placeholder OCR——舊的 tesseract 呼叫整段移除。

### 4.5 測試（TDD：先寫紅燈再實作）

新檔 `tests/test_chat_icon.py`（或依 tests/AGENTS.md 慣例併入現有檔）：

1. **fixture 分類**：三張 fixture 各載入（`cv2.imread`）→
   `chat_icon_state(crop, DEFAULT.chat_icon_probe, ...)` 斷言分別回
   `"open"`／`"closed"`／`"closed"`。另斷言補丁值範圍（開 ≥230、關 ≤95）
   作為 fixture 完整性 sanity（數字見第 3 節表格）。
2. **合成邊界**：`np.full((40,40,3), v)` 灰值 v=255 → `"open"`（白閃安全方
   向）；v=150 → `"unknown"`；v=0 → `"closed"`（黑屏點擊無 UI 可點、無害，
   記錄行為即可）。
3. **plan_chat_open_action 全分支**：表格測試覆蓋第 4.3 節六個分支，特別
   斷言 `unknown` 在任何 clicks_done 下都不回 `'click'`（toggle 安全核心）。
4. **舊信號退役**：`rg "chat_input_region|chat_input_phrases"` 全 repo 無殘
   留引用（含 tests/）；相關舊測試改寫或移除。

### 4.6 不在本任務範圍

- `docs/incidents.md` H047 事故敘事與 CLAUDE.md 段落（由委派方事後撰寫）。
- 挖礦中／回礦中的聊天框狀態巡檢（本規格只改啟動前置檢查）。

## 5. 驗收

- `uv run pytest -q` 全綠、`uv run ruff check . --no-cache` 乾淨。
- 第 4.5 節測試先紅後綠（TDD 證據：實作前先跑一次確認紅燈）。
- 舊 `chat_input_*` 欄位與引用全數移除。
- 不 commit——完成後停在 working tree，由委派方審 diff。

## 6. 結案標準（實機，不在實作範圍）

下輪掛機啟動 log 預期出現
`UI 前置檢查：聊天框已開啟（圖示實心，probe=…）`（或明確判關後一擊即轉
實心）；不得再出現「仍未開啟，第 N 次重試」連鎖與奇數擊終態關閉。
