# assets

執行時需要的素材（皆由使用者準備；.wav/.png 已被 .gitignore 排除，不進版控）。

- `chill_reference.wav`：chill boom 參考音。由使用者的 mp3 轉檔：
  - 用 ffmpeg：`ffmpeg -i "Achillgoesdownyourspine.mp3.mpeg" -ac 1 -ar 48000 chill_reference.wav`
  - 取最具特徵的 1~2 秒（boom 主體），避免前後靜音過長。
- `marker.png`：D2 掃描後礦物標記的模板截圖（採集時用來定位）。在遊戲掃描後對標記區域截圖裁切。
- `boost_expired.png`：右下角加成效果「已結束」的模板截圖（觸發重新按 D5）。
- `activity_event.png`：頂部中央「D4 控制活動」事件的模板截圖（觸發按 D4）。注意此模板需與 chill 文字明顯不同，避免誤判。
- `scan_event.png`：SCAN 變體事件的模板截圖（觸發 D2/Z/D5 組合）。
- `cave_event.png`：洞穴入口事件的模板截圖（觸發 F 進出洞穴）。

> 只啟用你實際會用到的變體：若不跑 scan/cave，放一張不可能比中的純色小圖即可讓對應偵測恆為 False。
