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
- **對策**：(1) **傳送驗證區域化＋雙訊號**——`_click_surface_verified` 改量 `reentry_game_region`，`mean ≥ 12` OR `frac ≥ 0.05`（兩側餘裕 4.8x/20x 起）；(2) **探測式開場**——點擊當探針：判「未傳送」不通知不拍圖，每 `reentry_open_retry_wait_s=20s` 再點一次，解凍後下一擊自然傳送成功流程續走；`reentry_open_budget_s=300s` 用盡才通知一次附截圖（全黑＝虛空、有畫面＝凍結）；H043 虛空偶發成功也被同一迴圈吸收；(3) 同輪新增**手動回礦**：Discord `回礦`/`reenter` 指令＋STUCK 警告 🏠 反應鈕（`states.decide_transition` 新旗標 `manual_reentry`；MINING/NEEDS_HUMAN/RESET_WAIT 可觸發、RESET_WAIT 下＝繞過 reset_complete 的人工強制；用途不限卡死，ledger 記 `trigger` 來源）。
- **fixture**：`tests/fixtures/reentry/h044_{frozen,alive_static,teleport}_{a,b}.png`＋`tests/test_reentry_fixtures.py` 兩側夾回歸。
- **設計**：`docs/superpowers/specs/2026-07-14-manual-reentry-and-freeze-gate-design.md`。
- **commit**：（本輪工作樹）
