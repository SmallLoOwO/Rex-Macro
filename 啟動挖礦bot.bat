@echo off
cd /d "%~dp0"
REM 用 .venv 的 pythonw（非 PATH 解析到的 Store 版），Store 版沒裝 tesserocr/fastapi 等
REM 專案依賴，會靜默退回慢路徑或整個功能不存在（H061／2026-08-08 sweep 慢查核）。
REM 沒有主控台視窗；倒數與狀態 HUD 由 bot 自己顯示。
start "" "%~dp0.venv\Scripts\pythonw.exe" -m miningbot
