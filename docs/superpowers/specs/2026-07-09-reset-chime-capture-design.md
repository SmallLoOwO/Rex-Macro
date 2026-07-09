# RESET_WAIT 期間自動擷取「重置完成鈴聲」候選片段設計

日期：2026-07-09
狀態：設計定案，待實作計畫

## 目標與範圍

礦坑重置後 bot 進 `RESET_WAIT` 等待，這段等待很長；重置**完成**時遊戲會發出一記清脆鈴聲/鐘聲（前面相對安靜）。目前**還沒有這個音效的樣本**，無法拿它去比對——先有雞才有蛋。

本設計只做**第一階段：自動錄下候選片段**，讓使用者事後人工挑出那一聲、裁成參考 wav（比照 chill 參考流程）。

**明確不做（YAGNI）**：
- 不做「聽到符合音效就自動停」的比對——那是**第二階段**，等使用者從本階段產出的 clip 裁出 `reset_reference.wav` 後才做。
- 不碰 banner OCR、不依賴 `auto_reenter`（關著也要能錄）。
- 不動 `ChillListener` 的 chill 安全偵測路徑（零迴歸風險）。

## 已確認的事實（2026-07-09 與使用者問答＋讀碼）

| 環節 | 事實 | 對設計的意義 |
|---|---|---|
| 音效特徵 | 前面相對安靜，重置完成時「一記清脆鈴聲/鐘聲」 | 相對響度尖峰即可乾淨觸發，不需事先知道絕對音量 |
| 等待長度 | 很長（末端才出現那一聲） | 不能只錄固定短窗；也不宜整段長錄（檔案大／撈不到）→ 用尖峰觸發存短片段 |
| 音訊層 | `LoopbackCapture` 背景執行緒每 ~85ms 餵一個 chunk 給 `on_chunk`；持續運行、不受 state 影響 | RESET_WAIT（含 `auto_reenter` 關）期間照樣有 chunk 可錄 |
| 滾動緩衝 | `ChillListener._buf` 只保留很短的比對窗，**留不住幾分鐘前的音訊** | 需另開獨立累積器，不能靠現有緩衝 |
| 現成模式 | `RisingEdgeDetector`（上升緣去抖動）＋ `_on_audio_event`（音訊執行緒 inline 存 wav ~5ms）已成熟 | 重用其語意與存檔慣例 |

## 第 1 節：元件切分（沿用「純邏輯 + 薄 I/O」慣例）

### 純邏輯 `AdaptiveSpikeDetector`（新增於 `audio.py`，可 TDD）

吃逐 chunk 的 RMS，維護一條「近期安靜基準線」（EMA），當 `目前RMS / 基準線 ≥ spike_factor` 時以上升緣語意回報一次觸發（重用 `RisingEdgeDetector` 的 armed/release 去抖動——高檔不重複觸發，回落到 release 才 re-arm）。

介面（暫定）：

```python
class AdaptiveSpikeDetector:
    def __init__(self, spike_factor: float, baseline_alpha: float,
                 min_floor: float, warmup_samples: int,
                 release_factor: float = 0.5): ...
    def update(self, rms: float) -> bool:
        """餵一個 RMS 值，回傳「這一次是否為新尖峰」。"""
```

兩個必防的坑：

1. **暖機**：前 `warmup_samples` 次 `update` 只累積基準線、一律回 False（否則第一個 chunk 無基準會誤觸）。
2. **基準線不被鈴聲自己拉高**：處於「已觸發／高檔」狀態（`ratio ≥ release_factor * spike_factor`）時**凍結基準線 EMA 更新**，回落到 release 以下才續更。否則鈴聲會把基準線推高、進而自我抑制或漏掉連續兩聲。

`ratio = rms / max(baseline, min_floor)`——`min_floor` 防純靜音時基準線趨近 0、除出假尖峰。

### 薄 I/O `ResetChimeRecorder`（包住上面的純偵測器）

- 自維護一條 `window_s`（~4s）滾動緩衝（`np.concatenate([...])[-N:]`，比照 `ChillListener.feed`）。
- 逐 chunk：算 RMS → 餵 `AdaptiveSpikeDetector` → 觸發時**不立即存**，改設一個 `post_roll_s`（~1.5s）倒數；倒數期間繼續收 chunk；倒數歸零才把當下整條 `window_s` 緩衝存檔。
  - 結果：存下的片段 ≈「觸發前 ~2.5s ＋ 觸發後 ~1.5s」，鈴聲完整落在中段，方便裁 1s 參考。
  - 若倒數期間又來一次觸發，延長倒數（避免把一串鈴聲切兩半）。
- 存 `logs/snapshots/audio/resetchime_YYYYmmdd_HHMMSS_rmsNNN.wav`（沿用 `audiochg_*` 命名慣例、同一子夾），用 `audio.save_wav`。
- `max_clips` 上限：單輪 RESET_WAIT 存滿即停止存檔（仍繼續更基準線），防洗版。
- `reset()`：清緩衝、清偵測器狀態、清 clip 計數——離開 RESET_WAIT 時呼叫，下輪重新暖機。

## 第 2 節：生命週期與接線

- **扇出 on_chunk**：`LoopbackCapture` 的 `on_chunk` 從單餵 listener 改成：
  ```python
  def _on_audio_chunk(chunk):
      self.listener.feed(chunk)
      if self._reset_chime_active:
          self._reset_chime_recorder.feed(chunk)
  ```
  （音訊執行緒；存檔 inline，比照 `_on_audio_event`。）
- **active 旗標由主迴圈設定**（音訊執行緒只讀這個 bool，bool 讀取夠原子）：
  - 進入 `RESET_WAIT` 時記 `self._reset_wait_since = now`（沿用既有 `_on_enter(RESET_WAIT)` 路徑）。
  - 主迴圈每 tick 計算：`active = cfg.reset_chime_capture and state is RESET_WAIT and (now - self._reset_wait_since) >= cfg.reset_chime_arm_delay_s`。
  - `active` 由 True→False（離開 RESET_WAIT）時呼叫 `recorder.reset()`。
- Q / Ctrl+Q / F12 不受影響；此功能純被動錄音，不介入任何動作。

## 第 3 節：Config（全加在 `config.DEFAULT`，好關）

| 參數 | 預設 | 說明 |
|---|---|---|
| `reset_chime_capture` | `True` | 總開關；校準完成後可關 |
| `reset_chime_arm_delay_s` | `30.0` | 進 RESET_WAIT 多久後才開始錄（跳過重置**開始**的雜音） |
| `reset_chime_spike_factor` | `3.0` | `rms/baseline` 達此倍數即觸發 |
| `reset_chime_baseline_alpha` | `0.9`（暫定） | 基準線 EMA 係數（越大越慢跟隨；實機再調） |
| `reset_chime_min_floor` | 待實機量 | 絕對 RMS 下限，防純靜音誤觸；第一次可設保守小值，看 log 再校 |
| `reset_chime_window_s` | `4.0` | 存檔片段總長 |
| `reset_chime_post_roll_s` | `1.5` | 觸發後再收多久才存（讓鈴聲落中段） |
| `reset_chime_warmup_s` | `2.0` | 暖機時間（換算 warmup_samples 需 chunk 時距） |
| `reset_chime_max_clips` | `20` | 單輪 RESET_WAIT 存檔上限 |

## 第 4 節：Log（一次跑完既拿片段又拿校準證據）

- armed 期間每算一次 RMS，節流（比照 `score_interval`，~0.3s 一次）把 `rms / baseline / ratio` 寫進 `heartbeat.log`——就算 `spike_factor` 第一次沒調準，也有數據回頭校門檻。
- 每存一個 clip 寫 `miningbot.log`（含 RMS、ratio、路徑），使用者當場知道抓到幾個候選、在哪。

## 第 5 節：測試（TDD，先寫失敗測試）

純邏輯 `AdaptiveSpikeDetector`（`tests/test_audio.py` 或既有 audio 測試檔）：
- 安靜基準線 → 單一尖峰值 → 觸發一次。
- 持續大聲 → 只觸發一次（回落到 release 以下才 re-arm，再升起才第二次）。
- 暖機期內的尖峰 → 不觸發。
- 鈴聲（短高值）**不得**把基準線拉高到後續同樣尖峰被抑制（凍結更新驗證）。
- 純靜音下 RMS 抖動 → `min_floor` 擋住、不觸發。

`ResetChimeRecorder` pre/post roll：
- 餵合成 chunk 串（安靜→尖峰→安靜），斷言：存檔恰好一次、存下的緩衝長度 ≈ `window_s`、尖峰樣本落在片段內（非最末端）。
- `max_clips` 達上限後不再存檔。

不需實機即可全綠（純合成訊號）。實機驗證＝真的等一次重置、確認 `logs/snapshots/audio/resetchime_*.wav` 裡有那一聲。

## 風險邊界

- 最壞結局＝存了幾個非鈴聲的響度尖峰候選 wav（無害，人工聽一下即排除）；或門檻沒調準第一輪全漏，但有 `heartbeat.log` 的 RMS 數據可校第二輪。
- 不影響 chill 偵測、不影響任何動作路徑、`reset_chime_capture=False` 即完全回到現狀。
- 第二階段（比對到樣本自動停 / 當 REENTRY 觸發訊號）待本階段拿到真實樣本後另開 spec。
