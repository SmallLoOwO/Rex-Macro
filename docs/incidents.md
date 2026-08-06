# 實機事故錄（H 系列）

每次實機採集事故的完整經過。`Hxxx` 是 harvest episode 編號（`logs/harvest.log`／snapshots 的採集輪次）。
CLAUDE.md 只保留「現行規則＋一句話根因＋(Hxxx 見本檔)」；**改規則前先來這裡讀完整脈絡**，
別因為看不懂某條門檻的來歷就動它——多半是實機用血換的。

fixture 位置慣例：
- `tests/fixtures/chat/hxxx_*.png` — 聊天裁圖回歸（進版控，`tests/test_ocr_fixtures.py` / `tests/test_ocr.py` 使用）
- `assets/*_scene.png` — 追蹤框全幀場景回歸（**本機檔、gitignore**，對應測試缺檔自動 skip）
- `assets/markers/*_tracker_real.png` — 實機裁的追蹤框外框模板（形狀確認集）

快速索引：

| 編號 | 日期 | 一句話 |
|---|---|---|
| 前置事故 | 06-27~29 | D3 toggle／黃綠中心漏抓／黑心框／掃描到期假成功／chill 單參考漏抓 |
| H001–H013 | 07-02 | 綠實心中心真框被 ring/fill 在形狀確認前硬拒 |
| H014 | 07-03 | 亮粉背景單一前處理讀不到聊天行→假陰性誤交人工 |
| H015 | 07-03 | D5 到期 FOV 收縮座標位移＋單幀驗證踩空窗 |
| H019 | 07-03 | FOV 位移把完好真框推進 margin 邊緣排除帶 |
| H020 | 07-03 | 行讀得到但 "has found" 被讀歪→精確匹配全滅 |
| H026 | 07-04 | boost 守門缺口＋重掃重拍 ref 把活框寫進排除基準 |
| H032 | 07-04 | 多行同窗口抵達＋捲動剛好補償 count→雙信號假陰性 |
| H033–H038 | 07-04 | RapidOCR 留用裁決；i/l 同形誤讀信心高 |
| H034 | 07-04 | 低分觸發 0.26 採到 Transcendent＝缺參考家族非誤觸 |
| H039 | 07-04 | 首例 Enigmatic 全鏈路成功；ionized 變體被動進聊天實錘 |
| 視角回歸 45° 斜角 | 07-05 | 旋轉鍵被吃→net_rotations 計數與實際角度脫鉤 |

---

## 前置事故（2026-06-27～2026-06-29，無 H 編號）

早期實機踩坑，對策已固化成 CLAUDE.md 硬規則，這裡留完整因果：

- **D3 toggle 連射必 miss（2026-06-27）**：數字鍵會 toggle——D3 已裝備時再按 3 ＝卸下 D3，retry 的第二發必定 miss。
  對策＝每次發射前先按 2 切離 D3 再按 3（無論手上拿什麼都安全）。
- **黃綠中心礦漏抓（2026-06-28）**：`find_tracker` 的 colored 確認寫死 `(S>90)&(V>90)&((H<35)|(H>95))`，
  排除 H35-95 黃綠帶→黃綠中心礦（如 Ionized）colored=0 漏抓。實機 `assets/very_rare.png`（紅礦坑、藍框+黃綠中心
  Transcendent）踩到：HSV 有找到 (1231,644) 但被 accept 拒。對策＝colored 改**色相無關** `(S>90)&(V>90)`。
- **wiki 模板全 miss（2026-06-28）**：wiki 是透明 PNG 只有外框（alpha），向量 icon 邊緣在合理尺度配不到
  遊戲內渲染框（只在 scale 0.2 噪點假命中）；實機裁圖 edge≈0.91 且一張跨階通用（exotic 裁圖命中藍階框 0.64，
  顏色無關、色相位移仍命中）。fixture：`assets/markers/*_tracker_real.png`。
- **chill 單參考漏抓（2026-06-28，commit 92cceaa）**：錄到 5 個「清楚」的 chill 對單一參考檔只分到
  0.87/0.43/0.15/0.22/0.20——交叉比對證實至少 3 種不同 chill 音效，單一參考代表性不足＝「有時不觸發」。
  對策＝多參考集取最高分（`audio.match_score_multi`）＋decimate 加速。後續：2026-06-29 分析 12 個 confirmed
  實錄收斂出 4 個家族（A~D），補 3 參考後 12/12 全 ≥0.73。
- **黑心框被當暗色 UI 面板（2026-06-29）**：追蹤框中心可能是**純黑空心**（`BGR[0,0,0]`）；舊版 colored 只量
  「中心 2/3 ROI」→黑心綠框 colored=0.00 被拒、整圖回 None、稀有沒採到（其實形狀 edge=0.64 認得它）。
  對策＝colored 量**整個 bbox**（真框厚實外框佔比高：黑心 0.51-0.62、彩心 0.7-1.0；細框暗 UI 面板 0.16-0.33）
  →門檻 `colored_frac>0.40`。教訓（與 H001–H013 同類）：**中心特徵全非不變量**。
  fixture：`assets/black_center_scene.png`。
- **掃描到期假成功（2026-06-29，trace 20260629_022126，commit bc7a622）**：真框疊在角色額頭 D3 打不到、
  D2 掃描到期框自己淡掉→`gone=True`，舊邏輯 `gone or confirmed` 誤報成功（稀有礦 5→5 根本沒變）。
  對策＝成功只認 confirmed（聊天新增稀有行），`gone & ~confirmed`→RESWEEP。
- **borderline 裝備誤射（2026-06-29，commit c3ed7c9）**：sweep_confirmed 裁圖中 (990,665) 是角色裝備
  誤射座標，偶發假確認→borderline survivor 守門。fixture：`assets/false_positive_equipment.png`、
  `assets/exquisite_scene.png`（同批補的 exquisite 實機模板）。

## H001–H013（2026-07-02）：綠實心中心被 ring/fill 硬拒

- **症狀**：使用者 9 張手動截圖畫面明明有框，sweep 八方全 None、放棄交人工（H001/H002/H004/H006–H009/H013
  都栽在此）；使用者以為礦被挖走，其實是漏抓。
- **一句話根因**：追蹤框中心是**亮礦色實心方塊**時，ring/fill 關卡在形狀確認之前就把真框殺掉。
- **細節**：H013 綠框+黑環+綠實心中心、26px 小框→綠 mask 同吃外框+中心→`frame_fill≈1.00`、`ring_score≈0.00`，
  被 `ring_score<0.15`（rej not_ring）＋ accept 要求 `frame_fill<0.85` 硬拒；但外框 edge≈0.64（≫0.45）本應 confirmed。
  9 張截圖裡 4 張是這種「ring 誤殺但 edge≥0.45」的真框。
- **對策**：混合模式下 ring/fill 降為軟訊號 `ring_ok`；`edge≥threshold` 一律 confirmed（不看 ring_ok）；
  ring_ok 只留給 (a) 純 HSV 後備（無形狀模板時唯一結構過濾）、(b) borderline survivor 防線。
- **教訓**：「中心特徵」（顏色／黑心／實心）全都非不變量——凡靠中心的 HSV 關卡遲早誤殺真框，一律交形狀仲裁。
- **fixture**：`assets/green_center_scene.png`（gitignore、缺檔 skip）
- **commit**：740587f（ring/fill 改仲裁）；a396ab8（同日 threshold 0.45→0.42，收「被角色帽子擋到角」的
  近失綠框 173709，edge 0.43；實機真框 edge≥0.43、裝備假陽性≤0.30 中間有 gap）

## H014（2026-07-03）：亮粉背景 OCR 假陰性誤交人工

- **症狀**：糖果礦區（亮粉礦壁）真採到 Diamorite，confirmed=False + gone=True→RESWEEP 全空（已採走掃不到）
  →誤交人工。chat_before 淡出全空（rare_before=0）也讓 count 差分失去基準。
- **一句話根因**：單一 OCR 前處理必有背景盲區——min_channel 在亮粉背景讀不到彩色聊天行。
- **細節（三坑疊加）**：
  1. min_channel 前處理為暗背景校準，在亮粉紅礦壁上紫/橘/暗紅字全滅只剩白黑字→真正採到的底部新行
     `has found Diamorite` 沒讀到。離線實驗：**暗色外框遮罩**（`V<120` 反相，聊天字有深色 outline、背景亮）
     能把全部行讀回。
  2. OCR 讀到的「最後一行」變成 `Jollycane (Candied Cave)`，Jollycane 在 Lucernia Mythic 排除清單
     →`startswith` 連括號 cave 變體一起排除→last-line 信號 False（此為正確行為：洞穴礦聊天行帶
     `(Xxx Cave)` 尾註＝被動 find 的位置註記，非變體階級）。
  3. 活動礦區（情人節主題 Dulcinette/Diamantine/Diamorite/Ladyfeeb…，合成 Amourite）整套礦名不在
     game_data→排除清單失真，會進聊天的低階漏列＝假成功風險。
- **對策**：(1) `ocr.read_text_multi`＝min_channel/gray/dark_mask 三 pass 融合，`any_new_rare_found`
  **逐 pass 自洽差分**（不同 pass 噪音不同、不可交叉比），任一 pass 確認即成功；(2) game_data Lucernia 補
  2026 春季四圖層＋洞穴限定共 26 個 Surreal/Mythic（wiki MediaWiki API 抓；fandom 網頁 403、
  `curl -A Mozilla` 打 `api.php?action=parse` 可通）。離線重演 H014：confirmed False→True。
- **同場加映（wiki 機制事實修正）**：所有 find 都進 local chat（Exotic+ 也是），只是 Exotic+ 被動挖到
  ≤1/1M→聊天高階行實務＝D3 採的；Rare/Master 的 Spectral 變體也會被動進聊天→剝 `ocr.VARIANT_PREFIXES`
  再查排除清單（commit 5ac9514）；三態分類＋未知礦名告警（54d9425）；`fetch_ores` wiki 同步＋排除清單
  diff（47e444b，首跑抓到 'Cublexrtiye'→'Candensium' 誤植）。**排除清單只收 Surreal/Mythic、Exotic 以上
  絕不可列**（列進去＝重演本事故的鏡像：真採到 Diamorite 卻被排除；有測試鎖住）。
- **fixture**：`tests/fixtures/chat/h014_before_faded_pink.png`、`h014_after_pink_bg.png`；
  回歸集 `tests/test_ocr_fixtures.py`（實機裁圖×三背景，改前處理必跑）
- **commit**：6bdfae4（OCR 三 pass 融合）、29f0836（Lucernia 資料）

## H015（2026-07-03）：D5 FOV 收縮＋驗證時序（四個實機事實）

- **症狀**：sweep 找到框、第一槍點空牆；其實採到卻 RETRY→超時誤交人工。
- **一句話根因**：D5 boost 到期會收縮 FOV、畫面所有座標整批位移；且框擊中後 2~10s 才消失、
  聊天成功行更晚到，單幀驗證必踩空窗。
- **細節（四個實機事實）**：
  1. **FOV 耦合**：buff 週期 ~60s（actions.log 每分鐘重上一次）、到期常落在採集中段；sweep 座標放久必失效，
     H015 第一槍 sweep 座標到點擊時已是不同牆面。「等 buff 消失再採」不划算：回 MINING 又會重上 D5，問題只是搬家。
  2. **聊天 3-pass OCR 滿版文字實測 ~3.3s/pass、共 ~10s**（空白圖 0.14s；舊註記 0.4s/pass 是小圖數字）
     →逐次開火前重讀 before 會讓開火座標幀齡 12s。
  3. **框是擊中後 2~10s 才消失、聊天成功行更晚到；聊天無新訊息 ~15s 整個淡出**（裁圖變純背景、count 假遞減），
     唯有新訊息會喚醒→click 後固定等 0.5s 抓單幀判生死必踩空窗。
  4. **timeout 要對齊真實嘗試成本**：一次 D3 嘗試 ~20s，舊 `harvest_verify_timeout_s=15s` 連一次都裝不下
     →RETRY 後 1s 即超時、5 次重試預算形同虛設。
- **對策**：開火前重抓當下幀 re-find 再點（找不到→立即重掃）；聊天基準 sweep 完成時取一次、跨嘗試共用；
  驗證改 8s 窗口輪詢（`decide_verify_poll`，confirmed 隨時早退）＋`vision.frames_differ` 省 OCR 閘；
  timeout 15s→45s；放棄兩路徑都附聊天/背包前後對比圖（框裁圖在框已消失時空無一物，人工無從判斷）。
- **fixture**：無專屬圖（對策是時序）；對比圖機制見 `_harvest_giveup`
- **commit**：16fae44

## H019（2026-07-03）：FOV 位移 × 邊緣排除帶

- **症狀**：sweep 看到框、轉回對齊後 verify 整幀 None→誤判「未找到」交人工；框其實完好在 (1862,418)、edge 0.57。
- **一句話根因**：轉回期間 D5 到期 FOV 收縮把框往外推 ~390px，撞進 `find_tracker` 的 `margin_frac=0.1`
  邊緣排除帶（in_area=False），margin 是唯一擋它的關卡。
- **細節**：同一顆框常橫跨相鄰 2~3 個 sweep 方位（45° 視野重疊）；舊版取「最先看到的方位」可離中心 500px+，
  邊緣餘裕先天不足。
- **對策**：`harvester.pick_sweep_candidate` 選 **x 最居中**候選（天然留邊緣餘裕）＋`decide_sweep_failure`
  sweep 失敗分流——全程沒看到→人工；**看到過但 verify 失敗→重掃一次**（上限 1 防循環）。
- **fixture**：`assets/edge_clipped_tracker_scene.png`（gitignore、缺檔 skip）＋ `tests/test_vision.py` 釘住
- **commit**：352ff1f

## H020（2026-07-03）：關鍵字被 OCR 讀歪＝multi-pass 也救不了

- **症狀**：亮粉背景，三 pass 精確關鍵字全滅→RESWEEP→重掃全空（礦已被自己採走）→誤交人工；
  giveup 前後對比圖兩張一模一樣、人工無從判斷。
- **一句話根因**：與 H014 不同層——**行讀得到、字讀歪**：dark_mask 把 `has found Valytium` 讀成
  `hee foumel velyiiuinm`，精確子字串 `"has found"` 對不上→count=0。
- **細節與對策**：
  1. **模糊 found 兜底**：`any_new_rare_found(..., rare_names=game_data.rare_ore_names())`——
     found-ish token（SequenceMatcher≥0.52、**非行首**（found 行前面必有玩家名；系統行 "friends can chat..."
     曾誤收）、**長度≥4**（OCR 黏字的 "un" 曾誤當））＋其後礦名對白名單 fuzzy ≥0.62 **且嚴格高於排除清單分數**。
     門檻由實資料兩側夾出：真值 founcl=0.727／foumel=0.545／velyiiuinm→Valytium=0.667；曾誤收
     friends=0.500／can chat→Luckant=0.600。平手判 common（biemnentine 對 Solemn Lamentine＝對
     Presentine＝0.667→拒），寧漏勿假成功。白名單檔缺→fuzzy 自動停用（降級回精確）。
  2. **窗口到期 final-check**：3-pass OCR 7~11s ≈ 8s 驗證窗口→窗口內只有一次 OCR 機會；且幀差閘可能在聊天
     「淡入中」就觸發 OCR 並更新 `_chat_last_crop`（讀到半透明文字必歪、之後像素不再變不重讀）→判
     RESWEEP/RETRY 前強制對最新幀再 OCR 一次（只在失敗路徑多花 ~10s）。
  3. **giveup 基準分離**：before 曾取 `_pre_scan_ref` 但 `_reharvest_sweep` 會重拍它——礦已採到才 RESWEEP 時
     重拍的是「採完後」畫面→兩張一樣。改 `_harvest_origin_ref` 只在進 HARVESTING 時取一次、giveup 專用。
  4. **verify 詳細 log**：poll 每輪記 chat 像素差值 vs 門檻（DEBUG）、每次 OCR 記耗時/逐 pass 稀有計數/
     末行原文、fuzzy 收/拒診斷附雙邊分數、收場逐 pass OCR 全文落盤 `trace/*_chat_ocr_<verdict>.txt`
     （事後排錯不必重跑 OCR、引擎一改也不可重現）。
- **fixture**：`tests/fixtures/chat/h020_before_faded_pink.png`、`h020_after_pink_bg.png`
  （鎖「精確=False、fuzzy=True」）
- **commit**：9e9a349（對策）、89bc94b（docs）；branch feature/h020-ocr-fuzzy-verify

## H026（2026-07-04）：FOV 坑的完整解＋boost 守門＋重掃自我致盲

- **症狀**：sweep 早停確認後、聊天基準 OCR 卡 12s 期間 D5 到期→開火前重定位正確拒發（H015 防線有效），
  但接著重掃全空→誤交人工。
- **一句話根因**：兩個獨立坑——(1) 採集途中 D5 到期沒人補（MINING 的到期即補在 HARVESTING 不跑）；
  (2) `_reharvest_sweep` 重拍 reference 把「活框」寫進排除基準→自我致盲。
- **細節（四項）**：
  1. **FOV 收縮實測＝以畫面中心為錨的 ~2.6x 縮放**（兩軸一致量出：(1084,744)→(1288,1049)），離中心越遠推越遠。
     D5 到期間隔實測 50~70s（actions.log），非使用者記的 25~37.5s。
  2. **重掃自我致盲（確定性 bug）**：重拍 `_pre_scan_ref` 時活框已在畫面上→框進排除基準→每方位
     `rej(preexist)`（dir=0 實錄 ref_fill=0.57＝框自己）。改沿用進場「框出現前」的 ref
     （靜態 UI 不隨視角/FOV 變、排除效果不減）。
  3. **底緣框 8 方位都救不回**：yaw 旋轉只改 x 不改 y→`margin_frac=0.1` 底部帶（y>972）永遠擋住。
     改 `cfg.tracker_margin_frac=0.02`（vision 函式預設仍 0.10，實戰由 main 傳入），救回 H019/H026
     兩顆邊緣真框、全 fixture 無新假陽性。
  4. **boost 守門 `_harvest_boost_guard`**：在 tick 頂/sweep 每方位/輪詢每輪/進場 ref 前跑便宜瓶子檢查
     （單尺度 edge-match ~56ms、0.2s 節流），一消失即 `miner.use_boost_harvest()`（不切 D1、不握左鍵）
     ＋等 `boost_fov_settle_s=1.5s` FOV 展開＋重抓幀。**buff 在時按 D5 無效、不能提早續時**（2026-07-02 實測）
     →「快到期先補」不可行，只能到期即補（使用者「補 D5 再掃」提案的可行落地形）。
  5. **基準 OCR 移到開火後**：sweep 完成只截裁圖（瞬間）、先開火，~10s OCR 挪到開火後蓋掉等命中的死時間
     （驗證窗口從 OCR 完成起算）→確認→開火從 ~13s 縮到 ~1.5s（H026 就是這 12s 空窗內 D5 到期）。
- **fixture**：`assets/bottom_edge_tracker_scene.png`（gitignore、缺檔 skip）
- **commit**：062b897

## H032（2026-07-04）：「新稀有行必在底部」假設破功＋雙信號同滅

- **症狀**：D3 第一發命中、聊天新增 `has found Essentlum`（Essentium），仍 RESWEEP 全空（礦已採走）誤交人工。
  使用者看到的「用 D5 重新對準」＝驗證輪詢中 boost 守門正常到期補 D5（14:12:16，非 bug）＋RESWEEP 轉頭。
- **一句話根因**：多行同窗口抵達——一般礦行 `Halcylite (Lucky Cave)` 排在成功行後面→底行信號滅；
  同時頂部剛好刷掉一行舊稀有（Saerylium）→count 3→3 不增也滅→雙信號假陰性。
- **對策**：`ocr.new_chat_tail_lines` 把 before 底行對齊到 after 的錨點（多候選取「向上連續吻合最長」、
  錨行容忍 OCR 噪音 `FUZZY_STALE_LINE_RATIO`≥0.85），錨點之後**全部**＝新增行、任一行稀有即 confirmed
  （`has_new_rare_found_tail`，模糊路徑同步）；對不到錨點回空保守不假陽性。實錄重放（trace txt）
  confirmed False→True、count 3→3 變正確 2→2。
- **同批發現（變體行帶冠詞）**：實際聊天行是 `has found an ionized Diamantine`，`_strip_variant` 原不剝冠詞
  →`an ionized ...` 對不上排除清單→被動低階變體被當稀有/special（假成功風險、H032 rare count 虛胖 3）。
  現先剝 `an`/`a` 再剝變體前綴（`classify_found_ore` 共用一併修）。
- **延伸對策（Episode 帳本＋晚到確認，同日 branch feature/episode-chat-ledger）**：單一基準點對點差分
  守不住兩個時間軸破口——(a) RESWEEP 作廢重取基準：誤判失敗後成功行常在重掃期間才抵達、被吃進新基準
  →差分永遠看不見；(b) 失敗路徑（D2 重掃/D5 守門 settle/8 方位重掃）沒人看聊天：成功行抵達後被一般礦行
  推到**捲出裁圖**→之後任何 after 都不再出現、錨點對齊也救不了。修法：
  1. 聊天基準升 **episode 級**（進場截一次、RESWEEP 不作廢；開火前不可能有自己的成功行＝天生乾淨；
     OCR 仍延到開火後＝H026 不變）。
  2. `ocr.ChatLedger` 鏈式錨點帳本：每次 verify OCR 以「上一次讀取」為錨對齊（間隔短錨點不易捲丟）
     累積新增行、逐 pass 自洽；帳本累積出任一稀有 found 行即 confirmed、全 episode 有效。語意由領域事實
     撐住：單人＋Exotic+ 被動 ≤1/1M→episode 內新稀有行只可能來自自己的 D3。
  3. `main._late_chat_confirm` 在失敗路徑三決策點（pre-sweep/post-sweep/D3 超時交人工前）幀差閘＋OCR
     晚到確認，confirmed→`_harvest_success`（從 poll 路徑抽出共用；通知行＝差分抽取∪帳本稀有行）。
  4. 保守規則：錨點對不到→不追加不推進；上次讀取空（淡出）→只起鏈不計新增（重顯示舊行不可假陽性）；
     tail 行≈上次已有行＝重讀跳過。**踩坑：噪音守門必比「礦名部分」不可比整行**——聊天行共享長前綴
     `<名> has found `，整行 SequenceMatcher 0.85 連 Saerylium vs Essentlum（不同礦）都 ≥0.857
     →真新增行被誤殺（TDD 當場抓到）；都是 found 行時只比礦名。同名稀有連續兩筆帳本不收
     ＝count 差分 1→2 兜底。
- **fixture**：`tests/test_ocr.py` H032 實錄區塊＋ChatLedger 區塊（7 測試）
- **commit**：ac22e15（錨點對齊＋剝冠詞）、626ac66（episode 帳本＋晚到確認）

## H033–H038（2026-07-04）：RapidOCR 觀察期六輪＋i/l 同形誤讀

- **症狀/結果**：聊天 OCR 換 RapidOCR 首選後上線觀察六輪：4 成功、2 掃描全空（後者是框偵測層非 OCR）。
  成功行拼字乾淨（前一晚 tesseract 同場景滿屏誤讀）、found 行低信心 WARNING=0→**裁決留用**。
- **發現的弱點（H033）**：遊戲字型 **i/l 同形**、誤讀信心還很高（Essentium→Essentlum conf 0.889，
  WARNING 門檻 0.80 抓不到）→高階被標「⚠ 未知礦名」、低階誤讀（Dianantine 等）洗版未知警告。
- **對策**：`game_data.classify_found_ore` 加模糊最近鄰兜底 `CLASSIFY_FUZZY_RATIO=0.80`（遠高於垃圾救援層
  FUZZY_ORE_RATIO=0.62——只修近失拼字、真清單漂移仍落 unknown；H020 垃圾 velyiiuinm→Valytium 0.667
  不可被吃）；rare 須嚴格贏 common（寧漏勿假）；命中回 `rare_fuzzy`＋fuzzy_ratio、通知標 ≈ 供人工核對。
- **另一坑（H032/H033 實錄）**：RapidOCR init 實機 6~7s（非 benchmark 的 2.5s），lazy init 曾吃掉第一次採集
  的 verify 窗口→`Bot.run` 啟動時背景執行緒預熱。
- **選型備忘**：關鍵參數 `Det.limit_type=max`（不設會把 280px 裁圖短邊放大到 736、慢 3 倍）；en_v4 mobile
  模型反而更慢（16~20s）勿用；星數會誤導（RapidOCR 7k vs PaddleOCR 84k），PyPI 月下載 RapidOCR ~491 萬
  反超。benchmark：H020 的 `has found Valytium` 精確匹配直接過（tess 靠 fuzzy 才救）、H005 的 Saerylium
  拼字全對。詳見記憶 project-dependency-alternatives-survey。
- **fixture**：`tests/fixtures/chat/h005_mixed_dark_bg.png`（Saerylium benchmark）、h014/h020 系列共用
- **commit**：51cf981（RapidOCR 首選）、419321d（觀察期裁決輸出）、d202fdb（classify 兜底＋預熱）

## H034（2026-07-04）：chill 低分觸發是真 chill＝缺參考家族

- **症狀**：chill 以 0.26（剛過門檻）觸發，實際採到 Transcendent 級 Kardiá——低分觸發**不是誤觸**。
- **一句話根因**：真 chill 但不像任何現有參考＝參考集缺該音效家族（chill 至少 4+ 家族，單參考必漏）。
- **對策**：`python -m miningbot.add_chill_ref --scan` 擴充參考集 6→8（H014/H034 兩個新家族；
  H019/H027/H028/H029/H032 是它們的重複、去重 0.73-0.96 命中）。
- **同日教訓（盲掃 _miss＝雜訊）**：盲掃曾把 6 個 audiochg `_miss` 升級成參考，對照實驗（新參考前後
  對全部 confirmed 錄音各算 match_score_multi）證實 6 個全部「對 25 個 confirmed 真 chill 零貢獻＋
  對任何 confirmed 最高只像 0.16-0.48」＝純假觸發風險，已移除——「與現有參考不像」分不出新家族 vs 雜訊，
  去重種子順序擋不住這洞。`--scan` 改**預設只收 confirmed**（chill_audio_*），`--include-miss` 顯式
  opt-in＋人工聽過（有測試鎖）。正確擴充法＝從「低分但有成功採收佐證」的 confirmed 錄音加。
- **預算備忘**：參考變多要同步查 decimate 預算——12 refs×k=4 一輪 ~312ms 超過 0.3s score 間隔＝必積壓
  （歷史 6s 延遲的失效模式）→`audio_match_decimate` 4→8（8 refs ~98ms；20 個實錄驗證 k=4/8 分數差 ≤0.007）。
  另：離線拿「整段錄音」量分數比實機滾動窗（1.5s）保守——同一檔 clip 對 clip 0.96、整段只 0.31，
  別用整段低分否定參考涵蓋，以實機 log 分數為準。
- **fixture**：參考集 `assets/chill_refs/*.wav`（機器相依、gitignore）
- **commit**：d202fdb（參考集擴充）、9cc7420（--scan 預設只收 confirmed）

## H039（2026-07-04 22:12）：首例 Enigmatic 成功＋Master ionized 變體實錘

- **經過（成功案例）**：chill 0.82 高分觸發→sweep dir=3 早停（edge=0.62）→D3→poll 0.5s confirmed，
  採到 **Sweetheart（Enigmatic，1/65M）**，白名單正確標注。全鏈路（音訊參考集/早停/RapidOCR/開火後
  基準 OCR）首次一次到位，端到端 ~24s。
- **副產物發現**：聊天被動舊行 `an ionized Heartstone`（Master、ionized 1/4M）——證實 **Rare/Master 的
  ionized 變體也會被動進聊天**（wiki 之前只證實 spectral）。當時 Heartstone 缺列→被計入 rare count＋
  假 special＋標未知礦名（幸運同窗口有真 Sweetheart＝真陽性；**若 D3 miss 就是假成功**）。
- **對策**：Heartstone 入 LUCERNIA.common_ores（**Rare/Master 底名可列的首例**；Master 遠低於 Exotic、
  chill 不會為它觸發→零假陰性風險）。`fetch_ores` 設計上只收 Surreal+ 印不出這類 diff→**這類缺口靠實機
  「⚠ 未知礦名」警告浮出、逐例補列**。
- **已知保守面**：基準空（聊天淡出）時新訊息喚醒的舊被動行全算「新增」——靠排除清單擋；Heartstone 這類
  缺列就是此路徑的假成功缺口。
- **fixture**：`assets/markers/enigmatic_tracker_real.png`（尖刺太陽形框，舊模板集對它僅 0.539）；
  `tests/fixtures/chat/h039_after_pink_bg.png`、`h039_before_empty.png`（亮粉背景 11 行、before 空基準）
- **commit**：對策在 2026-07-05 工作樹 WIP（本檔撰寫時尚未 commit；fixtures 同批）

## 視角回歸 45° 斜角（2026-07-05）：驗證式旋轉

- **症狀**：使用者回報採集後視角有時回不到原角、停在 45/135/225°（挖礦視角 90° 倍數對齊，斜角直接傷挖礦效率）。
- **一句話根因**：視角回歸靠 `net_rotations` 計數反轉，但 `,`/`.` 可能被吃→計數與實際角度脫鉤、差 45°×被吃次數。
- **細節**：吃鍵來源＝(1) **成功路徑 restore_view 在 pickup 動畫 1-2s 吃鍵窗口內送鍵＝主要肇因**；
  (2) 焦點被搶；(3) miner init/handle_cave 成對 `,.` 吃半對。
- **對策（`Bot._rotate_verified`）**：每次送鍵前後截 `rotation_verify_region`（中央偏上場景帶，避 UI/角色）
  比對——**兩訊號都近零才判被吃**（`harvester.rotation_looks_eaten`＝平均差＋`vision.frames_changed_frac`；
  近全黑礦坑旋轉平均差低但變化像素佔比高，**誤判重送＝過轉反製造偏移，比漏判更糟**）→`_focus_roblox` 後
  重送（上限 `rotation_max_retries=2`）；重試用盡**不計入 net_rotations**（計數＝實際角度）。套用點：
  sweep 兩迴圈、`restore_view(rotate=…)` 注入、miner 成對（右轉沒成就不左轉）；成功路徑動畫等待挪到
  restore 之前；settle 含在 `_rotate_verified` 內。
- **待辦**：門檻（mean 2.0／frac 0.02／pixel 12）尚未實機校準，被吃誤重送風險已由 AND 條件壓低。
- **fixture**：無（純時序/輸入層）
- **commit**：2026-07-05 工作樹 WIP（本檔撰寫時尚未 commit）

## H040（2026-07-10 20:28~23:53，harvest 066-070）：sweep 全空家族——207px 大框裝不進 160px shape ROI

- **症狀**：一晚連續五輪採集交人工。067/069/070 第一次 sweep 就 8 方位全空；066/071 開火後 RESWEEP 全空。
- **一句話根因（070 實錘）**：追蹤框可以渲染到 **207×208 px**（070_dir0 畫面正中央粗紅方框，bbox x836-1043 y492-700），但 `tracker_shape_roi_px=160` 的形狀確認 ROI 根本裝不下它——模板×尺度超過 ROI 被 `_best_edge_match_sized` 的 `th > sh` 跳過、既有最大模板 120px 對 207px 實框尺度差 1.7 倍 → edge 崩到 0.28-0.32 全數 hard_rej。**ROI 尺寸把可偵測框大小硬上限在 ~160px，是結構性缺口**（H044-064 全空家族備忘錄的「裁模板」處方對這型無效，模板再多也裝不進 ROI）。
- **證據**：`_diag_tracker` 070_dir0：HSV 候選 (960,617) colored=0.99 / (960,592) 0.79 / (991,553) 0.84 全落在紅框內、edge 0.28-0.32 hard_rej。離線兩側夾（模板含新裁圖、reference=None）：roi=320 → TP 場景命中 (991,553) **edge=1.00**；負樣本（069 紅緞帶裝備）維持 None（裝備 edge 峰值 0.21-0.38 不越 0.42）；roi=160 → TP 抓不到（事故重現）。roi=320 唯一新增誤收＝工作列圖示 (824,1055) borderline ring 路徑（edge 0.30-0.37）——靜態 UI，實戰被 pre-scan reference 差分擋掉，非新風險面。
- **對策**：`tracker_shape_roi_px` 160→320；裁 070 實機紅方框入 `assets/markers/red_square_tracker_real.png`（第 4 種實機框形：粗紅方框）。
- **未解殘留（本事故只修 070 型）**：069 各方位無傳統框可見（角色手邊有紅圈小礦、地上白彩虹礦，疑掃描未觸發或框形未見過）；070 部分方位鏡頭被牆擠成臉部特寫（camera collision，框不可能入鏡）；067/068 無幀存檔前例可判。這三型靠下輪實機 log＋全空快照續診。
- **fixture**：`assets/red_square_tracker_scene.png`（TP）、`assets/red_ribbon_equipment_scene.png`（負樣本，紅緞帶裝飾＋紅圈小礦）
- **commit**：（本輪工作樹）

## H041（2026-07-11 00:55，harvest 071）：RapidOCR 連字號黏行——成功行對兩條解析路徑同時隱形

- **症狀**：D3 開火後 verify 三次 OCR（poll/final-check/late）全部 confirmed=False → RESWEEP → 全空（礦已採走）→ 誤交人工。快照肉眼可見聊天末行綠字 `small_lo has found Fortuitous`＝真成功。
- **一句話根因**：RapidOCR 把該行讀成 `small-lo-has-found-Fortuitous`（三次重測穩定，conf 0.97-0.99，空格全變連字號、整行黏成單一 token）→ 精確路徑 `has found` 子字串對不上、模糊路徑 `_fuzzy_rare_line` 整行只剩 1 個 token 且在行首（i==0 跳過）→ **兩條路徑同時全滅**，log 連 fuzzy 評估記錄都沒有（這行完全隱形）。
- **與 H020 的差異**：H020 是「關鍵字讀歪」（hee foumel）、token 還在；H041 是「分詞整個消失」——fuzzy 兜底的 token 結構假設（found-ish token 非行首）被黏行擊穿。
- **對策（寧漏勿假成功方向不變）**：found 行解析加連字號 fallback——原行比對全滅且含 `-` 時，`-`→空格重試一次；排除清單 startswith 兩側對稱去連字號（一般礦黏行 `small-lo-has-found-Siogyne` 仍被排除，白名單既有連字號礦名 X-Flare/Sub-Zero 等不受害）；fuzzy tokenization 同步去連字號。Fortuitous 本身已在白名單（rare_ores.json），清單零改動。
- **fixture**：`tests/fixtures/chat/h041_before_faded.png`（淡出基準，OCR 只剩側欄 2 行）、`h041_after_fortuitous_hyphen.png`（13 行含黏行，本機重測穩定重現 `rsmall_lo-has-found-Fortuitous`）
- **commit**：（本輪工作樹）

## H042（2026-07-11 22:14~22:16，harvest 072）：同畫面兩顆礦只採一顆——成功路徑無條件收尾

- **症狀**：一次 chill 觸發的採集中，畫面同時出現兩顆不同階礦的追蹤框（黃橘方框＋尖刺太陽框兩種框形）。腳本採到第一顆（Feebrechaun，Exotic 1/3,232,323）後直接回 MINING，第二顆漏採。
- **時間線**：22:14:44 chill(0.28) 進 HARVESTING → sweep dir=4 鎖 (603,223)、第一發 D3 未中 → RETRY → 開火前重定位失敗轉全方位重掃 → 22:15:58 **同一幀兩個候選過形狀確認**：(607,223) edge=0.78 ＋ (1097,475) edge=0.61 → 22:16:03 對 (607,223) 開火命中（聊天確認、背包 6→7）→ SUCCESS → 22:16:19 成功收場幀上 (1097,475) 尖刺太陽框仍清晰存在，照樣 restore_view 回 MINING。
- **一句話根因**：`_harvest_success` 無條件收尾回 MINING（設計假設一次 episode＝一顆礦），同畫面第二顆礦的追蹤框被直接放棄——不是偵測問題（find_tracker 在成功幀上離線實測仍抓得到 (1097,475) edge=0.61），是流程沒有這條路。
- **對策（續採迴圈，寧漏勿誤）**：成功收尾前雙幀穩定 recheck 當下幀；`harvester.decide_post_success` 純決策——**距離閘** `harvest_extra_target_min_dist_px=100` 擋「剛採掉、擊中後 2~10s 才淡出」的原地殘影（兩側夾：真第二顆距上發開火點 **551px**、殘影漂移 **≤8px**，兩側各 ~5.5x/12x 餘裕）；上限 `harvest_extra_targets_max=2` 防迴圈；fired_pos 不明（晚到確認路徑）→ 不續採。CONTINUE＝重開聊天差分基準（成功已入帳，不重開則上一顆的成功行會讓第二發未命中也判 confirmed＝假成功；「episode 基準不作廢」規則護的是誤判失敗、不適用確認成功後）＋走既有 `_reharvest_sweep`（保 `_pre_scan_ref` 不自我致盲）留在 HARVESTING；net_rotations 跨目標累計、最後一次轉回。**護欄**：續採途中 sweep 全空/超時 → `EXIT_SUCCESS` 正常收尾回 MINING（bonus 框淡掉≠失敗，絕不把已成功 episode 轉成交人工）。
- **fixture**：`assets/dual_tracker_scene.png`（開火前雙框幀→(607,223)）、`assets/post_success_second_tracker_scene.png`（成功收場幀→(1097,475)）；回歸 `tests/test_vision.py` 072 區塊＋`tests/test_harvester.py` decide_post_success/extra_mode 區塊。
- **commit**：（本輪工作樹）

## H043（2026-07-12~13，reentry ep1-3）：重置墜入虛空——「Go to surface」在虛空下墜中點不動
- **症狀**：remote 回礦三次實機 run（07-12 19:48/21:04、07-13 16:52）全部「按回到地表畫面無變化」；`重骰` 有被消費（log 可見 focus＋點擊重跑）但一樣無效，只能 `跳過` 交人工。
- **時間線（07-13 場）**：16:52:16 banner「reset in 28 seconds」→ 16:52:44 礦體消失、玩家自由落體墜入虛空 → 16:52:50 REENTRY 開場點擊 (1855,965) 無效 → 17:09/17:10 兩次重骰同樣無效 → 17:18 實機截圖：畫面全黑、**Depth 33,290,005m 持續增加**（掛 25 分鐘還在掉）。
- **一句話根因**：RESET_WAIT 等 banner 消失才進 REENTRY ＝ 重置瞬間人還在礦內 → 礦體消失直接掉進虛空；**虛空下墜狀態「Go to surface」按鈕幾乎不回應**（活體實驗：瞬間點/hold 0.35s/懸停 0.3s 全滅、僅偶發成功；同時刻 hotbar `^` 鈕即點即開＝合成點擊與座標都沒問題）。
- **反證實驗（地表狀態）**：同一 `focus→grab→click_at` 原序列 100% 傳送成功；重複點＝換重生點（spec 重骰語意成立）。
- **附帶量測**：傳送幀差——虛空→夜間地表穩定值僅 ~19、地表換重生點最低 26.8、無變化噪音 ≤4.4 → 舊門檻 `reentry_teleport_diff=25` 會漏判真傳送，降 12.0（兩側夾）。
- **對策**：(1) **RESET_WAIT 進場即撤離**——banner 出現時礦體還在、點擊可靠，先按回到地表離開礦坑，不讓人掉虛空（僅 remote 模式）；(2) 撤離/開場點擊共用 `_click_surface_verified`：幀差驗證＋重試 `reentry_click_retries=3`（重試前游標移中央再移回、多一次真實移動事件）；(3) 開場失敗警告附當下截圖（全黑＝虛空一眼可辨）；(4) `_rr_notify` 統一記錄 Discord 送達結果（舊版 send_message 回傳被丟棄、送沒送到無從稽核）。
- **診斷佐證**：logs/reentry_debug_now.png（虛空全黑幀）、logs/exp2_after.png（傳送成功幀）；memory `reentry-void-fall`。
- **commit**：（本輪工作樹；同輪含 REENTRY 互動 embed 化——🎲重骰/⏭️跳過/📷重掃反應鈕）

## H044（2026-07-14，reentry ep3）：礦坑重生客戶端全凍結——REENTRY 凍結中誤跑＋覆蓋視窗假傳送
- **症狀**：18:25:43 banner「reset in 28 seconds」→ 撤離成功 → 18:26:15 REENTRY 開跑後整條開場鏈打在凍結畫面上：俯仰歸位 mean=0.0/frac=0.0、8 個方位旋轉鍵全數「疑似被吃」重試用盡、8 張方位圖全是同一張凍結幀發到 Discord；18:28:35 使用者按 📷 重掃時畫面已恢復、重掃正常。
- **時間線**：~18:26:11 礦坑開始重生 → 客戶端渲染**整個凍結 1~2.5 分鐘**（頂部凍在事件橫幅「Viridescent i」打字動畫中途、無 reset 字樣）→「banner 消失＋沉澱 5s」成立 → REENTRY 在凍結中開跑。
- **一句話根因**：開場鏈在凍結畫面上全數空轉，因為 (a) 觸發條件只驗 banner 字樣、凍結幀恰無該字樣；且 (b) 傳送驗證量**全幀**、被螢幕中央覆蓋視窗（Claude 視窗）重繪灌爆門檻 12（全幀 11.3~13.2 全來自覆蓋視窗區 35.3＋頂部橫幅 7.5）誤判「已傳送」。
- **關鍵量測**（`reentry_game_region` x1100-1790/y200-850 裁圖）：凍結對 5s/12s＝**0.00 整**（逐位元相同）；活著但靜止（07-12 夜間地表）0.35s/4s/10s＝mean ≤0.09/frac ≤0.0004；真傳送（礦內→地表）＝mean 57.73/frac 0.9966。
- **重要否決**：「被動活性閘（遊戲區連續 N 秒無變化＝凍結）」被量測否決——活著靜止畫面與凍結像素上不可分（0.0004 vs 0.0000），硬上會在靜止地表假凍結卡到超時。
- **對策**：(1) **傳送驗證區域化＋雙訊號**——`_click_surface_verified` 改量 `reentry_game_region`，`mean ≥ 12` OR `frac ≥ 0.05`（兩側餘裕 4.8x/20x 起）；(2) **探測式開場**——點擊當探針：判「未傳送」不通知不拍圖，每 `reentry_open_retry_wait_s=20s` 再點一次，解凍後下一擊自然傳送成功流程續走；`reentry_open_budget_s=300s` 用盡才通知一次附截圖（全黑＝虛空、有畫面＝凍結）；H043 虛空偶發成功也被同一迴圈吸收；(3) 同輪新增**手動回礦**：Discord `回礦`/`reenter` 指令＋STUCK 警告 🏠 反應鈕（`states.decide_transition` 新旗標 `manual_reentry`；MINING/NEEDS_HUMAN/RESET_WAIT 可觸發、RESET_WAIT 下＝繞過 reset_complete 的人工強制；用途不限卡死，ledger 記 `trigger` 來源）；(4) **互動先 ACK、結果後送**（2026-07-16）：本事故 📷 重掃在 18:28:35 已偵測、18:28:55 才送結果，故反應／文字排入 pending 後立即回「已收到」，reaction 輪詢改單張訊息 count 摘要並把間隔 3s→1s；八方位結果仍於安全的主迴圈完成後送。
- **fixture**：`tests/fixtures/reentry/h044_{frozen,alive_static,teleport}_{a,b}.png`＋`tests/test_reentry_fixtures.py` 兩側夾回歸。
- **設計**：`docs/superpowers/specs/2026-07-14-manual-reentry-and-freeze-gate-design.md`。
- **commit**：（本輪工作樹）

## H045（2026-07-14 ep3 追加根因，2026-07-17 裁決）：提前撤離丟位置記憶＋開場閘漏「傳送後才凍結」
- **症狀（使用者回報）**：(1) 重置回礦「不知為何提前點 Go to surface」——遊戲只在**重置當下人在礦坑內**才記錄玩家位置，提前撤到地表＝臨時挖到的稀有礦回不去原位；(2) 回礦 Discord 照片「速度過快、大多重複」——照片全是凍結舊幀，容量還沒歸 0、也沒收到重置鈴聲，操作全被吃。
- **時間線（07-14 18:25 ep3，與 H044 同輪）**：18:25:43 banner「reset in 28 seconds」→ 18:25:47 **banner+4s 即撤離**（H043 對策，離真重置還有 ~24s）→ 18:26:15 REENTRY → 18:26:19 開場點擊**真的傳送成功**（點在凍結開始前、幀差真過門檻）→ 18:26:40 俯仰歸位 mean=0.0/frac=0.0（凍結已開始）→ 程式只說「圖照發，角度可能偏」**照樣拍**：18:26:41~18:27:10 八張方位圖全同一張凍結舊幀（Capacity 78%）→ 18:28:42 旋轉才恢復（凍結 ~2 分鐘，H044 型態）。
- **一句話根因**：(1) H043「進場即撤離」無條件執行，位置記憶被無條件犧牲；(2) H044 探測閘只設在**開場點擊**上——點擊落在凍結開始前時驗證真過，其後的俯仰 0.0 訊號已量到凍結卻沒拿來中止拍照鏈。
- **附帶發現（鈴聲樣本存不到的結構性原因）**：`reset_chime_arm_delay_s=30` > banner 倒數 26~28s，且離開 RESET_WAIT 即停錄——實錄 18:26:14 錄音啟動、18:26:15 就轉 REENTRY，**錄音窗僅 1s**，鈴聲（重置當下）永遠在窗外。
- **對策（使用者 2026-07-17 裁決：留坑內記位置，回位仍走 Discord 選傳送板）**：(1) 撤離改 `reentry_evac_on_banner` 總開關、**預設關**——重置當下人在坑內讓遊戲記位置，墜虛空/重生凍結交 H044 探測預算（300s）吸收；實機若虛空卡死率不可接受可開回 True 復原 H043 行為；(2) **開場雙閘**（`reentry_remote.plan_opening_gate` 純函式）：傳送驗證過後、拍照前再閘「俯仰歸位幀差」（凍結探針：凍結 0.00 vs 傳送 57.73）＋「容量歸零」（`reentry_open_capacity_max_pct=0`；兩側夾：凍結舊幀 **78%** vs 真重置後 **0%**，ep3 實機幀）——任一未過不拍照不發圖、回探測迴圈；容量閘僅 reset 觸發（手動回礦挖礦中容量本來就非 0）、OCR 讀不到＝保守等下一探（預算收口有界）；(3) **錄音窗改容量錨**（使用者同日追加裁決：時間錨是猜的，banner 到真重置完成耗時不定）——`audio.chime_capacity_armed`＋`capture_window_active` 純函式：RESET_WAIT/REENTRY 期間容量 OCR 讀到 ≤ `reset_chime_capacity_arm_pct=10` 才開窗（與開場容量閘同訊號源；兩側夾同 78/0），窗自觀測時刻起 `reset_chime_capture_max_s=120s` 收口、跨 RESET_WAIT/REENTRY；讀值來源＝banner worker（RESET_WAIT 期間解除飽和鎖定照讀容量）＋REENTRY 開場閘的容量 OCR。
- **回歸**：`tests/test_reentry_remote.py` H045 區塊（雙閘兩側夾 78/0、手動觸發跳過容量閘）＋`tests/test_audio.py` 錄音窗四例。
- **下輪實機驗證預期**：miningbot.log 不再出現「重置撤離：已傳送至地表」；凍結輪看到「開場閘未過（frozen/capacity…）——20s 後再探」且該期間 **零** `reentry_epN_dir*` 快照；解凍後一次過閘才出現 8 張方位圖；重置完成後出現「🔔 容量已歸零（…）→ 鈴聲錄音窗開啟 120s」＋「🔔 重置鈴聲擷取啟動（容量錨…）」且窗內 `logs/snapshots/audio/` 有 reset-chime 片段落盤。
- **部分實機驗證（2026-07-17 ep1/ep2，H046 同輪 16:43 程序）**：對策 (1) 撤離預設關已生效——兩輪重置（17:22、18:51）皆無「重置撤離」行；其餘預期（過閘拍照、鈴聲容量錨開窗）被 H046 誤鎖擋住沒走到，隨 H046 版下輪一併驗證。
- **commit**：（本輪工作樹）

## H046（2026-07-17 ep1/ep2 實測，同日修正）：H045 開場閘首戰翻車——活人被鎖 300s＋真成功地表被判未成功
- **症狀（使用者回報＋log）**：ep1（17:22）與 ep2（18:51）重置回礦全程「開場閘未過（frozen：capacity=None）」20s 一發直到預算 300s 用盡；`重骰` 有被消費但走同一條誤鎖的閘→不拍照（「重骰失敗、沒有重新掃描」）；只能跳過交人工。實機幀（17:24:55 pitch_eaten_before）打臉：頂部明寫 **Capacity: 0% / Depth: Surface**——人活著站在地表、重置早已完成。
- **一句話根因（三個，環環相扣）**：(a) **凍結判定誤用 pitch_eaten 門檻**（8.0/0.15 是「拖曳生效」兩側夾：被吃 ≤3.29 vs 生效 ≥32.5）——夜間地表場景暗，俯仰拖曳真的動了 mean 也只有 **0.93~5.13/frac 0.018~0.096**，全被判「frozen」；(b) **容量 OCR 被耦合在 pitch_ok 之後**——pitch 不過就永遠不讀容量（capacity=None 十一連發），畫面上的 0% 從沒被消費，鈴聲容量錨也因此從沒開窗；(c) **轉移式驗證的結構缺陷**（使用者點名）：開場成立與否綁在「點擊造成幀差」上——人已真的在地表時再點「回到地表」畫面可能毫無變化，真成功被判未成功、卡死重骰。
- **對策（開場閘全面改「狀態制」）**：(1) 凍結判定改 `probe_frozen` 專用門檻 `reentry_frozen_mean_max=0.02`/`frac_max=0.0002`（AND 語意；兩側夾：凍結 **0.00/0.0000** 逐位元相同 vs 活著靜止 0.09/0.0004 vs 夜間地表拖曳最小 0.93/0.018——⚠ 永遠不可拿 pitch_eaten_* 當凍結判定）；(2) **Depth 狀態錨**：頂部「Depth: Surface / NNNm」列（`depth_region=Region(890,92,210,45)`，實機 3 幀 Surface/488m/25790m 實測 3/3）——Surface＝人真的在地表才拍照，NNNm＝礦內/虛空墜落中繼續探測點擊；(3) 容量/深度讀值與俯仰結果**解耦**（同一幀 grab 一次裁兩區）；(4) `plan_opening_gate` 改判 frozen→not_surface/depth_unread→capacity→proceed，**點擊幀差降為輔助訊號**（未傳送不再提前 return）；(5) 俯仰「被吃但沒凍結」只警告不擋拍照，遠端可用新 `仰角 歸位`/`仰角 上|下 [px]` 指令修正後 📷 重掃。
- **同輪**：R 取樣視窗（Tk 面板＋R 熱鍵）退役——截圖→遙控器 📷（落編號樣本供 `calibrate_surface --import`）、俯仰→`仰角` 指令；`_pitch_drag_measured` 拆出原始量測值供凍結探針用。
- **fixture**：`tests/fixtures/reentry/h046_depth_{surface,488m,25790m}.png`＋`tests/test_depth_fixtures.py`（真實引擎 3/3）；純函式回歸 `tests/test_reentry_remote.py` H046 區塊（probe_frozen 兩側夾、狀態閘各 verdict、仰角解析）。
- **附帶發現（追 log 一小時）**：`pythonw -m miningbot`＝Microsoft Store/MSIX Python，`%LOCALAPPDATA%\RexMacro\logs` 被虛擬化重導到 `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\LocalCache\Local\RexMacro\logs`——log 內印的路徑直接查會撲空（已記入 CLAUDE.md 實機排錯）。
- **同日追加（2026-07-17 晚，預防性收尾＋通知強化）**：(1) `_rr_click` 下礦驗證是同型轉移式缺陷（點擊後等幀差）——改狀態錨 `plan_click_verdict`：Depth 從 Surface 翻成 NNNm＝唯一成功條件（重複點已成功的傳送板畫面不動＝舊版假失敗；地表→地表換重生點 diff ≥26.8 畫面大動＝舊版假成功），幀差降輔助訊號——Depth OCR 讀不到時退回幀差降級（有動＝交人工確認寧問勿假成功、沒動＝判無效留 awaiting_fine，皆有 log 警告不靜默）；礦內亮度檢查退役（夜間暗景騙亮度，H046(a) 同源）。(2) 開場探測 give_up 通知附最後一探讀值（`format_gate_readings`：depth/capacity/pitch 幀差）——遠端一眼分型：depth=NNNm/讀不到＋pitch 有動＝虛空、pitch 0.00/0.0000＝凍結、Surface＋容量未歸零＝重置未完成/按鈕失效。純函式回歸 `tests/test_reentry_remote.py` H046(c) 區塊（7 例）。
- **下輪實機驗證預期**（⚠ 先重啟 bot——**19:31 前所有程序載的都是修正前的碼**；07-17 16:43~18:53 那輪是事故本身不是驗證）：重置回礦 log 出現「開場閘未過（…surface=False…）」（傳送前）→ 傳送成功後一輪內「surface=True capacity=0.0」過閘拍照；人已在地表的輪（點擊無幀差）**不再**卡 300s，一樣過閘；`重骰` 後 20-30s 內出現新八方位圖；`仰角 上 100` 回「✅ 仰角▲ 上 100px」；細格點擊後 log 出現「[RR#N] 點擊驗證：descended（depth_surface=False…）」且 Discord 回「✅ …下礦成功（Depth 已離開 Surface…）」；探測預算用盡時通知帶「最後一探：depth=…｜capacity=…｜pitch幀差=…」。
- **commit**：（本輪工作樹）

## H047（2026-07-17 14:47＋2026-07-18 02:15 兩場啟動）：開場聊天框檢查假陰性——bot 親手把開著的聊天框關掉

- **症狀（使用者發現）**：實機掛機中左上聊天框是關的，懷疑是 bot 關的、開場檢測沒真的驗證。log 佐證：兩場啟動的聊天框檢查都以「連點 3 次仍未開啟」WARNING 收場；關閉期間聊天 verify 鏈全瞎；02:46 快照的聊天圖示掛未讀徽章「11」＝訊息持續進來沒人看見。
- **時間線（02:15 場，14:47 場同劇本）**：02:15:39 首檢 OCR 判「關閉」→ 點擊 #1 → 02:15:43 複檢仍「關」（聚焦成功）→ 點擊 #2 → 02:15:47 仍「關」→ 點擊 #3 → 02:15:50 WARNING＋`chat_open_fail` 快照（終幀聊天框確實關閉）。過去 5 次啟動首檢**全部**判「關閉」。
- **一句話根因**：REX 聊天框**開著且過久沒訊息會把整個視窗自動隱藏**（使用者證實；實驗當場重現——手動開啟數分鐘後再截圖，`chat_input_region` OCR 讀到的是背包面板標題 `'NYVAMNMAL\nwww'`）→ placeholder 文字信號假陰性「關閉」→ toggle 圖示被當單向開啟鈕點下去，**第一擊就把開著的聊天框關掉**；複檢用同一個瞎掉的信號，重試連點奇數次、終態必關。
- **奇偶推理（初態=開的證明）**：三擊皆有「Roblox 聚焦成功」（點擊落地）＋終幀=關 ⇒ 初態=開；且上一場（20:16）結束時聊天框由 bot 確認開啟過、之後無人關它。
- **新信號（使用者指出）＋兩側夾**：左上聊天圖示開啟（含自動隱藏）＝**實心白**泡泡、關閉＝**空心白邊**泡泡（可帶右上未讀徽章）；40×40 裁圖（全幀 (154,51)）取泡泡內部補丁（crop 相對 x∈[6,18) y∈[21,28)，避開中央筆劃與徽章）gray mean：**開 238..255（n=42）vs 關 81..87（n=19 含徽章樣本 83）**→ 門檻 ≥180 開／≤130 關／中間 unknown。
- **對策**：檢查改「圖示狀態制」——`vision.chat_icon_state`（open/closed/unknown 純分類）＋`roblox_menu.plan_chat_open_action`（純決策）；**unknown 絕不點擊**（比照玩家列表「絕不按第二次 Tab」：誤判開＝不點無害、誤判關＝點下去會關掉開著的，破壞性動作只在明確判關時執行；白閃全白判開＝安全方向）；placeholder 信號（`chat_input_region`/`chat_input_phrases`）退役。通知維持 log＋HUD＋trace 快照、不上 Discord（使用者 2026-07-18 裁決）。
- **fixture**：`tests/fixtures/chat_icon/h047_icon_{open_solid,closed_hollow,closed_hollow_badge11}.png`＋分類/決策純函式回歸。
- **設計**：`docs/superpowers/specs/2026-07-18-chat-open-icon-check-design.md`。
- **下輪實機驗證預期**：啟動 log 出現「聊天框已開啟（圖示實心，probe=…）」（或明確判關後一擊即轉實心）；不得再出現「仍未開啟，第 N 次重試」連鎖與奇數擊終態關閉。
- **commit**：（本輪工作樹）

## H048（2026-07-17 17:24 RR#1／18:51 RR#2／2026-07-18 03:35 RR#2 連三場）：回礦開場俯仰歸位「重置後第一次必被吃」——右鍵拖曳游標甩出視口＋拖曳間距不足

- **症狀（使用者發現）**：`仰角` 指令調好的視角，每次重置後開場鏈第一次俯仰歸位都沒作用。log 佐證：三場開場歸位全判「疑似被吃」（mean 0.51~5.54），07-17 21:00 兩次「生效 19.7/17.4」實為下拉段假陽性；trace 前後幀快照證實拖曳前後畫面逐位元幾乎相同。
- **實機兩側實驗（2026-07-18 04:0x~04:2x，遊戲開著逐段量測）**：
  - 游標軌跡：中央 (960,540) 起手下拉 1500 → 游標實走到底邊 (1200,1079)；回拉 400 → 游標飛到頂邊 (1200,0)，右鍵在標題列放開**彈出視窗系統選單**（還原/移動/…）吃掉後續輸入。指標加速實測：注入 40→實走 78、80→174、120→271、180→416（~2.0-2.3x）。
  - 拖曳間距：前段拖完 0.15~0.2s 內起手的下一段右鍵被吃（回拉段緊接下拉段 settle 0.15s → **回拉長期失效、歸位實停在下夾限**）；0.55s 以上生效。
  - 起手位置：游標蓋在 3D 視口上的單段上拉 400px → full-frame mean 86.98 大動；起手在「回到地表」按鈕/工作列上→整段被吞（開場鏈點完按鈕游標就停在按鈕上，正是「第一次必被吃」的直接原因）。
- **一句話根因**：合成右鍵拖曳時 Roblox 不一定鎖游標，`pitch_reset` 兩段拖曳都從「游標當下位置」起手且一次 hold 注入過大——起手點落在 UI 按鈕/工作列上整段被吞、指標加速把游標甩到標題列彈系統選單、兩段間 0.15s 的下一段右鍵必被吃。
- **對策**：(1) `input_control._drag_vertical` 人式分段重寫——單次 hold 注入 ≤`pitch_drag_hold_budget_px`(150，加速後實走 ~345px 甩不出視口)、每次 hold 前游標置中＋`pitch_drag_hold_settle_s`(0.8) 沉澱（含首段，覆蓋「點完 UI 立刻拖」時序）；校準量仍以注入 px 總和計。(2) 開場鏈歸位比照其他俯仰路徑：`_sampler_pitch_prepare`＋被吃重試一次（冪等）。實機驗證：修後 `ic.pitch_reset` 連跑兩次最終幀差 0.621（冪等成立）、游標活動範圍 [270,743] 全程視口內、單次歸位 ~18s。
- **fixture/回歸**：`tests/test_input_control.py` H048 區塊（hold 預算/置中/沉澱/總量守恆/飽和→回拉順序）＋`tests/test_main_pitch_home.py` 開場鏈重試兩例。
- **同日指令面調整（使用者需求）**：方位改 1-8（訊息/檔名 1 起算、內部 0-based）；新增 `放大 <細格>` 再放大（細格子區域變新 zoom_region 可連鎖，scale 自動補償，`fine_cell_subregion`/`magnify_scale` 純函式）；`走` 走位退役；`跳過` 改直接回正常挖礦（不再交 NEEDS_HUMAN）；REENTRY 中收到 暫停/繼續（指令或遙控器鈕）視同跳過。
- **仰角可視化（使用者需求，位置指定在「有仰角功能的回礦區」）**：回礦互動卡新增「俯仰：夾限上 Npx（`仰角 上/下 [px]` 調）」行（每指令 PATCH 即時更新，`build_reentry_embed` 帶 `pitch_offset_px`）；`仰角` 指令回覆帶調整後讀值；啟動時 log「啟動仰角：…」＋Discord 啟動訊息「🤖 Bot 已啟動｜仰角：…」（`harvester.format_startup_pitch_status`：歸位成功=夾限上 Npx／被吃=不受控警示／未校準=角度不明）。標準角裁決：`reentry_pitch_back_px=400` 實測後使用者接受（E2E：兩個擾動起始角歸位後最終幀差 0.83＝收斂；~18s/次亦接受）。使用者預告將以本輪資訊為底做新功能。
- **下輪實機驗證預期**：`miningbot.log` 開場出現「俯仰歸位(attempt 1)…-> 生效」（mean 應遠大於個位數；夜間可能仍標被吃但角度實際正確，看 trace 快照）；不得再出現整場歸位全滅；Discord 照片訊息標「方位 1-4／5-8」。
- **實機驗證（2026-07-19 01:33 RR#2）✅**：開場鏈三次「俯仰歸位(attempt 1) → 生效」mean 16.50/16.11/237.39、frac 0.385/0.298/1.0（對照被吃階的 0.51~5.54）＝對策通過；開場閘容量錨 71→56→0 後放行、8 方位照片與 RR 卡（01:35:09 ep=2）照常。
- **commit**：（本輪工作樹）

## H049（2026-07-19 00:51~01:28 掛機場；使用者發現）：D4 事件全被刷新——未知文字即右鍵＋決策快取可早於上次動作

- **症狀（使用者發現）**：D4 把所有事件都跳過（右鍵刷新），包含應該保留的事件。log 佐證：該場 10 次 D4 全為刷新，其中 01:16:42/01:16:46 兩筆「未知/無事件」間隔僅 4 秒連刷、01:32:24 一筆「未知」在重置橫幅偵測前 2 秒；對照 07-17 20:31~20:53 Wintburg 連續保留 7 次＝keep 機制當時正常、事後無程式面變更。
- **證據限制**：已辨識的 7 次刷新（Snowglobe III／Yuki Onna／Evergreen×3／Polaris／Cobbore）都確實不在 keep 清單（Celinity/Ephemryst/Sunflower/Verdafrost/Wintburg）＝照清單行事；01:16 兩筆「未知」當下的原始 OCR 文字**沒落 log、無快照**，無法事後判定是否為 keep 事件被誤讀刷掉——這個可觀測性缺口本身就是本案要修的一部分。
- **一句話根因（結構性，三者都真）**：(1) D4 決策直接用背景 worker 的事件列快取，只驗「4s 內夠新」不驗「晚於上次 D4 動作」——上次右鍵後 4s 內再判時，快取可能是動作前／換場動畫中 OCR 的舊文字；(2) 認不得的文字**立刻**右鍵刷新——keep 事件單次 OCR 誤讀即被不可逆刷掉（刷新不可復原，安全方向應寧等勿刷）；(3) 事件列與重置公告**共用 `chill_text_region`**——重置倒數中 D4 讀到的是重置文字→判未知→白按右鍵（01:32:24 實證，2s 後偵測到 'The mine will reset in 25 seconds.'）。
- **對策**：`miner.d4_text_fresh`（快取須夠新**且**晚於上次 D4 動作，否則同步重讀當前幀）＋`miner.plan_d4`（未知文字第一次 hold，等 worker 下一份新樣本仍未知才刷新——雙樣本確認，比照 tracker 雙幀穩定；hold 逾 3 個 worker 週期無新樣本走同步後備防餓死；`_mine_resetting` 中一律 skip 不動作、不進 hold 記帳）；決策 log 一律落原始文字 `text=…`、hold 時存 `d4_unknown` 快照（歸 review 分類，不被 trace 清檔政策掃掉）。
- **追查陷阱（07-19 補記）**：MSIX LocalCache 的目錄列表中繼資料過期（mtime/size 停在 01:08，內容實際寫到 02:02+）＋窄時間窗 grep，讓第一輪追查把場次終點誤判為 01:28——實際 bot 一路跑到 02:17（01:32 重置→RR#2 等指令 45 分鐘）。判讀規則已入 CLAUDE.md 實機排錯。
- **回歸**：`tests/test_miner.py` D4 區塊（快取有效性 4 例＋plan_d4 4 例）＋`tests/test_diagnostics.py` d4_unknown 分類。
- **下輪實機驗證預期**：`miningbot.log` 若出現「D4: 事件文字認不得，hold 一輪等新樣本再確認 (text=…)」，~2-6s 內須跟一筆正常 keep/刷新決策；`actions.log` 刷新行帶 `text='…'`；不得再出現間隔 <5s 的連續「未知/無事件」刷新。若再有 keep 事件被刷，review/d4_unknown 快照＋log 原文可直接定位是誤讀還是清單問題。
- **同日指令面補強（使用者反映）**：`上|下 [px]`/`歸位` 裸寫（不帶「仰角」前綴）在回礦流程可用；校準卡新增等價文字指令（`上|下 [px]`/`歸位`/`截圖`/`存檔`/`離開`，px 可覆寫幅度）；挖礦中打俯仰指令不再靜默——回指引導向 `校準 挖礦|回礦` 專屬卡（先前 MINING 下這類訊息被無回饋丟棄，使用者以為指令壞掉、也找不到回礦專屬操控卡）。
- **commit**：（本輪工作樹）

---

## H050（2026-07-19 19:33~19:42 RR#7；使用者發現）：「放大圖不是指定的放大圖」——sweep 快照與放大現場面向脫鉤

- **症狀（使用者發現）**：手動回礦 RR#7 中回 `1 E2`（方位 1 的 E2 格，快照上是 Teleportation Board 主體），bot 回的放大圖裡傳送板卻幾乎不在格內（只擦到右緣）；改試 `1 F2` 傳送板又出現在左緣——放大圖與八方位圖對不上，無法據以指細格點擊。
- **量測（實機幀重現）**：attempt2 快照 dir1（19:35:44）vs `1 E2` 現場截圖（19:38:33）＝畫面水平偏移 ~170px（≈6°）；E2 粗格 mean diff **29.66**、F2 **21.6**。無漂移側：同面向差 3 秒（19:35:41 vs 19:35:44）全 24 粗格最大 **3.14**（角色 idle 所在格）、E2 本身 0.04。E2（19:38）與 F2（19:39）兩張現場互相一致＝偏移是 sweep 後一次性、之後穩定。
- **一句話根因**：放大圖是「現場轉向重截」而非裁快照（點擊座標以現況為準，設計正確），但 sweep 拍 dir1 後轉滿一圈的殘差/斜坡滑移使現場面向偏 ~6°，「快照（選格依據）vs 現場（點擊依據）」之間沒有任何守門——偏移直接反映成「放大圖不是我指定的那格」，且使用者無從知道該重掃。
- **對策**：(1) `_rr_zoom` 放大前比對 sweep 快照同格 vs 現場同格（`reentry_remote.zoom_drifted`，門檻沿用 `reentry_remote_drift_diff=12.0`＝`_rr_click` 點擊守門同語意同區域大小；兩側夾 29.66/21.6 vs ≤3.14 分離乾淨）——超標時放大圖照發（現況才可點）、訊息前置「⚠ 畫面已偏離八方位圖…可 📷 重掃」；快照讀不到＝不守門照現行。(2) zoom 檔名加時間戳——同格重複放大不再互相覆蓋（本案 E2 兩次放大只剩一份，事後比對靠 Discord 附圖）。(3) `_rr_sweep_and_send` 補記 `_rotate_verified` 重試用盡次數（原本回傳值被忽略）——發生時 head 帶「方位標籤可能偏」警告＋WARNING log。
- **fixture/回歸**：`tests/fixtures/reentry/h050_zoom_dir1_{e2,d2}_*.png`（漂移/靜態/idle 三型）＋`tests/test_reentry_fixtures.py` H050 區塊（4 例）＋`tests/test_main_rr_zoom.py`（守門觸發/不觸發/快照缺失/檔名時間戳/sweep 旋轉警告 6 例）。
- **下輪實機驗證預期**：放大後畫面若已偏，Discord 放大訊息第一行出現「⚠ 畫面已偏離八方位圖」；`snapshots/reentry/` 同格多次放大留下多份 `ep*_zoom_*_<ts>.png`。
- **未解之謎（不擋結案）**：~6° 殘差的物理來源（8 次 45° 右轉理論精確歸位 vs 斜坡滑移）本案證據不足以定裁；守門不依賴來源，兩型都會被抓。

## H051（2026-07-19 18:57~19:33，harvest 092；使用者發現「正常回礦出問題」）：重置倒數中 chill 搶先採集→收尾誤交人工、重置回礦鏈斷頭 36 分鐘

- **時間線**：18:57:07 容量滿加速輪詢同 tick 偵測 banner「reset in 26 seconds」→ RESET_WAIT；18:57:11 chill（音訊 0.41）→ RESET_WAIT→HARVESTING[092]（刻意設計：搶在重置前採）；18:57:36 sweep 8 方位全空（掃描中 ~18:57:33 礦坑已重置清場——全空是重置的正常結果）→ `_harvest_giveup` 直接 `state=NEEDS_HUMAN`「礦可能已被挖走，請手動處理」；此後 `_mine_resetting` 凍在 True（banner worker 只在 MINING/RESET_WAIT 跑）但 NEEDS_HUMAN 無人讀它，reset_complete 永不成立——卡到 19:33 使用者手動 `回礦` 才解。
- **一句話根因**：HARVESTING 的兩個收尾出口（giveup→NEEDS_HUMAN、success→MINING）都不看「重置 pending」——RESET_WAIT 因 chill 轉出後，重置這件事在狀態機裡蒸發；NEEDS_HUMAN 卡死（worker 不跑、無人清旗標），MINING 則會清旗標＋對已重置礦坑空挖，兩個出口都斷掉回礦鏈。
- **對策**：採集收尾時 `_mine_resetting` 快取為 True → 一律回 RESET_WAIT（比照 `_rr_abort_reset` 直接賦值＋`_on_enter`），讓既有 reset_complete → REENTRY 鏈接手：`_harvest_giveup` 不再誤發「請手動處理」（清 `_needs_human_extra_meta`）、`_resume_mining_tail` 不跑 init_mining。`states.decide_transition` HARVESTING 分支同步補 `mine_resetting` 檢查＋`_check_reset` 閘擴至 HARVESTING（worker 在該狀態不跑、凍結快取＝「進採集前重置已偵測」；RESET_WAIT/REENTRY/NEEDS_HUMAN 各分支不讀此旗標不受影響）。誤報 banner 的代價＝多走一次重置等待/回礦流程，安全方向正確。
- **回歸**：`tests/test_states.py`（收尾兩出口×重置 pending＋進行中不打斷，3 例）。
- **下輪實機驗證預期**：重置倒數中再遇 chill：`miningbot.log` 出現「採集放棄但礦坑重置 pending -> 回 RESET_WAIT（不交人工）」（或 success 版），隨後正常「重置完成→REENTRY」；不再出現「全方位掃描未找到追蹤框…請手動處理」後長時間停在 NEEDS_HUMAN。

## H052（2026-07-19 19:33~19:36 RR#7；H046(a) 餘波）：開場俯仰歸位四連發「疑似被吃」誤報——eaten 門檻誤用於冪等歸位的成敗判定

- **症狀**：RR#7 兩輪開場俯仰歸位 attempt1/2 全判「疑似被吃」（mean=4.64/0.66、2.34/0.18），Discord 連發兩次「⚠ 俯仰歸位疑似被吃；圖照發，角度可能偏」。trace 前後幀實錘：attempt1 before＝鏡頭貼暗土壁、after＝俯視紅棕地面——**歸位真的生效**；量測區（中央偏上 800×320）夜間兩幀都近黑把 mean 壓到 4.64 < 門檻 8.0。attempt2 的 0.66/0.18＝已歸位再重做、畫面本來就不變（冪等必然）。
- **一句話根因**：`pitch_eaten_*`（8.0/0.15）是 07-11 白天礦內兩側夾（被吃 ≤3.29 vs 生效 ≥32.5），夜間地表真動只有 0.93~5.13（H046(a) 實錄）落在「被吃」區間——mean/frac 兩訊號在暗場景下與真被吃**區間重疊、物理上不可分**；且歸位冪等，生效後重做幀差必近零，eaten 判定對歸位本身沒有意義。誤判的實害＝白拖一輪 ~20s、誤導警告、`pitch_ok=False` 跳過 `_pitch_offset_px` 記帳同步（回礦卡俯仰行/`上|下` 基準/`存檔` 值全脫鉤）。
- **對策**：開場鏈（`_rr_open_episode`）與 `歸位` 指令（`_rr_pitch`）的重試與成敗判定改認**凍結探針**（`probe_frozen`，H046 兩側夾：凍結 0.00/0.0000 vs 活著靜止 0.09/0.0004 vs 夜間拖曳後最小 0.93/0.018——本案全部樣本 0.18/0.0023 起皆穩在活著側）：非凍結＝歸位生效（不重試、不警告、記帳同步）；真凍結重試一次後由 `plan_opening_gate` 擋拍照（開場）/回「疑似被吃」警告（指令）。開場鏈舊「疑似被吃；圖照發」警告移除（新語意下不可達）。`pitch_eaten_*` 門檻本身不動——`仰角 上|下` 微調、挖礦歸位、旋轉驗證各呼叫端語意不同、照舊。
- **回歸**：`tests/test_main_pitch_home.py` H052 區塊（開場：暗場景低幀差＝成功＋記帳同步、真凍結重試後 gate 擋拍照；`歸位` 指令：暗場景 ✅、真凍結 ⚠，4 例）。
- **下輪實機驗證預期**：夜間/暗場景回礦開場不再出現「⚠ 俯仰歸位疑似被吃」Discord 訊息；`miningbot.log` 俯仰歸位量測行照落（mean/frac 供事後比對）；回礦卡俯仰行在開場後顯示 `夾限上 <back_px>px`（記帳已同步）。

## H053（2026-07-20 02:38~02:48 RR#7；使用者發現「容量 1% 卡死」）：開場容量閘門檻 0.0 太嚴——真重置完成後容量 OCR 穩定讀到 1%（非 0%）被判 capacity 永遠過不了閘

- **症狀（使用者回報＋log）**：RR#7 重置回礦，02:37:13 容量 OCR 讀到 1%、`🔔 容量已歸零（1% ≤ 10%）→ 鈴聲錄音窗開啟`，但 02:38:08 起到 02:48:30 連續 **17 次** `開場閘未過（capacity：...surface=True capacity=1.0）`——人已在地表、重置早已完成，卻因 `1.0 > 門檻 0.0` 恆成立、預算 300s 耗盡（02:41:42 第一次歸零、重啟後 02:46~02:48 再卡一輪），使用者 02:48:33 手動關閉 bot。
- **一句話根因**：H045 開場容量閘 `reentry_open_capacity_max_pct = 0.0` 是用「凍結舊幀 78% vs 真重置 0%」兩側夾出來的，但真重置完成後容量 OCR **不一定讀到 0%**——RR#7 穩定讀到 1%（遊戲顯示殘留／OCR 進位），`1.0 > 0.0` 恆成立 → `plan_opening_gate` 永遠回 `"capacity"` → 拍照鏈永遠進不去。同一幀的鈴聲路徑（`reset_chime_capacity_arm_pct = 10.0`，H045 使用者裁決）早已接受 1%——兩條路徑共享「容量 OCR 低值＝重置完成」這個概念，門檻卻飄移成 0% vs 10%。
- **對策**：`reentry_open_capacity_max_pct` 預設 `0.0 → 10.0`。兩側夾：真重置完成（地表）**0~1%**（H046 0%、H053 RR#7 連續 17 次 1%）vs 重置進行中（地表）**56~71%**（RR#2 01:33:38 讀 71%、01:34:04 讀 56%）vs 凍結舊幀 **78~100%**（H045 ep3）。10.0 與 `reset_chime_capacity_arm_pct` 同概念、兩側各 ≥10x 餘裕。函式本身不動（`plan_opening_gate` 早把門檻當參數傳），只改 Config 預設。
- **回歸**：`tests/test_reentry_remote.py::test_opening_gate_default_tolerates_post_reset_capacity_residual`（Config 預設門檻下：1%/0% proceed、56%/78% defer，兩側夾）。既有 H045/H046 閘測試（explicit 門檻 0.0）不動、仍全綠。
- **下輪實機驗證預期**：重置回礦輪 `miningbot.log` 容量讀到 1%（或 0%）時 `[RR#N] 開場閘未過（capacity...` 不再出現，直接進 sweep 拍照（`reentry_epN_dir*` 8 張方位圖）；僅在容量仍高（≥56%，重置未完成）時才續探。

## H054（2026-07-20 12:44，harvest 094；使用者發現「把過去的挖礦紀錄當成挖礦成功的信任」）：基準 OCR 落在聊天淡出時段——舊採集行重新顯示被計數差當成本次新增 → 假成功

- **症狀（使用者回報＋log）**：094 判 `verify harvest: gone=False rare [0]->[2] NEW special=True -> SUCCESS`，Discord 報採到 `Clovara 〔Exotic 1/5,456,545〕`＋`ionized Imbollyx`，但礦**根本沒挖到**（使用者 12:45:44 手動截圖：礦體仍立在原地、容量 59%）。鐵證兩條：(1) 追蹤框自始至終沒消失（`gone=False`）；(2) 開火前 `20260720_124447_..._094_d3_chat_before.png` 與開火後 `20260720_124456_..._094_d3_chat_after.png` **MD5 完全相同**（`8365F213D9A681A55A42480FB87079C4`）——聊天區跨越整發 D3 逐位元沒變＝這一發沒產生任何新聊天行。被當成「新增」的 6 條 has-found 全是開火前早就在畫面上的舊紀錄。
- **一句話根因**：episode 進場時凍結的 `_chat_baseline_crop`（`main.py` `State.HARVESTING` 進場）落在 **Roblox 聊天無新訊息 ~15s 整窗淡出隱藏**的時段，基準 OCR 只讀到常駐礦物面板文字 `NORMAL`、**0 條 has-found 行**（`rapid(baseline) 0.59s 共 1 行`）；sweep 那 ~25s 間事件 reroll 訊息抵達使聊天整段重新淡入（poll 讀到 10 行），**無錨點的計數差**信號（`has_new_rare_found` 0→2、`any_new_special_found`）遂把舊行重現當成本次新增 → SUCCESS。`ChatLedger` 早有等效規則（「上次讀取為空 → 只推進錨點、不計新增」）、兩個錨點信號（`_last_line`/`_tail`）也正確拒絕了，但 `confirmed` 是三者 OR——**帳本只能加分、無法否決**。
- **對策**：`ocr.baseline_saw_found_history(before_texts, found_keywords)`（新純函式，逐 pass 取聯集），在 `_verify_chat_ocr` 內當基準閘：基準沒讀到任何 has-found 行 → 兩個計數差信號一律不採信（記 WARNING `H054 基準閘`），帳本因自帶錨點照常生效（H032 晚到行仍救得回）。判準用「有沒有 has-found 行」而非「有沒有文字」——裁圖含左上礦物面板等常駐 UI，聊天全隱藏時仍讀得到那些字。方向照「寧漏勿假成功」：擋掉後 `gone=False` 走 RETRY 再射一次，礦還在、不損失。兩側夾（實機五場基準 has-found 行數）：**0 條**（081/091/093/094 四場皆聊天淡出）vs **10 條**（082 真成功，計數差正確確認 rare 1→2，閘後照樣 SUCCESS）。座標／門檻皆未更動。
- **回歸**：`tests/test_ocr.py` H054 區塊（隱藏/可見/逐 pass 聯集/全空基準＋「計數差在 094 確實回 True」的事故本體釘樁，6 例，原文取自 094/082 實機 trace dump）＋`tests/test_main_harvest_runtime.py` H054 區塊（隱藏基準擋下並記 WARNING、082 真成功不被擋、閘不得否決帳本確認，3 例）。
- **下輪實機驗證預期**：`harvest.log` 出現 `H054 基準閘：基準無 has-found 歷史` WARNING 時，同一輪**不得**再出現 `-> SUCCESS`，應改走 `RETRY`（框還在）或 `RESWEEP`（框消失）；反之基準讀得到歷史的輪次（`rapid(baseline)` 行數 ≥8）行為完全不變。grep 檢查：`Select-String 'H054 基準閘' harvest.log` 的每個 hid，其 `verify harvest:` 行 verdict 應為 RETRY/RESWEEP。

## H055（2026-07-20，harvest 082；H054 調查副產物，使用者當時裁決不在該輪範圍、問題本身確認存在）：常駐礦物面板 "NORMAL" 恆為聊天 OCR 最後一行 → 兩個抗捲動信號與 ChatLedger 錨點鏈結構性失效

- **症狀**：082 是一次**真成功**（`rare [1]->[2]`、Discord 正確報出採到的礦），但四個確認信號只有**計數差**活著。實機 trace dump（`20260719_012711_082_chat_ocr_success.txt`）顯示新增的兩行 `small_lo has found Weevil` 與 `small-lo-has-found-an ionized Starstride` 都插在 `NORMAL` **上面**，before/after 的最後一行同為 `NORMAL`。這不是機率性漏判、是**恆成立**：六份實機 dump 的 after 段最後一行 100% 是面板文字（`NORMAL` ×11；091 另有右側圖層面板 `Shamrock` ×2，殘留兩行）。
- **一句話根因**：`config.chat_region = Region(0,110,460,280)` 的下緣蓋到左上礦物面板標頭，`NORMAL` 每次都被 OCR 讀成最後一行 → (a) `has_new_rare_found_last_line` 的 `before_last == after_last == "NORMAL"` 恆成立、恆回 False；(b) `_align_tail` 的錨點恆對到 after 尾端的 `NORMAL`、tail 恆為空 → `has_new_rare_found_tail`（H032 對策）與共用同一 `_align_tail` 的 `ChatLedger` 錨點鏈一併失效。等於整套 verify 退化成單一信號，**而計數差正是 H054 假成功的來源**——H054 的基準閘擋掉計數差之後，faded-baseline 場次已無任何信號可用。
- **為何不縮短 `chat_region`（route b，實機量測否決，非保守估計）**：面板不是「在聊天下方」而是**疊在聊天上**。082 裁圖量測：面板白色圓角上緣在 y=**227**，最新 has-found 行的字身（量在無面板干擾的 x≥250 帶）在 y=**225..234** → 邊框橫穿字身（這也是該行被 OCR 讀成 `small-lo-has-found-an` 連字號的來源，H041 同型）。094 裁圖更極端：最新（淡出中）聊天行落在 y≈**240..255**，正是 `NORMAL` 白字帶（y=240..258）之內。故任何「停在面板上方」的裁法都會切掉真聊天行，`config.py` 對 `chat_review_region` 的「勿縮短高度否則漏掉最新 has-found」是實機事實。
- **對策（route a，純加法、零校準風險）**：`ocr._strip_ui_residue()` 在比對進入點 `_chat_lines()` 剝掉**尾端**常駐 UI 殘留行，讓錨點自然落回真正的最後一條聊天行；`has_new_rare_found_last_line` 與 `has_new_fuzzy_rare_found` 的底行路徑改走同一個 `_chat_lines()`。座標／`config.py` 完全未動。
  - **兩側夾**（6 份實機 dump 全部行）：UI 殘留＝**恰好 1 token**（`NORMAL`／`Shamrock`，13 筆）vs 真 found 行＝**≥3 token**（`has found X` 的結構下限；實測最短 `small_lo has found W` ＝4 token）。門檻取 `UI_RESIDUE_MAX_TOKENS = 1`。
  - **安全性可證、不只經驗**：`found_keywords = ("has found", "found a")` 皆為雙詞片語 → 任何 found 行必 ≥3 token → **1 token 行永遠不可能是 found 行**，剝掉它在數學上不可能剝掉成功信號。1 token 的真聊天行只有折行碎片（`Weevil`／`hasfound`／`Reminiscence!`／`30%!`），本來就 `_found_ore()→None`、對信號零貢獻。
  - **去黏後再數 token**：H041 型整行連字號黏連（`small-lo-has-found-an ionized Starstride`）若照空白切只有 3 token、全黏則 1 token → 必須先把 `-`/`=` 當分隔（`_token_count`），否則會誤殺**正是撐起 082 成功判定的那一行**。
  - **只剝尾端、遇第一個非殘留行即停**：中段折行碎片留著，`_align_tail` 的「向上連續吻合最長」比對不受擾。
- **連帶修補（剝殼暴露的既有破口，必須同批修）**：剝掉 `NORMAL` 後，聊天整窗淡出的場次基準會變成**真的空**，而底行信號舊版對「空基準」沒有防護——091 實錄的 after 底行剛好是稀有礦（`Starstride`），若不補防護會**憑空生出假成功**（舊版是靠 `"NORMAL"=="NORMAL"` 意外擋住的）。故 `has_new_rare_found_last_line` 與 `has_new_fuzzy_rare_found` 底行路徑加「基準無聊天行即棄權」，方向與 `ChatLedger`「上次讀取為空→只起鏈不計新增」及 H054 基準閘完全一致（寧漏勿假成功）。
- **修復前後實機六場對照**（`common_ore_names()` 全世界聯集）：

  | dump | last_line | tail | ledger | count | 基準閘 |
  |---|---|---|---|---|---|
  | 081 resweep | False | False | False | False | False |
  | 081 success | False | False | False | True | False |
  | **082 success** | **True**（修前 False） | **True**（修前 False） | **True**（修前 False） | True | True |
  | 091 success | False | False | False | True | False |
  | 093 success | False | False | False | True | False |
  | 094 success | False | False | False | True | False |

  082（唯一基準可見的真成功）從 1 個信號恢復成 4 個；四場 faded-baseline 的錨點信號全部維持 False、計數差仍由 H054 基準閘擋下＝**沒有引入任何新的假陽性**。
- **回歸**：`tests/test_ocr.py` H055 區塊（10 例，原文取自 082/091/094 實機 trace dump）——事故本體三條（底行／tail／ledger 在 082 應為 True）、剝殼正確性三條（091 雙殘留行、H041 黏連行不可被剝、3 token 折行碎片不可被剝）、安全方向四條（091 空基準不得經底行或 tail 確認、H054 的 094 不得復活假成功）。既有 H014/H020/H032/H041/H054 測試與 `tests/test_ocr_fixtures.py` 15 例實圖回歸全綠。
- **fixture**：沿用 H054 區塊已收錄的 082 原文（同一份 dump），新增 091 原文（雙面板殘留場景）。
- **下輪實機驗證預期**：`harvest.log` 的 `verify harvest:` 行，在**基準讀得到聊天歷史**的輪次（`rapid(baseline)` 行數 ≥8）應開始看到底行／tail／ledger 信號與計數差**同時**成立（修復前這類輪次只有計數差）；faded-baseline 輪次行為完全不變（仍走 H054 基準閘 → RETRY/RESWEEP）。反指標：若出現「基準只有 1 行（面板文字）卻判 SUCCESS」＝棄權防護失效，須立即回查。
- **commit**：2026-07-20 `fix(verify): 剝掉聊天 OCR 尾端常駐面板殘留行（H055）`

## H056（2026-07-20 16:20~16:22，harvest 097；使用者發現「所有備選全部都沒有偵測到」→ 追查後改判）：瞄準介面方位 0-7 vs 回礦介面 1-8——使用者看 `DIR 4` 的圖打 `5`，腳本轉到別的方位開火

- **時間線**：16:20:25 chill 觸發 → HARVESTING[097]；16:20:29~43 八方位 sweep 全 `no tracker` → giveup 交人工，Discord 發 9 個近失候選（分數 0.26~0.34，理由全為「形狀分不足」）；16:21:41~48 使用者回 `手動`，腳本重按 D2＋確認生效後拍八方位圖；16:22:21 使用者回 **`5 D2`** → `AIM 對齊：rot=-3（目標 dir=5）`；16:22:30 `AIM 重找全滅 -> 直接朝先驗點開火 (1120, 405)`；16:22:43 verify OCR 兩次只讀到 `'NORMAL'`、`confirmed=False` → 未採到；此後無人再回覆，16:35:49 防掛機 Space。
- **一句話根因**：**同一支 bot 的兩個指令面用了不同的方位編號基準**——回礦（`reentry_remote.py:92`「方位 1-8（2026-07-18 使用者要求 1 起算）；內部仍 0-based」）是 1 起算，瞄準（`remote_aim.parse_reply` 舊 regex `[0-7]`、疊圖標頭 `DIR {dir_idx}`）是 0 起算。使用者在回礦側養成 1-8 習慣，看到標頭寫 `DIR 4` 的那張圖（第 5 張）打 `5`，瞄準側解析成 `dir_idx=5` → 對齊到**另一個方位**的畫面 → 先驗格心落在該方位的空地上，重找當然全滅、盲開必空。
- **量測（實機幀，全部可重跑）**：
  - 使用者指的是對的：`097_manual_survey_dir4_manual.png`（標頭 `DIR 4 | MID`）中綠色追蹤框在 **(983, 435)**，`best_outline_score` = **0.613**（confirmed 門檻 0.42），落在 **D2** 格內（欄界 x=960、列界 y=540，框在界右上方）；距 D2 格心僅 **140px**。
  - 實際開火點 (1120,405) = `grid_cell_center('D2')` 精確值——**格線與解析都沒錯，錯的只有方位號**。
  - 開火幀（dir5）(540,481) 另有一個 edge=**0.586** 的框，距開火點 585px。
  - `parse_reply('5 D2')` 舊版回 `dir_idx=5`；`dir_label(4)==5` 說明使用者要的是 `dir_idx=4`。
- **對策**：**瞄準介面全面改 1-8，與回礦一致**。新增 `remote_aim.dir_label(dir_idx) -> dir_idx+1` 作為唯一顯示轉換點；`parse_reply` regex `[0-7]`→`[1-8]` 且回傳 `int(...)-1`（`0` 不再是合法方位）；候選總表 `DIR{n}`→`方位{n+1}`、續組 caption 同步；`MANUAL_SURVEY_HELP` 明示「方位 1-8，同回礦介面」；兩處疊圖標頭（`_render_aim_shots`、`_execute_manual_survey`）改印 `dir_label`。內部 `dir_idx` 一律維持 0-based，轉換只發生在 `dir_label` 與 `parse_reply` 兩處。
- **同輪一併修的兩個下游缺口（原本誤判為主因，保留因為確實是問題）**：(1) `build_aim_context` 無空間去重——097 DIR1 三筆 `(569,924)/(534,952)/(570,951)`（相距 27~45px、同為 0.34）是**一塊角色紅武器＋彩虹碎片衣裝**被 HSV 切成三個 blob，吃掉 9 個名額中的 3 個 → `_dedup_rejects` 同層同方位 <`remote_aim_dedup_radius_px=60` 合併留最高分（60 < 框寬 100~207px）。(2) `_execute_remote_fire` 重找只看先驗點 ±`remote_aim_refind_radius_px=160`，全滅即盲開 → 加全畫面兜底（`remote_aim_fullframe_fallback`），只認 0.42 confirmed 門檻、刻意不帶 `reference_bgr`（替代方案是盲開，且 preexist 差分會剔掉掃描前就在畫面上的真框）。
- **回歸**：`tests/test_remote_aim.py`（H056 編號釘樁：`5 D2`→`dir_idx 4`、`dir_label(4)==5`、八方位 label/parse 互逆、`0 C3`/`9 C3` 皆拒；去重 5 例）＋`tests/test_main_aim_fullframe.py`（4 例）。既有 parse/顯示測試的期望值由 0-based 改 1-based——**這是刻意的契約變更，不是放寬**；`test_cap_max_candidates` 合成座標間隔 10px→100px（該例驗上限，不應被去重干擾）。
- **下輪實機驗證預期**：Discord 疊圖標頭與候選總表的方位號**與使用者該輸入的數字一致**（標頭 `DIR 5` ⇔ 打 `5`）；`miningbot.log` 的 `AIM 對齊：…（目標 dir=N）` 中 N 應等於使用者輸入減 1；候選清單不再出現同方位相距 <60px 的重複編號；ROI 落空時出現 `AIM 全畫面兜底命中 edge=… （距先驗點 …px）`。
- **未解／不擋結案**：(a) **偵測器在 DIR4 手動圖上的全畫面最佳命中是 (959,547)＝角色的臉（0.613），不是 (983,435) 的真框**——候選排序取 `colored_frac` 最高者，角色飽和衣裝/膚色可壓過真框；這代表全畫面兜底在角色遮擋場景可能打到角色身上，是**新引入的風險**，需另案處理排序準則（改用 edge 排序或加角色區抑制）。**→ 已由 H057 修復**：臉的 0.613 其實是「借」了 320px ROI 內真框的分數，confirmed 重錨後座標回到真框本身。(b) 近失外露閘仍是純 `colored_frac > 0.40`，衣裝洗版的**來源**未修（只修了重複計數）；改 colored＋edge 雙條件可能誤殺薄暗小框（edge 0.19~0.22 族），需備 fixture 兩側夾後單獨處理。(c) sweep 的 dir5（16:20:38）與開火時的 dir5（16:22:30）構圖差異極大，姿態記帳已核對自洽（giveup 回轉 net=7 → 手動掃 8 次 ≡ 0 → rot=-3 ≡ dir5），推測為 camera collision 解算差異，證據不足以定裁。(d) 八方位 sweep 在鏡頭卡進角色特寫時整輪全空的問題完全未動——本案修正只把「人工介入後仍失手」變成「人工介入會中」，不減少交人工次數。
- **調查過程的教訓（方法面）**：前兩輪分析先後誤判為「使用者指到空地」與「ROI 半徑不足」，兩次都是**從候選清單反推使用者意圖、未向使用者求證所看的圖**所致——第一次把 `5 D2` 誤認成候選⑥的 D4（D4 格心 (1120,945)，與實際開火點差 540px，本可立即否證）。**指令類事故必須先確認「使用者看到的那張圖」與「使用者輸入的原文」兩項一手證據，再談偵測門檻。**

## H057（2026-07-20，harvest 097 事後追修；源自 open-detection-issues.md D01/D02）：綠框貼受光綠牆被輪廓黏連吃掉＋角色的臉「借」隔壁真框的形狀分數勝出

- **症狀**：097 dir4（手動重掃圖與 sweep 幀皆然）畫面上有肉眼明顯的亮綠追蹤框 `(983,435)`，但 `find_tracker` 全畫面回傳 `(959,547)`＝角色的臉（edge=0.61 判 OK）；真框附近 ±70px 連一行候選 log 都沒有——它在 HSV 輪廓階段就出局，形狀確認根本沒跑到。097 的八方位 sweep 也因此全空 → giveup 交人工（見 H056 時間線）。
- **一句話根因（兩條，一體兩面）**：
  1. **黏連（D01）**：追蹤框與它身後**同色系、被照亮的綠牆**被 `cv2.RETR_EXTERNAL` 接成同一條輪廓（bbox `493x85`、area `14620`），而 area 閘 400~5000 與 bbox 閘 18~80 是照「孤立小框」設的 → 整塊被 `continue`，真框進不了候選池。
  2. **借分（D02）**：H040 把 shape ROI 撐到 320px 後，臉候選 `(959,547)` 的 ROI 把 114px 外的真框包了進來——`best_outline_score` 只回分數不回命中位置，`exquisite_tracker_real` scale=1.0 命中中心換算回全幀正是 `(983,435)`。**分數是真框的、座標是臉的**，confirmed 就記在臉頭上。
- **量測（兩側夾，全部可離線重跑）**：
  - 分離信號：框芯 V=**222** vs 受光牆帶 V=**72~76** vs 一般綠背景 V=20；框自身右下角暗部 V=22（全域拉高 V 下限會殺暗框，已否決）；「S>200 且 V>200」亮芯 mask 會把框打碎到 area<400（已否決）。
  - 救援參數：`v_min` 100~180 都能在爆閘輪廓 bbox 內分出正中 `(983,435)`、area 552~600 的碎片 → 取中值 **150**；`area_min=120`（碎片 552 vs 更小牆面亮點）。負樣本側：紅緞帶/裝備兩場景＋097 其餘 7 個 sweep 方位，救援碎片 edge 全部 0.26~0.34 < 0.42 → 0 個 confirmed。
  - 重錨偏移：真框 confirmed 的「候選中心↔命中中心」偏移比 `dist/max(tw,th)` 實測 0.00~0.32（red_square 大框 0.10~0.32）；借分的臉是 **1.68**。連帶發現 072 `post_success_second_tracker_scene` 歷史測試釘的 `(1097,475)` 其實是 HSV 偏移中心（借了 96px 外真框的 0.61），畫面上唯一的框（黃色尖刺太陽）在 **(1043,555)**（人工目視裁圖確認）——期望值已按 ground truth 修正。
- **對策**（`vision.py`；參數進 `Config.tracker_rescue_*`）：
  1. **confirmed 重錨**：`best_outline_match` 連命中中心一起回傳；confirmed 候選座標一律搬到形狀命中處（命中點出界／落排除區時保留原座標，不比舊行為差）。log 帶「（重錨自(x,y)）」。
  2. **超大輪廓救援**：爆 area/bbox 閘的輪廓不再直接丟棄，記下 bbox；**confirmed 全滅時**回頭在這些 bbox 內用 `V ≥ tracker_rescue_v_min(150)` 子 mask 二次分割，碎片過寬鬆閘（area ≥ 120、bbox 12~80、同長寬比閘、同 preexist 差分、去重 60px、上限 12 個）後**只走形狀 confirmed 路徑**——不進 survivor/純 HSV 排名、不進近失外露清單（垃圾碎片不洗版，D03 教訓），救回與否全由 edge 0.42 裁決，不放寬任何全域色域門檻。
- **影響範圍**：這條是「全八方位掃描全空」的一大來源——綠世界整片是綠的，綠色階級的框貼上任何受光綠面就消失。**097 的 sweep dir4 幀經救援後直接命中 (983,436) edge=0.62——那次 giveup 本可完全避免**；這也部分削弱 H056 未解 (d)「鏡頭特寫害整輪全空」的敘事：至少 dir4 的漏是黏連造成，不是看不到。H056 未解 (a)（全畫面兜底可能打臉）由重錨一併修復：臉候選現在會被錨回真框。
- **回歸**：`tests/test_vision.py` H057 六例——實機 manual 幀（全管線命中真框＋不得回臉）、重錨隔離（關救援仍中）、實機 sweep 幀（當時 giveup 的那幀）、合成黏連救援隔離（無救援必 None／開救援必中）、合成純牆負樣本、紅緞帶裝備負樣本。fixture 依現行契約放追蹤的 `tests/fixtures/tracker/h057_green_on_green_{manual,sweep}.png`。
- **下輪實機驗證預期**：綠世界 sweep 遇黏連時 `harvest.log` 出現「`超大輪廓救援：oversized=N -> 救援候選=M`」後接 `shape確認(救援)`；借分場景出現「`shape確認 … -> OK（重錨自(x,y)）`」且開火座標為重錨後座標；「全方位掃描未找到追蹤框」giveup 頻率在綠世界應可見下降。
- **未解／不擋結案**：D03（近失外露閘 colored+edge 雙條件）維持暫緩——誤收側（裝備 edge 0.20~0.38）與真值側（薄暗小框 0.19~0.22）在 edge 軸重疊，兩側夾不出來；可能的分離信號是 ring_ok（097 裝備全為 False），需薄暗小框 fixture 量 ring_ok 佐證後另案。D04（同方位跨時點構圖漂移守門）、D05（鏡頭特寫遮擋）續留 open-detection-issues.md。

## H058（2026-07-20 12:20~21:19 RR#8~12；使用者回報「容量還沒到 10 就不停嘗試自動回礦、卡頓又不成功」）：REENTRY 起跑太早——重置第二階段（容量 60~76% 排到 ≤門檻）收尾中即開跑，每 20s 一輪 click+pitch+OCR 卡在卡頓裡被吃

- **症狀（使用者回報＋log）**：RR#8~12 五場重置回礦，REENTRY_START 起跑（reset banner 消失＋`reentry_reset_settle_s` 5s 沉澱）瞬間容量 OCR 還在 60~76%（RR#8 12:20:48 讀 65%、RR#9 13:03:06 讀 67%、RR#9 15:53:09 讀 70%、RR#10 19:34:47 讀 63%、RR#12 21:18:14 讀 76%）。隨後 `[RR#N] 開場閘未過（capacity：...）` 每 ~20s 一輪，容量一路排 65→23、67→30、70→61→20、63→34→13、76→56→28，持續 ~90s 直到 ≤10% 才放行（RR#12 21:19:42 讀 8%→🔔 鈴聲窗→sweep）。每輪都跑完整「按回到地表＋俯仰歸位＋OCR」——RR#12 21:18:52 pitch mean=5.62 判「疑似被吃」、21:19:50 zoom 鍵 o 判「疑似被吃」。
- **一句話根因**：`_update_reset_complete`（main.py）觸發條件是「`_mine_resetting` banner 旗標消失＋5s 沉澱」，但遊戲重置有**第二階段**——banner 倒數結束（容量 100%）後容量還要 ~90s 才排到 0~1%（H053 實測真完成）；banner 消失那一刻容量仍在 60~76%。REENTRY 在收尾中途起跑，`_rr_open_episode` 的「回到地表點擊＋俯仰歸位」對「等容量排掉」毫無幫助、又全卡在收尾卡頓裡被吃（H052 的 pitch_eaten 誤判家族再犯）；H053 的 `reentry_open_capacity_max_pct=10.0` 只在「點擊＋拖曳之後」才檢查容量，動作早已發生。
- **對策**：(1) `reentry_open_capacity_max_pct` 預設 `10.0 → 5.0`（使用者裁決：5% 以內才算重置夠乾淨）。(2) 新增純函式 `reentry_remote.capacity_blocks_opening(trigger, cap, max_pct)`，在 `_rr_open_episode` 點擊「回到地表」**之前**預檢：`trigger=="reset"` 且容量 > 門檻 → **不點擊、不拖曳**，只被動 OCR 容量＋推進鈴聲錨（`_maybe_arm_chime`，維持 reset_chime_capacity_arm_pct=10.0 原行為），由 `plan_open_retry` 每 20s 再探；容量 ≤ 門檻才進入既有的「點擊→俯仰→狀態閘」鏈。手動回礦（trigger!="reset"）、讀不到（None）皆不擋（後者交回 `plan_opening_gate` 的 capacity_unread 分支）。`_rr_ctx.attempt` 只在真正點擊那輪 increment（收尾等候不計）。兩側夾沿用 H053 證據：真完成 0~1% vs 收尾中 56~71% vs 凍結 78~100%，5.0 兩側各 ≥4x 餘裕。
- **回歸**：`tests/test_reentry_remote.py::test_capacity_blocks_opening_reset_drain`（收尾 28/56/65/76% 阻塞、≤門檻 0/1/邊界放行、manual/None 不擋）＋`test_capacity_blocks_opening_two_sided_clamp`（0/1 放行、56/71/78/100 阻塞 兩側夾）。既有 H053 測試（Config 預設下 1/0 proceed、56/78 capacity）在 5.0 下仍全綠。全套 996 例綠。
- **下輪實機驗證預期**：重置回礦輪 `miningbot.log` 先出現一連串 `[RR#N] 開場前容量 XX% > 5%（重置收尾中）——不點擊不拖曳，20s 後再探`，其間**不再**夾雜 `[RR#N] 俯仰歸位`／`開場閘未過（capacity` 行（這些只在容量降到 ≤5% 後才出現一次、隨即 sweep）。舊門檻 10 會放行的 8% 讀值仍會等候到 ≤5%。grep：`Select-String '開場前容量' miningbot.log` 的每個 episode，其後第一個 `reentry_epN_dir1`（sweep 拍照）應在讀到容量 ≤5% 之後；`俯仰歸位` 出現次數應遠少於舊版（收尾等候期不再每輪拖曳）。

## H059（2026-07-20 設計、2026-07-21 更正確認；使用者回報「回礦轉到的方位跟圖上的對不起來，而且大約一半場次才發生」）：每一輪 attempt 都按「回到地表」＝遊戲隨機化 yaw，`restore_view` 把偏移正確扣回了一個**隨機基底**

- **症狀**：回礦八方位 sweep 選定方位後，實際轉到的朝向與快照對不上；使用者獨立實測**約一半**場次發生（另一半正常）。
- **一句話根因**：`_rr_open_episode` 每輪 attempt 都執行 `ic.click_at(*cfg.reentry_surface_button_xy)`＝按「回到地表」換重生點，而遊戲換重生點會**隨機化 yaw**（`docs/superpowers/specs/2026-07-08-mine-reentry-design.md:18` 早有記載「隨機旋轉只亂 yaw」）。於是 sweep 的 `cur_dir=0` 基底＝該輪隨機 yaw、不是挖礦原視角；`b9f7783` 的 `restore_view(ctx.cur_dir)` 把使用者的方位偏移**正確**扣掉了，扣回去的卻是那個隨機基底 → 落在直角或對角各約一半。僅 attempt 1 例外（未經 reroll，基底＝挖礦原視角）。記帳（`cur_dir`／`net_rotations`）無法補救：沒有絕對 yaw 感測器。
- **⚠ 調查期間的錯誤與撤回**：`06e782a` 曾宣稱「ledger 證明 ep10/ep11 從未 reroll ⇒ 根因失效」並據此否證整份設計文件，**該結論錯誤、已撤回**。錯因是混淆兩種 reroll：ledger `log[].kind == "reroll"` ＝**使用者手動**下的 `重骰`／🎲；`ctx.attempt` ＝**bot 自動**的每一輪嘗試，而每輪都按一次「回到地表」——`config.py:276`（`reentry_max_attempts` 註明「reroll 上限」）、`_rr_ensure_ctx` docstring、`main.py` 每輪的 surface-button 點擊三處明證。ep10/ep11 的 `attempt=4` 正表示重生點已換過 4 次。**教訓：只驗一處就推翻整份設計文件是錯的做法。**
- **量測**：使用者實測發生率 ~50%，與「轉回隨機基底、直角/對角各半」的預測一致。`config.py:279-281` 的既有兩側夾亦佐證換重生點是既有已知動作（真傳送穩定值 ≥19 vs 地表→地表換重生點最低 26.8）。
- **對策（現況：緩解，非自動修正）**：(1) Discord `轉` 指令遠端手動轉 45°（`main.py` `_rr_turn` 鏈；輪詢執行緒只寫旗標、送鍵在主迴圈）。(2) `Config.reentry_yaw_sample_sweep`（預設關）成功收尾後原地拍八方位收語料（`main.py::_rr_yaw_sample`，須在回正之後；label 見 `harvester`）。**尚未寫任何自動判向門檻**——語料目前 100% 單層（Lucernia＋Shamrock＋夜晚）且缺「斜挖」負樣本，寫門檻等於不可否證；坑道是 bot 自己挖的，自指、不含世界軸資訊，LIMIT 徽章／層名牌是螢幕空間 UI 不可當世界物件判朝向。
- **回歸**：`tests/test_reentry_yaw_sample.py`。
- **結案條件（未達成）**：要有跨世界／跨層／含斜挖負樣本的語料，才談得上自動判向；在那之前 `轉` 指令是唯一正解。相關文件：`docs/superpowers/specs/2026-07-20-reentry-yaw-reroll-random-design.md`、`2026-07-21-reentry-yaw-investigation-findings.md`（更正版）。

## H060（2026-07-22 01:43／02:55／18:59 三次 REENTRY＋17:48 一次 NEEDS_HUMAN；使用者回報「回礦階段等約 30 分鐘就自己跳出 spawn chill，而且 spawn chill 只有在回礦時才會出現」）：bot 自己的防掛機 Space（原地跳）音效被認成 chill——自製假觸發迴圈

- **症狀（使用者回報＋log）**：REENTRY 等指令期間，約 30 分鐘後憑空跳出「spawn chill！稀有礦在刷新預設方塊」通知。當日 `events.log` 共 4 筆 `SPAWN_CHILL`（audio 0.25／0.38／0.25／0.37），其中 3 筆 REENTRY、1 筆 NEEDS_HUMAN；三次 REENTRY 的通知**全部**發生在 `防掛機：按 Space` 之後 **2 秒**（01:43:29→31、02:55:05→07、18:59:26→28），分數尾巴各維持到按鍵後 +4s／+5s／+4s。04:32 暫停後更露骨：`snapshots/audio/audiochg_*` 自 04:47:22 起連續 7 小時鎖在 **15.00 分整數格**（HH:02:22／17:22／32:22／47:22）、分數穩定 0.37，與 `防掛機：按 Space（暫停中等超過 15 分鐘）` 逐筆對齊。
- **一句話根因**：兩層疊加。**(1) 觸發源**——`antiafk_interval_s`（900s）在等待狀態（暫停／NEEDS_HUMAN／RESET_WAIT／回礦等指令，見 `run()` 的 antiafk 分支）每 15 分鐘按一次 Space 保活，角色原地跳的音效被 WASAPI loopback 收進 chill 偵測器；`_antiafk_last` 進等待狀態歸零 → 第 1 次按在 +15 分（不觸發）、第 2 次在 +30 分（觸發），這就是使用者說的「約 30 分鐘」。**(2) 分數為何夠高**——2026-07-21 校準（ae3bd16）把 7 個 `audiochg_*`（chill 的**上升緣**錄音）收成參考，`loudest_window` 抽「最大聲的 1.0s」時上升緣窗裡 chill 還沒到、抽到的是背景音（與 H040 同型污染，只是來源是上升緣）；其中 `chill_audiochg_20260721_134004_s27_TRIG` 把跳躍音從 **0.176~0.180 推到 0.37~0.58**（22 筆相位鎖定跳躍音有 19 筆越過 0.25 門檻，兇手佔 19/21）。ae3bd16 的 `would_false_trigger` 守門沒擋下，是因為當時可用的負樣本語料只有 0.18 那個舊變體，07-22 起的高分變體在校準之後才出現。
- **為什麼只在回礦看得到**：兩個獨立條件恰好同一交集——`states.should_notify_spawn_chill` 只在 NEEDS_HUMAN／REENTRY 發通知（MINING 遇 chill 是直接轉 HARVESTING），而防掛機**只在等待狀態按 Space**（挖礦中不按）。所以同一個假觸發在挖礦時根本不會發生，使用者只會在回礦看到它。同日 102／103／107 的「全方位掃描皆空」giveup **不屬於**這條路。
- **對策**：(1) 新增純函式 `audio.chill_muted_after_antiafk(pressed_at, now, mute_s)` ＋ `Config.antiafk_chill_mute_s=6.0`；`_antiafk_tick` 在**真的按下** Space 當刻寫 `_antiafk_pressed_at`（不可用進函式時的 now——失焦時 `_focus_roblox` 會先花 ~1.3s），`observe()` 在窗內把 `chill_audio` 壓成 False 並記一筆可診斷 log（每次按鍵只記一次）。窗長 6.0s 取自實機分數尾巴 +5s 再留邊際，佔保活週期 0.67% 且只在等待狀態發生。這是唯一一種 bot 知道確切發生時刻的音源，用時間窗排除比調參考集可靠。(2) 移除 7 個 `chill_audiochg_*` 上升緣參考（構造上污染；34→27）。保留 `chill_101`——它對跳躍音中位數僅 0.217、22 筆中只 1 筆越線，卻是撐住 104/105/106 真 chill 的主力（0.433，拿掉後掉到 0.311）；那唯一一筆殘留由靜音窗確定性擋掉。
- **兩側夾（decimate=8；負樣本＝04:47~11:32 相位鎖定的 22 筆跳躍音，正樣本＝當日有聊天證據的真採集 104/105/106）**：34 參考 → 跳躍音 **19/22 越門檻**、最高 0.481；27 參考 → **1/22**、最高 0.266、真 chill 0.340~0.433；再拿掉 chill_101 → 0/22、最高 0.180，但真 chill 掉到 0.308~0.340。取 27 參考＋靜音窗。
- **回歸**：`tests/test_main_antiafk_chill.py` 五例（窗內壓制／窗外照常觸發／從未按過不影響／靜音 log 每次按鍵只一筆／`_antiafk_tick` 錨點是按下當刻）——抽掉 main.py 修改後其中 3 例確實變紅。`tests/test_audio.py` 六例純函式邊界（含預設窗長須涵蓋 +5s 且 <保活週期 1%）。`tests/test_add_chill_ref.py` 兩例守門回歸，fixture `neg_antiafk_jump_s37.wav`（跳躍音現行變體）＋`contaminated_rising_edge_101.wav`（上升緣污染裁片）：確認該裁片會把跳躍音推到 0.375 且必被 `would_false_trigger` 拒收——防止 `--scan` 再把它收回參考集。
- **下輪實機驗證預期**：`miningbot.log` 中每一行 `防掛機：按 Space` 之後 6 秒內不得再出現 `chill 觸發`；若跳躍音仍達門檻，該處改出現一行 `chill 靜音（音訊 X）：防掛機 Space 後 6s 內，判定為原地跳音效`。`events.log` 的 `SPAWN_CHILL` 應歸零（除非真的是刷新在預設方塊的稀有礦）。反指標：若出現「按 Space 後 6~15 秒」的 chill 觸發，代表窗長不足；若真 chill 漏抓（有聊天新稀有礦卻無 `chill 觸發`），代表 27 參考的正樣本側不夠、需用 104/105/106 實錄補參考而非放寬門檻。


## H061（2026-07-26 10:31／10:43／11:19 三次啟動；使用者回報「只挖 D1、遙控器沒出來、log 停住」）：web UI 整合後的啟動「卡死」其實是 **bot 執行緒無聲死亡**——實機直譯器沒裝 uvicorn，pythonw 沒有 stderr，traceback 整個蒸發

- **症狀（使用者回報＋log）**：只挖 D1（`init_mining_sequence` 已按下 W＋左鍵並持續）、D2/D4/D5 常駐效果消失、遇稀有礦不進採集流程、HUD `last_action` 停在「俯仰歸位（挖礦標準角）」、Discord 遙控器從未出現、log 停在 web 模組 import 那行之後不再增長。
- **一句話根因**：`Bot.run()` 跑在 daemon thread，舊碼在那裡才 deferred import web 模組；實機用 `啟動挖礦bot.bat` → `pythonw -m miningbot` ＝ **Microsoft Store 版 Python**，跟 `uv sync` 灌的 `.venv` 是兩個環境，那顆直譯器有 numpy/cv2/rapidocr/pyaudiowpatch/mss/pydirectinput 卻**沒有 fastapi/uvicorn/starlette** → `ModuleNotFoundError` 在 worker thread 拋出 → pythonw 沒有 console，Python 預設的 `threading.excepthook` 把 traceback 印到不存在的 stderr → **整個失敗蒸發**。上述症狀全是「執行緒早就死了」，不是卡住。
- **⚠ 調查期間的錯誤與撤回**：先前判定「多執行緒同時 deferred import C 擴展 → import lock 死結」（見 `docs/superpowers/handoffs/2026-07-26-h061-web-ui-startup-hang.md`），**該結論是錯的**。之所以能自圓其說，是因為 mini repro 一律用 `uv run` 跑（venv 有 uvicorn，import 得起來）——**整條調查比對了錯的直譯器**。教訓：查實機問題第一件事＝確認 production 與重現環境是不是同一顆 Python。
- **量測／驗證**：Store Python 直接 import → `WEB_IMPORT_ERROR` 帶直譯器路徑、`web_server_enabled` 自動 False；`pythonw -m miningbot` 啟動 → log 一路寫到 `bot started`（先前完全沒有這行），再乾淨地在 focus 檢查失敗處退出、process 無殘留。
- **對策**（三個 commit）：
  - `de1f4c4`：(1) `status_hud._run_bot_guarded` 包住 bot 執行緒——未捕捉例外寫 log fatal＋traceback、寫進 HUD、crash 時先彈錯誤框再收視窗（**最重要的一項**，有它 H061 是 30 秒定位的問題）。(2) `main.py` 檔頭 web 預載改成吞 `ImportError` 降級（記 `WEB_IMPORT_ERROR` 含直譯器路徑、關掉 `web_server_enabled`），挖礦照跑、介入退回 Discord——直接讓 ImportError 往上拋會變成「連 bot 都開不起來」，比原問題更糟。(3) 降級不靜默：log WARNING 講明缺什麼、缺在哪顆直譯器，Discord 啟動訊息帶一行網頁 UI 狀態。
  - `a94888e`：web 依賴裝進 Store Python 後第一次真的走到 `WebIPCThread.start()` 就炸——`uvicorn/logging.py` 的 `DefaultFormatter` 無條件呼叫 `sys.stdout.isatty()`，pythonw 下 `sys.stdout is None` → `AttributeError` → `ValueError: Unable to configure formatter`。修法：`uvicorn.Config(log_config=None)`（uvicorn logger 直接 propagate 到 root，由 `diagnostics.setup_logging` 收進 `miningbot.log`）＋ `run()` 的整個 WebIPC 區塊包 try/except（失敗就清空三個 web 屬性、全面退回 Discord；半死不活的 `_web_thread` 比沒有更危險）。⚠ 這發生在 **`uvicorn.Config` 建構時**，不是 import 時——handoff 驗過「import 時 dictConfig 0 calls」，結論正確但毫無保護力，因為呼叫點根本不在 import。
  - `e36502b`：`Bot.__init__` 緊接 runtime log directory 印一行 `interpreter: <sys.executable>`（H061 的預防針）。
  - 續集（同批）：裸 `uvicorn` **不含任何 WebSocket 實作** → `GET /ws` 回 404、介入面板恆斷線、fallback 恆 True；`pyproject.toml` 顯式宣告 `websockets>=12`（不可靠 extras 順帶）。`TestClient.websocket_connect` 是 in-process shim，測不出這一類；真 socket 測試在 `tests/test_web_server_real_socket.py`。
- **回歸**：`tests/test_startup_import_order.py`（模組層 import 順序＋降級路徑）、`tests/test_status_hud.py`（crash 必留 log/彈框）、`tests/test_web_server*.py`（`log_config=None`、`sys.stdout=None` 下 bind、WebIPC 區塊包在 try/except）。
- **千萬別做**：不要把 web 模組改回 deferred import／lazy import——缺件會再度變成 worker thread 內的無聲死亡。`_run_bot_guarded` 與 `run()` 內 WebIPC 的 try/except 兩道防線也別拆。

## H062（2026-07-28 01:07~01:08，harvest 118；使用者回報「掃描階段中途 D2 目標框就已經消失了，也沒有補充」）：sweep 中途補 D5 導致 FOV 全域收縮/展開，舊 ref 對不上新畫面，剩餘方位與緊接的重掃全部系統性落空

- **症狀（使用者回報＋log／截圖）**：118 進 HARVESTING 後首輪 sweep 於 01:07:27 在 dir0 找到穩定框（edge=0.38，pos=(1026,578)）；01:07:45 `actions.log` 出現 `[118] harvest: boost 消失 -> 立即補 D5（FOV 守門）`（`_harvest_boost_guard` 在 sweep 迴圈第 6 個方位觸發）；掃完 8 方位、轉回 dir0 verify 該框時，01:07:57 `harvest.log` 記 `[118] sweep verify lost target at abs_dir=0 prior=(1026, 578)`——分數已 accepted 的框憑空消失，判「看過穩定框但 verify 失敗」→ 呼叫 `_reharvest_sweep()` 重掃一次（上限 1 次，H019）；01:08:02~01:08:25 第二輪 8 方位**全部** `no tracker`，giveup 交人工。**視覺證據**：`118_sweep_accepted_dir0_1026_578.png`（01:07:27）角色近景、清楚可見紅圈追蹤標記；`118_sweep_empty_dir0.png`（01:08:25，同方位）鏡頭明顯拉遠、角色縮小數倍、紅圈消失——不是框真的不見，是 FOV 縮放把它的螢幕座標整批搬走了。
- **一句話根因**：`_harvest_boost_guard` 補 D5 是**全域 FOV 收縮/展開**（docstring 早有記載：「D5 到期會以畫面中心為錨收縮 FOV（~2.6x 縮放），所有螢幕座標整批外推」），但它在 `_sweep_for_tracker` 迴圈中途觸發時，迴圈仍沿用呼叫端傳入、在**舊 FOV** 下拍的 `ref`（背景排除基準）——觸發之後的每一次 `_find_tracker`（含掃完後的最終 verify）都拿舊 FOV 的參考跟新 FOV 的畫面做像素差分，結構性錯位；緊接著的 `_reharvest_sweep()` 依 H026 對策**刻意**不重拍 `_pre_scan_ref`（避免把畫面上的活框拍進排除基準），於是連補救的那一輪也繼續套用同一份跟現實對不上的 ref，8 方位注定全空。
- **量測**：boost guard 觸發時間點（01:07:45）精確落在 `actions.log`；觸發前後兩張同方位（dir0）截圖的角色像素尺寸差數倍（FOV 縮放的直接視覺證據，非門檻量測——這條事故不動任何 vision 分數門檻，是狀態機/時序修復）。
- **對策**（`miningbot/main.py`）：`_sweep_for_tracker` 迴圈內若 `_harvest_boost_guard` 回 True，記旗標 `self._sweep_fov_shifted = True`（每輪 sweep 開頭重置為 False）；`_tick_harvest` 的 RESWEEP 分流讀這個旗標，決定要不要在 `_reharvest_sweep` 裡重拍 ref。`_reharvest_sweep` 新增 `refresh_ref: bool = False` 參數：True 時比照**進場邏輯**（`_on_enter` HARVESTING）的既有安全時機——先確認 D5/FOV 已展開，在**按下 D2 之前**重拍（此刻理論上不會有 D2 高亮的活框，跟入口拍 ref 同一個安全窗口，不是隨便挑一幀）；False（預設）維持 H026 既有行為完全不變，不碰 ref/畫面。旗標只在「本輪 sweep 內確實補過 D5」時立起，跟「verify 失敗但原因不明」的一般情形區分開——不擴大 H026 的例外範圍。
- **回歸**：`tests/test_main_harvest_runtime.py` 四例——`_sweep_for_tracker` 補過 D5／沒補過 D5 兩種旗標結果（用 118 第二輪「全 8 方位 no tracker」的真實形狀重現）；`_reharvest_sweep(refresh_ref=True)` 確認重拍發生在 boost guard 之後、`_run_scan`（按 D2）之前，且事後旗標清空；`refresh_ref=False`（預設）確認完全不碰 `capture.grab`／`_harvest_boost_guard`，既有行為零改動。全套 1815+ 通過，ruff clean。
- **下輪實機驗證預期**：harvest 的 `sweep 看過穩定框但 verify 失敗...-> 重掃一次` 那行，若同輪掃描期間 `actions.log` 出現過 `harvest: boost 消失`，訊息尾端應多印 `（本輪掃描中補過 D5，重拍 ref）`；緊接的重掃**不應**再像 118 那樣 8 方位全空機率偏高（樣本數不足以定門檻，需累積多輪對照）。反指標：若「補過 D5」的重掃仍常態性全空，代表 refresh_ref 重拍的時機本身還是抓到了活框（H026 風險兌現），需要另外找更安全的重拍窗口，而不是回頭放寬偵測門檻。

## H063（2026-07-28 14:09 啟動；使用者回報「每次初始化都會把左上角的聊天框關起來」）：H047 的「關」判定沒有下界——補丁被暗色浮層蓋住讀到 41.0 也算「關」，於是對著看不見的圖示連點 3 次 toggle，把開著的聊天框關掉

- **症狀（使用者回報＋log）**：啟動前聊天框是開的，跑完環境檢查就變關。`miningbot.log` 14:09:23~28：`聊天圖示空心，點擊開啟（probe=41.0）` → `仍空心，第 1 次重試（probe=41.0）` → `第 2 次重試（probe=41.0）` → `聊天框未開啟（state=closed, probe=88.2）`。
- **一句話根因**：`vision.chat_icon_state` 的關值判定是 `mean <= chat_icon_closed_max_gray(130)`，**沒有下界**；41.0 遠低於實測關值整段（81..94）代表補丁根本沒照到圖示（靜態暗色浮層／別的視窗蓋在左上角），卻仍被判成 `closed` → `plan_chat_open_action` 連發 3 次點擊（`chat_open_max_retries=2`）→ **奇數次 toggle**：開→關→開→關，剛好把使用者開著的聊天框關掉；第 4 次讀（浮層已消失）拿到真圖示 88.2＝空心，正是被自己關掉的結果。
- **量測（實機，2026-07-28，全螢幕 1920×1080）**：
  - 座標與素材無誤：`chat_icon_state_region(154,22,40,40)` 的實機裁圖與 `tests/fixtures/chat_icon/*.png` 逐列對齊；游標移到 `chat_icon_xy(174,42)` 跳出 Roblox 的 `Chat` tooltip。
  - 兩側夾在現行版面仍成立：關 82.9（無 hover）／93.6（游標懸停）、開 237.2~238.5。開關各自穩定，與 Roblox 前景與否無關（前景/非前景各量 4 次皆 238.5）、與 Tab 玩家列表開關無關（8 次皆 238.5）、閒置 5 分鐘不會自己變暗（無 idle fade）。
  - `41.0` 在整份 log 只出現 3 次＝全部來自這一場、且三讀**分毫不差**（活的遊戲畫面會抖動，靜態浮層才會分毫不差）。歷史 5 場「點了沒反應」的重試共 **0 次**救回（07-25 18:23／07-26 12:23、15:27／07-27 16:38／07-28 14:09），成功的場次一律第一次點擊就從 83 跳到 237。
- **對策**：
  - `config.chat_icon_closed_min_gray = 60.0`（新欄位）＋ `vision.chat_icon_state` 多收一個 `closed_min_gray`：關改成**有下界的區間** `60..130`，低於下界一律 `unknown`。`unknown` 在 `plan_chat_open_action` 任何 `clicks_done` 下都不會回 `click`（H047 既有安全方向），所以這一類讀值再也不會點到聊天框。門檻取 41 與實測關值下界 81 的中點（≈61）→ 60。
  - `config.chat_open_max_retries: 2 → 0`（判關只點一次）。重試的原始動機是「點擊被吃 → 重新聚焦再點」，但實機 0/5 救回，而每一次重試都是一次 toggle；讀值錯時奇數次點擊必定把聊天框關掉。
  - `main._ensure_chat_open` 的 unknown 重讀 log 從 DEBUG 升 INFO（實機 `log_level=INFO`，落 DEBUG 等於事後查不到 unknown 發生過）。
- **回歸**：`tests/test_chat_icon.py`——合成灰階 41／0 判 `unknown`（並確認 plan 不回 `click`）、85 仍判 `closed`、fixture 關值必須高於 `chat_icon_closed_min_gray`、config 額度下「判關恰好點一次就 give_up」。
- **實機驗收（2026-07-28）**：(1) 走 `.bat`／pythonw production 路徑重啟，聊天框開著 → `聊天框已開啟（圖示實心，probe=238.5）`、零點擊、啟動後仍開；旁觀截圖整段啟動 probe 未偏離 238.5。(2) 雙態腳本用同一條決策路徑（`vision.chat_icon_state` ＋ `roblox_menu.plan_chat_open_action` ＋ 正式額度）各跑一次：**開著＝0 次點擊維持開啟**（237.2 → `done`）、**關著＝恰好 1 次點擊就開起來**（83.3 → `click` → 237.2 → `done`）。
- **41.0 的遮擋源（使用者裁決，不再追查）**：那是 **Roblox 內建的浮層**，會蓋住畫面上方的物件；使用者平常就會避免讓它出現。**不必再花力氣定位它**——這條事故的對策刻意不依賴查明遮擋物身分：**讀值不落在任何一個實測區間就是沒讀到**，遮擋物是誰都一樣處理（unknown → 重讀 → give_up，絕不點擊）。
- **千萬別做**：不要為了「讓它敢點」而把 `chat_icon_closed_min_gray` 調低或拿掉——那等於回到「夠暗就算關」，H063 會原樣復發。也不要把 `chat_open_max_retries` 加回去當作點擊被吃的解法；真要救被吃的點擊，做法是「點完確認 probe 有變化」再決定下一步，而不是盲目多點幾次 toggle。

## H064（2026-07-25~28，harvest 110/111/112/119；使用者回報「稀有礦幾乎都採到了，最後卻幾乎全部走到人工」）：採集自己讓聊天淡出 → episode 基準恆為空 → 四個確認信號全部棄權，採到也永遠 no-new

- **症狀（使用者回報＋log）**：連續四輪 D3 命中、聊天確實出現稀有礦行，`harvest.log` 卻一律 `verify harvest: gone=True rare [0]->[2] no-new special=False -> RESWEEP`，重掃八方位全空（礦已被自己採走）→ `giveup` → NEEDS_HUMAN。119 的 `verify OCR` 逐輪都是 `rare/pass=[2] confirmed=False`，同時每輪都伴隨 `H054 基準閘：基準無 has-found 歷史`。
- **一句話根因**：`HARVESTING` 進場第一件事就是 `harvester.prepare_scan()` 停止移動 → 被動採礦停止 → 聊天 ~15s 無新訊息整窗淡出 → **episode 基準（進場凍結的裁圖）必然讀到 0 條 has-found**。於是四個確認信號同時失效：計數差被 H054 基準閘擋下、`has_new_rare_found_last_line` 與 `has_new_rare_found_tail` 因 `before_lines` 為空而棄權、`ChatLedger` 因「上次讀取為空 → 只起鏈不計新增」而棄權。**這不是機率性漏判，是這條路徑上恆成立的結構性全滅**——採到與沒採到在證據面完全同型。（記憶中的「harvest 109 未修復型」就是本案。）
- **量測（5 份實機 trace dump，全部可離線重跑）**：淡出基準重顯示後的**最底行**＝

  | dump | 底行（剝掉面板殘留後） | 稀有？ | 真相 |
  |---|---|---|---|
  | 119 | `small_lo has found Coinstorm` | 是 | 真成功（誤交人工） |
  | 111 | `small=lo-has-found-Coinstorm` | 是 | 真成功（誤交人工） |
  | 112 | `rsmall-lo-has-found-Starstride` | 是 | 真成功（誤交人工） |
  | **094（H054 假成功）** | `small_lo has found Syrooze (Candied Cave)` | **否**（排除清單內） | 沒採到，必須拒 |
  | 110 | （聊天全程沒重現，只有面板 `NORMAL`） | — | 無證據可用 |

- **對策**：`ocr.ChatLedger.update` 的「上次讀取為空 → 只起鏈、不計新增」改成「**只認最底行**」。依據是 Roblox 聊天語意：整窗只在**有新訊息抵達**時重新顯示，而新訊息恆在最底下 → 底行＝讓聊天重現的那則新訊息，其上全是重顯示的舊歷史（照舊一律不計）。H054 基準閘與 last_line/tail 的棄權規則**完全不動**（它們沒有錨點、無從自我保護）；帳本自帶錨點鏈，本來就是 `_verify_chat_ocr` 唯一不受基準閘否決的信號。
- **為何底行是「舊稀有行」的假陽性不成立**：聊天淡出前的最後一則訊息＝停手前的被動採礦行，那是一般礦（低階礦才會被動出土進聊天）；bot 不按 `/`、也不在採集期間點聊天圖示（H063 之後只在啟動時判一次）。若哪天真的踩到，代價是一次假成功、走人時礦還在——與現況「每輪都誤交人工」相比方向仍可接受，但**發現即回報**。
- **連帶修正**：`main._harvest_success` 的 Discord 通知行來源。基準為空時集合差集（`extract_new_found_lines_multi` / `new_fuzzy_rare_lines`）會把重顯示的整段舊歷史全列成「本次新增」→ 謊報一次採到五顆。基準沒有 has-found 歷史時改成只信帳本入帳的行。
- **回歸**：`tests/test_ocr.py` H064 區塊 6 例（119 底行確認、112 連字號黏連底行、只認底行不認中段舊稀有行、094 假成功仍拒、110 全程隱藏仍棄權且錨點不被面板汙染、Coinstorm/Starstride 在任何世界都是稀有的 fixture 前提釘樁）＋`tests/test_main_harvest_runtime.py` H064 區塊 2 例（走完整 `_verify_chat_ocr`：119 經帳本 confirmed 且基準閘 WARNING 照記、094 端到端仍不成功）。既有 H014/H020/H032/H041/H054/H055 測試全綠（1852 passed）。
- **下輪實機驗證預期**：`harvest.log` 出現 `H054 基準閘` WARNING 的那一輪，若聊天重現且底行是稀有礦，應接著看到 `帳本入帳新稀有行: [...]` 與 `-> SUCCESS`（或 `窗口到期最終確認救回`），不再出現「rare [0]->[2] no-new → RESWEEP → 全方位掃描未找到追蹤框」。反指標：`帳本入帳新稀有行` 的礦名若不是這一發打的那顆＝底行歸因假設有誤，須立即回查。
### H064（b）根因側對策：拍基準前 hover 喚醒聊天（`Bot._reveal_chat`，同日補上）

上面（a）是在證據面補救——聊天沒重現（110 型）仍然無解。使用者指出「聊天太久沒新訊息會自動隱藏，游標移到左上角遊戲會主動把聊天叫回來」，於是直接把根因移掉：**拍聊天基準前先把聊天叫回來**，四個信號全部恢復正常，(a) 退居後備。

- **量測（2026-07-28 18:2x，全螢幕、Roblox 前景；`chat_region` 亮像素 >90 計數）**：

  | 游標位置 | 亮像素 | 結果 |
  |---|---|---|
  | 原位（畫面中央偏右） | 0 | 聊天淡出 |
  | `chat_icon_xy` (174,42) | **304** | **只冒出 `Chat` tooltip，聊天沒出來** |
  | `chat_reveal_xy` (230,250) | **13614** | 整段聊天出現 |
  | 移回中央 (960,540) | 13503 | **離開後仍留著** |

  hover 僅 **0.25s** 即生效（0.5s 後量到滿值），離開後 **≥25s 不再淡出**（t=0/0.5/1/2/5/10/15/20/25s 連續採樣皆 13503+）。
- **⚠ 第一次量測全 0 是假陰性**：那時 Roblox 不在前景（跑腳本的 shell 搶走焦點），**合成 hover 在非前景時被整個丟掉**。補 `SetForegroundWindow` 後才重現。任何「送輸入卻沒反應」的實驗，第一件事是確認 Roblox 是不是前景。
- **對策**：`main.Bot._reveal_chat()` — `ic.move_to(chat_reveal_xy)` → 停 `chat_reveal_hover_s` → `ic.move_to(螢幕中心)` → 停 `chat_reveal_settle_s` → 用 `vision.bright_pixel_count` 確認有沒有喚醒成功（失敗記 WARNING，不擋流程）。呼叫點＝四個聊天基準取得處：`_on_enter(HARVESTING)`（**必須在 `_await_scan_ready` 之後**，那裡可能等 D2 冷卻數十秒，先喚醒等於白喚醒）、`_execute_remote_fire_from_web`、`_execute_remote_aim`、`_execute_aim_fine_fire`。
- **只移游標、絕不點擊**：聊天隱藏時 `chat_reveal_xy` 底下是 3D 場景，點下去＝打到遊戲世界；`chat_icon_xy` 更是 toggle（H063 的翻面風險）。回歸測試把「一次都不准點」釘成斷言。
- **喚醒後的聊天會一起進 `_pre_scan_ref`**：這是刻意的——之後每方位偵測都把它判 `preexist`，聊天文字不會變成假框。
- **回歸**：`tests/test_chat_icon.py`（`bright_pixel_count` 兩側夾對 `chat_reveal_min_bright_px`、喚醒點必須在 `chat_region` 內且不等於 `chat_icon_xy`）＋`tests/test_main_harvest_runtime.py` H064 區塊（hover 座標順序正確且 `click_at`/`mouse_click` 零呼叫、喚醒失敗記 WARNING 且仍不點擊）。
- **實機驗收（2026-07-28，同一場 harvest 119 現場）**：等聊天淡出（亮像素 0）→ 基準 OCR `baseline_saw_found_history=False`、0 行 → 跑真的 `Bot._reveal_chat()` → log `聊天已喚醒（亮像素 13614）` → 基準 OCR `baseline_saw_found_history=True`、12 行含 5 條 has-found（含底行 `small_lo has found Coinstorm`）。
- **殘留**：`_reveal_chat` 失敗（最可能＝Roblox 不在前景）時退回 (a) 的重顯示底行規則，不比修復前差。


## H065（2026-07-29，harvest 121；使用者回報「掃描俯仰時右下角 D2 效果消失、沒補上，某角度有礦卻沒目標框」）：D2 是 toggle，`execute_scan` 盲按 "2" 把已裝備的掃描器卸下 → 整層沒掃描

- **症狀（使用者回報＋log）**：俯仰層掃描時，121 的 up 層八方位全空，使用者肉眼看到右下角掃描指示器滅了、沒補上。log 的「俯仰層 up 重掃 D2：距上次掃描 54.9s」看似正常（>30s 冷卻＝沒被擋），但 up 層就是沒框——這行只證明**按鍵發出去了**，證明不了掃描真的觸發。
- **一句話根因**：`harvester.execute_scan` 每次盲按 `key_press("2")`，而 slot 2 是 toggle（rule 3、`fixtures/slot/README` 早已警告）；掃描器已裝備時再按 "2" ＝**卸裝**，接著的左鍵點空氣＝沒掃描。正常流程裡 D3 開火走 `2→3`（rule 5）會把 slot 換成 3，下一次掃描的 "2" 是「裝上」，陷阱被蓋住；**俯仰層把它掀出來**：mid 全空→沒開 D3→層轉換又是 `execute_scan`→第二次 "2" 卸裝→up 整層沒掃描。這是潛伏在掃描路徑裡、被 D3 的 `2→3` 長期蓋住的 toggle 陷阱，俯仰層是第一個「連續兩次掃描、中間不換 slot」的呼叫者。
- **量測（121 四張實機幀，slot 2 區域 `Region(864,998,54,58)` 的 greenness）**：

  | 幀 | 時間／情境 | slot2 greenness | 判定 |
  |---|---|---|---|
  | mid empty | 02:41:14，進場掃描成功後掃描器仍裝備 | **+10.50** | 已裝備（綠） |
  | up empty | 02:42:30，層轉換盲按 "2" 卸裝後 | **+1.48** | **已卸裝（灰）＝toggle 鐵證** |
  | d3 fire | 02:44:46，D3 的 `2→3` 後 slot3 裝著 | +1.48 | slot2 未裝備 |
  | down found | 02:43:49，down 掃描後 boost 守門按 "5" 又卸下 slot2 | +1.48 | slot2 未裝備（掃描那一刻有裝，是 boost 之後卸的）|

  門檻 5.0 兩側夾（裝備 +10.50 ≫ 5.0 ≫ 未裝備 +1.48）。slot2 未裝備基線（+1.48）比 slot1（-1.37）高——掃描器圖示本身帶微綠，但 up/d3/down 三個**不同場景**幀量出來分毫不差，是 hotbar 面板的 UI 固定屬性、不隨場景變，門檻安全。slot2 綠色範圍在 mid 幀為 x864–923（slot1 x798-852、pitch 66）。
- **為何 121 仍成功（不是反例）**：down 層在 02:43:15 重按 D2 那一刻 slot5 裝著（boost 守門 02:41:48 按的），"2" 是「裝上」不是「卸下」→ down 掃描有效 → 撈到 Gelisol。up 層中招是因為 mid→up 之間沒換 slot；down 沒中招是因為 up→down 之間 boost 守門剛好換過 slot。**這是靠運氣繞過，不是設計**——只要連續兩次掃描中間沒換 slot（任何 resweep／層轉換路徑），第二次必中。
- **對策**：`execute_scan` 加守門（比照 D1 的 `miner.py` slot_selected）：先 `vision.slot_selected(capture.grab(), d2_slot_region, d2_selected_greenness_min)`，**已裝備就不按 "2"、只 click 重掃**（已裝備時左鍵即重掃，與進場首次 `2→click` 同理）；未裝備才按 "2" 裝上。新增 `config.d2_slot_region`／`d2_selected_greenness_min`。守門放在 `execute_scan` 這個唯一掃描 chokepoint——`_run_scan`、`start_scan`（死碼）全經過它，所有掃描路徑一次修齊。
- **scan_confirm_mode 仍 off 的現狀下，這個守門是唯一防線**：`_confirm_scan` 在 off 時直接 `return True` 不驗（AGENTS.md CURRENT RISK AREAS 記著）。所以 slot_selected 守門不能省——它取代了「按下去到底有沒有生效」這條本該由 confirm 把關的檢查。
- **回歸**：`tests/test_execute_scan_toggle.py`（slot2 已裝備→不按 "2" 只 click、未裝備→按 "2" 再 click）＋`tests/test_slot_fixtures.py` D2 區塊（fixture 兩側夾：slot2_equipped_green=True、slot2_unequipped_gray=False、greenness +10.50/+1.48 夾門檻 5.0）。fixture 取自 121 實機幀（`slot2_unequipped_gray.png` 正是 up 層 toggle 卸裝那一幀）。
- **下輪實機驗證預期**：俯仰層轉換後的 up／down 層，`harvest.log` 應出現穩定框（不再因「沒掃描」而全空）。反指標：若某層仍全空、且該層開採前 slot2 區域 greenness 落在 +1.5 附近（未裝備），代表守門誤判「已裝備」而漏按 "2"——查 `d2_slot_region` 是否因 UI 改版位移，只改座標不動邏輯。

## H066（2026-07-29 03:34 RR#30／16:02 RR#31 兩次；使用者回報「回礦 #31：開場探了 300s 仍未全過驗證，最後一探 depth=讀不到｜capacity=讀不到｜pitch幀差=0.00/0.0000」）：重置收尾的**被動等候**吃掉開場探測預算，交人工訊息還附上一組從未量測過的讀值

- **症狀**：RR#31 16:02:07~16:06:56 共 15 輪 `[RR#N] 開場前容量 XX% > 5%（重置收尾中）`，容量 97→88,88→82,82→72×8→48,48，預算耗盡交人工。使用者收到的訊息寫「最後一探：depth=讀不到｜capacity=讀不到｜pitch幀差=0.00/0.0000」，照訊息附的判讀表（`pitch 0.00/0.0000＝凍結`）等於宣告遊戲凍結——但同一份 log 顯示容量 OCR 每輪都讀得到、而且一直在降。RR#30 03:34 同型（99→93→87→81×10）。此前 RR#13~#29 共 17 場全部正常（等 ~110~160s 就放行）。
- **一句話根因**：H058 的開場前容量預檢是「不點擊、不拖曳，只被動等遊戲把容量排掉」，但 `_rr_open_episode` 把 `_rr_open_first_ts`（開場**探測**預算 `reentry_open_budget_s`=300s 的起算點）設在函式開頭——於是被動等候的每一秒都從探測預算裡扣。等候本身完全沒有探測動作，`_rr_last_probe` 一次都沒被寫過，give_up 印出來的是它的初始值 `(None, None, 0.0, 0.0)`：depth/capacity 的「讀不到」與 pitch 的「0.00/0.0000」全是**佔位符不是量測**。
- **量測**（同一份 `miningbot.log` 的 19 場重置回礦，逐筆抄容量軌跡）：
  | 場次 | 軌跡 | 最長「沒再降」 | 結果 |
  |---|---|---|---|
  | RR#13/16/17/18/20/27/29（健康，7 場） | 95→79→71→63→56→43→6 之類，~110~160s | **1 輪** | 正常放行 |
  | RR#31 | 97→88,88→82,82→**72×8**→48,48 | **7 輪** | 一直在降，只是慢（~0.165 個百分點/s，排到 ≤5% 需 ~575s）|
  | RR#30 | 99→93→87→**81×10** | **9 輪** | 81% 後沒再降過（但 9 是被舊 300s 截斷的上界）|
- **對策**：(1) 等候有**自己的預算** `reentry_reset_drain_budget_s`=900s（最壞觀測 ~575s 的 1.5 倍），純函式 `reentry_remote.plan_reset_drain` 收口；`_rr_open_first_ts` 改在「容量過關、真的要點回到地表」那一刻才起算，探測拿回完整 300s。(2) 等候輪的節奏改由 `_rr_drain_first_ts` 驅動（這階段 `_rr_open_first_ts` 是 0，舊的 H044 迴圈條件會失效，首輪之後就再也沒人呼叫 `_rr_open_episode`）。(3) 等候超預算走 `_rr_drain_give_up`：講容量軌跡（最後讀值＋連續沒再降輪數＋已等秒數），明說「這不是開場探測失敗，bot 全程沒點過回到地表也沒拖曳俯仰」，不再借用凍結敘事。(4) HUD 等候輪不得被「回礦等待指令」覆蓋（那會謊報 bot 在等人）。
- **刻意不做：不寫「凍結」門檻**。stall 輪數只寫進 log／通知供人判讀。健康 1 輪 vs RR#31 的 7 輪 vs RR#30 的 9 輪——只差兩輪，而 9 還是被舊預算截斷的上界，沒人知道 RR#30 第 11 輪會不會恢復。任何門檻都不可否證（H059 教訓）。要放門檻進來，得先收一組「等到確定不會恢復」的負樣本。`tests/test_reentry_remote.py::test_plan_reset_drain_stall_count_cannot_separate_slow_from_frozen` 就是釘住這個決定的守門測試。
- **回歸**：`tests/test_reentry_remote.py` H066 七例（健康 7 場實機軌跡全程 wait 且 stall ≤1、RR#31 在 900s 下放行／在舊 300s 下必被砍、stall 分不開慢與凍、預算邊界 899/900、OCR None 不計 stall、容量回升算沒再降）＋`tests/test_main_pitch_home.py` 五例整合（等候輪不起算探測預算且不點不拖、放行才起算、放行後照舊 sweep、逾時通知講真症狀且不得出現 `pitch幀差`／`0.00/0.0000`、stall 計數累加）。
- **下輪實機驗證預期**：重置回礦輪的 `開場前容量` 行結尾改成「（已等 Ns／900s，連續沒再降 M 輪）」。慢速場次（如 RR#31）應該自己等到 ≤5% 後接上 `reentry_epN_dir1` 拍照，不再交人工。真的等不到時 Discord 訊息不得再出現 `pitch幀差=0.00/0.0000`。反指標：若某場 stall 輪數衝到 20+ 仍等滿 900s，那就是「確定不會恢復」的負樣本，拿它回頭補門檻。

## H067（2026-07-29 14:36 啟動；使用者回報「網頁 UI：http://127.0.0.1:8765/ ⚠ 綁不到 100.110.130.17」）：綁定等待 5s 太短，把「uvicorn 還在 init」誤判成「位址不通」而退回 127.0.0.1，手機整場連不進來

- **症狀**：`miningbot.log` 14:36:37 連三行——`WebIPC server 5s 內未 bind socket；uvicorn 可能還在 init 或綁失敗（should_exit=False）`→`WebIPC 綁 100.110.130.17 失敗`→14:36:38 `WebIPC server 啟動：http://127.0.0.1:8765`＋`綁不到設定的 100.110.130.17（Tailscale 沒起來？）`。介入面板只在 bot 這台開得起來，手機（同 tailnet）整場連不進來。07-26~07-29 01:35 之前的每一次啟動都綁得上 100.110.130.17。
- **一句話根因**：`should_exit=False` 就是答案——uvicorn 真的綁不上時會自己設 `should_exit`（`Server.startup` 捕 OSError），polling 迴圈立刻跳出。這裡 5s 到期時 uvicorn **還沒走到綁那一步**，只是第一次啟動要付一次性成本（asyncio proactor event loop 建立、`config.load()`、protocol 模組 import），而主執行緒正忙著 `Bot.__init__`（bot 程序 14:31:48 起、這裡已經是 14:36）。緊接著退回 127.0.0.1 的那次 <1s 就成了——模組已經熱了，正是「超時太短」而非「位址不通」的鐵證。
- **反證「Tailscale 沒起來」**：開機時間 07-25 15:45（事發前四天）、`tailscaled`/`tailscale-ipn` 都在跑、`Get-NetIPAddress` 顯示 `100.110.130.17` 為 `Preferred`，事後用 `TcpListener` 實測該 IP bind 得上。log 那句「（Tailscale 沒起來？）」是寫死的臆測，把排錯往錯方向帶了一整場。
- **對策**：(1) `WebIPCThread.start(bind_wait_s=20.0)`，值走新的 `Config.web_server_bind_wait_s`（預設 20.0）；真綁不上時 `should_exit` 讓迴圈立刻跳出，不會白等 20s。(2) 逾時警告按 `should_exit` 分兩種講法——True＝「uvicorn 已自行放棄（位址不存在或 port 被佔）」，False＝「還在 init、**不是位址不通**，調大 `web_server_bind_wait_s`」。(3) main.py 退回警告刪掉「Tailscale 沒起來？」的臆測，改叫人先看上一行分型。
- **回歸**：`tests/test_web_server.py::test_webipcthread_bind_wait_is_configurable_and_wired_from_config`（簽章有 `bind_wait_s`、Config 預設 >5.0、**且 main.py 真的把 cfg 值傳進去**——只改預設值沒接線的話 production 照樣吃寫死的 5s）。
- **下輪實機驗證預期**：啟動 log 出現 `WebIPC server 啟動：http://100.110.130.17:8765`，手機連得進去。反指標：若仍逾時且新訊息說「還在 init」，就是 20s 還不夠（再往上調）；若說「uvicorn 已自行放棄」，才是真的去查 Tailscale／port 佔用。

## H068（2026-07-31，harvest 129/133/141；由玩家在網頁標註工具標出的 `false_negative` 反查）：追蹤框被角色/裝備擋掉一角，`edge` 掉到 0.33~0.41 卡在 `tracker_shape_threshold=0.42` 下方 → 八方位全空誤交人工

- **症狀**：多輪 sweep 判 `sweep_empty`／`d3_gone_unconfirmed` 交人工，但玩家在網頁標註頁對同一批快照畫框標成「這裡有礦」。快照裡的框肉眼清晰可見（黃色尖刺太陽外框＋實心綠心）。
- **證據來源**：`tests/fixtures/aim/2026073*_*.json`＋`.png`（玩家標註的 320×270 粗格裁圖），對應全幀在 MSIX LocalCache `snapshots/review/`。把 crop 用 `matchTemplate` 定位回全幀就得到每顆框的絕對座標。
- **一句話根因**：這些框都被角色本體或裝備擋掉外框一角，形狀相關度 `edge` 因此掉到 0.33~0.41，低於 `shape_threshold` 0.42；而 `ring_ok=False`（實心彩心框本來就不環形）讓它們連 survivor 都進不了 → 直接 `hard_rej`，整輪全空。
- **量測（全幀重放 `find_tracker`，production 參數）**：
  - 真框被拒：`(979,550) 0.33/0.86`、`(937,458) 0.36/0.86`、`(1015,571) 0.36/0.86`、`(1396,815) 0.36/1.00`、`(1460,555) 0.40/0.86`、`(1433,491) 0.41/0.86`（edge/colored）
  - 真框被收（同批對照組）：0.43、0.43、0.45、0.46、0.48、0.49
  - 誤收側（**逐張肉眼確認過是什麼**）：粉紅岩層 `0.33/1.00`、NORMAL 面板文字 `0.33/0.86`、角色 `0.33/0.73`、裝備 `0.36/0.56`、其餘同色地形 0.31/0.30/0.29/0.28/0.25
  - → **`edge` 單軸已經沒有 gap**（真框 0.33 vs 岩層 0.33）。只調 `tracker_shape_threshold` 必然誤收地形。
- **對策**：
  1. `find_tracker` 加第二條 confirmed 路徑（二維軟收）：`edge ≥ tracker_shape_soft_edge(0.35)` **且** `colored ≥ tracker_shape_soft_colored(0.80)`。兩側夾＝岩層 0.33 之上留 0.02、角色 colored 0.73 之上留 0.07。軟收路徑**不重錨**（這種分數的形狀命中不足以信任座標）。
  2. 新增 `Config.ore_panel_region`（x 0-240、y 380-1080），與 `chat_region` 一起由新的 `Bot._tracker_exclusions()` 供給四個呼叫點。左側 NORMAL 面板是不透明 UI，蓋住的世界看不到也打不到，文字卻會出 `0.33/0.86` 的候選——結構性排除，不靠門檻。量測法：同場不同視角兩幀逐像素差分取靜態區（x 11~281、y 386~1068）。
- **回歸**：`tests/fixtures/tracker/h068_avatar_occluded_tracker.png`（129 dir4，真框 0.36/0.86 vs 同幀 0.30/0.87）、`h068_panel_vs_tracker.png`（141 up dir6，真框 0.36/1.00 vs 裝備 0.36/0.56 vs 面板 0.33/0.86）；誤收側由既有 `test_find_tracker_bottom_edge_scene_h026_recovered_by_config_margin`（粉紅岩層 0.33）與 `test_h068_soft_path_does_not_admit_equipment_scene`（裝備 0.29）兩張實機幀夾住。紅綠自證：`shape_soft_edge=1.0`（等同修復前）時兩張新幀都回 `None`。
- **整體命中率**：玩家標成真框的 12 張快照，修復前 6 命中，修復後 **11 命中**；唯一沒救回的是 `(979,550)` 的 0.33——與粉紅岩層同分，見 `docs/open-detection-issues.md` D09。
- **下輪實機驗證預期**：`harvest.log` 的 `shape確認` 行開始出現 `-> OK(彩心)`，且該輪不再落 `sweep_empty`。反指標：出現 `OK(彩心)` 卻在開火後 verify 全空、快照裡是地形／UI → 誤收側被 0.02 的 margin 咬到，回頭看該候選的 colored 與座標再決定加排除區還是抬 `soft_edge`。

## H069（2026-07-31 14:39:28，harvest 145；使用者回報「截圖提供的證據全部都是低階礦物，且表示已經挖到了，導致一個稀有礦物被捨棄」）：交人工前救援路 B 的稀有判準用「不在排除清單上」，而排除清單只收 Surreal+ → 鎬子挖兩分鐘就必然假命中

- **症狀**：`🛟 交人工前救援命中：sugarmuck、egguinox、cloverstone（panel 證據）已在 chill 前進帳，不交人工、繼續挖礦`。三個名字全是低階礦，D3 打了 4 次全 miss（`rare [0]->[0] no-new`）、`D3 階段超時 -> 人工`，救援卻把它攔下來回 MINING——一顆真稀有礦被靜默放生，且不會有任何人工介入的機會。
- **一句話根因**：`harvester.new_noncommon_panel_ores` 拿「`classify_found_ore != common`」當稀有判準，但 `common_ore_names()` 是**聊天排除清單**——它只收 Surreal/Mythic（＋會出變體的 Master 底名），因為只有那兩階會被動進聊天。NORMAL 面板列的卻是**整個背包**，絕大多數列（Sugarmuck／Cloverstone／Imbollyx／Bonnite／Fortunatum／Celtisalt／Auriclase…）階級遠低於 Surreal、兩張表都查不到 → 落 `unknown`，舊版一律當非-common。於是「bot 正常挖礦兩分鐘」本身就會生出新名字，救援對**任何** giveup 都會命中。
- **第二個根因（同一場獨立成立）**：`classify_found_ore` 用裸 `startswith` 比對白名單。Lucernia 白名單真的有一顆叫 `Eg`（Brittlestone、Transcendent），所以 `egguinox`.startswith(`eg`) → 低階礦被判成 Transcendent。同型地雷還有 `It.`／`Luna`／`Sol`／`Y`／`Bug`／`Vys`／`Lynx`。只修第一個根因的話 `egguinox` 仍會單獨讓救援命中。
- **量測**（`145_rescue_pre_panel.png` → `145_rescue_cur_panel.png`，相隔 130.4s，列數 9→8）：
  | 新增列 | 舊版分類 | 實際 | 新版 |
  |---|---|---|---|
  | `duskgravite` | common（Umbragloom Cave Mythic） | 低階 | 濾掉 |
  | `siogyne` | common（Shamrock Surreal） | 低階 | 濾掉 |
  | `sugarmuck` | **unknown → 算進帳** | 低階，兩張表都沒有 | 濾掉 |
  | `egguinox` | **rare（`Eg` 前綴誤配）** | 低階 | 濾掉 |
  | `cloverstone` | **unknown → 算進帳** | 低階 | 濾掉 |
  - 面板依稀有度排序，新列從頂端插入把舊列擠出 335px 裁圖 → 列數會**減少**卻同時有新名字，「列數沒增加所以沒挖到」這種守門也擋不住。
- **對策**：(1) `new_noncommon_panel_ores` → `new_rare_panel_ores`，判準改成**要有正面證據**：`classify_found_ore` 回 `rare`/`rare_fuzzy` 才算進帳。白名單（`assets/rare_ores.json`）收的是 Exotic 以上，正是 chill 會響、D3 要採的那批；unknown 一律不算（寧漏勿誤——假命中的代價是靜默放生真稀有礦，漏判只是照舊交人工）。救援路 B 與雙 chill 對帳共用同一個函式，兩邊一起修正。(2) 新增 `game_data._prefix_hit`：前綴必須結束在**名字邊界**上（尾端只放行非英數，容忍 OCR 雜訊 `bandeau!` 與洞穴註記 ` (floral cave)`）；尾端多一個字母屬於拼字近失，交給既有的 `CLASSIFY_FUZZY_RATIO` 模糊兜底判。common 與 rare 兩張表同時套用。
- **不動**：救援路 A（聊天）維持「非 common」判準。聊天只印 Surreal+，unknown 在那裡的意思是「白名單漂移或 OCR 讀歪的高階礦」，與面板的語意相反——`ocr._is_rare_ore` 的守門員規則在該路徑仍然正確。
- **回歸**：`tests/fixtures/panel/145_rescue_{pre,cur}_panel.png` 兩張實機裁圖跑完整 RapidOCR 管線（`test_h069_live_panel_diff_must_not_rescue`：確認有新增列、且差分必須是空）＋`test_new_rare_panel_ores_h069_live_panel_names`（合成名字版）＋`test_new_rare_panel_ores_ignores_unknown`＋`test_classify_short_whitelist_name_needs_word_boundary`（`eg` 與 `eg (eggshell cave)` 仍是 rare、`egguinox` 落 unknown）。真陽性側由既有的 125 Faedrine 兩例夾住（`test_faedrine_is_the_rescue_signal` 已改成斷言 `== "rare"`）。
- **下輪實機驗證預期**：`harvest.log` 的行改成 `面板差分（救援路B）：列數 X → Y，新增高階礦名 無`，giveup 照常交人工。反指標：若某場面板上肉眼看得到高階礦名、log 卻寫「無」→ 才是真漏判，照 `docs/data-collection-pipeline.md` 的分類表往 OCR／幾何閘查。救援的實機命中率統計要**從 H069 之後重新起算**：在此之前的每一筆 `HARVEST_RESCUED` 都可能是這型假命中。

## H070（2026-07-31 23:40:20，harvest 148 收尾；使用者回報「實機測試過了，似乎背包依然沒有清空」）：`_clear_panel_filter` 是唯一沒有聚焦守門的輸入序列，Roblox 失焦時整組點擊＋8 個 `w` 被系統丟掉，而失敗與「面板本來就有礦」在 OCR 上完全同形

- **症狀**：面板歸零上線後三次實機全失敗。前兩次（17:37、17:43）另有根因（已修）；23:40:20 這次在修完之後仍然失敗，log 寫「面板零點不成立：標頭 NORMAL、列數 8」，但 `panel_zero_failed` 裁圖顯示**篩選框裡是 `www`**——那是使用者 session 初始化時手打的原始值，bot 送的 8 個 `w` 一個都沒進去。
- **鐵證（log 相鄰兩行）**：
  ```
  23:40:20 WARNING 面板零點不成立：標頭 NORMAL、列數 8（faedrine、…）讀 1 次
  23:40:21 WARNING 旋轉鍵 . 疑似被吃（mean_diff=0.00013802 changed_frac=3.9e-06，attempt 1/3）→ 重新聚焦後重送
  23:40:24 INFO    Roblox 聚焦成功
  ```
  清空與那個被吃的按鍵只隔 1 秒，是**同一段失焦區間**。上一次聚焦成功是 23:39:54，中間隔了俯仰歸位（23:40:12）。
- **根因**：`_clear_panel_filter` 裸送 `click_at` + `pydirectinput.typewrite`，沒有聚焦守門也沒有生效驗證。repo 裡其他輸入序列都有：旋轉走 `_rotate_verified`（被吃會重新聚焦重送）、俯仰走 `_pitch_drag_verified`（前後幀比對）。只有這條沒有——因為它是最後才加的，且「清空失敗」與「面板真的有礦」在 OCR 結果上一模一樣，失敗被靜默吸收。
- **調查中被否證的兩個假說**（都花了實機量測才排除，記下來免得重走）：
  1. **座標差 1px**：OCR 複驗 `www` 中心是 (118,441)、設定值 (119,441)。第一輪 A/B 測試看似 118 過、119 不過，但**交錯重複三輪後兩者都 3/3**——差別是「框已被點過」而非座標。
  2. **第一次點擊不生效（要點兩次）**：冷啟（先按 Enter 把焦點還給 3D 世界）後點 1 次，3/3 全過。
  兩個假說都是在**腳本自己先 `focus_roblox()` 之後**測的，所以永遠重現不了實機那個失焦狀態——這正是「查實機問題要先確認重現環境與 production 是同一個狀態」的又一次（H061 是同一顆 Python 與否，這次是同一個焦點狀態與否）。
- **⚠ 量測方法本身也踩過坑**：篩選框的 `w` 會**越積越多並被壓縮成一條線**（使用者指出），所以「亮字寬度變寬」不能當「字進去了」的判準——滿框後恆為假。改用**墨量有沒有變**（`vision.filter_box_ink`，亮像素計數），壓縮會改變字形，墨量照樣不同。
- **對策**：(1) 清空前先 `_focus_roblox()`，拿不到焦點整條跳過並記 WARNING——盲送的代價不只清空失敗，那 8 個 `w` 若在焦點回來後才生效就是 8 次前進。(2) 打字前後比 `filter_box_ink(panel_filter_band)`，墨量沒變＝字沒進 TextBox，記 WARNING ＋ 存 `panel_zero_no_input` 裁圖，不記零點。兩道守門的失敗模式都是「路 B 下一場關掉」＝回到今日行為。
- **回歸**：`test_clear_requires_foreground_before_touching_ui`（失焦時零點擊零打字）、`test_clear_focuses_before_clicking`（順序）、`test_clear_detects_input_never_reached_the_textbox`（墨量沒變 → 不記零點＋留裁圖）、`test_clear_ink_guard_does_not_block_the_happy_path`（兩側夾）、`test_filter_box_ink_changes_with_text`（純函式）。
- **實機驗收（2026-07-31 當場跑過）**：情境 1 模擬失焦 → 點擊次數 0、`_panel_zeroed_at is None`；情境 2 正常路徑 → 自己聚焦、面板真的清空、零點成立。⚠ 未驗到的一段：「面板有礦時清得掉嗎」——驗收腳本想用 40 個 backspace 把篩選框清掉讓礦回來，但**backspace 沒生效**（框仍滿是 `w`），所以往返沒測成。下一場實機採集成功後看 log 是否出現「面板零點成立」即可補上。

## H071（2026-08-01 02:17:29，harvest 151 之後按「繼續」回挖礦；使用者回報「NEEDS_HUMAN 按繼續讓腳本繼續跑，但不會照挖到稀有礦之後的模式走，背包沒有清空」）：篩選框顯示壓縮到飽和後墨量恆定，H070 那道「墨量沒變＝字沒進」的硬閘從此永遠誤判，連面板 OCR 都不跑

- **先排除的假設**：「繼續」那條路沒接上清空。實際上 `_on_enter(MINING)` 早就呼叫 `_clear_panel_filter()`（commit 28ba7d6），log 也證明它跑了——02:17:12 `STATE_CHANGE NEEDS_HUMAN -> MINING`、02:17:29 清空失敗。缺的不是呼叫，是那次呼叫做不到事。
- **症狀**：`面板歸零：篩選框墨量沒變（494）→ 字沒進 TextBox`，接著提早 `return`，面板留著整場的礦（`panel_zero_no_input` 裁圖看得到 Clovara 14 排在最上面）。同一天 00:19（ink 257）、01:04（ink 769）也各掛一次，成功與失敗交錯出現，看起來像隨機掉鍵。
- **根因（量測序列）**：`typewrite` 是**附加**，框裡的字越積越多，**顯示壓縮到飽和後墨量就固定不動了**。
  | 時間 | 框內容 | ink | 字寬 |
  |---|---|---|---|
  | 07-31 23:55 打字前 | 5 個 `w` | 257 | 57px |
  | 07-31 23:55 打字後 | 13 個 `w` | 769 | 169px |
  | 07-31 23:56 **送 40 個 backspace 後** | 沒變 | 769 | 169px |（見下方訂正）
  | 07-31 23:56 再清一次 | 滿框 | 500 | 180px |
  | 08-01 02:15／02:17 前後 | 滿框 | 494／494 | — |
  飽和後再打 `w` **一個像素都不變**。⚠ **但框吃得下無限長的字**（使用者指正）——文字其實有變、遊戲的篩選照樣重跑、面板照樣會清空（H071b 實機確認：typing alone 面板 3→0 列）。壞掉的只有那道墨量硬閘：它把「墨量沒變」讀成「字沒進 TextBox」就提早 `return`，連面板 OCR 都不跑、`_panel_zeroed_at` 一路是 `None`。08-01 三次歸零（00:19 ink 257／01:04 ink 769／02:17 ink 494）全掛在這裡。
- **手段是實機夾出來的**（`.scratch/probe_filter_clear.py`，08-01 03:5x 三法對照，起點是滿框 ink=494／字寬 199px）：
  | 手段 | 之後 | 判定 |
  |---|---|---|
  | Ctrl+A 全選 → 打 w | 494／**199px**（分毫不變） | ❌ 這個 TextBox 不吃全選 |
  | 滑鼠拖曳選取 → 打 w | 468／100px | ✅ |
  | backspace × 40 | 275／57px | ✅ |
  **訂正 H070 的旁註**：那條寫「backspace 沒生效」是**誤判**——`verify_roundtrip.py` 那次是冷點擊沒真的聚焦到框（H070 自己列為假說 2 卻在暖狀態下測、因此重現不了），不是按鍵無效。⚠ **H071b 補充**：backspace 單獨經 pydirectinput 發 60 次確實無效——但不影響 H071 的對策（不需要清框，typing alone 就夠）。
- **對策**：**只拆掉那道硬閘**，輸入序列一個字都不改（使用者指定：照舊疊加、不必清空篩選框）。墨量從判準降級成 log 裡的線索，面板 OCR 的重讀迴圈一律跑完，由它決定零點成不成立。H071b 確認此對策正確——typing alone 就能清空面板。
  ⚠ **走過的兩條冤枉路**（都已實機否決，別再試）：先想用 Ctrl+A 全選取代——實測對這個 TextBox **完全無效**（199→199px 分毫不變）；再想用 backspace 騰空間——有效（199→100→57px）但**根本不需要**，因為框沒有長度上限。
- **回歸**：`test_clear_ink_unchanged_but_panel_empty_still_counts_h071`（墨量沒變但面板是空的 → 零點照樣成立；這條直接鎖住玩家回報的那個 bug）、`test_clear_never_tries_to_empty_the_filter_box_h071`（整條只有 click → 打字 → Enter，不得出現任何清空動作）、`test_clear_failure_log_carries_the_ink_numbers`（墨量前後值仍要進 log 當線索）。
- **⚠ 下一場實機驗證預期**：不論篩選框墨量變不變，log 都要出現「面板零點成立（標頭 NORMAL、無白名單礦…）」＝修好了。反指標：出現「面板零點不成立：…篩選框墨量 X→Y(沒變…)」且裁圖上面板真的還有礦——那才是輸入真的沒進去，回頭查點擊座標與焦點（H070 那條路）。

## H071b（2026-08-01，harvest 153 調查結論：typing alone 就夠、不需要 Ctrl+A+backspace；根因見 H071c）

- **症狀**：harvest 153 採到 Coinstorm（Transcendent）後，`_clear_panel_filter` 執行歸零：ink 921→921（沒變），面板仍 8 列（coinstorm、halcylite 等）。當天 7 次歸零唯一失敗的就是這次。
- **遊戲機制（使用者澄清）**：filter 一直在、從不關閉。挖到新 礦時遊戲把它加到面板上（bypass filter）。打 w 進篩選框會觸發 filter 重評估、面板清空。filter 不管框裡有幾個 w——8 個跟 80 個效果一樣。
- **一句話根因**：8 個 w 進了遊戲世界（=前進鍵）而非 TextBox，filter 沒被更新。最初判為 click 沒命中，H071c 訂正為 **typewrite 間隔太短（40ms）**——click 命中了但 TextBox 還沒準備好接收鍵盤輸入。
- **實機量測（2026-08-01，bot 暫停、Roblox 開著）**：
  | 手段 | 結果 | 判定 |
  |---|---|---|
  | type 8w alone（面板有 3 列新 礦） | 面板 3→0 列 | ✅ typing alone 就夠 |
  | Ctrl+A + backspace + type 8w | 面板 8→0 列 | ✅ 但多餘 |
  | backspace x60（pydirectinput） | ink 7405／字寬 213px，零效果 | ❌ 進不了 TextBox |
  ink 在飽和狀態下是純噪訊（933→216→741→535 亂跳，字寬恆 213px）——不是字沒進去，是量不出來（使用者：顯示壓縮到字太小，像素量測失效）。
- **結論**：**H071 的做法（只拆硬閘、照舊疊加 w）正確，不需要 Ctrl+A+backspace。** 實機證明 typing alone 就能觸發 filter。Ctrl+A+backspace 曾短暂上線（commit 6370580）但已 revert。真正的根因（typewrite 太快）由 H071c 解決。

## H071c（2026-08-01，harvest 153 根因訂正＋修復：typewrite 40ms 太快 → key_press 90ms；w 數 8→4）

- **根因**：`_clear_panel_filter` 用 `pydirectinput.typewrite("w" * 8)` 打字，間隔只有 `PAUSE=0.04`（40ms）。codebase 其他所有按鍵都走 `ic.key_press`（90ms）。`input_control.py` 第一行就寫「之前輸入太快、遊戲來不及讀」——`typewrite` 恰恰繞過了這道保護。post-harvest 遊戲忙碌時 8 個 w 以 40ms 間隔打入，遊戲來不及聚焦 TextBox，w 進了遊戲世界（=前進鍵）而非 filter 輸入框。
- **對策**：`typewrite` → `ic.key_press("w")` 迴圈（90ms 間隔，與 codebase 一致）；`panel_clear_keystrokes` 8→4（90ms 間隔下按鍵幾乎不掉，不需要過量送）。
- **回歸**：`test_clear_input_sequence_is_click_w_then_enter_h071c`（驗序列 click→w×4→enter）、更新 `test_clear_sets_timestamp_when_normal_and_empty`（keys 含 w×4+enter）、`test_clear_rereads_when_panel_redraw_lags`（keys.count("w")==4）。72 passed。
- **⚠ 下一場實機驗證預期**：採集成功後 log 出現「面板零點成立」。墨量 before/after 在飽和時仍可能是噪訊——重點看面板 OCR 是否 0 列。反指標：仍出現「面板零點不成立」→ 90ms 還是不夠，考慮加長 click-to-type gap（目前 0.15s）。

## H072（2026-08-01 18:39:07，harvest 162；使用者回報「跳過背包檢查，將低稀有 礦作為通過，稀有框沒被挖掘」）：RapidOCR 尾端截斷 common 礦名 Weevil→Weevi，_is_rare_ore 的單向 startswith 不成立 → 假稀有 → count 0→1 → 假成功

- **症狀**：D3 命中真追蹤框（dir2 1458,497 score=0.622），verify 輪詢到窗口到期最終確認時，同一行 "has found Weevil" 被 OCR 截斷成 "has found Weevi"。baseline rare=0（Weevil 在排除清單）、final rare=1（Weevi 不在）→ count 差 0→1 → confirmed=True → SUCCESS。events.log：`tracker_gone=False rare_before=[0] rare_after=[1] new_found_lines=['small_lo has found Weevi']`。稀有 礦從未被採到。
- **根因**：`ocr._is_rare_ore` 用 `base.startswith(c)` 單向——容忍尾端**加**雜訊（"weevil!" → common）但不容忍尾端**截斷**（"weevi" → 不 match "weevil" → rare）。同時 `game_data.classify_found_ore` 有 fuzzy 兜底（CLASSIFY_FUZZY_RATIO=0.80，SequenceMatcher("weevi","weevil")=0.909 ≥ 0.80 → common）——正確判 common，但只用在通知標注，沒回流到 verify 決策路徑。兩套分類各自獨立、用不同匹配邏輯；H033 加的 fuzzy 分類只進 game_data、沒回流 ocr。
- **對策（三層）**：
  1. `_is_rare_ore`（ocr.py）補反向 prefix：common 名以 base 開頭（base ≥ 4 字）→ 視為截斷 → common。方向安全（寧漏勿假成功）。count/last_line/tail 所有信號同時修好。
  2. classify 交叉驗證（main.py `classify_confirms_new_rare`）：count_rare_found 說有新稀有但 classify_found_ore 說沒有 → 否決 confirmed。只否決計數差那份——帳本有行級匹配（`_lines_alike` ratio 0.85，對截斷免疫），照常 OR 上來（H032 晚到行仍救得回）。
  3. 進場面板色檢（main.py `_harvest_entry_panel_check`）：chill 觸發進 HARVESTING 時，若面板（已歸零可信）已有白名單 礦＝chill 前鎬子已挖到→不需要 D3 採集。觀察期照舊交人工確認（同救援路 B）。
- **回歸**：`test_count_rare_found_tolerates_trailing_ocr_truncation_on_common`、`test_has_new_rare_found_false_when_common_ore_ocr_truncated`、`test_classify_confirms_new_rare_rejects_truncated_common`、`test_classify_confirms_new_rare_accepts_real_rare`、`test_entry_panel_check_*` ×4。2297 passed。
- **⚠ 下一場實機驗證預期**：log 不再出現 `H072 classify 交叉驗證否決`（代表截斷沒發生或被層 1 擋下）。若出現 `H072 進場面板色檢命中`→面板色檢偵測到 chill 前已挖到的 礦，攤開證據問使用者是否合理。反指標：真成功卻被層 1 或層 2 否決（rare 礦名也被截斷成 <4 字的前綴）→ 鬆門檻。

## H073（2026-08-02 04:06:43，harvest 168；使用者發現「稀有挖礦工序沒有檢查 D2 效果是否使用」）：scan_confirm_mode="off" 使 _confirm_scan 永遠放行 → 進場 click 被吃／掃描沒觸發 → bot 無法分辨「沒稀有礦」與「掃描沒觸發」→ 白掃 8 方位全空 → giveup

- **症狀**：harvest 168 進場 D2 掃描後，8 方位 sweep 全部 no tracker（所有候選 ring_ok=False、edge ≤0.33），俯仰層 up/down 全被吃，最終 NEEDS_HUMAN。連續 3 場（166/167/168）同樣模式。使用者實機觀察確認畫面上無 D2 掃描效果。
- **實機量測（sweep_empty_dir0 幀）**：
  | 項目 | 值 | 判定 |
  |---|---|---|
  | slot 2 greenness | 10.5（門檻 5.0） | D2 已裝備（slot_selected 通過） |
  | 效果列 per-slot OCR | "Used tu"／"A" | **無 Local 徽章** → scan_succeeded=False |
  | 8 方位候選 ring_ok | 全 False | 全是地形/UI 噪音，無真追蹤框 |
  | D5 boost bottle 偵測 | matchTemplate score 0.337 < 門檻 0.4 | **D5 也未生效**（使用者確認：成功觸發應出現兩個同樣圖示，只有一個＝使用次數非 boost） |
- **一句話根因**：`execute_scan()` 的 `slot_selected` 只驗裝備（slot 亮綠）不驗效果（掃描是否觸發），click 被吃時裝備仍在但掃描沒生效；`_confirm_scan()` 的 OCR 徽章驗證寫好了但因 `scan_confirm_mode="off"` 永遠 return True，使這層保護形同虛設。
- **修復（比照 D5 boost guard 的 self-heal 模式，使用者指定）**：
  1. `_confirm_scan` enforce 模式重試後回傳實際結果（`return ok` 取代 `return True`）。
  2. `scan_confirm_mode` 預設從 `"off"` 改 `"enforce"`——進場 `_confirm_scan` 偵測到 badge 缺失時自動 refocus + 等冷卻 + 重掃一次（一次 retry）。
  3. **`_harvest_scan_guard`（核心）**：比照 `_harvest_boost_guard`，在 `_sweep_for_tracker` 每方位檢查效果列 Local 徽章，缺了就 `_await_scan_ready` + `_run_scan` 補掃再繼續——**不交人工**（self-heal）。throttle（`_scan_guard_at`，`radar_repeat_interval_s`）防 OCR 假陰性 spam 冷卻。
- **D5 boost 偽陽性（同場修復）**：`_boost_needs_refresh` 的 `find_template_edges` 在效果列 matchTemplate score 僅 0.337（< 門檻 0.4），但 edge-based 偵測通過——命中位置 (1705,1039) 與 boost 使用次數區 (1720,990,90,90) 重疊。使用者指出：D5 成功觸發時效果列會出現**兩個**幾乎同樣的瓶子圖示（一個 active buff、一個使用次數）；只有一個＝boost 未生效，那個是次數icon。**根因**：全螢幕校準（2026-07-28）後 boost_indicator_region 從 145px 高變 95px 高，使用次數 icon 在新 region 內的 edge match score 從 0.19 升到 0.42（剛過舊門檻 0.40）。**修復**：`boost_edge_threshold` 0.40→0.55。新 fixture `h168_sweep_no_boost.png`／`h168_mining_boost_active.png` 是 harvest 168 生產幀裁圖（95px 高），與既有 fixture（145px 高、校準前）互補。**兩側夾（2026-08-02 code review 複驗，全五張 fixture 實測）**：

  | fixture | 高度 | edge score | 期望 |
  |---|---|---|---|
  | `before_only_count` | 145px | 0.194 | 拒 |
  | `h168_sweep_no_boost` | 95px | **0.419** ← 誤收上界 | 拒 |
  | `active_61` | 145px | **0.619** ← 真值下界 | 收 |
  | `h168_mining_boost_active` | 95px | 0.787 | 收 |
  | `active_47` | 145px | 0.798 | 收 |

  ⚠ 初版本條目寫「true boost 0.77+」是**錯的**（只看了兩張最高分的），真值下界是 `active_61` 的 0.619——0.55 的正側餘裕只有 0.069、負側 0.131。要再調高門檻前必須先補真 boost 樣本，否則會切掉 `active_61` 這型。
- **code review 補修（2026-08-02，同日）**：雙軸 review 抓到四個缺口，已一併修掉——
  1. **`手動` survey 仍會交人工**：`_tick_remote_aim` 的 `if not self._confirm_scan(where) and layer.name == "mid": return` 是 `04a2d2c` 的既有碼，`scan_confirm_mode="off"` 時是死碼，改 `enforce` 後**被啟用**＝正面違反「先補上再繼續」。改成照拍、記 `scan_unconfirmed`，並在發圖前用 ⚠️ 訊息告知玩家「這層掃描未確認、沒框可再 `手動` 一次」（否則玩家會把 bot 失誤當成「這層真的沒礦」）。
  2. **補掃後沒重置 sweep 預算**：`_await_scan_ready` 最長等 `radar_scan_wait_max_s`(36s)，不重置則下個 tick 的 `elapsed_s` 必 > `sweep_timeout_s`(30s) → self-heal 剛救回掃描就被自己的耗時判成「sweep 超時 -> 歷史目標復原/人工」。比照 `_reharvest_sweep` 重置 `_harvest_start`／`elapsed_s`。
  3. **`_scan_guard_at` 沒在 `__init__` 宣告**（只靠 `getattr` 預設）：跨 episode 殘留會讓新一輪前 34s 守門形同關閉。已補宣告，並在進場 `_confirm_scan("enter")` 之後設為當下——進場那次就是最近一次補掃，順帶擋掉「retry 剛失敗、dir0 立刻按第三次 D2」。
  4. **兩側夾數字寫錯**（見上表）。新增 `test_boost_edge_threshold_brackets_both_sides` 用全五張 fixture 實算兩側，門檻挪到夾不住就紅燈，不必再靠人重跑離線量測。
- **回歸**：`tests/test_scan_confirm_gate.py` 11 項——`_confirm_scan` 五種模式回傳值、`_harvest_scan_guard` badge 在放行/缺了補掃/throttle 防spam/補掃後重置預算/harvest 為 None 不爆/`__init__` 有宣告。`tests/test_boost_fixtures.py` 6 項（含兩側夾）。`tests/test_main_harvest_runtime.py` 4 項 sweep 測試加 `_harvest_scan_guard` mock。
- **⚠ 下一場實機驗證預期**：log 出現 `[scan-confirm] enter ok=True/False`（進場驗證）及 `[168] scan guard: 無 Local 徽章 -> 補掃 D2`（sweep 中途補掃）。反指標：ok=True 卻 sweep 全空＝真正沒礦（正常）；scan guard 頻繁觸發＝掃描持續被吃或 OCR 假陰性。補掃後不該再看到緊接著的「sweep 超時」（那是上面第 2 點修掉的病徵）。
- **⚠ 仍未補的證據缺口**：`scan_confirm_mode` 從 `off` 改 `enforce` 讓 `_scan_local_badge_present` 這條逐格 OCR 變成 load-bearing，但目前所有測試都是 `lambda: True/False` mock，**沒有一張真實效果列幀進 `tests/fixtures/`**（harvest 168 的實測文字 `"Used tu"`／`"A"` 只寫在本條目，幀還在 `.scratch/h168_*.png`）。依 AGENTS.md「Visual/OCR threshold changes require real fixtures」這是欠的——OCR 假陰性的代價現在是每方位多一次補掃＋等冷卻。下次實機取到有／無 Local 徽章的成對效果列幀時補進 `tests/fixtures/scan_confirm/`。

---

## H074（2026-08-02 16:25:41，harvest 171；state-commit bug＋double chill 放生風險）

### 症狀
進場面板色檢命中 astatine（chill 前鎬子已挖到）→ `_harvest_giveup` 送出 NEEDS_HUMAN alert → 但 bot 沒停在 NEEDS_HUMAN，繼續在 HARVESTING 跑 `_tick_harvest` → 用上一輪（episode 170）的殘值 `_target_marker`／`_chat_baseline` 跑到 D3-timeout 晚到確認 → 被動挖礦的 Astatine 剛好進聊天 → 轉成功 → 續採 bonus sweep。結果恰好正確（ore A 確實被挖到了），但全程是不可靠的殘值驅動。

### 根因（兩層）
1. **state-commit bug**：`_harvest_entry_panel_check` 在 `_on_enter(HARVESTING)` 內呼叫 `_harvest_giveup`（line 5611 直接寫 `self.state = NEEDS_HUMAN`）。但 `_on_enter` 回傳 None（line 3539 `return`）→ `resolve_state_transition(current=NEEDS_HUMAN, decided=HARVESTING, entered=None)` 回傳 HARVESTING（line 114 `return decided`）→ 主迴圈 `self.state = HARVESTING` 蓋回。對比 MINING 聚焦失敗路徑（line 3472）正確地 `return State.NEEDS_HUMAN` 當降級信號——panel check 路徑沒有。
2. **殘值 state**：panel check 在 `_on_enter(HARVESTING)` line 3538 就 return，在它之前的 episode 狀態初始化（line 3568 `_target_marker = None`、line 3573 `_chat_baseline = None`、line 3567 `_harvest_start`）都沒跑到 → 保留 episode 170 的值。`_tick_harvest` 用殘值 `_target_marker=(1430,501)` 進 D3 階段 → `elapsed_s` 天文數字（`_harvest_start` 未設）→ D3 立刻超時 → 晚到確認用殘值 `_chat_baseline` 比對 → 命中被動挖礦行。

### 同場發現的更大風險：double chill 放生
使用者指出：兩顆稀有礦近同時重新整理時，音訊「連音」（1.5s 滾動窗合併為一聲）。若其中一顆被鎬子被動挖到（面板已有）→ panel check 舊版直接跳過 sweep → 第二顆追蹤框從未被掃過 → 靜默放生。

**音訊無法計數**（`match_score` 回傳 peak，不計數；1.5s 窗合併兩聲）。**banner 文字可計數**：每則 spawn 訊息有唯一隨機 RGB（16.7M 種），色相跳變＝第二則。文字在音效前刷新（~0.4-0.6s gap），MINING 期間每 tick 取樣即可抓到。

### 修復（三層）
- **層 A — state-commit bug fix + panel check sweep**：`_harvest_entry_panel_check` 不再呼叫 `_harvest_giveup`，改成純檢查回傳 gains list。`_on_enter(HARVESTING)` 存 `_entry_panel_gains` 後照常跑 prepare_scan／sweep。sweep 全空才 giveup（reason 帶入面板 gains）。
- **層 B — banner 色相 double-chill 偵測**：新增 `vision.banner_text_hue(crop)`（HSV mask → median hue，純像素 ~1ms）。`observe()` 在 MINING 每 tick 取樣 `chill_text_region`，色相跳變 ≥ `banner_hue_change_deg`(15°) → 記時戳到 `_banner_color_changes`。`_on_enter(HARVESTING)` 查近期跳變設 `_double_chill_detected`。
- **層 C — flag 消費**：double chill 時採完第一顆仍強制 bonus sweep（即使無可見追蹤框）；bonus sweep 全空 → `decide_bonus_empty(True)` → 交人工不回 MINING。

### 回歸
- `tests/test_giveup_rescue.py`：panel check 5 項更新（回傳 list 不再 giveup）
- `tests/test_vision.py`：`banner_text_hue` 4 項（暗底 None／綠色色相／紅藍區分／像素不足 None）
- `tests/test_harvester.py`：`decide_bonus_empty` 2 項（False→RESUME／True→HUMAN）
- ⚠ **待實機驗證**：panel check 命中後看到 sweep 跑（非直接 giveup）；double chill 場次看到 `banner 色相跳變` log + 強制 bonus sweep。低飽和隨機色（~5-10%）抓不到時退回層 A sweep 保護，不會更差。

## H075（2026-08-06；標註驅動微調，91 張玩家標註 fixture）：`detect_tracker_core` 只認飽和綠且揀選候選用面積最大，被誤判成「玩家標註不可信」

### 症狀

玩家在 `/annotate` 累積 91 張未進版控標註（覆蓋 20 個場次），離線重放
`detect_tracker_core` 只有 33/204（16%）跟玩家一致。前一輪分析（`.scratch/
annotation-trust-audit/issues/01-annotation-trust-audit.md`）在**沒有看過任何一張
裁圖**的前提下，把 83% 不同意歸因成「玩家在暗幀上瞎標」，並規劃了一整套人工覆審 UI
＋語料信任閘要先擋住 tuning 迴圈。肉眼核對後這個假說是錯的：抽查的 `sweep_confirmed`
（production 已 confirmed 的真框）與 `false_negative`（玩家標「看得到框」）幾乎每張
框都清楚可見、標註座標也大致落在框上。

### 一句話根因

`detect_tracker_core` 的 `tracker_core_profiles` 只有一個 green profile（S≥150），
且候選揀選用「面積最大」而非「離 region 中心最近」——兩者疊加，讓大量真框（尤其是
低飽和綠、以及紅／棕／近白／紫四種完全沒覆蓋的色系）在合法場景下偵測不到，被誤判為
標註品質問題。

### 量測（91 張標註 fixture 重放，按場次去重）

| 現象 | 場次數 | 說明 |
|---|---|---|
| green S 只有 128~130（舊門檻 S≥150） | 11（harvest 128/138/147/148/150/159/161/198/199/205/207） | 淡薄荷框心 |
| 色系完全未覆蓋 | 4（harvest 145 red／119+153 brown／162 white_blue／196 magenta） | 肉眼核對過裁圖，四色系都是清楚可辨的框 |
| green 色系內、面積正確但候選揀選選錯 | 1（harvest 197） | region 中心 area=256 的真框輸給邊緣 area=416 的地形 |
| 同色地形黏連成超大 blob，撞 `max_area` 出局 | 1（harvest 158，未修，見 D15） | 跟 H057 同類，`detect_tracker_core` 沒有 V-submask 救援 |
| 素材本身壞掉（聊天面板疊字，非追蹤框） | 1（harvest 152 dir5，見 D15） | 差點被誤當第三種橘色系，跟 decoy 負例只隔 2° 夾不出兩側才發現不對 |

兩側夾（新色系 vs 81 張 `decoy`/`empty` 負例的最近距離）：

| profile | 真值 H/S/V | 最近負例 H/S/V | 分隔方式 |
|---|---|---|---|
| green（S 下限下修） | 57~63 / **128~130** / 200~255 | 57 / **245** / 49；59 / 177~255 / 39~144 | S 缺口 [125,150) 內無負例落點 |
| red（新增） | 0 / 185 / 250 | 10 / 251 / **64** | V 隔開（暗） |
| brown（新增） | 14 / 160 / 147 | 25 / 224 / 122 | H 隔 11° |
| white_blue（新增） | 110 / **25** / 255 | 126~128 / 44 / **29** | V 隔開（暗），S 也窄 |
| magenta（新增） | 171 / 121 / 131 | 128 / 44 / 29 | H 隔 43° |

harvest 152 的 H≈23 橘色候選**不採用**：與 decoy 負例（H≈25，7+ 個獨立命中）只隔 2°，
且肉眼核對來源幀後發現那張裁圖根本不是追蹤框（聊天面板疊字），樣本本身不可信。

### 修復

1. `config.py` `tracker_core_profiles`：green S 下限 150→125；新增 red／brown／
   white_blue／magenta 四色系（各附兩側夾註解）。
2. `vision.detect_tracker_core`：候選揀選從「面積最大」改「離 region 中心最近」——
   region 是玩家選定的粗格，premise 是目標在格心附近，不是「畫面裡最大的合法候選」。
3. 兩張問題 fixture（harvest 158 同色黏連、harvest 152 壞素材）記入
   `docs/open-detection-issues.md` D15，不在本次修復範圍。
4. 91 張玩家標註 fixture 隨本次修復一併 commit 進 `tests/fixtures/aim/`。

### 沒有做的事（原 spec 的 Phase 2/3）

原 spec 規劃的「人工覆審 UI」＋「未覆審素材不得參與 tuning」信任閘，在根因查明後
不再是優先項——真正擋住 tuning 迴圈的是偵測器色系覆蓋不全，不是標註品質。若之後真的
出現大量肉眼確認的錯標（不是這次查到的偵測器 bug 類型），再評估要不要做那套機制。

### 回歸

`tests/test_vision.py` 新增 8 項：5 個色系命中（含既有 green 場景）、1 個候選揀選
（`test_detect_tracker_core_picks_candidate_nearest_center_not_largest_area`）、1 個
假陽性率守門（`test_detect_tracker_core_decoy_empty_false_hit_rate_not_regressed`，
鎖住 81 張 decoy/empty 負例掃過新五色 profile 後假陽性數 ≤2，不得比修復前更差）。
全部用 91 張批次裡的實機 fixture，不是合成圖。

### ⚠ 待實機驗證

下一輪手動瞄準（`手動`／grid 路徑）遇到非綠色系或低飽和綠框時，log 應出現
`AIM 限縮偵測命中` 而非 `AIM 限縮偵測 None cell=...（待補色系 profile）`。反指標：
新色系命中後開火位置明顯偏離框——代表某個新 bracket 夾太寬，收了色系相近但位置不對
的雜物，需要回頭縮 bracket。

## H076（2026-08-06，H075 續；使用者提問「都是因為已經有固定顏色才被記錄進去，之後
遇到沒遇到的礦物是否又會出現問題」）：色彩清單追不上新道具，`detect_tracker_core` 加形狀 fallback

### 一句話根因

H075 補完的色彩清單（green/red/brown/white_blue/magenta）只解決「這批 91 張標註裡出現
過的內心色」，使用者當面點出結構性問題：**內心方塊顏色不是 tier 決定的，同一 tier 換
道具就換內心色**（Transcendent 藍菱星量到棕/白/暗三種心）——色彩清單註定永遠追著新
道具的新內心色跑，跟一開始「新色 fixture 到手才加」是同一種被動姿態，換湯不換藥。

### 設計（grill-me 逐輪敲定，見對話記錄）

1. **觸發時機**：色彩 profile 全部零候選時才進形狀 fallback；候選存在但被
   area/ar/extent/border 濾掉的（例：harvest 158 同色黏連超大 blob）不算——那是 D15
   的 V-submask 救援範疇，不共用這條路徑，用 `had_color_candidate` 旗標把兩者分開
   （第一版沒分，harvest 158 意外被形狀 fallback 撿走，border_frac 剛好壓線 0.213
   通過 0.15 門檻，範圍跟定案的界線不符，已補 `had_color_candidate` 修正＋回歸測試鎖住）。
2. **兩段式**：不是對整張裁圖硬跑模板比對，而是重用既有 `_best_edge_match_sized`／
   `template_outline_edges`（`find_marker` 已驗證過的同一套色相無關 edge 比對），
   命中位置再過同一套黑邊環帶 `_dark_border_frac`（跟色彩候選共用同一份，避免兩處
   會漂的複製）確認——不是另開一條比對邏輯。
3. **開火**：命中即開火，不加兩幀穩定性複驗，門檻照兩側夾量測值定（`shape_threshold=
   0.60`，比 `find_tracker` 的 `tracker_shape_threshold` 高——沒有色彩兩側夾撐腰，
   出手前要求更確定）。使用者原話：「歪打正著射擊中總比什麼都沒拿到好」。
4. **模板來源**：91 張標註肉眼核對後按 `tier` 分組（不是按內心色 HSV——同色跨 tier、
   同 tier 跨色，兩者是分開變化的維度，用色彩分群會把不同外框的素材混在一起）。
   量到 Transcendent／Exquisite／Enigmatic 各恆一種外框，Exotic 一階內量到 4 種
   （推測特定道具各自帶圖標）。裁 7 張新模板：
   `transcendent_diamond`／`exquisite_star`／`enigmatic_spikystar`／`exotic_octagon`
   （主流款）／`exotic_burst`／`exotic_cross`／`exotic_circle`。

### 位置決定：模板進 `tests/fixtures/markers/`，不是 `assets/markers/`

既有 5 張形狀模板（`exotic_tracker_real.png` 等）放在 `assets/markers/`——整個目錄被
`.gitignore` 排除，是機器本地素材；既有 `find_tracker` 形狀測試已經用
`if not os.path.exists(...): pytest.skip()` 容忍缺席（全測試套件裡 23 個 skip 有一部分
來源正是這裡）。`tuning-from-incidents` skill 明講這是要避免的舊坑：「不可放
assets/，別台機器 clone 下來測試就 skip，無樣本的修復＝下次必迴歸」。新模板改放
`tests/fixtures/markers/`（進版控），production 執行時仍讀 `assets/markers/`——新增
模板時另外複製一份過去（純檔案複製，不進 git，使用者確認要做）。

`_load_marker_templates()`（`main.py`）對 `assets/markers/*.png` 是**盲 glob**，這 7 張
複製過去後會自動被 `find_tracker` 的 `self._shape_templates` 一併吃到——不是只有
`detect_tracker_core` 用得到。分數只會增不會減（`best_outline_match` 取多模板 max），
理論上不會讓既有真陽性變陰性，只可能讓某個原本卡在門檻下的候選過閘；已跑全測試套件
驗證無新增失敗（見下方回歸）。

### 量測（91 張標註 fixture）

| 模板 | tier | 自我比對 edge（來源幀，非跨場次） | 場次證據 |
|---|---|---|---|
| `transcendent_diamond` | Transcendent | 0.994 | 139/153/162（3 場一致） |
| `exquisite_star` | Exquisite | 1.000 | 128/147/148/197/205（5 場一致） |
| `enigmatic_spikystar` | Enigmatic | 0.998 | 196（1 場） |
| `exotic_octagon` | Exotic（主流） | 1.000 | 138/158/161/198/199（5 場一致） |
| `exotic_burst` | Exotic（變體） | 0.963 | 159（1 場） |
| `exotic_cross` | Exotic（變體） | 0.997 | 145（1 場） |
| `exotic_circle` | Exotic（變體） | 未獨立量測（回歸測試已收，僅自我比對數字沒印） | 207（1 場） |

⚠ 這是模板對**自己裁出來源那張圖**的比對分數，證明裁圖/載入管線本身沒問題，不是
跨場次泛化能力的量測——`exquisite_star`／`exotic_octagon` 各有 5 場一致，換另一場
測應該也高；但 `exotic_burst`／`exotic_cross`／`exotic_circle` 只有單一場次來源，
換到別的幀會多準完全沒把握，這正是下方「待實機驗證」要盯的重點。

兩側夾：81 張 decoy/empty 負例掃過形狀 fallback（`profiles=[]` 逼它只能靠外框+黑邊）
只 1 張假陽性（harvest 133），跟色彩路徑既有的假陽性是同一張 fixture——H057 家族
同色/同形地形殘留，非本次新引入的失效模式。

### 回歸

`tests/test_vision.py` 新增 10 項：模板載入健檢 1、7 個外框樣式各自形狀命中 1（用
`profiles=[]` 逼形狀路徑獨立成立，不偷靠色彩候選；Exotic 4 種變體全收）、假陽性率
守門 1（≤2）、D15 範圍邊界守門 1（harvest 158 不得被形狀 fallback 撿走）。全部用
91 張批次裡的實機 fixture。
`uv run pytest -q` 全數通過（含既有 `find_tracker` 回歸，驗證新模板混進
`self._shape_templates` 沒有引入新失敗）。

### ⚠ 待實機驗證

下一輪手動瞄準遇到色彩清單沒覆蓋的新道具時，log 應出現 `core: 色彩零候選，嘗試形狀
fallback` 接 `core形狀候選 ... -> OK`，而非直接退回放大手選。反指標：形狀命中後開火
位置明顯偏離框——代表某個 tier 的模板配到了錯誤位置，需要回頭檢查該 tier 是否其實
不只一種外框（比照 Exotic 的前例）。`exotic_burst`／`exotic_cross`／`exotic_circle`
三個變體模板各只有單一場次證據，信心低於 `exotic_octagon`，優先觀察這三個是否誤觸發。

## H077（2026-08-07，使用者回報「每次清空背包都清不乾淨」）：面板清空的游標鎖定釋放
只放左鍵，右鍵拖曳（俯仰/瞄準）中途拋例外沒有 try/finally，卡住的右鍵讓所有後續點擊
落空

### 一句話根因

`_clear_panel_filter_once` 的游標釋放（a8dfca6，2026-08-06）只呼叫 `ic.mouse_up()`
（`pydirectinput.mouseUp()` 預設 `button='primary'`＝左鍵），但 `aim_move`／
`_drag_vertical`（`pitch_reset` 底層，俯仰歸位／瞄準漂移全靠它）按住的是**右鍵**，且
這兩個函式在此修復前完全沒有 `try/finally`——中途任何一步拋例外，右鍵就永遠卡在按住
狀態，Roblox 的攝影機拖曳鎖定跟著卡住，之後任何 `click_at` 都落在鎖定中心而非目標
座標。只放左鍵的既有修復對這條路徑是 no-op。

### 症狀與證據

實機快照 `panel_zero_failed`（`snapshot_index.jsonl`）：2026-08-06 22:24:34 與
22:28:03 相隔 3.5 分鐘、各自跑完一輪 8 次重試，**面板像素完全相同**（`Leprechaun 28
/ Siogyne 242 / Cloverstone 1,239 / Imbollyx 1,183 / Fortunatum 5,176 / Celtisalt
8,165 / Pyrisand 202 / Auriclase 4,873`，一個字元都沒變）。清空機制的原理是打字母
`w` 觸發遊戲自己的篩選器重新整理（H071）——這 8 個礦名**沒有一個含 `w`**，若字元真的
送進篩選框，遊戲篩選器會把全部 8 列濾掉；紋風不動代表兩輪合計最多 64 次按鍵、16 次
點擊完全沒有送進 TextBox，是輸入沒送達，不是判斷錯誤。`game_data.classify_found_ore
("Leprechaun")` 回 `('rare', tier='Exquisite')`——真的是白名單礦卡在面板上。2026-08-05
11:28/11:30 的另一組 `panel_zero_failed` 同樣卡著 `Fortuitous`（rare/Exquisite）與
`Feebrechaun`（rare/Exotic）。這兩次失敗都發生在 a8dfca6（17:47:50 commit、19:14-19:17
重開後生效）之後，證明左鍵釋放不夠。

### 根因分析

`states.py` 的 `resolve_state_transition`：`NEEDS_HUMAN` 且 `human_cleared`（玩家按
▶️）直接轉 `MINING`（不經 `HARVESTING`），對應 `main.py` `_on_enter(State.MINING)`
（約 3614 行）跑 `_clear_panel_filter()`。`pydirectinput.mouseUp`/`mouseDown` 的
`button` 參數預設是 `'primary'`（左鍵）——`ic.mouse_up()` 沿用這個預設，從未釋放右鍵。
`input_control.aim_move`／`_drag_vertical` 用右鍵拖曳轉視角/歸位俯仰，`mouseDown` 與
`mouseUp` 之間**沒有 try/finally**：`moveRel` 或任何一步拋例外（win32 呼叫失敗、執行
緒被中斷）都會讓右鍵停在按下狀態，往後任何嘗試釋放「游標鎖定」的程式碼如果只放左鍵，
救不回這個狀態。

### 對策

1. `input_control.aim_move`／`_drag_vertical`：`mouseDown(button="right")` 後的整段
   包 `try/except/finally`，`finally` 一律 `mouseUp(button="right")`，`except` 額外
   記一筆 WARNING（`aim_move 中途例外，強制放開右鍵` / `_drag_vertical 中途例外，強制
   放開右鍵`）後 re-raise——沿用既有呼叫端的例外處理，只是保證右鍵一定被放開。
2. `ic.mouse_up`/`ic.mouse_down` 加 `button: str = "left"` 參數（預設值保留所有既有
   呼叫端行為不變）。
3. `_clear_panel_filter_once` 的游標釋放序列加一行 `ic.mouse_up("right")`，與既有的
   左鍵/W 釋放並列——兩個按鍵對「沒有真的按著」都是 no-op，一律放開無副作用。

### 附帶修復：`miningbot.log` 死頻道（不是同一個 bug，但擋住了本次診斷）

調查過程中發現 `miningbot.log`（`self.logger`，`_clear_panel_filter` 的所有 WARNING
都寫在這裡）從 **2026-08-03 14:27:54 就完全停寫**，卡在 1,999,982 / 2,000,000 bytes
（`maxBytes`），`backupCount=5` 卻連一個 `.1` 都沒生出來。根因：`setup_logging`
對 `miningbot`／`uvicorn`／`websockets` 三個 logger **各自呼叫 `_make_file_handler`
開了三份獨立的檔案 handle**，全部指向同一個 `miningbot.log`；其中一個先滾到
`maxBytes` 觸發 `doRollover()` 要 rename 時，另外兩個 handle 還開著同一個檔——Windows
上 rename 撞到還開啟的 handle 直接 `PermissionError`；`pythonw` 沒有 stderr，
`logging.Handler.handleError` 靜默吞掉，之後四天所有 `self.logger` 呼叫（含本次面板
清空失敗的 WARNING）全部消失，只能靠 `snapshot_index.jsonl` 與 `heartbeat.log` 的時間
軸硬湊證據。已修：三個 logger 改共用同一個 `RotatingFileHandler` 實例（`setup_logging`
內只 `_make_file_handler` 一次），不再各開一份檔案 handle。

### 回歸

`tests/test_input_control.py`：`test_drag_vertical_releases_right_button_when_moverel_raises`／
`test_aim_move_releases_right_button_when_moverel_raises`（monkeypatch `moveRel` 拋
例外，斷言 `mouseUp("right")` 仍被呼叫）。`tests/test_giveup_rescue.py`：
`test_clear_releases_right_mouse_button_too`（斷言 `_clear_panel_filter` 同時放開
`"left"` 與 `"right"`）。`tests/test_diagnostics.py`：
`test_setup_logging_adopts_uvicorn_logger` 新增斷言收編 logger 與主 logger 共用同一個
handler 實例；新增 `_reset_main_logger()` 供需要驗證「這次呼叫真的開了新檔」的測試
重置主 logger（否則測試之間互相污染同一個 process-wide `logging.getLogger("miningbot")`
單例）。全套 `uv run pytest -q` 2537 passed（log 修復後另外驗證，input_control/
giveup_rescue 修復同批跑過）、`ruff check` clean。

### ⚠ 待實機驗證

下一次面板清空失敗時，`miningbot.log` 應該能正常看到 `面板歸零：...` 系列 WARNING
（證明死頻道已修）。若清空仍然失敗，log 裡的墨量/字寬數字＋`panel_zero_failed`
快照能直接判斷是否還是同一種「完全沒變」的輸入未送達模式；若面板礦名這次**有**變化
（部分列消失/數量變動），代表右鍵不是（唯一）根因，需要回頭查 `_focus_roblox()` 的
視窗焦點路徑。右鍵拖曳例外目前沒有實機重現樣本（`moveRel` 罕見失敗，回歸測試用強制
raise 模擬）——這條 try/finally 是結構性補強而非已量測到的必然觸發點，先觀察下一輪
`_log.warning("aim_move 中途例外...")`／`_drag_vertical 中途例外...` 有沒有真的出現。
