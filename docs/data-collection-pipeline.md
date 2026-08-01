# 資料搜集管線清單

本檔列出所有「**現在跑著收集資料、等資料足夠後才開做／開門檻**」的功能。每條寫清楚：
收什麼、落在哪、收夠了要做什麼、現在什麼狀態。

下一個 agent 或一週後的自己：**先讀這份**判斷哪條管線資料收夠了可以動工，再讀對應的
spec／ticket／incident 細節。別從頭查 config 裡哪些欄位標了「待實機」——全在這裡。

維護規則：新增一條「先收資料再開做」的功能時，在這裡加一行；活化／棄用時標記結果。
別讓這份清單變成死檔。

---

## 1. 交人工前救援（路 B 命中率／漏判率）

- **收什麼**：救援命中次數（自動）＋ 漏判次數（人工回看 giveup 裁圖）＋ 降級原因分類。
- **落在哪**：`HARVEST_RESCUED` 事件（events.log／Discord 🛟）；漏判的降級原因在
  `harvest.log`（「交人工前救援」開頭的行）；giveup 裁圖在 Discord `NEEDS_HUMAN` 通知。
- **收夠了要做什麼**：
  - 如果漏判多在「裁圖有名、差分說無」→ 修 OCR／幾何閘。
  - 如果漏判多在「同礦種重複盲」（名字已在面板、只有數量 +1）→ 動手做 www 篩選框武裝。
  - 如果幾乎沒漏判 → 救援功能驗收通過，不用動。
- **現在狀態**：`giveup_rescue_enabled=True`（已上線收資料，2026-07-30 `d0a004c`）。
  **觀察期中**：`giveup_rescue_observe=True`——命中照記 `HARVEST_RESCUED` 但照舊交人工，
  不自己收尾。命中次數持久化在 `<log_dir>/rescue_observed.json`，滿
  `giveup_rescue_observe_target`（10）次由 agent session 攤開證據問玩家要不要切自動。
- **降級原因分類**（路 B 跳過時 log 可見）：
  - **面板未歸零**（`_panel_zeroed_at is None`）：進 MINING 時清空未通過驗證（清空序列
    失敗／面板重繪沒跟上／rapidocr 不可用）→ 路 B 整條跳過，只靠路 A（聊天）。log：
    「路 B：面板未歸零 → 跳過」。
  - **標頭非 NORMAL**：面板標頭讀到 IONIZED／SPECTRAL 或讀不到 → 路 B 跳過（白名單礦
    排在 NORMAL 頁最上面，在其他頁看不到）。log：歸零驗證的 WARNING 帶實際標頭。
  - **兩訊號不一致**： 礦名認出白名單但列底色說沒有 Exotic+（或反向）→ 否決命中、照舊
    交人工。log：「面板兩訊號不一致」WARNING。
  - **同 礦種重複盲**：兩顆同種 礦只算一顆（名字已在面板、只有數量 +1，數量欄被 craft
    面板疊住讀不到）。這是漏判不是錯判，寧漏勿誤。
- **規格**：`docs/superpowers/specs/2026-07-31-panel-zero-rescue-design.md`（存在性檢查
  設計）、`docs/superpowers/specs/2026-07-31-rescue-trust-hardening-design.md`（實機
  失效點修正＋觀察期）、`docs/superpowers/specs/2026-07-30-giveup-rescue-already-mined-design.md`
  （原始設計，面板側已被 07-31 兩份 spec 取代）。
- **附帶校準**：`prechill_min_age_s = 3.0`（config.py，標「待實機修正」）——只影響路 A
  （聊天差分），路 B 已改成存在性檢查不需要 chill 前參考點。太新的參考可能已含那次挖掘、
  太舊納入無關挖掘。用救援命中／漏判分布修正。
- **⚠ H072（2026-08-01）相關**：成功驗證路徑（`_is_rare_ore` count 差）若誤判成功，
  `_episode_succeeded=True` 會讓救援整條跳過——假成功等於靜默繞過救援。已三層修復
  （截斷容忍＋classify 交叉驗證＋進場面板色檢），但救援命中率統計要看的是「救援被叫到
  時判得對不對」，不含「根本沒輪到救援」的假成功。

## 2. chill 上升緣／回落時間戳 → 雙 chill 對帳門檻

- **收什麼**：同一 episode 內每一聲 chill 的上升緣時間戳／分數、回落時間戳。目標是量出
  「同一聲內多 tick 的形狀」與「兩聲之間的間隔分布」。
- **落在哪**：`harvest.log`（「chill 上升緣 #N」「chill 回落」行）。
- **收夠了要做什麼**：
  - 用間隔分布定 `chill_edge_release_s`（分數要回落多久才算下一聲）。
  - 然後開 `chill_reconcile_enabled = True`。
  - 門檻猜錯會直接製造新的人工次數——沒有分布之前不可上線。
- **現在狀態**：純記錄已上線（2026-07-30 `d0a004c`）；對帳程式已寫好但兩個開關出廠關
  （`chill_edge_release_s=0.0`／`chill_reconcile_enabled=False`）。
  已知一個真實間隔：07-29 14:43:58 → 14:44:14，16 秒。
- **規格**：`docs/superpowers/specs/2026-07-30-prechill-evidence-cache-design.md` B 段、
  `docs/superpowers/specs/2026-07-30-double-chill-reconciliation-design.md`。
- **ticket**：`.scratch/prechill-rescue-reconcile/issues/06-fill-threshold-and-enable.md`。

## 3. boost FOV 縮放曲線

- **收什麼**：boost 到期（FOV 收縮中）vs 補瓶後（FOV 展開）的同場景前後幀對，附螢幕
  計數（使用次數）做 x 軸標籤。
- **落在哪**：`logs/boost_fov/`（JPEG 前後幀對）＋ `logs/boost_fov/count.jsonl`
  （使用確認／對帳 jsonl）。
- **收夠了要做什麼**：擬合 FOV 隨使用次數的收縮曲線，讓 sweep／偵測能預補償（目前靠
  harvest boost 守門事後補救）。
- **現在狀態**：取樣節流 `boost_fov_pair_every_n = 10`（每 10 次一組，`config.py:115`）。
  **待實機收一場完整資料**。瓶次右下角紅字＝使用次數 ground truth。
- **相關**：`miningbot/main.py` `_boost_fov_pair_save`、`vision.read_boost_use_count`。

## 4. 重置完成鈴聲（reset chime）

- **收什麼**：RESET_WAIT 期間容量歸零後錄的候選音訊片段。
- **落在哪**：`logs/snapshots/audio/` 的 reset chime 候選片段。
- **收夠了要做什麼**：從樣本萃出 reset-complete 鈴聲參考，開始比對 → 礦坑重置完成
  自動偵測（不必靠 banner OCR 字樣消失＋沉澱）。
- **現在狀態**：第一階段（只錄不比對），`reset_chime_capture = True`
  （`config.py:190`，標「校準拿到樣本後可關」）。容量 OCR 歸零才開錄
  （`reset_chime_capacity_arm_pct = 10.0`）。
- **規格**：`docs/superpowers/specs/2026-07-09-reset-chime-capture-design.md`。

## 5. 回礦 yaw 隨機化校正（H059）

- **收什麼**：成功收尾後原地拍八方位（`reentry_yaw_sample_sweep`），收集「直角 vs 對角」
  的視覺特徵，建立 yaw 分類器。每輪 attempt 按「回到地表」會隨機化 yaw →
  restore_view 轉回的是隨機基底，無法靠邏輯校正。
- **落在哪**：`logs/snapshots/` 的 `yaw_sample_*` 快照。
- **收夠了要做什麼**：建 yaw 分類器，讓自動回礦能校正到正確方位。目前**缺「斜挖」
  負樣本**，無法兩側夾（H040/H054 慣例）。
- **現在狀態**：`reentry_yaw_sample_sweep = False`（`config.py:472`，標「預設關：每
  episode 多 ~10-15s，只在收語料的場次開」）。
- **規格**：`docs/superpowers/specs/2026-07-20-reentry-yaw-reroll-random-design.md`、
  `docs/superpowers/specs/2026-07-21-reentry-yaw-investigation-findings.md`。

## 6. 傳送板偵測器門檻（teleport board）

- **收什麼**：回礦語料裡傳送板的偵測分數分布（真板子 vs 非板子候選）。
- **落在哪**：`logs/reentry_remote/` 的快照＋ ledger。
- **收夠了要做什麼**：現在 `reentry_predict_min_score = 0.70` 是「最弱一個真命中的下緣」
  而不是兩側夾的分離點。語料長大、出現非板子高分候選時要重新量。
- **現在狀態**：偵測器可跑（suggest only、never auto-click），門檻待收資料。
  `config.py:402`。
- **相關**：`miningbot/teleport_board.py`。

## 7. 回礦語料庫 / dataset（全自動回礦前置）

- **收什麼**：玩家手動點擊傳送板的八方位全畫面＋座標（click ground truth），供
  `build_reentry_dataset` 離線訓練／評估。
- **落在哪**：`logs/reentry_remote/`（ledger.jsonl ground-truth 帳本）、`<log_dir>/corpus/reentry/`。
- **收夠了要做什麼**：
  - `reentry_mode = "auto"`（全自動回礦，目前是 `"remote"`＝Discord 指位）。
  - 「auto」需要面板模板校準完成（`config.py:411` 標「面板模板校準完成前勿開」）。
- **現在狀態**：語料累積中；07-28 實測 200 shots 只剩 58 張（`snapshot_max_total_mb`
  從最舊刪不分 ground truth＋`_save_auto_fixture` 只存 1 張丟 7 張負樣本）——收語料前
  先備份 landing 快照。
- **相關**：`miningbot/corpus.py`、`miningbot/build_reentry_dataset.py`（`--rescue`／`--eval`）。

## 8. 回礦遠端自動開挖亮度簽名

- **收什麼**：點擊後落地幀的「礦內亮度」簽名，用來判「已經回到礦層可以開挖了」。
- **收夠了要做什麼**：校準亮度簽名 → 開 `reentry_remote_auto_resume = True`
  （幀差＋亮度雙過即自動開挖，不必等 Discord 「好」放行）。
- **現在狀態**：`reentry_remote_auto_resume = False`（`config.py:562`，標「亮度簽名校準前
  的安全預設」）——一律等「好」放行。

## 9. 俯仰層掃描（sweep pitch）

- **收什麼**：標準層看不到的框，換俯仰層（up/down）才掃得到——需要校準 pitch step px。
- **收夠了要做什麼**：校準 `sweep_pitch_step_px` → 開 `sweep_pitch_enabled = True`。
- **現在狀態**：`sweep_pitch_enabled = False`（`config.py:504`，標「校準完成前保持
  False」）。程式已寫好（`_pitch_layer_transition`／`plan_pitch_layers`），差校準值。
- **相關**：`docs/superpowers/specs/2026-07-28-sweep-pitch-enable-design.md`。

## 10. 掃描確認模式（scan_confirm_mode）

- **收什麼**：D2 掃描效果列的 OCR 確認（掃描真的觸發了嗎）。
- **收夠了要做什麼**：在 live session 的 `observe()` 裡跑一輪，確認 region（2026-07-25
  校準到右下效果列）真的讀得到，再開啟。
- **現在狀態**：region 已校準，但 AGENTS RISK AREAS 標「has not yet run in observe
  against a live session」——還沒在實機跑過。

## 11. 音訊變動記錄器（chill 漏抓診斷／新參考）

- **收什麼**：score 越過觀察門檻（0.15，低於觸發 0.25）的音訊片段——可能是漏抓的 chill，
  也可能是候選新參考。
- **落在哪**：`logs/snapshots/audio/` 的 `audiochg_*.wav`。
- **收夠了要做什麼**：從中挑出真 chill（排掉防掛機跳音等負樣本）擴充 `assets/chill_refs/`
  參考集。⚠上升緣 `audiochg_*` 不可直接當參考（loudest_window 可能抽到 chill 前的背景）。
- **現在狀態**：`audio_event_threshold = 0.15`（`config.py:187`），持續記錄。

---

## 活化檢查表

每條管線活化前，確認：

1. **樣本足夠嗎**——兩側夾（正負樣本各有，不是只看正面）。
2. **門檻有實機依據嗎**——不是猜的，寫進 config 註解記量測日期。
3. **淨值是正的嗎**——新增的人工次數（對帳／誤判）要小於省下的人工次數（救援）。
4. **改完跑全套測試綠**，中文 commit 訊息附量測依據（H incident 或日期）。
