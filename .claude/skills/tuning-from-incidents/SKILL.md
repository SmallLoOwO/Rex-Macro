---
name: tuning-from-incidents
description: Use when the mining bot misbehaved in a live run (漏採、假陰性、誤交人工、誤觸發、OCR 讀歪、掃描全空、視角偏移), or when asked to adjust any miningbot detection threshold, OCR preprocessing, exclusion list, timing, or verify logic.
---

# 實機事故微調迴圈（Tuning from Incidents）

## 核心原則

**沒有實機證據不改參數；沒有失敗測試不寫修復。**
本專案每個門檻都是由真實事故資料「兩側夾」出來的；「猜一個值試試」是歷史上所有迴歸的來源。

## 何時使用

- 使用者回報某輪採集出問題（通常附 Hxxx 編號或大概時間）
- 想調 config 門檻、OCR 前處理、排除清單、verify 邏輯、vision 偵測、音訊參考
- 不適用：全新功能（走 brainstorming → writing-plans）

## 迴圈（順序不可跳）

1. **取事故編號**：事故＝出事那一輪的採集編號 `Hxxx`（harvest_id，持久化流水號，貫穿 log／快照檔名／Discord）。在 `logs/` 內 grep 該編號即撈出全部證據。
2. **先收證據，不改碼**：
   - `logs/harvest.log`（sweep/D3/verify 逐步）＋ `logs/miningbot.log`（主敘事）
   - `logs/snapshots/trace/` 內該輪的 `*_chat_ocr_*.txt`（verify OCR 全文落盤）
   - `logs/snapshots/` 該輪截圖（檔名含 Hxxx）、Discord 附圖
   - 用時間戳排出時間線：觸發→sweep→開火→verify→收場，每步發生了什麼。
3. **一句話根因**：格式「X 因為 Y 所以 Z」，每個環節有 log 佐證。只說得出症狀 → 停，走下方升級條件。
4. **樣本固化成 fixture**：聊天裁圖 → `tests/fixtures/chat/hxxx_<desc>.png`；追蹤框場景 → `assets/<desc>_scene.png`；音訊 → `add_chill_ref` 流程。**無樣本的修復＝下次必迴歸。**
5. **TDD**：先寫用 fixture 重現事故的失敗測試（紅），再修（綠）。
6. **門檻兩側夾**：新門檻必須同時列出「真值分數」與「誤收值分數」（例：H020 真值 0.545/0.727、誤收 0.500/0.600 → 取 0.62）。寫不出兩側數字＝證據不足，回步驟 2。
7. **查安全方向表**（下）決定偏哪邊。
8. **回歸**：`python -m pytest -q` 全綠；動過 OCR 前處理必過 `tests/test_ocr_fixtures.py`；動過 vision 必過 assets 場景回歸。
9. **文件化**：CLAUDE.md 對應段落補「（日期 Hxxx 對策）根因＋對策」；memory 對應檔同步更新。
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
- 動 verify／episode 帳本／聊天基準前，**先整段重讀 CLAUDE.md「稀有礦採集流程」步驟 6**——每個分支都對應一個實機事故，看似冗餘的都不是。

## 升級條件（小模型停手，交人／大模型）

任一成立 → 不改碼，把時間線＋證據整理成報告：

- 說不出一句話根因
- 修復需要改狀態機結構、或跨 3 個以上模組
- 事故型態不像 CLAUDE.md 任何已知 H 案例
- 只能靠新的實機實驗判斷（離線重現不了）

## Quick Reference

| 要做 | 命令 |
|---|---|
| 全測試 | `python -m pytest -q` |
| OCR fixture 回歸 | `python -m pytest tests/test_ocr_fixtures.py -q` |
| 撈某輪證據 | 在 `logs/` 內 grep `H0xx`（log 行＋快照檔名都會中） |
| 讀 log 不亂碼 | `Get-Content logs\harvest.log -Encoding UTF8 -Tail 100` |
| 實機截圖 | 見 CLAUDE.md「實機排錯」一行命令（要先設 DPI-aware） |
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
