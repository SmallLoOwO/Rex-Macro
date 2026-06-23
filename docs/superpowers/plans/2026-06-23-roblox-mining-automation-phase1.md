# Roblox 挖礦自動化（Phase One）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Python 重寫 Roblox 挖礦掛機巨集，加入「音訊偵測 chill → 自動採集稀有礦（D2 掃描 → 水平對準 → D3 → 雙重確認）→ 失敗轉人工」與卡住偵測，並預留 Discord 事件掛接點。

**Architecture:** 單一程式、三狀態機（MINING / HARVESTING / NEEDS_HUMAN）。主迴圈每約 50ms 擷取一幀畫面，由純函式決定動作；I/O（截圖、音訊、按鍵、OCR）封裝在薄模組後面，核心決策邏輯（狀態轉換、對準計算、事件分派）為純函式以便 TDD。

**Tech Stack:** Python 3.11+、mss（截圖）、opencv-python + numpy（影像）、pyaudiowpatch + scipy（音訊 loopback 與交叉相關）、pytesseract + Tesseract（OCR）、pydirectinput（按鍵/滑鼠）、keyboard（全域熱鍵）、pytest（測試）。

**為何這樣切分測試**：影像/音訊/按鍵/視窗都是與真實遊戲耦合的副作用，無法用單元測試斷言「遊戲真的被挖到」。因此策略是：**把可決定性的邏輯抽成純函式做嚴格 TDD**（狀態轉換、對準向量計算、片語比對、交叉相關門檻、事件分派表），把**與遊戲耦合的薄封裝層用真實素材的整合測試 + 明確的手動校準/驗證程序**涵蓋。每個 task 標明屬於哪一類。

---

## File Structure

```
miningbot/
  __init__.py
  config.py          # 所有座標、顏色、容差、超時、熱鍵、路徑（dataclass）
  events.py          # EventLog 統一事件介面（Phase 2 接 Discord）
  states.py          # State enum + 純函式狀態轉換 decide_transition()
  geometry.py        # 純函式：對準向量、垂直極端判定、區域換算
  capture.py         # mss 截圖 + Roblox 視窗定位（薄封裝）
  audio.py           # loopback 擷取 + chill 交叉相關偵測（核心比對為純函式）
  vision.py          # opencv 模板比對 + 礦物標記定位 + 輪廓存在判定
  ocr.py             # pytesseract 讀區域 + 片語比對（比對為純函式）
  input_control.py   # pydirectinput 薄封裝（送按鍵/滑鼠）
  miner.py           # MINING 狀態行為（事件分派、視窗復原、卡住偵測）
  harvester.py       # HARVESTING 狀態行為（掃描→對準→D3→驗證）
  calibrate.py       # 一次性校準工具
  main.py            # 狀態機主迴圈 + 全域熱鍵
assets/
  chill_reference.wav  # 由使用者的 mp3 轉檔而來的比對樣本
tests/
  fixtures/            # 測試用截圖/音訊片段
  test_events.py
  test_states.py
  test_geometry.py
  test_vision.py
  test_ocr.py
  test_audio.py
  test_miner.py
  test_harvester.py
requirements.txt
README.md
```

每個檔案單一職責；核心決策（states / geometry / 比對函式）與副作用（capture / audio I/O / input）分離。

---

## Task 1: 專案骨架與依賴

**Files:**
- Create: `requirements.txt`
- Create: `README.md`
- Create: `miningbot/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: 建立 requirements.txt**

```
mss==9.0.1
opencv-python==4.10.0.84
numpy==2.1.2
pyaudiowpatch==0.2.12.7
scipy==1.14.1
pytesseract==0.3.13
pydirectinput==1.0.4
keyboard==0.13.5
pytest==8.3.3
```

- [ ] **Step 2: 建立 README.md 安裝步驟**

````markdown
# Roblox 挖礦自動化

## 安裝
1. 安裝 Python 3.11+（python.org，勾選 "Add Python to PATH"）
2. 安裝 Tesseract OCR：下載 UB-Mannheim build，安裝後記下路徑（預設 `C:\Program Files\Tesseract-OCR\tesseract.exe`），填入 `miningbot/config.py` 的 `tesseract_path`
3. `pip install -r requirements.txt`
4. 把 chill 音檔轉成 `assets/chill_reference.wav`（見下方）
5. 執行校準：`python -m miningbot.calibrate`
6. 啟動：`python -m miningbot.main`

## 熱鍵
- F8：暫停 / 恢復
- F9：NEEDS_HUMAN 狀態下，處理完按此恢復挖礦
- F12：緊急停止並結束
````

- [ ] **Step 3: 建立空套件檔**

`miningbot/__init__.py` 與 `tests/__init__.py` 寫入單行註解 `# package marker`。

- [ ] **Step 4: 驗證 pytest 可執行**

Run: `pytest -q`
Expected: `no tests ran`（無錯誤，代表環境就緒）

- [ ] **Step 5: Commit**

```bash
git add requirements.txt README.md miningbot/__init__.py tests/__init__.py
git commit -m "chore: scaffold project structure and dependencies"
```

---

## Task 2: config.py 集中設定

**Files:**
- Create: `miningbot/config.py`

純資料，無邏輯。座標為「1920×1080 視窗化」初始值，校準後覆寫。

- [ ] **Step 1: 寫設定 dataclass**

```python
from dataclasses import dataclass, field

@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int

@dataclass
class Config:
    # 視窗
    window_title: str = "Roblox"
    screen_w: int = 1920
    screen_h: int = 1080

    # 偵測區域（視窗內相對座標，校準後覆寫）
    chill_text_region: Region = field(default_factory=lambda: Region(660, 20, 600, 60))
    chat_region: Region = field(default_factory=lambda: Region(0, 90, 440, 260))
    boost_indicator_region: Region = field(default_factory=lambda: Region(1380, 940, 430, 90))
    window_focus_pixel: tuple = (10, 940)        # 失焦復原偵測點
    window_focus_color: int = 0x2B2B2B           # 佔位，校準時量測
    slot_pixel: tuple = (1011, 845)
    slot_color: int = 0x232323

    # 音訊
    chill_audio_path: str = "assets/chill_reference.wav"
    audio_match_threshold: float = 0.55          # 交叉相關門檻，實測調
    audio_sample_rate: int = 48000
    audio_window_seconds: float = 1.5

    # 採集
    aim_center_tolerance_px: int = 25            # 準心對準容差
    mouse_aim_gain: float = 0.2                  # 像素偏移→滑鼠相對位移的縮放（校準時調，避免過衝）
    vertical_extreme_ratio: float = 0.35         # 標記 y 偏離中心超過此比例→頭頂/腳下
    max_aim_rotations: int = 8                   # 水平轉視角上限
    harvest_verify_timeout_s: float = 6.0
    max_harvest_attempts: int = 3

    # 卡住
    stuck_timeout_s: float = 60.0
    stuck_frame_diff_threshold: float = 2.0      # 平均像素差低於此視為無變化

    # OCR
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    chill_phrases: tuple = (
        "a chill goes down your spine",
        "your heart skips a beat",
    )
    found_keywords: tuple = ("has found", "found a")

    # 熱鍵
    hotkey_pause: str = "f8"
    hotkey_resume_human: str = "f9"
    hotkey_quit: str = "f12"

    # Discord（Phase 2 預留）
    discord_webhook_url: str = ""

DEFAULT = Config()
```

- [ ] **Step 2: 驗證可載入**

Run: `python -c "from miningbot.config import DEFAULT; print(DEFAULT.window_title, DEFAULT.max_harvest_attempts)"`
Expected: `Roblox 3`

- [ ] **Step 3: Commit**

```bash
git add miningbot/config.py
git commit -m "feat: add centralized config"
```

---

## Task 3: events.py 事件記錄（TDD，純邏輯）

**Files:**
- Create: `miningbot/events.py`
- Test: `tests/test_events.py`

Phase 1 只記憶體 + 檔案；Discord 留 hook（`_sinks` 清單）。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_events.py
from miningbot.events import EventLog

def test_log_event_records_type_and_meta():
    log = EventLog()
    log.log("RARE_FOUND", mineral="Spectral 4FA208", tier="Spectral")
    assert len(log.records) == 1
    rec = log.records[0]
    assert rec.type == "RARE_FOUND"
    assert rec.meta["mineral"] == "Spectral 4FA208"
    assert rec.timestamp > 0

def test_sinks_are_called():
    seen = []
    log = EventLog()
    log.add_sink(lambda rec: seen.append(rec.type))
    log.log("STUCK", reason="no progress")
    assert seen == ["STUCK"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_events.py -v`
Expected: FAIL（`ModuleNotFoundError: miningbot.events`）

- [ ] **Step 3: 實作**

```python
# miningbot/events.py
import time
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class EventRecord:
    type: str
    timestamp: float
    meta: dict = field(default_factory=dict)

class EventLog:
    def __init__(self):
        self.records: list[EventRecord] = []
        self._sinks: list[Callable[[EventRecord], None]] = []

    def add_sink(self, sink: Callable[[EventRecord], None]) -> None:
        self._sinks.append(sink)

    def log(self, type_: str, **meta) -> EventRecord:
        rec = EventRecord(type=type_, timestamp=time.time(), meta=meta)
        self.records.append(rec)
        for sink in self._sinks:
            sink(rec)
        return rec
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_events.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/events.py tests/test_events.py
git commit -m "feat: add EventLog with sink hooks"
```

---

## Task 4: geometry.py 對準計算（TDD，純函式）

**Files:**
- Create: `miningbot/geometry.py`
- Test: `tests/test_geometry.py`

這是採集對準的數學核心，必須嚴格 TDD。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_geometry.py
from miningbot.geometry import aim_decision

# 畫面中心 (960, 540)，容差 25，垂直極端比例 0.35（=> |dy|>540*0.35=189 視為極端）
CENTER = (960, 540)

def test_marker_centered_means_fire():
    d = aim_decision((965, 545), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "FIRE"

def test_marker_left_means_rotate_left():
    d = aim_decision((300, 540), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "ROTATE_LEFT"

def test_marker_right_means_rotate_right():
    d = aim_decision((1600, 540), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "ROTATE_RIGHT"

def test_marker_near_horizontal_uses_mouse_fine_aim():
    # 水平偏差小（在一次轉視角的視野內），垂直在範圍內 → 用滑鼠微調
    d = aim_decision((1000, 560), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "MOUSE_AIM"
    assert d.dx == 40 and d.dy == 20

def test_vertical_extreme_means_human():
    d = aim_decision((960, 760), CENTER, tol_px=25, vertical_ratio=0.35, half_h=540)
    assert d.action == "HUMAN"  # dy=220 > 189
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_geometry.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作**

```python
# miningbot/geometry.py
from dataclasses import dataclass

# 一次 `.`/`,` 轉 45°；在 1920 寬、~70° 水平視野下，約佔畫面 0.64 寬。
# 超過此門檻才用整段轉視角，否則用滑鼠微調。
ROTATE_THRESHOLD_PX = 480

@dataclass
class AimDecision:
    action: str          # FIRE | ROTATE_LEFT | ROTATE_RIGHT | MOUSE_AIM | HUMAN
    dx: int = 0
    dy: int = 0

def aim_decision(marker, center, tol_px, vertical_ratio, half_h) -> AimDecision:
    mx, my = marker
    cx, cy = center
    dx = mx - cx
    dy = my - cy

    # 垂直極端（頭頂/腳下）→ 人工
    if abs(dy) > half_h * vertical_ratio:
        return AimDecision("HUMAN")

    # 已對準
    if abs(dx) <= tol_px and abs(dy) <= tol_px:
        return AimDecision("FIRE")

    # 水平偏差大 → 整段轉視角 45°
    if dx <= -ROTATE_THRESHOLD_PX:
        return AimDecision("ROTATE_LEFT")
    if dx >= ROTATE_THRESHOLD_PX:
        return AimDecision("ROTATE_RIGHT")

    # 否則滑鼠微調
    return AimDecision("MOUSE_AIM", dx=dx, dy=dy)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_geometry.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/geometry.py tests/test_geometry.py
git commit -m "feat: add aim decision geometry"
```

---

## Task 5: states.py 狀態轉換（TDD，純函式）

**Files:**
- Create: `miningbot/states.py`
- Test: `tests/test_states.py`

把「每幀觀察 → 下一狀態」抽成純函式，與 I/O 無關。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_states.py
from miningbot.states import State, Observation, decide_transition

def obs(**kw):
    base = dict(chill_audio=False, chill_text=False, harvest_done=False,
                harvest_failed=False, human_cleared=False)
    base.update(kw)
    return Observation(**base)

def test_mining_to_harvesting_requires_audio_and_text():
    assert decide_transition(State.MINING, obs(chill_audio=True, chill_text=True)) == State.HARVESTING

def test_mining_audio_only_stays_mining():
    # 只有音訊、OCR 未確認 → 不接管（防誤判）
    assert decide_transition(State.MINING, obs(chill_audio=True, chill_text=False)) == State.MINING

def test_harvesting_done_returns_to_mining():
    assert decide_transition(State.HARVESTING, obs(harvest_done=True)) == State.MINING

def test_harvesting_failed_goes_human():
    assert decide_transition(State.HARVESTING, obs(harvest_failed=True)) == State.NEEDS_HUMAN

def test_human_stays_until_cleared():
    assert decide_transition(State.NEEDS_HUMAN, obs()) == State.NEEDS_HUMAN
    assert decide_transition(State.NEEDS_HUMAN, obs(human_cleared=True)) == State.MINING
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_states.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作**

```python
# miningbot/states.py
from dataclasses import dataclass
from enum import Enum

class State(Enum):
    MINING = "MINING"
    HARVESTING = "HARVESTING"
    NEEDS_HUMAN = "NEEDS_HUMAN"

@dataclass
class Observation:
    chill_audio: bool
    chill_text: bool
    harvest_done: bool
    harvest_failed: bool
    human_cleared: bool

def decide_transition(state: State, o: Observation) -> State:
    if state is State.MINING:
        if o.chill_audio and o.chill_text:   # 雙重確認才接管
            return State.HARVESTING
        return State.MINING
    if state is State.HARVESTING:
        if o.harvest_failed:
            return State.NEEDS_HUMAN
        if o.harvest_done:
            return State.MINING
        return State.HARVESTING
    if state is State.NEEDS_HUMAN:
        return State.MINING if o.human_cleared else State.NEEDS_HUMAN
    return state
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_states.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/states.py tests/test_states.py
git commit -m "feat: add state machine transitions"
```

---

## Task 6: ocr.py 片語比對（TDD 純函式 + 薄封裝）

**Files:**
- Create: `miningbot/ocr.py`
- Test: `tests/test_ocr.py`

OCR 讀字是副作用，但「文字 → 是否含片語」是純函式，先 TDD 它。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_ocr.py
from miningbot.ocr import contains_phrase, contains_any

def test_contains_phrase_case_insensitive_and_fuzzy():
    text = "A CHILL goes  down your spine..."
    assert contains_phrase(text, "a chill goes down your spine")

def test_contains_phrase_rejects_other_text():
    text = "manzana rerolled the event to The Firewall!"
    assert not contains_phrase(text, "a chill goes down your spine")

def test_contains_any_matches_found_keywords():
    text = "ImGoc52 has found Equalizosity"
    assert contains_any(text, ("has found", "found a"))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_ocr.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作（純函式 + 薄 OCR 封裝）**

```python
# miningbot/ocr.py
import re
import numpy as np

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()

def contains_phrase(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)

def contains_any(text: str, phrases) -> bool:
    n = _normalize(text)
    return any(_normalize(p) in n for p in phrases)

def read_text(image_bgr: np.ndarray, tesseract_path: str | None = None) -> str:
    """薄封裝：對已裁切的區域影像做 OCR。整合測試覆蓋。"""
    import pytesseract
    import cv2
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return pytesseract.image_to_string(gray)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_ocr.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/ocr.py tests/test_ocr.py
git commit -m "feat: add OCR phrase matching"
```

---

## Task 7: audio.py chill 偵測（TDD，交叉相關純函式）

**Files:**
- Create: `miningbot/audio.py`
- Test: `tests/test_audio.py`

核心是「一段音訊緩衝 vs 參考樣本」的正規化交叉相關，可完全 TDD（用合成訊號）。loopback 擷取是薄封裝。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_audio.py
import numpy as np
from miningbot.audio import match_score, detect

def test_match_score_high_for_same_signal():
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = np.concatenate([np.zeros(1000, np.float32), ref, np.zeros(1000, np.float32)])
    assert match_score(buf, ref) > 0.9

def test_match_score_low_for_noise():
    rng = np.random.default_rng(0)
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = rng.standard_normal(6000).astype(np.float32)
    assert match_score(buf, ref) < 0.5

def test_detect_uses_threshold():
    # detect 就是 score >= threshold；用實際分數兩側的門檻驗證，
    # 不假設確切分數（乾淨嵌入訊號分數本來就接近 1.0）。
    ref = np.sin(np.linspace(0, 50, 4000)).astype(np.float32)
    buf = np.concatenate([np.zeros(500, np.float32), ref])
    score = match_score(buf, ref)
    assert detect(buf, ref, threshold=score - 0.01) is True
    assert detect(buf, ref, threshold=score + 0.01) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_audio.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作**

```python
# miningbot/audio.py
import numpy as np
from scipy.signal import correlate

def match_score(buffer: np.ndarray, reference: np.ndarray) -> float:
    """參考樣本在緩衝中的最大正規化交叉相關 (0..1)。"""
    b = buffer.astype(np.float64)
    r = reference.astype(np.float64)
    b -= b.mean()
    r -= r.mean()
    if np.linalg.norm(b) == 0 or np.linalg.norm(r) == 0:
        return 0.0
    corr = correlate(b, r, mode="valid")
    denom = np.linalg.norm(r) * np.sqrt(
        correlate(b**2, np.ones_like(r), mode="valid")
    )
    denom[denom == 0] = 1e-9
    return float(np.max(np.abs(corr / denom)))

def detect(buffer: np.ndarray, reference: np.ndarray, threshold: float) -> bool:
    return match_score(buffer, reference) >= threshold


class ChillListener:
    """薄封裝：背景擷取喇叭 loopback，提供 latest_score()。整合測試/校準覆蓋。"""
    def __init__(self, reference: np.ndarray, sample_rate: int, window_seconds: float):
        self.reference = reference
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_seconds)
        self._buf = np.zeros(self.window, np.float32)

    def feed(self, chunk: np.ndarray) -> None:
        chunk = chunk.astype(np.float32)
        self._buf = np.concatenate([self._buf, chunk])[-self.window:]

    def latest_score(self) -> float:
        return match_score(self._buf, self.reference)


def load_reference(path: str) -> tuple[np.ndarray, int]:
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float32), sr
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_audio.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/audio.py tests/test_audio.py
git commit -m "feat: add chill audio cross-correlation detection"
```

---

## Task 8: vision.py 模板比對與標記定位（TDD with fixtures）

**Files:**
- Create: `miningbot/vision.py`
- Test: `tests/test_vision.py`
- Create: `tests/fixtures/` 內合成測試影像（測試內以程式產生，不需外部檔）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_vision.py
import numpy as np
from miningbot.vision import find_template, template_present

def _scene_with_patch(patch, at):
    scene = np.zeros((300, 400, 3), np.uint8)
    y, x = at
    ph, pw = patch.shape[:2]
    scene[y:y+ph, x:x+pw] = patch
    return scene

def test_find_template_returns_center():
    patch = np.full((20, 20, 3), 200, np.uint8)
    scene = _scene_with_patch(patch, at=(100, 150))
    loc = find_template(scene, patch, threshold=0.9)
    assert loc == (160, 110)  # center x=150+10, y=100+10

def test_find_template_missing_returns_none():
    patch = np.full((20, 20, 3), 200, np.uint8)
    scene = np.zeros((300, 400, 3), np.uint8)
    assert find_template(scene, patch, threshold=0.9) is None

def test_template_present_bool():
    patch = np.full((20, 20, 3), 123, np.uint8)
    scene = _scene_with_patch(patch, at=(50, 50))
    assert template_present(scene, patch, threshold=0.9) is True

def test_pixel_matches_within_tolerance():
    from miningbot.vision import pixel_matches
    scene = np.zeros((100, 100, 3), np.uint8)
    scene[50, 40] = (43, 43, 43)  # BGR
    assert pixel_matches(scene, (40, 50), 0x2B2B2B, tol=5) is True
    assert pixel_matches(scene, (40, 50), 0x000000, tol=5) is False

def test_frame_mean_diff_zero_for_identical():
    from miningbot.vision import frame_mean_diff
    a = np.full((10, 10, 3), 100, np.uint8)
    assert frame_mean_diff(a, a.copy()) == 0.0
    b = np.full((10, 10, 3), 110, np.uint8)
    assert frame_mean_diff(a, b) == 10.0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_vision.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作**

```python
# miningbot/vision.py
import cv2
import numpy as np

def find_template(scene_bgr, template_bgr, threshold: float):
    """回傳模板在 scene 的中心座標 (x, y)，找不到回 None。"""
    res = cv2.matchTemplate(scene_bgr, template_bgr, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None
    th, tw = template_bgr.shape[:2]
    return (max_loc[0] + tw // 2, max_loc[1] + th // 2)

def template_present(scene_bgr, template_bgr, threshold: float) -> bool:
    return find_template(scene_bgr, template_bgr, threshold) is not None

def load_template(path: str):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img

def pixel_matches(scene_bgr, xy, rgb_hex: int, tol: int) -> bool:
    """指定點顏色是否接近 rgb_hex（容差 tol，逐通道）。scene 為 BGR。"""
    x, y = xy
    b, g, r = (int(c) for c in scene_bgr[y, x])
    R = (rgb_hex >> 16) & 0xFF
    G = (rgb_hex >> 8) & 0xFF
    B = rgb_hex & 0xFF
    return abs(r - R) <= tol and abs(g - G) <= tol and abs(b - B) <= tol

def frame_mean_diff(a_bgr, b_bgr) -> float:
    """兩幀平均絕對像素差，用於卡住偵測。"""
    return float(np.mean(np.abs(a_bgr.astype(np.int16) - b_bgr.astype(np.int16))))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_vision.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/vision.py tests/test_vision.py
git commit -m "feat: add template matching and marker location"
```

---

## Task 9: capture.py 截圖與視窗定位（薄封裝 + 手動驗證）

**Files:**
- Create: `miningbot/capture.py`

與 OS 耦合，無單元測試；提供手動驗證腳本。

- [ ] **Step 1: 實作**

```python
# miningbot/capture.py
import mss
import numpy as np

def grab(region=None) -> np.ndarray:
    """擷取整個主螢幕或指定區域 dict(top,left,width,height)，回 BGR ndarray。"""
    with mss.mss() as sct:
        mon = region or sct.monitors[1]
        shot = sct.grab(mon)
        arr = np.array(shot)            # BGRA
        return arr[:, :, :3][:, :, ::-1].copy()  # -> RGB? 轉成 BGR 供 cv2

def crop(image_bgr, region):
    """region: miningbot.config.Region"""
    return image_bgr[region.y:region.y + region.h, region.x:region.x + region.w]
```

> 註：mss 取得為 BGRA；上行轉成 cv2 慣用的 BGR。實作時以 `cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)` 亦可，擇一即可，並在 Step 2 目視確認顏色正確。

- [ ] **Step 2: 手動驗證**

Run: `python -c "import cv2; from miningbot.capture import grab; cv2.imwrite('snap.png', grab())"`
開啟 `snap.png` 確認：擷取到完整畫面、顏色正確（不是藍紅顛倒）。若顏色顛倒，改用 `cv2.cvtColor`。

- [ ] **Step 3: Commit**

```bash
git add miningbot/capture.py
git commit -m "feat: add screen capture"
```

---

## Task 10: input_control.py 按鍵/滑鼠封裝（薄封裝 + 手動驗證）

**Files:**
- Create: `miningbot/input_control.py`

- [ ] **Step 1: 實作**

```python
# miningbot/input_control.py
import time
import pydirectinput

pydirectinput.PAUSE = 0.01

def key_press(key: str, delay: float = 0.05):
    pydirectinput.press(key)
    time.sleep(delay)

def key_down(key: str):
    pydirectinput.keyDown(key)

def key_up(key: str):
    pydirectinput.keyUp(key)

def mouse_down():
    pydirectinput.mouseDown()

def mouse_up():
    pydirectinput.mouseUp()

def mouse_click(button: str = "left"):
    pydirectinput.click(button=button)

def mouse_move_rel(dx: int, dy: int):
    pydirectinput.moveRel(dx, dy, relative=True)

# 視角轉動：'.' 向右 45°、',' 向左 45°（對應原巨集 KeyCode190/188）
def rotate_right():
    key_press(".")

def rotate_left():
    key_press(",")
```

- [ ] **Step 2: 手動驗證**

開記事本，Run: `python -c "import time; time.sleep(2); from miningbot.input_control import key_press; key_press('h'); key_press('i')"`
切到記事本，2 秒內應看到自動輸入「hi」。確認 pydirectinput 能送鍵。

- [ ] **Step 3: Commit**

```bash
git add miningbot/input_control.py
git commit -m "feat: add input control wrapper"
```

---

## Task 11: miner.py MINING 行為（TDD 分派邏輯 + 整合）

**Files:**
- Create: `miningbot/miner.py`
- Test: `tests/test_miner.py`

把「這一幀偵測到哪些彈窗 → 該做哪個道具動作」抽成純函式 `dispatch_event()` 做 TDD；實際送鍵在 `handle_mining()` 整合。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_miner.py
from miningbot.miner import dispatch_event, EventFlags

def flags(**kw):
    base = dict(boost_expired=False, activity_event=False, scan_event=False,
                cave_event=False, window_unfocused=False)
    base.update(kw)
    return EventFlags(**base)

def test_window_unfocused_has_top_priority():
    assert dispatch_event(flags(window_unfocused=True, boost_expired=True)) == "REFOCUS"

def test_boost_expired_uses_d5():
    assert dispatch_event(flags(boost_expired=True)) == "USE_D5"

def test_activity_event_uses_d4():
    assert dispatch_event(flags(activity_event=True)) == "USE_D4"

def test_no_event_returns_none():
    assert dispatch_event(flags()) is None

def test_priority_order_refocus_over_d4():
    assert dispatch_event(flags(window_unfocused=True, activity_event=True)) == "REFOCUS"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_miner.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作（分派純函式 + 整合行為）**

```python
# miningbot/miner.py
from dataclasses import dataclass
from . import input_control as ic

@dataclass
class EventFlags:
    boost_expired: bool
    activity_event: bool
    scan_event: bool
    cave_event: bool
    window_unfocused: bool

def dispatch_event(f: EventFlags):
    """回傳該幀要執行的動作標籤，優先序固定。"""
    if f.window_unfocused:
        return "REFOCUS"
    if f.cave_event:
        return "CAVE"
    if f.scan_event:
        return "SCAN"
    if f.boost_expired:
        return "USE_D5"
    if f.activity_event:
        return "USE_D4"
    return None

def init_mining_sequence():
    """移植原巨集初始化：放開狀態→調視角→雙 Shift→挖礦。"""
    ic.key_up("w"); ic.mouse_up()
    ic.rotate_right(); ic.rotate_left()
    ic.key_press("shift"); ic.key_press("shift")
    ic.key_down("w"); ic.mouse_down()

def use_boost():           # D5：放開左鍵→D5→點擊→D1→續挖
    ic.mouse_up(); ic.key_press("5"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

def use_activity():        # D4：放開左鍵→D4→點擊→D1→續挖
    ic.mouse_up(); ic.key_press("4"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

def use_scan():            # SCAN 變體：D2→點擊→Z→D5→點擊→D1→續挖（對照 boost+scan .mcr）
    ic.mouse_up(); ic.key_press("2"); ic.mouse_click(); ic.key_press("z")
    ic.key_press("5"); ic.mouse_click(); ic.key_press("1"); ic.mouse_down()

def handle_cave():         # CAVE 變體：F 進入→等待→旋轉視角+X 退出（對照 boost+cave .mcr）
    import time
    ic.key_press("f"); time.sleep(3.0)
    ic.rotate_right(); ic.rotate_right(); ic.key_press("x"); time.sleep(1.0)
    ic.rotate_left(); ic.rotate_left()
    ic.key_down("w"); ic.mouse_down()
```

> 註：`use_scan` / `handle_cave` 的按鍵序列直接移植自現有 `boost event and scan.mcr` 與 `boost event and cave.mcr`；整合驗證（Task 13）時對照原巨集逐步確認等效，必要時微調 `time.sleep` 秒數。

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_miner.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/miner.py tests/test_miner.py
git commit -m "feat: add mining event dispatch and actions"
```

---

## Task 12: harvester.py HARVESTING 行為（TDD 計畫器 + 整合）

**Files:**
- Create: `miningbot/harvester.py`
- Test: `tests/test_harvester.py`

把「目前標記座標 + 已嘗試次數 → 下一步」抽成純函式 `next_harvest_step()`，包住 `geometry.aim_decision` 並加上嘗試上限/超時。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_harvester.py
from miningbot.harvester import next_harvest_step, HarvestState
from miningbot.config import DEFAULT

def test_no_marker_yet_waits():
    st = HarvestState(rotations=0, elapsed_s=0.5)
    step = next_harvest_step(marker=None, state=st, cfg=DEFAULT)
    assert step.action == "WAIT_SCAN"

def test_timeout_without_success_fails_to_human():
    st = HarvestState(rotations=0, elapsed_s=DEFAULT.harvest_verify_timeout_s + 1)
    step = next_harvest_step(marker=(960, 540), state=st, cfg=DEFAULT)
    assert step.action == "HUMAN"

def test_too_many_rotations_fails_to_human():
    st = HarvestState(rotations=DEFAULT.max_aim_rotations + 1, elapsed_s=1.0)
    step = next_harvest_step(marker=(100, 540), state=st, cfg=DEFAULT)
    assert step.action == "HUMAN"

def test_centered_marker_fires_d3():
    st = HarvestState(rotations=0, elapsed_s=1.0)
    step = next_harvest_step(marker=(965, 545), state=st, cfg=DEFAULT)
    assert step.action == "FIRE_D3"

def test_vertical_extreme_human():
    st = HarvestState(rotations=0, elapsed_s=1.0)
    step = next_harvest_step(marker=(960, 1000), state=st, cfg=DEFAULT)
    assert step.action == "HUMAN"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `pytest tests/test_harvester.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作**

```python
# miningbot/harvester.py
from dataclasses import dataclass
from .geometry import aim_decision
from . import input_control as ic

@dataclass
class HarvestState:
    rotations: int
    elapsed_s: float

@dataclass
class HarvestStep:
    action: str   # WAIT_SCAN | ROTATE_LEFT | ROTATE_RIGHT | MOUSE_AIM | FIRE_D3 | HUMAN
    dx: int = 0
    dy: int = 0

def next_harvest_step(marker, state: HarvestState, cfg) -> HarvestStep:
    if state.elapsed_s > cfg.harvest_verify_timeout_s:
        return HarvestStep("HUMAN")
    if state.rotations > cfg.max_aim_rotations:
        return HarvestStep("HUMAN")
    if marker is None:
        return HarvestStep("WAIT_SCAN")

    center = (cfg.screen_w // 2, cfg.screen_h // 2)
    d = aim_decision(marker, center, cfg.aim_center_tolerance_px,
                     cfg.vertical_extreme_ratio, cfg.screen_h // 2)
    mapping = {
        "HUMAN": "HUMAN", "FIRE": "FIRE_D3",
        "ROTATE_LEFT": "ROTATE_LEFT", "ROTATE_RIGHT": "ROTATE_RIGHT",
        "MOUSE_AIM": "MOUSE_AIM",
    }
    return HarvestStep(mapping[d.action], dx=d.dx, dy=d.dy)

def start_scan():
    ic.key_up("w"); ic.mouse_up(); ic.key_press("2")  # 停挖 + D2 掃描

def fire_d3():
    ic.key_press("3")
```

- [ ] **Step 4: 跑測試確認通過**

Run: `pytest tests/test_harvester.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add miningbot/harvester.py tests/test_harvester.py
git commit -m "feat: add harvesting step planner"
```

---

## Task 13: main.py 主迴圈與熱鍵（整合 + 手動驗證）

**Files:**
- Create: `miningbot/main.py`

組裝所有模組成狀態機主迴圈，無單元測試，靠手動端到端驗證。

- [ ] **Step 1: 實作主迴圈**

```python
# miningbot/main.py
import time
import winsound
import numpy as np
import keyboard

from .config import DEFAULT as cfg
from .events import EventLog
from .states import State, Observation, decide_transition
from . import capture, vision, ocr, audio, miner, harvester
from . import input_control as ic

def alert(message: str):
    """本機提醒：嗶聲 + 終端訊息（NEEDS_HUMAN / STUCK 用）。"""
    print(f"[ALERT] {message}")
    try:
        winsound.Beep(880, 400); winsound.Beep(660, 400)
    except RuntimeError:
        pass

class Bot:
    def __init__(self):
        self.state = State.MINING
        self.paused = False
        self.human_cleared = False
        self.log = EventLog()
        ref, sr = audio.load_reference(cfg.chill_audio_path)
        self.listener = audio.ChillListener(ref, cfg.audio_sample_rate, cfg.audio_window_seconds)
        self.harvest = harvester.HarvestState(rotations=0, elapsed_s=0.0)
        self._harvest_start = 0.0
        self._prev_frame = None
        self._last_progress = time.time()
        self._stuck_notified = False
        # 模板只在啟動時讀一次（避免每幀讀檔）
        self._templates = {
            name: vision.load_template(f"assets/{name}.png")
            for name in ("marker", "boost_expired", "activity_event",
                         "scan_event", "cave_event")
        }

    def observe(self, frame) -> Observation:
        chill_audio = self.listener.latest_score() >= cfg.audio_match_threshold
        chill_text = False
        if chill_audio:
            region = capture.crop(frame, cfg.chill_text_region)
            text = ocr.read_text(region, cfg.tesseract_path)
            chill_text = ocr.contains_any(text, cfg.chill_phrases)
        return Observation(chill_audio=chill_audio, chill_text=chill_text,
                           harvest_done=False, harvest_failed=False,
                           human_cleared=self.human_cleared)

    def run(self):
        keyboard.add_hotkey(cfg.hotkey_pause, self._toggle_pause)
        keyboard.add_hotkey(cfg.hotkey_resume_human, self._clear_human)
        keyboard.add_hotkey(cfg.hotkey_quit, self._quit)
        self._running = True
        miner.init_mining_sequence()
        while self._running:
            if self.paused:
                time.sleep(0.1); continue
            frame = capture.grab()
            obs = self.observe(frame)
            new_state = decide_transition(self.state, obs)
            if new_state != self.state:
                self.log.log("STATE_CHANGE", from_=self.state.value, to=new_state.value)
                self._on_enter(new_state)
            self.state = new_state
            self._tick(frame)
            time.sleep(0.05)

    def _on_enter(self, s):
        if s is State.HARVESTING:
            self.log.log("RARE_FOUND")
            harvester.start_scan()
            self.harvest = harvester.HarvestState(0, 0.0)
            self._harvest_start = time.time()
        if s is State.NEEDS_HUMAN:
            self.log.log("NEEDS_HUMAN", reason="harvest aim/verify failed")
            ic.key_up("w"); ic.mouse_up()
            alert("需要人工介入：稀有礦採集失敗，請手動處理後按 F9 恢復")
            self.human_cleared = False

    def _tick(self, frame):
        if self.state is State.MINING:
            self._tick_mining(frame)
        elif self.state is State.HARVESTING:
            self._tick_harvest(frame)
        # NEEDS_HUMAN: 等待熱鍵，不動作

    def _tick_mining(self, frame):
        # 1) 偵測事件旗標（像素 + 模板），組成 EventFlags
        flags = miner.EventFlags(
            boost_expired=vision.template_present(
                capture.crop(frame, cfg.boost_indicator_region),
                self._templates["boost_expired"], threshold=0.7),
            activity_event=vision.template_present(
                capture.crop(frame, cfg.chill_text_region),
                self._templates["activity_event"], threshold=0.7),
            scan_event=vision.template_present(
                capture.crop(frame, cfg.boost_indicator_region),
                self._templates["scan_event"], threshold=0.7),
            cave_event=vision.template_present(
                frame, self._templates["cave_event"], threshold=0.7),
            window_unfocused=not vision.pixel_matches(
                frame, cfg.window_focus_pixel, cfg.window_focus_color, tol=12),
        )
        action = miner.dispatch_event(flags)
        if action == "REFOCUS":
            miner.init_mining_sequence()
        elif action == "CAVE":
            miner.handle_cave()
        elif action == "SCAN":
            miner.use_scan()
        elif action == "USE_D5":
            miner.use_boost()
        elif action == "USE_D4":
            miner.use_activity()

        # 2) 卡住偵測：連續無畫面變化超過 stuck_timeout_s
        if self._prev_frame is not None:
            diff = vision.frame_mean_diff(frame, self._prev_frame)
            if diff >= cfg.stuck_frame_diff_threshold or action is not None:
                self._last_progress = time.time()
                self._stuck_notified = False
        self._prev_frame = frame
        if (not self._stuck_notified
                and time.time() - self._last_progress > cfg.stuck_timeout_s):
            self.log.log("STUCK", reason=f"{cfg.stuck_timeout_s}s 無進度")
            alert("腳本可能卡住了")
            self._stuck_notified = True

    def _tick_harvest(self, frame):
        self.harvest.elapsed_s = time.time() - self._harvest_start
        marker = vision.find_template(frame, self._templates["marker"], threshold=0.7)
        step = harvester.next_harvest_step(marker, self.harvest, cfg)
        if step.action == "HUMAN":
            self.state = State.NEEDS_HUMAN; self._on_enter(State.NEEDS_HUMAN); return
        if step.action == "ROTATE_LEFT":
            ic.rotate_left(); self.harvest.rotations += 1
        elif step.action == "ROTATE_RIGHT":
            ic.rotate_right(); self.harvest.rotations += 1
        elif step.action == "MOUSE_AIM":
            ic.mouse_move_rel(int(step.dx * cfg.mouse_aim_gain),
                              int(step.dy * cfg.mouse_aim_gain))
        elif step.action == "FIRE_D3":
            harvester.fire_d3()
            if self._verify_success(frame):
                self.log.log("HARVEST_SUCCESS")
                self.state = State.MINING; miner.init_mining_sequence()

    def _verify_success(self, frame) -> bool:
        chat = capture.crop(frame, cfg.chat_region)
        text = ocr.read_text(chat, cfg.tesseract_path)
        return ocr.contains_any(text, cfg.found_keywords)

    def _toggle_pause(self): self.paused = not self.paused
    def _clear_human(self):
        self.human_cleared = True
    def _quit(self):
        self._running = False

def main():
    Bot().run()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手動端到端驗證**

前置：完成 Task 14 校準、放好 `assets/chill_reference.wav` 與 `assets/marker.png`。
1. 開 Roblox 進遊戲，Run: `python -m miningbot.main`
2. 觀察：MINING 狀態能持續挖礦、D4/D5 在彈窗時觸發。
3. 觸發一次稀有礦（或用喇叭播放 chill 音檔測試音訊觸發），確認進入 HARVESTING、執行掃描與對準。
4. 確認成功時記錄 `HARVEST_SUCCESS` 並回 MINING；失敗時進 NEEDS_HUMAN 並提醒。
5. 按 F8 暫停/恢復、F12 結束，確認熱鍵有效。
記錄每項結果於 commit message 或 issue。

- [ ] **Step 3: Commit**

```bash
git add miningbot/main.py
git commit -m "feat: wire state machine main loop and hotkeys"
```

---

## Task 14: calibrate.py 校準工具（互動式）

**Files:**
- Create: `miningbot/calibrate.py`

協助使用者在自己的解析度下確認區域與顏色，輸出可貼進 `config.py` 的數值。

- [ ] **Step 1: 實作**

```python
# miningbot/calibrate.py
"""一次性校準：擷取畫面，讓使用者用滑鼠框選關鍵區域，印出 Region 數值。"""
import cv2
from .capture import grab

REGIONS = ["chill_text_region", "chat_region", "boost_indicator_region"]

def main():
    frame = grab()
    for name in REGIONS:
        print(f"請框選 {name}，框好按 ENTER，取消按 c")
        r = cv2.selectROI(name, frame[:, :, ::-1], showCrosshair=True)
        cv2.destroyWindow(name)
        x, y, w, h = map(int, r)
        print(f"{name} = Region({x}, {y}, {w}, {h})")
    print("把上面數值貼進 miningbot/config.py 對應欄位。")
    print("另外用截圖工具確認 slot_pixel / window_focus_pixel 的座標與顏色（cv2 BGR）。")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 手動驗證**

開 Roblox，Run: `python -m miningbot.calibrate`
依提示框選三個區域，確認終端印出 `Region(...)` 數值，貼進 `config.py`。

- [ ] **Step 3: Commit**

```bash
git add miningbot/calibrate.py
git commit -m "feat: add interactive calibration tool"
```

---

## Task 15: chill 音檔轉檔說明與資產

**Files:**
- Create: `assets/README.md`

- [ ] **Step 1: 寫資產說明**

````markdown
# assets

- `chill_reference.wav`：chill boom 參考音。由使用者的 mp3 轉檔：
  - 用 ffmpeg：`ffmpeg -i "Achillgoesdownyourspine.mp3.mpeg" -ac 1 -ar 48000 chill_reference.wav`
  - 取最具特徵的 1~2 秒（boom 主體），避免前後靜音過長。
- `marker.png`：D2 掃描後礦物標記的模板截圖（採集時用來定位）。在遊戲掃描後對標記區域截圖裁切。
- `boost_expired.png`：右下角加成效果「已結束」的模板截圖（觸發重新按 D5）。
- `activity_event.png`：頂部中央「D4 控制活動」事件的模板截圖（觸發按 D4）。注意此模板需與 chill 文字明顯不同，避免誤判。
- `scan_event.png`：SCAN 變體事件的模板截圖（觸發 D2/Z/D5 組合）。
- `cave_event.png`：洞穴入口事件的模板截圖（觸發 F 進出洞穴）。

> 只啟用你實際會用到的變體：若不跑 scan/cave，放一張不可能比中的純色小圖即可讓對應偵測恆為 False。
````

- [ ] **Step 2: 產生 wav（需 ffmpeg）**

Run（路徑替換成實際 mp3）:
`ffmpeg -i "C:\Users\puppy\Downloads\Achillgoesdownyourspine.mp3.mpeg" -ac 1 -ar 48000 assets/chill_reference.wav`
Expected: 產生 `assets/chill_reference.wav`

- [ ] **Step 3: Commit**

```bash
git add assets/README.md
git commit -m "docs: add asset preparation instructions"
```

---

## 整體驗證（Definition of Done，Phase One）

- [ ] 所有單元測試通過：`pytest -q`（events / geometry / states / ocr / audio / vision / miner / harvester）
- [ ] 校準完成，`config.py` 區域數值符合實機
- [ ] 端到端：MINING 持續挖礦且 D4/D5 正常；播放 chill 音檔可觸發 HARVESTING；採集成功回 MINING 並記錄、失敗進 NEEDS_HUMAN 並提醒；F8/F9/F12 熱鍵有效
- [ ] D4 活動事件不會誤觸 HARVESTING（音訊 + OCR 雙重把關驗證）

## 後續（Phase Two，另開計畫）

- Discord Webhook 接到 `EventLog.add_sink`，轉發 RARE_FOUND / HARVEST_SUCCESS / NEEDS_HUMAN / STUCK。
- 桌面通知（toast）強化本機提醒。
- 採集成功時擷取礦物名稱（OCR 聊天框）寫入事件 meta。
