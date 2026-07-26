# `capacity/` — 背包容量百分比 OCR

頂部常駐「Capacity: NNN%」列的實機裁圖（`Region(715, 92, 200, 45)`）。
測試路徑：`ocr.read_text` → `ocr.parse_capacity_pct`。

| 檔案 | 期望讀值 |
|---|---|
| `capacity_14pct.png` | 14 |
| `capacity_100pct.png` | 100 |
| `capacity_101pct_a.png` | 101 |
| `capacity_101pct_b.png` | 101 |

## 為什麼要收 101%

遊戲**真的會顯示 101%**（溢位），不是 OCR 讀錯。把 >100 當成讀錯而丟棄，會在最需要
觸發重置的那一刻把信號丟掉。兩張獨立樣本就是為了擋住「這一定是雜訊」這個直覺。

## 尾端雜訊

裁圖尾端的 `|` / `[` 是 pill 分隔線，不是數字。`parse_capacity_pct` **必須容忍**它們。

## 容量的角色邊界

容量 100% **只加速 reset banner 輪詢**，不能自行進入 `RESET_WAIT`——真正的重置信號是
banner。另外開場鏈有容量閘（H053／H058）：容量還沒排到門檻以下就起跑，會讓 click／
pitch／OCR 全部卡頓被吃。

引擎不可用時整檔 skip（比照 `test_ocr_fixtures.py` 慣例）。
