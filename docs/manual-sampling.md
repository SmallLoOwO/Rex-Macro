# R 鍵手動取樣使用說明

R 鍵開一個小視窗，讓你在遊戲裡「看到值得留檔的畫面」時按幾下就存成**編號截圖**，
之後用編號餵給校準工具（`calibrate_surface`）或裁模板/補 OCR fixture。

## 基本操作

| 操作 | 效果 |
|------|------|
| 按 **R**（bot 執行中，焦點在遊戲也有效） | 開啟取樣視窗；**正在挖礦會自動暫停**（避免 W+左鍵跟取樣拖曳互搶輸入） |
| 再按 **R** 或點視窗 X | 關閉取樣視窗（**不會自動恢復挖礦**——視角多半已被拖歪） |
| 取樣完 | 自己把視角調回去，按 **Q** 恢復挖礦 |

視窗開在螢幕左側（HUD 上方），置頂。實際建窗由 HUD 執行緒處理，按 R 後最多 ~0.3s 出現。

### 視窗按鈕

| 按鈕 | 做什麼 |
|------|--------|
| **俯仰歸位** | 按住右鍵把視角俯仰拖到夾限飽和、再回拉固定量（`reentry_pitch_back_px`）→ 得到**可重現**的已知仰角 |
| **▲ 上 / ▼ 下** | 俯仰微調一步（`sample_pitch_step_px`，預設 40px）；label 即時顯示目前偏移量 |
| **📸 截圖** | 全幀存 `logs/snapshots/manual/NNN.png`＋sidecar `NNN.json`（記俯仰偏移量與時間） |

sidecar 的意義：找到「合適的仰角」後，那個偏移量是個數字，可直接寫回 config
（例如調 `reentry_pitch_back_px`），不用憑感覺重調。

點按鈕時焦點會先切回 Roblox 再送鍵/拖曳（約 1 秒），是正常延遲。

## 回礦校準（reentry）取樣流程

`auto_reenter` 開起來之前要先收三種樣本。**建議順序**：

1. **礦內亮度樣本**——人還在礦坑裡時：按 R → 📸。
   記下編號（例 `005`），供步驟 4 的 `--brightness` 當「礦內」組。
2. **地表面板樣本（第一次：go to surface 後拍）**——遊戲選單按「回到地表」，
   出生在地表後：按 R → **俯仰歸位** →（可用 ▲▼ 微調到能看清傳送面板的視角）→ 📸。
   畫面裡要**看得到傳送面板**（不用很近）。這張是面板模板與「地表」亮度樣本的來源。
   - 重生點是隨機的（reroll 就是再按一次回到地表換點）：**多拍幾張不同重生點/距離/角度**，
     模板多張比對更穩（`assets/surface/` 內全部 `panel_*.png` 都會拿來掃）。
3. **傳送面板 UI 樣本（第二次：走到傳送板上拍）**——走近傳送面板讓傳送選單打開
   （顯示 Mantle Layer 等各層按鈕）→ 📸。
   這張用來人工核對按鈕文字：`reentry_target_layer`（要去的層）與
   `reentry_decoy_buttons`（絕不能誤點的按鈕，如 "Back to pre-reset location"）
   拼字要跟畫面一模一樣，OCR 才能嚴格分勝負（寧漏勿誤：分不出就 reroll 不點）。
4. **把截圖變成資產**：
   ```
   python -m miningbot.calibrate_surface --import NNN      # 開步驟 2 的圖，框出面板 → assets/surface/panel_NNN.png
   python -m miningbot.calibrate_surface --brightness NNN  # 步驟 1（礦內）與步驟 2（地表）各跑一次
   ```
   兩組亮度取中間值填 `config.reentry_mine_max_brightness`（礦內應遠低於地表）。

## 其他用途

- **裁追蹤框模板**：漏抓的真框畫面（新階礦）按 R 留檔，之後裁進 `assets/markers/`。
- **補聊天 OCR fixture**：新背景（糖果礦壁等）下的聊天框畫面留檔，
  裁進 `tests/fixtures/chat/` 跑回歸。

## 踩坑備忘（2026-07-10 修復，兩個獨立 bug 疊加）

取樣視窗曾經完全不顯示（按 R 沒任何反應、log 卻顯示開啟/關閉交替）：

1. **第二個 Tk root 靜默失敗**：舊版 `SamplerWindow` 自己開執行緒跑第二個 `tk.Tk()`，
   但主執行緒已有 HUD 的 Tk mainloop 時，第二個 root 的 OS 視窗**永遠不會建立**
   （執行緒活著、after 回呼有跑、EnumWindows 卻列不到視窗）。
   修法：改成 HUD 執行緒上的 `Toplevel`（`sampler.SamplerPanel`），
   熱鍵只翻 `_sampler_want` 旗標、HUD `_poll` 每 300ms `sync_sampler_ui` 同步建/銷視窗。
   `hud_enabled=False`（無 HUD）時仍走舊執行緒版視窗（該情境沒有第二 root 問題）。
2. **astral-plane emoji 卡死 Tk 事件迴圈**：按鈕文字裡的 📸（U+1F4F8，超出 BMP）
   會讓這台 Tcl/Tk 8.6 的**整個事件迴圈無聲卡死**（無例外、無崩潰；二分實驗定位）。
   修法：按鈕改 ◉（BMP 安全）；`last_action` 等會流進 HUD label 的自由文字，
   HUD 端統一過 `status_hud._bmp_safe` 剝掉 >U+FFFF 字元當防線。
   **教訓：任何要進 Tk widget 的字串都別放 emoji**（📸🔔🤖🎮 全是 astral；
   ● ⚠ ▲ ▼ ◉ 是 BMP 安全的）。log/Discord 文字不受限。
