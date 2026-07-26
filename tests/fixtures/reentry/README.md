# `reentry/` — 回礦流程

三組互不相干的素材，共用這個目錄。

## 一、H044 傳送驗證兩側夾

`reentry_game_region(1100, 200, 690, 650)` 的 690×650 裁圖。判定「畫面到底有沒有變」
用前後幀差。

| 檔案對 | 情境 | 量測值 |
|---|---|---|
| `h044_teleport_a.png` + `h044_teleport_b.png` | **真的傳送了** | mean 57.73／frac 0.9966 |
| `h044_alive_static_a.png` + `h044_alive_static_b.png` | 活著但站著不動 | mean 0.09／frac 0.0004 |
| `h044_frozen_a.png` + `h044_frozen_b.png` | **重生凍結**（角色卡住） | mean 0.00／frac 0.0000 |

三態之間差了好幾個數量級，門檻好定。重點是**凍結與靜止必須分得開**：凍結是逐位元
0.00，靜止還有 0.09 的雜訊底。開場閘用的是 `probe_frozen`（認 0.00），不是 pitch 那套。

⚠ 改 `reentry_game_region` 座標的話，這批 fixture 必須從 `logs/snapshots/` 原幀**重裁**，
不能沿用。

## 二、H046 Depth 狀態錨

| 檔案 | 顯示 | 意義 |
|---|---|---|
| `h046_depth_surface.png` | Surface | 還在地表 |
| `h046_depth_488m.png` | 488m | 已下礦（淺） |
| `h046_depth_25790m.png` | 25790m | 已下礦（深） |
| `depth_7100m_shamrock_landing.png` | 7100m，Shamrock 世界落地幀 | 層別反推語料 |

Depth 從 Surface 翻成 NNNm ＝**真的下礦了**，這是開場閘的狀態錨。幀差只能當輔助訊號：
重複點已成功的傳送板畫面可能不動（假失敗）、地表→地表換重生點畫面大動（假成功），
轉移式驗證兩頭都會判錯。

## 三、H050 放大圖漂移守門

| 檔案 | 是什麼 |
|---|---|
| `h050_zoom_dir1_d2_snap.png` + `h050_zoom_dir1_d2_snap_3s.png` | dir1 D2 格快照，兩個時間點 |
| `h050_zoom_dir1_e2_snap.png` + `h050_zoom_dir1_e2_snap_3s.png` | dir1 E2 格快照，兩個時間點 |
| `h050_zoom_dir1_e2_live_drift.png` | **現場已漂移**的同格畫面 |

sweep 轉滿一圈會有 ~6° 殘差，快照與現場之間沒有守門就會對著過期畫面點下去。
兩側夾：漂移 29.66／21.6 vs 未漂移 ≤3.14 → 門檻 `zoom_drifted = 12.0`。

## 相關事故

H043 虛空墜落、H044 重生凍結、H045 撤離預設關、H046 狀態制開場閘、H048 歸位被吃
（右鍵拖曳被指標加速甩出視口）、H050 放大圖漂移、H051 重置中採集收尾斷鏈、
H052 歸位誤報、H053／H058 開場容量閘。全文見 `docs/incidents.md`。

⚠ **每輪 attempt 都會按「回到地表」換重生點＝隨機化 yaw**，所以 sweep 的 `cur_dir=0`
基底是隨機的（僅 attempt 1 例外）。這批素材 100% 是 Lucernia + Shamrock + 夜晚
（Lucernia 設定上恆夜），單層語料無法否證「名牌＝當前層」這類假說——用它們推論方位
前先確認外部對照。
