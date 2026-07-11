# CLAUDE.md — Roblox REX 挖礦自動化

Windows 專用 Python 機器人，掛機玩 Roblox 遊戲「REX」（rex-3 wiki）：自動挖礦、用道具、聽到 chill 音效時採集稀有礦、礦坑重置時停下等人工。

## 指令
- 測試：`python -m pytest -q`（純邏輯 TDD，不需遊戲；改完必須綠）
- 啟動：`python -m miningbot.main`（Roblox 要先開好）
- 轉 chill 音檔：`python -m miningbot.convert_audio "chill.mp3"` → `assets/chill_reference.wav`
- 下載階級標記模板：`python -m miningbot.fetch_trackers`（→ `assets/markers/`）
- 同步 wiki 礦物清單：`python -m miningbot.fetch_ores`（Category:Worlds 動態發現**全部世界**（9 個）→ `assets/rare_ores.json` 高階白名單、`assets/ores_all.json` 聊天相關階級 Surreal+；印排除清單 diff＋跨世界低/高衝突報告；遊戲更新後跑一次。Common~Master 不進聊天、不收）
- 擷取事件模板：`python -m miningbot.capture_template boost`
- 校準偵測區：`python -m miningbot.calibrate`
- 回礦校準：`python -m miningbot.calibrate_surface --import NNN`（R 鍵截圖裁面板模板 → `assets/surface/`）／`--brightness NNN`（礦內/地表亮度簽名）

## 架構（狀態機）
主迴圈每 ~50ms 擷取一幀，純函式決定動作。狀態：`MINING / HARVESTING / NEEDS_HUMAN / RESET_WAIT / REENTRY`。
- **I/O 薄封裝**：`capture`(mss 截圖)、`audio`(喇叭 loopback + 交叉相關)、`vision`(OpenCV)、`ocr`(Tesseract)、`input_control`(pydirectinput)
- **純邏輯（有單元測試）**：`states`(轉換)、`geometry`(瞄準)、`miner`(事件分派)、`harvester`(採集步驟)、`events`
- `main.Bot` 組裝主迴圈；`status_hud` 置頂狀態窗；**`config.DEFAULT` 集中所有座標/門檻/熱鍵**。

## 硬規則 / 重要前提（多為實機踩過的坑）
規則後的 `(Hxxx)` ＝事故編號，完整經過/量測數據/踩坑敘事都在 **`docs/incidents.md`**——改規則或門檻前先去讀對應事故。

- **Roblox 要「最大化填滿螢幕」**：視覺座標照 1920×1080 校準。`_focus_roblox` 用 **SW_MAXIMIZE**，
  **絕不可用 SW_RESTORE**（會把全螢幕縮成小視窗、座標全錯）。音訊不受畫面影響。
- **啟動先設 DPI-aware**（`main._set_dpi_aware`）：否則 `mss` 第一次截圖才把行程切 DPI-aware，
  害 `GetWindowRect`/輸入座標在截圖前後不一致（視窗跑位偵測誤判 resized）。
- **道具數字鍵會 toggle 裝備**：對已拿著的工具再按一次該數字鍵 = **收起來**。所以 init 只在
  槽位顯示「沒拿鎬子」時才按 D1（見 `miner._ensure_pickaxe`）；D5/D4 用完按 D1 是從別的工具切回，OK。
  **D1 是否已裝備＝區域顏色判定（2026-07-10 起，`vision.slot_selected`）**：hotbar 選中的槽位底色會轉綠，
  量 `d1_slot_region`（slot 1 內部 54×58）的 greenness＝平均G−平均(R+B)/2，≥`d1_selected_greenness_min`(5.0)
  ＝已裝備。實測 選中≈+10.8、未選中≈−1.4（兩側夾 5.0）。舊寫死單點 `slot_pixel`(1011,845)/`slot_color`
  0x232323 已停用——**工作列調回顯示後遊戲底部 UI 整條上移約 50px**（實測 boost 瓶子 y1039→989），單點落到
  場景上（讀到紅色 ~[164,167,217]）→ 判定全錯；區域平均對輕微位移穩健。回歸：`tests/test_slot_fixtures.py`。
  **注意此 region 為 taskbar 可見版面校準**：若日後把工作列隱藏（回全 1080）需重新量 slot 1 位置。
- **轉視角＝ `,` / `.`（轉 45°，可數、可回歸）**；`pydirectinput.moveRel` 單獨用**不會**轉視角，
  細部瞄準要 **按住右鍵**拖曳（`input_control.aim_move`）。但右鍵難精準，策略以 `,`/`.` 為主。
- **旋轉一律走驗證式（2026-07-05，`Bot._rotate_verified`）**：`,`/`.` 可能被吃（pickup 動畫 1-2s 吃鍵窗口／焦點被搶）→ `net_rotations` 計數與實際角度脫鉤、視角停在 45° 斜角傷挖礦效率（成功路徑 restore_view 曾在動畫窗口內送鍵＝主要肇因，動畫等待已挪到 restore 之前；見 docs/incidents.md「視角回歸 45° 斜角」）。每次送鍵前後截 `rotation_verify_region`（中央偏上場景帶）比對：**兩訊號都近零才判被吃**（`harvester.rotation_looks_eaten`＝平均差＋`vision.frames_changed_frac` 有感變化像素佔比；近全黑礦坑旋轉平均差可能很低但佔比仍高——誤判重送＝過轉製造偏移，比漏判更糟）→ `_focus_roblox` 後重送（上限 `rotation_max_retries=2`）；重試用盡**不計入 net_rotations**（計數＝實際角度，restore 才必回原角）。套用點：sweep 兩個旋轉迴圈、成功/放棄路徑 `restore_view(rotate=...)`、`miner.init_mining_sequence`/`handle_cave` 的成對 `,`/`.`（成對淨 0 的前提是兩鍵都生效；右轉沒轉成就不左轉）。settle 含在 `_rotate_verified` 內，呼叫端不再自行 sleep 0.35s。
- **稀有礦採集流程（HARVESTING 狀態）**：
  1. `harvester.prepare_scan()` — 停止移動、置中鏡頭（裝備位置穩定）
  2. 置中後截 `_pre_scan_ref`（reference）— 排除「掃描前就存在的裝備/礦石假陽性」
  3. `harvester.execute_scan()` — 裝備 D2 + 點擊觸發掃描（等 1.5s）
  4. **全 8 方位掃描（`Bot._sweep_for_tracker`）**：rotate_right×7，每方位雙幀穩定確認（0.08s 間隔，誤差<8px 才接受），記錄有追蹤框的方位，**選「x 最居中」候選**（`harvester.pick_sweep_candidate`，H019 對策：同一顆框常橫跨相鄰 2~3 方位（45° 視野重疊），取最先看到的可離中心 500px+，FOV 位移易把框推進邊緣排除帶；居中候選天然留邊緣餘裕）後**走最短方向旋回該方位（`plan_return_rotations`，2026-07-04）**——可右轉 wrap 360°（best_dir=0 從左轉 7 次 ~2.4s 變右轉 1 次）；`restore_actions` 亦 `normalize_rotations` mod 8 取最短（淨 ±8 ≡ 不轉，省整圈 ~2.8s）。
     **早停（2026-06-29）**：某方位雙幀穩定且 `edge ≥ tracker_shape_early_exit=0.60`（遠高於裝備上限 0.26，實測真框 0.54-1.00）→ 人已在該方位，直接確定、免掃完剩餘方位也免轉回 verify（`find_tracker(with_score=True)` 外露 edge 分數）。分數不夠高者仍收集 → 掃完走 candidates[0]+verify（保留「不確定就繼續掃」）。
  5. D3 射擊：**開火前重定位（H015 對策）**——先重抓當下幀 re-find 追蹤框、用**當下座標**開火（找不到→立即重掃不浪費一發）。**根因：D5 boost 到期會收縮 FOV、畫面所有座標整批位移**（實測＝以畫面中心為錨的 ~2.6x 縮放（H026 量出）；buff 週期 ~60s、到期常落在採集中段；H015/H026）。**基準 OCR 移到「開火之後」跑（H026 對策）**——sweep 完成只截聊天裁圖（瞬間），先開火，~10s 的 OCR 挪到開火後、正好蓋掉等命中/框淡出的死時間（驗證窗口從 OCR 完成起算），確認→開火從 ~13s 縮到 ~1.5s。射擊序列不變：按 2（切離 D3）→ 等 0.15s → 按 3 → 等 0.3s → hold click 0.4s → 等 0.5s。
  5b. **HARVESTING 全程 boost 守門（H026 對策，`Bot._harvest_boost_guard`）**：MINING 的「D5 到期即補」在採集中不會跑 → 採集途中到期會全程凍在收縮後 FOV，ref/sweep 座標/重定位全部失準。守門在**每個關鍵點**（`_tick_harvest` 頂、sweep 每方位、verify 輪詢每輪、進場 ref 拍攝前）跑既有便宜瓶子檢查（單尺度 edge-match ~56ms、0.2s 節流），瓶子一消失→`miner.use_boost_harvest()`（不切 D1、不按住左鍵的採集版）→等 `boost_fov_settle_s=1.5s` FOV 展開→**重抓幀**再繼續。**「快到期先補」不可行**：buff 還在時按 D5 無效、無法續時（2026-07-02 實測），只能到期即補。
  6. **確認（`harvester.decide_verify_poll` 輪詢 → `decide_harvest_result` 收尾；2026-06-29 改「排除低稀有度」反轉策略）**：成功**只認聊天新增的稀有礦**（confirmed），不再用 `gone`。
     - **輪詢驗證（H015 對策）**：實機框是**擊中後 2~10s 才消失**、聊天成功行更晚到（且聊天無新訊息 ~15s 整個淡出、唯有新訊息會重新顯示）→ 單幀判生死必踩空窗。改在 `harvest_verify_window_s=8s` 窗口內輪詢：confirmed 隨時早退；窗口到才 RESWEEP/RETRY。聊天 OCR 有 `vision.frames_differ` 省 OCR 閘（角色靜止時聊天裁圖近乎逐位元相同，只在像素變了才重 OCR——滿版文字 3-pass 實測 ~10s/次，不能每輪跑）。**窗口到期最終確認（H020 對策）**：一次 OCR 7~11s ≈ 整個 8s 窗口＝窗口內只有一次機會；且幀差閘可能在聊天**淡入中**就觸發 OCR 並更新 `_chat_last_crop`（讀到半透明文字必歪、之後像素不再變不重讀）→ 判 RESWEEP/RETRY 前強制對最新幀再 OCR 一次（只在失敗路徑多花 ~10s，`_verify_chat_ocr(..., "final-check")`）。
     - **聊天基準（chat_before）＝episode 級（2026-07-04 起）：HARVESTING 進場時「截圖」一次、開火後才 OCR、跨本輪所有 D3 嘗試與 RESWEEP 共用、全程不作廢**（截圖/OCR 時點分離＝H026 對策，見步驟 5）：逐次重讀或 RESWEEP 作廢重取，都會把晚到的成功行吃進下一次基準→差分永遠看不見→重掃必然全空（礦已採走）→誤交人工（H032 延伸）。
     - **Episode 帳本＋晚到確認（H032 延伸對策，`ocr.ChatLedger`／`main._late_chat_confirm`）**：單一基準點對點差分守不住「成功行晚到被吃進基準」與「失敗路徑沒人看聊天、成功行被推到捲出裁圖」兩個時間軸破口。對策：每次 verify OCR 以「上一次讀取」為錨**鏈式對齊**（間隔短→錨點幾乎不會捲丟）把新增行累積進 episode 帳本（逐 pass 自洽），帳本累積出任一稀有 found 行即 confirmed 且全 episode 有效（領域事實撐住語意：單人作業＋Exotic+ 被動出土 ≤1/1M → episode 內新稀有行只可能來自自己的 D3）。失敗路徑三個決策點（重掃前 pre-sweep／掃完全空 post-sweep／D3 超時交人工前）先跑幀差便宜閘、像素有變才 OCR 做**晚到確認**，confirmed→直接 `_harvest_success` 成功收尾（與 poll 路徑共用；通知行＝基準差分抽取聯集帳本稀有行）。保守規則（寧漏勿假陽性，漏的由 count/底行長程信號兜底）：錨點對不到→該 pass 不追加、錨點不推進；上次讀取為空（聊天淡出）→只起鏈不計新增；tail 行 ≈ 上次已有行＝重讀、跳過（**噪音守門比「礦名部分」不比整行**——聊天行共享長前綴 `<名> has found `，整行相似度連不同礦都會過→真新增行被誤殺；同名稀有連續兩筆帳本不收，該情境 count 差分 1→2 本來就抓得住）。回歸：`tests/test_ocr.py` 的 ChatLedger 區塊。
     - `confirmed=True` → **SUCCESS**（不論框在不在）。`confirmed` = 聊天「`has found X`」裡 **X 不在低稀有度排除清單** (`game_data.common_ore_names()`) 的筆數**增加**，或**底部新出現一行稀有礦**（`ocr.count_rare_found` / `has_new_rare_found_last_line`）。特殊階（ionized/spectral）另由 `special_keywords` 字樣確認、也算 confirmed。
     - **聊天 OCR 首選 RapidOCR（2026-07-04 起，`ocr.read_text_multi` 自動分派）**：PaddleOCR 模型轉 ONNX（onnxruntime CPU），對彩色遊戲背景 UI 文字拼字精準；速度與三 pass 融合打平（滿版 ~3s、空圖 ~0.3s；**關鍵參數 `Det.limit_type=max`** 不把 280px 裁圖放大 2.6x，否則慢 3 倍）。回單元素 list、差分邏輯不變（對 pass 數無假設）；fuzzy 兜底保留當保險。未裝/init 失敗自動退回 tesseract 三 pass 融合（`PREFER_RAPIDOCR=False` 可強制退回）；banner/事件列小圖 OCR 不變、仍走 tesserocr。log 標籤用 `ocr.pass_labels`（單 pass 標 rapidocr，不誤標 min_channel）。**2026-07-04 實機裁決：留用**（H033~H038 六輪，見 docs/incidents.md）；已知弱點＝遊戲字型 **i/l 同形**且誤讀信心高（Essentium→Essentlum），由 classify 模糊兜底吸收（見下方三態分類）；**另一弱點＝整行空格讀成連字號（H041，2026-07-11）**：`small_lo has found Fortuitous` 讀成 `small-lo-has-found-Fortuitous`（conf 0.97-0.99 高信心、三次重測穩定）→ 整行黏成單一 token，精確子字串與 fuzzy（token 非行首規則）**兩條路同滅**、真成功誤交人工——對策＝found 行解析加連字號 fallback（`ocr._dehyphenate_if_unmatched`：原比對全滅且含 `-` 才 `-`→空格重比；排除清單 startswith 兩側對稱去連字號，一般礦黏行仍被排除、白名單連字號礦名 X-Flare/Sub-Zero 不受害）。回歸：`tests/fixtures/chat/h041_*.png`＋`test_ocr.py` H041 區塊。**init 實機 6~7s（非 benchmark 的 2.5s）→ Bot.run 啟動時背景執行緒預熱**，別讓它吃掉第一次採集的 verify 窗口（H032/H033 踩過）。
     - **聊天 OCR 後備＝多前處理融合（H014 對策；rapidocr 缺席時的路徑）**：基準與輪詢皆用 `ocr.read_text_multi`（`CHAT_PREPROCESSES`＝min_channel/gray/dark_mask 各 OCR 一次；滿版文字實測 ~3.3s/pass、3 pass ~10s，空白圖 0.14s，故只在「基準」與「輪詢中像素有變」時跑），`ocr.any_new_rare_found` **逐 pass 自洽差分**（不同 pass 噪音不同、不可交叉比），任一 pass 確認即成功。**單一前處理必有背景盲區**（H014：min_channel 為暗背景校準、在亮粉糖果礦壁上彩色行全滅→真採到卻假陰性誤交人工；dark_mask 反之在近全黑礦坑失效）。**改前處理必跑回歸集 `tests/test_ocr_fixtures.py`**（實機裁圖×三種背景），新背景樣本從 `logs/snapshots/trace` 補進 `tests/fixtures/chat/`。
     - **模糊 found 兜底（H020 對策）**：H014 是「整行讀不到」（前處理盲區），H020 是**「行讀得到、關鍵字讀歪」**（`has found` 被讀成 `hee foumel`，精確子字串全滅→假陰性）。對策：`any_new_rare_found(..., rare_names=game_data.rare_ore_names())` 加模糊路徑——found-ish token（SequenceMatcher≥0.52、**非行首**（found 行前面必有玩家名）、**長度≥4**）＋其後礦名對**白名單** fuzzy ≥0.62 **且嚴格高於排除清單分數**（雙向最近鄰，平手判 common，寧漏勿假成功）。門檻由 H020 實資料兩側夾出（數值見 docs/incidents.md）。白名單檔缺→`rare_ore_names()` 空→fuzzy 自動停用（降級回精確）。回歸：`tests/fixtures/chat/h020_*.png` 鎖「精確=False、fuzzy=True」。
     - **verify 詳細 log（H020 起，這類假陰性已發生多次）**：poll 每輪 DEBUG 記 chat 像素差值 vs 門檻（回答「為何那輪沒觸發 OCR」）；每次 OCR 記觸發原因/耗時/逐 pass 稀有計數/末行原文；fuzzy 收/拒診斷附雙邊分數；**每輪收場（成功或失敗）都逐 pass OCR 全文落盤 `trace/*_chat_ocr_<verdict>.txt`**（`_dump_chat_ocr`——失敗查假陰性、成功查誤判成功；事後排錯不必重跑 OCR、引擎一改也不可重現）。**RapidOCR 觀察期裁決輸出（2026-07-04）**：init 成敗記 miningbot.log（用哪個引擎/為何降級）；每次 rapid 呼叫逐行信心分數記 harvest.log DEBUG；**found 行信心 < `ocr.RAPID_LOW_CONF_THRESHOLD`(0.80) 記 WARNING**——grep WARNING 即收集疑似讀歪樣本（`_log_rapid_diag`／`ocr.pop_rapid_diagnostics`）。
     - 框消失但無新稀有礦（gone & ~confirmed）→ **RESWEEP**：礦被**掃描到期**拿走，原地再射也射不到 → 立即重掃（不浪費 attempts）。
     - 框還在且未命中（~gone & ~confirmed）→ **RETRY**：原地重試 D3。
     - **為何不再用 `gone` 當成功（踩坑根因）**：「框消失 ≠ 我們採到」——真追蹤框會因 **D2 掃描到期（框自己淡掉）**而消失，舊邏輯 `gone or confirmed` 把這誤報成功（2026-06-29 實錄見 docs/incidents.md 前置事故）。
     - **階級/聊天/聲音機制（使用者確認 2026-06-29，關鍵前提）**：**只有 Surreal + Mythic 兩階會被動出現在聊天框**；Exotic 以上不被動進聊天，改用 **chill 聲音**觸發採集。但**用 D3 親手採到高階礦時，那一筆會進聊天** → 不在排除清單（清單只含 Surreal/Mythic）→ 被算成稀有 → confirmed。故排除清單天生完整（會進聊天的就這兩階），是它有效的關鍵。清單的角色＝**排除器**：擋掉低階誤觸發，剩下不在清單的 has found ＝真正採到的高階。
     - **為何「排除低稀有度」而非「列舉高稀有度」**：聊天「`<小名> has found X`」混了低階礦（Surreal/Mythic）和 D3 採到的高階；單人作業 `小名` 就是自己、污染源同名 → 名字過濾無解。高階礦太多列不完，**低階反而有限且封閉**（只有兩階會進聊天）→ 列舉低階當排除清單（`World.common_ores`）。代價：漏列會進聊天的低階礦、或 OCR 把礦名讀錯 → 偶發假成功（用 `startswith` 容忍尾端雜訊、偏保守降低誤判）。
     - **為何比「數量」不是「存不存在」+ 對抗捲動**：上一輪留下的稀有礦會同名出現 2-3 次；且**舊訊息會從頂部刷掉 → count 可能 2→1 假負**。故主信號是 `has_new_rare_found_last_line`（只看底部最新行，捲動只影響頂部），count 增加為輔。
     - **底部新增行對齊（H032 對策，`ocr.new_chat_tail_lines`）**：「新稀有行必在底部」在**多行同窗口抵達**時不成立（H032：一般礦行排在成功行後面→底行信號滅；頂部剛好捲掉舊稀有→count 不增也滅→雙滅假陰性誤交人工）。對策：把 before 底行對齊到 after 中的錨點（候選多個取「向上連續吻合最長」者，錨點行容忍 OCR 噪音 `FUZZY_STALE_LINE_RATIO`），錨點之後**全部**都是新增行、任一行是稀有 found 行即 confirmed（`has_new_rare_found_tail`，模糊路徑同步支援）；對不到錨點回空＝保守交回 count/底行信號，不引入假陽性。回歸：`tests/test_ocr.py` 的 H032 實錄區塊。**變體行帶冠詞**（同批發現）：實際聊天行是 `has found an ionized Diamantine`，`_strip_variant` 不剝冠詞則 `an ionized ...` 對不上排除清單 → 被動低階變體被當稀有/special（假成功風險）→ 現先剝 `an`/`a` 再剝變體前綴（`classify_found_ore` 共用同函式一併修正）。
     - **變體前綴＋special 判定（2026-07-03 wiki 證實後改）**：**Rare/Master 的 Spectral 變體也會被動進 local chat——H039 實錄證實 ionized 也會**（被動 `an ionized Heartstone` 缺列→假 special＋計入 rare count，詳 docs/incidents.md）、Surreal/Mythic 全變體都會 →「has found Spectral Bandeau」必須剝 `ocr.VARIANT_PREFIXES`（spectral/ionized）再查排除清單（否則 startswith 對不上→假成功）。special 判定＝`any_new_special_found`（**綁 found 行＋base 不在排除清單**，逐 pass 差分）——舊版只看 spectral 字樣出現、事件文字/被動低階變體都會誤觸。
     - **三態分類（confirmed 成功後的通知標注，`game_data.classify_found_ore`）**：新增行的礦名剝前綴後查——排除清單→原樣；`assets/rare_ores.json` 高階白名單（fetch_ores 抓的 Exotic+，254 個）→附階級/稀有度；**都不在→標「⚠ 未知礦名」仍算成功**（安全方向：礦多半真的採到了），清單漂移（遊戲更新/OCR 誤讀）自己浮出來。白名單檔缺→安全降級全 unknown。**精確都對不上再走模糊最近鄰兜底（H033 對策，`CLASSIFY_FUZZY_RATIO=0.80`）**：RapidOCR 對遊戲字型 **i/l 同形**誤讀信心很高、低信心 WARNING 抓不到→高階被標未知、低階誤讀洗版未知警告；0.80 遠高於垃圾救援層 FUZZY_ORE_RATIO=0.62——只修近失拼字、真清單漂移仍落 unknown（H020 垃圾誤讀不可被吃）；rare 須嚴格贏過 common（寧漏勿假），命中回 `rare_fuzzy`＋fuzzy_ratio、通知標 ≈ 供人工核對。**排除清單仍手動維護在 game_data**（安全關鍵、須人工過目；fetch_ores 印 diff 輔助，有測試鎖「Exotic 以上絕不可列」）。**機制事實（wiki）**：所有 find 都進 local chat，只是 Exotic+ 被動挖到 ≤1/1M → 聊天高階行實務上＝D3 採的；chill＝「Chills 設定選定的 Exotic+ tier 出土音」。
     - **Z 雷達不產生 has found、且未實作 → 與採集確認無關**。
     - **未來方向（使用者提到）**：可能關閉「部分高階礦的聲音」，讓「只有出聲的高階」才觸發採集＝天然過濾想採的礦；屆時觸發判斷會更依賴 chill 音訊的**前後對比**（`ChillListener`）。
  7. 成功後 `harvester.restore_view(net_rotations)` 轉回原視角 → `miner.init_mining_sequence()`（與 Q 恢復/啟動相同的完整序列：清鍵→視角→置中→確認鎬子→W+左鍵）
  - **超時兩階段**：sweep 階段 `sweep_timeout_s=30s`；sweep 完成後重置計時器（聊天基準 OCR 的 ~10s 不吃 D3 預算），D3 階段 `harvest_verify_timeout_s=45s`——一次 D3 嘗試實測 ~20s，舊 15s 連一次都裝不下 → RETRY 後 1s 即超時交人工、5 次重試預算形同虛設（H015 根因之一）。
  - **重試**：RETRY 連 `max_harvest_attempts=5` 次未命中 → 重掃（`_reharvest_sweep`）；RESWEEP 立即重掃；sweep 失敗依「掃描時是否看過穩定框」分流（`harvester.decide_sweep_failure`，H019 對策）——**全 8 方位都沒看到** → 人工（2026-06-29：偵測已準，再掃不會更好；但 2026-07-07 實錄 harvest 044-064 有一批真框薄/暗/被遮、shape-edge 0.19-0.22 被 hard_rej 而全空——真框 edge 與裝備假陽性 ≤0.30 重疊，**不可降門檻**，正解是裁模板補進 `assets/markers`。故 `config.sweep_empty_snapshot`（預設開）全空時存每個方位全幀到 `snapshots/trace/` 供事後 `_diag_tracker` 診斷/裁模板）；**看到過但轉回後 verify 失敗**（FOV 位移/邊緣裁切）→ 框確實存在，**重掃一次**（上限 1 次防無限循環）。交人工時 **先 `restore_view` 轉回原視角**（放棄路徑統一走 `_harvest_giveup`，讓畫面回正便於人工判斷「礦已被挖走」的好假警報）。**`_reharvest_sweep` 不重拍 `_pre_scan_ref`（H026 對策）**：重掃時追蹤框往往已在畫面上，重拍會把「活框」寫進排除基準 → 之後每方位偵測都 `rej(preexist)`、**自我致盲**；沿用進場時「框出現前」拍的 reference（靜態 UI 不隨視角/FOV 變、排除效果不減）。
  - **聊天裡的 `小名 has found` 全是自己**（單人作業、無其他玩家）：混了**普通鎬子挖的一般礦**（Lovelocket/Bandeau 等在左側 NORMAL 面板）和 D3 稀有礦——故不能用「出現 has found」判斷成功，要**排除低稀有度礦後看是否有新稀有礦**（見步驟 6）。
  - **遊戲資料分世界（`game_data.World`）**：REX 分 world，每世界各有 `events`（D4 事件）與 `common_ores`（低稀有度排除清單）。目前有 **Aesteria + Lucernia**（Lucernia 含 2026 春季四圖層 Amourite/Shamrock/Brittlestone/Harmonine 與洞穴限定，wiki Lucernia 頁為資料源；洞穴礦聊天行帶 `(Xxx Cave)` 尾註、`startswith` 容忍會正確排除）；新增世界＝建一個 `World` 加進 `WORLDS`。`EVENTS` 是模組層相容別名＝Aesteria 事件。**排除清單以 Surreal/Mythic 為主，Rare/Master 底名可列（H039 起，Heartstone 為首例）**——Rare/Master 的 ionized/spectral 變體會被動進聊天、剝前綴後查的是底名；fetch_ores 只收 Surreal+ 印不出這類 diff，缺口要從實機「⚠ 未知礦名」警告補。**Exotic 以上絕不可列**——是 D3 目標，列進去＝重演 H014 假陰性（真採到 Diamorite 卻被排除）。
  - **世界偵測（`game_data.detect_world`/`update_world_from_event`，2026-06-29）**：遊戲不直接顯示在哪個世界，靠**「看到的事件屬於哪個世界」**推斷（事件分世界）。`main._maybe_detect_world` 搭既有事件 OCR 便車（`_check_reset` 每 2s + D4 路徑）呼叫；某事件唯一命中一個世界 → `set_world` 鎖定（跨世界共用事件＝無法區分→不鎖）。**世界未確定時 `common_ore_names()` 用「所有世界聯集」當保守排除清單**；鎖定後收斂成該世界的，更準（同名礦在不同世界階級可能不同，用錯世界會把高階採集目標誤排除→漏判成功）。`match_event`/`fuzzy_match_ore` 一律搜全世界聯集（讀到事件時可能還沒鎖世界）。

- **追蹤框偵測 `vision.find_tracker`（2026-06-28 改混合方案）**：HSV 快速定位 + 實機裁圖外框形狀確認。
  1. **HSV 候選**：各色系範圍獨立 mask（不合併）→ reference_bgr 差分（同色 fill>0.15 排除掃描前就有的）→ **色相無關** colored 確認（`(S>90)&(V>90)`，門檻 `colored_frac>0.40`；**不可再加 `(H<35)|(H>95)`**——那會漏抓黃綠中心礦如 Ionized，是 very_rare.png 踩過的根因）。**ring_score 環形結構/`frame_fill` 只當軟訊號（`ring_ok`），混合模式不硬拒**（見下）。
     - **colored 必須量「整個 bbox」、專注外框，不可只看中心（2026-06-29 黑心框踩坑）**：追蹤框中心顏色每次會變（不同礦色/粉紅/甚至**純黑空心**），中心非不變特徵——只量中心會把黑心真框當暗色 UI 面板拒掉。量整個 bbox 的彩色佔比：真框厚實外框佔比高（黑心 0.51-0.62、彩心 0.7-1.0），細框暗 UI 面板低（0.16-0.33）→ 門檻 `colored_frac>0.40` 區隔，形狀確認再精篩。
     - **ring_score/`frame_fill` 不可在形狀確認前硬拒（H001–H013 綠實心中心踩坑）**：追蹤框中心可能是**亮礦色實心方塊**（小框 mask 同吃外框+中心→`fill≈1.00`、`ring≈0.00`），舊版在形狀確認前就殺掉真框→sweep 八方全 None、放棄交人工。**與黑心框同類（「中心非不變特徵」）**：改由形狀 edge 當精準仲裁——`edge≥threshold` 一律 confirmed（不看 `ring_ok`，救回實心/彩心真框）；`ring_ok` 只保留給 (a) 純 HSV 後備（無形狀模板時唯一結構過濾）、(b) borderline survivor 防線（`hard_floor≤edge<threshold` 才需環形，擋非環形假陽性翻盤）。
  2. **形狀確認（`shape_templates`）**：在每個 HSV 候選周圍小 ROI 跑「實機裁圖外框」邊緣比對（`best_outline_score`≥`cfg.tracker_shape_threshold`＝**0.42**），拒「有色但非追蹤框形狀」的假陽性（如角色裝備誤射）。只在小 ROI 跑（全幀模板比對 5~23s/幀太慢）。**門檻 0.45→0.42（2026-07-02）**：實機真框 edge≥0.43、裝備假陽性≤0.30，中間有 gap → 0.42 收得回「被角色帽子擋到角」的近失綠框，而 `hard_floor` 0.30 + `colored_frac>0.40` 仍擋裝備。**追蹤框可能疊在角色身上**（頭頂/胸前），別因「在角色上」就當非框（使用者確認）。
  3. **雙幀穩定**（`_tick_harvest`/sweep 內）：連續兩幀誤差 < 8px 才採用。
  4. **邊緣排除帶收窄 `cfg.tracker_margin_frac=0.02`（H026；vision 函式預設仍 0.10，實戰由 main 傳入）**：H019 右緣、H026 底緣兩次**真框**都被 0.10 的帶擋掉——D5 到期 FOV 縮放把框推到邊緣，且 **yaw 旋轉只改 x 不改 y → 底緣框 8 方位永遠在帶內**、換方位也救不回。0.02 對全 fixture 集無新假陽性（邊緣雜訊由 preexist 差分/colored_frac/形狀確認擋）；回歸 fixture：`assets/edge_clipped_tracker_scene.png`＋`assets/bottom_edge_tracker_scene.png`。
  5. **shape ROI 必須裝得下最大實機框 `tracker_shape_roi_px=320`（H040，2026-07-11）**：追蹤框可渲染到
     **207×208px**（近距離粗紅方框，harvest 070），舊 ROI 160×160 根本裝不下——模板×尺度超過 ROI 被
     `_best_edge_match_sized` 的 `th>sh` 跳過、120px 模板對 207px 框尺度差 1.7 倍 → edge 崩到 0.28-0.32
     全 hard_rej → 8 方位全空誤交人工。**ROI 尺寸＝可偵測框大小的硬上限**，這型光裁模板救不了；
     320 兩側夾實測：TP（`assets/red_square_tracker_scene.png`）edge=1.00 命中、紅緞帶裝備負樣本
     （`assets/red_ribbon_equipment_scene.png`）不誤收；roi 撐大唯一新增誤收＝工作列圖示 borderline
     （靜態 UI，實戰被 pre-scan reference 差分擋）。回歸：`tests/test_vision.py` H040 區塊。
  - **模板必須用「實機裁圖」不是 wiki 圖**：wiki 是透明 PNG 只有外框（alpha），但向量 icon 邊緣在合理尺度配不到遊戲內渲染框（實測全 miss）；實機裁圖 edge≈0.91 且**一張可跨階通用**（顏色無關，色相位移仍命中）。形狀確認集 = `assets/markers` 內無 alpha 的裁圖（自動篩，wiki 排除）。新階礦從 log snapshots 裁實機框補進去即可（H039 的 enigmatic 尖刺太陽形框是首個新形狀案例；H040 的 207px 粗紅方框 `red_square_tracker_real.png` 是第 4 種——注意這型還需要 ROI 裝得下，見上方第 5 點）。**半自動裁模板工具**：`python logs/_diag_tracker.py "logs/snapshots/trace/*sweep_empty*.png" --crop-to assets/markers/staging`——對每張幀裁「最像追蹤框的候選」±shape_roi_px 方形、分數進檔名（colored/edge），人工挑高分乾淨的改名 `<tier>_tracker_real.png` 移入 `assets/markers/`（支援 glob 批次；search `sweep_empty` 全空診斷幀）。

- **`harvester.prepare_scan()` / `execute_scan()` 分開的原因**：
  中間截 reference 才能排除「D2 裝備後才出現的光效」假陽性。`start_scan()` 是 convenience wrapper（兩步連做），測試用。

- **D2 掃描＝按 2 後還要 click 畫面中央才觸發**（純按 2 只裝備，不掃）；掃描成功 = 左下出現「Local」。
  掃描在有 UI 彈窗開著時點不到（點擊被彈窗吃掉）→ 掃描前要先確保無彈窗。
- **D3 採集 = 先按 2（確保 D3 未裝備）→ 等 0.15s → 按 3 → 等 0.3s → hold click 0.4s → 等 0.5s 在 tracker 螢幕座標**：
  **數字鍵會 toggle**：若 D3 已裝備再按 3 = 卸下 D3（踩坑 2026-06-27，retry 時第二次必定 miss 的根因）。
  故每次發射前必須先按 2 切離 D3，再按 3 裝備——這樣無論現在拿著什麼都安全。
  瞬間 click 無效；按 3 後不等也無效（0.3s 裝備 + 0.5s 伺服器回應，2026-06-28 實測減半仍可靠）。
  D3 以**滑鼠點選位置**瞄準（非 crosshair 方向），不需旋轉 camera。
  tracker 立即消失 = 成功；緩慢消失 = D2 掃描到期，需重新掃描。
  **採集成功後恢復挖礦用 `miner.init_mining_sequence()`**（與 Q 暫停恢復、啟動完全相同的完整序列）——舊的精簡 `resume_mining()` 常漏按住 W（採集後鍵盤殘留狀態讓 `key_down("w")` 失效），已移除統一走 init。
- **chill 偵測靠喇叭 loopback**（`audio.LoopbackCapture` 餵 `ChillListener`）；預設只靠音訊
  （`chill_require_ocr=False`）。**真實 chill 約 0.4**（非參考檔的 1.0），門檻設 ~0.30。
  **match_score 很重（~110ms）**，每 chunk（85ms）都算會讓音訊執行緒積壓→6s 延遲。
  解法：score 每 `audio_score_interval_s`（0.3s）算一次，緩衝每 chunk 照常更新。延遲 ~1s。
  **低分觸發（0.26-0.39）≠ 誤觸**（H034：0.26 採到 Transcendent）＝真 chill 但缺參考家族
  → 擴充參考集 `python -m miningbot.add_chill_ref --scan`（chill 至少 4+ 音效家族，單參考必漏）。
  **--scan 預設只收 confirmed（chill_audio_\*）**——盲掃 `_miss` 經對照實驗全是雜訊、純假觸發風險
  （「與現有參考不像」分不出新家族 vs 雜訊，詳 docs/incidents.md H034）；`_miss` 要 `--include-miss`
  顯式 opt-in＋人工聽過。**參考變多要同步查 decimate 預算**（12 refs×k=4 一輪 ~312ms 超過 0.3s
  間隔必積壓）：已改 `audio_match_decimate=8`（8 refs ~98ms；k=4/8 分數差 ≤0.007）。
- **D4 事件保留**：USE_D4 前讀頂部事件列 OCR → `game_data.match_event` → `is_kept` →
  在 keep 清單 → `use_activity_keep()`（左鍵確認）；否則 `use_activity()`（右鍵刷新）。
  keep 清單透過 Discord 命令控制（`!keep`/`!list`/`!clear`），背景執行緒每 10s 輪詢。
- **所有座標/門檻改 `miningbot/config.py`**；**輸入保留延遲**（太快會被吃掉，放開挖礦左鍵後要 `settle`）。
- **OCR 引擎＝tesserocr（in-process）優先、pytesseract 後備（`ocr.read_text`）**：pytesseract 每次
  `image_to_string` 都 spawn 一個 `tesseract.exe` 子行程 + 重載模型＝**與圖無關的 ~2.5s 固定開銷**。
  這 OCR 在 MINING 每 2s 跑一次（`_check_reset`），**同步跑會卡住主迴圈 ~2.5s → 每幀的 boost 偵測被餓死
  →「boost 常常是空的」（D5 補太慢的真因）**。tesserocr 同引擎/模型、**準度不變**（banner OCR 3062→~400ms）。
  `PyTessBaseAPI` 非執行緒安全 → 比照 `capture` 的 mss 用 `threading.local` 每執行緒各持一個持久 API；
  未裝/初始化失敗自動退回 pytesseract（`PREFER_TESSEROCR=False` 可強制退回）。安裝見 `requirements.txt` 註解。
  **2026-07-04 再進一步：banner OCR 整顆移背景執行緒（`main._banner_ocr_loop`）**——tesserocr 的 ~400ms
  仍每 2s 同步卡主迴圈一次（D5 到期偵測跟著被拖）。worker 讀主迴圈每 tick 發佈的 `_latest_frame`
  （grab 後 buffer 不再改寫、跨執行緒唯讀安全），寫 `_mine_resetting`/`_banner_text` 快取；D4 路徑 4s 內
  重用快取免同步 OCR。**回 MINING 入口必清 `_mine_resetting`**（worker 只在 MINING 跑，RESET_WAIT 期間
  快取凍在 True，不清會一回來就彈回 RESET_WAIT）。搭配主迴圈 sleep 補償（50ms 目標節奏扣掉 tick 已花時間、
  保留 10ms 下限讓 GIL）與 `_focus_roblox` 焦點輪詢早退（固定睡 1.0s → 每 50ms 查、到手即走），
  MINING tick 穩定 ~0.12-0.16s、D5 補瓶延遲最壞 ~0.8s → ~0.2s。
- **`capture.grab()` BGRA→BGR 用 `cv2.cvtColor`（不是 `np.ascontiguousarray(arr[:,:,:3])`）**：後者對
  stride-4 的 view 逐元素複製、實測 154ms/幀；cvtColor 走 SIMD、19ms、輸出 byte-identical。grab 每幀都跑
  （主迴圈 ~20/s + sweep 一輪 17 次），這 ~135ms/幀省很大。（mss 原始 full grab 本身在此機 ~106ms，
  更快可換已裝的 bettercam ~25ms——但目前非瓶頸，未接。）
- **boost 高頻偵測「不空轉」＋ D4 較疏節流（`buff_scales`）**：`_boost_needs_refresh`/`_activity_ready` 原本每幀跑
  5 尺度 edge-match（共 ~344ms/幀）→ 改成節流 + 少尺度、其餘沿用快取（`_boost_present`/`_activity_present`）。
  - **boost（不空轉）**：提早補 D5 無意義（不刷新、還浪費換道具時間打斷挖礦）→ 只能「到期瞬間即補」＝越快偵測
    瓶子消失越好。偵測已便宜（單尺度 `boost_buff_scales=(1.0,)` ~56ms）→ 用高頻 `boost_check_interval_s=0.2s`，
    到期延遲 ≈ 一個 tick + D5 生效，幾乎不空轉。
  - **D4（不在意空轉）**：維持 `buff_scales=(0.9,1.0,1.1)` 3 尺度 + `activity_check_interval_s=3s` 較疏。
  - 進階（未做，spec #4 方案 B）：用數字模板讀瓶底秒數做自適應頻率（中段跳過、近到期高頻）——僅在量到中段 CPU 仍痛時才上。
- **需人工介入（採集放棄）依有無框分流（`_harvest_giveup` → `harvester.plan_giveup` 純決策）**：
  - **有框採不到**（D3 階段超時，`face_tracker=True`）：**不轉回**、保持面對追蹤框，tracker 群給追蹤框裁圖
    （`_save_tracker_screenshot`），人工一眼看到框可手動採；不附 rotation_hint（已正對著框）。
  - **沒找到框 / 掃描超時 / 採到但聚焦失敗**（`face_tracker=False`）：**轉回原視角**。
  - **兩條路徑都附 4 張左側前後對比裁圖（H015 對策）**：D3 超時交人工時框往往已消失（其實已採到、驗證抓太早），
    只送框裁圖＝圖上空無一物、人工無從判斷 → 有框路徑也附前後對比（tracker 群排最前，`_REGION_CAPTIONS["tracker"]`）。
    附圖＝`chat_review_region`×前後、`backpack_review_region`×前後。**Discord 分則發送：先聊天框（前/後），再背包（前/後）**
    （`harvester.giveup_send_groups` 依 region 分組 → meta `image_groups` → `notify.format_group_messages`／sink 各發一則；
    第一則帶完整警告文字＋群標題，其餘只帶群標題）。舊版一則附 4 圖（2×2）縮圖太小，拆兩則各 2 圖更清楚（2026-07-02 需求）。
    before＝**本輪採集開始時的 `_harvest_origin_ref`**（H020 對策：舊版用最近一次 sweep 的 `_pre_scan_ref`，
    但 `_reharvest_sweep` 會重拍它→礦已採到才 RESWEEP 時前後兩張一模一樣、對比失去鑑別力）、
    after＝轉回後現況；左側 UI 是螢幕覆蓋層、不隨鏡頭轉動 → 前後同框可直接比對「礦是否已被採走」
    （新 has-found 行 / 背包數量增加＝已採到）。舊版單一 `human_review_region` 窄高長條對 Discord 縮圖不友善，拆兩區更貼縮圖比例。
- 熱鍵用**全域輪詢**（`Bot._check_hotkeys`，GetAsyncKeyState）：**Ctrl+Q** 緊急停、**Q** 暫停/繼續、
  **F12** 結束、**R** 手動取樣視窗（編號截圖＋俯仰歸位/微調；開啟時自動暫停挖礦；用法詳 `docs/manual-sampling.md`）。
  **啟動環境檢查期間按 Q＝跳過剩餘檢查直接開挖**（程式重開環境沒變時用；單向非 toggle，
  init 完成後 Q 回歸暫停/繼續；語意分派在 `states.toggle_pause_action` 的 `skip_env` 分支。
  **原 F8 專用鍵與 Roblox 內建功能衝突而廢棄（2026-07-10 實測）——別再掛 F 系專用鍵**；
  設計見 `docs/superpowers/specs/2026-07-10-fast-startup-skip-design.md`）。
  焦點在遊戲也有效（`keyboard` 庫在遊戲前景時收不到，已棄用）。熱鍵執行緒在 `run()` 開頭就啟動
  （2026-07-10 起）——環境檢查期間 Q/Ctrl+Q/F12 全部有效；Movement Mode 鏈另有
  `menu_budget_s`(90s) 總預算，超時自動中止走失敗路徑（實測成功 71~82s、失敗曾燒 170s）。
  **啟動事前確認只剩兩項（2026-07-11 需求）：玩家列表關閉＋聊天框開啟**。Movement Mode 鏈
  **不再於啟動跑**（回礦功能未完成、設定不會被動到）；備而不用——只有 `_auto_reenter_active()`
  （auto_reenter 開＋surface 面板模板在）時，才在 session 第一次礦坑重置結束、恢復挖礦
  （`_on_enter(MINING)`、init 序列前）跑一次。auto_reenter 未啟用＝整個 session 都不跑。
  **R 視窗俯仰鈕（2026-07-11）：聚焦後必須 settle 再拖**（`sampler_pitch_focus_settle_s`）——
  實機三次「聚焦成功」但拖曳全沒生效＝焦點剛從小視窗切回就送右鍵拖曳會被吃（與旋轉鍵被吃
  同家族）。拖曳前後幀差驗證（量測同 `_rotate_verified`）：歸位冪等（飽和→回拉）可自動重試
  一次；微調不重送（誤重送＝記帳脫鉤）只記 log＋HUD 警示。
  **俯仰驗證用獨立門檻 `pitch_eaten_*`，不可共用旋轉門檻（2026-07-11 晚間對策）**：settle 後
  右鍵拖曳仍會偶發被吃（歸位一度 0/5 生效；被吃時游標物理滑到工作列、hover 彈出視窗預覽縮圖
  ＝右鍵按下沒被遊戲註冊的鐵證），但旋轉門檻（mean≤2.0 且 frac≤0.02 才判被吃）是為近全黑
  礦坑校準——地表粒子特效讓「沒動的畫面」frac 也有 0.022~0.045 → 全數誤判「生效」、歸位的
  attempt 2 重試從未觸發。兩側夾（被吃 mean≤3.29/frac≤0.045、真生效 mean≥32.5/frac≥0.63）
  → `pitch_eaten_mean_diff=8.0`/`pitch_eaten_changed_frac=0.15`。方向安全：歸位冪等、誤判
  被吃重做無害（與旋轉「寧漏判勿誤重送」取捨相反，故必須分家）。被吃的下一次拖曳實測常成功
  → 門檻判準後重試即自然救回。回歸：`tests/test_pitch_fixtures.py`＋`tests/fixtures/pitch/`。
  **R 視窗必須由 HUD 執行緒建（`sampler.SamplerPanel` Toplevel，2026-07-10）**：主執行緒有 HUD 的 Tk
  mainloop 時，背景執行緒開第二個 `tk.Tk()` 的 OS 視窗**永遠不會出現**（執行緒活著、mainloop 有跑、
  EnumWindows 列不到——實機驗證）。熱鍵執行緒只翻 `_sampler_want` 旗標，HUD `_poll` 每 300ms
  `sync_sampler_ui` 建/銷視窗；`hud_enabled=False` 才走舊執行緒版 `SamplerWindow`。
  **Tk widget 文字絕不可含 astral emoji（>U+FFFF：📸🔔🤖 等）**：這台 Tcl/Tk 8.6 會讓整個事件迴圈
  **無聲卡死**（無例外；二分實驗定位 2026-07-10）。HUD label 前有 `status_hud._bmp_safe` 防線，
  但源頭（按鈕文字/`last_action`）也別放；● ⚠ ▲ ▼ ◉ 是 BMP 安全。log/Discord 不受限。
- **重置自動回礦（REENTRY，2026-07-08）**：設計全文 `docs/superpowers/specs/2026-07-08-mine-reentry-design.md`。
  `auto_reenter` 預設 **False**（關＝RESET_WAIT 等人工＝舊行為；且 `assets/surface/` 無面板模板時視同關閉）。
  流程＝按「回到地表」→ 俯仰歸位（拖到夾限飽和→回拉固定量）→ 八方位掃面板（`best_template_match_scored`）
  → 右鍵 click-to-move 走近 → RapidOCR 文字框（`ocr.read_text_boxes`）點目標層按鈕 → 幀差+礦內亮度驗證。
  **寧漏勿誤**：面板分數低於門檻/按鈕文字對 target 沒有嚴格贏過 decoy → 不點、reroll（再按回到地表換重生點）；
  reroll 用盡（`reentry_max_attempts`）→ NEEDS_HUMAN＝今日現狀。決策純函式在 `reentry.py`（有單元測試），
  I/O 在 `Bot._tick_reentry`；座標/門檻全在 config `reentry_*`，實機校準（R 鍵取樣＋`calibrate_surface`）完成前勿開。

## 實機排錯（怎麼看到畫面）
- 截圖：`python -c "import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2); import cv2; from miningbot.capture import grab; cv2.imwrite('logs/x.png', grab())"` → 再 Read `logs/x.png`。
- 也可用 computer-use（先 `request_access` Roblox）截圖/觀察；驅動遊戲時**只用遊戲按鍵**（1–5、`,`/`.`、W、左右鍵），**絕不要按 Esc**（會開選單）。
- log 分檔（`diagnostics.setup_logging` 子 logger，propagate=False 隔離）：
  `miningbot.log`（主敘事：啟動/狀態/里程碑/alert）、`heartbeat.log`（心跳+audio+RMS）、
  `actions.log`（boost/D4 重複動作）、`harvest.log`（sweep/D3 細節）、`discord.log`（通知送出+命令執行）；
  另有 `events.log`（結構化 TSV）、`snapshots/`（截圖+chill WAV）；`config.log_level="DEBUG"` 看每幀細節。
  **快照非同步（2026-06-29）**：`_snapshot`/`_snapshot_crop` 只算路徑+丟佇列即時回傳，PNG 編碼+寫檔在背景執行緒（`_snapshot_worker`），避免 aim→D3 銜接被全幀 imwrite（~50-200ms）卡住。`snapshots/` 依 label 自動分流子夾（`diagnostics.snapshot_subdir`：trackers/review/events/trace/audio）。

## 工作慣例
- 純邏輯改動走 TDD（先寫失敗測試）。
- 在預設分支先開 feature 分支再 commit；commit 訊息結尾加 `Co-Authored-By: Claude ...`。
- **寫 code 交給 opencode subagent（使用者要求 2026-07-09，首例＝玩家列表前置檢查 0c7b779）**：
  程式實作預設委派 `opencode run`（模型 GLM 5.2，**無視覺能力**）；Claude 負責視覺與驗證。
  **⚠ 這條常被漏用（使用者實測 2026-07-11：Opus session 有時直接自己寫 code）——只要是
  「程式實作」（新功能、bug 修、重構、跨檔改動）一律走 opencode，不因「改動小」自己動手；
  例外只有：資產/文件/memory、一行 config 調參、以及「opencode 跑完後對同檔的小幅收尾補丁」
  （併發改同檔會衝突，等它結束再補）。** 分工：
  1. **Claude（有視覺）先做**：實機/歷史截圖量測座標、裁 fixtures、用真實引擎驗證偵測配方
     （哪個 OCR/前處理可靠要「實測過」不是猜）、抓座標陷阱（如 Roblox 內建截圖＝client area
     1920×1051，實機 grab＝1080，差 ~30px）。
  2. **寫自足規格書**（存 scratchpad）：列「先讀哪些檔案」（要模仿的樣板、config 格式、測試樣板）、
     「已驗證的視覺/OCR 事實照用勿重推」、明講 **GLM 不要嘗試讀任何圖片**、實作規格含安全細節
     （寧漏勿誤等）、TDD、完成標準＝`python -m pytest -q` 全綠、**不要 commit**（留人工審）。
  3. **背景執行（實例 2026-07-11，H040/H041 batch 驗證可用）**——用 Bash 工具（Git Bash 語法、
     `run_in_background: true`）：
     ```bash
     cd "/c/Users/puppy/OneDrive/Desktop/無聊的挖礦遊戲" && \
       opencode run "$(cat '/c/.../scratchpad/spec_xxx.md')" --title <任務名> 2>&1 | tail -40
     ```
     注意：路徑用 Git Bash 的 `/c/...` 形式；**輸出檔到結束前都是空的（buffer 到結束才吐），
     中途查進度用 `git status --short` 看它動了哪些檔**，不要因輸出空白誤判沒在跑；
     期間不要動它會改的檔（main.py/ocr.py/tests），文件/assets/memory 可並行。
  4. **Claude 事後驗證**：親自審 diff、獨立重跑新測試（含把修復暫時 revert 的紅燈驗證）、
     可行就做實機端到端驗證，全過才 commit。

## 延伸文件（不在此重複）
- **實機事故錄（H 系列完整敘事）：`docs/incidents.md`**——症狀/根因/對策/fixture/commit，改門檻前必讀
- 遊戲機制與道具：`docs/game-mechanics.md`
- 設計與計畫：`docs/superpowers/specs/`、`docs/superpowers/plans/`
- 接手微調指引：`docs/HANDOFF.md`
- R 鍵手動取樣用法（含回礦校準取樣流程）：`docs/manual-sampling.md`
