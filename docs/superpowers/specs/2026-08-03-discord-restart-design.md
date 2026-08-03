# Discord 重開指令（Restart）— Design Spec

> 2026-08-03．使用者需求：程式碼變更後，可以從 Discord 直接終止 bot 並自動
> 重啟來套用更新。只透過 Discord 指令觸發，且只能在暫停狀態下使用。
> 暫停本身就是一種確認——不再加第二層確認。

## 問題

目前套用程式碼更新必須回到電腦前手動關掉再重開。使用者希望在遠端（Discord）
就能完成「終止 → 重啟」的循環，前提是 bot 已暫停（安全閘）。

## 啟動鏈背景

- `啟動挖礦bot.bat` → `start "" pythonw -m miningbot` → `__main__.py`（splash）
  → `main()` → `Bot.run()`。
- `.bat` 用 `start`（fire-and-forget），本身立刻退出——**沒有父行程會幫忙重啟**。
- bot 必須自己 spawn 一個獨立的 relauncher，在自身結束後由 relauncher 啟動新行程。

## 設計

### 方案：自包含 relauncher

Bot 自己 spawn 一個 **detached** relauncher 行程（不受父行程結束影響），
然後走既有的正常關機流程；relauncher 在延遲後啟動新 bot。

否決的替代方案：
- **改 `.bat` 成迴圈**——破壞現有 fire-and-forget 啟動模型；非 `.bat` 啟動
  （如 `uv run`）時失效。
- **外部 supervisor 腳本**——過度工程，改變部署模型。

### 指令

`重開`（中文，符合使用者用語）＋ `restart`（英文別名），加入
`discord_commands.COMMAND_NAMES` 白名單。無參數。

### 安全閘：只在暫停時生效

`_handle_discord_command` 收到 `重開`／`restart` 時：

| `self.paused` | 行為 |
|---|---|
| `True` | Discord 回覆「🔄 重開中，N 秒後自動重啟（套用更新）」→ 設 `_pending_restart = True` |
| `False` | 回覆「❌ 請先 `pause` 暫停再重開（重開會中斷目前工作）」→ 不執行 |

暫停已是刻意動作（要先用 `pause` 或 Q 鍵暫停），重開是第二個刻意指令——兩步
即觸發，不再加二次確認（使用者確認：暫停本身就是一種確認）。

### 旗標流轉（比照既有 `_pending_*` 模式）

Discord 命令在**背景輪詢執行緒**處理（`_discord_poll_loop` →
`_handle_discord_command`）。重開是關機操作，不在輪詢執行緒直接執行——
設 `_pending_restart` 旗標，由**主迴圈**消費（確保 `run()` 的 `finally`
清理區塊完整跑過）：

```
輪詢執行緒                        主迴圈
─────────                        ──────
收到 重開 + paused=True           每輪最上方檢查 _pending_restart
→ Discord 回覆確認                → _schedule_restart()（spawn relauncher）
→ _pending_restart = True         → _quit()（_running = False）
                                  ↓
                                  while _running 結束
                                  → finally: audio stop / snapshot drain / web thread join
                                  → process 結束
                                  ↓
                            relauncher（detached，N 秒前 spawn）
                            → start "" pythonw -m miningbot
                            → 新 bot 啟動
```

### 主迴圈檢查點

在 `run()` 的 `while self._running:` 迴圈最上方（`_pending_calib_start`
之前）加：

```python
if self._pending_restart:
    self._pending_restart = False
    if self._schedule_restart():   # spawn 成功才關機；失敗回 False → bot 繼續跑
        self._quit()
    continue
```

`_schedule_restart()` 回 `bool`：成功 → `_quit()` 設 `_running = False`，
`while` 下一輪失效，自然進入 `finally` 清理。失敗 → bot 不關機（旗標已清）。

### Relauncher 實作

```python
def _schedule_restart(self) -> bool:
    """Spawn detached relauncher；成功回 True（主迴圈接著 _quit），失敗回 False。"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    delay = cfg.restart_delay_s
    # ping 做延遲：timeout 在 detached（無 console）環境不可靠。
    # sys.executable 確保用同一顆直譯器（pythonw.exe for Store Python）。
    # DETACHED_PROCESS 讓 relauncher 在父行程結束後存活。
    relaunch = (
        f'ping -n {delay + 1} 127.0.0.1 >nul '
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
        # spawn 失敗 → 回 False，主迴圈不呼叫 _quit（bot 繼續跑，避免「自殺卻沒人接手」）
        self.logger.error("restart relauncher spawn failed: %s", e)
        notify.send_message(cfg.discord_bot_token, cfg.discord_channel_id,
            f"❌ 重開失敗：無法啟動 relauncher（{e}），bot 繼續運行。請手動重啟。")
        return False
```

**為什麼用 `ping` 而非 `timeout`**：`timeout` 需要附著的 console，
detached 行程沒有 → 卡住。`ping -n N` 送 N−1 次間隔 ≈ N−1 秒延遲，
是無 console 環境的標準 Windows 延遲手法。

**為什麼用 `sys.executable` 而非 `pythonw`**：不依賴 PATH；精確重現
啟動當下的直譯器（Store Python 的 `pythonw.exe` 或 `.venv` 的 python）。

### 重開完成通知

exit 前寫 marker 檔到 `cfg.log_dir`；新 bot 在 `Bot.__init__` 或 `run()`
開頭檢查到就發 Discord「✅ 重開完成，已套用更新」再刪除。讓使用者確認
新行程真的起來了。

- marker 路徑：`<log_dir>/restart_marker`（純文字，內容 = 重開時間戳）
- 寫入時機：`_schedule_restart()` spawn 成功後
- 讀取 + 刪除 + 通知：`run()` 開頭（聚焦 Roblox 之前，讓使用者盡早收到）

### Config

新增 `restart_delay_s`（預設 `5`）：relauncher 等待秒數，確保舊 process
完全結束（含 `snapshot_shutdown_drain_s` 的 drain 時間）。

### 日誌（遵循專案「必加 log」原則）

| 決策點 | log |
|---|---|
| 收到指令（暫停中） | `CMD 重開 -> paused=True, _pending_restart set` |
| 收到指令（非暫停） | `CMD 重開 -> rejected (not paused), state=X` |
| spawn relauncher | `restart scheduled: relauncher spawned (delay=Ns, exe=...)` |
| spawn 失敗 | `restart relauncher spawn failed: ...`（ERROR） |
| 開始關機 | 既有 `_quit` 的 `QUIT ...` log 已涵蓋 |

## 測試

純邏輯可測，不需 Roblox／Discord／真實行程：

1. **解析**：`parse_command("重開")` / `parse_command("restart")` →
   `DiscordCommand(name="重開"|"restart")`；`parse_command("別的")` → `None`。
2. **暫停閘**：用 `tests/fake_bot.py` harness，`_handle_discord_command`
   在 `paused=False` 時 → 不設 `_pending_restart`、回覆含「請先暫停」；
   `paused=True` 時 → 設 `_pending_restart = True`。
3. **主迴圈消費（成功）**：設 `_pending_restart = True` → mock
   `subprocess.Popen` → 呼叫一輪主迴圈 → 驗證 `Popen` 被呼叫
   （creationflags 正確）＋ `_pending_restart` 被清回 False ＋
   `_running == False`（`_quit` 被呼叫）。
4. **spawn 失敗**：mock `Popen` 擲例外 → `_schedule_restart()` 回 False ＋
   `_running` 仍 True（`_quit` 沒被呼叫，bot 沒關機）。
5. **marker**：`_schedule_restart` 成功後 marker 檔存在；模擬新 bot 讀到
   marker → 刪除 + 回「重開完成」。

## 文檔同步

| 檔案 | 改動 |
|---|---|
| `discord_commands.py` | `COMMAND_NAMES` 加 `重開`／`restart` |
| `main.py` | `_handle_discord_command` 加分支；`run()` 加 `_pending_restart` 檢查；`__init__` 加旗標；help text 列出新指令 |
| `config.py` | 加 `restart_delay_s` |
| `docs/web-ui-guide.md` | 指令表加 `重開`／`restart` |
| `AGENTS.md` | WHERE TO LOOK「Discord controls」行提及重開 |

## 風險與緩解

- **relauncher 沒起來**：spawn 失敗時 bot 不關機（上方 `except` 分支），
  並 Discord 警告。最壞情況＝使用者手動重啟，與現狀相同。
- **兩個行程同時跑**：`restart_delay_s`（5s）> 關機清理時間
  （snapshot drain 預設 `snapshot_shutdown_drain_s`），確保舊行程先釋放
  audio device／Discord token。新行程啟動時做既有 `_focus_roblox`，若
  失敗會降級（既有路徑）。
- **暫停中被其他指令搶先**：`_pending_restart` 在主迴圈最上方檢查，
  優先於 `_pending_calib_start` 和 paused 分支。`resume` 設 `paused=False`
  不影響——`_pending_restart` 不看 paused，重開優先（正確：使用者要求重開）。
