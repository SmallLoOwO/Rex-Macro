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
- **未解／不擋結案**：(a) **偵測器在 DIR4 手動圖上的全畫面最佳命中是 (959,547)＝角色的臉（0.613），不是 (983,435) 的真框**——候選排序取 `colored_frac` 最高者，角色飽和衣裝/膚色可壓過真框；這代表全畫面兜底在角色遮擋場景可能打到角色身上，是**新引入的風險**，需另案處理排序準則（改用 edge 排序或加角色區抑制）。(b) 近失外露閘仍是純 `colored_frac > 0.40`，衣裝洗版的**來源**未修（只修了重複計數）；改 colored＋edge 雙條件可能誤殺薄暗小框（edge 0.19~0.22 族），需備 fixture 兩側夾後單獨處理。(c) sweep 的 dir5（16:20:38）與開火時的 dir5（16:22:30）構圖差異極大，姿態記帳已核對自洽（giveup 回轉 net=7 → 手動掃 8 次 ≡ 0 → rot=-3 ≡ dir5），推測為 camera collision 解算差異，證據不足以定裁。(d) 八方位 sweep 在鏡頭卡進角色特寫時整輪全空的問題完全未動——本案修正只把「人工介入後仍失手」變成「人工介入會中」，不減少交人工次數。
- **調查過程的教訓（方法面）**：前兩輪分析先後誤判為「使用者指到空地」與「ROI 半徑不足」，兩次都是**從候選清單反推使用者意圖、未向使用者求證所看的圖**所致——第一次把 `5 D2` 誤認成候選⑥的 D4（D4 格心 (1120,945)，與實際開火點差 540px，本可立即否證）。**指令類事故必須先確認「使用者看到的那張圖」與「使用者輸入的原文」兩項一手證據，再談偵測門檻。**
