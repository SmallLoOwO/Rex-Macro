# CLAUDE.md — Roblox REX 挖礦自動化

@AGENTS.md

本檔是 Claude Code 的入口，**唯一的操作契約是根目錄 `AGENTS.md`**（上面那行會自動
把它載進 context）。硬規則、查閱順序、命令清單、實機排錯全在那裡，本檔不複製——
複製過的東西一定會漂。套件與測試另有 `miningbot/AGENTS.md`、`tests/AGENTS.md`，
就近的檔案優先。

其他 agent 工具（Codex、Cursor…）直接讀 `AGENTS.md` 即可，內容不綁任何工具。

## 這個 repo 是什麼

Windows 專用的 Python 3.11+ Roblox REX 挖礦自動化。`miningbot/main.py` 是狀態機與
I/O 編排；純決策拆在 `states.py`、`harvester.py`、`miner.py`、`game_data.py`、
`reentry*.py`、`remote_aim.py`、`web_*.py`。行為以程式、測試與 `miningbot/config.py`
預設值為準，不以文件為準。

## 開工三步

```powershell
git status --short          # 保留所有不相關的既有修改（可能有另一個 session 在改）
uv sync --locked
uv run pytest -q            # 完整命令清單見 AGENTS.md COMMANDS
```

## Claude Code 專屬

- 回覆與 commit 訊息用中文；識別字、log key、錯誤字串保持原文。
- 用 `rg`／Grep 找符號，不要相信文件裡的歷史行號。
- ⚠ Grep 工具守 gitignore，搜不到 `.claude/worktrees/**`；查「某修復是否已存在」時
  要另外跑 `git worktree list` 與孤兒 commit 掃描。
- 專案技能：`.claude/skills/tuning-from-incidents`（實機事故微調迴圈）。

## 文件地圖

完整清單與「現行／歷史」判定在 `docs/README.md`。最常用：`docs/incidents.md`
（實機事故）、`docs/open-detection-issues.md`（已量測未修復）、`docs/web-ui-guide.md`
（網頁 UI 操作與排錯）、`docs/manual-sampling.md`、`assets/README.md`、
`tests/fixtures/README.md`。
