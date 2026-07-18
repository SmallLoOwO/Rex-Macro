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
uv run python -m miningbot.add_chill_ref --scan
uv run python -m miningbot.fetch_trackers
uv run python -m miningbot.capture_template boost
uv run python -m miningbot.calibrate_surface --import NNN
```
