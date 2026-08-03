# Discord 重開指令 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 Discord `重開`/`restart` 指令，只在暫停狀態下生效，終止 bot 並自動重啟以套用程式碼更新。

**Architecture:** Discord 輪詢執行緒收到指令後設 `_pending_restart` 旗標（比照既有 `_pending_*` 模式）；主迴圈消費旗標 → spawn detached relauncher（`ping` 延遲 + `start "" pythonw -m miningbot`）→ `_quit()` 走既有正常關機流程。relauncher 在舊行程結束後啟動新 bot，marker 檔讓新 bot 回報「重開完成」。

**Tech Stack:** Python 3.11+ / `subprocess`（DETACHED_PROCESS）/ pytest / 既有 `make_fake_bot` harness

## Global Constraints

- 回覆與 commit 訊息用中文；識別字、log key 保持原文。
- 純決策先測；不依賴 Roblox／Discord／真實行程。
- 每個 task 結束前跑 `uv run pytest -q` 全綠，只 stage 該 task 的檔案。
- `subprocess` 尚未在 main.py import——Task 3 加入。
- `sys`／`os` 已在 main.py import（行 1-2）。

---

### Task 1: 指令解析（`重開`／`restart` 加入白名單）

**Files:**
- Modify: `miningbot/discord_commands.py:5-10`（`COMMAND_NAMES`）
- Test: `tests/test_discord_commands.py`

**Interfaces:**
- Produces: `parse_command("重開")` → `DiscordCommand(name="重開")`；`parse_command("restart")` → `DiscordCommand(name="restart")`

- [ ] **Step 1: Write the failing tests**

加到 `tests/test_discord_commands.py` 末尾：

```python
def test_parse_command_accepts_restart():
    assert parse_command("重開").name == "重開"
    assert parse_command("restart").name == "restart"
    assert parse_command("RESTART").name == "restart"
    assert parse_command("!重開").name == "重開"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_discord_commands.py::test_parse_command_accepts_restart -v`
Expected: FAIL（`重開`／`restart` 不在 `COMMAND_NAMES`，`parse_command` 回 `None` → AttributeError on `.name`）

- [ ] **Step 3: Add to COMMAND_NAMES**

`miningbot/discord_commands.py:5-10`，在 `COMMAND_NAMES` frozenset 加 `"重開"` 和 `"restart"`：

```python
COMMAND_NAMES = frozenset({
    "list", "keep", "unkeep", "clear", "pause", "resume", "status", "help", "shot",
    "ability", "回礦", "reenter", "校準", "calib", "轉", "rotate",
    "掃描", "scan", "削洞", "caveskim",
    "階級", "tier", "清空", "清背包", "clearpanel",
    "重開", "restart",
})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_discord_commands.py -v`
Expected: PASS（全部含新的）

- [ ] **Step 5: Commit**

```bash
git add miningbot/discord_commands.py tests/test_discord_commands.py
git commit -m "feat(discord): 新增 重開/restart 指令解析"
```

---

### Task 2: 暫停閘 handler + `_pending_restart` 旗標

**Files:**
- Modify: `miningbot/main.py:423`（`__init__`，`_pending_clear_panel` 之後加旗標）
- Modify: `miningbot/main.py:2563`（`_handle_discord_command`，`清空` 分支之後加 `重開` 分支）
- Modify: `miningbot/config.py:746`（加 `restart_delay_s`——handler 訊息要引用）
- Test: `tests/test_restart.py`（新檔）

**Interfaces:**
- Consumes: Task 1 的 `parse_command` 已認得 `重開`／`restart`
- Produces: `self._pending_restart: bool`（預設 `False`；handler 在 `paused=True` 時設 `True`）；`cfg.restart_delay_s: float = 5.0`；handler 回覆 Discord 訊息

- [ ] **Step 1: Write the failing tests**

建立 `tests/test_restart.py`：

```python
"""Discord 重開指令的暫停閘 + relauncher 測試。"""
import types

from miningbot.discord_commands import DiscordCommand
from miningbot.states import State
from tests.fake_bot import make_fake_bot


def _make_bot(**kwargs):
    defaults = dict(
        bind=["_handle_discord_command"],
        paused=False,
        state=State.MINING,
        _pending_restart=False,
        _calib_session=None,
    )
    defaults.update(kwargs)
    return make_fake_bot(**defaults)


def test_restart_sets_flag_when_paused(monkeypatch):
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = _make_bot(paused=True)
    bot._handle_discord_command(DiscordCommand(name="重開", args=()))
    assert bot._pending_restart is True
    assert any("重開" in m or "重啟" in m for m in sent)


def test_restart_alias_english(monkeypatch):
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = _make_bot(paused=True)
    bot._handle_discord_command(DiscordCommand(name="restart", args=()))
    assert bot._pending_restart is True


def test_restart_rejected_when_not_paused(monkeypatch):
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = _make_bot(paused=False)
    bot._handle_discord_command(DiscordCommand(name="重開", args=()))
    assert bot._pending_restart is False
    assert any("暫停" in m for m in sent)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_restart.py -v`
Expected: FAIL（`_handle_discord_command` 沒有 `重開` 分支 → 命令被忽略，`_pending_restart` 沒被設）

- [ ] **Step 3: Add `restart_delay_s` to config.py**

`miningbot/config.py`，行 745（`discord_status_edit_min_interval_s` 段落）之後加：

```python
    restart_delay_s: float = 5.0               # Discord `重開`：relauncher 等待秒數（確保舊行程完全結束再啟動新的；>snapshot_shutdown_drain_s）
```

- [ ] **Step 4: Add `_pending_restart` flag to `__init__`**

`miningbot/main.py`，行 423（`self._pending_clear_panel = False`）之後加：

```python
        # Discord `重開` 指令（2026-08-03）：只在暫停時生效；輪詢執行緒設旗標，
        # 主迴圈消費（spawn relauncher + _quit）。布林於 GIL 下原子（同 _pending_clear_panel）。
        self._pending_restart = False
```

- [ ] **Step 5: Add handler branch**

`miningbot/main.py`，`_handle_discord_command` 的 `清空` 分支（行 2563 `self.log_discord.info("CMD 清空 ...")`）之後、`RADAR_COMMAND_KIND` 分支（行 2565）之前，加：

```python
        elif cmd in ("重開", "restart"):
            # 遠端重開（2026-08-03，使用者需求）：終止 bot 並自動重啟套用更新。
            # 安全閘＝只在暫停時生效（暫停本身就是確認，不加二次確認）。
            # 輪詢執行緒只設旗標，主迴圈消費（spawn relauncher 需在主執行緒 +
            # _quit 後 finally 清理區塊要完整跑過）。
            if not self.paused:
                notify.send_message(token, ch,
                    f"❌ 重開未接受：目前非暫停（{self.state.value}）。\n"
                    f"請先 `pause` 暫停再打 `重開`（重開會中斷目前工作）")
                self.log_discord.info("CMD 重開 -> rejected (not paused), state=%s",
                                      self.state.value)
            else:
                self._pending_restart = True
                notify.send_message(token, ch,
                    f"🔄 重開中——將在 {cfg.restart_delay_s:.0f} 秒後自動重啟"
                    f"（套用更新）。bot 先正常關機，再由 relauncher 啟動新行程。")
                self.log_discord.info("CMD 重開 -> paused=True, _pending_restart set")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_restart.py -v`
Expected: PASS（三個測試全綠）

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -q`
Expected: 全綠（新測試不影響既有）

- [ ] **Step 8: Commit**

```bash
git add miningbot/main.py miningbot/config.py tests/test_restart.py
git commit -m "feat(restart): 重開指令暫停閘 + _pending_restart 旗標 + restart_delay_s"
```

---

### Task 3: Relauncher + 主迴圈消費 + config

**Files:**
- Modify: `miningbot/main.py:8`（import `subprocess`）
- Modify: `miningbot/main.py:3042`（`run()` 主迴圈頂端加 `_consume_pending_restart` 檢查）
- Modify: `miningbot/main.py`（新增 `_schedule_restart` 和 `_consume_pending_restart` 方法）
- Test: `tests/test_restart.py`（加測試）

**Interfaces:**
- Consumes: Task 2 的 `self._pending_restart` 旗標 + `cfg.restart_delay_s`
- Produces: `_schedule_restart() -> bool`（spawn 成功回 True）；`_consume_pending_restart() -> bool`（旗標設了且 spawn 成功回 True＝該關機）

- [ ] **Step 1: Write the failing tests**

加到 `tests/test_restart.py`：

```python
def test_consume_pending_restart_spawns_and_returns_true(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: calls.append(k) or types.SimpleNamespace())
    monkeypatch.setattr("miningbot.notify.send_message", lambda *a, **k: None)
    bot = make_fake_bot(
        bind=["_consume_pending_restart", "_schedule_restart"],
        _pending_restart=True,
    )
    result = bot._consume_pending_restart()
    assert result is True
    assert bot._pending_restart is False
    assert len(calls) == 1
    # DETACHED_PROCESS (0x8) 必須在 creationflags 裡——relauncher 才能在父行程結束後存活
    assert calls[0].get("creationflags", 0) & 0x00000008


def test_consume_pending_restart_noop_when_flag_clear(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: calls.append(k))
    bot = make_fake_bot(
        bind=["_consume_pending_restart", "_schedule_restart"],
        _pending_restart=False,
    )
    result = bot._consume_pending_restart()
    assert result is False
    assert calls == []   # 旗標沒設 → 不 spawn


def test_consume_pending_restart_spawn_fail_keeps_running(monkeypatch):
    def boom(*a, **k):
        raise OSError("spawn denied")
    monkeypatch.setattr("subprocess.Popen", boom)
    monkeypatch.setattr("miningbot.notify.send_message", lambda *a, **k: None)
    bot = make_fake_bot(
        bind=["_consume_pending_restart", "_schedule_restart"],
        _pending_restart=True,
    )
    result = bot._consume_pending_restart()
    assert result is False              # spawn 失敗 → 不關機
    assert bot._pending_restart is False  # 旗標已清（不會重試）
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_restart.py::test_consume_pending_restart_spawns_and_returns_true -v`
Expected: FAIL（`_consume_pending_restart` 和 `_schedule_restart` 方法不存在 → AttributeError）

- [ ] **Step 3: Add `import subprocess` to main.py**

`miningbot/main.py` 行 1-8 的 import 區塊，在 `import json`（行 8）之後加：

```python
import subprocess
```

- [ ] **Step 4: Add `_schedule_restart` method**

`miningbot/main.py`，在 `_quit` 方法（行 9626-9628）之前加新方法：

```python
    def _schedule_restart(self) -> bool:
        """Spawn detached relauncher；成功回 True（主迴圈接著 _quit），失敗回 False。

        relauncher 是獨立 cmd：ping 做延遲（timeout 在無 console 的 detached 環境
        不可靠）→ start "" 啟動新 pythonw -m miningbot。DETACHED_PROCESS 讓它在
        父行程結束後存活。sys.executable 精確重現啟動當下的直譯器（Store Python
        的 pythonw.exe 或 .venv 的 python）。
        """
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        delay = cfg.restart_delay_s
        relaunch = (
            f'ping -n {int(delay) + 1} 127.0.0.1 >nul '
            f'& start "" "{sys.executable}" -m miningbot'
        )
        try:
            subprocess.Popen(
                relaunch, cwd=repo, shell=True,
                creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.logger.info("restart scheduled: relauncher spawned (delay=%ds, exe=%s)",
                             delay, sys.executable)
            return True
        except Exception as e:
            self.logger.error("restart relauncher spawn failed: %s", e)
            from . import notify
            notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
                f"❌ 重開失敗：無法啟動 relauncher（{e}），bot 繼續運行。請手動重啟。")
            return False

    def _consume_pending_restart(self) -> bool:
        """主迴圈每輪呼叫：_pending_restart 設了就 spawn relauncher 並回 True（該關機）。

        spawn 失敗回 False（bot 不關機），旗標已清（不重試）。比照 _consume_calib_start
        的消費模式。
        """
        if not self._pending_restart:
            return False
        self._pending_restart = False
        return self._schedule_restart()
```

- [ ] **Step 5: Add main loop check**

`miningbot/main.py` 行 3042（`while self._running:` 之後、`if self._pending_calib_start is not None:` 之前）加：

```python
                if self._consume_pending_restart():
                    self._quit()
                    continue
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_restart.py -v`
Expected: PASS（六個測試全綠）

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -q`
Expected: 全綠

- [ ] **Step 8: Commit**

```bash
git add miningbot/main.py tests/test_restart.py
git commit -m "feat(restart): relauncher + 主迴圈消費 _consume_pending_restart"
```

---

### Task 4: 重開完成 marker

**Files:**
- Modify: `miningbot/main.py`（`_schedule_restart` 加 marker 寫入；`run()` 開頭加 marker 檢查）
- Test: `tests/test_restart.py`（加測試）

**Interfaces:**
- Consumes: Task 3 的 `_schedule_restart()`（在成功 spawn 後寫 marker）
- Produces: `run()` 開頭的 `_check_restart_marker()` 呼叫——marker 存在＝剛被重開

- [ ] **Step 1: Write the failing tests**

加到 `tests/test_restart.py`：

```python
def test_restart_marker_written_on_success(monkeypatch, tmp_path):
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: types.SimpleNamespace())
    monkeypatch.setattr("miningbot.config.DEFAULT.log_dir", str(tmp_path))
    monkeypatch.setattr("miningbot.notify.send_message", lambda *a, **k: None)
    bot = make_fake_bot(bind=["_schedule_restart"])
    bot._schedule_restart()
    assert (tmp_path / "restart_marker").exists()


def test_check_restart_marker_notifies_and_deletes(monkeypatch, tmp_path):
    marker = tmp_path / "restart_marker"
    marker.write_text("2026-08-03 12:00:00", encoding="utf-8")
    monkeypatch.setattr("miningbot.config.DEFAULT.log_dir", str(tmp_path))
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = make_fake_bot(bind=["_check_restart_marker"])
    bot._check_restart_marker()
    assert not marker.exists()
    assert any("重開完成" in m for m in sent)


def test_check_restart_marker_noop_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr("miningbot.config.DEFAULT.log_dir", str(tmp_path))
    sent = []
    monkeypatch.setattr("miningbot.notify.send_message",
                        lambda *a, **k: sent.append(a[2]))
    bot = make_fake_bot(bind=["_check_restart_marker"])
    bot._check_restart_marker()
    assert sent == []   # 沒 marker → 不發訊息
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_restart.py::test_check_restart_marker_notifies_and_deletes -v`
Expected: FAIL（`_check_restart_marker` 方法不存在 → AttributeError）

- [ ] **Step 3: Add marker write to `_schedule_restart`**

`miningbot/main.py`，`_schedule_restart` 方法裡，`return True` 之前（Popen 成功的 `self.logger.info(...)` 之後）加：

```python
            # 寫 marker 讓新行程啟動時通知「重開完成」（best-effort，寫失敗不擋重開）
            marker = os.path.join(cfg.log_dir, "restart_marker")
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            except OSError:
                self.logger.warning("restart marker write failed (non-blocking)")
```

- [ ] **Step 4: Add `_check_restart_marker` method**

`miningbot/main.py`，在 `_schedule_restart` 方法之前加：

```python
    def _check_restart_marker(self):
        """啟動時檢查 restart marker——存在=剛被重開，通知 Discord 後刪除。"""
        marker = os.path.join(cfg.log_dir, "restart_marker")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except OSError:
            pass
        from . import notify
        notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
            "✅ 重開完成，已套用更新")
        self.logger.info("restart marker found -> notified Discord, deleted marker")
```

- [ ] **Step 5: Call marker check at `run()` top**

`miningbot/main.py`，`run()` 方法裡，行 2812（`self._running = True`）之前加：

```python
        self._check_restart_marker()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_restart.py -v`
Expected: PASS（九個測試全綠）

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -q`
Expected: 全綠

- [ ] **Step 8: Commit**

```bash
git add miningbot/main.py tests/test_restart.py
git commit -m "feat(restart): 重開完成 marker 通知（新 bot 啟動時回報）"
```

---

### Task 5: Help text + 文檔同步

**Files:**
- Modify: `miningbot/main.py:2643-2645`（help 指令的「操控」段加 `重開`）
- Modify: `docs/web-ui-guide.md`（分工表加列）
- Modify: `AGENTS.md`（WHERE TO LOOK「Discord controls」行）

**Interfaces:**
- Consumes: Task 1-4 的完整功能

- [ ] **Step 1: Add to help text**

`miningbot/main.py`，help 指令（行 2643-2645）的「操控」段，在 `resume` 那行（行 2645）之後加：

```python
                "`重開 (restart)` — 重開 bot 套用更新（⚠ 只在暫停時生效；先 `pause` 再打）\n"
```

- [ ] **Step 2: Add to web-ui-guide.md**

`docs/web-ui-guide.md`，分工表（行 21-26 區域）加一列。在 `手動轉 45°` 那列（行 26）之後加：

```markdown
| `重開`（restart，套用程式碼更新；⚠ 只在暫停時生效） | ✅ 唯一 | ❌ 不放網頁——重启會斷 WebSocket 連線，必須由 bot 自己 spawn relauncher |
```

- [ ] **Step 3: Add to AGENTS.md WHERE TO LOOK**

`AGENTS.md`，WHERE TO LOOK 表的「Discord controls」行（搜尋 `Discord controls`），在現有描述末尾補充 `重開/restart` 的存在。

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -q`
Expected: 全綠（純文檔改動不影響測試，但確認沒有意外）

- [ ] **Step 5: Run ruff**

Run: `uv run ruff check . --no-cache`
Expected: 無新增警告

- [ ] **Step 6: Commit**

```bash
git add miningbot/main.py docs/web-ui-guide.md AGENTS.md
git commit -m "docs: 重開指令同步 help text、web-ui-guide、AGENTS.md"
```
