# `player_list/` — 右上角玩家列表開／關

client-area 截圖（1920×1051）裁 x 1490..1915、y 100..235。判定看 OCR 有沒有讀到
標題列的 `Players` / `Blocks Mined`。

| 檔案 | 情境 | 期望 |
|---|---|---|
| `open.png` | 列表開啟，**亮粉礦壁**背景 | 讀得到標題列 |
| `open2.png` | 列表開啟，**綠色礦壁**背景 | 讀得到標題列 |
| `closed.png` | 未開啟（同區域只剩礦壁雜訊） | OCR 讀空 |

兩種背景是必要的——單一前處理必有背景盲區（H014 的教訓）。

## 為什麼判定必須可靠

Tab 是 **toggle**：沒開時按 Tab 反而會把它打開，而玩家列表會遮住右側的點擊視線。
所以只有**確實偵測到列表開著**才可以按 Tab，判定寧可漏不可錯。

## 引擎：只用 RapidOCR

實測三張 fixture：

- RapidOCR（`read_text_boxes`）：**3/3 全對**
- tesseract（`read_text`）：漏 `open.png`
- tesseract + 2x 放大：漏 `open2.png`

所以這條路徑只用 RapidOCR；未裝時整檔 skip，不擋純邏輯 CI。
