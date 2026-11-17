@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1111.ver2] 本地回归：单元测试 + Schema 契约 + 词库完整性 + 计划往返
echo 边界：本地确定性检查；不是模型评测，不是真实点评端到端测试。
echo.
python run_all_checks.py
echo.
pause
