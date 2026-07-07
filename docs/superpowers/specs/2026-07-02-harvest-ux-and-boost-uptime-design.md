# 設計：採集 UX 調整 + boost 不空轉（2026-07-02）

> 狀態：**設計（未實作）**。交下一個 session 依此寫 plan → 實作。
> 本文評估 4 項需求並給出流程；每項標注「評估結論／要動的檔案／config／測試／風險」。

## 背景：本 session 已完成並 commit（`1c63e71`）

作為後續設計的前提，這些已經做好、驗證過（251 tests green）：

- **OCR 引擎改 tesserocr**（in-process，pytesseract 後備）：reset OCR 3062ms→~400ms。根因是
  pytesseract 每次 spawn `tesseract.exe`+載模型＝~2.5s 固定開銷，每 2s 卡住主迴圈 → boost 偵測被餓死。
- **`capture.grab()` BGRA→BGR 改 `cv2.cvtColor`**：154→19ms/幀（byte-identical）。
- **boost/D4 偵測節流 + `buff_scales`（3 尺度）**：每幀 344ms → 節流後多數幀 ~0；單次 216→143ms。
- **需人工介入附「前/後左側裁圖」**（`human_review_region`，背包+聊天框；before=`_pre_scan_ref`、after=放棄當下）。

重要事實（本 session 由使用者確認，設計前提）：
- **D5 節奏本身沒有變慢**（跨 3 天 actions.log 穩定 42–78s）；「boost 常常是空的」真因是上面的 OCR 卡迴圈。
- **boost 瓶子上「有」剩餘秒數**（實測讀到 22/32/39/10/26…）：位置在瓶子圖示底部，相對「瓶子 edge-match 中心」
  約偏移 `(+11, +28)`、盒約 44×30。但 **Tesseract 對這 ~22×13px 藝術字只 ~78% 準**，失誤都是「掉一位數 → 讀成偏小」
  （21→2、13→1；二值化更糟 5/9）。→ 若要「讀秒數控制時序」需改用**數字模板比對**（見 #4）。
- **按 D5 時若 boost 仍在，對 boost 沒有任何作用（不刷新、不浪費道具），但會花掉幾秒換道具時間**（打斷挖礦）。
  → **「提早補」無意義**；要不空轉只能「偵測到期的瞬間立刻補」。

---

## 需求 A：需人工截圖拆成 4 張（背包／聊天框各自獨立）

**現況**：`_harvest_giveup` 裁 `human_review_region=(0,105,470,970)`（整條左側）成 before/after 兩張。
Discord 縮圖對這種「窄高長條」不友善（見 `螢幕擷取畫面 2026-07-02 005050.png`：整張偏高、聊天區在縮圖裡不明顯）。

**評估**：✅ 值得做、低風險。把「聊天（寬短）」與「背包（窄高）」分開，各自更貼近縮圖比例，也砍掉右側沒用的粉紅場景。

**設計**：
- config 新增兩個子區域（取代單一 `human_review_region` 的用途；`human_review_region` 可保留或標記 deprecated）：
  - `chat_review_region`：左上 has-found 訊息。≈ 既有 `chat_region`(0,110,460,280)（可直接沿用/微調）。
  - `backpack_review_region`：左下 NORMAL 面板（礦名+數量）。由 005050.png 估 ≈ `(0, 395, 180, 660)`
    （寬只到礦名+數字 ~x180；高從 NORMAL 標題到清單底 ~y1055）。**實作時用實機截圖校準**。
- `_harvest_giveup` 改裁 4 張：`before_chat / after_chat / before_backpack / after_backpack`
  （before 來源＝`_pre_scan_ref`、after＝放棄當下 frame），依序放進 `image_paths`。
- Discord 一則訊息附 4 圖（`send_images_message` 已支援多圖）。建議附件順序：`[before_chat, after_chat, before_backpack, after_backpack]`
  或分組 `[chat_before, chat_after, bp_before, bp_after]`，讓使用者左右對照。訊息文字可標「上聊天/下背包，左前右後」。
- 注意 Discord 單訊息最多 10 附件、且**縮圖排列會依附件數自動排版**；4 張通常 2×2，正符合「前後×聊天背包」對照。

**檔案**：`config.py`（+2 region）、`main.py`（`_harvest_giveup` 裁 4 張）。**測試**：純 I/O glue，比照本 session 的
`verify_giveup` 手法（mock `_hsnap_crop` 計數/驗序）確認出 4 張、來源正確。**風險**：低；只需實機校準 backpack 區域座標。

---

## 需求 B：移除 sweep「先 D 挪位」機制，回歸單純八方旋轉

**現況**：`_sweep_for_tracker` 在 dir 2/4/6（右/後/左）轉動前 `ic.hold_key("d", 0.3)` 挪位清視野
（`should_strafe_at_dir`），且 strafe 模式下「只有弱候選時不走回」（`should_walk_back_to_weak` 回 False）。
此機制見 `2026-06-30-harvest-strafe-sweep-design.md`。

**評估**：⚠️ 這是**回退**一個近期功能。strafe 當初是為了「露出被角色身體/牆擋住的追蹤框」。移除後更單純、可預期
（純 `rotate_right×7`），但**可能重新暴露「身體/牆遮住追蹤框」的漏抓**。使用者已明確要移除 → 照做，但在此記錄取捨。

**設計**：
- `_sweep_for_tracker`：移除 strafe 區塊（現 `main.py:1037-1041` 的 `should_strafe_at_dir` + `hold_key` + `settle`）。
- `should_walk_back_to_weak`：strafe 拿掉後「弱候選走回最佳框」回歸原行為（等同 `True`）。做法二選一：
  (a) 直接把呼叫端改成無條件走回最佳弱候選（移除該 gate）；(b) 保留函式但讓它恆回 True。建議 (a)、順手刪函式。
- 刪 `harvester.should_strafe_at_dir`、`should_walk_back_to_weak`（若採 (a)）。
- config：移除/deprecate `sweep_strafe_enabled/key/hold_s/settle_s/dirs`（共 5 個）。
- 更新 `CLAUDE.md`（移除 strafe 段落，改註「單純八方旋轉」）與 `test_harvester.py`（刪 strafe 相關測試）。

**檔案**：`main.py`、`harvester.py`、`config.py`、`CLAUDE.md`、`tests/test_harvester.py`。
**測試**：改/刪 `test_harvester.py` 中 strafe 案例；確保 sweep 純邏輯（候選收集、走回最佳、verify）仍綠。
**風險**：中（回退占位功能，可能重現遮擋漏抓）——屬使用者決策，實作時保留 git 可回溯。

---

## 需求 C：放棄時依「有無追蹤框」決定視角處置

**現況**：`_harvest_giveup` **一律** `restore_view`（轉回原方位），並在有 `_target_marker` 時附 `rotation_hint`。

**使用者要的差異化**：
- **有找到追蹤框、但不明原因採不到**（`_target_marker is not None`，D3 階段失敗）→ **把視角留在／轉到追蹤框方位**
  再交人工（人工一眼看到框、可手動採）。
- **沒找到追蹤框**（`_target_marker is None`，sweep 一圈無框）→ **轉回原方位**（維持現況的「快速恢復」）。
  這是為了判別「礦是否已被玩家在直線路徑挖走 / 或在視線死角沒發現」——**除非能判別是否被玩家挖走，此機制必須保留**。

**評估**：✅ 合理且與語意相符。sweep 到 D3 階段時視角本來就面對追蹤框（D3 是點螢幕座標、不轉鏡頭），
所以「轉到追蹤框方位」＝**該路徑不要 `restore_view`**（維持面對框）即可。

**設計**（`_harvest_giveup` 內分支）：
- `if self._target_marker is not None`（有框、採不到）：
  - **不呼叫 `restore_view`**（保持面對追蹤框）；`net_rotations` 不歸零/不反轉（保留現狀）。
  - 截圖走「面對追蹤框」視角：沿用既有 `_save_tracker_screenshot(frame, marker, net_rotations)`（它本就是「轉回前截框」用途）
    或直接截當下全幀 + 標注框位。`image_paths` 以**追蹤框畫面**為主（人工要據此手動採）。
  - `rotation_hint` 這條路可省略（人已面對框，不需提示轉幾次）。
- `else`（無框）：**維持現況** → `restore_view` 轉回原方位 + 附**需求 A 的 4 張左側裁圖**（判別是否已被採走）。
- 兩條路都仍送 `NEEDS_HUMAN`（帶 `harvest_id`）。

**與 A 的關係**：4 張左側裁圖主要服務「無框（快速恢復）」路徑的「是否已被採走」判讀；「有框」路徑主秀追蹤框畫面。

**檔案**：`main.py`（`_harvest_giveup` 分支、可能沿用 `_save_tracker_screenshot`）。
**測試**：mock 兩種 `_target_marker` 狀態，驗證：有框→不呼叫 restore_view、image 走 tracker 圖；無框→呼叫 restore_view、走 4 張左側圖。
**風險**：低。注意「有框」路徑別再把 `net_rotations` 歸零導致後續狀態不一致（人工 `!resume` 時 `init_mining_sequence` 會重設視角，OK）。

---

## 需求 #4：boost「盡量永遠不空轉」

**目標與硬約束**（使用者確認）：
- 目標＝**不空轉**（到期→立刻補、把空窗降到最小）。
- **提早補無意義**（不刷新、不延長），且**每次多按 D5 都吃掉幾秒換道具時間**打斷挖礦 → 只能「**到期瞬間**才補」。
- 結論：不空轉 ⇔ **越快偵測到「瓶子消失」越好**（不是預測、不是提早補）。

**與本 session idea #1 節流的張力**：我為了「降低連續掃描」把 boost 偵測節流到 1s（到期最多晚 1s 補）。
這與「不空轉」相反。**取捨結論**：偵測現在已很便宜（`buff_scales`、cvtColor 後單幀 ~150ms），故用「**便宜的高頻偵測**」
即可同時滿足兩者——每次掃便宜（idea #2 已做），頻率拉高（滿足不空轉）。

### 方案 A（推薦、簡單可靠、免 OCR）：boost 高頻偵測
- 把 **boost** 的 `boost_check_interval_s` 調小（如 0.2s，或直接每幀）並用 `buff_scales=(1.0,)`（固定 UI，單尺度 ~56ms）。
  到期偵測延遲 ≈ 一個 tick(~150ms) + D5 生效時間 → 幾乎不空轉。
- **D4 維持較疏節流**（D4 不在意空轉，只是定期刷事件）——即使用者說的「d4 冷卻與 d5 類似但更長」。
- CPU：boost 每 ~0.2s 掃 56ms＝可接受（迴圈已因 OCR/capture 修復大幅變輕）。
- 風險：低。這其實是把 idea #1 的節流**對 boost 放寬**、對 D4 保留。

### 方案 B（進階、要建數字模板）：讀秒數做「自適應頻率」
- 用**數字模板比對**（不是 Tesseract）讀瓶底秒數：把 0–9 的實機字形裁成模板，對「瓶子中心+(+11,+28) 的 44×30 盒」
  切出 1–2 位數各自比對。固定藝術字 → 應遠比 Tesseract 78% 可靠。
- 有可靠秒數後：**中段（秒數大）跳過偵測省 CPU、近到期（秒數≤N）切高頻**直到消失→補 D5。兩全其美。
- 失誤安全性：即便讀偏小（掉位數），只會「提早進高頻」＝多掃、不會漏到期 → 安全。
- 成本：要蒐集 0–9 樣本（各數字至少一張實機裁圖）＋寫 digit-match；比方案 A 多不少工。
- **評估**：方案 A 已達「不空轉」目標；方案 B 只多省「中段 CPU」，而中段 CPU 在偵測已便宜後不是痛點。
  → **建議先做方案 A**；除非之後量到中段偵測 CPU 仍是問題，才上方案 B。

**檔案（方案 A）**：`config.py`（boost 專屬 interval 調小、可加 `boost_buff_scales`）、`main.py`（`_boost_needs_refresh` 沿用節流骨架、換參數）。
**測試**：沿用本 session 的節流計數手法，驗證 boost 高頻、D4 仍疏。**風險**：低。

---

## 建議實作順序（交下一 session）
1. **A**（4 張截圖）＋ **C**（放棄視角分流）——關聯緊（都在 `_harvest_giveup`/截圖），一起做。
2. **#4 方案 A**（boost 高頻偵測）——小改、直接解「不空轉」。
3. **B**（移除 strafe）——獨立、回退性改動，最後做並保留 git 可回溯。
4. #4 方案 B（數字模板）僅在確有中段 CPU 需求時再排。

每項先寫失敗測試（純邏輯部分）再實作；`_harvest_giveup` 等 I/O glue 用 mock-self 驗證（見本 session `verify_giveup` 手法）。
