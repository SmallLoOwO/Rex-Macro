# 回礦退層指令 + 精細選擇時卡可見性收斂（2026-07-20）

日期：2026-07-20
狀態：設計定案，待實作計畫
前置：`2026-07-12-remote-reentry-design.md`（遠端回礦主設計）、`2026-07-12-reentry-zoom-design.md`（`方位 粗格`／`放大 <細格>` 與漂移守門）、`2026-07-19-aim-candidate-presentation-design.md`（反應鈕與遙控器並存語意）

## 背景與問題

2026-07-20 使用者反映回礦遙控器三個斷點：

1. **放大錯格後回不去（bug）**：`方位 粗格`（如 `3 C2`）→ 進等細格；`放大 <細格>` 可連鎖放大。每放大一層 `ctx.zoom_region` 被**覆寫**成更小子區域（`_rr_zoom` line 4661、`_rr_magnify` line 4674）。沒有退回指令；要脫身只能重下方位粗格（要記得原本看哪格）、`📷` 重掃（會重置鏡頭距離＋重轉一圈）、`🎲` 重骰、`⏭️` 跳過回挖礦。一旦放大到錯的子區域，後續 `放大`／細格點擊都建立在錯格上 → 「一錯再錯，沒辦法回去」。

2. **精細選擇時回礦卡還在釘底重貼**：`_repin_tick`（line 1631-1639）在 REENTRY 中，只要頻道有新訊息（**含 bot 自己發的放大圖**）且安靜滿 `discord_repin_quiet_s`，就刪舊回礦卡、貼新的到頻道底。等細格時使用者正在放大圖上數格，卡被重貼到最新位置會把放大圖往上推、捲動位置跳動 → 干擾。使用者：「上面的需求都是在沒看到正確畫面才用」——卡上的 `方位 粗格`／`放大`／`重骰` 是 `awaiting_cmd` 階段用的，進入精細選擇後就不該再刷。

3. **脫離 REENTRY 後挖礦遙控器沒補回**：`_rr_finalize` 只立 `_remote_repin.mark_pending()`（line 4060）；真正重貼在 `_repin_tick` 等 `due()` 成立（`pending and now - last_activity ≥ quiet_s`，notify.py line 307-309）。但 finalize 後 bot 還會發成功通知／補瓶通知，這些訊息讓 `note_activity` 把 `last_activity` 一直刷近 → `due()` 不成立 → 遙控器要等頻道真正安靜 `quiet_s` 才回底部。使用者：「一旦確認完畢選擇好，便沒有遙控器可用，需要直到有新訊息出現」。

## 核心不變量

- 退層不改變實際面向（`cur_dir`）、不重掃、不動鏡頭距離（`net_zoom`）；只回溯 `zoom_region` 鏈。
- 退層是「放大圖層級」的回溯，不是「重截歷史幀」——退到的那層用「退層當下的現場幀」重渲染（畫面可能已漂移），漂移守門基準 `_src` 同步更新到該幀，`_rr_click` 邏輯零改動。
- 暫停的是「釘底重貼」（刪舊卡貼新卡到頻道底）；原地 PATCH（改 phase／分鐘數，不挪位置、不推播）全程保留。
- 退出精細選擇與脫離 REENTRY 都要「立刻」讓對應卡回到底部，不靠新訊息觸發、不等 `quiet_s`。

## 設計

### 1. 退一層指令（`退`／`back`）

**`RemoteReentryContext` 新增兩欄**（reentry_remote.py）：

- `zoom_stack: list = field(default_factory=list)` — 放大層歷史。元素 = `None`（空層標記，代表首次放大之前的 `awaiting_cmd`）或 `{"region": tuple, "base": str, "scale": int}`（某次連鎖放大之前的上一層快照）。
- `zoom_scale: int = 0` — 當前層渲染倍率（首層＝`cfg.reentry_remote_zoom_scale`；連鎖層＝`magnify_scale` 算出）。退層重渲染時用它。

**push 時機**（main.py，純 append）：

- `_rr_zoom`（首次放大）：在設 `ctx.zoom_region`／`ctx.zoom_base` 之前 `ctx.zoom_stack.append(None)`，並 `ctx.zoom_scale = cfg.reentry_remote_zoom_scale`。
- `_rr_magnify`（連鎖放大）：在設新 `ctx.zoom_region`／`ctx.zoom_base`／`ctx.zoom_scale` 之前 `ctx.zoom_stack.append({"region": ctx.zoom_region, "base": ctx.zoom_base, "scale": ctx.zoom_scale})`。

**pop 純函式** `reentry_remote.pop_zoom_layer(ctx) -> ("awaiting_cmd", None) | ("awaiting_fine", layer) | ("noop", None)`：

- `ctx.phase != "awaiting_fine"` → `("noop", None)`（呼叫端應先擋，防禦值；stack 不動）。
- `ctx.zoom_stack` 空 → `("awaiting_cmd", None)`（防禦：`awaiting_fine` 必有至少一層）。
- `pop` 出 `None` → `("awaiting_cmd", None)`（退過首層＝回等指令）。
- `pop` 出 `dict` → `("awaiting_fine", layer)`（layer 即該 dict）。

**解析**（`parse_reply`）：`_KEYWORDS` 加 `"退": "back", "back": "back"`。`RemoteReply` 的 `kind` dataclass 註解行補 `"back"`。

**執行** `Bot._rr_back(ctx)`（main.py；主迴圈執行，I/O 在此）：

1. `ctx.phase != "awaiting_fine"` → `_rr_notify("❓ 現在不是等細格，無層可退")`，return。
2. `if not self._focus_roblox(): _rr_notify("⚠ 無法聚焦 Roblox，稍後重試"); return`——**焦點失敗不 pop**，避免丟層。
3. `result = pop_zoom_layer(ctx)`。
4. `("awaiting_cmd", None)`：清 `ctx.phase = "awaiting_cmd"`、`ctx.zoom_region = ()`、`ctx.zoom_base = ""`、`ctx.zoom_scale = 0`；`_rr_notify("↩ 已退回等指令，重新 \`方位 粗格\`（如 \`3 C2\`）")`。（`zoom_dir` 不動——殘留無害，下次 `_rr_zoom` 覆寫；`cur_dir` 不動＝不必重新轉向。）
5. `("awaiting_fine", layer)`：把 `ctx.zoom_region`／`ctx.zoom_base`／`ctx.zoom_scale` 回復成 `layer` 的值；`f = capture.grab()`；`zoom = render_zoom(f, layer["region"], scale=layer["scale"], cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)`；`x, y, rw, rh = layer["region"]`；`cv2.imwrite(layer["base"] + "_src.png", f[y:y+rh, x:x+rw])`（漂移守門基準同步到現場幀）；`cv2.imwrite(layer["base"] + ".png", zoom)`；`_rr_notify(f"↩ 已退一層（×{layer['scale']}）。回細格（如 \`B3\`）點擊；可再 \`退\` 或 \`放大 <細格>\`", image_paths=[layer["base"] + ".png"])`。
6. `grab`／`imwrite` 極少失敗；失敗只記 log（不影響已完成的 pop——使用者重下指令即可，丟一層可接受）。

**dispatch**：`_rr_execute` 加 `elif k == "back": self._rr_back(ctx)`（與 `magnify`／`fine` 同層）。

`_PENDING_LABELS["back"] = "退一層"`（既有中文標籤表）。

### 2. 精細選擇時暫停回礦卡釘底

**`_repin_tick`**（main.py line 1637-1639）：回礦卡重貼條件加 `ctx.phase == "awaiting_cmd"`：

```python
if (frozen and self._rr_ctx is not None and not self._rr_busy
        and self._rr_ctx.phase == "awaiting_cmd"
        and self._rr_repin.due(now, quiet)):
    self._rr_repost_embed()
```

`mark_pending`（line 1631-1633）照舊——卡被擠仍記錄「需要重貼」，只是 `fine`／`confirm` 期間不執行。

**`RepinDebouncer.mark_pending_now()`**（notify.py，新方法）：

```python
def mark_pending_now(self):
    """立刻需要重貼（繞過安靜窗）：due() 下一輪恆成立。"""
    self.pending = True
    self.last_activity = 0.0
```

用途：特定事件要求「下輪立刻重貼」，不等 `quiet_s`。

**退出精細選擇時觸發**：`_rr_execute` 開頭記 `prev_phase = ctx.phase if ctx else None`；結尾（在既有 `_rr_edit_embed()` 之後）加：

```python
if (prev_phase in ("awaiting_fine", "awaiting_confirm")
        and self._rr_ctx is not None
        and self._rr_ctx.phase == "awaiting_cmd"):
    self._rr_repin.mark_pending_now()
```

目前唯一走這條路的是 `back` 退過首層；用 phase 轉換偵測而非寫死在 `_rr_back`，未來新增「退出精細選擇」路徑自動受惠。下輪 `_repin_tick` 看到 `due()` 成立（phase 已是 `awaiting_cmd`）→ `_rr_repost_embed()` 把回礦卡拉回頻道底。

### 3. 脫離 REENTRY 立刻補挖礦遙控器

**`_rr_finalize`**（main.py line 4060 一帶）：保留 `self._remote_repin.mark_pending()` 作保險，並在清完 episode 狀態後直接重貼挖礦遙控器：

```python
self._remote_repin.mark_pending()        # 保險：萬一底下 repost 失敗，下輪 _repin_tick 仍會重試
self._rr_open_first_ts = 0.0
if self._rr_embed_mid:
    ...delete 回礦卡...
self._rr_embed_mid = None
self._rr_reactions_seen = {}
self._rr_last_min = -1
ctx, self._rr_ctx = self._rr_ctx, None
self._pending_reentry = None
self._repost_remote_control()            # 直接刪舊挖礦遙控器、貼新的到頻道底（不等 quiet_s／新訊息）
if ctx is None:
    return
```

`_repost_remote_control` 內部 `_post_remote_control` → `_remote_repin.clear()`（line 1569）會清殘留 pending，與上面那道保險不衝突。

`_rr_finalize` 是 REENTRY 三個出口（`skip`／`success`／`abort_reset`）的共同收尾點，加在這裡一次覆蓋。效果：REENTRY 結束的當下，挖礦遙控器立刻可見，不再「等到有新訊息」。

## config

本次不新增 config——`discord_repin_quiet_s`、`reentry_remote_zoom_scale`、`reentry_remote_drift_diff` 全沿用既有。

## 測試（純函式 TDD）

1. `parse_reply`：`退`／`back` → `RemoteReply(kind="back")`；大小寫、全形空白容錯；不誤觸既有詞（`重骰`／`跳過`／`放大`）；`放大 B3`／`B3`／`3 C2` 回歸不變。
2. `pop_zoom_layer`：
   - 空 stack ＋ `phase="awaiting_fine"` → `("awaiting_cmd", None)`。
   - push `None` 後 pop → `("awaiting_cmd", None)`，stack 空。
   - push `dict{region,base,scale}` 後 pop → `("awaiting_fine", dict)`，dict 內容相等。
   - 連鎖多層 LIFO：push `None`→push `d1`→push `d2`，pop 依序得 `d2`→`d1`→`("awaiting_cmd", None)`。
   - `phase != "awaiting_fine"` → `("noop", None)` 且 stack 不變。
3. `RemoteReentryContext` 新欄位預設值（`zoom_stack == []`、`zoom_scale == 0`）；既有建構式用法（不帶新欄位）不破。
4. `RepinDebouncer.mark_pending_now`：呼叫後 `due(now, quiet=任意正數)` 立刻 `True`；之後 `note_activity(now)` 再 `due` 則回到看 `quiet_s`。
5. 既有 `tests/test_reentry_remote.py`、`tests/test_reentry.py` 回歸全綠。

I/O 面（`_rr_back` 的 grab／imwrite、`_rr_finalize` 的 repost、`_repin_tick` 的 phase 條件）沿用既有人工實機驗證慣例。

## 風險與對策

| 風險 | 對策 |
|---|---|
| 退層重新擷取幀時畫面已漂移 | `_src` 同步更新到現場幀，漂移守門基準正確；`_rr_click` 邏輯零改動 |
| `zoom_stack` 跨 reroll 殘留 | reroll 重建 ctx（`_rr_open_episode`），stack 是 ctx 欄位隨之清空 |
| `_rr_finalize` 直接 repost 與輪詢執行緒競態 | `RepinDebouncer` 既有說明：最壞多等一輪／多重貼一次，無正確性問題（notify.py line 291-292） |
| `mark_pending_now` 在 awaiting_cmd 退出連發刪貼 | 退出是單次事件（退層低頻）；常態 `awaiting_cmd` 的 repin 仍受 `quiet_s` 節流（`mark_pending_now` 只在退出瞬間用一次） |
| `_rr_back` pop 後 grab／imwrite 失敗丟層 | `_focus_roblox` 在 pop 前把關；grab／imwrite 罕見，失敗記 log，使用者重下可接受 |
| 使用者退層後忘了處於哪層 | 通知附 `×{scale}` 與「可再退／放大」提示；embed 的 phase 標籤由原地 PATCH 即時反映 |

## 明確不做（本版）

- 不加 emoji 反應鈕給退層（純文字 `退`／`back`）。
- 不做「一次退多層」（一次退一層，連按即可）。
- 不改既有 `_rr_zoom`／`_rr_magnify` 的渲染／漂移邏輯，只在它們裡面加 push。
- 不動 `_rr_click` 漂移守門。
- 不改 `discord_repin_quiet_s` 預設值。
- 不暫停原地 PATCH（`_rr_edit_embed`）——不挪位置、不推播，無害。
