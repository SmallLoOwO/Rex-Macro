# assets

執行時需要的素材（皆由使用者準備；.wav/.png 已被 .gitignore 排除，不進版控）。

- `chill_reference.wav`：chill boom 參考音。由使用者的 mp3 轉檔：
  - 用 ffmpeg：`ffmpeg -i "Achillgoesdownyourspine.mp3.mpeg" -ac 1 -ar 48000 chill_reference.wav`
  - 取最具特徵的 1~2 秒（boom 主體），避免前後靜音過長。
- `marker.png`：D2 掃描後礦物標記的模板（採集時用來定位）。
  - 用**形狀/邊緣**比對（`marker_color_invariant=True`），所以**填色不同沒關係**，只要外框形狀一致（例如藍色圓環＋星狀中心）。
  - **可以用 wiki 圖**當參考，但要形狀清楚、背景單純（最好去背或裁緊）。
  - 尺寸不必完全準：程式會用 `marker_scales` 多尺度自動縮放比對。但若差太多仍可能失敗——最可靠還是**遊戲內實際掃描後截圖、裁緊標記**。
- `boost_expired.png`：右下角加成效果「已結束」的模板截圖（觸發重新按 D5）。
- `activity_event.png`：頂部中央「D4 控制活動」事件的模板截圖（觸發按 D4）。注意此模板需與 chill 文字明顯不同，避免誤判。
- `scan_event.png`：SCAN 變體事件的模板截圖（觸發 D2/Z/D5 組合）。
- `cave_event.png`：洞穴入口事件的模板截圖（觸發 F 進出洞穴）。

> 只啟用你實際會用到的變體：若不跑 scan/cave，請放一張**隨機雜訊**的小圖（不要用純色！）。
> 偵測用 TM_SQDIFF_NORMED，純色模板會與純色背景區域吻合而恆為「偵測到」，效果相反；雜訊圖才不會比中任何畫面。
