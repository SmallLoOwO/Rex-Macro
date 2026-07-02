# CLAUDE.md — Roblox REX 挖礦自動化

Windows 專用 Python 機器人，掛機玩 Roblox 遊戲「REX」（rex-3 wiki）：自動挖礦、用道具、聽到 chill 音效時採集稀有礦、礦坑重置時停下等人工。

## 指令
- 測試：`python -m pytest -q`（純邏輯 TDD，不需遊戲；改完必須綠）
- 啟動：`python -m miningbot.main`（Roblox 要先開好）
- 轉 chill 音檔：`python -m miningbot.convert_audio "chill.mp3"` → `assets/chill_reference.wav`
- 下載階級標記模板：`python -m miningbot.fetch_trackers`（→ `assets/markers/`）
- 擷取事件模板：`python -m miningbot.capture_template boost`
- 校準偵測區：`python -m miningbot.calibrate`

## 架構（狀態機）
主迴圈每 ~50ms 擷取一幀，純函式決定動作。狀態：`MINING / HARVESTING / NEEDS_HUMAN / RESET_WAIT`。
- **I/O 薄封裝**：`capture`(mss 截圖)、`audio`(喇叭 loopback + 交叉相關)、`vision`(OpenCV)、`ocr`(Tesseract)、`input_control`(pydirectinput)
- **純邏輯（有單元測試）**：`states`(轉換)、`geometry`(瞄準)、`miner`(事件分派)、`harvester`(採集步驟)、`events`
- `main.Bot` 組裝主迴圈；`status_hud` 置頂狀態窗；**`config.DEFAULT` 集中所有座標/門檻/熱鍵**。

## 硬規則 / 重要前提（多為實機踩過的坑）
- **Roblox 要「最大化填滿螢幕」**：視覺座標照 1920×1080 校準。`_focus_roblox` 用 **SW_MAXIMIZE**，
  **絕不可用 SW_RESTORE**（會把全螢幕縮成小視窗、座標全錯）。音訊不受畫面影響。
- **啟動先設 DPI-aware**（`main._set_dpi_aware`）：否則 `mss` 第一次截圖才把行程切 DPI-aware，
  害 `GetWindowRect`/輸入座標在截圖前後不一致（視窗跑位偵測誤判 resized）。
- **道具數字鍵會 toggle 裝備**：對已拿著的工具再按一次該數字鍵 = **收起來**。所以 init 只在
  槽位像素顯示「沒拿鎬子」時才按 D1（見 `miner._ensure_pickaxe`）；D5/D4 用完按 D1 是從別的工具切回，OK。
- **轉視角＝ `,` / `.`（轉 45°，可數、可回歸）**；`pydirectinput.moveRel` 單獨用**不會**轉視角，
  細部瞄準要 **按住右鍵**拖曳（`input_control.aim_move`）。但右鍵難精準，策略以 `,`/`.` 為主。
- **稀有礦採集流程（HARVESTING 狀態）**：
  1. `harvester.prepare_scan()` — 停止移動、置中鏡頭（裝備位置穩定）
  2. 置中後截 `_pre_scan_ref`（reference）— 排除「掃描前就存在的裝備/礦石假陽性」
  3. `harvester.execute_scan()` — 裝備 D2 + 點擊觸發掃描（等 1.5s）
  4. **全 8 方位掃描（`Bot._sweep_for_tracker`）**：rotate_right×7，每方位雙幀穩定確認（0.08s 間隔，誤差<8px 才接受），記錄有追蹤框的方位，選最佳後 rotate_left 旋回該方位。
     **早停（2026-06-29）**：某方位雙幀穩定且 `edge ≥ tracker_shape_early_exit=0.60`（遠高於裝備上限 0.26，實測真框 0.54-1.00）→ 人已在該方位，直接確定、免掃完剩餘方位也免轉回 verify（`find_tracker(with_score=True)` 外露 edge 分數）。分數不夠高者仍收集 → 掃完走 candidates[0]+verify（保留「不確定就繼續掃」）。
  5. D3 射擊：先按 2（切離 D3）→ 等 0.15s → 按 3 → 等 0.3s → hold click 0.4s → 等 0.5s 在追蹤框座標
  6. **確認（`harvester.decide_harvest_result(gone, confirmed)`，2026-06-29 改用「排除低稀有度」反轉策略）**：成功**只認聊天新增的稀有礦**（confirmed），不再用 `gone`。
     - `confirmed=True` → **SUCCESS**（不論框在不在）。`confirmed` = 聊天「`has found X`」裡 **X 不在低稀有度排除清單** (`game_data.common_ore_names()`) 的筆數**增加**，或**底部新出現一行稀有礦**（`ocr.count_rare_found` / `has_new_rare_found_last_line`）。特殊階（ionized/spectral）另由 `special_keywords` 字樣確認、也算 confirmed。
     - **聊天 OCR 走多前處理融合（2026-07-03 H014 假陰性對策）**：`_read_chat` 用 `ocr.read_text_multi`（`CHAT_PREPROCESSES`＝min_channel/gray/dark_mask 各 OCR 一次，tesserocr 下每 pass ~0.4s、只在 D3 前後跑），`ocr.any_new_rare_found` **逐 pass 自洽差分**（不同 pass 噪音不同、不可交叉比），任一 pass 確認即成功。**單一前處理必有背景盲區**：min_channel 為暗背景校準、在亮粉糖果礦壁上彩色行全滅（H014：真採到的底部新行 `has found Diamorite` 沒讀到 → 假陰性誤交人工）；dark_mask（文字深色外框 vs 亮背景）反之在近全黑礦坑失效。**改前處理必跑回歸集 `tests/test_ocr_fixtures.py`**（實機裁圖×三種背景），新背景樣本從 `logs/snapshots/trace` 補進 `tests/fixtures/chat/`。
     - 框消失但無新稀有礦（gone & ~confirmed）→ **RESWEEP**：礦被**掃描到期**拿走，原地再射也射不到 → 立即重掃（不浪費 attempts）。
     - 框還在且未命中（~gone & ~confirmed）→ **RETRY**：原地重試 D3。
     - **為何不再用 `gone` 當成功（踩坑根因）**：「框消失 ≠ 我們採到」。真追蹤框會因 **D2 掃描到期（框自己淡掉）**而消失，舊邏輯 `gone or confirmed` 把這誤報成功（2026-06-29 trace 20260629_022126：真框疊在角色額頭 D3 打不到、掃描到期框自己淡掉 → gone=True 假成功，稀有礦 5→5 根本沒變）。
     - **階級/聊天/聲音機制（使用者確認 2026-06-29，關鍵前提）**：**只有 Surreal + Mythic 兩階會被動出現在聊天框**；Exotic 以上不被動進聊天，改用 **chill 聲音**觸發採集。但**用 D3 親手採到高階礦時，那一筆會進聊天** → 不在排除清單（清單只含 Surreal/Mythic）→ 被算成稀有 → confirmed。故排除清單天生完整（會進聊天的就這兩階），是它有效的關鍵。清單的角色＝**排除器**：擋掉低階誤觸發，剩下不在清單的 has found ＝真正採到的高階。
     - **為何「排除低稀有度」而非「列舉高稀有度」**：聊天「`<小名> has found X`」混了低階礦（Surreal/Mythic）和 D3 採到的高階；單人作業 `小名` 就是自己、污染源同名 → 名字過濾無解。高階礦太多列不完，**低階反而有限且封閉**（只有兩階會進聊天）→ 列舉低階當排除清單（`World.common_ores`）。代價：漏列會進聊天的低階礦、或 OCR 把礦名讀錯 → 偶發假成功（用 `startswith` 容忍尾端雜訊、偏保守降低誤判）。
     - **為何比「數量」不是「存不存在」+ 對抗捲動**：上一輪留下的稀有礦會同名出現 2-3 次；且**舊訊息會從頂部刷掉 → count 可能 2→1 假負**。故主信號是 `has_new_rare_found_last_line`（只看底部最新行，捲動只影響頂部），count 增加為輔。
     - **Z 雷達不產生 has found、且未實作 → 與採集確認無關**。
     - **未來方向（使用者提到）**：可能關閉「部分高階礦的聲音」，讓「只有出聲的高階」才觸發採集＝天然過濾想採的礦；屆時觸發判斷會更依賴 chill 音訊的**前後對比**（`ChillListener`）。
  7. 成功後 `harvester.restore_view(net_rotations)` 轉回原視角 → `miner.init_mining_sequence()`（與 Q 恢復/啟動相同的完整序列：清鍵→視角→置中→確認鎬子→W+左鍵）
  - **超時兩階段**：sweep 階段 `sweep_timeout_s=30s`；sweep 完成後重置計時器，D3 階段 `harvest_verify_timeout_s=15s`。
  - **重試**：RETRY 連 `max_harvest_attempts=5` 次未命中 → 重掃（`_reharvest_sweep`）；RESWEEP 立即重掃；sweep **環繞一次**找不到 → **先 `restore_view` 轉回原視角** → NEEDS_HUMAN（2026-06-29：偵測已準，移除二次重掃；放棄路徑統一走 `_harvest_giveup` 先轉回視角，讓畫面回正便於人工判斷「礦已被挖走」的好假警報）。
  - **聊天裡的 `小名 has found` 全是自己**（單人作業、無其他玩家）：混了**普通鎬子挖的一般礦**（Lovelocket/Bandeau 等在左側 NORMAL 面板）和 D3 稀有礦——故不能用「出現 has found」判斷成功，要**排除低稀有度礦後看是否有新稀有礦**（見步驟 6）。
  - **遊戲資料分世界（`game_data.World`）**：REX 分 world，每世界各有 `events`（D4 事件）與 `common_ores`（低稀有度排除清單）。目前有 **Aesteria + Lucernia**（Lucernia 含 2026 春季四圖層 Amourite/Shamrock/Brittlestone/Harmonine 與洞穴限定，wiki Lucernia 頁為資料源；洞穴礦聊天行帶 `(Xxx Cave)` 尾註、`startswith` 容忍會正確排除）；新增世界＝建一個 `World` 加進 `WORLDS`。`EVENTS` 是模組層相容別名＝Aesteria 事件。**排除清單只收 Surreal/Mythic**——Exotic 以上是 D3 目標，列進去＝重演 H014 假陰性（真採到 Diamorite 卻被排除）。
  - **世界偵測（`game_data.detect_world`/`update_world_from_event`，2026-06-29）**：遊戲不直接顯示在哪個世界，靠**「看到的事件屬於哪個世界」**推斷（事件分世界）。`main._maybe_detect_world` 搭既有事件 OCR 便車（`_check_reset` 每 2s + D4 路徑）呼叫；某事件唯一命中一個世界 → `set_world` 鎖定（跨世界共用事件＝無法區分→不鎖）。**世界未確定時 `common_ore_names()` 用「所有世界聯集」當保守排除清單**；鎖定後收斂成該世界的，更準（同名礦在不同世界階級可能不同，用錯世界會把高階採集目標誤排除→漏判成功）。`match_event`/`fuzzy_match_ore` 一律搜全世界聯集（讀到事件時可能還沒鎖世界）。

- **追蹤框偵測 `vision.find_tracker`（2026-06-28 改混合方案）**：HSV 快速定位 + 實機裁圖外框形狀確認。
  1. **HSV 候選**：各色系範圍獨立 mask（不合併）→ reference_bgr 差分（同色 fill>0.15 排除掃描前就有的）→ **色相無關** colored 確認（`(S>90)&(V>90)`，門檻 `colored_frac>0.40`；**不可再加 `(H<35)|(H>95)`**——那會漏抓黃綠中心礦如 Ionized，是 very_rare.png 踩過的根因）。**ring_score 環形結構/`frame_fill` 只當軟訊號（`ring_ok`），混合模式不硬拒**（見下方黑心/綠實心中心兩坑）。
     - **colored 必須量「整個 bbox」、專注外框，不可只看中心（2026-06-29 黑心框踩坑）**：追蹤框中心顏色每次會變（不同礦色/粉紅/甚至**純黑空心** `BGR[0,0,0]`），中心非不變特徵。舊版量「中心 2/3 ROI 的彩色像素」，遇黑心綠框（`black_center_scene.png`，中心 colored=0.00）→ 被當暗色 UI 面板拒掉 → 整圖回 None、沒進 D3、稀有沒採到（其實形狀 edge=0.64 認得它，只是 HSV 那關太早殺掉）。改量整個 bbox 的彩色佔比：真框厚實外框佔比高（黑心 0.51-0.62、彩心 0.7-1.0），細框暗 UI 面板低（合成 0.33、實機 ≈0.16）→ 門檻 `colored_frac>0.40` 區隔，形狀確認再精篩。
     - **ring_score/`frame_fill` 不可在形狀確認前硬拒（2026-07-02 綠實心中心 H13 踩坑）**：追蹤框中心可能是**亮礦色實心方塊**（`green_center_scene.png`，綠框+黑環+綠實心中心，26px 小框綠 mask 同吃外框+中心 → `fill≈1.00`、`ring≈0.00`）。舊版 `ring_score<0.15` 直接 `continue`（且 `accept` 要求 `frame_fill<0.85`）→ 在形狀確認前就殺掉真框 → sweep 八方全 None、放棄交人工（實測 H001/H002/H004/H006-H009/H013 都栽在此，9 張手動截圖裡 4 張是這種「ring 誤殺但 edge≥0.45」的真框）。**與黑心框同類**（「中心非不變特徵」的坑）：改由形狀 edge 當精準仲裁——`edge≥threshold` 一律 confirmed（不看 `ring_ok`，救回實心/彩心真框）；`ring_ok` 只保留給 (a) 純 HSV 後備（無形狀模板時唯一結構過濾）、(b) borderline survivor 防線（`hard_floor≤edge<threshold` 才需環形，擋非環形假陽性翻盤）。
  2. **形狀確認（`shape_templates`）**：在每個 HSV 候選周圍小 ROI 跑「實機裁圖外框」邊緣比對（`best_outline_score`≥`cfg.tracker_shape_threshold`＝**0.42**），拒「有色但非追蹤框形狀」的假陽性（如角色裝備誤射）。只在小 ROI 跑（全幀模板比對 5~23s/幀太慢）。**門檻 0.45→0.42（2026-07-02）**：實機真框 edge≥0.43、裝備假陽性≤0.30，中間有 gap → 0.42 收得回「被角色帽子擋到角」的近失綠框（173709，edge 0.43、實心中心非 survivor），而 `hard_floor` 0.30 + `colored_frac>0.40` 仍擋裝備。**追蹤框可能疊在角色身上**（頭頂/胸前），別因「在角色上」就當非框（使用者確認）。
  3. **雙幀穩定**（`_tick_harvest`/sweep 內）：連續兩幀誤差 < 8px 才採用。
  - **模板必須用「實機裁圖」不是 wiki 圖**：wiki 是透明 PNG 只有外框（alpha），但向量 icon 邊緣在合理尺度配不到遊戲內渲染框（實測全 miss）；實機裁圖 edge≈0.91 且**一張可跨階通用**（顏色無關，色相位移仍命中）。形狀確認集 = `assets/markers` 內無 alpha 的裁圖（自動篩，wiki 排除）。新階礦從 log snapshots 裁實機框補進去即可。

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
  **採集成功後恢復挖 礦用 `miner.init_mining_sequence()`**（與 Q 暫停恢復、啟動完全相同的完整序列）——舊的精簡 `resume_mining()` 常漏按住 W（採集後鍵盤殘留狀態讓 `key_down("w")` 失效），已移除統一走 init。
- **chill 偵測靠喇叭 loopback**（`audio.LoopbackCapture` 餵 `ChillListener`）；預設只靠音訊
  （`chill_require_ocr=False`）。**真實 chill 約 0.4**（非參考檔的 1.0），門檻設 ~0.30。
  **match_score 很重（~110ms）**，每 chunk（85ms）都算會讓音訊執行緒積壓→6s 延遲。
  解法：score 每 `audio_score_interval_s`（0.3s）算一次，緩衝每 chunk 照常更新。延遲 ~1s。
- **D4 事件保留**：USE_D4 前讀頂部事件列 OCR → `game_data.match_event` → `is_kept` →
  在 keep 清單 → `use_activity_keep()`（左鍵確認）；否則 `use_activity()`（右鍵刷新）。
  keep 清單透過 Discord 命令控制（`!keep`/`!list`/`!clear`），背景執行緒每 10s 輪詢。
- **所有座標/門檻改 `miningbot/config.py`**；**輸入保留延遲**（太快會被吃掉，放開挖礦左鍵後要 `settle`）。
- **OCR 引擎＝tesserocr（in-process）優先、pytesseract 後備（`ocr.read_text`）**：pytesseract 每次
  `image_to_string` 都 spawn 一個 `tesseract.exe` 子行程 + 重載模型＝**與圖無關的 ~2.5s 固定開銷**
  （實測連 20×120 空白圖也要 2.5s）。這 OCR 在 MINING 每 2s 跑一次（`_check_reset` 讀頂部列找重置字樣），
  **同步跑會卡住主迴圈 ~2.5s → 每幀的 boost 偵測被餓死 → 「boost 常常是空的」（D5 補太慢的真因）**。
  改用 tesserocr（同一顆 Tesseract 引擎/模型、**準度不變**，只是引擎常駐免重複 spawn）：banner OCR 3062→~400ms。
  `PyTessBaseAPI` 非執行緒安全 → 比照 `capture` 的 mss 用 `threading.local` 每執行緒各持一個持久 API；
  未裝/初始化失敗自動退回 pytesseract（`PREFER_TESSEROCR=False` 可強制退回）。安裝見 `requirements.txt` 註解。
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
  - **有框採不到**（D3 階段超時，`face_tracker=True`）：**不轉回**、保持面對追蹤框，主圖給追蹤框裁圖
    （`_save_tracker_screenshot`），人工一眼看到框可手動採；不附 rotation_hint（已正對著框）。
  - **沒找到框 / 掃描超時 / 採到但聚焦失敗**（`face_tracker=False`）：**轉回原視角** + 附 **4 張左側前後對比裁圖**
    （`chat_review_region`×前後、`backpack_review_region`×前後）。**Discord 分兩則發送：先聊天框（前/後），再背包（前/後）**
    （`harvester.giveup_send_groups` 依 region 分組 → meta `image_groups` → `notify.format_group_messages`／sink 各發一則；
    第一則帶完整警告文字＋群標題，第二則只帶群標題）。舊版一則附 4 圖（2×2）縮圖太小，拆兩則各 2 圖更清楚（2026-07-02 需求）。
    before＝該輪 `_pre_scan_ref`、after＝轉回後現況；左側 UI 是螢幕覆蓋層、不隨鏡頭轉動 → 前後同框可直接比對「礦是否已被採走」
    （新 has-found 行 / 背包數量增加＝已採到）。舊版單一 `human_review_region` 窄高長條對 Discord 縮圖不友善，拆兩區更貼縮圖比例。
- 熱鍵用**全域輪詢**（`Bot._check_hotkeys`，GetAsyncKeyState）：**Ctrl+Q** 緊急停、**Q** 暫停/繼續、
  **F12** 結束。焦點在遊戲也有效（`keyboard` 庫在遊戲前景時收不到，已棄用）。

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

## 延伸文件（不在此重複）
- 遊戲機制與道具：`docs/game-mechanics.md`
- 設計與計畫：`docs/superpowers/specs/`、`docs/superpowers/plans/`
- 接手微調指引：`docs/HANDOFF.md`
