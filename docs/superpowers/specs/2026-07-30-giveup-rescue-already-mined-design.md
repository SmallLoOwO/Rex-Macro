# 交人工前救援：判「礦在 chill 前就被挖走了」（聊天 ＋ NORMAL 面板雙路）

日期：2026-07-30
狀態：設計定案，待實作
關聯：`2026-07-30-prechill-evidence-cache-design.md`（**前置**，提供 chill 前參考點）、
H064（`_reveal_chat`，commit `9a9db7b`）、H054/H055（基準閘與 UI 殘留剝除）、
H019（`decide_sweep_failure` 的 had_candidates 分流）

## Problem Statement

`_harvest_giveup`（`main.py:4680`）之前沒有人再看一次「這顆礦其實已經進帳了嗎」。
最常見的交人工型態是礦在 chill 響之前就被鎬子挖掉——之後掃描必然全空，
證據卻明明就在畫面上。

07-29 harvest 125 實錄：

- 15:26:34 chill → HARVESTING，15:26:37 `聊天已喚醒（亮像素 14066）`
- 進場幀聊天最底行 `small_lo has found Faedrine`，`Faedrine` 不在 `common_ore_names()`
- 左下 NORMAL 面板也有 `Faedrine`（篩選框已武裝，所以那是本 session 挖到的）
- 標準層＋up＋down 三層八方位全空 → 15:29:41 交人工

兩條獨立訊號互相對上，bot 卻一條都沒讀。

## Solution

在 `_harvest_giveup` 的最前面插入 `Bot._giveup_rescue()`：用
`2026-07-30-prechill-evidence-cache-design.md` 的 chill 前裁圖當基準，比對「現在」，
兩路取聯集。任一路判定有新的非-common 礦名 → 判定本 episode 的礦其實已經進帳，
不交人工。

**範圍刻意保守**：只在 giveup 前跑，**不動** `_late_chat_confirm` 的
`if self._chat_baseline is None: return False` guard。拆掉那個 guard 會讓 pre-sweep／
post-sweep 兩個呼叫點活過來＝變成「提早中止 episode」，那條路的誤判代價是**靜默放生一顆
真稀有礦且沒有任何 log 會讓你發現**。本 spec 不碰。

### 兩條證據路

**路 A：聊天。** pre-chill 裁圖與現在的裁圖各跑一次 `ocr.read_text_multi`，
走既有的 `ocr._chat_lines`（內含 `_strip_ui_residue`，H055 的 NORMAL 面板殘留剝除），
取 has-found 行差分，濾掉 `common_ore_names()`。

- 優點：每一次挖到都會記錄。
- 天花板：會淡出（~15s 無新訊息），`_reveal_chat` 在 Roblox 非前景時整個被丟掉
  （`main.py:1612` 的註解與 WARNING 就是為此）。

**路 B：NORMAL 面板名字。** pre-chill 與現在的 `cfg.backpack_review_region` 裁圖各跑一次
`ocr.read_text_boxes`，抽名字欄，建名字集合，差分後濾掉 `common_ore_names()`。

- 優點：面板是**狀態不是訊息流**——不會淡出、不需要 hover、不受前景影響。
  這是聊天在前景失守時的唯一證據。
- 天花板：**同一 filter 零點之後第二次挖到同一礦種時全盲**（名字已在、只有數量 +1，
  而數量欄要另外處理，見下）。125 的聊天裡 `has found Faedrine` 出現兩次，
  session 是 14:34 開的 → 重複是真實情境，不是假想。

兩路互補、都不完整，所以要兩路，取聯集。

### 名字欄剖析

2026-07-30 實機量測（全螢幕，craft 面板關閉，篩選框已武裝）：

```
NORMAL 標頭      y=409
篩選框           y=441
礦物列 center y  472 / 508 / 544 / 580 / 618 / 653   列距 ≈36.2px
彩色列 x 起點    18        名字左緣 x≈22        數字右對齊 x≈212
```

全部落在既有 `backpack_review_region = Region(0, 395, 226, 335)` 之內，**寬度不必改**。

RapidOCR 讀名字實測（素材：125 的 `giveup_before_backpack`）：

```
Leprechaun 0.99998   Faedrine 0.99998   Cleavelite 0.99997
Siogyne    0.99974   Weevil   0.99981   Plentium   0.99991
Cloverstone 0.96015（名字與數字黏成同一框）
Imbollyx    0.88326（同上，多一個尾點）
```

黏框是剖析問題不是 OCR 問題：**切在第一個數字或逗號之前**即可分出名字。
剖析後對 `game_data` 做 fuzzy 比對（`game_data.fuzzy_match_ore`）再判 common／非-common，
避免尾點之類的雜訊造成漏配。

### craft 面板不必守門（重要）

125 那張是右側 Shamrock「Materials to Craft」面板**開著**拍的，名字仍然 0.999+ 全數讀出，
只有最下面兩列與被截斷的數字黏在一起。**名字路不受該面板遮擋影響。**

該面板從 x≈185 起疊在**數字欄**上，會讓 OCR 讀到配方需求（`310/190 Siogyne`、
`87/53 Cleavelite`）而不是礦物存量——那是**錯的值不是缺值**。所以：

- 本 spec 只用名字，**不需要 craft 面板守門**。
- 任何未來要讀數字的實作**必須**先守門：在加寬區跑 `read_text_boxes`，偵測到
  `Materials to Craft`／`Previous`／`Next` 就停用數字路並記一次 WARNING，
  比照 `_ensure_player_list_closed` 的「偵測不到就整個跳過，寧漏勿誤」。

### 判定與收尾

- 兩路都沒有新的非-common 礦名 → 回 `False`，`_harvest_giveup` 照常走完（今日行為）。
- 任一路有 → 記 `HARVEST_RESCUED` 事件（欄位：`harvest_id`、`source`（`chat`／`panel`／`both`）、
  `ore_names`、兩張裁圖路徑），呼叫 `_harvest_resume_mining()`，回 `True`。
- **不偽造 `HARVEST_SUCCESS`。** 實機驗證期要能把「救援命中」與「正常採集成功」分開統計，
  混在一起就算不出救援的命中率與誤判率。

### 失效降級（全部維持今日行為，不製造新的失敗模式）

- chill 前快取沒有（剛啟動／剛從別的狀態進 MINING）→ 整個救援跳過。
- `ocr.rapidocr_available()` 為假 → `read_text_boxes` 回 `[]` → 路 B 整條跳過，只跑路 A。
- 任何例外 → 記 WARNING 後回 `False`，絕不讓救援本身把 giveup 弄壞。

### 篩選框（`www`）的角色

NORMAL 標頭下方的 `www` 是**篩選文字框**，不是 placeholder。輸入任何礦名都不含的字串
會清空面板顯示，之後新挖到的礦重新出現並累積。使用者手動在初始化時打一次，
**bot 不碰**（打字需要新的輸入原語，而 AGENTS 規則 11 禁用 `keyboard`；
脫離焦點要點 3D 世界，會打壞 MINING 期間持續按著的 LMB 狀態）。

它是**覆蓋率條件不是正確性條件**：

- 沒武裝 → 面板是完整帳號庫存 → 舊礦名字早就在 → 只有「這輩子第一次挖到」才會出現新名字
  → 訊號**沉默**（不會給出錯誤答案）。
- 武裝了 → 變成「零點之後第一次」→ 覆蓋率大幅提高。

因為差分用的是 bot 自己留的 pre-chill 裁圖，**零點在哪不影響差分本身**。所以不需要硬守門，
只在啟動時記一筆 log 說明面板列數，供事後判斷當時有沒有武裝。

## Config

```python
giveup_rescue_enabled: bool = True        # 關掉即完全回到今日行為
```

## Testing

純函式先測（`harvester` 或新模組，不進 `main.py`）：

- 面板名字剖析：黏框字串（`"Cloverstone 1,6"`、`"Imbollyx. 8"`）切出正確名字；
  純名字框原樣通過。
- 名字集合差分 → 濾 common → 判定：新增非-common 名字才回真；只新增 common 回假；
  完全沒變回假；pre 集合為空（快取剛建立）時的行為要明確。
- 聊天路沿用既有的 has-found 差分函式，補一個「pre-chill 已含該行 → 不算新」的迴歸。
- 用 125 的 `giveup_before_backpack` 當 fixture 收進 `tests/fixtures/`
  （**不可放 `assets/`，那裡被 gitignore**）。

## Further Notes

- **這是 2/9 樣本的問題，不是 9/9。** 9 份 `giveup_before_chat` 裡有 6 份聊天全黑，
  但那 6 份都在 07-28 `_reveal_chat` 修復（`9a9db7b`）之前，是舊帳。修復後
  hover 6/6 成功（`harvest.log`「聊天已喚醒」亮像素 12690~17871）。修復後只有兩次
  sweep 全空交人工：125 有稀有證據、122 的聊天全是 common
  （Toppatrick／Weevil／Siogyne／Synthesite／Riches）。**樣本只有 2，實機驗證期要重新統計
  命中率，不要拿 1/2 當結論。**
- 2026-07-30 那張現場幀只能當**幾何**樣本（臨時挖礦、只有低稀有度礦、面板只有 6 列）。
  稀有礦排序與多列版面仍要靠過往截圖與後續實機場次確認。
- 面板列距 36.2px、稀有度由高到低排序、新的高稀有礦浮到最上面 → 既有 `h=335`
  涵蓋標頭加約 7 列，對稀有礦足夠。真要涵蓋更多列再加高，但要先確認不會撞到
  螢幕左下的 HUD 疊圖（2026-07-30 量測：HUD 在 y≈905 起，面板 6 列時底部在 y≈672）。
