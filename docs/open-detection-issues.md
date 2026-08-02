# 待修：偵測與瞄準的已知缺口

**這份是「已量測、未修復」的問題清單**，不是設計規格。每條都附實機幀量測與可重跑指令；
修好一條就把它整段搬進 `incidents.md`（給 H 編號）並從這裡刪掉。

現行行為仍以程式、測試與 `miningbot/config.py` 為準。已修復的部分見
`incidents.md` H056、**H057（原 D01/D02：同色黏連救援＋confirmed 重錨，2026-07-20 修復）**。

---

## D03（2026-07-20，harvest 097）：近失候選外露閘只看 colored，角色衣裝會洗版

### 症狀

097 giveup 時 Discord 發的 9 個近失候選**全部是角色身上的紅武器與彩虹碎片衣裝**，
沒有一個是真框。使用者只能在垃圾清單裡挑，必然指錯。

### 量測

外露閘是純 `colored_frac > 0.40`（shape 階段的 `collect_rejects` 隱含此條件）。
097 DIR1 那群 `colored` 高達 **0.88~0.90**（飽和紅／彩虹輕鬆過閘），但 `edge`
僅 **0.20~0.34**（< thr 0.42）且 `ring_ok=False` → 全 hard_rej，卻仍被外露成候選。

### 已修的部分

- H056 修了**重複計數**（`_dedup_rejects`：同層同方位 <60px 合併）。
- H057 讓救援碎片**刻意不進** `collect_rejects`（牆面碎片不再新增洗版來源），
  且黏連／借分場景的真框現在多半直接 confirmed——走不到 giveup 就不會發近失清單。

### 為何暫緩（2026-07-20 量測結論）

「colored **且** edge 雙條件」在現有信號上**兩側夾不出來**：

| 側 | edge |
|---|---|
| 誤收側：097 裝備 | 0.20~0.34 |
| 誤收側：紅緞帶裝備（H040 場景 docstring） | 峰值 0.21~0.38 |
| 真值側：薄暗小框族（全方位全空兩型根因） | 0.19~0.22 |

任何 edge 門檻不是放進裝備就是殺掉薄暗小框。可能的分離信號是 **ring_ok**：
097 外露的裝備候選全為 `ring_ok=False`（ring −0.45~−0.56），薄暗小框理論上環形
結構強——但**尚無薄暗小框 fixture 的 ring_ok 實測**，補齊兩側夾前不動。

---

## D04（2026-07-20，harvest 097）：同一方位在 sweep 與開火兩個時點構圖差異極大

### 症狀

097 的 dir5 在 sweep（16:20:38）與開火（16:22:30）兩張幀構圖**完全不同**
（正面大頭特寫 vs 背面）。姿態記帳已核對自洽：giveup 回轉 `net=7` → 手動掃 8 次
（≡ 0 mod 8）→ `rot=-3` ≡ dir5，沒有算錯。

### 為什麼要記

衍生風險是**格子座標跨時間不可重現**：使用者在快照上指的格子，開火時可能已經指向
別的東西。回礦側已有同族守門（`incidents.md` H050 的「快照 vs 現場」漂移檢查，
`reentry_remote.zoom_drifted`），**挖礦瞄準側目前沒有任何等價守門**。

### 待查

推測為 camera collision 解算差異（鏡頭卡進角色時，同一 yaw 兩次解出不同機位），
但證據不足以定裁。若成立，H050 那套「快照同格 vs 現場同格比對超標就警告」可以直接
移植到 `_execute_remote_fire` 的對齊後、重找前。

---

## D05（2026-07-20，harvest 097）：鏡頭卡進角色特寫時，八方位 sweep 整輪全空

### 症狀

097 的 sweep 八個方位全部 `no tracker` → 交人工。畫面顯示鏡頭卡在角色特寫
（camera collision），角色身體塞滿畫面中央，礦區幾乎看不到。

### H057 之後的修正認知

**097 的 dir4 漏抓已證實不是特寫害的**：sweep 那幀真框 `(983,436)` 就在畫面上，
是同色黏連（D01）吃掉的，H057 救援後同幀直接命中 edge=0.62。特寫遮擋仍是獨立
問題（其他方位確實被角色塞滿），但它對「全空」的貢獻比原先以為的小——先觀察
H057 上線後綠世界 giveup 頻率再決定要不要做「偵測到特寫就先退鏡頭／移動再掃」。

### 為什麼要記

要真正降低打擾頻率，得處理遮擋本身（偵測到特寫就先退鏡頭／移動再掃），
這是獨立且較大的題目。

---

## D06（2026-07-21 查出；2026-08-01 以玩家標註第二批複驗仍在，harvest 087~101 與 131~150 兩批）：sweep 的 preexist 差分把**起始方位**的 reference 套在**全部八個方位**上——真框被當成「掃描前就存在」殺掉

### 症狀

087/088/089/090/092/096/098/100/101 九場 chill 觸發後，sweep 八方位全 `no tracker`
→ giveup 交人工。但這些幀上**肉眼看得到追蹤框**（下表 8 個，已逐一放大確認）。

### 一句話根因

`_sweep_for_tracker(self, excl, ref)`（main.py）在 8 個方位的迴圈裡重用**同一個**
`ref`，而 `ref = _pre_scan_ref` 只在進場那一刻（起始方位、`prepare_scan()` 置中後）
拍一次。轉到其他方位後，reference 的同一塊 bbox 對應到世界上**完全不同的地方**；
礦坑到處是綠牆，`ref_fill > 0.15` 很容易成立 → 真框被判 `rej(preexist)`。

`preexist` 差分對**螢幕空間**的靜態物（角色裝備、UI）是有效的（它們在任何方位都落在
同一個螢幕位置，reference 裡也在同一位置）；失效的只有**世界內容**——這正是真框所在。

### 量測（實機幀，可重跑）

用該輪 `dir0` 幀當 reference 代理（實機 ref 就是在起始方位拍的），H057 救援開啟：

| 輪次 | 框型 | 座標 | 無 reference | 用起始方位 reference |
|---|---|---|---|---|
| 101 dir4 | A 薄荷四角星/亮綠心 | (836,181) | 命中 | 命中 |
| 090 dir4 | B 薄荷四角星/藍心 | (1271,340) | 命中 | 命中 |
| 090 dir5 | B | (884,413) | 命中 | **沒抓到** |
| 090 dir6 | B | (381,273) | 命中 | **沒抓到** |
| 088 dir4 | B | (900,473) | 命中 | 命中 |
| 087 dir1 | C 黃尖刺太陽/暗心 | (1571,654) | 命中 | **沒抓到** |
| 087 dir2 | C | (1039,603) | 抓到別的 | 沒抓到 |
| 087 dir3 | C | (663,617) | 命中 | — |

  → **無 reference 7/8 命中；用起始方位 reference 只剩 3/8。**

單點證據：087 dir1 的真框 bbox 在 reference 幀的 `ref_fill = 1.00`（log 實錄
`tracker候選 (1571,654) area=1739 fill=0.46 ref_fill=0.99 -> rej(preexist)`）；
090 dir6 為 0.23。兩者都遠超 0.15 門檻，但那塊「綠」是**別的方位的牆**。

### 誤收側（若直接拿掉 reference，全 72 幀會多抓到什麼）

全 72 幀跑 `find_tracker`（不帶 ref、H057 救援開）共 24 個非真框命中，
**全部是 Windows 工作列**，不是遊戲內容：

| 位置 | 次數 | 是什麼 | edge |
|---|---|---|---|
| (824,1055) | 22 | 工作列圖示（Discord 等） | 0.30~0.38 |
| (468,1017) | 1 | 工作列資料夾圖示 | 0.45 |

兩側夾：真框 y 最大 654（8 個全在 181~654）vs 工作列 y 最小 1017 — 中間有 363px 空隙。
**但不可直接用 y 門檻切**：H026 的真框就在 (1288,1020)，`tracker_margin_frac`
當初 0.10→0.02 正是為了收回那種底緣框。正解是**把偵測範圍限縮在 Roblox 視窗內**
（`capture.grab()` 目前抓整個螢幕，含標題列與工作列，見任一 `sweep_empty_*.png`），
工作列本來就不該進偵測；`window.py` 已知道視窗矩形。

### 為何沒有直接修（留給下一手裁定）

拿掉跨方位 reference 之前得先補「限縮在遊戲視窗內」，否則工作列會變成新的假陽性源。
而 reference 本身還有三條路可走，各有代價，**需要先裁定**：

1. **掃描前先轉一圈拍 8 張 reference**——語意最正確，但每輪多花一整圈旋轉時間。
2. **只對起始方位套差分，其餘七方位不套**——便宜；靠形狀 confirmed（0.42）獨撐。
   本頁量測顯示這樣在 72 幀裡只多出工作列假陽性（修掉視窗範圍後即為 0），但樣本
   僅四場綠世界，未涵蓋角色裝備吃重的場景。
3. **把差分從「同色佔比」改成「同內容比對」**——`ref_fill>0.15` 只問「這裡以前有沒有
   同色的東西」，訊號極弱；改比 reference 與現幀該 bbox 的實際像素相似度，
   螢幕空間靜態物（工作列/裝備）相似度≈1 必拒、真框所在處內容全變必收。
   最有原則但要另補裝備負樣本做兩側夾。

### 重跑指令

實機幀在 MSIX LocalCache（`snapshots/review/*_sweep_empty_dir?.png`，九場 72 幀）。
上表的真框座標即 ground truth；`_TRACKER_COLORS` 綠系掃不到 C 型黃框（087 dir3 是
用 `find_tracker` 全幀跑出來才補進表的），列清單時要連黃/藍系一起掃。

### 2026-08-01 複驗（全螢幕版面、玩家標註第二批）：D06 仍是掃描漏抓的**主因**，且上面三條路死了兩條

玩家在 `/annotate` 標了 11 張「看得到框、bot 判空」（episode 137/144/147/148/150，
素材＋判讀在 `tests/fixtures/aim/README.md`）。逐關拆解後**沒有一關是門檻問題**：

- 形狀 `edge` 在標註處全部 **1.000**；
- 7/11 的核心與同色地形黏成超大輪廓（最大 949×444）→ 走 H057 救援，子分割後是乾淨的
  25×25／area 576，**全過救援子閘**，排名也擠得進 `rescue_max=12`；
- 9 張可測的（有同場 `dir0` 幀當 reference 代理）**6 張**死在 `ref_fill > 0.15`，
  `ref_fill` 分別是 1.00／0.78／0.70／0.22／0.16。

**被否決的修法（各附兩側夾，別再重試）：**

| 修法 | 收側 | 誤收側 | 判定 |
|---|---|---|---|
| ref mask 加亮度閘（只有 `V ≥ 150` 的參考像素才算 preexist） | 6 張真框的參考底色是**暗綠牆**（V 中位 53~134）→ `ref_fill` 全掉到 0.00，救回 5 張 | 同一批幀裡**多放行 85 個**候選，位置集中在 x 900~1000／y 550~750＝玩家自己的角色 | ✗ |
| 選項 3「改比像素相似度」 | 真框處相似度 0.16／0.24／−0.07／0.17／0.35 | 現行被 preexist 正確擋掉的 46 個候選 中位數就是 0.235、26% ≥ 0.5 | ✗ 無 gap |
| 選項 2「只對起始方位套差分」 | — | 192 幀不帶 ref 重放 → **161 個命中**，逐格看過：綠苔地形、角色身體與裝備、製作面板／`Next >` 按鈕，**沒有一個是真框** | ✗ |
| hotbar 進 `_tracker_exclusions()`（擋 ep134 那組誤收） | ep134 對著 hotbar 開了一發 D3（`d3_fire_dir2_772x1017`） | hotbar 展開成 10 格時橫跨 x 628~1290、y 988~1065，H026 的真框就在 (1288,1020) | ✗ 同一塊螢幕兩邊都要 |

⚠ **選項 2 的舊結論已作廢**：2026-07-21 那次量到「不帶 ref 只多出工作列假陽性」，
所以本條目原本寫著「補完視窗限縮就能走選項 2」。全螢幕之後工作列確實不再進畫面
（`capture.grab()` 抓到的整張都是遊戲內容），但誤收側從 24 暴增到 161——中間差的是
**H068 的二維軟收**（`shape_soft_edge=0.35` + `shape_soft_colored=0.80`，2026-07-31）：
角色與地形正好落在那條軟收帶裡，現在是 `reference` 這道差分在獨力擋住它們。
兩個功能互相綁死了，動任何一邊都要重跑另一邊的誤收側。

**於是只剩選項 1（掃描前先轉一圈、每方位各拍一張 reference）**，代價是每次 chill
episode 多一整圈旋轉（~19s，發生在 D2 掃描**之前**，不吃追蹤框壽命）。
不要動 `tracker_shape_*`／`tracker_rescue_*`／`tracker_margin_frac`——量測顯示那幾關
對這批素材本來就全過。

### 2026-08-01：選項 1 已實作（`sweep_per_dir_reference`，使用者裁定「如果會比較好就做」）

先補上決定可行性的那一個量測：**轉滿一圈回得到同一個朝向嗎**。ep133 同一場掃了兩輪
（sweep + reharvest_sweep），八個方位逐一相位相關：

| 方位 | dir0 | dir1 | dir2 | dir3 | dir4 | dir5 | dir6 | dir7 |
|---|---|---|---|---|---|---|---|---|
| 轉一圈回來位移 | 0.0px | 0.0px | 0.0px | 0.0px | 0.0px | 0.0px | 0.0px | 0.0px |

次像素等級，所以「先轉一圈拍 8 張、掃描後再轉一圈比對」兩趟是對齊的，不會把 45° 錯位
換成另一種錯位。

實作：`Bot._capture_dir_references()` 在 `_run_scan()` **之前**轉一圈拍 8 張
（掃描後框才出現，先拍才不會把活框寫進排除基準＝H026 自我致盲），
`_sweep_for_tracker` 改用 `_dir_reference(abs_dir, ref)`。降級全部退回今日行為：
旗標關掉、任一次旋轉被吃（整組作廢並轉回原方位）、俯仰層對不上（`_pre_scan_refs_layer`）
→ 一律沿用單張 ref。`_reharvest_sweep(refresh_ref=True)`（H118 FOV 變過）連方位 ref
一起重拍，預設路徑則沿用進場那組（H026）。

⚠ **離線無法驗證**：語料裡沒有任何「掃描前的各方位幀」（快照都是掃描後拍的），
所以收側只有推理與上面那張位移表，沒有重放證據。**下一場實機驗收**：
`harvest.log` 要出現 `方位 reference（進場）：8 張已拍`；漏抓率與
`rej(preexist)` 行數應同時下降。反指標：假陽性變多（尤其是角色身上的裝備）
→ 把 `sweep_per_dir_reference` 關掉即回到今日行為。
**俯仰層仍是舊行為**：up/down 層的 sweep 用的還是 mid 層那張單張 ref
（那兩層要各自補拍就得各自重掃一次 D2），本批 6 張誤殺裡有 2 張屬於這型。

---

## D07（2026-07-29，harvest 121）：`sweep_pitch_step_px=185` 的 up 層必定撞出 camera collision，down 層又壓過頭

### 症狀

121 是俯仰層掃描**啟用後的第一場**（`sweep_pitch_enabled=True`、`step_px=185`、
`center_back_px=370`）。up 層八方位全空、down 層才撈到唯二兩顆 Gelisol。
原本歸因於 H065 的 D2 toggle，**實機幀顯示不是**（或不只是）。

### 量測（實機幀，肉眼判讀；MSIX LocalCache）

三層同方位對照 + 每次拖曳的前後全幀（`_pitch_drag_verified` 落盤的 `trace/pitch_ok_*`）：

| 幀 | 內容 |
|---|---|
| `review/…121_sweep_empty_dir0.png`（mid） | 隧道水平視角，牆-地交界 y≈620、角色高 ~170px、鏡頭正常吊臂距離 |
| `review/…121_sweep_empty_dir7.png`（mid） | 同上，交界 y≈700 |
| `review/…121_sweep_empty_up_dir0.png` | **角色塞滿畫面中央**，鏡頭貼身；交界掉到 y≈950 |
| `review/…121_sweep_empty_up_dir4.png` | 角色＋背包塞滿中央，底部只剩一條地面 |
| `review/…121_sweep_empty_up_dir7.png` | 角色佔滿，背景全是貼近的地面/牆體 |
| `trace/20260729_024143_*_pitch_ok_{before,after}.png` | up nudge −185px 的前後：before＝正常隧道視角，after＝鏡頭已被拉到貼身 |
| `trace/20260729_024308_*_pitch_ok_before.png` | up 層**掃完八方位後**的視野：角色佔滿約 70% 畫面 |
| `trace/20260729_024312_*_pitch_ok_{before,after}.png` | down nudge +185px 的前後：before＝水平，after＝俯視地面、鏡頭距離仍正常 |
| `review/…121_sweep_accepted_dir7_1440_162.png` | down 層命中，框在 **y=162** |
| `review/…121_sweep_accepted_dir0_896_154.png` | down 層命中，框在 **y=154** |

log 側五次拖曳全部判「生效」，被吃不是原因：

```
02:41:38 俯仰層 up 歸位   mean=5.44   （冪等歸位，本來就該接近 0）
02:41:43 俯仰層 up nudge -185px  mean=7.79
02:43:08 俯仰層 down 歸位 mean=14.38  （從 up 拉回 mid，變化最大）
02:43:13 俯仰層 down nudge 185px mean=9.00
02:45:47 收尾 挖礦標準角歸位 mean=8.42
```

### 兩個結論

1. **up 層是自己製造出 D05 的條件**。抬高俯仰＝鏡頭吊臂往下擺進地面 → Roblox 把鏡頭
   拉到貼身 → 角色身體蓋住畫面中央，而候選 ROI 正好在中央。查過的三個方位（0/4/7）
   加層尾幀**都**是這個狀態，不是某個方位運氣不好。up 層八方位全空是幾何必然。
2. **down 層壓太低**。全場唯二命中落在 y=154／162（畫面最上 15%），代表真正有料的
   帶狀區在畫面之外、只擦到下緣進來一點。以 70° 垂直 FOV 反推，那兩顆的仰角其實
   還在 mid 層的視野帶內。

⚠ 交界位移換算角度會被鏡頭距離（碰撞）污染，上面的 y 值只能當「方向與量級」，
不是精準的度數量測。

### 待修

`config.py` 的註解已預留這條退路：「驗收發現視野抬得太多/太少或方向相反時，
只改這個數字或它的正負，不動任何邏輯」。下一步就是把 `sweep_pitch_step_px`
往下調（185 → 100~120 量級）再跑一場，收兩側夾：

- up 側要看的是「角色**不再**塞滿中央」且交界確實往下移；
- down 側要看的是命中不再擠在畫面最上緣。

### 順帶存疑（證據不足，別當結論）

down 層那次重掃 D2 距上次掃描 **87.3s**（log 實錄），也就是 down 層拿到的是**新鮮的**
掃描標記，mid 層那次已經很舊。「down 層才撈到」有可能主要是重掃的功勞而非俯仰的功勞。
要分開，得讓某一場的 mid 層在同樣新鮮的掃描下重跑一次。

### 追加量測（2026-07-31，harvest 144；`step_px=100` 的第一場）

`sweep_pitch_step_px` 已於 `158f8c4` 調成 100，144 是這個值的第一場俯仰層場次。
**up 側沒有修好，down 側修好了。**

| 幀 | 判讀 |
|---|---|
| `review/…144_sweep_empty_dir4.png`（mid） | 正常隧道視角，角色高約 200px |
| `review/…144_sweep_empty_up_dir4.png` | **角色軀幹塞滿畫面中央**，看不到世界 |
| `review/…144_sweep_empty_up_dir2.png` | 更糟——角色臉部特寫佔滿右半畫面 |
| `review/…144_sweep_empty_up_dir0.png` | 角色正面佔中央，但**上緣仍看得到世界**（見 D08） |
| `review/…144_sweep_empty_down_dir4.png` | 牆-頂交界 y≈320、地面大片入鏡、鏡頭距離正常＝**俯視成立** |
| `review/…144_sweep_empty_down_dir0.png` | 同上，交界 y≈320 |
| `review/…144_sweep_accepted_dir4_964_368_aim.png` | down 層 dir4 命中 (964,368)，**不再擠在最上緣**（121 是 y=154/162） |

log：三層的重掃 D2 間隔分別是 32.0s／34.8s（皆 ≥30s＝重掃真的生效），
down 層 `sweep abs_dir=4: stable (964,368) edge=0.47`，隨後
`sweep verify lost target at abs_dir=4` → 重掃全空 → 交人工。

**結論：100px 對 down 是對的，對 up 還是過頭。** up 層的可用抬升量受限於角色與地面
的間距，在 bot 自挖的窄坑道裡幾乎沒有空間——這正是本 issue 原本列的反指標
（`.scratch/pitch-relative-nudge/issues/00`）：再往下調到 up 不撞的量級，up 與 mid
的視野就重疊到沒有新內容。

下一步不是繼續調這個數字，該評估的是**換機制**：把鏡頭拉到最近（第一人稱）再抬頭，
沒有吊臂就沒有碰撞。代價是畫面構圖與 D3 點擊座標鏈都要重驗，屬於新設計不是調參。

---

## D08（2026-07-31，harvest 144）：真框被頂端 HUD 橫幅切成 17px 高，卡在 `bh >= 18` 的尺寸閘外一個像素

### 症狀

144 的 up 層 dir0（絕對方位 0）畫面裡**有一顆真的追蹤框**，位置在畫面正上方、
被 `Mine Capacity / Depth / $` 那條橫幅蓋掉上半。整場 log 對那個座標
**連一行 `tracker候選` 都沒有**——不是被拒，是根本沒進候選清單。
最後交人工的近失候選 ⑨（方位1・約C2・分數0.25）是角色肩膀的一角，
就在那顆真框正下方——使用者看到的「礦物位於近失候選 ⑨ 的上方」就是它。

### 量測（離線重放 `find_tracker` 的 HSV 階段）

素材：`review/20260731_034044_047175400_000022_144_sweep_empty_up_dir0.png`
（MSIX LocalCache；4× 放大裁圖確認過是黃框綠心的標準追蹤框，非 UI 圖示）。

用 production 的第一組色域 `H18-78 / S≥80 / V≥50` 跑 `findContours`，那顆框在
畫面上緣拆成三個輪廓：

```
bbox (1004, 108, 27, 17) area 415.0   ← 主體
bbox ( 990, 108, 13, 22) area 109.5
bbox (1032, 108,  6, 17) area  57.0
```

`vision.find_tracker` 的尺寸閘是 `18 <= bw <= 80 and 18 <= bh <= 80`。
主體 **bh=17**，差一個像素被 `continue` 掉；另兩塊是被橫幅切開的碎片，寬度不足。
`area=415` 反而過得了 `area < 400` 的下限——擋掉它的**只有高度**。

三塊 bbox 的 `y` 全是 108，正是橫幅底緣：框的上半不是「出畫面」，是**被 UI 蓋住**。

### 待修（別直接改數字）

把 `18` 放寬會同時放行大量細長噪點（同幀 `(1034,170,28,7)`、`(1067,135,19,6)`
之類的碎片一堆），而且 `abs(bw-bh) > max*0.5` 的方形比例閘對「被切一半的框」
本來就會失效。可能的方向，都要先收兩側夾再動：

1. 把頂端橫幅那條矩形加進 `exclude`，讓被它切開的碎片能重新合併（要先量橫幅的
   實際範圍，且 `exclude` 目前語意是「中心落在裡面就拒」，不是「填補」）。
2. 對貼齊畫面上／下緣的候選改用單邊尺寸閘（只要 `bw` 合格、`bh` 是被裁的，就放行
   進形狀確認讓它自己仲裁）。
3. 什麼都不做，交給 D07 的「換機制」——如果 up 層改成第一人稱抬頭，那顆框會落在
   畫面中段，尺寸完整，這個閘根本碰不到。

反指標：只把 `18` 改小、不加任何補償，會把 D03（角色衣裝洗版近失候選）整組放大。

## D09（2026-07-31，harvest 133 dir4；H068 修復後的殘留）：`edge=0.33` 的真框與粉紅岩層完全同分，二維軟收也救不回

### 症狀

`20260731_001251_253131500_000190_133_sweep_empty_dir4`：真框在 (979,550)，玩家標成
`false_negative`。H068 的二維軟收（`edge≥0.35` 且 `colored≥0.80`）把同批其他 5 顆都救回來了，
這顆沒有。

### 量測

| 東西 | edge | colored |
|---|---|---|
| 真框 (979,550) | 0.33 | 0.86 |
| 同幀角色 (959,633) | 0.33 | 0.73 |
| H026 場景粉紅岩層 (1154,937) | **0.33** | **1.00** |

真框與岩層在**兩個軸上都不可分**（岩層的 colored 還更高）。把 `soft_edge` 降到 0.33
會讓 `assets/bottom_edge_tracker_scene.png` 直接對岩層開火——
`test_find_tracker_bottom_edge_scene_h026_recovered_by_config_margin` 會紅，那是實機幀，不是合成圖。

### 待查方向（都要先收兩側夾）

1. **暗邊環帶**：`vision.detect_tracker_core` 的 `border_dark_frac_min` 這一軸（真框心 0.35、
   空格 0）在 `find_tracker` 這邊完全沒用上。岩層/UI 沒有「亮心被暗邊包住」的結構。
   要做得把候選 bbox 帶進形狀確認迴圈（目前只傳 `(colored, cx, cy, ring_ok)`）。
2. **多幀穩定**：sweep 本來就雙幀；岩層在鏡頭微動下 bbox 會飄，框不會。現行雙幀穩定
   在形狀確認之後才做，`hard_rej` 的候選根本活不到那裡。
3. 什麼都不做：這顆的代價是一次交人工，而網頁介入現在無條件推圖，玩家點得到。

### 反指標

單獨把 `tracker_shape_soft_edge` 往下調到 0.33/0.34 而不補任何第三軸——已量測會誤收岩層。

## D10（2026-07-31，harvest 128/119 玩家標註）：`detect_tracker_core` 只認飽和綠，淡薄荷框與藍菱星框的核心整組看不到

### 症狀

手動瞄準玩家點了有框的那一格，`detect_tracker_core` 回 `None` → 退回放大手選。
不是誤射，是白走一趟。

### 量測（標註素材中心 ±8px 的 HSV 中位數）

| 素材 | 核心 H / S / V | 現行 `tracker_core_profiles` |
|---|---|---|
| `20260730_200052_..._128_sweep_accepted_dir7`（淡薄荷框） | 60 / **128** / 255 | `green (40,150,150)-(85,255,255)` → S 差 22 出局 |
| `20260728_..._119_d3_miss_1`（藍菱星框） | **14** / 160 / 147 | 色相根本不在範圍內 |

同批飽和綠框核心 S≥189，`find_tracker`（走外框形狀而非核心色）兩張都收得到——
所以這是 `detect_tracker_core` 單獨的盲點，不影響 sweep。

### 為什麼還沒加 profile

- 淡薄荷：放寬 S 下限會把**去飽和的霧狀綠地形**一起放進來，目前手上沒有這類負樣本。
  可行方向是另開一條「低 S 但 V≥245」的窄 profile（真框 V=255、亮綠地形 S=190~255），
  但仍要先收一組實機負樣本才夠兩側夾。
- 藍菱星的土黃核心與泥土地形同色帶，**風險最高**：`detect_tracker_core` 命中即自動開火。
  沒有地形負樣本前一律不加。

`config.tracker_core_profiles` 的註解本來就寫著「新色 fixture 到手才加」——素材到手了，
負樣本還沒有。

## D11（2026-07-31，使用者提案並指正）：面板列底色＝tier，可當礦名之外的第二條訊號；殘留缺口是 `classify_found_ore` 的模糊假陽性

### 提案與第一次量測的錯誤

使用者提出：稀有礦都有自己的顏色，可以用顏色推斷、避開礦名讀不準。第一次量測我用
`classify_found_ore` 的 `rare`／`common` 當分組軸就下了「色相是每顆礦一色、夾不出來」
的結論——**那是錯的**。`rare/common` 是**聊天排除清單**分類，不是 tier。使用者指出
「應該是每階一色，只是漸層讓它看起來不明顯」，改用 `assets` 的真 tier 重跑就對上了。

### 量測（238 幀、1909 列；取樣窗 x120-165＝名字與數量之間的純底色帶）

| tier | 色相 H | S | 出現列數 | 例 |
|---|---|---|---|---|
| Transcendent | **210** | 255 | 185 | coinstorm、darkhelm |
| Exquisite | **128** | 143 | 30 | faedrine、leprechaun、fortuitous |
| Exotic | **46** | 189 | 105 | feebrechaun、clovara |
| Mythic | 304 | 255 | 230 | toppatrick、riches、cleavelite |
| Surreal | 166 | 221 | 319 | weevil、siogyne、vitiscus |
| 低階（資料集未收） | 0 / 30 / 280 | — | 1040 | loinnire、fortunatum、cloverstone… |

**每一階在所有幀裡都是單一色相、零變異、零重疊。** 最近的兩帶是 Exotic 46 與低階 30
（相隔 16°）→ `panel_hue_tol_deg=6` 兩側各留 10°。列底色左亮右暗是漸層，H 全程不變、
只有 V 變——所以「看起來不明顯」但量起來乾淨。⚠ 取樣窗別往左，x<10 是面板邊框
（深藍 H≈120，與列色無關；第一次量測就是踩這個坑）。

### 已實作（保守方向雙向用）

`vision.panel_row_hues` ＋ `harvester.whitelist_hue_hits`：

- **零點閘**（`_clear_panel_filter`）：底色說有 Exotic+ → 零點不成立，即使礦名讀歪成低階。
- **救援路 B**（`_panel_rare_ores`）：底色說沒有 → 否決該次命中，照舊交人工。

兩邊的失敗模式都是「多交一次人工」，絕不會多宣告一次「已進帳」。反向（底色有、礦名
讀不出來）只記 WARNING，不自己宣告命中——沒有礦名可寫進 ledger／通知。

### 殘留缺口：`essence of luck` → Lovessence 的模糊假陽性

`classify_found_ore("essence of luck")` 回 `rare_fuzzy`，配到 **Lovessence
（Transcendent、Aesteria 的礦）ratio 0.82**。底色 H=0（低階帶）直接否決，救援側安全，
但**零點閘是 OR（任一訊號說有就不成立）**，所以只要背包裡有 Essence of Luck——實機面板
上很常駐——零點就一直不成立，路 B 等於還是關著。

修法方向（**都還沒做，缺兩側夾**）：

- 收緊面板路徑的 `fuzzy_ratio` 下限：面板礦名的 OCR 信心 0.999+，模糊比對本來就不該
  像聊天那樣寬。要先量 `rare_fuzzy` 真陽性的 ratio 分布才知道門檻擺哪。
- 或加世界閘：路 B 問的是「這段 MINING 挖到了嗎」＝當前世界的礦；Lovessence 是
  Aesteria 的礦，當前世界 Lucernia 就不該配上。

在那之前，零點閘會偏保守（多交人工），不會誤放生礦。

## D12（2026-08-01，採 152/156/157/158 玩家標註）：自己的角色同時是最大遮擋源與最大誤收源，遠處小框夾不出兩側

### 症狀

採 158 全 8 方位皆空交人工。`sweep abs_dir=5` 明明在 15:19:16 以 edge=0.54 收下
(598,781)，轉過去 verify 立刻 `lost target`，重掃 8 方位全空。**礦一直都在**：
六分鐘後玩家回 `1`，重掃 D2 後 `_refind_tracker_near` 在 (599,781)（距先驗點 1px）
以 edge=0.63 找回同一顆。

### 量測

重掃那輪的 8 張 `158_sweep_empty_dir*`，其中 **dir5/6/7/0 四張整片被自己的角色塞滿**
（`snapshots/review`，boost 瓶子在場、計數 19→12 秒數正常遞減，不是 D5 到期的 FOV 收縮）。
畫面上沒有框可偵測，偵測器沒有錯。

同一批標註素材另有四顆「玩家看得到、偵測器判 None」的真框：

| 幀 | 位置 | colored | edge | 判定 |
|---|---|---|---|---|
| 152 sweep_empty_dir4 | (1278,77) | 0.86 | 0.32 | hard_rej |
| 156 sweep_empty_dir4 | (982,255) | 0.86 | 0.32 | hard_rej |
| 156 sweep_empty_dir5 | (461,119) | 0.81 | 0.32 | hard_rej |
| 157 sweep_empty_dir4 | (919,664) | 0.86 | 0.29 | hard_rej |

重跑：`PYTHONPATH=. uv run python .scratch/ann_replay_full.py false_negative`
（⚠ 模板要走 `vision.load_template_any` 再濾 3 通道；用 `cv2.IMREAD_COLOR` 讀會把
wiki 透明圖也算進確認集，退化邊緣圖讓每個候選都拿 edge=1.00 並重錨到 ROI 角落，
是 replay 的假結論。）

### 兩側夾：**兩條軸都夾不出來，門檻不動**

誤收側（`.scratch/ann_negside_0801.py`，逐格肉眼看過）在同一批幀裡撈到 18 個
`edge∈[0.27,0.34] 且 colored≥0.80` 的候選，**全部是玩家自己的角色身體/披風與 hotbar 圖示**。
真框最低 0.287，誤收最高 0.337 → 降 `tracker_shape_soft_edge` 必連角色一起收。

尺度軸也試過（`.scratch/ann_scale_bracket.py`）：這四顆的 `exotic_tracker_real`
連前三名都排不進（都是 `exquisite`/`transcendent` 借分），因為框在畫面上比 120px 模板小得多，
而尺度網格 (0.7,1.0,1.4) 最小只到 84px。補小尺度**把誤收拉得比真框更高**：

| 尺度網格 | 真框最低 | 誤收最高 | gap |
|---|---|---|---|
| (0.7,1.0,1.4)（現行） | 0.287 | 0.337 | −0.050 |
| +0.45 | 0.323 | 0.474 | −0.150 |
| +0.45,0.55 | 0.323 | 0.474 | −0.150 |
| +0.35,0.45 | 0.456 | 0.586 | −0.130 |

小輪廓在雜亂場景本來就假高分（`_best_edge_match_sized` 的 `min_px=12` 正是為此）。
**結論：現有特徵分不開「遠處的小真框」與「自己的角色」，門檻與尺度網格都不動。**

### 要往前推需要的東西

1. **角色遮擋/貼臉的獨立訊號**。它同時解掉遮擋（掃不到）與誤收（角色被當候選）兩件事。
   目前手上沒有「角色貼臉 vs 正常」的標註對，不能寫門檻。收法：每次 giveup 都已經留了
   8 張 `sweep_empty_dir*`，請玩家標 `no_target` 即可攢負樣本。
2. 遠處小框的正樣本要**加拍近距離同一顆**做尺度對照，才知道該補模板還是補尺度。

已修的相鄰項（2026-08-01，同一批證據）：candidate 路徑重找全滅後**不再盲打先驗點**
（採 158 第二發打在自己角色身上，玩家標註 `152623_..._aim_fire_599x781` = empty/false_positive），
以及交人工候選清單改推整輪 8 個方位到網頁（原本只推有候選的方位，158 只有一張圖、
方位切換列切不動，玩家 27 秒後就按 🔀 退回 Discord）。

## D13（2026-08-01，RR#42）：玩家點的是八分鐘前那一幀——已修（點擊前吸附），但自動點擊路徑仍未用預測器

### 症狀

RR#42 玩家在網頁點了三次傳送板，三次都 `still_surface`。

### 量測

八方位掃描 14:44:07 拍完，玩家 14:51:57 才點——中間隔了 **7 分 50 秒**。
比對三張幀（`corpus/reentry/ep42_attempt1/dir1.png`、`dir2.png`、
`tests/fixtures/reentry/teleport_board/auto_42_fail.png`＝點擊瞬間全幀）：

- 玩家看的 dir1 舊幀：板子在畫面最右，玩家點的 **(1786,456) 正中板面**。
- 點擊瞬間的當下幀：同一個方位，但板子已經在 **(1630,419)**（`teleport_board.detect`
  score=0.938）——鏡頭/角色在那 8 分鐘裡漂了約 156px。那一下落在板子右邊的雪地。

兩側夾（八組 fixture 全跑，腳本內嵌在 `tests/test_reentry_prediction.py`
`test_rr_click_snap_bracket_holds_on_real_fixtures`）：

| 樣本 | verify | 點擊離偵測錨點 |
|---|---|---|
| auto_27/39/40/37/35/41 | descended | 37.5 / 41.4 / 45.2 / 43.9 / 56.9 / **65.8** |
| auto_38 | failed（點在板上，敗因另有其他） | 47.5 |
| **auto_42** | failed（**點在板外**） | **160.3** |

66 與 160 之間乾淨分離 → `reentry_click_snap_px=110`（兩側各留 ~45px）。
成功點擊一致落在錨點下方 +37~+45px → `reentry_click_anchor_dy_px=40`。

### 已修

`_rr_snap_click_to_board`（`_rr_click_and_verify` 的第一行，Discord/web 兩條點擊路徑
共用）：偵測分數過 `reentry_predict_min_score` **且**玩家座標離板子 >110px 才吸附，
否則原封不動照玩家原意打。低信心／偵測不到一律不介入。

### 殘留

1. `auto_38_fail` 點在板上（47.5px）卻仍 `still_surface`——**點擊落在正確位置也可能失敗**，
   敗因不明，需要另一組證據（點擊瞬間的滑鼠位置？板子有無冷卻？）。
2. 這批 fixture 的 `annotation` 是 **bot/玩家點了哪裡**，不是人標的板子位置
   （`source.kind == "auto"`、`size` 恆為 50）。`verify != "descended"` 的座標**不是**
   ground truth——曾有一版回歸測試把 `auto_42_fail` 的失敗點當標準答案，判成「偵測器退步」。
   要真正的板子 ground truth，得請玩家在 `/annotate` 手動框（`source.kind == "manual"`）。

---

## D12（2026-08-02）：~~TIER_HUES Transcendent 210° 待驗證~~ → **已解決**

**原問題**：`essence of luck`（H167 快照）被 fuzzy matcher 判成 Transcendent 但
實測色相 [27, 0] 與 210° 不符。

**根因**（使用者澄清）：`essence of luck` 不是 Transcendent，是 **Enigmatic**
（藍色階級 H=70）。fuzzy matcher 把它配到 rare_ores.json 裡同名但不同階級的條目。

**解決**（2026-08-02 實機全面板截圖）：使用者在遊戲中同時擁有四階 礦，一次截圖
量到全部四個色相——每階單一色相、零變異、零重疊：

| 階級 | 色相 | BGR |
|---|---|---|
| Enigmatic | **70°** | [0,128,106] 青藍 |
| Transcendent | **210°** | [133,66,0] 紅橙 |
| Exquisite | **128°** | [52,101,44] 綠 |
| Exotic | **46°** | [33,104,128] 藍 |

`TIER_HUES` 已補入 Enigmatic=70°。`panel_whitelist_hues` 同步加入 70°。
Unfathomable 以上仍未量測——靠 `non_low_tier_hues` 反向閘兜住。

---

## D13（2026-08-02）：Transcendent 與 Unfathomable 色帶在 `panel_hue_tol_deg=6` 下重疊 2°；非連續階級選擇時產生矛盾判定

**量測**（`tests/fixtures/panel_tiers/`，使用者背包實機幀，礦名查 `rare_ores` 獨立確認階級）：

| 階級 | wiki | 實機 | Δ | 來源礦名 |
|---|---|---|---|---|
| Otherworldly | 333° | **334°** | 1° | Retina |
| Unfathomable | 219° | **220°** | 1° | Asminthia |
| Enigmatic | 70° | **70°** | 0° | Genuinium 等 8 顆 |
| Transcendent | 210° | **210°** | 0° | Finalitium 等 8 顆 |
| Exquisite | 128° | **128°** | 0° | Cosmic Treasure 等 5 顆 |
| Exotic | 45° | **46°** | 1° | Asterium/Mechaspark/Astatine |
| Mythic（低階） | 305° | **304°** | 1° | Plasmal 等 3 顆 |
| Surreal（低階） | 165° | **166°** | 1° | Prasiloudis 等 3 顆 |
| Master（低階） | 280° | **280°** | 0° | Adasparta |

Unfathomable 與 Otherworldly 先前只有 wiki 色碼、無實機佐證（註釋表卻標成已量測），
本批補上。**wiki HEX→HSV 全 12 階重算無誤**，`TIER_HUES` 的值全部正確。

**問題**：實機 Transcendent 210° 與 Unfathomable 220° 相差 10°，`panel_hue_tol_deg=6`
需要 >12° 才不重疊 → 兩帶重疊 2°（214-216）。

原註釋曾有這條警告，但在 `5650531` 改寫表格時被刪，理由「兩階都屬高階，對偵測無影響」
——當時成立（兩個閘都只做存在判定）。**同日稍晚的 `2539119`（階級門檻改勾選式）
讓它不成立**：該功能主打非連續選擇，單獨關掉 Transcendent 而保留 Unfathomable 時，
色相 **213-216** 同時滿足「白名單命中（算稀有）」與「落在低階帶（不算高階）」。

**為何不修**：實機量到的 Unfathomable 是 220°，**不在矛盾區間 213-216 內**；
逐列讀數穩定（218-220，n=45/列）。實務上不會觸發，且 `main.py:5392` 遇到兩訊號
不一致會走「否決，照舊交人工」，方向安全。要收窄 `panel_hue_tol_deg`（4.5 以下即
不重疊）必須先有落在 213-216 的實機樣本做兩側夾——**沒有樣本不動門檻**。

**取樣協議（結論的一部分，改量測方式前必讀）**：固定窗 `cfg.panel_hue_sample_x`
(120,165) + **逐列中位→跨列中位，不用平均**。首次量測用環形平均得 Unfathomable
227.4°（差 8.4°、看起來像表值錯了），實為紅色礦名的抗鋸齒像素污染，改逐列中位後
220.0°——**差點寫出一個假修復**。面板列有水平漸層（左亮右暗）但**只在 V 上**，
H 沿列與沿行皆恆定（Transcendent 幅度 0.0°），故取樣位置不影響階級判定；
要加 S/V 判據時必須連取樣窗一起指定。工具：`uv run python -m miningbot.measure_tier_hues`。

**仍缺**：`Imaginary`（wiki 雙色 `EEBA44`+`C9DEE9`＝42°+201°，雙色漸層，固定窗
只會讀到其一或混色）與 `Zenith`（wiki 無色碼）至今無樣本，靠 `non_low_tier_hues`
反向閘兜住（未知色相當高階，保守）。

### D13 續（2026-08-02）：第三張素材補灰階列（Common／Layer）與「色帶起點＝wiki 原色」

使用者換面板提供低階為主的一張（`tiers_grey_lowtier_20260802.png`），補上前兩張
沒有的**灰階列**型態。11 列全部判定正確（1 高階擋零點、10 低階放行，零誤判）。

| 礦名 | 階級 | H | S | 備註 |
|---|---|---|---|---|
| Pixelated Mass | Transcendent | 210 | 255 | 唯一高階，正確擋零點 |
| Passionblaze | Mythic（低） | 304 | 255 | |
| Vantaglass | Rare（低） | 30 | 253 | |
| Brass／Obsidian Glass／Cassiopeia | Uncommon（低） | 0 | ~217 | 與 Common 同 H，靠 S 區分 |
| Glass／Orglass／Bass | **Common（低）** | — | **0** | 灰階，x=18 的 V=192（wiki C1C1C1=193） |
| Foligrass／Frosted Grass | **Layer（低）** | — | **0** | 灰階，x=18 的 V=132；wiki 色碼待查 |

**灰階列的判定是「巧合正確」**：`panel_row_hues` 對 S=0 回 H=0.0，而 0.0 剛好在
`panel_low_tier_hues` 裡 → 零點閘放行、白名單閘不命中，兩者都對。但**若將來出現
H=0 的高階礦，這條會反過來咬人**（wiki 現有 14 階裡沒有，暫時安全）。已加迴歸
`test_grey_rows_are_not_mistaken_for_high_tier` 釘住現況。

⚠ **量測腳本的盲區**：用 `S>60` 過濾會**整列跳過**灰階列，輸出裡看不到它們。
第一版 `_band_hue` 就是這樣寫的，加進灰階 fixture 後直接紅燈；已改成「整條帶無
飽和像素 → 確認確實是灰（S≤30）再回 0.0」。

**額外發現：色帶起點 x=18 的像素就是 wiki 官方色。** 漸層由此往右衰減。三張幀
14 條帶逐一比對，ΔBGR ≤2：

```
Transcendent  x=18 [254,127,0]   wiki 0080FF [255,128,0]
Enigmatic     x=18 [0,244,203]   wiki CDF600 [0,246,205]
Common        x=18 [192,192,192] wiki C1C1C1 [193,193,193]
```

**未改用**：現行 H-only 判定在取樣窗 (120,165) 已全數正確（三張幀 21 條帶零誤判），
換窗要重驗每一條既有迴歸，不值得。x=18 的價值在**將來要加 S/V 判據時**——那時 H
不夠用（灰階就是這種情況），而 (120,165) 的 V 已衰減到原色 ~55%、沒有跨階級可比性。
已由 `test_band_origin_x18_equals_wiki_colour` 釘住，將來要用時不必重新發現。

**累計覆蓋**：三張幀、21 條帶、11 個階級。仍缺 `Imaginary`（wiki 雙色漸層
42°+201°）與 `Zenith`（wiki 無色碼），使用者尚未取得。

**順手修掉的 config 死行**：`panel_low_tier_hues` 在 `config.py` 被**定義兩次**
（`470f1ff` 加註釋表時遺留），第一行 `(0.0, 30.0, 165.0, 280.0, 305.0)` 是 wiki 值、
第二行 `(0.0, 30.0, 166.0, 280.0, 304.0)` 是 D11 實機值。dataclass 後者覆蓋前者，
**行為一直是對的**（生效值是實機值），但編輯第一行會靜默無效——下一個人照著 wiki
改那行會以為改了、實際沒有。已合併成單一定義（生效值不變，已驗證）。

---

## D14（2026-08-02）：傳送板 mask blob 在部分 descended 幀是直向/近方形，卡在 v0 的 aspect 閘外

### 症狀

`test_teleport_board_detector_hits_every_annotated_fixture` 與
`test_rr_click_snap_bracket_holds_on_real_fixtures` 紅：`teleport_board.detect`
對 `auto_46_success`、`auto_48_success`（皆 `verify=descended`，即真板子）回 `None`。

### 量測

annotation 窗（±180px）內用極寬 hue range（100–160）抓所有紫色 mask，最大 connected
component 的形狀（`teleport_board` 的 aspect 閘是 `[1.60, 3.00]`，只要橫向）：

| fixture | verify | 最大 comp (w×h) | aspect | 結果 |
|---|---|---|---|---|
| auto_52_success | descended | 235×154 | **1.53** 橫向 | ✓ 偵測到 |
| **auto_46_success** | descended | 212×273 | **0.78** 直向 | ✗ None |
| **auto_48_success** | descended | 130×141 | **0.92** 近方 | ✗ None |

兩側夾 hue 下界（126 → 124 → 120 → 116 → 110）：auto_46/48 **全程 None**、其餘 10
張 descended 命中數不變（10/12）、無新誤報——**降 hue 無效，問題不在 HSV range**。

板子框的紫色確實進了 mask（auto_46 窗內紫色像素 40963、mask_px 12408），但形成的
blob 是**直向/近方形**而非 v0 校準的 ~2:1 橫向（校準語料 4 個板子實例 aspect
1.53–2.21，見 `teleport_board.py` 配方註）。auto_48 的窗內 S_med=51 還低於校準 S
下界 60（板子偏去飽和）。可能成因：俯角不同使板子看起來被壓扁／旋轉、或這批板子
本身是直向款式——**需肉眼確認這幾幀的板子外觀**（素材：
`tests/fixtures/reentry/teleport_board/auto_46_success.png`、`auto_48_success.png`）。

### 為何不直接放寬 aspect 閘

aspect 下界降到 ~0.78 會讓任何直向紫色物（UI 柱、夜空、左側礦物面板邊）全部過閘，
在沒有直向板的負樣本下無法兩側夾——違反「夾不出兩側就別動門檻」。v0 偵測器本就標榜
「語料是單一世界/單一層/全夜晚、只求在這個分布上可用」（`teleport_board.py` docstring）。

### 處置

- 門檻不動。`detect` 是**建議用**（`_predict_teleport_board` 只建議不自動點），偵測
  不到時照常走 web/Discord 八方位手選，不影響介入流程。
- 測試誠實化（本次 commit）：descended 才算 ground truth（`verify != "descended"`
  偵測不到不算退步，與 D13 的 `auto_42_fail` 同一條規則）；D14 兩張以 `_D14_ASPECT_GAP`
  排除硬斷言但發 `UserWarning` 可見化，修好移除即消失。
- 待辦：肉眼確認 auto_46/48 的板子外觀後，決定是 (a) 加直向板模板/放寬 aspect（要配套
  負樣本），還是 (b) 歸類為 v0 不涵蓋的分布。`build_reentry_dataset --eval` 是唯一量尺。

### 根因確認（使用者 2026-08-02）：板子有旋轉／直向款式

使用者肉眼確認：這批板子**大部分是旋轉與直向**——不是校準飄移，是遊戲本身有非橫向的
板子。auto_46 的板子在 close≤7 時是乾淨直向矩形（128×234, aspect 0.55, normAsp 1.82，
落在 [1.60,3.00] 內），但 close=11 把它跟鄰近紫色物 merge 成 212×261（normAsp 1.23）。

### 兩側夾實驗（close_px × orientation-normalized aspect，19 張全跑）

| combo | descended 命中 | 誤報 | 損失 |
|---|---|---|---|
| **close=11 raw（現行）** | **11/13** | 2 | 僅 auto_46/48 |
| close=11 norm | 10/13 | 3 | norm 讓 auto_41 的正確橫向板被直向物搶走 |
| close=7 norm | 10/13 | 1 | 少 close → auto_43 外框碎片化 |
| close=3/5 | 8/13 | 1 | auto_43/52/53 全碎片化 |

**任何組合都是淨負值**：
- **降 close_px**：橫向板外框是細長條，不接會碎（`config.py` 註：「外框是細長條，不接
  起來會碎成多塊」）——close=11 是為橫向板校準的，降了就碎。
- **aspect normalize**：讓直向物也過閘，在 auto_41 搶走正確偵測、還多一個誤報。
- **auto_48**（近方形 107×98 asp 1.09 + S_med=51 去飽和）任何組合都救不了。

### 結論：v0 結構性限制，需 v1 重新設計

單一 `close_px` 無法同時服務橫向（需大 close 接框）和直向（大 close 跟鄰物 merge）
板——這不是門檻問題是架構問題。門檻不動（現行 close=11 raw 已是 11/13 的最佳點）。
v1 方向：模板匹配（不受碎片化影響）、或直向/橫向兩條獨立偵測路徑各配各的 close 與
負樣本。`detect` 仍只做建議，偵測不到走 web/Discord 手選，不阻塞介入流程。
