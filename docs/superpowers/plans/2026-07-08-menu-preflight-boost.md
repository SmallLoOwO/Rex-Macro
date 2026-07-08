# 選單前置切換＋UI前置檢查＋D5新顯示適配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 REENTRY 導航前後能自動切換 Roblox「Movement Mode」設定、啟動時自動確保聊天框開啟，並修正 D5 buff 偵測區/模板以適配遊戲更新後新增的永久計數圖示。

**Architecture:** 新模組 `miningbot/roblox_menu.py` 提供 OCR 錨定的選單決策純函式（找分頁/找標籤列/讀值/模糊比對，比照 `reentry.pick_layer_button` 的「嚴格贏過其他選項」寫法）；I/O 全部在 `Bot._set_movement_mode`/`Bot._ensure_chat_open`（比照 `main.py` 既有 `_tick_reentry`／`_harvest_giveup` 的「純函式決策＋方法做 I/O」慣例）。D5 偵測不改邏輯，只調 `config.boost_indicator_region` 排除新增的永久計數圖示、換新模板。

**Tech Stack:** Python 3.11、pytest、OpenCV（`cv2`，模板/邊緣比對）、RapidOCR（`ocr.read_text_boxes` 文字框，選單偵測與點擊座標依賴此路徑；未裝時該路徑回傳 `[]`，行為與現有 `reentry` 對 rapidocr 的依賴一致）、pydirectinput（鍵鼠模擬；本機版本**沒有** `scroll()`，見 Task 2）。

## Global Constraints

- **測試指令**：`python -m pytest -q`。每個 Task 做完，此指令必須全綠才算完成（除 `pytest.importorskip`/`skipif` 的環境相依測試，如 rapidocr/tesseract 未裝時允許 skip，不允許 fail）。
- **座標/門檻一律進 `miningbot/config.py`**：任何本計畫用到的螢幕座標、region、門檻、次數上限都以 `cfg.xxx` 形式讀取，不可寫死在函式內。
- **決策純函式與 I/O 分離**：能單測的邏輯（模糊比對、找標籤列、找值文字、判斷是否已達目標）一律寫成 `roblox_menu.py` 裡的純函式（吃資料回資料，不碰螢幕/鍵鼠）；I/O（截圖、點擊、按鍵、OCR 呼叫）只留在 `Bot` 的方法裡。這是本專案既有慣例（`reentry.py` 純決策 + `main.Bot._tick_reentry` 做 I/O），比照辦理。
- **寧漏勿誤**：任一步驟不確定（OCR 對不到、選單狀態不符預期）→ 回中性狀態（按 Esc）→ 依規格重試 → 仍失敗則明確回傳失敗信號交呼叫端分流（多半是 `NEEDS_HUMAN` 或啟動時記警告），絕不用「猜測」硬點下去。
- **`Bot` 的 I/O glue 方法（`_set_movement_mode`／`_ensure_chat_open`）比照現有 `_tick_reentry`/`_harvest_giveup` 慣例，不寫 mock 單元測試**——這類方法需要完整 `Bot()` 才能實例化（音訊/日誌/視窗等 I/O 初始化），本專案至今沒有任何測試直接 new 一個 `Bot()`。正確性由（a）其呼叫的純函式測試把關、（b）最後一個 Task 的實機驗證清單把關。
- **commit 訊息結尾**：`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- **分支**：目前在 `feature/optimization-roadmap`，直接在此分支續作、不用另開分支。
- **資產檔案是 gitignored**：`assets/*.png`、`assets/**/*.png`、`logs/` 整個資料夾都不進版控（見 `.gitignore`）。`tests/fixtures/**/*.png` **沒有**被排除、會進版控（比照既有 `tests/fixtures/chat/*.png`）。
- **本計畫依賴的既有截圖檔案**（2026-07-08 使用者實機截圖，已存在於工作目錄 `logs/`，但因 `logs/` 被 gitignore 不在版控裡——若這些檔案在執行環境中不存在，Task 3/7/8 的素材準備步驟會失敗，需請使用者重新截圖補齊，檔名可以不同但需重新量測座標）：
  - `logs/d5_before.png`、`logs/d5_active.png`、`logs/d5_expired.png`（D5 buff 三態，1920×1080 全螢幕截圖）
  - `logs/mm_cycle0.png`、`logs/mm_cycle1.png`（Settings 選單 Movement Mode 分別顯示 `Default (Keyboard)`／`Keyboard + Mouse`）
  - `logs/menu_settings1.png`（聊天框展開狀態，含輸入列文字）
  - 本計畫作者已用這些檔案實測驗證下列所有座標/門檻可行（非憑空估計）：`boost_indicator_region`、`boost_active.png` 裁切框、`chat_input_region`＋OCR 短語、`menu_panel_region`＋Settings 分頁/Movement Mode 列座標。

---

## Task 1: config.py 新增欄位

**Files:**
- Modify: `miningbot/config.py`（`boost_indicator_region` 定義約在第 34 行；在檔案「重置自動回礦」區塊後方新增一段新欄位，約第 176 行之後）
- Test: `tests/test_config_menu_fields.py`（新檔）

**Interfaces:**
- Produces（後續 Task 都直接讀取這些 `cfg.` 欄位，不重新定義）：
  - `cfg.boost_indicator_region: Region`（**改值**：從 `Region(1150, 935, 665, 135)` 改為 `Region(1150, 935, 590, 145)` —— 右緣縮到 x=1740（新永久計數圖示左緣）、下緣延到 1080）
  - `cfg.movement_mode_options: tuple[str, str, str]`
  - `cfg.movement_mode_mining: str`
  - `cfg.movement_mode_reentry: str`
  - `cfg.menu_panel_region: Region`
  - `cfg.menu_arrow_right_x: int`
  - `cfg.menu_value_column_x_range: tuple[int, int]`
  - `cfg.menu_row_y_tolerance_px: int`
  - `cfg.menu_scroll_xy: tuple[int, int]`
  - `cfg.menu_scroll_amount: int`
  - `cfg.menu_scroll_max_screens: int`
  - `cfg.menu_arrow_click_max: int`
  - `cfg.menu_arrow_settle_s: float`
  - `cfg.menu_open_settle_s: float`
  - `cfg.menu_close_settle_s: float`
  - `cfg.menu_fuzzy_min_ratio: float`
  - `cfg.menu_retry_max: int`
  - `cfg.chat_icon_xy: tuple[int, int]`
  - `cfg.chat_input_region: Region`
  - `cfg.chat_input_phrases: tuple[str, ...]`

**Steps:**

- [ ] 寫測試（新檔 `tests/test_config_menu_fields.py`）：

```python
"""選單前置切換／UI前置檢查／D5新顯示適配 的 config 欄位存在性與型別檢查。

這批欄位單獨開檔測試（而非散落在各功能測試裡斷言一次），因為 config.py 本身
不含邏輯，只有「有沒有定義、型別對不對」值得鎖——實際行為由消費這些欄位的
roblox_menu/vision/ocr 測試把關。
"""
from miningbot.config import DEFAULT as cfg
from miningbot.config import Region


def test_boost_indicator_region_excludes_permanent_counter_icon():
    # 2026-07-08 實機量測：永久計數圖示 bbox=(1740,1010,58,58)，右緣必須 <=1740 才不含它；
    # 下緣延到螢幕底 1080（原 1070 裁到圖示底）
    r = cfg.boost_indicator_region
    assert r.x + r.w <= 1740
    assert r.y + r.h == 1080


def test_movement_mode_options_are_three_known_values():
    assert cfg.movement_mode_options == (
        "Default (Keyboard)", "Keyboard + Mouse", "Click to Move")
    assert cfg.movement_mode_mining == "Default (Keyboard)"
    assert cfg.movement_mode_reentry == "Click to Move"
    assert cfg.movement_mode_mining in cfg.movement_mode_options
    assert cfg.movement_mode_reentry in cfg.movement_mode_options


def test_menu_panel_region_is_region():
    assert isinstance(cfg.menu_panel_region, Region)


def test_menu_numeric_fields_present_and_sane():
    assert cfg.menu_arrow_click_max >= 1
    assert cfg.menu_scroll_max_screens >= 1
    assert cfg.menu_retry_max >= 1
    assert 0.0 < cfg.menu_fuzzy_min_ratio <= 1.0
    assert cfg.menu_value_column_x_range[0] < cfg.menu_value_column_x_range[1]


def test_chat_input_region_and_phrases():
    assert isinstance(cfg.chat_input_region, Region)
    assert len(cfg.chat_input_phrases) >= 1
```

- [ ] 跑測試確認失敗（欄位還不存在）：
  ```
  python -m pytest tests/test_config_menu_fields.py -q
  ```
  預期：`AttributeError: 'Config' object has no attribute 'movement_mode_options'`（或類似，因欄位未定義）。

- [ ] 修改 `miningbot/config.py`：把 `boost_indicator_region` 那一行（目前是）：

```python
    boost_indicator_region: Region = field(default_factory=lambda: Region(1150, 935, 665, 135))
```

  改成：

```python
    # 右緣縮到永久計數圖示左緣(x=1740)、下緣延到 1080（2026-07-08 遊戲更新新增常駐計數圖示，
    # 舊區涵蓋到它 → 舊「瓶子在=生效中」邏輯永遠判生效、永遠不補 D5；見 boost_active.png 說明）
    boost_indicator_region: Region = field(default_factory=lambda: Region(1150, 935, 590, 145))
```

- [ ] 在 `miningbot/config.py` 檔案最後一段（`discord_poll_interval_s` 那行）之後、`DEFAULT = Config()` 之前，新增：

```python
    # 選單前置切換（Movement Mode）＋聊天框前置檢查
    # docs/superpowers/specs/2026-07-08-menu-preflight-boost-design.md
    movement_mode_options: tuple = ("Default (Keyboard)", "Keyboard + Mouse", "Click to Move")
    movement_mode_mining: str = "Default (Keyboard)"    # 挖礦用（兩個鍵鼠模式皆可，使用者確認取此值）
    movement_mode_reentry: str = "Click to Move"        # REENTRY 導航用（click-to-move 依賴此模式）
    menu_panel_region: Region = field(default_factory=lambda: Region(460, 130, 1000, 880))
        # Esc 選單面板整塊（分頁列 People/Settings/... ＋ 內容列表），OCR 找標籤/值/箭頭都在此裁圖裡做
        # （2026-07-08 實機驗證：People(576,156) Settings(774,156) Gallery(976,156) 等分頁文字，
        # Movement Mode 標籤(571,503)／值(1153,503) 皆落在此區內）
    menu_arrow_right_x: int = 1425       # 值列右箭頭 x（y 用該列 label 的 y；2026-07-08 實測 1423~1425）
    menu_value_column_x_range: tuple = (1000, 1350)   # 值文字欄 x 範圍（中心約 1153，三個值都置中對齊）
    menu_row_y_tolerance_px: int = 18    # 同一列判定的 y 容差（label 與 value 實測同列時 y 差 0~1px）
    menu_scroll_xy: tuple = (960, 500)   # 捲動前滑鼠停駐座標（面板中央）
    menu_scroll_amount: int = -3         # 每次捲動的滾輪格數（負=向下捲；WHEEL_DELTA=120/格）。
        # 方向依 Windows 滾輪慣例推斷、未經真實遊戲驗證——實機校準時若捲反了對調正負（見最後 Task）。
    menu_scroll_max_screens: int = 8     # 捲動找標籤上限（屏數）；Movement Mode 實測不捲動就找得到，
        # 此上限只是「遊戲改版把它挪到更下面」的防呆餘裕
    menu_arrow_click_max: int = 3        # 右箭頭最多點幾次（三值循環，最多 3 次必回到任意目標值）
    menu_arrow_settle_s: float = 0.3     # 點右箭頭後等值更新
    menu_open_settle_s: float = 0.3      # Esc/點分頁/點圖示後等畫面反應
    menu_close_settle_s: float = 0.3     # Esc 關閉後等選單收合
    menu_fuzzy_min_ratio: float = 0.6    # 標籤/值模糊比對下限（比照 reentry_button_min_ratio 精神）
    menu_retry_max: int = 1              # 整鏈失敗後重試次數（不含首次嘗試）

    chat_icon_xy: tuple = (174, 71)      # 左上聊天圖示（收合時點它展開；2026-07-08 實測座標）
    chat_input_region: Region = field(default_factory=lambda: Region(0, 355, 620, 55))
        # 展開後固定位置的輸入列「To chat click here or press / key」（2026-07-08 實機截圖量測＋
        # 真實 tesseract OCR 驗證過：開啟時讀到 "press / key"、收合時讀到雜訊不誤判）
    chat_input_phrases: tuple = ("to chat click here", "press / key")
```

- [ ] 跑測試確認通過：
  ```
  python -m pytest tests/test_config_menu_fields.py -q
  ```

- [ ] 跑全套測試確認沒改壞既有東西（`boost_indicator_region` 改值可能影響既有 boost 相關測試，若有 fail 屬預期——Task 7 會補新 fixture；若此刻有非 boost 相關測試 fail 才需要停下來查）：
  ```
  python -m pytest -q
  ```

- [ ] commit：
  ```
  git add miningbot/config.py tests/test_config_menu_fields.py
  git commit -m "$(cat <<'EOF'
  feat(config): 選單前置切換／聊天前置檢查／D5新顯示 新增設定欄位

  boost_indicator_region 右緣縮到新永久計數圖示左緣、下緣延到螢幕底；新增
  Movement Mode 切換與選單 OCR 錨點座標、聊天框輸入列偵測座標。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 2: input_control.py 新增 scroll()／move_to()

**Files:**
- Modify: `miningbot/input_control.py`（在 `mouse_move_rel` 後方新增，約第 47 行之後）
- Test: `tests/test_input_control.py`（新檔）

**Interfaces:**
- Produces: `input_control.scroll(clicks: int) -> None`、`input_control.move_to(x: int, y: int) -> None`
- Consumes: `ctypes.windll.user32.mouse_event`（win32 API；本機安裝的 pydirectinput **沒有** `scroll()` 函式——2026-07-08 已用 `python -c "import pydirectinput as p; print('scroll' in dir(p))"` 實測確認為 `False`，`dir(pydirectinput)` 裡只有 `moveTo/moveRel/click/keyDown/keyUp/...`，故改用 Windows 原生 `mouse_event(MOUSEEVENTF_WHEEL, ...)`，不要嘗試呼叫不存在的 `pydirectinput.scroll`）

**Steps:**

- [ ] 寫測試（新檔 `tests/test_input_control.py`）：

```python
"""input_control 新增 I/O 薄封裝的單元測試：用 monkeypatch 換掉底層呼叫，
斷言傳入的參數/呼叫次數正確（不實際發送輸入）。"""
import ctypes
from miningbot import input_control as ic


def test_scroll_sends_wheel_delta_down(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes.windll.user32, "mouse_event",
                        lambda flag, dx, dy, data, extra: calls.append((flag, dx, dy, data, extra)))
    ic.scroll(-2)
    assert len(calls) == 1
    flag, dx, dy, data, extra = calls[0]
    assert flag == ic._MOUSEEVENTF_WHEEL
    assert dx == 0 and dy == 0 and extra == 0
    assert data == -2 * ic._WHEEL_DELTA


def test_scroll_sends_wheel_delta_up(monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes.windll.user32, "mouse_event",
                        lambda flag, dx, dy, data, extra: calls.append((flag, dx, dy, data, extra)))
    ic.scroll(3)
    assert calls[0][3] == 3 * ic._WHEEL_DELTA


def test_move_to_calls_pydirectinput_moveto(monkeypatch):
    calls = []
    monkeypatch.setattr(ic.pydirectinput, "moveTo", lambda x, y: calls.append((x, y)))
    ic.move_to(500, 600)
    assert calls == [(500, 600)]
```

- [ ] 跑測試確認失敗：
  ```
  python -m pytest tests/test_input_control.py -q
  ```
  預期：`AttributeError: module 'miningbot.input_control' has no attribute 'scroll'`。

- [ ] 修改 `miningbot/input_control.py`：在檔案頂部 `import pydirectinput` 之後新增 `import ctypes`，在 `mouse_move_rel` 函式（第 45-47 行）之後新增：

```python
_MOUSEEVENTF_WHEEL = 0x0800
_WHEEL_DELTA = 120           # Windows 滾輪一格的標準單位

def scroll(clicks: int):
    """滑鼠滾輪捲動：clicks 正值向上捲、負值向下捲（Windows WHEEL_DELTA=120/格）。

    本機安裝的 pydirectinput 版本沒有 scroll()（2026-07-08 確認：dir(pydirectinput)
    只有 moveTo/moveRel/click/keyDown/keyUp 等，無 scroll），改走 win32 mouse_event
    直接送 MOUSEEVENTF_WHEEL——與 main.py 既有用 ctypes.windll.user32 做視窗操作同模式。
    呼叫前應先用 move_to() 把游標移到要捲動的區域上方（Windows 滾輪事件作用於游標所在視窗/控制項）。
    """
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, clicks * _WHEEL_DELTA, 0)
    time.sleep(_STEP)

def move_to(x: int, y: int):
    """移動滑鼠到絕對座標（不點擊）。給選單捲動/略過點擊的場景用。"""
    pydirectinput.moveTo(x, y)
    time.sleep(0.05)
```

- [ ] 跑測試確認通過：
  ```
  python -m pytest tests/test_input_control.py -q
  ```

- [ ] commit：
  ```
  git add miningbot/input_control.py tests/test_input_control.py
  git commit -m "$(cat <<'EOF'
  feat(input_control): 新增 scroll()/move_to()（選單捲動用）

  本機 pydirectinput 版本無 scroll()，改用 win32 mouse_event 送 MOUSEEVENTF_WHEEL。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 3: roblox_menu.py 純決策函式（新模組）

**Files:**
- Create: `miningbot/roblox_menu.py`
- Create: `tests/test_roblox_menu.py`
- Create: `tests/fixtures/menu/mm_cycle0.png`、`tests/fixtures/menu/mm_cycle1.png`（實機截圖裁圖，來源 `logs/mm_cycle0.png`／`logs/mm_cycle1.png`）
- Test: 上面兩個測試檔

**Interfaces:**
- Consumes: `ocr.read_text_boxes(image_bgr, region_offset=(0,0)) -> list[dict]`（每筆 `{"text": str, "score": float, "center": (x,y)}`，已存在於 `miningbot/ocr.py:811`，Task 4 會用它產生本模組吃的 `records` 參數）
- Produces（Task 4 的 `Bot._set_movement_mode` 會呼叫這些函式）：
  - `roblox_menu.menu_open(records: list[dict], min_ratio: float) -> bool`
  - `roblox_menu.find_tab_center(records: list[dict], tab_name: str, min_ratio: float) -> tuple[int,int] | None`
  - `roblox_menu.find_label_row_y(records: list[dict], label: str, min_ratio: float) -> int | None`
  - `roblox_menu.read_row_value(records: list[dict], row_y: int, value_x_range: tuple[int,int], y_tol: int) -> str | None`
  - `roblox_menu.value_matches_target(value_text: str, target: str, other_options: tuple[str,...], min_ratio: float) -> bool`

**Steps:**

- [ ] 準備兩張實機回歸 fixture（一次性素材準備，非本次要重複執行的程式）。在專案根目錄執行：

```python
import cv2
import numpy as np

def load(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)

import os
os.makedirs("tests/fixtures/menu", exist_ok=True)
for name in ("mm_cycle0", "mm_cycle1"):
    img = load(f"logs/{name}.png")
    crop = img[130:1010, 460:1460]           # 對應 cfg.menu_panel_region=(460,130,1000,880)
    cv2.imencode(".png", crop)[1].tofile(f"tests/fixtures/menu/{name}.png")
print("done")
```

  （存成 `tests/fixtures/menu/mm_cycle0.png` = Movement Mode 顯示 `Default (Keyboard)`、
  `mm_cycle1.png` = 顯示 `Keyboard + Mouse`。這兩張截圖是 2026-07-08 使用者實機操作 Settings
  選單時拍的，已用 `ocr.read_text_boxes` 實測驗證：`mm_cycle0` 讀出 `Movement Mode` 標籤在
  `(571,503)`、值 `Default (Keyboard)` 在 `(1153,503)`；`mm_cycle1` 值變成 `Keyboard + Mouse`
  在 `(1153,502)`——與本 Task 稍後的 fixture 測試斷言一致。）

- [ ] 寫測試（新檔 `tests/test_roblox_menu.py`）：

```python
"""roblox_menu 純決策模組單元測試（TDD）。

設計：docs/superpowers/specs/2026-07-08-menu-preflight-boost-design.md 第 1 節。
所有函式只吃/回資料（OCR 文字框列表、字串），不碰螢幕/鍵鼠——比照 reentry.py 的
「決策純函式＋I/O 在 Bot」慣例。「嚴格贏過其他選項」的模糊比對精神抄
reentry.pick_layer_button（寧漏勿誤：分不清就不判定為命中）。
"""
import os
import pytest
from miningbot import roblox_menu

MOVEMENT_MODES = ("Default (Keyboard)", "Keyboard + Mouse", "Click to Move")


def _rec(text, center):
    return {"text": text, "score": 0.9, "center": center}


TAB_ROW = [
    _rec("People", (576, 156)),
    _rec("Settings", (774, 156)),
    _rec("Gallery", (976, 156)),
    _rec("Report", (1179, 156)),
    _rec("Help", (1378, 156)),
]

MOVEMENT_ROW_RECS = [
    _rec("Camera Sensitivity", (579, 441)),
    _rec("Movement Mode", (571, 503)),
    _rec("Default (Keyboard)", (1153, 503)),
    _rec("Shift Lock Switch", (571, 565)),
    _rec("On", (1155, 566)),
]


class TestMenuOpen:
    def test_true_when_tab_labels_visible(self):
        assert roblox_menu.menu_open(TAB_ROW, 0.7) is True

    def test_false_when_no_tab_labels(self):
        recs = [_rec("Cloverstone 204", (80, 470))]
        assert roblox_menu.menu_open(recs, 0.7) is False

    def test_false_on_empty_records(self):
        assert roblox_menu.menu_open([], 0.7) is False


class TestFindTabCenter:
    def test_exact_hit(self):
        assert roblox_menu.find_tab_center(TAB_ROW, "Settings", 0.7) == (774, 156)

    def test_ocr_noise_still_hits(self):
        # 遊戲字型 i/l 同形（比照 H033）：Settlngs 仍應命中
        recs = [_rec("Settlngs", (774, 156))]
        assert roblox_menu.find_tab_center(recs, "Settings", 0.7) == (774, 156)

    def test_no_match_returns_none(self):
        recs = [_rec("People", (576, 156))]
        assert roblox_menu.find_tab_center(recs, "Settings", 0.7) is None


class TestFindLabelRowY:
    def test_hits_movement_mode(self):
        assert roblox_menu.find_label_row_y(MOVEMENT_ROW_RECS, "Movement Mode", 0.7) == 503

    def test_none_when_absent(self):
        recs = [_rec("Shift Lock Switch", (571, 565))]
        assert roblox_menu.find_label_row_y(recs, "Movement Mode", 0.7) is None


class TestReadRowValue:
    def test_hits_same_row_value_column(self):
        v = roblox_menu.read_row_value(MOVEMENT_ROW_RECS, 503, (1000, 1350), 18)
        assert v == "Default (Keyboard)"

    def test_ignores_other_rows(self):
        v = roblox_menu.read_row_value(MOVEMENT_ROW_RECS, 503, (1000, 1350), 18)
        assert v != "On"          # "On" 屬於 Shift Lock Switch 那列(y=566)，不該被讀到

    def test_none_when_row_has_no_value_in_range(self):
        recs = [_rec("Movement Mode", (571, 503))]
        assert roblox_menu.read_row_value(recs, 503, (1000, 1350), 18) is None

    def test_y_tolerance_respected(self):
        recs = [_rec("Movement Mode", (571, 503)), _rec("Default (Keyboard)", (1153, 530))]
        # 差 27px，超過容差 18 → 不該算同列
        assert roblox_menu.read_row_value(recs, 503, (1000, 1350), 18) is None


class TestValueMatchesTarget:
    OTHERS_FOR_DEFAULT = ("Keyboard + Mouse", "Click to Move")

    def test_exact_match(self):
        assert roblox_menu.value_matches_target(
            "Default (Keyboard)", "Default (Keyboard)", self.OTHERS_FOR_DEFAULT, 0.6) is True

    def test_ocr_noise_still_hits(self):
        assert roblox_menu.value_matches_target(
            "Defauit (Keyboard)", "Default (Keyboard)", self.OTHERS_FOR_DEFAULT, 0.6) is True

    def test_wrong_value_is_false(self):
        assert roblox_menu.value_matches_target(
            "Keyboard + Mouse", "Click to Move",
            ("Default (Keyboard)", "Click to Move"), 0.6) is False

    def test_ambiguous_returns_false(self):
        # 對 target 與 other 分數打平/都低 → 分不清，不判命中（寧漏勿誤）
        assert roblox_menu.value_matches_target(
            "Mode", "Keyboard + Mouse", self.OTHERS_FOR_DEFAULT, 0.6) is False


# ---------- 實機截圖回歸（2026-07-08 Settings 選單截圖，鎖住整條「OCR框→找列→讀值」） ----------

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402
from miningbot import ocr  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "menu")


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


rapid_skip = pytest.mark.skipif(not ocr.rapidocr_available(), reason="rapidocr 未安裝")


@rapid_skip
def test_real_screenshot_default_keyboard_detected():
    img = _load("mm_cycle0.png")
    recs = ocr.read_text_boxes(img, region_offset=(460, 130))
    row_y = roblox_menu.find_label_row_y(recs, "Movement Mode", 0.7)
    assert row_y is not None
    value = roblox_menu.read_row_value(recs, row_y, (1000, 1350), 18)
    assert roblox_menu.value_matches_target(
        value, "Default (Keyboard)", ("Keyboard + Mouse", "Click to Move"), 0.6) is True


@rapid_skip
def test_real_screenshot_keyboard_mouse_detected_and_not_confused_with_default():
    img = _load("mm_cycle1.png")
    recs = ocr.read_text_boxes(img, region_offset=(460, 130))
    row_y = roblox_menu.find_label_row_y(recs, "Movement Mode", 0.7)
    assert row_y is not None
    value = roblox_menu.read_row_value(recs, row_y, (1000, 1350), 18)
    assert roblox_menu.value_matches_target(
        value, "Keyboard + Mouse", ("Default (Keyboard)", "Click to Move"), 0.6) is True
    assert roblox_menu.value_matches_target(
        value, "Default (Keyboard)", ("Keyboard + Mouse", "Click to Move"), 0.6) is False
```

- [ ] 跑測試確認失敗（模組還不存在）：
  ```
  python -m pytest tests/test_roblox_menu.py -q
  ```
  預期：`ModuleNotFoundError: No module named 'miningbot.roblox_menu'`。

- [ ] 建立 `miningbot/roblox_menu.py`：

```python
"""Roblox 內建設定選單的 OCR 錨定驅動——純決策邏輯。

設計：docs/superpowers/specs/2026-07-08-menu-preflight-boost-design.md 第 1 節。
比照 reentry.py：這裡只有可單測的純函式（吃 OCR 文字框列表，回決策），所有 I/O
（Esc/點擊/捲動/截圖/OCR 呼叫本身）在 main.Bot._set_movement_mode。
核心原則「寧漏勿誤」：模糊比對必須嚴格贏過其他候選才算命中（比照
reentry.pick_layer_button 的雙向最近鄰），打平/都低分一律回「沒找到」，
交呼叫端走 Esc 回中性＋重試，而非用猜的硬點下去。
"""
from difflib import SequenceMatcher

# 選單分頁列固定會出現的文字（用於判斷 Esc 後選單是否真的開了）
_TAB_LABELS = ("people", "settings", "gallery", "report", "help")


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def menu_open(records, min_ratio: float) -> bool:
    """OCR 文字框裡看不看得到分頁列（People/Settings/...）任一個——選單開了的訊號。

    records 為空或找不到任何分頁字樣 → False（呼叫端判定 Esc 沒開成功或選單已關）。
    """
    for r in records:
        t = _norm(r["text"])
        for label in _TAB_LABELS:
            if SequenceMatcher(None, t, label).ratio() >= min_ratio:
                return True
    return False


def find_tab_center(records, tab_name: str, min_ratio: float):
    """找分頁文字框中心（點擊用）。取最高分且達門檻者；找不到回 None。"""
    tgt = _norm(tab_name)
    best = None
    for r in records:
        ratio = SequenceMatcher(None, _norm(r["text"]), tgt).ratio()
        if ratio >= min_ratio and (best is None or ratio > best[0]):
            best = (ratio, r["center"])
    return best[1] if best else None


def find_label_row_y(records, label: str, min_ratio: float):
    """找標籤（如 "Movement Mode"）所在列的螢幕 y 座標。取最高分且達門檻者；找不到回 None。"""
    tgt = _norm(label)
    best = None
    for r in records:
        ratio = SequenceMatcher(None, _norm(r["text"]), tgt).ratio()
        if ratio >= min_ratio and (best is None or ratio > best[0]):
            best = (ratio, r["center"][1])
    return best[1] if best else None


def read_row_value(records, row_y: int, value_x_range, y_tol: int):
    """在同一列（|y - row_y| <= y_tol）且 x 落在 value_x_range 內取值文字。找不到回 None。

    只回第一個符合的文字框——選單一列的值欄只會有一段文字，多個符合代表 OCR
    把值切成多段（目前遇到的實機案例都是單一文字框），暫不處理合併。
    """
    lo, hi = value_x_range
    for r in records:
        cx, cy = r["center"]
        if abs(cy - row_y) <= y_tol and lo <= cx <= hi:
            return r["text"]
    return None


def value_matches_target(value_text, target: str, other_options, min_ratio: float) -> bool:
    """value_text 是否等於 target——模糊比對且嚴格贏過 other_options 裡的每一個。

    value_text 為 None（該列沒讀到值）一律 False。打平或都低分＝分不清，回 False
    （寧漏勿誤：呼叫端會判斷「還沒到目標」而繼續點右箭頭，而不是誤判成功提早收工）。
    """
    if value_text is None:
        return False
    t = _norm(value_text)
    tgt_ratio = SequenceMatcher(None, t, _norm(target)).ratio()
    if tgt_ratio < min_ratio:
        return False
    other_ratio = max((SequenceMatcher(None, t, _norm(o)).ratio() for o in other_options),
                      default=0.0)
    return tgt_ratio > other_ratio
```

- [ ] 跑測試確認通過（rapidocr 未安裝時後兩個實機回歸測試會 skip，不算失敗）：
  ```
  python -m pytest tests/test_roblox_menu.py -q
  ```

- [ ] 跑全套：
  ```
  python -m pytest -q
  ```

- [ ] commit（含新 fixture 圖檔）：
  ```
  git add miningbot/roblox_menu.py tests/test_roblox_menu.py tests/fixtures/menu/
  git commit -m "$(cat <<'EOF'
  feat(roblox_menu): 新模組——選單 OCR 錨定純決策函式

  找分頁/找標籤列/讀值/模糊比對（嚴格贏過其他選項），比照 reentry.pick_layer_button
  的寧漏勿誤精神。含 2026-07-08 實機 Settings 截圖回歸測試。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 4: Bot._set_movement_mode（main.py I/O glue）

**Files:**
- Modify: `miningbot/main.py`（在 `_focus_roblox` 方法後方新增，約第 710 行之後，即 `_hotkey_loop` 定義之前）

**Interfaces:**
- Consumes:
  - `roblox_menu.menu_open/find_tab_center/find_label_row_y/read_row_value/value_matches_target`（Task 3）
  - `input_control.scroll(clicks)`／`input_control.move_to(x,y)`（Task 2，模組別名 `ic`，main.py 已有 `from . import input_control as ic`）
  - `ocr.read_text_boxes(image_bgr, region_offset)`（既有）
  - `capture.grab()`／`capture.crop(frame, region)`（既有）
  - `cfg.movement_mode_options/menu_*`（Task 1）
- Produces: `Bot._set_movement_mode(target: str) -> bool`（Task 5、Task 6 會呼叫它）

**Steps:**

- [ ] 在 `miningbot/main.py` 檔案頂部 import 區塊確認已有 `from . import sampler, reentry`（第 16 行），改成同時匯入 `roblox_menu`：

  找到：
  ```python
  from . import sampler, reentry
  ```
  改成：
  ```python
  from . import sampler, reentry, roblox_menu
  ```

- [ ] 在 `_focus_roblox` 方法結尾（約第 709-710 行，`return got` 之後、`def _hotkey_loop` 之前）插入新方法：

```python
    def _set_movement_mode(self, target: str) -> bool:
        """把 Roblox 設定 Movement Mode 切到 target（三值之一）。

        決策純函式在 roblox_menu.py，這裡只做 I/O（Esc/點擊/捲動/OCR）。冪等：已是
        目標值時不點任何箭頭直接收工。任一步不確定 → Esc 回中性 → 整鏈重試
        cfg.menu_retry_max 次 → 仍失敗回 False（呼叫端依情境分流 NEEDS_HUMAN 或記警告）。
        """
        others = tuple(o for o in cfg.movement_mode_options if o != target)
        for attempt in range(cfg.menu_retry_max + 1):
            if self._set_movement_mode_once(target, others):
                return True
            self.log_act.warning("Movement Mode 切換失敗（第 %d 次），Esc 回中性後重試",
                                 attempt + 1)
            ic.key_press("esc")
            time.sleep(cfg.menu_close_settle_s)
        return False

    def _set_movement_mode_once(self, target: str, others: tuple) -> bool:
        """單次嘗試：開選單→找 Settings→找 Movement Mode 列→比對值→不符則點右箭頭。"""
        ic.key_press("esc")
        time.sleep(cfg.menu_open_settle_s)
        records = self._menu_ocr()
        if not roblox_menu.menu_open(records, cfg.menu_fuzzy_min_ratio):
            self.log_act.warning("Movement Mode 切換：Esc 後未偵測到選單開啟")
            return False

        tab_xy = roblox_menu.find_tab_center(records, "Settings", cfg.menu_fuzzy_min_ratio)
        if tab_xy is None:
            self.log_act.warning("Movement Mode 切換：找不到 Settings 分頁")
            return False
        ic.click_at(*tab_xy)
        time.sleep(cfg.menu_open_settle_s)

        row_y = None
        records = []
        for _ in range(cfg.menu_scroll_max_screens):
            records = self._menu_ocr()
            row_y = roblox_menu.find_label_row_y(records, "Movement Mode", cfg.menu_fuzzy_min_ratio)
            if row_y is not None:
                break
            ic.move_to(*cfg.menu_scroll_xy)
            ic.scroll(cfg.menu_scroll_amount)
            time.sleep(cfg.menu_open_settle_s)
        if row_y is None:
            self.log_act.warning("Movement Mode 切換：捲動 %d 屏仍找不到標籤",
                                 cfg.menu_scroll_max_screens)
            return False

        value_text = roblox_menu.read_row_value(
            records, row_y, cfg.menu_value_column_x_range, cfg.menu_row_y_tolerance_px)
        if roblox_menu.value_matches_target(value_text, target, others, cfg.menu_fuzzy_min_ratio):
            self.log_act.info("Movement Mode 已是目標值 %s，收工", target)
            ic.key_press("esc")
            time.sleep(cfg.menu_close_settle_s)
            return True

        for click_i in range(cfg.menu_arrow_click_max):
            ic.click_at(cfg.menu_arrow_right_x, row_y)
            time.sleep(cfg.menu_arrow_settle_s)
            records = self._menu_ocr()
            value_text = roblox_menu.read_row_value(
                records, row_y, cfg.menu_value_column_x_range, cfg.menu_row_y_tolerance_px)
            if roblox_menu.value_matches_target(value_text, target, others, cfg.menu_fuzzy_min_ratio):
                self.log_act.info("Movement Mode 切到 %s（點了 %d 次右箭頭）", target, click_i + 1)
                ic.key_press("esc")
                time.sleep(cfg.menu_close_settle_s)
                return True

        self.log_act.warning("Movement Mode 切換：點滿 %d 次右箭頭仍未到目標 %s（現讀值=%r）",
                             cfg.menu_arrow_click_max, target, value_text)
        return False

    def _menu_ocr(self):
        """截圖＋裁 menu_panel_region＋OCR 文字框（回傳座標已還原成全螢幕座標）。"""
        frame = capture.grab()
        crop = capture.crop(frame, cfg.menu_panel_region)
        r = cfg.menu_panel_region
        return ocr.read_text_boxes(crop, region_offset=(r.x, r.y))
```

- [ ] 這個方法是 I/O glue，不寫 mock 單元測試（見 Global Constraints）；先跑一次全套測試確認語法正確、沒有 import 錯誤：
  ```
  python -m pytest -q
  ```
  （此時測試數量應與 Task 3 結束時相同，只是確認新程式碼沒有 import/語法錯誤導致 collection error）

- [ ] commit：
  ```
  git add miningbot/main.py
  git commit -m "$(cat <<'EOF'
  feat(main): Bot._set_movement_mode——Movement Mode 切換 I/O glue

  Esc→找 Settings 分頁→捲動找 Movement Mode 列→讀值比對→不符則點右箭頭
  （上限 3 次）；任一步不確定 Esc 回中性重試一次，仍失敗回 False。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 5: REENTRY 接線（main.py）

**Files:**
- Modify: `miningbot/main.py`（三處修改：`_on_enter` 的 `State.REENTRY` 分支約第 1395-1416 行；`_tick_reentry` 的 `CLICK_VERIFY` 分支約第 2256-2267 行；`_reentry_reroll` 的放棄分支約第 2286-2291 行——**執行前用 `Grep` 或編輯器搜尋下列「找到」片段的精確文字來定位，不要依賴行號**，Task 3/4 已插入新程式碼會讓行號整體下移）

**Interfaces:**
- Consumes: `Bot._set_movement_mode(target: str) -> bool`（Task 4）、`cfg.movement_mode_mining/movement_mode_reentry`（Task 1）
- 本 Task 不新增純函式；三處都是既有 I/O 流程裡插入一次 `_set_movement_mode` 呼叫＋分流，行為比照現有「聚焦失敗→NEEDS_HUMAN」的既定模式（見下方 anchors）。

**Steps:**

- [ ] 修改 1／進 REENTRY 前切 Click to Move（按「回到地表」之前）。在 `_on_enter` 方法裡找到：

```python
        if s is State.REENTRY:
            # 入口聚焦失敗 → 降級 NEEDS_HUMAN（比照 MINING 入口）：REENTRY 全程都在
            # 送鍵/點擊，焦點不在 Roblox 上會全部送錯視窗、白白燒光 reroll 次數。
            if not self._focus_roblox():
                self.logger.warning("進入 REENTRY 但無法聚焦 Roblox -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法聚焦 Roblox（自動回礦前），請確認遊戲視窗後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)
                return State.NEEDS_HUMAN
            now = time.time()
            self._reentry = reentry.ReentryState(phase_started=now, attempt_started=now)
            self._reentry_done = False
            self._reentry_failed = False
            self._reentry_ref = None
            self._reentry_panel_xy = None
            self._move_diffs = []
            self._last_nav_frame = None
            ic.key_up("w"); ic.mouse_up()            # RESET_WAIT 本已放開，保險再放一次
            ic.click_at(*cfg.reentry_surface_button_xy)   # 按「回到地表」
```

  改成（在聚焦成功之後、按「回到地表」之前插入 Movement Mode 切換；失敗同樣走「降級 NEEDS_HUMAN」模式）：

```python
        if s is State.REENTRY:
            # 入口聚焦失敗 → 降級 NEEDS_HUMAN（比照 MINING 入口）：REENTRY 全程都在
            # 送鍵/點擊，焦點不在 Roblox 上會全部送錯視窗、白白燒光 reroll 次數。
            if not self._focus_roblox():
                self.logger.warning("進入 REENTRY 但無法聚焦 Roblox -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法聚焦 Roblox（自動回礦前），請確認遊戲視窗後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)
                return State.NEEDS_HUMAN
            # click-to-move 導航依賴 Movement Mode=Click to Move；切不過去導航無意義，
            # reroll 也救不了 → 直接降級 NEEDS_HUMAN（比照聚焦失敗的既定模式）。
            if not self._set_movement_mode(cfg.movement_mode_reentry):
                self.logger.warning("進入 REENTRY 但無法切換 Movement Mode -> 降級 NEEDS_HUMAN")
                self._human_reason = "無法切換至 Click to Move（自動回礦前），請手動確認設定後按 Q"
                self._on_enter(State.NEEDS_HUMAN, frame)
                return State.NEEDS_HUMAN
            now = time.time()
            self._reentry = reentry.ReentryState(phase_started=now, attempt_started=now)
            self._reentry_done = False
            self._reentry_failed = False
            self._reentry_ref = None
            self._reentry_panel_xy = None
            self._move_diffs = []
            self._last_nav_frame = None
            ic.key_up("w"); ic.mouse_up()            # RESET_WAIT 本已放開，保險再放一次
            ic.click_at(*cfg.reentry_surface_button_xy)   # 按「回到地表」
```

- [ ] 修改 2／進礦驗證成功後、`init_mining_sequence` 前切回 Default (Keyboard)。在 `_tick_reentry` 方法裡找到：

```python
        if st.phase == reentry.CLICK_VERIFY:
            if vision.frame_mean_diff(self._reentry_ref, frame) >= cfg.reentry_teleport_diff:
                r = cfg.stuck_region
                crop = frame[r.y:r.y + r.h, r.x:r.x + r.w]
                if float(np.mean(crop)) <= cfg.reentry_mine_max_brightness:
                    self._reentry_done = True
                    self._snapshot(frame, "reentry_success")
                    self.log.log("REENTRY_SUCCESS", attempts=st.attempts + 1)
                    self.logger.info("REENTRY 成功（第 %d 輪）→ 恢復挖礦", st.attempts + 1)
                    return
            if now - st.phase_started > cfg.reentry_teleport_wait_s:
                self._reentry_reroll("click did not teleport into mine")
```

  改成（驗證成功後先切回 Default (Keyboard)，失敗直接交人工——比照 `_harvest_giveup` 的
  「直接寫 `self.state`＋呼叫 `_on_enter`」模式，因為此刻已經在 `_tick_reentry` 內，不是走
  `_on_enter`／`decide_transition` 那條路）：

```python
        if st.phase == reentry.CLICK_VERIFY:
            if vision.frame_mean_diff(self._reentry_ref, frame) >= cfg.reentry_teleport_diff:
                r = cfg.stuck_region
                crop = frame[r.y:r.y + r.h, r.x:r.x + r.w]
                if float(np.mean(crop)) <= cfg.reentry_mine_max_brightness:
                    # 進礦已驗證成功——切回 Default (Keyboard) 才能安全 init_mining_sequence
                    # （Click to Move 模式下按住 W+左鍵的挖礦序列不可信）。切失敗不可帶病開挖，
                    # 直接交人工（比照 _harvest_giveup：此刻在 tick 內，不走 decide_transition）。
                    if not self._set_movement_mode(cfg.movement_mode_mining):
                        self.logger.warning("REENTRY 進礦成功但切回 Movement Mode 失敗 -> NEEDS_HUMAN")
                        self._human_reason = "自動回礦成功但無法切回 Default (Keyboard)，請手動確認設定後按 Q"
                        self.state = State.NEEDS_HUMAN
                        self._on_enter(State.NEEDS_HUMAN, frame)
                        return
                    self._reentry_done = True
                    self._snapshot(frame, "reentry_success")
                    self.log.log("REENTRY_SUCCESS", attempts=st.attempts + 1)
                    self.logger.info("REENTRY 成功（第 %d 輪）→ 恢復挖礦", st.attempts + 1)
                    return
            if now - st.phase_started > cfg.reentry_teleport_wait_s:
                self._reentry_reroll("click did not teleport into mine")
```

- [ ] 修改 3／放棄路徑 best-effort 切回（失敗不擋通知）。在 `_reentry_reroll` 方法裡找到：

```python
        st = self._reentry
        st.attempts += 1
        self.log_act.info("reentry reroll #%d：%s", st.attempts, reason)
        if reentry.should_giveup(st.attempts, cfg.reentry_max_attempts):
            self._reentry_failed = True
            self._human_reason = f"自動回礦失敗×{st.attempts}（{reason}），請手動回礦後按 Q"
            self._needs_human_extra_image = self._snapshot(capture.grab(), "reentry_giveup")
            return
```

  改成：

```python
        st = self._reentry
        st.attempts += 1
        self.log_act.info("reentry reroll #%d：%s", st.attempts, reason)
        if reentry.should_giveup(st.attempts, cfg.reentry_max_attempts):
            self._reentry_failed = True
            self._human_reason = f"自動回礦失敗×{st.attempts}（{reason}），請手動回礦後按 Q"
            self._needs_human_extra_image = self._snapshot(capture.grab(), "reentry_giveup")
            # best-effort 切回 Default (Keyboard)：人工接手時鍵鼠模式對才好操作，
            # 但失敗不擋 NEEDS_HUMAN 通知（人工本來就會检查/修正設定）。
            if not self._set_movement_mode(cfg.movement_mode_mining):
                self.log_act.warning("REENTRY 放棄時切回 Movement Mode 失敗（best-effort，不擋通知）")
            return
```

- [ ] 跑全套測試（`tests/test_reentry.py`／`tests/test_states.py` 應仍全綠——本 Task 沒改任何純函式，只改 `main.py` 的 I/O glue）：
  ```
  python -m pytest -q
  ```

- [ ] commit：
  ```
  git add miningbot/main.py
  git commit -m "$(cat <<'EOF'
  feat(reentry): 接線 Movement Mode 切換——導航前 Click to Move／進礦後切回

  按「回到地表」前切 Click to Move（失敗→NEEDS_HUMAN，reroll 無意義）；進礦驗證
  成功後、init_mining_sequence 前切回 Default (Keyboard)（失敗→NEEDS_HUMAN，
  不可帶病開挖）；放棄交人工前 best-effort 切回（失敗不擋通知）。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 6: 聊天框開/關偵測 fixtures ＋ Bot._ensure_chat_open

**Files:**
- Create: `tests/fixtures/chat_ui/open.png`、`tests/fixtures/chat_ui/closed.png`（來源 `logs/menu_settings1.png`／`logs/d5_before.png`，裁 `chat_input_region`）
- Create: `tests/test_chat_ui_fixtures.py`
- Modify: `miningbot/main.py`（在 `_focus_roblox` 之後新增 `_ensure_chat_open` 方法——本 Task 只新增方法本體，Task 7 才把它接進 `Bot.run()`）

**Interfaces:**
- Consumes: `ocr.read_text(image_bgr, tesseract_path)`（既有）、`ocr.contains_any(text, phrases)`（既有，`miningbot/ocr.py:14`）、`cfg.chat_input_region/chat_input_phrases/chat_icon_xy`（Task 1）
- Produces: `Bot._ensure_chat_open() -> None`（Task 7 會在 `Bot.run()` 啟動時呼叫；本身不回傳成功/失敗——設計上「仍關」只記警告不擋啟動，見 spec 第 3 節）

**Steps:**

- [ ] 準備兩張回歸 fixture。在專案根目錄執行：

```python
import cv2
import numpy as np
import os

def load(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)

os.makedirs("tests/fixtures/chat_ui", exist_ok=True)
region = (0, 355, 620, 55)   # x, y, w, h == cfg.chat_input_region
x, y, w, h = region

opened = load("logs/menu_settings1.png")[y:y+h, x:x+w]
closed = load("logs/d5_before.png")[y:y+h, x:x+w]
cv2.imencode(".png", opened)[1].tofile("tests/fixtures/chat_ui/open.png")
cv2.imencode(".png", closed)[1].tofile("tests/fixtures/chat_ui/closed.png")
print("done")
```

  （2026-07-08 已用真實 tesseract 驗證：`open.png` OCR 讀到含 `"press / key"` 的文字、
  `contains_any` 判 True；`closed.png` OCR 讀到雜訊字串，不含任何 `chat_input_phrases`、
  判 False——不會誤判。）

- [ ] 寫測試（新檔 `tests/test_chat_ui_fixtures.py`）：

```python
"""聊天框開/關偵測回歸測試：鎖住「展開時 OCR 讀得到輸入列提示、收合時不會誤判」。

fixtures 取自 2026-07-08 實機截圖裁 cfg.chat_input_region：
- open.png：聊天框展開狀態（「To chat click here or press / key」輸入列）
- closed.png：預設收合狀態（該區域只剩背包面板一角，OCR 讀到雜訊，不得誤判為開啟）

需要本機 tesseract（同 production 引擎）；未裝時整檔 skip，不擋純邏輯 CI。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import ocr  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "chat_ui")


def _engine_ready() -> bool:
    try:
        ocr.read_text(np.zeros((20, 120, 3), dtype=np.uint8), cfg.tesseract_path)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _engine_ready(), reason="tesseract 引擎不可用")


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def test_open_chat_detected():
    text = ocr.read_text(_load("open.png"), cfg.tesseract_path)
    assert ocr.contains_any(text, cfg.chat_input_phrases) is True


def test_closed_chat_not_falsely_detected():
    text = ocr.read_text(_load("closed.png"), cfg.tesseract_path)
    assert ocr.contains_any(text, cfg.chat_input_phrases) is False
```

- [ ] 跑測試確認失敗（fixture 還沒準備／檔案不存在會直接 assert 失敗）：
  ```
  python -m pytest tests/test_chat_ui_fixtures.py -q
  ```

- [ ] 若尚未執行上面的準備素材腳本，先執行它產生 fixture png，再跑測試確認通過：
  ```
  python -m pytest tests/test_chat_ui_fixtures.py -q
  ```

- [ ] 在 `miningbot/main.py` 找到 Task 4 新增的 `_menu_ocr` 方法結尾（精確錨點——這是
  `_menu_ocr` 的完整方法本體，Task 4 剛新增、此刻應該逐字存在於檔案裡）：

```python
    def _menu_ocr(self):
        """截圖＋裁 menu_panel_region＋OCR 文字框（回傳座標已還原成全螢幕座標）。"""
        frame = capture.grab()
        crop = capture.crop(frame, cfg.menu_panel_region)
        r = cfg.menu_panel_region
        return ocr.read_text_boxes(crop, region_offset=(r.x, r.y))
```

  在它後面（緊接著、同一縮排層級）新增：

```python
    def _ensure_chat_open(self):
        """啟動 UI 前置檢查：聊天框關著就點圖示開啟；仍關只記警告＋HUD，照常啟動
        （不發 Discord：啟動時人在旁邊，比照 preflight 警訊分流慣例，見 CLAUDE.md）。
        """
        frame = capture.grab()
        text = ocr.read_text(capture.crop(frame, cfg.chat_input_region), cfg.tesseract_path)
        if ocr.contains_any(text, cfg.chat_input_phrases):
            self.logger.info("UI 前置檢查：聊天框已開啟")
            return
        self.logger.info("UI 前置檢查：聊天框關閉，點擊圖示開啟")
        ic.click_at(*cfg.chat_icon_xy)
        time.sleep(cfg.menu_open_settle_s)
        frame = capture.grab()
        text = ocr.read_text(capture.crop(frame, cfg.chat_input_region), cfg.tesseract_path)
        if ocr.contains_any(text, cfg.chat_input_phrases):
            self.logger.info("UI 前置檢查：聊天框已開啟（點擊後確認）")
            return
        self.logger.warning("UI 前置檢查：聊天框仍未開啟，可能影響採集確認；請手動開啟")
        self.last_action = "⚠ 聊天框未開啟，採集確認可能失效"
```

- [ ] 跑全套測試：
  ```
  python -m pytest -q
  ```

- [ ] commit：
  ```
  git add miningbot/main.py tests/test_chat_ui_fixtures.py tests/fixtures/chat_ui/
  git commit -m "$(cat <<'EOF'
  feat(main): 聊天框開/關偵測——Bot._ensure_chat_open + 實機回歸 fixtures

  OCR 讀 chat_input_region 判斷輸入列提示字樣；關著就點圖示開啟，仍關只記警告
  （啟動時人在旁邊，不擋啟動、不發 Discord）。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 7: Bot.run() 啟動前置檢查接線

**Files:**
- Modify: `miningbot/main.py`（`run()` 方法，約第 1048-1070 行）

**Interfaces:**
- Consumes: `Bot._ensure_chat_open()`（Task 6）、`Bot._set_movement_mode(target)`（Task 4）、`cfg.movement_mode_mining`（Task 1）

**Steps:**

- [ ] 在 `run()` 方法裡找到：

```python
        miner.init_mining_sequence(rotate=self._rotate_verified)
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
```

  改成（在 `init_mining_sequence` 之前插入兩項前置檢查——**順序**：先確保聊天框開（不影響按鍵狀態），
  再切 Movement Mode（若這裡失敗只記警告不中止，因為此時還沒開始挖礦，跟 REENTRY 場景「不可帶病
  開挖」的嚴重度不同——見 spec 第 3 節「本身就是不對就修」的措辭，沒有寫「失敗中止啟動」）：

```python
        # 啟動 UI 前置檢查（spec 2026-07-08-menu-preflight-boost-design.md 第 3 節）：
        # 聊天框關著會讓整條 verify OCR 鏈瞎眼；Movement Mode 不對會讓 W+左鍵挖礦序列失效。
        self._ensure_chat_open()
        if not self._set_movement_mode(cfg.movement_mode_mining):
            self.logger.warning("UI 前置檢查：Movement Mode 切換失敗，可能影響操作，請手動確認後繼續")
            self.last_action = "⚠ Movement Mode 切換失敗，請手動確認"
        miner.init_mining_sequence(rotate=self._rotate_verified)
        threading.Thread(target=self._hotkey_loop, daemon=True).start()
```

- [ ] 跑全套測試：
  ```
  python -m pytest -q
  ```

- [ ] commit：
  ```
  git add miningbot/main.py
  git commit -m "$(cat <<'EOF'
  feat(main): Bot.run() 接線啟動 UI 前置檢查（聊天框＋Movement Mode）

  init_mining_sequence 之前先確保聊天框開啟、Movement Mode 為 Default (Keyboard)；
  失敗只記警告不中止啟動（此刻尚未開始挖礦，嚴重度低於 REENTRY 場景）。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 8: D5 boost 偵測適配——新模板＋回歸 fixtures

**Files:**
- Create/Overwrite: `assets/boost_active.png`（gitignored，本機產生，不會進 git status）
- Create: `tests/fixtures/boost/before_only_count.png`、`tests/fixtures/boost/active_47.png`、`tests/fixtures/boost/active_61.png`
- Create: `tests/test_boost_fixtures.py`

**Interfaces:**
- Consumes: `vision.find_template_edges(scene_bgr, template_bgr, threshold, scales)`（既有，`miningbot/vision.py:85`）、`vision.load_template(path)`（既有）、`cfg.boost_indicator_region/boost_edge_threshold/boost_buff_scales`（`boost_indicator_region` 已在 Task 1 改值）

**Steps:**

- [ ] 寫測試（新檔 `tests/test_boost_fixtures.py`）——先寫測試、此時 fixture png 還不存在，測試會因檔案讀不到而失敗：

```python
"""D5 boost 偵測三態回歸測試（2026-07-08 遊戲更新新增永久計數圖示）。

背景：右下角原本只有「boost 生效中的瓶子圖示」，遊戲更新後新增一顆常駐的
「使用次數計數」圖示，長得跟 boost 瓶子一樣，只是位置固定在 boost 瓶子右側、
不會消失。舊 boost_indicator_region 涵蓋到它 → 判定邏輯（瓶子消失=該補 D5）
永遠看到一顆「瓶子」→ 永遠判生效中、永遠不補 D5。

對策：boost_indicator_region 右緣縮到永久計數圖示左緣（Task 1 已改）；模板換成
從新截圖裁的倒數圖示（2026-07-08 logs/d5_active.png，bbox 用像素差分實測鎖定：
(1676,1010)-(1734,1068)，58x58）。

fixtures 是三個真實遊戲畫面狀態，直接裁 cfg.boost_indicator_region 那塊區域
（即 find_template_edges 在正式程式碼裡實際會收到的輸入）：
- before_only_count：只有永久計數圖示（該圖示已被新 region 排除在外）→ 預期偵測不到瓶子 → 該補 D5
- active_47 / active_61：計數圖示之外還有倒數圖示（47s/61s，兩種數字驗證邊緣比對不受數字影響）
  → 預期偵測到瓶子 → 生效中，不該補

「無圖示」（新伺服器、從未用過 D5）today 沒截到樣本，見 docs 最後校準清單。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import vision  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "boost")


def _load(name):
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def _template():
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "boost_active.png")
    assert os.path.exists(path), "assets/boost_active.png 不存在——先跑素材準備腳本"
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def test_only_permanent_counter_icon_is_not_detected_as_boost():
    # 只有永久計數圖示（無倒數）→ 該補 D5：偵測必須是 None
    scene = _load("before_only_count.png")
    result = vision.find_template_edges(scene, _template(), cfg.boost_edge_threshold,
                                        cfg.boost_buff_scales)
    assert result is None


def test_active_47_countdown_detected():
    scene = _load("active_47.png")
    result = vision.find_template_edges(scene, _template(), cfg.boost_edge_threshold,
                                        cfg.boost_buff_scales)
    assert result is not None


def test_active_61_countdown_detected():
    # 另一個數字變體（61 而非 47）：邊緣比對忽略數字，必須同樣偵測到
    scene = _load("active_61.png")
    result = vision.find_template_edges(scene, _template(), cfg.boost_edge_threshold,
                                        cfg.boost_buff_scales)
    assert result is not None
```

- [ ] 跑測試確認失敗（`assets/boost_active.png` 是舊模板或素材還沒準備）：
  ```
  python -m pytest tests/test_boost_fixtures.py -q
  ```

- [ ] 準備模板與 fixture 素材（一次性腳本，執行後檔案落地即可，不用保留腳本檔）：

```python
import cv2
import numpy as np
import os

def load(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)

# 新模板：倒數圖示（不含永久計數圖示），bbox 由像素差分實測鎖定
active = load("logs/d5_active.png")
template = active[1010:1068, 1676:1734]
cv2.imencode(".png", template)[1].tofile("assets/boost_active.png")

# 三態 fixture：裁新 boost_indicator_region＝(1150,935,590,145) → x:1150-1740, y:935-1080
os.makedirs("tests/fixtures/boost", exist_ok=True)
region_map = {
    "before_only_count.png": "logs/d5_before.png",
    "active_47.png": "logs/d5_active.png",
    "active_61.png": "logs/d5_expired.png",
}
for out_name, src in region_map.items():
    img = load(src)
    crop = img[935:1080, 1150:1740]
    cv2.imencode(".png", crop)[1].tofile(f"tests/fixtures/boost/{out_name}")

print("done")
```

- [ ] 跑測試確認通過：
  ```
  python -m pytest tests/test_boost_fixtures.py -q
  ```

- [ ] 跑全套：
  ```
  python -m pytest -q
  ```

- [ ] commit（`assets/boost_active.png` 是 gitignored，不會被加進去；只 commit 測試與 fixture）：
  ```
  git add tests/test_boost_fixtures.py tests/fixtures/boost/
  git commit -m "$(cat <<'EOF'
  fix(boost): D5 新增永久計數圖示適配——新模板＋三態回歸 fixtures

  boost_indicator_region 已在前一個 commit 排除永久計數圖示；本次換新模板
  （倒數圖示裁圖）並鎖住「只有計數=該補／計數+倒數=生效中」兩態不誤判。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 9: 實機校準與驗證（人工檢查清單）

本 Task 沒有可自動化的程式碼變更，前 8 個 Task 完成、`python -m pytest -q` 全綠後才進行。
需要實機開著 Roblox（REX），依序執行下列檢查；每項標明「若不符預期要調哪個 config 欄位」。

- [ ] **Movement Mode 雙向切換**：手動把遊戲內 Movement Mode 設回 `Default (Keyboard)`，
  呼叫（或觸發會呼叫 `_set_movement_mode` 的路徑，例如啟動 bot）確認能切到 `Click to Move`；
  再手動確認能切回 `Default (Keyboard)`。
  - 若 Esc 後 `menu_open` 判 False：檢查 `cfg.menu_panel_region` 是否涵蓋分頁列（People/Settings/...）。
  - 若點了 Settings 分頁沒反應：檢查 `cfg.menu_fuzzy_min_ratio` 是否太嚴（OCR 讀到的文字有雜訊時降低）。
  - 若捲動方向跟預期相反（該往下捲反而往上）：對調 `cfg.menu_scroll_amount` 正負號。
  - 若點右箭頭 3 次仍沒切到位：確認 `cfg.menu_arrow_right_x` 與該次讀到的 `row_y` 是否真的點在箭頭上
    （可用 R 鍵取樣視窗截圖比對，或暫時把 `menu_arrow_settle_s` 調大排除「畫面還沒更新就讀值」）。

- [ ] **聊天框開合**：手動收合聊天框後啟動 bot（或呼叫 `_ensure_chat_open`），確認能自動點開；
  再手動開啟聊天框後啟動，確認判斷為「已開啟」不會誤點導致意外收合。
  - 若誤判：用當下截圖裁 `cfg.chat_input_region` 存進 `tests/fixtures/chat_ui/` 補樣本，
    調整 `cfg.chat_input_phrases`／region 邊界後重跑 `tests/test_chat_ui_fixtures.py`。

- [ ] **D5 boost 偵測**：讓一輪 D5 buff 到期，觀察 bot 是否在到期後 `boost_check_interval_s`
  等級的延遲內重新按 D5（比照 `docs/incidents.md` 過去 boost 延遲的量測方式，看 `actions.log`）。
  同時確認**從未用過 D5 的乾淨畫面**（新伺服器剛進場）不會被誤判成「生效中」——這是 spec
  提到「今天沒截到」的第三態，補一張截圖進 `tests/fixtures/boost/` 並依樣加一條
  `test_no_icon_state_treated_as_needs_refresh` 測試（預期 `find_template_edges` 回 `None`）。

- [ ] **REENTRY 全流程 dry-run**：觸發一次真實的礦坑重置（或等待自然重置），確認：
  1. 進 REENTRY 時看到 log「無法切換至 Click to Move」不出現（代表切換成功）；
  2. 面板掃描/導航/點層級按鈕全程用 Click to Move 正常運作（沿用既有 REENTRY 驗證，非本次改動範圍）；
  3. 進礦驗證成功、回 MINING 前 log 看到 Movement Mode 已切回、且接下來 `init_mining_sequence`
     的 W+左鍵挖礦動作確實生效（角色真的在挖，不是站著不動）；
  4. 手動測試「reroll 用盡交人工」路徑（連續讓幾輪面板掃描失敗，或直接調低
     `cfg.reentry_max_attempts` 成 1 方便測）：確認交人工前 log 出現 best-effort 切回嘗試，
     且即使切回失敗（可暫時把 `movement_mode_mining` 改成打錯字的值來製造失敗）NEEDS_HUMAN
     通知仍正常送出，不會被擋住。

- [ ] 全部檢查通過後，把上述任何有調整的 config 值連同這份檢查記錄一併 commit（若有變更）：
  ```
  git add miningbot/config.py
  git commit -m "$(cat <<'EOF'
  chore(config): 選單前置切換/D5適配 實機校準微調

  依 docs/superpowers/plans/2026-07-08-menu-preflight-boost.md Task 9 實機檢查結果調整。

  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  EOF
  )"
  ```
