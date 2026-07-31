---
name: tuning-from-incidents
description: Use when a miningbot live-run misbehavior needs detection/decision tuning, or when unversioned player annotations under tests/fixtures/ are waiting to be turned into a tuning pass — adjusting a detection threshold, OCR preprocessing, exclusion list, timing, or verify logic. Symptoms like 漏採／假陰性／誤交人工／誤觸發／OCR 讀歪／掃描全空／視角偏移 usually route here, but first confirm the root cause is detection — NOT a player-facing convention off-by-one, stale help text, or two remote flows (reentry vs aim) out of sync, which this skill does not cover (H056 fixed one such case that looked exactly like a detection miss).
---

# 實機事故微調迴圈（Tuning from Incidents）

## 核心原則

**沒有實機證據不改參數；沒有失敗測試不寫修復。**
本專案每個門檻都是由真實事故資料「兩側夾」出來的；「猜一個值試試」是歷史上所有迴歸的來源。

## 何時使用

- 使用者回報某輪採集出問題（通常附 Hxxx 編號或大概時間）
- 想調 config 門檻、OCR 前處理、排除清單、verify 邏輯、vision 偵測、音訊參考
- 不適用：全新功能（走 brainstorming → writing-plans）
- 不適用：遙控／手動瞄準的**玩家慣例／UI 契約**——方位編號、help 文字過期、
  兩個 remote flow（`reentry_remote` 與 `remote_aim`）只改一邊。這類是 off-by-one／
  訊息不同步，不是偵測門檻，**別調 vision／OCR**，走一般開發流程把兩邊 flow＋玩家訊息
  一次補齊（見 memory `feedback_new_command_must_update_player_messages`）。
  ⚠ 症狀會偽裝成偵測問題：使用者常回報「掃描全空／選的格子沒東西」，但根因可能是
  「玩家指的方位被 off-by-one 送到隔壁空格」——**H056 就是這型**（瞄準介面當時還是
  0-7、回礦介面已是 1-8；現已由 `remote_aim.dir_label()` 統一成對外 1-8、內部 0-based）。
  動手前先驗慣例一致性：兩個 flow 的 parse／display／help 是不是同一套。

## 標註驅動（玩家自己標素材時的入口；2026-07-31 起）

玩家在網頁 `/annotate` 畫框標記，素材落 `tests/fixtures/<類別>/`（兩檔一組
`<stem>.png` + `<stem>.json`）。**未進版控的 `.json` ＝ 還沒被微調處理過**，
`.claude/hooks/annotation-tuning-nag.ps1` 每次提問都會檢查並提醒（提醒是靠版控狀態，
不是 marker 檔——素材連同修復一起 commit 後自動消失）。

這條入口取代下方步驟 1-3（不必先問 harvest_id，標註本身就是證據），步驟 4 之後照走：

1. **crop 定位回全幀**：`.png` 是 320×270 粗格裁圖，**不要拿它量門檻**——
   `shape_roi_px=320` 在 270 高的裁圖上會被裁掉一角，`edge` 系統性偏低（H068 差 0.05~0.1，
   足以把結論翻面）。全幀在 MSIX LocalCache `snapshots/review/`，同名檔；用
   `cv2.matchTemplate(全幀, crop)` 取得標註物的絕對座標。
2. **重放現行偵測器**：對每張全幀跑 production 參數的 `find_tracker`（或該類別對應的
   偵測器），把 `log=` 收下來——每個候選的 `colored`／`edge`／`ring_ok` 就是兩側夾的原料。
   `symptom="false_negative"` 是收側，`symptom=None`+`observation="ore"` 是對照組。
3. **誤收側一定要肉眼看**：把所有被拒候選裁 160×160 貼成一張圖逐格看。H068 差點把
   「(1154,937) 是 hotbar」寫進結論，實際是粉紅岩層——**看錯誤收側＝門檻訂錯方向**。
   誤收側不只來自這批新素材，既有實機幀（`assets/*_scene.png`、`tests/fixtures/tracker/`）
   也要一起掃，否則會踩到別人的迴歸測試才發現。
4. 之後接下方步驟 4（fixture 固化）起的既有流程。**夾不出兩側就別動門檻**：把量測寫進
   `docs/open-detection-issues.md`（Dxx），素材仍要 commit——否則下次又從頭量一遍。

## 迴圈（順序不可跳）

1. **取編號（兩套別混）**：
   - `harvest_id`＝出事那一輪的採集流水號，**純數字零填充三位**（`007`、`118`；`harvester.format_harvest_id`）。log 判定行、快照檔名、Discord 訊息共用它 → 在 `logs/` 內 grep `118` 就撈出該輪全部證據。
   - `Hxxx`＝`docs/incidents.md` 的**事故編號**，只在文件與程式碼註解裡出現，log 裡沒有。
   - 兩者 2026-07-07 起刻意分家（舊格式 `H064` 與事故碼撞名）。**grep log 一律用純數字**；grep `H118` 會一無所獲。
2. **先收證據，不改碼**：
   - `logs/harvest.log`（sweep/D3/verify 逐步）＋ `logs/miningbot.log`（主敘事）
   - `logs/snapshots/trace/` 內該輪的 `*_chat_ocr_*.txt`（verify OCR 全文落盤）
   - `logs/snapshots/` 該輪截圖（檔名含 harvest_id 純數字）、Discord 附圖；`snapshot_index.jsonl` 可反查分類與路徑
   - ⚠ 用 `pythonw`／`啟動挖礦bot.bat` 跑的實機 log 不在 repo `logs/`，在 MSIX LocalCache（見下方 Quick Reference）
   - 用時間戳排出時間線：觸發→sweep→開火→verify→收場，每步發生了什麼。
3. **一句話根因**：格式「X 因為 Y 所以 Z」，每個環節有 log 佐證。只說得出症狀 → 停，走下方升級條件。
4. **樣本固化成 fixture**：一律放 `tests/fixtures/<類別>/`（聊天 → `chat/`、追蹤框場景 → `tracker/`、單格瞄準 → `aim/`、回礦 → `reentry/`…；先讀 `tests/fixtures/README.md` 選目錄，加完更新該目錄 README 表格）。音訊走 `add_chill_ref` 流程。
   ⚠ **不可放 `assets/`**：`assets/*.png`／`assets/**/*.png`／`*.wav` 全被 gitignore，放進去等於別台機器 clone 下來測試就 skip。**無樣本的修復＝下次必迴歸。**
5. **TDD**：先寫用 fixture 重現事故的失敗測試（紅），再修（綠）。
6. **門檻兩側夾**：新門檻必須同時列出「真值分數」與「誤收值分數」（例：H020 真值 0.545/0.727、誤收 0.500/0.600 → 取 0.62）。寫不出兩側數字＝證據不足，回步驟 2。
7. **查安全方向表**（下）決定偏哪邊。
8. **回歸**：`uv run pytest -q` 全綠；動過 OCR 前處理必過 `tests/test_ocr_fixtures.py`；動過 vision 必過對應 fixture 場景回歸。（裸 `python -m pytest` 在這台受管 Windows 會權限失敗，見 `AGENTS.md` COMMANDS。）
9. **文件化**：**證據與敘事寫 `docs/incidents.md`**（症狀／一句話根因／量測／對策／回歸／下輪實機驗證預期，格式照既有條目）；`AGENTS.md`／`CLAUDE.md` 只在「違反會壞掉安全性或正確性」時補一條硬規則，不放事故全文（`docs/README.md` 維護規則）。量測未修復的偵測缺口進 `docs/open-detection-issues.md`。memory 對應檔同步更新。
10. **commit**：feature branch、中文訊息含 Hxxx、結尾 `Co-Authored-By: Claude ...`。
11. **結案＝實機驗證**：寫下「下一輪 log 預期看到什麼」（哪個 log、哪種行），下輪掛機後 grep 確認。測試綠只證邏輯，不算結案。

## 安全方向表（動手前查）

| 子系統 | 方向 | 為什麼 |
|---|---|---|
| 聊天成功判定（ocr） | 寧漏勿假成功 | 漏的有 count／底行信號兜底；假成功提前收尾＝丟礦 |
| 排除清單（game_data.common_ores） | 寧短勿長；**Exotic+ 絕不可列** | 列了＝真採到被判失敗（H014）；Rare/Master 底名可列（H039） |
| 旋轉被吃判定（rotation_looks_eaten） | 寧漏判勿誤重送 | 誤重送＝過轉 45° 斜角，比漏判更糟 |
| classify 未知礦名 | 未知仍算成功、只標警告 | 礦多半真採到；清單漂移靠警告浮現 |
| chill 參考集（add_chill_ref） | 只收 confirmed；`_miss` 要人工聽過 | 盲收＝雜訊參考、純假觸發風險 |
| tracker 偵測（vision） | HSV 寬鬆、形狀 edge 仲裁 | 中心非不變特徵；ring/fill 提前硬拒殺過 4 張真框 |

## 硬規則

- 座標／門檻只進 `miningbot/config.py`，不散落。
- OCR 差分逐 pass 自洽，不可跨 pass 比（各 pass 噪音不同）。
- 帳本噪音守門比「礦名」不比整行（聊天行共享長前綴，整行相似度必然過高）。
- 動 verify／episode 帳本／聊天基準前，**先整段重讀 `AGENTS.md` NON-NEGOTIABLE RUNTIME RULES 第 6 條**（採集成功判定；H014/H020/H032/H041/H054/H055 都壓在那條裡）——每個分支都對應一個實機事故，看似冗餘的都不是。

## 升級條件（小模型停手，交人／大模型）

任一成立 → 不改碼，把時間線＋證據整理成報告：

- 說不出一句話根因
- 修復需要改狀態機結構、或跨 3 個以上模組
- 事故型態不像 CLAUDE.md 任何已知 H 案例
- 只能靠新的實機實驗判斷（離線重現不了）

## Quick Reference

| 要做 | 命令 |
|---|---|
| 全測試 | `uv run pytest -q` |
| OCR fixture 回歸 | `uv run pytest tests/test_ocr_fixtures.py -q` |
| 撈某輪證據 | 在 `logs/` 內 grep **純數字** harvest_id（`118`；log 行＋快照檔名都會中）——不是 `H118` |
| 讀 log 不亂碼 | `Get-Content logs\harvest.log -Encoding UTF8 -Tail 100` |
| 找實機 log（pythonw 啟動） | MSIX 重導到 `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_*\LocalCache\Local\RexMacro\logs`；⚠ 目錄列表 mtime/size 會過期數小時，一律 `Get-Content -Tail` 看內容時間戳（`CLAUDE.md` 實機排錯） |
| RapidOCR 疑似讀歪樣本 | grep `harvest.log` 的 `WARNING` |
| 補 chill 參考 | `python -m miningbot.add_chill_ref --scan` |
| 遊戲更新後同步礦表 | `python -m miningbot.fetch_ores`（排除清單仍須人工過目） |

## 藉口對照表

| 藉口 | 現實 |
|---|---|
| 「先把門檻降一點試試」 | 門檻必兩側夾；猜測式調參是本專案所有迴歸的來源 |
| 「這修復太小，不用 fixture」 | H020／H026 都是「小修」引發的迴歸 |
| 「測試綠了＝修好了」 | 綠只證邏輯；結案要下一輪實機 log 驗證 |
| 「排除清單加這顆就不誤報了」 | 先查階級；Exotic+ 列入＝重演 H014 假陰性 |
| 「這段邏輯看起來冗餘，順手簡化」 | verify 每個分支都是實機事故堆出來的；先讀 CLAUDE.md 再動 |
| 「聊天沒新行＝沒採到」 | 成功行會晚到／被推走／淡出（H015/H020/H032）；查 episode 帳本與晚到確認 |
| 「選的方位／格子沒東西＝偵測或掃描漏了」 | 遙控／手動瞄準事故先驗玩家慣例：H056 就是 `remote_aim` 當時還 0-7、`reentry_remote` 已 1-8，玩家看 `DIR 4` 的圖打 `5` 被送到隔壁空格（現已由 `remote_aim.dir_label()` 統一）。先查兩 remote flow 的 parse／display／help 是否同步，再談偵測門檻 |
