# 面板歸零救援：把「這場採到了嗎」從 3 秒差分換成整段 episode 的存在性檢查

日期：2026-07-31
狀態：設計定案，待實作
關聯：`2026-07-30-giveup-rescue-already-mined-design.md`（**被本文取代路 B**）、
`2026-07-30-prechill-evidence-cache-design.md`（本文刪掉它的 panel 那一半）、
H069（`docs/incidents.md`，本文的直接起因）

## Problem Statement

玩家的話：「截圖提供的證據全部都是低階礦物，且表示已經挖到了，導致一個稀有礦物被捨棄。」

H069（2026-07-31 harvest 145）已經修掉假命中的**分類器**根因，但把日誌攤開之後
露出兩件更根本的事：

1. **救援路 B 問錯了問題。** `prechill_cache_depth=6` × `prechill_cache_interval_s=1.0`
   ＝環形緩衝只存 6 秒，`prechill_min_age_s=3.0` ＝參考點只能落在
   `[chill−6s, chill−3s]`。所以現行路 B 問的不是「這場有沒有挖到稀有礦」，而是
   「**chill 前那 3 秒**有沒有挖到」。礦若在 chill 被偵測到之前 7 秒就被鎬子挖走，
   參考裁圖裡早就有它，差分恆為 0，救不到。125 那一型只是剛好落在窗內。

2. **不歸零的面板無法區分「早就持有」與「剛剛挖到」。** 面板是帳號庫存，玩家在
   session 初始化時手動用 `www` 篩選框打過一次零點；bot 完全不碰它。零點之後
   bot 跑好幾個小時，面板一路累積，同一顆礦種第二次挖到就只有數量 +1（而數量欄被
   右側 craft 面板疊住，讀到的是配方需求不是存量），路 B 全盲。

玩家提出的機制：既然篩選框輸入任何礦名都不含的字串就會清空顯示、之後新挖到的礦
重新出現，那**每次稀有礦入帳後清空一次**，下一次面板上冒出白名單礦就直接等於採到了。

## Solution

把路 B 從「pre/post 差分」改成「**存在性檢查**」，前提由 bot 自己維持：

> **不變式：進入 `State.MINING` 時 NORMAL 面板必為空。**
> 因此 giveup 前面板上任何白名單（Exotic+）礦名，都是這段 MINING 期間進帳的。

bot 在每次進 MINING 時點一下篩選框、多打幾個 `w`、點回 3D 世界還焦點，再 OCR
驗一次「標頭是 NORMAL 且列數為 0」。驗過才記 `_panel_zeroed_at`；沒驗過就把下一場的
路 B 整條關掉，回到今日行為。

覆蓋率從「chill 前 3 秒」變成「上一次進 MINING 以來的整段時間」，是舊窗的嚴格超集。

### 為什麼存在性檢查夠用：面板按 tier 由高到低排

2026-07-31 量測 5 張實機面板、49 列，**tier 嚴格遞減，零違例**：

```
137  Transcendent │ Exquisite ×3 │ Exotic ×2 │ Mythic ×2
140  Transcendent ×2 │ Mythic │ Surreal ×2 │ 低階 ×3
142  Transcendent ×2 │ Exotic │ Mythic │ Surreal ×3 │ 低階
145  Mythic │ Surreal │ 低階 ×15
144  Mythic │ 低階 ×7
```

（同 tier 內按另一個鍵遞增，不是稀有度遞減：leprechaun 7.6M 排在 faedrine 9.0M 上面。
那個鍵是什麼不重要，本設計只用「tier 遞減」這一條。）

白名單（`assets/rare_ores.json`）收的是 Exotic 以上，所以**白名單礦永遠排在所有
Mythic／Surreal／低階之上，永遠在第 1~2 列**。既有的
`backpack_review_region = Region(0, 395, 226, 335)` 只涵蓋 8 列，但那不影響——要找的
東西永遠在最上面。**裁圖不加高**（另有實測理由，見 Further Notes）。

### 為什麼不能沿用「非 common」判準

H069 已經釘死：`common_ore_names()` 是**聊天排除清單**，只收 Surreal/Mythic（＋會出
變體的 Master 底名），因為只有那兩階會被動進聊天。面板列的是整個背包，低階礦兩張表
都查不到 → 落 `unknown`。判準必須是「**在白名單上**」的正面證據，`unknown` 一律不算。

## User Stories

1. 作為玩家，我希望 bot 在鎬子已經把稀有礦挖走的情況下不要叫我，這樣我半夜不會被沒有意義的通知吵醒。
2. 作為玩家，我希望 bot 判「已經挖到了」時給的證據是真的稀有礦，這樣我不會因為一則「已進帳」的通知而永遠失去一顆礦。
3. 作為玩家，我希望救援涵蓋整段挖礦時間而不是 chill 前三秒，這樣「礦早就被挖走」的常見情形真的被接住。
4. 作為玩家，我希望 bot 自己維護篩選框零點，這樣我不必每挖到一顆就手動去打字。
5. 作為玩家，我希望 bot 清空面板失敗時**寧可叫我**，這樣失敗不會偽裝成成功。
6. 作為玩家，我希望 bot 清空失敗時在 log 裡吼出來，這樣我事後查得到是哪一場開始失效。
7. 作為玩家，我希望面板停在 IONIZED／SPECTRAL 頁時 bot 知道自己讀錯頁了，這樣它不會拿別頁的內容當證據。
8. 作為玩家，我希望我在交人工期間手動採走的礦不會被算成 bot 下一場的戰績，這樣統計是誠實的。
9. 作為玩家，我希望 bot 打字時多打幾個字元，這樣按鍵被吃不會讓清空默默失敗。
10. 作為玩家，我希望 bot 打完字把焦點還給遊戲，這樣後續的 W／D1／D3 不會被打進文字框。
11. 作為玩家，我希望焦點沒還回來時 bot 自己抓得到，這樣不會出現「按鍵全被吃但 log 一切正常」。
12. 作為玩家，我希望救援命中與正常採集成功在通知與事件記錄裡分得開，這樣我算得出救援的命中率。
13. 作為玩家，我希望救援命中時通知寫出是哪一顆礦，這樣我能自己核對。
14. 作為玩家，我希望救援本身出任何例外都不會把 giveup 流程弄壞，這樣最差也只是照舊交人工。
15. 作為玩家，我希望 rapidocr 不可用時整條路 B 安靜跳過，這樣不會因為引擎沒裝就亂判。
16. 作為玩家，我希望聊天那條路（路 A）維持原樣，這樣兩條證據路的天花板不同、互相補位。
17. 作為玩家，我希望面板變成 bot 的工作區之後，我還能從 Discord 訊息串看到整場戰績。
18. 作為玩家，我希望異色版本（ionized／spectral）漏判時是交人工而不是誤判，這樣我還有機會自己處理。
19. 作為玩家，我希望白名單沒收錄的新礦種漏判時也是交人工，這樣遊戲更新不會讓 bot 開始亂放生。
20. 作為玩家，我希望這個功能可以一個開關關掉，這樣出事時我能立刻回到舊行為。
21. 作為 AI agent，我希望判準集中在一個純函式裡，這樣我改判準時不必翻 `main.py`。
22. 作為 AI agent，我希望「面板已歸零」是一個明確的狀態旗標，這樣我讀 log 就知道那一場路 B 到底有沒有資格說話。
23. 作為 AI agent，我希望實機裁圖回歸涵蓋誤收側（145 兩張）與真陽性側（125 那張），這樣門檻改動有兩側夾。
24. 作為 AI agent，我希望被刪掉的 `prechill` panel 快取真的被刪掉，這樣不會留一份沒人用卻還在吃記憶體的環形緩衝。
25. 作為 AI agent，我希望所有寫 `State.MINING` 的地方都被稽核過，這樣清空不會漏掉最重要的那條入口。

## Implementation Decisions

### 清空原語

- 新方法（暫名 `Bot._clear_panel_filter()`），序列固定為：
  `click(panel_filter_xy)` → `typewrite("w" × panel_clear_keystrokes)` →
  `click(畫面中央)` → `sleep(panel_clear_settle_s)` → 一次 `read_text_boxes`。
- 點畫面中央是**還焦點**用的，不是新行為——`init_mining_sequence` 本來就會在世界上
  `mouse_down`/`mouse_up`。清空必須排在 `init_mining_sequence` **之前**（那之後 LMB 被
  按住不放）。
- 打字走 `pydirectinput.typewrite`（`input_control` 已經在用 pydirectinput）。
  AGENTS 規則 11 禁的是 `keyboard` 套件，不是打字本身。**實測按鍵掉 25%**（送 4 個進 3 個），
  所以 `panel_clear_keystrokes` 要明顯過量（建議 8）。
- 篩選字串只會越打越長（`www` → `wwwwwww` → …）。不需要清掉舊字元：任何礦名都不含
  的字串效果相同，長度不影響。

### 驗證與降級

- 清完的那次 `read_text_boxes` 同時取兩樣東西，**不開新 region**：
  - 標頭：`center.y < panel_row_min_y` 且文字在 `{NORMAL, IONIZED, SPECTRAL}` 內
  - 礦名列：既有 `parse_panel_ore_names`（`center.y ≥ panel_row_min_y`、`x ≤ 185`、≥3 字母）
- `標頭 == panel_expected_header ("NORMAL")` **且** 列數 == 0 → `_panel_zeroed_at = now`；
  否則 `_panel_zeroed_at = None` ＋ 一筆 WARNING（含實際標頭與列數）。
- **不重試**。H047/H063 的教訓是「多試幾次」在 UI 上會翻面；而且點歪的座標若是別的
  按鈕，重試等於多按它幾次。一次失敗＝下一場路 B 關掉＝回到今日行為＝最差多一則通知。
- 這道驗證順便接住撿取延遲競態：D3 採到的礦若在清空之後才落袋，列數 != 0 → 判未歸零 →
  下一場路 B 關 → 安全方向。

### 插入點（兩處，缺一不可）

`main.py` 有兩條進 `State.MINING` 的路，**只掛 `_on_enter` 會漏掉最重要的那條**：

- `_on_enter(State.MINING)`：在 `_focus_roblox()` 成功之後呼叫（焦點是清空的前提）。
  涵蓋 NEEDS_HUMAN 恢復、RESET_WAIT、回礦、啟動。
- `_resume_mining_tail`：這裡直接寫 `self.state = State.MINING` **不經過 `_on_enter`**，
  是採集成功／救援命中的收尾路徑。清空要插在 `init_mining_sequence` 之前。

`Bot.__init__` 的 `self.state = State.MINING` 只是初始值，`run()` 的首次
`_on_enter(MINING)` 會涵蓋。實作要把所有 `self.state = State.MINING` 的位置稽核一遍
並在 issue 勾掉。

### 路 B 改寫

- `_giveup_rescue` 的路 B：`_panel_zeroed_at is None` → 整條跳過（記一筆 info 說明原因）；
  否則 OCR 現況面板，白名單礦名非空即命中。
- `harvester.new_rare_panel_ores(pre, cur)` → `harvester.rare_panel_ores(names)`，
  拿掉 `pre` 參數與「pre 為空一律回 []」那道守門（歸零之後那道守門的語意不再成立）。
  判準不變：`classify_found_ore` 回 `rare`／`rare_fuzzy` 才算。
- `HARVEST_RESCUED` 事件與 Discord 通知格式不變，`source` 仍是 `chat`／`panel`／`both`。
- **仍然不偽造 `HARVEST_SUCCESS`**（沿用 2026-07-30 spec 的理由：實機驗證期要把救援命中
  與正常採集成功分開統計）。

### 刪除

- `prechill` 環形緩衝的 panel 那一半（`_prechill_sample` 的第三個元素、`_prechill_ref`
  的回傳）。路 A 還要 chat 那一半，緩衝本身留著。記憶體 3.7MB → ~2.4MB。
- `_panel_ore_gain` 的 `pre` 參數與差分語意 → 改成單張面板的白名單存在性讀取。
- `_episode_panel_pre` 與 `_episode_panel_gains` 的差分：雙 chill 對帳（預設關閉）
  改成「數現況面板上有幾顆白名單礦」。歸零點就在本場 episode 之前，語意正確且更簡單。
- `_log_panel_rows_once`：bot 現在自己控制篩選框，啟動時那筆「面板列數供事後判斷有沒有
  武裝」的 log 失去意義（啟動也會走 `_on_enter(MINING)` 清一次）。

### Config

```python
panel_filter_xy: tuple = (119, 441)       # 篩選框中心（2026-07-31 全螢幕 OCR 定位）
panel_clear_keystrokes: int = 8           # 打幾個 w；實測按鍵掉 ~25%，要過量
panel_clear_settle_s: float = 0.3         # 打完到 OCR 的等待（OCR 自身 ~1.1s 已是充分 settle）
panel_expected_header: str = "NORMAL"     # 標頭閘：讀到 IONIZED/SPECTRAL 一律不信任面板
```

`giveup_rescue_enabled` 保留原義（關掉即完全回到 2026-07-30 之前的行為）。

## Testing Decisions

好的測試只驗**外部可觀察行為**：判準的輸入輸出、實機裁圖跑完整管線的結果、以及方法之間
的接線與旗標流；不驗內部呼叫次數或參數。

**不開新接縫，三個都是現成的：**

| 接縫 | 測什麼 | 前例 |
|---|---|---|
| `miningbot/harvester.py` 純函式 | `rare_panel_ores(names)`：白名單命中、common 濾掉、unknown 濾掉、空輸入。`panel_is_zeroed(header, names)`：NORMAL+0 列為真、非 NORMAL 為假、有列為假、標頭讀不到為假 | `tests/test_harvester.py` 既有的 `parse_panel_ore_names` / 面板差分 / `pick_prechill_ref` 測試 |
| 實機裁圖跑完整 RapidOCR | 誤收側：`145_rescue_{pre,cur}_panel.png` 兩張都不得產生白名單礦名。真陽性側：`125_giveup_before_backpack.png` 必須讀出 `faedrine` 且判命中。標頭必須從同一次 `read_text_boxes` 取得 | `tests/test_panel_fixtures.py` 整檔就是為此存在（H069 已經加了 145 兩張） |
| `tests/fake_bot.py` 接線 | 進 MINING 兩條路（`_on_enter` 與 `_resume_mining_tail`）都清；`_panel_zeroed_at` 在驗過／沒驗過時分別被設成時間戳／`None`；`_panel_zeroed_at is None` 時路 B 跳過且不 OCR；標頭非 NORMAL 時判未歸零；清空序列的順序（清空 → `init_mining_sequence`）；例外不打斷 giveup | `tests/test_giveup_rescue.py`（同一組 fake bot、同一組 `_Rec` log 斷言、同一組降級分支測法） |

紅綠自證：把 `panel_expected_header` 改成別的值時，實機裁圖那組必須變紅；把
`rare_panel_ores` 的判準改回 `!= "common"` 時，145 那兩張必須變紅（那正是 H069）。

## Out of Scope

- **三頁循環（IONIZED／SPECTRAL）**。玩家確認切換是 NORMAL → IONIZED → SPECTRAL → NORMAL
  的三態循環、標頭 OCR 驗得出來，所以事後加得進來。但異色版本要踩到這個 bug 得同時成立
  三件事（D3 目標是異色版、它在 chill 前就被鎬子挖走、且會進聊天的路 A 也沒接到），
  機率複合。第一步只做 NORMAL，實機看到異色漏判再加。
- **讀數量欄**。同礦種第二次挖到只有數量 +1 這個天花板，被「每場歸零」繞過了，不需要
  讀數字。真要讀，2026-07-30 spec 已經寫好必要的 craft 面板守門（該面板從 x≈185 起疊在
  數字欄上，OCR 會讀到配方需求＝**錯的值不是缺值**）。
- **裁圖加高**。tier 排序讓白名單礦永遠在最上面，加高沒有收益；而且實測 bot 自己的 HUD
  落在面板柱裡，加高反而會製造假礦名（見 Further Notes）。
- **白名單漂移的位置推斷**。tier 排序下，「`unknown` 但排在已知 common 之上」＝白名單漏收
  的高階礦，理論上可用。但那是把 H069 剛封死的 `unknown` 重新放進判準，沒有負樣本語料
  之前不做。
- **路 A（聊天）**。完全不動。它的天花板（聊天淡出、`_reveal_chat` 在非前景時被丟掉）
  與路 B 不同，兩路互補的結構是刻意的。
- **`_late_chat_confirm` 的 `_chat_baseline is None` guard**。2026-07-30 spec 拒絕動它的
  理由（拆掉會讓 pre-sweep／post-sweep 呼叫點活過來＝提早中止 episode）仍然成立。

## Further Notes

### 2026-07-31 實機量測（`.scratch/measure_panel_clear.py`）

| 未知數 | 結果 |
|---|---|
| 篩選框座標 | **(119, 441)**；標頭 (118, 408) |
| `typewrite` 進不進 Roblox TextBox | **進得了**：`wwww` → `wwwwwww`，面板 1 列 → 0 列 |
| 按鍵可靠度 | **送 4 個進 3 個（掉 25%）** |
| settle | 首次讀到 0 列在 t=1.76s，其中 OCR 自身佔 ~1.1s → 重繪遠快於此 |

兩個附帶發現：

- **量測當下面板停在 `SPECTRAL` 頁**（不是 NORMAL）。標頭閘不是防禦性設計，是現況就
  已經錯了——若不加閘，bot 一恢復就會拿 SPECTRAL 頁的內容當 NORMAL 用。
- **bot 自己的 HUD 落在面板柱裡**：`挖礦中（暫停）` 在 (133, 972)、`動作：挖礦中` 在
  (104, 997)、`音訊：… 容量：` 在 (136, 1025)。`str.isalpha()` 對中文回 `True`、x 又
  ≤ `panel_name_col_max_x`(185)，所以裁圖若加高到 1080 會把 bot 自己的 HUD 讀成假礦名。
  這是「不加高」的獨立理由。

### 面板實際列數

實機全幀量到面板至少畫 **18 列**（一路到螢幕底 y=1080），現行裁圖只切 8 列。因為
tier 排序，這對本設計無影響——但任何未來想從面板讀「這場總共挖了什麼」的功能都要知道
這件事。

### 命中率統計要重新起算

H069 之前的每一筆 `HARVEST_RESCUED` 都可能是分類器造成的假命中，本設計又整個換掉路 B。
實機命中率／漏判率的資料收集（`docs/data-collection-pipeline.md` §1）從本設計上線後
重新起算。漏判分類表要同步更新：新增「`_panel_zeroed_at is None`（清空未通過驗證）」
與「標頭非 NORMAL」兩個降級原因。
