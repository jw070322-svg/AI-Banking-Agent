@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 安全自评增强版（本地模拟）：http://127.0.0.1:8808/
echo 请保留本窗口；不要使用旧8805或8807服务验收本版。
where py >nul 2>nul
if errorlevel 1 (
  python -X utf8 start_security_integrated.py
) else (
  py -3 -X utf8 start_security_integrated.py
)
pause
