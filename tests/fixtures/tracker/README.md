# `tracker/` — `find_tracker` 的實機兩側夾語料（H057 同色黏連、H068 擋角軟收）

| 檔案 | 來源 | 期望 |
|---|---|---|
| `h057_green_on_green_manual.png` | 097 dir4 手動掃圖 | 命中真框 (983,435)；**不得**命中角色的臉 (959,547) |
| `h057_green_on_green_sweep.png` | 097 sweep dir4 幀（16:20:43） | 必須偵測到（修復前整格全空 → 交人工） |
| `h068_avatar_occluded_tracker.png` | 129 sweep dir4 幀（2026-07-30 20:07:45） | 命中真框 (937,458)（edge=0.36 colored=0.86，框壓在角色頭頂被擋角）；同幀 (1054,655) edge=0.30 colored=0.87 必須留在門檻外 |
| `h068_panel_vs_tracker.png` | 141 sweep up dir6 幀（2026-07-31 02:31:39） | 命中真框 (1396,815)（edge=0.36 colored=1.00）；**不得**命中裝備 (1375,719)（0.36/0.56）或左側 NORMAL 面板文字 (70,869)（0.33/0.86，靠 `ore_panel_region` 排除） |

## H057 — 同色黏連（097 dir4）

### 根因

同色黏連：綠框跟背後的受光綠牆連成一大塊輪廓，色彩遮罩切不開。修復前
`find_tracker` 回報 (959,547)＝**角色的臉**，分數 0.61 是**借來的**——那 0.61 其實來自
ROI 內偏移 114px 的真框，而真框自己連候選都進不了。

### 兩個機制各自有隔離測試

- **重錨**：`confirmed` 座標必須搬到形狀命中的中心，不能留在借分的候選中心。
  `test_h057_reanchor_alone_redeems_borrowed_score` 關掉救援（`rescue_v_min=None`）
  單獨驗重錨就足以把答案從臉救回真框。
- **V-submask 救援**：`confirmed` 全滅時，對超大輪廓（V≥150）做二次分割。

兩個都要留——關掉任一個都有實機幀會失敗。

## H068 — 框被角色/裝備擋角，edge 掉進 0.33~0.41（129/133/141）

玩家在網頁標註工具把整輪 sweep 全空的幀標成 `false_negative`，離線重放量出兩側：

- **真框（當時被拒）** edge/colored：0.33/0.86、0.36/0.86 ×3、0.40/0.86、0.41/0.86、0.36/1.00
- **誤收側 colored≥0.80 群** edge 最高 **0.33**（`assets/bottom_edge_tracker_scene.png`
  的粉紅岩層，colored=1.00），其餘 0.31/0.30/0.29/0.28
- **edge≥0.35 群** colored 最高 0.56（裝備）；角色 0.73 只到 edge 0.33

→ `tracker_shape_soft_edge=0.35` + `tracker_shape_soft_colored=0.80`（岩層之上留 0.02、
角色之上留 0.07）。edge 單軸已經沒有 gap，**別再想只調 `tracker_shape_threshold`**。
0.33 那顆真框（133 dir4 (979,550)）與粉紅岩層同分，這條路救不回——見
`docs/open-detection-issues.md` D09。

## ⚠ 這批素材要跟合成圖分開看

無視覺 agent 只能用合成圖驗演算法，而合成圖**沒有同色干擾物**——測試全綠仍可能對地形
開火。碰偵測門檻時務必回來掃這四張真幀，並**肉眼看每個命中**（H068 就是這樣抓到
「(1154,937) 不是 hotbar 而是粉紅岩層」的）。

`find_tracker` 現行管線與更早的事故索引見記憶檔 `project_find_tracker`／
`docs/incidents.md`。舊版「ring_score < 0.15 硬拒」已被 H001~H013 廢除，別加回來。
