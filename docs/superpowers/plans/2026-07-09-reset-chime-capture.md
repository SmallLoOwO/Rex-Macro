# RESET_WAIT 重置完成鈴聲擷取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RESET_WAIT 進入 30 秒後，用相對響度尖峰自動錄下「重置完成鈴聲」的候選短片段，供人工裁成參考 wav（第一階段：只錄不比對）。

**Architecture:** 純邏輯 `AdaptiveSpikeDetector`（EMA 基準線 + 上升緣去抖動，可 TDD）＋薄 I/O `ResetChimeRecorder`（pre/post-roll 滾動緩衝、觸發後存 wav），兩者放 `miningbot/audio.py`。`main.Bot` 把 loopback chunk 扇出給既有 `ChillListener` 與新 recorder，active 旗標由主迴圈依 state＋計時設定。完全不動 chill 安全偵測路徑。

**Tech Stack:** Python、numpy、scipy.io.wavfile（既有 `audio.save_wav`）、pytest。

## Global Constraints

- 純邏輯改動走 TDD（先寫失敗測試）；完成標準＝`python -m pytest -q` 全綠。
- 座標/門檻/秒數全部進 `miningbot/config.py` 的 `DEFAULT`（dataclass 欄位＋行內註解）。
- 不得修改 `ChillListener` 或 chill 偵測行為（零迴歸風險）。
- 不 commit 前不需人工審；本 plan 每個 Task 各自 commit，訊息結尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 目前分支 `feature/optimization-roadmap`（非預設分支），直接在此 commit。
- 環境為 Windows；git 指令走 PowerShell（Bash 工具無 git）。測試指令 `python -m pytest` 兩者皆可。
- 存檔命名沿用 `audiochg_*` 慣例：`logs/snapshots/audio/resetchime_YYYYmmdd_HHMMSS_rmsNNNN.wav`。

---

### Task 1: `AdaptiveSpikeDetector`（純邏輯尖峰偵測器）

**Files:**
- Modify: `miningbot/audio.py`（在 `RisingEdgeDetector` 類別之後新增）
- Test: `tests/test_audio.py`（檔尾新增區塊）

**Interfaces:**
- Consumes: 無（純邏輯）。
- Produces:
  - `class AdaptiveSpikeDetector.__init__(self, spike_factor: float, baseline_alpha: float, min_floor: float, warmup_samples: int, release_factor: float = 0.5)`
  - `AdaptiveSpikeDetector.update(self, rms: float) -> bool`（餵一個 RMS，回傳「這次是否為新尖峰」）
  - `AdaptiveSpikeDetector.baseline`（property → float，目前基準線，供診斷 log）
  - `AdaptiveSpikeDetector.reset(self) -> None`（清基準線/暖機/armed，供下輪 RESET_WAIT 重用）

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_audio.py` 檔尾新增（並把第 2 行 import 補上 `AdaptiveSpikeDetector`）：

```python
# --- AdaptiveSpikeDetector：安靜基準線 + 相對響度尖峰上升緣觸發 -----------------
from miningbot.audio import AdaptiveSpikeDetector


def _mk_detector(spike_factor=3.0, warmup_samples=2, min_floor=1.0, baseline_alpha=0.9):
    return AdaptiveSpikeDetector(spike_factor=spike_factor, baseline_alpha=baseline_alpha,
                                 min_floor=min_floor, warmup_samples=warmup_samples)


def test_spike_triggers_once_after_quiet_baseline():
    d = _mk_detector()
    # 暖機 2 次 + 幾次安靜，基準線 ~1
    for _ in range(5):
        assert d.update(1.0) is False
    # 一記尖峰
    assert d.update(10.0) is True


def test_spike_sustained_loud_triggers_only_once():
    d = _mk_detector()
    for _ in range(5):
        d.update(1.0)
    assert d.update(10.0) is True          # 第一次升起
    assert d.update(10.0) is False         # 持續高檔不重複
    assert d.update(10.0) is False


def test_spike_suppressed_during_warmup():
    d = _mk_detector(warmup_samples=3)
    assert d.update(10.0) is False         # 暖機期內尖峰不觸發
    assert d.update(10.0) is False
    assert d.update(10.0) is False


def test_spike_baseline_not_inflated_by_chime():
    # 鈴聲不得把基準線拉高到後續同樣尖峰被抑制：安靜→尖峰→回安靜(re-arm)→再尖峰 應再觸發
    d = _mk_detector()
    for _ in range(5):
        d.update(1.0)
    assert d.update(10.0) is True
    for _ in range(5):                     # 回落安靜，re-arm、基準線續更回 ~1
        d.update(1.0)
    assert d.update(10.0) is True          # 第二記仍觸發


def test_spike_min_floor_blocks_pure_silence_jitter():
    d = _mk_detector(spike_factor=3.0, min_floor=1.0)
    # 純靜音的微小抖動：rms 都遠小於 min_floor → ratio 恆小 → 不觸發
    for v in [0.01, 0.05, 0.02, 0.08, 0.03, 0.09]:
        assert d.update(v) is False
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_audio.py -k spike -q`
Expected: FAIL（`ImportError` / `AdaptiveSpikeDetector` 未定義）

- [ ] **Step 3: 實作 `AdaptiveSpikeDetector`**

在 `miningbot/audio.py` 的 `RisingEdgeDetector` 類別結尾之後、`def save_wav` 之前插入：

```python
class AdaptiveSpikeDetector:
    """安靜基準線上的「相對響度尖峰」偵測：不需事先知道目標音的絕對音量。

    每次 update() 餵一個 chunk 的 RMS：維護一條 EMA 基準線，當 rms/baseline 達
    spike_factor 時以上升緣語意回報一次（高檔不重複，回落到 release 才 re-arm）。
    專治「一段安靜之後一記清脆鈴聲」——重置完成音效正是這型。純邏輯，有單元測試。

    兩個必防的坑：
      1. 暖機：前 warmup_samples 次只建基準線、一律回 False（否則無基準會誤觸）。
      2. 基準線不被鈴聲自己拉高：ratio 處於高檔（>= release）時凍結 EMA 更新，
         回落才續更——否則鈴聲會把基準線推高、自我抑制或漏掉接連兩聲。
    min_floor 是絕對 RMS 下限，防純靜音時基準線趨近 0、除出假尖峰。
    """
    def __init__(self, spike_factor: float, baseline_alpha: float, min_floor: float,
                 warmup_samples: int, release_factor: float = 0.5):
        self.spike_factor = spike_factor
        self.baseline_alpha = baseline_alpha
        self.min_floor = min_floor
        self.warmup_samples = warmup_samples
        self.release_ratio = spike_factor * release_factor
        self.reset()

    def reset(self) -> None:
        self._baseline = 0.0
        self._count = 0
        self._armed = True

    @property
    def baseline(self) -> float:
        return self._baseline

    def _update_baseline(self, rms: float) -> None:
        if self._count == 1:
            self._baseline = rms                      # 第一個樣本直接當種子
        else:
            a = self.baseline_alpha
            self._baseline = a * self._baseline + (1.0 - a) * rms

    def update(self, rms: float) -> bool:
        self._count += 1
        if self._count <= self.warmup_samples:        # 暖機：只建基準線
            self._update_baseline(rms)
            return False
        ratio = rms / max(self._baseline, self.min_floor)
        if ratio < self.release_ratio:                # 只在低檔更新基準線（凍結防自我抑制）
            self._update_baseline(rms)
        fired = False
        if self._armed and ratio >= self.spike_factor:
            self._armed = False
            fired = True
        elif not self._armed and ratio < self.release_ratio:
            self._armed = True
        return fired
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_audio.py -k spike -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```powershell
git add miningbot/audio.py tests/test_audio.py
git commit -m @'
feat(audio): AdaptiveSpikeDetector——安靜基準線上的相對響度尖峰偵測

EMA 基準線＋上升緣去抖動；暖機期不觸發、高檔凍結基準線防鈴聲自我抑制、
min_floor 擋純靜音抖動。供 RESET_WAIT 重置完成鈴聲擷取用。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 2: `ResetChimeRecorder`（pre/post-roll 存檔器）

**Files:**
- Modify: `miningbot/audio.py`（在 `AdaptiveSpikeDetector` 之後新增）
- Test: `tests/test_audio.py`（檔尾新增區塊）

**Interfaces:**
- Consumes: `AdaptiveSpikeDetector`（Task 1）、`save_wav`（既有）。
- Produces:
  - `class ResetChimeRecorder.__init__(self, sample_rate: int, window_s: float, post_roll_s: float, chunk_seconds: float, detector, out_dir: str, max_clips: int, save_fn=None, log=None, diag=None)`
  - `ResetChimeRecorder.feed(self, chunk: np.ndarray) -> None`（餵一個 loopback chunk）
  - `ResetChimeRecorder.reset(self) -> None`（清緩衝/計數＋`detector.reset()`）
  - `save_fn(path, samples, sample_rate)`：預設 `save_wav`，測試可注入攔截。
  - `log(path, rms)`：每存一個 clip 回呼（可選）。
  - `diag(rms, baseline)`：每 feed 回呼（可選，供主迴圈節流寫 heartbeat）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_audio.py` 檔尾新增：

```python
# --- ResetChimeRecorder：尖峰觸發後 pre/post-roll 存短片段 ----------------------
from miningbot.audio import ResetChimeRecorder


class _StubDetector:
    """在指定的第 N 次 feed（1-based）回報觸發，其餘 False。baseline 固定 0。"""
    def __init__(self, fire_on):
        self.fire_on = set(fire_on)
        self._n = 0
        self.baseline = 0.0
    def update(self, rms):
        self._n += 1
        return self._n in self.fire_on
    def reset(self):
        self._n = 0


def _mk_recorder(detector, saved, **kw):
    # sample_rate=10, window_s=1.0 → 10 樣本；chunk_seconds=0.1, post_roll_s=0.3 → 3 chunk
    def save_fn(path, samples, sr):
        saved.append(samples.copy())
    params = dict(sample_rate=10, window_s=1.0, post_roll_s=0.3, chunk_seconds=0.1,
                  detector=detector, out_dir="/unused", max_clips=20, save_fn=save_fn)
    params.update(kw)
    return ResetChimeRecorder(**params)


def test_recorder_saves_once_with_postroll_containing_spike():
    saved = []
    det = _StubDetector(fire_on=[4])          # 第 4 個 chunk 觸發
    rec = _mk_recorder(det, saved)
    seq = [0.0, 0.0, 0.0, 9.0, 0.0, 0.0, 0.0, 0.0]  # 尖峰在 index3(第4個)
    for v in seq:
        rec.feed(np.array([v], np.float32))
    assert len(saved) == 1                    # 恰存一次
    buf = saved[0]
    assert len(buf) == 10                     # window = sample_rate*window_s
    assert 9.0 in buf                         # 尖峰樣本落在片段內
    assert buf[-1] == 0.0                     # 尾端是 post-roll 的安靜（非切在尖峰當下）


def test_recorder_respects_max_clips():
    saved = []
    det = _StubDetector(fire_on=range(1, 100))   # 每個 chunk 都觸發
    rec = _mk_recorder(det, saved, post_roll_s=0.1, max_clips=2)  # post_roll=1 chunk
    for _ in range(50):
        rec.feed(np.array([5.0], np.float32))
    assert len(saved) == 2                    # 達上限即停


def test_recorder_reset_calls_detector_reset():
    saved = []
    det = _StubDetector(fire_on=[1])
    rec = _mk_recorder(det, saved)
    rec.feed(np.array([1.0], np.float32))
    rec.reset()
    assert det._n == 0                        # detector 已重置
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -m pytest tests/test_audio.py -k recorder -q`
Expected: FAIL（`ImportError` / `ResetChimeRecorder` 未定義）

- [ ] **Step 3: 實作 `ResetChimeRecorder`**

在 `miningbot/audio.py` 的 `AdaptiveSpikeDetector` 之後插入：

```python
class ResetChimeRecorder:
    """RESET_WAIT 期間錄「重置完成鈴聲」候選片段（第一階段：只錄不比對）。

    維護 window_s 滾動緩衝；detector 觸發後不立即存，改設 post_roll 倒數、繼續收
    chunk，倒數歸零才把整條緩衝存檔——存下的片段是「觸發前一段 + 觸發後 post_roll」，
    鈴聲完整落在中段，方便裁 1s 參考。倒數期間再觸發則延長（不把一串鈴聲切兩半）。
    存檔在音訊執行緒 inline 跑（~5ms，比照 _on_audio_event）。
    """
    def __init__(self, sample_rate, window_s, post_roll_s, chunk_seconds, detector,
                 out_dir, max_clips, save_fn=None, log=None, diag=None):
        self.sample_rate = sample_rate
        self.window = int(sample_rate * window_s)
        self.post_roll_chunks = max(1, round(post_roll_s / chunk_seconds))
        self.detector = detector
        self.out_dir = out_dir
        self.max_clips = max_clips
        self._save = save_fn or save_wav
        self._log = log
        self._diag = diag
        self.reset()

    def reset(self):
        self._buf = np.zeros(self.window, np.float32)
        self._countdown = 0
        self._pending_rms = 0.0
        self._clips = 0
        self.detector.reset()

    def feed(self, chunk):
        chunk = np.asarray(chunk, np.float32)
        self._buf = np.concatenate([self._buf, chunk])[-self.window:]   # 滾動窗
        rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
        fired = self.detector.update(rms)
        if self._diag is not None:
            self._diag(rms, self.detector.baseline)
        if fired and self._clips < self.max_clips:
            self._countdown = self.post_roll_chunks    # (重)啟動 post-roll＝延長
            self._pending_rms = rms
        if self._countdown > 0:
            self._countdown -= 1
            if self._countdown == 0:
                self._flush()

    def _flush(self):
        import os, time
        os.makedirs(self.out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.out_dir,
                            f"resetchime_{ts}_rms{int(round(self._pending_rms)):04d}.wav")
        self._save(path, self._buf.copy(), self.sample_rate)
        self._clips += 1
        if self._log is not None:
            self._log(path, self._pending_rms)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python -m pytest tests/test_audio.py -k recorder -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```powershell
git add miningbot/audio.py tests/test_audio.py
git commit -m @'
feat(audio): ResetChimeRecorder——尖峰觸發後 pre/post-roll 存候選片段

滾動緩衝＋觸發後 post_roll 倒數才存，鈴聲落片段中段；max_clips 防洗版、
reset 連 detector 一起清。存 resetchime_*.wav 供人工裁參考。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 3: config 欄位

**Files:**
- Modify: `miningbot/config.py`（音訊區塊 `audio_event_threshold` 那行之後）

**Interfaces:**
- Produces（`config.DEFAULT` 新增欄位，供 Task 4 讀取）：
  `reset_chime_capture: bool`、`reset_chime_arm_delay_s: float`、`reset_chime_spike_factor: float`、
  `reset_chime_baseline_alpha: float`、`reset_chime_min_floor: float`、`reset_chime_window_s: float`、
  `reset_chime_post_roll_s: float`、`reset_chime_warmup_s: float`、`reset_chime_max_clips: int`。

- [ ] **Step 1: 新增欄位**

在 `miningbot/config.py` 的 `audio_event_threshold: float = 0.15 ...` 那行之後插入：

```python
    # 重置完成鈴聲擷取（第一階段：RESET_WAIT 期間只錄候選片段、不比對）
    # 設計：docs/superpowers/specs/2026-07-09-reset-chime-capture-design.md
    reset_chime_capture: bool = True             # 總開關；校準拿到樣本後可關
    reset_chime_arm_delay_s: float = 30.0        # 進 RESET_WAIT 多久後才開始錄（跳過重置開始的雜音）
    reset_chime_spike_factor: float = 3.0        # rms/baseline 達此倍數即觸發（安靜後一記鈴聲＝相對尖峰）
    reset_chime_baseline_alpha: float = 0.9      # 基準線 EMA 係數（越大越慢跟隨；實機再調）
    reset_chime_min_floor: float = 50.0          # 絕對 RMS 下限，防純靜音除以極小值誤觸（int16 值域，實機看 heartbeat log 校）
    reset_chime_window_s: float = 4.0            # 存檔片段總長（秒）
    reset_chime_post_roll_s: float = 1.5         # 觸發後再收多久才存（讓鈴聲落片段中段）
    reset_chime_warmup_s: float = 2.0            # 暖機：頭幾秒只建基準線不觸發
    reset_chime_max_clips: int = 20              # 單輪 RESET_WAIT 存檔上限（防洗版）
```

- [ ] **Step 2: 確認可載入**

Run: `python -c "from miningbot.config import DEFAULT as c; print(c.reset_chime_capture, c.reset_chime_spike_factor, c.reset_chime_max_clips)"`
Expected: `True 3.0 20`

- [ ] **Step 3: Commit**

```powershell
git add miningbot/config.py
git commit -m @'
feat(config): 新增 reset_chime_* 重置鈴聲擷取參數

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

### Task 4: 接線 `main.Bot`（扇出 chunk + active 旗標 + 診斷 log）

**Files:**
- Modify: `miningbot/main.py`（`__init__` 音訊接線處 ~106-116；`_on_enter` RESET_WAIT 分支 ~1758；`_tick` 頂 ~1766；新增三個 helper 方法）

**Interfaces:**
- Consumes: `audio.AdaptiveSpikeDetector`、`audio.ResetChimeRecorder`（Task 1/2）、`config` 欄位（Task 3）。
- Produces（整合行為，非公開 API）：`self._reset_chime_recorder`、`self._reset_chime_active`、`self._reset_wait_since`、`self._last_chime_diag`、方法 `_on_audio_chunk`、`_update_reset_chime_active`、`_on_reset_chime_saved`、`_reset_chime_diag`。

> **註**：本 Task 是 I/O 整合，無新單元測試；驗收＝`python -m pytest -q` 全綠（不迴歸）＋人工讀碼確認接線。實機驗證另列在計畫尾。

- [ ] **Step 1: 建 recorder 並改扇出 on_chunk**

在 `miningbot/main.py` 把原本這段（~106-111）：

```python
        self.listener = audio.ChillListener(
            refs, sr, cfg.audio_window_seconds, cfg.audio_score_interval_s,
            event_threshold=(cfg.audio_event_threshold if cfg.audio_event_record else None),
            on_event=self._on_audio_event, decimate=cfg.audio_match_decimate)
        # 啟動喇叭 loopback 擷取，持續餵音訊給 listener（chill 偵測的核心）
        self._audio_cap = audio.LoopbackCapture(self.listener.feed)
```

改成：

```python
        self.listener = audio.ChillListener(
            refs, sr, cfg.audio_window_seconds, cfg.audio_score_interval_s,
            event_threshold=(cfg.audio_event_threshold if cfg.audio_event_record else None),
            on_event=self._on_audio_event, decimate=cfg.audio_match_decimate)
        # 重置完成鈴聲擷取（第一階段：只錄不比對）——與 ChillListener 隔離
        self._reset_chime_active = False
        self._reset_wait_since = 0.0
        self._last_chime_diag = 0.0
        self._reset_chime_recorder = None
        if cfg.reset_chime_capture:
            chunk_seconds = 4096 / cfg.audio_sample_rate      # LoopbackCapture 預設 chunk_frames
            detector = audio.AdaptiveSpikeDetector(
                spike_factor=cfg.reset_chime_spike_factor,
                baseline_alpha=cfg.reset_chime_baseline_alpha,
                min_floor=cfg.reset_chime_min_floor,
                warmup_samples=max(1, round(cfg.reset_chime_warmup_s / chunk_seconds)))
            self._reset_chime_recorder = audio.ResetChimeRecorder(
                sample_rate=cfg.audio_sample_rate,
                window_s=cfg.reset_chime_window_s,
                post_roll_s=cfg.reset_chime_post_roll_s,
                chunk_seconds=chunk_seconds,
                detector=detector,
                out_dir=f"{cfg.log_dir}/snapshots/audio",
                max_clips=cfg.reset_chime_max_clips,
                log=self._on_reset_chime_saved,
                diag=self._reset_chime_diag)
        # 啟動喇叭 loopback 擷取，扇出給 listener（chill 核心）＋ reset-chime recorder
        self._audio_cap = audio.LoopbackCapture(self._on_audio_chunk)
```

- [ ] **Step 2: 新增音訊執行緒扇出與回呼方法**

在 `_on_audio_event` 方法（~1465）之後新增：

```python
    def _on_audio_chunk(self, chunk):
        """loopback 每 chunk 回呼（音訊執行緒）：餵 chill listener；active 時也餵 reset-chime。"""
        self.listener.feed(chunk)
        rec = self._reset_chime_recorder
        if rec is not None and self._reset_chime_active:
            rec.feed(chunk)

    def _on_reset_chime_saved(self, path, rms):
        """存下一個重置鈴聲候選片段時（音訊執行緒）記一筆到主 log。"""
        self.logger.info("🔔 重置鈴聲候選存檔 rms=%.1f -> %s", rms, path)

    def _reset_chime_diag(self, rms, baseline):
        """armed 期間每 chunk 回呼（音訊執行緒）：節流把 rms/baseline/ratio 寫 heartbeat，供校門檻。"""
        now = time.time()
        if now - self._last_chime_diag < cfg.audio_score_interval_s:
            return
        self._last_chime_diag = now
        ratio = rms / max(baseline, cfg.reset_chime_min_floor)
        self.log_hb.info("RESET_CHIME rms=%.1f base=%.1f ratio=%.2f", rms, baseline, ratio)
```

- [ ] **Step 3: 進入 RESET_WAIT 時記起算時間**

在 `_on_enter` 的 `if s is State.RESET_WAIT:` 分支（~1758）內、`self.human_cleared = False` 之後加一行：

```python
            self._reset_wait_since = time.time()     # reset-chime 擷取的 arm 計時起點
```

- [ ] **Step 4: 主迴圈每 tick 更新 active 旗標**

在 `_tick(self, frame)` 方法（~1766）最上面、`if self.state is State.MINING:` 之前插入：

```python
        self._update_reset_chime_active()
```

並在 `_tick` 方法之後（或任一合理位置）新增：

```python
    def _update_reset_chime_active(self):
        """依 state＋計時決定 reset-chime recorder 是否收音；離開 RESET_WAIT 清空重錄。

        先把旗標設 False 再 reset() recorder，避免音訊執行緒在 reset 當下還餵 chunk
        （競態最壞＝邊界丟一個 chunk，對校準無害）。"""
        rec = self._reset_chime_recorder
        if rec is None:
            return
        active = (self.state is State.RESET_WAIT
                  and self._reset_wait_since > 0.0
                  and time.time() - self._reset_wait_since >= cfg.reset_chime_arm_delay_s)
        if active and not self._reset_chime_active:
            self._reset_chime_active = True
            self.logger.info("🔔 重置鈴聲擷取啟動（RESET_WAIT 滿 %.0fs）", cfg.reset_chime_arm_delay_s)
        elif not active and self._reset_chime_active:
            self._reset_chime_active = False
            rec.reset()
```

- [ ] **Step 5: 跑全測試確認不迴歸**

Run: `python -m pytest -q`
Expected: PASS（全綠；新增 8 個 audio 測試也在內）

- [ ] **Step 6: 靜態載入健檢**

Run: `python -c "import miningbot.main"`
Expected: 無錯誤（import 成功，語法/名稱無誤）

- [ ] **Step 7: Commit**

```powershell
git add miningbot/main.py
git commit -m @'
feat(main): RESET_WAIT 滿 30s 起自動錄重置完成鈴聲候選片段

loopback on_chunk 扇出給既有 chill listener＋新 ResetChimeRecorder；active
旗標由主迴圈依 state＋計時設、離開 RESET_WAIT 清空重錄；armed 期間節流把
rms/baseline/ratio 寫 heartbeat 供校門檻。不動 chill 偵測路徑。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

## 實機驗證（人工，非 CI）

1. 開 Roblox、`python -m miningbot.main`，等到一次真的礦坑重置進 RESET_WAIT。
2. 等重置完成那一聲後，看 `logs/snapshots/audio/resetchime_*.wav` 是否有檔、播放確認含鈴聲。
3. 看 `logs/heartbeat.log` 的 `RESET_CHIME rms=.. base=.. ratio=..`：確認鈴聲那刻 ratio 明顯衝高；若第一輪全漏或全中，依數據調 `reset_chime_spike_factor` / `reset_chime_min_floor` 再跑。
4. 拿到乾淨鈴聲後，裁成參考 wav（第二階段 spec 再定「比對到就判定重置完成」）。

---

## Self-Review

**Spec coverage：**
- 第 1 節純邏輯 `AdaptiveSpikeDetector` → Task 1；薄 I/O `ResetChimeRecorder` pre/post-roll → Task 2。✅
- 第 2 節扇出 on_chunk、active 由主迴圈設、離開 reset()、音訊執行緒只讀 bool → Task 4。✅
- 第 3 節全部 config 欄位 → Task 3。✅
- 第 4 節 heartbeat 節流 log rms/baseline/ratio、存檔寫 miningbot.log → Task 4 Step 2。✅
- 第 5 節測試（暖機不觸發、持續大聲一次、基準線不自我抬高、min_floor 擋靜音、pre/post-roll、max_clips）→ Task 1/2 測試齊備。✅
- 不做比對/不碰 banner OCR/不依賴 auto_reenter → 本 plan 未觸及該等路徑。✅

**Placeholder scan：** 無 TBD/TODO；每個 code step 皆含完整程式。✅

**Type consistency：** `AdaptiveSpikeDetector(spike_factor, baseline_alpha, min_floor, warmup_samples, release_factor)`、`.update()->bool`、`.baseline` property、`.reset()` 於 Task 1 定義，Task 2/4 一致使用；`ResetChimeRecorder(sample_rate, window_s, post_roll_s, chunk_seconds, detector, out_dir, max_clips, save_fn, log, diag)`、`.feed()`、`.reset()` 於 Task 2 定義，Task 4 一致呼叫。✅
