# REX 遊戲機制筆記（自動化依據）

本檔只記錄會影響自動化決策的遊戲機制。實作細節與門檻以程式、測試和
`miningbot/config.py` 為準；事故量測與門檻來由放在 `docs/incidents.md`。

## 通則

- 礦坑背景、光線與整體色偏會隨區域改變，不能把背景顏色當固定特徵。
- 工具鍵會切換裝備；對已裝備工具再按一次會卸下。
- 工具效果與冷卻圖示共用右下角 UI 區域，其他 buff 會讓圖示位置位移。
- 所有座標以最大化 1920×1080、Windows taskbar 可見的實機畫面校準。

## D5 — Boost

- 生效中的 boost 以右下角瓶子外觀判斷；倒數數字會變，模板不可包含數字。
- 現行偵測使用 `boost_indicator_region`、`boost_edge_threshold` 與
  `boost_buff_scales`，預設為固定 UI 尺寸的單尺度比對。
- 瓶子消失才補 D5。補瓶前必須釋放挖礦左鍵，完成 D5 點擊與 settle 後再走
  `miner.init_mining_sequence()` 恢復 D1、W 與左鍵。

## D4 — Activity

- 左鍵加強目前事件；右鍵刷新事件。
- 現行 readiness 依 `Config.activity_cooldown_template` 指向的
  `assets/d4_cooldown.png` 判斷，模板缺失時才使用有明確 log 的定時 fail-safe。
- D4 事件名稱由 OCR 交給 `game_data.match_event`，keep/reroll 決策來自目前世界
  與 keep 清單。

## D2 — Scan

- 按 2 只裝備 D2；還必須點擊畫面中央才真正掃描。
- 掃描會產生 tracker，tracker 可因掃描到期、畫面變化或其他原因自行消失。
- tracker 消失只表示需要重新定位／重掃，不能單獨證明 D3 採集成功。

## D3 — 稀有礦採集

- 固定輸入序列：`2 → 0.15s → 3 → 0.3s → hold-click 0.4s → 0.5s`。
  先按 2 是為了確保 D3 不會因 toggle 被卸下。
- D3 以 tracker 的螢幕座標作為點擊目標；開火前必須在最新畫面重新定位。
- 成功只認 episode 內新增的稀有／特殊 `has found` 聊天證據。
- 判定矩陣：

  | 聊天確認 | tracker 狀態 | 結果 |
  |---|---|---|
  | 有 | 任意 | `SUCCESS` |
  | 無 | 已消失 | `RESWEEP` |
  | 無 | 仍存在 | `RETRY` |

## 聊天確認

- HARVESTING 進場時截一次 episode 基準；OCR 可延後到開火後執行。
- `ocr.ChatLedger` 以逐次 OCR 鏈式對齊新增行，跨 D3 重試與 `RESWEEP` 保留。
- 低階／被動挖到的礦由目前世界的 `common_ores` 排除；只有新的稀有／特殊
  行能確認成功。
- 錨點對不上、OCR 引擎缺失或白名單不可用時採保守 fail-safe：保留證據、
  不製造成功結果，並讓後續重讀或人工路徑接手。
- RapidOCR 是聊天首選；既有 tesseract 多前處理路徑是已測試的相容降級。

## NORMAL 面板與篩選框

- 左下面板列出背包內容（NORMAL／IONIZED／SPECTRAL 三個頁籤）。面板上方有一個
  篩選框（filter box），輸入文字即時過濾顯示的 礦。
- 篩選框是**即時且持續**的：打字進去就觸發 filter 重評估，面板只顯示匹配的 礦。
  打一個不匹配任何 礦名的字串（bot 用 `w`）→ 面板清空。filter 不會在挖礦期間
  被關閉——按 D1/D2/D3、旋轉視角等動作不影響它。
- **挖到新 礦時遊戲將它加到面板上**（bypass 當前 filter），所以面板上顯示的是
  「上次清空後新增的 礦」。這是救援路 B 的存在性判準：面板上有白名單 礦＝這場
  採到了（H069）。
- 進 MINING 時 bot 打 `w` 進篩選框清空面板、重設「這輪」邊界（`_clear_panel_filter`）。
  觸發時機：採集成功歸位、NEEDS_HUMAN 按 Q 繼續、開機首次進場——所有 MINING 入口都跑。
  打字進 TextBox 就會觸發 filter——框裡累積多少 `w` 不影響效果（8 個跟 80 個一樣）。
- 篩選框只增不減（`typewrite` 是附加）。顯示壓縮飽和後再多打 `w` 一個像素都不變，
  但 filter 照樣重跑、面板照樣清空（H071b 實機確認）。墨量量測在飽和狀態下是
  噪訊，只當 log 線索、不當判準（H071）。

## 世界與礦物資料

- 有效世界以 `miningbot.game_data.WORLDS` 為唯一 registry。
- `python -m miningbot.fetch_ores` 從 wiki 同步資料並排除已移除或合併的世界；
  產物是 `assets/rare_ores.json` 與 `assets/ores_all.json`。
- D4 events 與低階排除清單仍由 `game_data.py` 的 active-world 資料提供；修改
  後必須跑世界、衝突與分類測試。

## Reset 與回礦

- 只有 reset banner 可以停止挖礦並進入 reset 流程。
- 容量到 100% 只記錄資訊並加速 banner 輪詢，不能觸發 `RESET_WAIT`。
- Reset 完成後行為由 `Config.reentry_mode` 控制：`off` 等人工、`remote` 使用
  遠端指位、`auto` 使用已校準地表模板。
- 自動與遠端路徑都必須有嘗試上限；失敗進 `NEEDS_HUMAN`，並復原 pitch/zoom。

## Z — Cybernetium Radar

Z/cave 自動化目前不是一般 mining tick 的啟用路徑。保留遊戲機制與舊實驗
證據，但不得把舊 `scan_event.png`／`cave_event.png` 文件當成現行觸發規格。

新的實機觀察先寫入 `docs/incidents.md` 並附 frame/log/fixture，再更新本檔。
