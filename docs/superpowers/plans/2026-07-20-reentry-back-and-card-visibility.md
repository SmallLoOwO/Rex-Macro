# 回礦退層指令 + 精細選擇時卡可見性收斂 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 給回礦遙控器加「退一層」指令、精細選擇時暫停回礦卡釘底重貼、脫離 REENTRY 時立刻補回挖礦遙控器。

**Architecture:** 純函式（解析、退層 stack 邏輯、防抖繞過）走 TDD；main.py 的 I/O 編排沿用專案既有慣例（全測試綠護身＋實機人工驗證）。退層用 `ctx.zoom_stack` 記每層 `{region, base, scale}`，pop 純函式決定退到哪、主迴圈負責重渲染。卡可見性靠 `RepinDebouncer.mark_pending_now()`（繞過安靜窗）與 `_rr_finalize` 直接重貼。

**Tech Stack:** Python 3.11+、pytest、既有 `miningbot.reentry_remote` / `miningbot.notify` / `miningbot.main`。

設計依據：`docs/superpowers/specs/2026-07-20-reentry-back-and-card-visibility-design.md`。

## Global Constraints

- 純函式面（reentry_remote.py / notify.py）必須有單元測試；I/O 面（main.py）靠全測試綠＋實機驗證。
- 座標、門檻、間隔與模式只放在 `Config`；本次不新增 config。
- 每個任務結束前跑 `uv run pytest -q` 全綠 + `uv run ruff check . --no-cache` 無新錯，只 stage 該任務動到的檔案，中文 commit 訊息。
- 行號僅供定位參考，實作時用 `rg` 找錨點字串確認（檔案會因前幾個 task 變動）。
- 不主動 push、切 branch；目前 branch `feature/optimization-roadmap`。

---

### Task 1: 退層解析與純邏輯（reentry_remote.py）

**Files:**
- Modify: `miningbot/reentry_remote.py`（`RemoteReply` kind 註解、`_KEYWORDS`、`RemoteReentryContext` 新欄位、`_PENDING_LABELS`、新增 `pop_zoom_layer`）
- Test: `tests/test_reentry_remote.py`（新增 `TestZoomBack` class）

**Interfaces:**
- Produces: `parse_reply` 接受 `退`/`back` 回 `RemoteReply(kind="back")`；`pop_zoom_layer(ctx) -> ("awaiting_cmd"|"awaiting_fine"|"noop", layer|None)`；`RemoteReentryContext.zoom_stack: list`、`zoom_scale: int`。Task 3/4/5 消費這些。

- [ ] **Step 1: 寫失敗測試** — 在 `tests/test_reentry_remote.py` 末尾新增：

```python
class TestZoomBack:
    def test_parse_back_keyword(self):
        from miningbot.reentry_remote import parse_reply
        assert parse_reply("退").kind == "back"
        assert parse_reply("BACK").kind == "back"
        assert parse_reply("　退　").kind == "back"        # 全形空白容錯

    def test_back_not_triggered_by_noise(self):
        from miningbot.reentry_remote import parse_reply
        assert parse_reply("退出") is None                 # 不是單獨「退」
        assert parse_reply("重骰").kind == "reroll"        # 既有詞不誤觸
        assert parse_reply("跳過").kind == "skip"
        assert parse_reply("backup") is None               # 精確匹配，不誤觸

    def test_pop_empty_stack_to_cmd(self):
        from miningbot.reentry_remote import RemoteReentryContext, pop_zoom_layer
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="x")
        ctx.phase = "awaiting_fine"
        assert pop_zoom_layer(ctx) == ("awaiting_cmd", None)

    def test_pop_none_marker_to_cmd(self):
        from miningbot.reentry_remote import RemoteReentryContext, pop_zoom_layer
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="x")
        ctx.phase = "awaiting_fine"
        ctx.zoom_stack.append(None)
        assert pop_zoom_layer(ctx) == ("awaiting_cmd", None)
        assert ctx.zoom_stack == []

    def test_pop_dict_layer_to_fine(self):
        from miningbot.reentry_remote import RemoteReentryContext, pop_zoom_layer
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="x")
        ctx.phase = "awaiting_fine"
        layer = {"region": (10, 20, 30, 40), "base": "/tmp/x", "scale": 5}
        ctx.zoom_stack.append(layer)
        assert pop_zoom_layer(ctx) == ("awaiting_fine", layer)
        assert ctx.zoom_stack == []

    def test_pop_chain_is_lifo(self):
        from miningbot.reentry_remote import RemoteReentryContext, pop_zoom_layer
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="x")
        ctx.phase = "awaiting_fine"
        d1 = {"region": (1, 1, 1, 1), "base": "a", "scale": 3}
        d2 = {"region": (2, 2, 2, 2), "base": "b", "scale": 6}
        ctx.zoom_stack.extend([None, d1, d2])
        assert pop_zoom_layer(ctx) == ("awaiting_fine", d2)
        assert pop_zoom_layer(ctx) == ("awaiting_fine", d1)
        assert pop_zoom_layer(ctx) == ("awaiting_cmd", None)
        assert ctx.zoom_stack == []

    def test_pop_wrong_phase_is_noop(self):
        from miningbot.reentry_remote import RemoteReentryContext, pop_zoom_layer
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="x")
        ctx.phase = "awaiting_cmd"
        ctx.zoom_stack.append(None)
        assert pop_zoom_layer(ctx) == ("noop", None)
        assert ctx.zoom_stack == [None]                    # stack 不動

    def test_ctx_new_fields_default(self):
        from miningbot.reentry_remote import RemoteReentryContext
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="x")
        assert ctx.zoom_stack == []
        assert ctx.zoom_scale == 0
```

- [ ] **Step 2: 跑測試確認失敗** — `uv run pytest tests/test_reentry_remote.py::TestZoomBack -v`。預期：FAIL（`pop_zoom_layer` 不存在、`parse_reply("退")` 回 None、`zoom_stack` 屬性不存在）。

- [ ] **Step 3: 實作** — 改 `miningbot/reentry_remote.py`：

  (a) `RemoteReply` kind 註解（`rg "coarse.*fine.*magnify"` 找，現行 line 12）尾巴加 `"back"`：
  ```python
    kind: str        # "coarse"/"fine"/"magnify"/"sweep"/"reroll"/"skip"/"confirm"/"void"/
                     # "layer"/"zoom_out"/"zoom_in"/"pitch_reset"/"pitch"/"back"
  ```

  (b) `_KEYWORDS`（`rg '"存檔": "pitch_save"'` 找，現行 line 28-29）加兩行：
  ```python
      "存檔": "pitch_save", "save": "pitch_save",
      "退": "back", "back": "back",
  }
  ```

  (c) `RemoteReentryContext`（`rg "zoom_base: str"` 找，現行 line 232）在 `zoom_base` 後加兩欄：
  ```python
      zoom_base: str = ""          # 等細格時：漂移守門基準圖路徑（Task 5 _rr_zoom 寫、_rr_click 讀）
      zoom_stack: list = field(default_factory=list)  # 放大層歷史（2026-07-20）：None=空層(回 awaiting_cmd)、dict=上一層 {region,base,scale}
      zoom_scale: int = 0          # 當前層渲染倍率（首層=reentry_remote_zoom_scale；連鎖=magnify_scale 算出）
      shots: list = field(default_factory=list)    # [(dir_idx, snapshot_path)]
  ```

  (d) `_PENDING_LABELS`（`rg "'magnify': '再放大'"` 找，現行 line 392）加一行：
  ```python
      'magnify': '再放大',
      'back': '退一層',
      'coarse': '轉向並放大',
  ```

  (e) 新增 `pop_zoom_layer` 純函式（放在 `magnify_scale` 函式之後、`fine_cell_to_screen` 之前；`rg "def magnify_scale"` 定位）：
  ```python
  def pop_zoom_layer(ctx):
      """退一層純邏輯（2026-07-20）：主迴圈執行 I/O，此處只決定退到哪。

      回 ("awaiting_cmd", None)：stack 空 or pop 出 None（退過首層＝回等指令）；
      回 ("awaiting_fine", layer)：pop 出某層 dict（region/base/scale），主迴圈重渲染該層；
      回 ("noop", None)：phase 不是 awaiting_fine（呼叫端應先擋，防禦值；stack 不動）。
      """
      if ctx.phase != "awaiting_fine":
          return ("noop", None)
      if not ctx.zoom_stack:
          return ("awaiting_cmd", None)
      layer = ctx.zoom_stack.pop()
      if layer is None:
          return ("awaiting_cmd", None)
      return ("awaiting_fine", layer)
  ```

- [ ] **Step 4: 跑測試確認通過** — `uv run pytest tests/test_reentry_remote.py::TestZoomBack -v`。預期：全 PASS。

- [ ] **Step 5: 跑全測試 + ruff** — `uv run pytest -q` 與 `uv run ruff check . --no-cache`。預期：全綠、無新 lint。

- [ ] **Step 6: Commit** —
  ```bash
  git add miningbot/reentry_remote.py tests/test_reentry_remote.py
  git commit -m "feat(reentry): 退層指令解析＋zoom_stack 純邏輯（pop_zoom_layer）"
  ```

---

### Task 2: RepinDebouncer.mark_pending_now（notify.py）

**Files:**
- Modify: `miningbot/notify.py`（`RepinDebouncer` 加 `mark_pending_now`）
- Test: `tests/test_discord_responsiveness.py`（新增測試）

**Interfaces:**
- Produces: `RepinDebouncer.mark_pending_now()` —— 設 `pending=True; last_activity=0.0`，使 `due()` 下一輪恆成立（繞過 `quiet_s`）。Task 5 消費。

- [ ] **Step 1: 寫失敗測試** — 在 `tests/test_discord_responsiveness.py` 的 `test_repin_debouncer_waits_for_quiet_window`（`rg "def test_repin_debouncer_waits_for_quiet_window"`）之後新增：

```python
def test_repin_debouncer_mark_pending_now_bypasses_quiet_window():
    """mark_pending_now（2026-07-20）：繞過安靜窗，即使 last_activity 才剛刷近也立刻 due。"""
    d = notify.RepinDebouncer()
    d.note_activity(100.0)                  # 模擬剛有活動（連發中）
    d.mark_pending_now()
    assert d.due(100.0, 4.0) is True        # 不等 quiet_s
    assert d.due(999.0, 999.0) is True      # 任意 quiet 都 due（last_activity=0）
    d.note_activity(200.0)                  # 後續又有活動 → 回到看 quiet_s
    assert d.due(203.9, 4.0) is False
    assert d.due(204.0, 4.0) is True
```

- [ ] **Step 2: 跑測試確認失敗** — `uv run pytest tests/test_discord_responsiveness.py::test_repin_debouncer_mark_pending_now_bypasses_quiet_window -v`。預期：FAIL（`mark_pending_now` 不存在）。

- [ ] **Step 3: 實作** — `miningbot/notify.py` 的 `RepinDebouncer.mark_pending`（`rg "def mark_pending"`，現行 line 303-305）之後加：

```python
    def mark_pending_now(self):
        """立刻需要重貼（2026-07-20）：繞過安靜窗，due() 下一輪恆成立。

        用於「退出精細選擇」等單次事件——卡被擠到上面時不該再等 quiet_s；
        常態 repin 仍走 mark_pending + quiet_s 防連發刪貼。
        """
        self.pending = True
        self.last_activity = 0.0
```

- [ ] **Step 4: 跑測試確認通過** — `uv run pytest tests/test_discord_responsiveness.py::test_repin_debouncer_mark_pending_now_bypasses_quiet_window -v`。預期：PASS。

- [ ] **Step 5: 跑全測試 + ruff** — `uv run pytest -q` 與 `uv run ruff check . --no-cache`。

- [ ] **Step 6: Commit** —
  ```bash
  git add miningbot/notify.py tests/test_discord_responsiveness.py
  git commit -m "feat(notify): RepinDebouncer.mark_pending_now 繞過安靜窗立刻重貼"
  ```

---

### Task 3: _rr_zoom / _rr_magnify push 放大層（main.py，I/O）

**Files:**
- Modify: `miningbot/main.py`（`_rr_zoom` 與 `_rr_magnify` 各加 push + scale 記帳）

**Interfaces:**
- Consumes: Task 1 的 `ctx.zoom_stack`、`ctx.zoom_scale`。
- Produces: 每次放大前 stack 留下退層線索，供 Task 4 的 `_rr_back` pop。

- [ ] **Step 1: _rr_zoom push 空層標記** — `rg "ctx.phase = \"awaiting_fine\""` 在 `_rr_zoom`（現行 line 4659-4662）把：

```python
        ctx.phase = "awaiting_fine"
        ctx.zoom_dir = tgt_dir
        ctx.zoom_region = region
        ctx.zoom_base = base                      # _rr_click 讀回（不重組字串）
```

改為：

```python
        ctx.zoom_stack.append(None)               # 2026-07-20：首層之前＝awaiting_cmd（退層 pop None 回指令）
        ctx.phase = "awaiting_fine"
        ctx.zoom_dir = tgt_dir
        ctx.zoom_region = region
        ctx.zoom_base = base                      # _rr_click 讀回（不重組字串）
        ctx.zoom_scale = cfg.reentry_remote_zoom_scale
```

- [ ] **Step 2: _rr_magnify push 上一層 dict** — `rg "ctx.zoom_region = sub"` 在 `_rr_magnify`（現行 line 4704-4705）把：

```python
        ctx.zoom_region = sub
        ctx.zoom_base = base
```

改為：

```python
        ctx.zoom_stack.append({                   # 2026-07-20：連鎖放大前 push 上一層（退層用）
            "region": ctx.zoom_region, "base": ctx.zoom_base, "scale": ctx.zoom_scale})
        ctx.zoom_region = sub
        ctx.zoom_base = base
        ctx.zoom_scale = scale
```

- [ ] **Step 3: 跑全測試 + ruff** — `uv run pytest -q` 與 `uv run ruff check . --no-cache`。預期：全綠（純 append，不改既有行為）。

- [ ] **Step 4: Commit** —
  ```bash
  git add miningbot/main.py
  git commit -m "feat(reentry): _rr_zoom/_rr_magnify 進放大層前 push 退層線索到 zoom_stack"
  ```

---

### Task 4: _rr_back 退層執行 + dispatch（main.py，I/O）

**Files:**
- Modify: `miningbot/main.py`（`_rr_execute` 加 `back` 分支；新增 `_rr_back` 方法）

**Interfaces:**
- Consumes: Task 1 的 `pop_zoom_layer`、`reentry_remote.render_zoom`、`cfg.reentry_remote_fine_cols/rows`；Task 3 push 的 stack。

- [ ] **Step 1: _rr_execute 加 dispatch** — `rg "elif k == \"magnify\":"`（現行 line 4508）之後、`elif k == "coarse":`（line 4513）之前插入：

```python
        elif k == "back":
            self._rr_back(ctx)
```

- [ ] **Step 2: 新增 _rr_back 方法** — 放在 `_rr_magnify` 之後、`_rr_click` 之前（`rg "def _rr_click"` 定位邊界）。完整方法：

```python
    def _rr_back(self, ctx):
        """退一層（2026-07-20）：連鎖放大時 pop 上一層 zoom_region；退過首層回 awaiting_cmd。

        退層不轉向、不重掃、不動鏡頭距離——只回溯放大鏈。退到的那層用當下現場幀
        重渲染（畫面可能已漂移），漂移守門基準 _src 同步更新，_rr_click 邏輯零改動。
        focus 失敗不 pop（避免丟層）；grab/imwrite 罕見失敗則記 log（已 pop，重下即可）。
        """
        import cv2
        if ctx.phase != "awaiting_fine":
            self._rr_notify("❓ 現在不是等細格，無層可退")
            return
        if not self._focus_roblox():
            self._rr_notify("⚠ 無法聚焦 Roblox，稍後重試")
            return
        result = reentry_remote.pop_zoom_layer(ctx)
        if result[0] == "awaiting_cmd":
            ctx.phase = "awaiting_cmd"
            ctx.zoom_region = ()
            ctx.zoom_base = ""
            ctx.zoom_scale = 0
            self._rr_notify("↩ 已退回等指令，重新 `方位 粗格`（如 `3 C2`）")
            return
        layer = result[1]
        ctx.zoom_region = layer["region"]
        ctx.zoom_base = layer["base"]
        ctx.zoom_scale = layer["scale"]
        f = capture.grab()
        zoom = reentry_remote.render_zoom(
            f, layer["region"], scale=layer["scale"],
            cols=cfg.reentry_remote_fine_cols, rows=cfg.reentry_remote_fine_rows)
        x, y, rw, rh = layer["region"]
        try:
            os.makedirs(self._rr_snap_dir(), exist_ok=True)
            cv2.imwrite(layer["base"] + "_src.png", f[y:y + rh, x:x + rw])
            cv2.imwrite(layer["base"] + ".png", zoom)
        except OSError as e:
            self.logger.warning("[RR#%s] 退層寫檔失敗（%s）——已 pop，使用者重下即可",
                                ctx.episode_id, e)
        self._rr_notify(
            f"↩ 已退一層（×{layer['scale']}）。回細格（如 `B3`）點擊；"
            f"可再 `退` 或 `放大 <細格>`",
            image_paths=[layer["base"] + ".png"])
```

- [ ] **Step 3: 跑全測試 + ruff** — `uv run pytest -q` 與 `uv run ruff check . --no-cache`。預期：全綠（新方法不影響既有路徑）。

- [ ] **Step 4: Commit** —
  ```bash
  git add miningbot/main.py
  git commit -m "feat(reentry): _rr_back 退層指令執行（pop zoom_stack 重渲染上一層）"
  ```

---

### Task 5: 退出精細選擇觸發回礦卡立刻重貼（main.py，I/O）

**Files:**
- Modify: `miningbot/main.py`（`_rr_execute` 開頭記 `prev_phase`、結尾觸發 `mark_pending_now`）

**Interfaces:**
- Consumes: Task 2 的 `RepinDebouncer.mark_pending_now`、`self._rr_repin`。

- [ ] **Step 1: _rr_execute 開頭記 prev_phase** — `rg "def _rr_execute"`（現行 line 4477-4480）把：

```python
    def _rr_execute(self, reply):
        """主迴圈消費一則回礦指令（輸入操作全在此執行緒）。"""
        ctx = self._rr_ctx
        k = reply.kind
```

改為：

```python
    def _rr_execute(self, reply):
        """主迴圈消費一則回礦指令（輸入操作全在此執行緒）。"""
        ctx = self._rr_ctx
        k = reply.kind
        prev_phase = ctx.phase if ctx is not None else None
```

- [ ] **Step 2: 結尾觸發 mark_pending_now** — `rg "if k not in \(\"skip\", \"reroll\"\):"`（現行 line 4528-4529）把：

```python
        if k not in ("skip", "reroll"):
            self._rr_edit_embed()
```

改為：

```python
        if k not in ("skip", "reroll"):
            self._rr_edit_embed()
        # 2026-07-20：退出精細選擇（fine/confirm → awaiting_cmd）立刻要求回礦卡重貼到頻道底，
        # 不等 quiet_s——精細選擇期間卡被擠上去沒重貼，退回指令時要立刻可見。
        if (prev_phase in ("awaiting_fine", "awaiting_confirm")
                and ctx is not None and ctx.phase == "awaiting_cmd"):
            self._rr_repin.mark_pending_now()
```

- [ ] **Step 3: 跑全測試 + ruff** — `uv run pytest -q` 與 `uv run ruff check . --no-cache`。

- [ ] **Step 4: Commit** —
  ```bash
  git add miningbot/main.py
  git commit -m "feat(reentry): 退出精細選擇時立刻重貼回礦卡（mark_pending_now）"
  ```

---

### Task 6: 精細選擇時暫停回礦卡釘底（main.py + 既有測試更新）

**Files:**
- Modify: `miningbot/main.py`（`_repin_tick` 回礦卡分支加 phase 條件）
- Modify: `tests/test_discord_responsiveness.py`（更新 `test_repin_tick_reentry_rr_card_and_busy_gate`；新增 fine/confirm 不重貼測試）

**Interfaces:**
- Consumes: `ctx.phase`（`RemoteReentryContext`）。

- [ ] **Step 1: 寫新測試（失敗）** — 在 `tests/test_discord_responsiveness.py` 的 `test_repin_tick_reentry_rr_card_and_busy_gate`（`rg "def test_repin_tick_reentry_rr_card_and_busy_gate"`）之後新增。先確認檔頭有 `import types`，沒有就加：

```python
def test_repin_tick_skips_repost_during_fine_selection(monkeypatch):
    """2026-07-20：精細選擇（awaiting_fine/confirm）期間不釘底重貼回礦卡——避免推走放大圖。"""
    for phase in ("awaiting_fine", "awaiting_confirm"):
        bot = _bare_repin_bot(monkeypatch, state=State.REENTRY)
        bot._rr_embed_mid = "rr-message"
        bot._rr_ctx = types.SimpleNamespace(phase=phase)
        bot._rr_repin.mark_pending()          # 卡已被擠（旗標立著）
        bot._repin_tick([], 999.0)             # 安靜早已滿
        assert bot.reposted == [], f"{phase} 不該 repost"
```

- [ ] **Step 2: 更新既有測試** — `test_repin_tick_reentry_rr_card_and_busy_gate`（現行 line 446-459）把 `bot._rr_ctx = object()` 改成帶 `phase` 的物件，使其仍能走到 repost（現在 repost 需 `phase == "awaiting_cmd"`）：

```python
def test_repin_tick_reentry_rr_card_and_busy_gate(monkeypatch):
    """REENTRY：回礦卡走同一安靜窗；_rr_busy 中即使 due 也不搬；遙控器旗標不因新訊息立。"""
    bot = _bare_repin_bot(monkeypatch, state=State.REENTRY)
    bot._rr_embed_mid = "rr-message"
    bot._rr_ctx = types.SimpleNamespace(phase="awaiting_cmd")   # 2026-07-20：repost 只在 awaiting_cmd
    bot._repin_tick([{"id": "photo-1"}], 200.0)
    assert bot.reposted == []
    bot._rr_busy = True
    bot._repin_tick([], 210.0)                          # due 但發圖/指令執行中
    assert bot.reposted == []
    bot._rr_busy = False
    bot._repin_tick([], 211.0)
    assert bot.reposted == ["rr"]
    assert bot._remote_repin.pending is False           # REENTRY 中遙控器旗標由收尾立
```

- [ ] **Step 3: 跑測試確認失敗** — `uv run pytest tests/test_discord_responsiveness.py::test_repin_tick_skips_repost_during_fine_selection -v`。預期：FAIL（目前 fine/confirm 仍會 repost）。

- [ ] **Step 4: 實作** — `rg "frozen and self._rr_ctx is not None and not self._rr_busy"` 在 `_repin_tick`（現行 line 1637-1639）把：

```python
        if (frozen and self._rr_ctx is not None and not self._rr_busy
                and self._rr_repin.due(now, quiet)):
            self._rr_repost_embed()
```

改為：

```python
        if (frozen and self._rr_ctx is not None and not self._rr_busy
                and self._rr_ctx.phase == "awaiting_cmd"
                and self._rr_repin.due(now, quiet)):
            self._rr_repost_embed()
```

- [ ] **Step 5: 跑這兩個測試確認通過** — `uv run pytest tests/test_discord_responsiveness.py::test_repin_tick_skips_repost_during_fine_selection tests/test_discord_responsiveness.py::test_repin_tick_reentry_rr_card_and_busy_gate -v`。預期：全 PASS。

- [ ] **Step 6: 跑全測試 + ruff** — `uv run pytest -q` 與 `uv run ruff check . --no-cache`。

- [ ] **Step 7: Commit** —
  ```bash
  git add miningbot/main.py tests/test_discord_responsiveness.py
  git commit -m "feat(reentry): 精細選擇(awaiting_fine/confirm)時暫停回礦卡釘底重貼"
  ```

---

### Task 7: 脫離 REENTRY 立刻補挖礦遙控器（main.py + 既有測試更新）

**Files:**
- Modify: `miningbot/main.py`（`_rr_finalize` 在收尾時直接呼叫 `_repost_remote_control`）
- Modify: `tests/test_discord_responsiveness.py`（改 `test_rr_finalize_marks_remote_repin_pending` 為驗證直接 repost；新增保險路徑測試）

**Interfaces:**
- Consumes: `self._repost_remote_control`（既有）、`self._remote_repin`。

- [ ] **Step 1: 改既有測試** — `rg "def test_rr_finalize_marks_remote_repin_pending"`（現行 line 462-477）。原本斷言「finalize 立旗標」改成「finalize 直接重貼遙控器」；必須 stub `_repost_remote_control` 否則會真打 Discord API。整函式替換為：

```python
def test_rr_finalize_reposts_remote_control_immediately():
    """2026-07-20：回礦收尾立刻重貼挖礦遙控器到頻道底——不再只立旗標等 quiet_s／新訊息。"""
    bot = Bot.__new__(Bot)
    bot._rr_open_first_ts = 1.0
    bot._rr_embed_mid = None                  # 無殘留卡 → 不走 delete_message
    bot._rr_reactions_seen = {}
    bot._rr_last_min = 3
    bot._rr_ctx = None                        # ctx=None 防禦路徑也要補遙控器
    bot._pending_reentry = None
    bot._remote_repin = notify.RepinDebouncer()
    bot.log_discord = _LogRecorder()
    bot.reposted = False

    def _fake_repost():
        bot.reposted = True
        bot._remote_repin.clear()             # 模擬 _post_remote_control 成功後 clear

    bot._repost_remote_control = _fake_repost

    bot._rr_finalize("success")

    assert bot.reposted is True               # 立刻重貼，不等新訊息／quiet_s
    assert bot._remote_repin.pending is False  # clear 過（＝成功重貼）
```

- [ ] **Step 2: 加保險路徑測試** — 緊接上面新增。驗證「repost 失敗時保險旗標保留，下輪 `_repin_tick` 兜底」：

```python
def test_rr_finalize_keeps_pending_if_repost_fails():
    """2026-07-20：_repost_remote_control 失敗（沒 clear）時，保險 mark_pending 保留給下輪兜底。"""
    bot = Bot.__new__(Bot)
    bot._rr_open_first_ts = 1.0
    bot._rr_embed_mid = None
    bot._rr_reactions_seen = {}
    bot._rr_last_min = 3
    bot._rr_ctx = None
    bot._pending_reentry = None
    bot._remote_repin = notify.RepinDebouncer()
    bot.log_discord = _LogRecorder()
    bot._repost_remote_control = lambda: None   # stub：失敗（沒 clear、沒貼）

    bot._rr_finalize("success")

    assert bot._remote_repin.pending is True    # 保險保留，下輪 _repin_tick 兜底
```

- [ ] **Step 3: 跑測試確認失敗** — `uv run pytest tests/test_discord_responsiveness.py::test_rr_finalize_reposts_remote_control_immediately tests/test_discord_responsiveness.py::test_rr_finalize_keeps_pending_if_repost_fails -v`。預期：FAIL（`reposted` 仍 False／`_repost_remote_control` 被 stub 成 no-op 但 finalize 還沒呼叫它——目前兩個都會在 `_rr_finalize` 不呼叫 `_repost_remote_control` 下：前者 `reposted is False`、後者 `pending` 視 finalize 是否 mark_pending）。

- [ ] **Step 4: 實作** — `rg "ctx, self._rr_ctx = self._rr_ctx, None"` 在 `_rr_finalize`（現行 line 4072-4076）把：

```python
        ctx, self._rr_ctx = self._rr_ctx, None
        self._pending_reentry = None
        if ctx is None:
            return
        self._zoom_restore_if_touched(ctx)
```

改為：

```python
        ctx, self._rr_ctx = self._rr_ctx, None
        self._pending_reentry = None
        # 2026-07-20：脫離 REENTRY 立刻補挖礦遙控器到頻道底——不再只立旗標等 quiet_s
        # （完成通知／補瓶通知會讓 last_activity 持續刷近，due() 不成立，遙控器遲遲不回底）。
        # 上面的 mark_pending 留作保險：repost 失敗時下輪 _repin_tick 仍會重試。
        self._repost_remote_control()
        if ctx is None:
            return
        self._zoom_restore_if_touched(ctx)
```

- [ ] **Step 5: 跑這兩個測試確認通過** — `uv run pytest tests/test_discord_responsiveness.py::test_rr_finalize_reposts_remote_control_immediately tests/test_discord_responsiveness.py::test_rr_finalize_keeps_pending_if_repost_fails -v`。預期：全 PASS。

- [ ] **Step 6: 跑全測試 + ruff** — `uv run pytest -q` 與 `uv run ruff check . --no-cache`。確認 `test_remote_reposts_after_reentry_finalize_without_new_message`（保險＋安靜窗兜底整合）仍綠——它測的是 `_repin_tick` 遙控器分支，本 task 沒動到。

- [ ] **Step 7: Commit** —
  ```bash
  git add miningbot/main.py tests/test_discord_responsiveness.py
  git commit -m "fix(reentry): 脫離 REENTRY 時立刻重貼挖礦遙控器（不再等新訊息／quiet_s）"
  ```

---

## Self-Review 備忘

- **Spec 覆蓋**：需求 1（退層）→ Task 1+3+4；需求 2（暫停釘底＋退出重貼）→ Task 5+6；需求 3（脫離補遙控器）→ Task 7。全部覆蓋。
- **型別一致**：`pop_zoom_layer` 回傳 tuple 在 Task 1 定義、Task 4 消費；`mark_pending_now` 在 Task 2 定義、Task 5 消費；`zoom_stack`/`zoom_scale` 在 Task 1 加、Task 3 寫、Task 4 讀。命名全對齊。
- **既有測試**：Task 6 改 `test_repin_tick_reentry_rr_card_and_busy_gate`（ctx 加 phase）；Task 7 改 `test_rr_finalize_marks_remote_repin_pending`（改名＋stub repost）、不動 `test_remote_reposts_after_reentry_finalize_without_new_message`（仍測兜底）。Task 1/2 不動既有測試。

## 實機驗證（全部 task 完成後）

落盤前最後一道：實機跑一場回礦，確認：
1. `方位 粗格` 進等細格 → `放大 <細格>` 連鎖 → `退` 退一層重發圖 → 再 `退` 退過首層回等指令（embed phase 標籤原地 PATCH 成「等指令」、下輪卡重貼到頻道底）。
2. 等細格期間，頻道有 bot 自己發的放大圖，安靜滿 quiet_s 後**回礦卡不重貼**（不被推走）。
3. 回礦成功／跳過／abort_reset 三個出口，挖礦遙控器**立刻**回到頻道底（不用等到下則訊息）。
