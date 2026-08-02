# `panel_tiers/` — NORMAL 面板列底色的階級色相

`TIER_HUES`（`game_data.py`）與 `panel_whitelist_hues`／`panel_low_tier_hues`
（`config.py`）的實機依據。兩張都是 1920×1080 全幀，測試自己裁
`cfg.ore_panel_region`。

| 檔案 | 涵蓋階級 | 為什麼留這張 |
|---|---|---|
| `tiers_high4_20260802.png` | Otherworldly 334／Unfathomable 220／Enigmatic 70／Transcendent 210 | **Unfathomable 與 Otherworldly 先前只有 wiki 色碼、沒有實機量測**，這張是第一份實機證據 |
| `tiers_mixed6_20260802.png` | Transcendent 210／Exquisite 128／Exotic 46／Mythic 304／Surreal 166／Master 280 | 含三個 LOW_TIERS，驗證它們**正確地不在** `TIER_HUES` 裡（在的話零點閘會誤判） |
| `tiers_grey_lowtier_20260802.png` | Transcendent 210／Mythic 304／Rare 30／Uncommon 0／**Common 灰**／**Layer 灰** | 唯一有**灰階列**（S=0）的素材。H 對灰階無意義，兩種灰只能用 V 分辨 |

## 灰階列（S=0）

`Common` 與 `Layer` 是最底層階級，底色是純灰 → **H 無意義**（`panel_row_hues` 回 0.0）。
兩者只差亮度，在色帶起點 x=18 量到：

| 階級 | x=18 的 V | wiki |
|---|---|---|
| Common | **192** | `C1C1C1` = 193 ✅ |
| Layer | **132** | 色碼待查 |

現行 H-only 判定對它們是**正確的**：H=0 落在 `panel_low_tier_hues` 的 0.0 帶 → 零點閘
放行、白名單閘不命中，兩者都對。但這是「H=0 剛好也在低階帶」的巧合而非設計——
**若將來出現 H=0 的高階礦，這條會反過來咬人**（wiki 現有 14 階裡沒有，暫時安全）。

⚠ 量測腳本若用 `S>60` 過濾，會**整列跳過灰階列**——輸出看不到它們，是盲區。

`ground_truth.json` 記每條帶的 y 範圍、色相與來源礦名。**階級是拿礦名查
`rare_ores` 獨立確認的，不是看顏色反推**——否則等於拿結論驗結論。

## 固定取樣協議（改量測方式前先讀）

量測工具：`uv run python -m miningbot.measure_tier_hues`（省略路徑＝抓當下畫面；
`--save out.png` 順便存檔）。三條規則缺一不可：

1. **固定窗 `cfg.panel_hue_sample_x`（120-165）** — 與 production 同一塊像素。
2. **逐列中位 → 跨列中位，不用平均** — 礦名文字是少數像素，中位吃不掉；
   環形平均會被抗鋸齒污染。2026-08-02 首量 Unfathomable 得 227.4°（差 8.4°、
   看起來像「表值錯了」），改逐列中位後是 220.0°。**那次差點寫出一個假修復。**
3. **S>60** 濾掉灰階與文字邊緣。

## 漸層（使用者 2026-08-02 提出的疑慮）

面板每列**有漸層，但只在 V 上**：Transcendent 帶從 x=20 的 V=252 掉到 x=212 的
V=68，而 H 沿整條列恆定 210.0°（幅度 0.0°），垂直方向同樣恆定。

→ 取樣位置改變 V、**不改變 H**。色相閘只用 H，所以階級判定不受取樣位置影響。
**但要加 S/V 判據時，必須連取樣窗一起指定**，否則數字無意義——灰階列就是這種情況
（Common vs Layer 只差 V），在現行取樣窗 (120,165) 量到的 V 已衰減到原色的 ~55%。

### 色帶起點 x=18 ＝ wiki 官方色

漸層的**起點就是原色**。三張幀 14 條帶逐一比對，x=18 的像素與 wiki HEX 相差
ΔBGR ≤2：

```
Transcendent  x=18 [254,127,0]   wiki 0080FF [255,128,0]
Enigmatic     x=18 [0,244,203]   wiki CDF600 [0,246,205]
Common        x=18 [192,192,192] wiki C1C1C1 [193,193,193]
```

**目前沒有改用它**——現行 H-only 判定在 (120,165) 已全數正確（三張幀 21 條帶零誤判），
換取樣窗要重驗每一條既有迴歸，不值得。x=18 的價值在**將來要加 S/V 判據時**：那時 H
不夠用，就需要這個色度未衰減的錨點。

## 缺口

`Imaginary` 與 `Zenith` 至今無樣本（使用者未取得）。wiki 給 Imaginary 雙色碼
`EEBA44`+`C9DEE9`（42°+201°）＝**雙色漸層**，固定窗只會讀到其中一個或混色，
實機看到之前不寫值。目前靠 `non_low_tier_hues` 反向閘兜住：未知色相一律當高階
（保守方向是多交一次人工，不會放生礦）。
