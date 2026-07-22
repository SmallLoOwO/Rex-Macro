# Runtime assets and tracked data

`assets/` 同時包含 Git 追蹤資料與機器本地校準素材。兩者用途不同，不能把
本機存在的 PNG/WAV 當成乾淨 checkout 一定具備的檔案。

## Git 追蹤資料

- `rare_ores.json`：active worlds 的高階礦物白名單。
- `ores_all.json`：wiki 同步的完整相關礦物資料。
- `README.md`：本素材契約。

更新資料：

```powershell
uv run python -m miningbot.fetch_ores
```

同步後必須檢查 world 集合、低／高階衝突報告與 `tests/test_game_data.py`、
`tests/test_fetch_ores.py`。

## 機器本地 runtime 素材

這些檔案通常被 `.gitignore` 排除。缺少時程式必須發出 preflight/log 警告，
並走有界、可觀察的 fail-safe；不得靜默改變行為。

| 素材 | 用途／來源 |
|---|---|
| `chill_reference.wav`、`chill_refs/*.wav` | chill 音訊參考；用 `convert_audio`／`add_chill_ref` 建立 |
| `boost_active.png` | D5 生效中的瓶子外觀，不包含倒數數字；用 `capture_template boost` |
| `d4_cooldown.png` | D4 readiness 的目前 cooldown 模板 |
| `markers/*_tracker_real.png` | 從實機 tracker 裁出的 shape 模板 |
| `marker.png` | `markers/` 無可用模板時的單張相容後備 |
| `surface/panel_*.png` | `reentry_mode=auto` 的地表面板模板 |

chill 參考集原則（2026-07-21 校準）：

- 收參考只認 confirmed 實錄（`*chill_audio_*.wav`）。`audiochg_*` 的 `_miss`
  只表示「錄的當下沒觸發」，**不代表不是 chill**——實測 44 個裡 15 個與某個
  confirmed 同時刻（±3s），那是同一次 chill 的上升緣。
- **不是每個 confirmed 都能當參考**：`loudest_window` 抽「最大聲的 1.0s」，
  chill 響時若有更大聲的雜音重疊就會抽到雜音。收之前必過假觸發守門
  （`Config.chill_ref_negative_ceiling`）：會把已知非 chill 音效推過觸發門檻的
  一律拒收（實測 H040 把每 ~15 分一次的週期性音效從 0.180 推到 0.507）。
- **上升緣錄音（`audiochg_*`）一律不可當參考來源**（H060，2026-07-21 犯過）：
  即使它與某個 confirmed 同時刻、確實是同一次 chill 的上升緣，那個窗裡 chill
  還沒到，`loudest_window` 抽到的是背景音——與 H040 同型污染。2026-07-21 收進
  7 個這種參考，其中一個把防掛機跳躍音從 0.18 推到 0.37，害每 15 分鐘假觸發
  一次。收參考只認 `*chill_audio_*` confirmed 實錄。
- **那個「每 ~15 分鐘的週期性非 chill 音效」是 bot 自己按出來的**（H060）：
  `antiafk_interval_s`（900s）在等待狀態按 Space 保活，角色原地跳的音效被
  loopback 收進來。它是負樣本語料的主力，也是最該拿來驗新參考的素材——
  對它分數會衝過 `chill_ref_negative_ceiling` 的候選一律拒收。runtime 另有
  `Config.antiafk_chill_mute_s` 的靜音窗當第二層保險。
- 去重與守門方向相反、缺一不可：去重比**完整實錄窗**（runtime 同款量測，
  不可補零——補零區窗能量趨近 0 會讓正規化相關度虛高 3 倍），守門比抽出的裁片。
- 兩側夾實測（34 個參考、decimate=8）：非 chill 最高 0.180 < 門檻 0.25 <
  真 chill 最低 0.292（唯一例外 077 被守門拒收，見上）。
- ⚠ `--scan` 讀 `Config.log_dir`；用 `uv run` 跑時它指到不存在的真實路徑，
  實機錄音在 MSIX LocalCache → 要用 `--snapshots-dir` 顯式指路。

Tracker 原則：

- Wiki icon 只能作為資料或初始參考，不是可靠的 runtime shape 模板。
- 外框 HSV 依 range 分開；中心顏色與礦坑背景都不是固定特徵。
- 使用遊戲內完整畫面裁出真框，門檻調整必須同時保留 TP 與裝備/UI 負樣本。
- 現行 tracker 參數讀 `Config.tracker_*`，不要依本檔複製數字。

舊的 `activity_event.png`、`scan_event.png`、`cave_event.png` 不是一般 mining
tick 的現行觸發契約。不要用隨機雜訊檔假裝功能已校準；未啟用功能應由
程式模式明確關閉。

## 測試素材邊界

- Regression 所需圖片／音訊放在 Git 追蹤的 `tests/fixtures/`。
- 測試不得直接依賴本機 `assets/*.png` 或 `assets/**/*.wav`。
- Runtime 校準素材可以保持本機專用，但 preflight 必須清楚列出缺失與影響。
- 新視覺門檻先增加具名 incident fixture，再修改設定或偵測器。

## 常用命令

```powershell
uv run python -m miningbot.convert_audio chill.mp3
# 實機錄音在 MSIX LocalCache（pythonw 跑的場次）→ 顯式指路，否則掃不到東西
uv run python -m miningbot.add_chill_ref --scan --snapshots-dir `
  "$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\Local\RexMacro\logs\snapshots"
uv run python -m miningbot.fetch_trackers
uv run python -m miningbot.capture_template boost
uv run python -m miningbot.calibrate_surface --import NNN
```
