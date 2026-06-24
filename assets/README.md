# assets

執行時需要的素材（皆由使用者準備；.wav/.png 已被 .gitignore 排除，不進版控）。

- `chill_reference.wav`：chill boom 參考音。轉檔最簡單用內建工具：
  - `python -m miningbot.convert_audio "你的chill.mp3"`（自動轉單聲道 48kHz，並裁出能量最強的 1 秒）
  - 也可手動：`ffmpeg -i chill.mp3 -ac 1 -ar 48000 chill_reference.wav`（記得裁短到約 1 秒，要比 audio_window_seconds 小）
- `markers/*.png`：各**階級**的 D2 掃描標記模板（採集時定位用）。每個階級一張圖。
  - **自動下載 wiki 圖**：`python -m miningbot.fetch_trackers`（高階級 Exotic 以上；加 `--all` 連低階級）→ 存到 `assets/markers/`。
  - 比對方式：**多模板 + 形狀/邊緣（忽略顏色）+ 多尺度**。所以填色（Normal/Ionized/Spectral）不影響，不同階級形狀也都能比中，還會回報是哪一級（log 裡看得到）。
  - wiki 圖只是「起點」。若實機對不準（看 `logs/snapshots/` 的失敗截圖），改用**遊戲內掃描後截圖、裁緊標記**最可靠，並調 `config.py` 的 `marker_edge_threshold`。
  - 後備：若 `assets/markers/` 是空的，程式會改用單張 `assets/marker.png`。
- `boost_expired.png`：右下角加成效果「已結束」的模板截圖（觸發重新按 D5）。
- `activity_event.png`：頂部中央「D4 控制活動」事件的模板截圖（觸發按 D4）。注意此模板需與 chill 文字明顯不同，避免誤判。
- `scan_event.png`：SCAN 變體事件的模板截圖（觸發 D2/Z/D5 組合）。
- `cave_event.png`：洞穴入口事件的模板截圖（觸發 F 進出洞穴）。

> 只啟用你實際會用到的變體：若不跑 scan/cave，請放一張**隨機雜訊**的小圖（不要用純色！）。
> 偵測用 TM_SQDIFF_NORMED，純色模板會與純色背景區域吻合而恆為「偵測到」，效果相反；雜訊圖才不會比中任何畫面。
