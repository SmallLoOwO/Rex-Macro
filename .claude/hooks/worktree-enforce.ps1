# 強制 NON-NEGOTIABLE RUNTIME RULE 16：每個 session 一棵 worktree。
# 主工作目錄共用，平行 edit 會互覆（H055 修復孤兒 408069b、dangling commit
# 7082eaeb／3c857eea 都是已發生的損失）。此 hook 在 SessionStart 注入提醒；
# 在 linked worktree 內則靜默放行。
$ErrorActionPreference = 'SilentlyContinue'
# PS 5.1 預設用主控台代碼頁輸出，中文會變亂碼進 agent context。
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$root = $env:CLAUDE_PROJECT_DIR
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

# 只在 git repo 內檢查
$gitDir = git rev-parse --git-dir 2>$null
if (-not $gitDir) { exit 0 }

# linked worktree 的 git-dir 路徑含 worktrees 段 → 安全放行
if ($gitDir -like '*worktrees*') { exit 0 }

# 主工作目錄：檢查髒度與 sibling worktree
$dirtyN = (git status --porcelain | Measure-Object).Count
$worktreeN = (git worktree list --porcelain | Select-String '^worktree ' | Measure-Object).Count
$siblings = $worktreeN - 1

if ($dirtyN -gt 0 -and $siblings -gt 0) {
    Write-Output "[RULE 16 違規風險] 主工作目錄有 $dirtyN 個未 commit 檔案，同時存在 $siblings 個 sibling worktree。"
    Write-Output "這些改動若不是你這個 session 寫的，就是另一個 session 正在主目錄改——你一動就互覆。"
    Write-Output "第一次 edit 前先 EnterWorktree（或 git worktree add）開自己的工作目錄；否則依 NON-NEGOTIABLE RUNTIME RULE 16 不要動主目錄。"
} elseif ($dirtyN -gt 0) {
    Write-Output "[RULE 16 提醒] 主工作目錄有 $dirtyN 個未 commit 檔案。若不是你這個 session 改的，開新 worktree 再 edit（NON-NEGOTIABLE RUNTIME RULE 16）。"
} elseif ($siblings -gt 0) {
    Write-Output "[RULE 16 提醒] 偵測到 $siblings 個 sibling worktree。要平行作業先開自己的 worktree（NON-NEGOTIABLE RUNTIME RULE 16）。"
}
exit 0
