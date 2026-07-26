# `pitch/` — 俯仰動作「真的動了」vs「被吃」兩側夾

右鍵拖曳的俯仰動作**經常被遊戲吃掉**（指標加速把游標甩出視口、視窗剛失焦等）。
判定靠前後兩幀的畫面差：`harvester.rotation_looks_eaten(mean, frac, ...)`。

**必須成對**：每個情境都是 `_before.png` + `_after.png`，缺一半就沒有差值可算。

| 對 | 情境 | 期望 |
|---|---|---|
| `eaten_reset_before.png` + `eaten_reset_after.png` | 歸位動作被吃 | 判「被吃」 |
| `eaten_reset_hi_before.png` + `eaten_reset_hi_after.png` | 同上，被吃樣本中差值較高者 | 判「被吃」 |
| `eaten_nudge_hi_before.png` + `eaten_nudge_hi_after.png` | **被吃樣本的最高值**（mean 3.29／frac 0.045） | 判「被吃」 |
| `real_nudge_lo_before.png` + `real_nudge_lo_after.png` | **真生效的最低值**（mean 32.49／frac 0.63） | 判「生效」 |

## 兩側夾

`test_pitch_thresholds_bracket_eaten_and_real` 直接鎖住：

```
eaten_mean(3.29) < cfg.pitch_eaten_mean_diff < real_mean(32.49)
eaten_frac(0.045) < cfg.pitch_eaten_changed_frac < real_frac(0.63)
```

被吃最高值與真生效最低值之間有一個數量級的 gap，門檻必須落在中間。**動門檻前先跑
這個測試**——它會直接告訴你新值有沒有跑出 gap。

## 為什麼俯仰不能共用旋轉門檻

`test_eaten_reset_would_pass_old_rotation_threshold` 是回歸鎖：舊的旋轉門檻
（2.0／0.02）會把 `eaten_reset` 樣本判成「生效」（frac 0.022 > 0.02 剛好翻面）。
有人把俯仰驗證改回共用旋轉門檻時這個測試必紅。

## ⚠ 夜間判讀陷阱

礦內夜間場景**真的動了 mean 也只有 0.93~5.13**，落在被吃區間裡——這批白天素材的門檻
不適用於夜間。H052 的對策是開場鏈與「歸位」指令改認 `probe_frozen`（逐位元 0.00），
不用 `pitch_eaten`；微調／挖礦歸位／旋轉才照舊。詳見 `docs/incidents.md` H048/H052。
