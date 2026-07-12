# REENTRY 鏡頭遠近支援 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **本 repo 慣例**：程式實作委派 opencode（GLM 無視覺、勿讀圖、不 commit）；本計畫即為其自足規格來源，Claude 事後審 diff＋重跑測試＋紅燈驗證才 commit。

**Goal:** 遠端回礦新增 `遠 [n]`/`近 [n]` 指令（I/O 鍵步進 zoom）＋「夾限飽和→回拉 K 步」絕對歸位，鏡頭距離不外洩進 MINING。

**Architecture:** 純函式（解析/步數 clamp/歸位計畫/記帳欄位）進 `reentry_remote.py`（TDD）；I/O（送鍵/驗證/歸位執行）進 `main.Bot` 的 `_rr_*` 家族；門檻/步數全在 `config.py`。歸位掛在 `_rr_finalize`（三個出口的共同漏斗）。

**Tech Stack:** Python、pytest、pydirectinput（`input_control.key_press`）、OpenCV（既有幀差驗證）。

**規格：** `docs/superpowers/specs/2026-07-12-reentry-zoom-design.md`（已定案）。

## Global Constraints

- `python -m pytest -q` 必須全綠（既有 remote-reentry 測試不可改動語意）。
- `zoom_reset_pullback_steps=0`＝未校準＝`遠`/`近` 指令整組停用（回提示不動作）。
- 步數超上限 clamp 到 `reentry_zoom_max_steps`，不拒收。
- zoom 被吃驗證用獨立 `zoom_eaten_*` 門檻，**不可共用旋轉門檻**（俯仰事故先例：地表粒子特效讓門檻必須分家；歸位冪等、誤判重做無害，方向安全性與旋轉相反）。
- 只在 `awaiting_cmd` phase 接受 zoom 指令。
- 歸位＝絕對基準（記帳誤差不得漏進 MINING）；`重骰` 不清 `net_zoom`。
- opencode 實作者：**不要嘗試讀任何圖片**；**不要 commit**。

---

### Task 1: 純邏輯——指令解析＋步數 clamp

**Files:**
- Modify: `miningbot/reentry_remote.py`（`RemoteReply` 加欄位、`parse_reply` 加分支、新函式 `effective_zoom_steps`）
- Test: `tests/test_reentry_remote.py`

**Interfaces:**
- Produces: `RemoteReply.steps: int = 0`（0＝未指定）；`parse_reply` 新 kind `"zoom_out"`/`"zoom_in"`；`effective_zoom_steps(requested: int, default: int, max_steps: int) -> int`。

- [ ] **Step 1: Write the failing tests**（加在 `tests/test_reentry_remote.py` 末尾）

```python
from miningbot.reentry_remote import effective_zoom_steps


class TestZoomParse:
    def test_zoom_bare_and_steps(self):
        r = parse_reply("遠")
        assert (r.kind, r.steps) == ("zoom_out", 0)      # 0＝未指定，用 config 預設
        r = parse_reply("far 3")
        assert (r.kind, r.steps) == ("zoom_out", 3)
        r = parse_reply("近 2")
        assert (r.kind, r.steps) == ("zoom_in", 2)
        assert parse_reply("NEAR").kind == "zoom_in"

    def test_zoom_invalid(self):
        assert parse_reply("遠 abc") is None
        assert parse_reply("遠 0") is None
        assert parse_reply("遠 -3") is None               # 負數（isdigit False）
        assert parse_reply("遠 3 5") is None              # 多餘參數

    def test_effective_zoom_steps(self):
        assert effective_zoom_steps(0, 4, 12) == 4        # 未指定 → default
        assert effective_zoom_steps(3, 4, 12) == 3
        assert effective_zoom_steps(99, 4, 12) == 12      # 超上限 clamp、不拒收
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reentry_remote.py -q -k Zoom`
Expected: FAIL（ImportError: cannot import name 'effective_zoom_steps'）

- [ ] **Step 3: Implement**（`miningbot/reentry_remote.py`）

`RemoteReply` 加欄位（docstring 的 kind 列表同步補 `zoom_out`/`zoom_in`）：

```python
@dataclass(frozen=True)
class RemoteReply:
    kind: str        # "coarse"/"fine"/"walk"/"sweep"/"reroll"/"skip"/"confirm"/"void"/"layer"/"zoom_out"/"zoom_in"
    dir_idx: int = 0
    cell: str = ""
    layer: str = ""  # layer 指令的新層名；fine 的單次覆寫（空＝無）
    steps: int = 0   # zoom_out/zoom_in：使用者指定步數（0＝未指定，用 config 預設）
```

模組層加（`_KEYWORDS` 之後）：

```python
_ZOOM_WORDS = {"遠": "zoom_out", "far": "zoom_out", "近": "zoom_in", "near": "zoom_in"}
```

`parse_reply` 在 `head in ("層", "layer")` 分支**之前**插入：

```python
    if head in _ZOOM_WORDS:
        if len(parts) == 1:
            return RemoteReply(_ZOOM_WORDS[head])
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > 0:
            return RemoteReply(_ZOOM_WORDS[head], steps=int(parts[1]))
        return None
```

新函式（`fine_cell_to_screen` 之後）：

```python
def effective_zoom_steps(requested: int, default: int, max_steps: int) -> int:
    """`遠 [n]` 的實際步數：0＝未指定→default；超上限 clamp（寧可少拉不擋操作）。"""
    n = requested if requested > 0 else default
    return min(n, max_steps)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_reentry_remote.py -q`
Expected: 全 PASS（含既有測試——`遠`/`近`/`far`/`near` 不與既有詞彙衝突）

- [ ] **Step 5: Commit**

```bash
git add miningbot/reentry_remote.py tests/test_reentry_remote.py
git commit -m "feat(reentry-zoom): 遠/近指令解析＋步數 clamp 純函式"
```

---

### Task 2: 純邏輯——net_zoom 記帳＋絕對歸位計畫＋ledger zoom 欄

**Files:**
- Modify: `miningbot/reentry_remote.py`（`RemoteReentryContext` 加欄位、`log_command`/`record_click` 加 zoom 欄、新函式 `plan_zoom_restore`）
- Test: `tests/test_reentry_remote.py`

**Interfaces:**
- Consumes: Task 1 的 `parse_reply`。
- Produces: `RemoteReentryContext.net_zoom: int = 0`（+＝遠）；`plan_zoom_restore(net_zoom: int, saturate: int, pullback: int) -> list[tuple[str, int]]`（`[("i", saturate), ("o", pullback)]` 或空）；`ctx.log[i]["zoom"]`／`ctx.clicks[i]["zoom"]`。

- [ ] **Step 1: Write the failing tests**

```python
from miningbot.reentry_remote import plan_zoom_restore


class TestZoomRestore:
    def test_plan_zoom_restore(self):
        assert plan_zoom_restore(0, 30, 7) == []                       # 沒碰過不歸位
        assert plan_zoom_restore(5, 30, 7) == [("i", 30), ("o", 7)]
        assert plan_zoom_restore(-2, 30, 7) == [("i", 30), ("o", 7)]   # 拉近過也歸位
        assert plan_zoom_restore(5, 30, 0) == []                       # 未校準防禦（上游已擋）

    def test_zoom_recorded_in_log_and_click(self):
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="L")
        ctx.net_zoom = 3
        log_command(ctx, "遠 3", parse_reply("遠 3"), now=1.0)
        record_click(ctx, (1, 2), "L", (0, 0, 320, 270), now=2.0)
        assert ctx.log[0]["zoom"] == 3
        assert ctx.clicks[0]["zoom"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reentry_remote.py -q -k ZoomRestore`
Expected: FAIL（ImportError: cannot import name 'plan_zoom_restore'）

- [ ] **Step 3: Implement**

`RemoteReentryContext` 加欄位（`walked` 之後）：

```python
    net_zoom: int = 0            # 淨 zoom 步數（+＝遠）；重骰不清（鏡頭距離跨重生點持續）
```

`log_command`/`record_click` 各加 `"zoom": ctx.net_zoom`：

```python
def log_command(ctx, raw, reply, now):
    ctx.log.append({"t": now, "raw": raw, "kind": reply.kind if reply else None,
                    "pose_dir": ctx.cur_dir, "zoom": ctx.net_zoom})


def record_click(ctx, pos, layer, region, now):
    ctx.clicks.append({"t": now, "pos": tuple(pos), "layer": layer,
                       "dir": ctx.cur_dir, "region": tuple(region),
                       "zoom": ctx.net_zoom, "invalid": False})
```

新函式（`effective_zoom_steps` 之後）：

```python
def plan_zoom_restore(net_zoom: int, saturate: int, pullback: int):
    """絕對歸位按鍵計畫：I 飽和進第一人稱（冪等）→ O 回拉 K 步＝標準挖礦距離。

    沒碰過（net_zoom=0）或未校準（pullback<=0）回空。記帳誤差/步進不對稱
    都不影響歸位正確性——這是選絕對基準而非反向記帳的理由（spec 第 3 節）。
    """
    if net_zoom == 0 or pullback <= 0:
        return []
    return [("i", saturate), ("o", pullback)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_reentry_remote.py -q`
Expected: 全 PASS（既有 `test_log_and_click_accumulate`/`test_ledger_entry_fields` 只驗既有鍵存在，加鍵不破壞）

- [ ] **Step 5: Commit**

```bash
git add miningbot/reentry_remote.py tests/test_reentry_remote.py
git commit -m "feat(reentry-zoom): net_zoom 記帳＋plan_zoom_restore＋ledger zoom 欄"
```

---

### Task 3: config＋main.py 接線（指令執行、驗證式送鍵、絕對歸位）

**Files:**
- Modify: `miningbot/config.py`（`reentry_remote_ledger` 那行之後，約 line 248）
- Modify: `miningbot/main.py`（`_rr_execute` 加分支、新方法 `_rr_zoom_cam`/`_zoom_key_verified`/`_zoom_restore_if_touched`、`_rr_finalize` 掛歸位、輪詢提示字串補詞彙）

**Interfaces:**
- Consumes: Task 1 `effective_zoom_steps`、Task 2 `plan_zoom_restore`/`ctx.net_zoom`；既有 `ic.key_press`/`ic.settle`、`capture.grab`/`capture.crop`、`vision.frames_mean_diff`/`frames_changed_frac`、`harvester.rotation_looks_eaten`、`cfg.rotation_verify_region`/`rotation_changed_pixel_thresh`。
- Produces: 無下游任務依賴（端點）。

- [ ] **Step 1: config 新增**（`config.py`，緊接 `reentry_remote_ledger` 之後）

```python
    # REENTRY 鏡頭遠近（2026-07-12 spec：遠/近指令＋夾限飽和絕對歸位）
    reentry_zoom_step_default: int = 4          # `遠`/`近` 省略步數時的預設
    reentry_zoom_max_steps: int = 12            # 單指令步數上限（防手滑打 99；超過 clamp 不拒收）
    zoom_reset_saturate_presses: int = 30       # 歸位飽和段按 I 次數（須大於最大可能累積步數）
    zoom_reset_pullback_steps: int = 0          # 歸位回拉 K 步；0＝未校準＝遠/近指令整組停用。
                                                # 校準：鏡頭調到平常挖礦距離→狂按 I 進第一人稱→
                                                # 一步步按 O 數到回到熟悉距離＝K（docs/manual-sampling.md）
    zoom_eaten_mean_diff: float = 8.0           # zoom 送鍵被吃判定（初值抄 pitch_eaten_*；獨立門檻，
    zoom_eaten_changed_frac: float = 0.15       # 不可共用旋轉門檻——歸位冪等、誤判重做無害，方向安全性與旋轉相反）
```

- [ ] **Step 2: `_rr_execute` 加分支**（`main.py`，`elif k == "walk":` 之前插入）

```python
        elif k in ("zoom_out", "zoom_in"):
            self._rr_zoom_cam(ctx, reply)
```

- [ ] **Step 3: 新方法 `_rr_zoom_cam`**（放在 `_rr_walk` 之後）

```python
    def _rr_zoom_cam(self, ctx, reply):
        """`遠`/`近`：I/O 鍵逐步驗證式 zoom → 其餘方位快照過期、重拍當前面向回傳。

        只在 awaiting_cmd 收（等細格時鏡頭一動放大圖必然作廢）；未校準整組停用。
        """
        from . import notify
        token, ch = cfg.discord_bot_token, cfg.discord_channel_id
        if cfg.zoom_reset_pullback_steps <= 0:
            notify.send_message(token, ch,
                "⚠ zoom 未校準（zoom_reset_pullback_steps=0），`遠`/`近` 不可用")
            return
        if ctx.phase != "awaiting_cmd":
            notify.send_message(token, ch,
                "❓ 現在不能動鏡頭；先完成細格點擊/確認，或重下 `方位 粗格`")
            return
        if not self._focus_roblox():
            notify.send_message(token, ch, "⚠ 無法聚焦 Roblox，稍後重試")
            return
        out = reply.kind == "zoom_out"
        key, sign = ("o", 1) if out else ("i", -1)
        steps = reentry_remote.effective_zoom_steps(
            reply.steps, cfg.reentry_zoom_step_default, cfg.reentry_zoom_max_steps)
        done = 0
        for _ in range(steps):
            if self._zoom_key_verified(key):
                ctx.net_zoom += sign
                done += 1
        f = capture.grab()
        grid_img = f.copy()
        remote_aim.draw_grid(grid_img, 6, 4)
        gpath = self._rr_sync_write(
            grid_img, f"reentry_ep{ctx.episode_id}_zoomcam_z{ctx.net_zoom:+d}")
        ctx.zoom_region = ()
        ctx.zoom_base = ""
        notify.send_images_message(token, ch,
            f"🔭 鏡頭{'拉遠' if out else '拉近'} {done}/{steps} 步（淨 {ctx.net_zoom:+d}；"
            f"其餘方位圖已過期）。回 `{ctx.cur_dir % 8} 粗格` 指位、`掃` 重掃、`遠`/`近` 微調",
            [gpath])
```

- [ ] **Step 4: 新方法 `_zoom_key_verified`**（放在 `_pitch_drag_verified` 之後）

```python
    def _zoom_key_verified(self, key: str) -> bool:
        """I/O 一步＋前後幀驗證被吃（獨立 zoom_eaten_* 門檻）；被吃重聚焦重送一次。

        誤判被吃而重送＝實際多 zoom 一步、net_zoom 記帳偏一步——只影響 ledger
        標注與回傳圖，歸位走絕對基準不受害（與旋轉「寧漏判勿誤重送」取捨相反）。
        """
        for attempt in (1, 2):
            before = capture.crop(capture.grab(), cfg.rotation_verify_region)
            ic.key_press(key)
            ic.settle()
            after = capture.crop(capture.grab(), cfg.rotation_verify_region)
            eaten = harvester.rotation_looks_eaten(
                vision.frames_mean_diff(before, after),
                vision.frames_changed_frac(before, after,
                                           cfg.rotation_changed_pixel_thresh),
                cfg.zoom_eaten_mean_diff, cfg.zoom_eaten_changed_frac)
            if not eaten:
                return True
            self.logger.info("zoom 鍵 %s 疑似被吃（attempt %d/2），重聚焦重送", key, attempt)
            self._focus_roblox()
        return False
```

- [ ] **Step 5: 新方法 `_zoom_restore_if_touched` ＋掛進 `_rr_finalize`**

新方法（放在 `_zoom_key_verified` 之後）：

```python
    def _zoom_restore_if_touched(self, ctx):
        """碰過 zoom 才歸位：I 飽和進第一人稱（冪等、量多無妨）→ O 回拉 K 步。

        掛在 _rr_finalize＝三個出口（成功回 MINING/跳過交人工/重置作廢）的共同漏斗；
        回拉段逐步驗證被吃、被吃重送無害（歸位冪等，同俯仰歸位 attempt-2 語意）。
        """
        plan = reentry_remote.plan_zoom_restore(
            ctx.net_zoom, cfg.zoom_reset_saturate_presses, cfg.zoom_reset_pullback_steps)
        if not plan:
            return
        self._focus_roblox()
        for key, count in plan:
            for _ in range(count):
                if key == "i":
                    ic.key_press(key)                    # 飽和段不驗證（冪等）
                else:
                    self._zoom_key_verified(key)         # 回拉段逐步驗證
            ic.settle(0.4)
        ctx.net_zoom = 0
        self.logger.info("[RR#%s] zoom 歸位完成（I 飽和→O 回拉 %d 步）",
                         ctx.episode_id, cfg.zoom_reset_pullback_steps)
```

`_rr_finalize` 在 `if ctx is None: return` 之後、`world = ...` 之前插一行：

```python
        self._zoom_restore_if_touched(ctx)
```

- [ ] **Step 6: 快照檔名帶 zoom 標記**（spec 第 4 節：`_z+N`，`net_zoom=0` 不加＝舊檔名不變）

`_rr_sweep_and_send` 的兩個 label（原始幀＋網格圖）與 `_rr_zoom` 的 `base`、`_rr_click` 的
`_marker`/`_full`/`_landing` 三組檔名，各在方法開頭算一次後綴再串進 f-string：

```python
        zs = f"_z{ctx.net_zoom:+d}" if ctx.net_zoom else ""
```

例（`_rr_sweep_and_send` 內）：

```python
            path = self._snapshot(f, f"reentry_ep{ctx.episode_id}_dir{i}{zs}")
            ...
            gpath = self._rr_sync_write(grid_img, f"reentry_ep{ctx.episode_id}_dir{i}_grid{zs}")
```

例（`_rr_zoom` 內）：

```python
        base = os.path.join(self._rr_snap_dir(),
                            f"ep{ctx.episode_id}_zoom_{tgt_dir}{cell}{zs}")
```

例（`_rr_click` 內，三個檔名同法）：

```python
        mpath = os.path.join(self._rr_snap_dir(),
                             f"ep{ctx.episode_id}_click{len(ctx.clicks)}_marker{zs}.png")
```

（`_rr_walk` 的 `walk_{cell}` label 同樣補 `{zs}`，走位不改 zoom、後綴沿用當下值。）

- [ ] **Step 7: 輪詢提示補詞彙**（`main.py` 約 line 1566 的「看不懂」提示，加 `遠`/`近`）

```python
            notify.send_message(token, ch,
                "❓ 看不懂。可用：`3 C2`（方位+粗格）、`B3`／`B3 <層名>`（細格）、"
                "`走 C2`、`遠 [n]`/`近 [n]`（鏡頭）、`掃`、`重骰`、`層 <層名>`、`好`、`作廢`、`跳過`")
```

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest -q`
Expected: 全 PASS（main.py 無單元測試；純邏輯已由 Task 1/2 鎖住）

- [ ] **Step 9: Commit**

```bash
git add miningbot/config.py miningbot/main.py
git commit -m "feat(reentry-zoom): Bot 接線——遠/近執行、驗證式 I/O 送鍵、_rr_finalize 絕對歸位"
```

---

### Task 4: 文件——K 校準流程

**Files:**
- Modify: `docs/manual-sampling.md`（末尾加一節）

**Interfaces:** 無程式依賴。

- [ ] **Step 1: 加校準章節**（`docs/manual-sampling.md` 末尾）

```markdown
## 回礦 zoom 歸位校準（zoom_reset_pullback_steps）

遠端回礦的 `遠`/`近` 指令在 `zoom_reset_pullback_steps=0` 時整組停用——先照下面量出 K：

1. 進遊戲，把鏡頭手動調到**平常挖礦的距離**（記住這個畫面感覺；可先按 R 開取樣視窗截一張留參考）。
2. 狂按 I 直到進第一人稱（夾限飽和，多按無妨）。
3. 一步一步按 O，數步數，直到畫面回到步驟 1 的距離——這個步數＝K。
4. 填進 `config.py` 的 `zoom_reset_pullback_steps`。之後 bot 歸位＝「按 I 飽和 → 按 O K 步」，
   與俯仰歸位同手法（夾限＝絕對基準，中途被吃/記帳錯都不影響落點）。
5. 驗證：實機讓 bot 跑一次 `遠 5` → `跳過`，確認歸位後畫面與步驟 1 參考圖一致。

`zoom_eaten_*` 門檻初值抄俯仰（mean 8.0 / frac 0.15）；若實機出現「明明有 zoom 卻判被吃而重送」
或反之，比照俯仰事故兩側夾實測值再調（docs/incidents.md 俯仰門檻分家一節）。
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-sampling.md
git commit -m "docs(manual-sampling): 回礦 zoom 歸位 K 校準流程"
```

---

## 實機驗證（Claude 親做，不在 opencode 範圍）

1. 校準 K（Task 4 流程）並填 config。
2. 真實重置一輪：`遠`（預設步數）→ 確認回傳單張粗網格、其餘方位圖標示過期；`遠 99` → clamp 到 12；`近 3` → 收回。
3. 等細格時下 `遠` → 收到時機提示、鏡頭沒動。
4. `跳過` 收尾 → 觀察 I 飽和→O 回拉，畫面回標準挖礦距離；`logs/reentry_remote/ledger.jsonl` 該 episode 的 log/clicks 帶 zoom 欄。
5. 未校準（K=0）時下 `遠` → 收到「未校準」提示。
