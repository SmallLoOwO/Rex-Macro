# 標註工具送出守門 + 背景預載

## 問題

佇列模式下快速連按 Enter（或快速點送出鍵），會在圖片還沒顯示時就把標註送
出去。佇列裡有些看似無用的素材其實藏著漏判（FN），但玩家看不到圖就標掉了，
永遠錯過。

兩個漏洞：

1. **換圖後無守門**：`showQueueItem()` 改 `img.src` 後送出鍵仍啟用——新圖還在
   載入就能按 Enter 送出。
2. **同一張重複送出**：`submitAnnotation()` 是 `async`，POST 還在 `await` 時
   再按一次 Enter 會對同一張圖發第二次請求。

## 設計

純前端 JS（`web_static.py` 的 `render_annotate_html` 內嵌 `<script>`），不動後端。

### 三層守門

| 層 | 觸發 | 行為 |
|---|---|---|
| 圖片載入守門 | `img.src` 改變 | 禁用送出鍵 + 顯示「載入中…」 |
| 圖片就緒 | `img` `load` 事件（或 `img.complete && naturalWidth` cache 命中） | 啟用送出鍵 |
| POST 防重複 | `submitAnnotation()` 進入 | 禁用送出鍵；POST 失敗時重新啟用 |

送出鍵啟用條件 = 圖片已載入 **且** 沒有 POST 在進行中。

### 背景預載

- 顯示第 `i` 張時，用 `new Image()` 背景預載第 `i+1`～`i+5` 張（桌機 localhost，
  頻寬不是瓶頸）。
- 送出成功跳下一張後自動補預載新的 `i+1`～`i+5`。
- 瀏覽器 HTTP cache 同 URL 第二次命中 → `img.src` 一改，`load` 幾乎瞬間觸發。
- 預載來不及時（玩家比預載快），守門正常生效：按鈕顯示「載入中…」直到 `load`。

### 視覺回饋

- 送出鍵禁用時：文字改成「載入中…」，沿用既有 `.submit:disabled` 半透明樣式。
- status 列在圖片載入期間顯示「正在載入圖片…」。

### 不改動的部分

- 後端 `/api/annotate`、`/api/annotate/undo` 完全不動。
- 佇列走完的 `setQueueDone(true)` 行為不變。
- `Ctrl+Z` 還原路徑不變（還原的圖已在 cache，`load` 瞬間觸發）。
- 單張模式（`?snapshot=`，無佇列）：只有初始載入守門，無預載。

## 實作範圍

`miningbot/web_static.py` 的 `render_annotate_html` 函式內嵌 JS，~30 行新增。

### 測試

現有 `tests/test_web_static.py` 驗 HTML 結構。新增測試確認：

1. 渲染出的 HTML 包含預載相關 JS（`preload` 函式存在）。
2. 送出鍵初始 `disabled`（圖片還沒載入時）。

純 JS 行為（load 事件、cache 命中、防重複）在瀏覽器裡驗證，單元測試只覆蓋
HTML 結構。
