# 06 — 一週實機分布 → 填 `chill_edge_release_s` 並開啟對帳

**What to build:** 01/02/04/05 上線後跑滿一週，從 02 記的上升緣／回落時間戳統計實際間隔分布，
用資料填 `chill_edge_release_s`，然後才開 `chill_reconcile_enabled`。同時回頭修正
`prechill_min_age_s` 的保守初值。

**門檻猜錯會直接製造新的人工次數**，與「只做保守救援」的方向相衝——在有分布之前不要接通知。

已知的一個真實間隔：07-29 14:43:58 → 14:44:14，**16 秒**。重疊 <2s 的兩聲，現在的分數形狀
分不出來，需要資料才知道那種情況存不存在。

**Blocked by:** 04（救援上線才有 `HARVEST_RESCUED` 可比淨值）、05（對帳程式與開關）。

**Status:** ready-for-agent

- [ ] 收滿一週實機 `harvest.log`，統計上升緣與回落的間隔分布（含同一聲內多 tick 的形狀）
- [ ] 用分布定 `chill_edge_release_s`，寫進 `config.py` 並在註解記下依據與量測日期
- [ ] 回頭檢視 `prechill_min_age_s = 3.0` 是否需要修正（太新可能已含那次挖掘、太舊會把無關
      挖掘算進差分）
- [ ] 開 `chill_reconcile_enabled`
- [ ] 淨值檢查：對帳**新增**的人工次數 vs `HARVEST_RESCUED` **省下**的人工次數；救援要大於對帳，
      否則整體是退步
- [ ] 重新統計救援命中率／誤判率（**樣本只有 2，不要拿 1/2 當結論**）
  - **命中**（自動）：`grep HARVEST_RESCUED` events.log，或翻 Discord 數 🛟
  - **漏判**（人工）：翻每則 `NEEDS_HUMAN` 的背包「後」裁圖——稀有礦名在上面但救援沒攔
    → 漏判。查 `harvest.log` 分類降級原因（見 rescue spec「實機驗證方法」表）
  - 只統計 reason 是「全方位掃描未找到追蹤框」的 giveup——D3 超時型的礦可能還在畫面上，
    救援不適用
- [ ] 觀察「上一場採集剛結束、還沒回到 MINING 就又 chill」拿到較舊參考的發生頻率，決定要不要處理
- [ ] **www 篩選框武裝的決策**：只有當漏判分類顯示「裁圖上有名字、差分說無」**且**那名字
      是本 session 早先挖過的同一種（同礦種重複盲）時，才值得動手做 www 武裝。裁圖上沒
      名字＝不是 www 的鍋。bot 不碰篩選框的既有決策見 rescue spec「篩選框的角色」與
      2026-07-30 使用者討論（啟動時 LMB 未按住可打字、但 per-harvest 打字 LMB 已按住且
      解不了同場雙 chill；www 是覆蓋率條件不是正確性條件，現階段帳號沒有那些礦＝做了也
      no-op）
- [ ] 結果寫進 `docs/incidents.md` 或 `docs/open-detection-issues.md`，並 commit 設定變更（中文訊息）
