# 有未處理的玩家標註素材時，提醒跑一次微調迴圈（使用者 2026-07-31 要求：
# 「每次提出新問題都幫我自主微調一次，這樣我就不會忘記」）。
#
# 「未處理」＝ tests/fixtures/ 底下還沒進版控的標註 .json。微調收尾一定會把該批素材
# 連同修復一起 commit，所以這個訊號會自己歸零，不需要另外維護 marker 檔。
$ErrorActionPreference = 'SilentlyContinue'
# PS 5.1 預設用主控台代碼頁輸出，中文會變亂碼進 agent context。
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$root = $env:CLAUDE_PROJECT_DIR
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

$new = git status --porcelain -- 'tests/fixtures/*/*.json' | Where-Object { $_ -match '^\?\?' }
$n = ($new | Measure-Object).Count
if ($n -eq 0) { exit 0 }

Write-Output "[標註素材待微調] tests/fixtures/ 有 $n 個未進版控的玩家標註 .json："
$new | ForEach-Object { ($_ -split '\s+', 2)[1] } | Select-Object -First 5 |
    ForEach-Object { Write-Output "  $_" }
Write-Output "跑一次標註驅動的微調迴圈（skill tuning-from-incidents 的「標註驅動」一節）："
Write-Output "重放現行偵測器 → 兩側夾 → TDD 修復 → 素材連同修復一起 commit，本提醒即自動消失。"
Write-Output "夾不出兩側就別動門檻：結論寫進 docs/open-detection-issues.md 再 commit 素材。"
