# `panel/` — 左下 NORMAL 背包面板名字欄

`backpack_review_region = Region(0, 395, 226, 335)` 的實機裁圖，用來釘住
`harvester.parse_panel_ore_names` 的**名字欄剖析**與兩道幾何閘。

面板是**狀態不是訊息流**——不會淡出、不需要 hover、不受前景影響。這是聊天在前景
失守時唯一還讀得到的「這顆礦到底進帳了沒」的證據，交人工前救援（路 B）與雙 chill
對帳都靠它。

## 判定

| 步驟 | 規則 | 依據 |
|---|---|---|
| 幾何閘 y | 框中心 `y ≥ panel_row_min_y`（60） | 標頭 y≈14、篩選框 y≈45、第一列 y≈78 |
| 幾何閘 x | 框中心 `x ≤ panel_name_col_max_x`（185） | 名字實測 72~103；craft 面板自 x≈185 起 |
| 黏框切分 | 切在第一個數字或逗號之前 | `Cloverstone 1,6` → `Cloverstone` |
| 雜訊下限 | 至少 `panel_name_min_letters`（3）個字母 | craft 欄被讀歪的 `•P11/`、`.73` 不得成為假礦名 |
| 進帳判定 | `classify_found_ore` 回 `rare`/`rare_fuzzy` 才算（**不是**「非 common」） | H069：排除清單只收 Surreal+，面板列的是整個背包，低階礦一律落 unknown |

## 兩側夾

- **真陽性**：`125_giveup_before_backpack.png` 六列彩色礦名 + 兩列黏框，
  RapidOCR 實測 `Leprechaun 0.99998 / Faedrine 0.99998 / Cleavelite 0.99997 /
  Siogyne 0.99974 / Weevil 0.99981 / Plentium 0.99991`，黏框
  `Cloverstone 1,6 = 0.96015`、`Imbollyx. 8 = 0.88326`。
- **負樣本（同一張圖內）**：`NORMAL`(y14)、`www`(y45)、`Sh`(y13)、`Mat`(y48) 與整條
  x≈204~211 的 craft 面板數字欄——閘沒守住就會多出假礦名。
- **「沒變就是沒變」**：`125_giveup_after_backpack.png` 與 before 相隔 7 秒、內容相同
  （採集期間 bot 已停止挖礦）→ 差分必須是空。誤判的代價是**靜默放生一顆真稀有礦
  且沒有任何 log 會發現**，所以這條迴歸比真陽性更重要。
- **「變了但全是低階」**（H069 實錄）：`145_rescue_pre_panel.png` → `145_rescue_cur_panel.png`
  新增 `Duskgravite / Siogyne / Sugarmuck / Egguinox / Cloverstone` 五列，全是鎬子挖到的
  低階礦，把舊列擠出裁圖（列數 9→8）。差分必須是空。舊版「非 common」判準讓其中三個
  算成進帳（`sugarmuck`/`cloverstone` 是 unknown，`egguinox` 被白名單上真實存在的兩字
  礦名 `Eg` 前綴誤配），bot 因此不交人工。

## 檔案

檔名前綴 `125`／`145` 是 **`harvest_id`（流水號）不是 `Hxxx` 事故編號**——兩套編號不同
命名空間，別混。

| 檔名 | 來源 | 說明 |
|---|---|---|
| `125_giveup_before_backpack.png` | harvest 125（2026-07-29 15:29:34） | 交人工前。面板上就有 `Faedrine`（Exquisite，在高階白名單上），聊天最底行也是 `small_lo has found Faedrine`，三層八方位全空仍交了人工——救援要救的正是這一型 |
| `125_giveup_after_backpack.png` | 同上，+7 秒 | 內容相同的對照組 |
| `145_rescue_pre_panel.png` | harvest 145（2026-07-31 14:37:18，chill 前參考點） | H069 假命中的基準張，頂列 `Imbollyx` |
| `145_rescue_cur_panel.png` | 同上，+130 秒（14:39:28 交人工前） | 五列低階新礦擠進來 → 舊版誤判進帳。**誤收側迴歸** |

⚠ 這兩張是 **craft 面板開著**拍的。名字路不受影響（0.999+ 全數讀出），但任何未來
要讀**數量**的實作必須先守門：craft 面板從 x≈185 起疊在數字欄上，OCR 會讀到配方
需求（`310/190 Siogyne`）而不是存量——**錯的值不是缺值**。

`www` 是**篩選文字框**不是 placeholder；使用者手動在 session 初始化時打一次做零點，
bot 不碰。它是覆蓋率條件不是正確性條件：沒武裝只會讓訊號沉默，不會給出錯誤答案。
