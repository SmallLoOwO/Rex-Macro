# 手動取樣使用說明

手動取樣把「值得當樣本的畫面」存成編號截圖與 sidecar，供回礦校準、tracker
模板或 OCR regression 使用。實際輸出根目錄由 `Config.log_dir` 決定，不假設
一定在 repository 的 `logs/`。

> 2026-07-17 起 R 鍵取樣視窗（Tk 面板）退役，功能移到 Discord：
> 截圖＝遙控器 📷 反應鈕；俯仰控制＝回礦流程的 `仰角` 指令。

## 基本操作

| 操作 | 效果 |
|---|---|
| 遙控器點 📷 | 立即抓當前畫面，存 `snapshots/manual/NNN.png`＋`NNN.json` sidecar，並回傳 Discord（訊息含編號） |
| 回礦中回 `仰角 歸位` | 右鍵拖到俯仰夾限，再回拉 `reentry_pitch_back_px`（冪等，被吃自動重試一次） |
| 回礦中回 `仰角 上 [px]`／`仰角 下 [px]` | 微調視角；省略像素時用 `sample_pitch_step_px`。微調不重送（誤重送＝角度記帳脫鉤），懷疑沒動就 `仰角 歸位` |
| 回礦中點 📷（episode embed） | 重新八方位掃描（與遙控器 📷 不同：那是單張即時截圖） |

Sidecar 保存時間與俯仰偏移，讓校準值可重現而不是靠目測。

注意：`仰角` 指令目前只在 REENTRY（回礦流程）內消費；一般挖礦中要調視角
請先 `回礦`（手動回礦）或暫停後人工調整。

## 自動回礦校準

在把 `reentry_mode` 設成 `auto` 前，先收下列實機樣本。模板未完成時保持
`off` 或 `remote`。

1. **礦內亮度**：仍在礦坑時用遙控器 📷 截圖，記下編號。
2. **地表／傳送面板**：手動回地表（或 `回礦`），`仰角 歸位` 並微調到看得見
   傳送面板後 📷。隨機重生點、距離和角度應各留數張。
3. **傳送 UI**：走近面板讓層級按鈕出現後 📷，用來核對
   `reentry_target_layer` 與 `reentry_decoy_buttons` 的實際文字。
4. **匯入與亮度校準**：

   ```powershell
   uv run python -m miningbot.calibrate_surface --import NNN
   uv run python -m miningbot.calibrate_surface --brightness NNN
   ```

   第一個命令裁出 `assets/surface/panel_NNN.png`；第二個分別量礦內與地表
   亮度。把兩組實測值的安全分界寫回 `Config`，不可憑感覺猜門檻。

## 其他用途

- Tracker：保留漏抓真框的完整畫面；runtime 裁圖放在本機
  `assets/markers/`，要成為 regression 的場景則放進追蹤的 `tests/fixtures/`。
- OCR：保留新背景下的聊天框，裁成具名 fixture 並記錄對應 H 事故。
- Reset/menu：保留 banner 或選單 OCR 近失畫面，新增 TP 與對應負樣本。

## Tk 限制（HUD 仍適用）

- 不要建立第二個 `tk.Tk()`；Tk 物件只能由 HUD 主執行緒建立/銷毀。
- 這台 Tcl/Tk 8.6 的 widget 文字不能包含 astral emoji。`◉`、`▲`、`▼`、
  `⚠` 可用；自由文字仍要經過 `_bmp_safe`。
- 熱鍵／輪詢執行緒只發布意圖，Tk 與遊戲輸入由各自擁有的主迴圈處理
  （唯讀截圖除外：capture 每執行緒自持 mss 實例）。

## Zoom 歸位校準

`zoom_reset_pullback_steps=0` 時遠／近指令停用。量測方式：

1. 把鏡頭調到平常挖礦距離並截圖留參考。
2. 重複按 I 到第一人稱夾限。
3. 一步一步按 O，數到畫面回到參考距離；步數就是 K。
4. 把 K 寫入 `zoom_reset_pullback_steps`。
5. 實機跑一次遠距調整再跳過，確認歸位畫面與參考圖一致。

`zoom_eaten_*` 門檻只能依兩側實測值調整。門檻來由與 pitch/zoom 事故證據
留在 `docs/incidents.md`。
