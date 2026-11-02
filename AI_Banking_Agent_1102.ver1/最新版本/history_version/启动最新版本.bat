@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo 最新UI恢复版：http://127.0.0.1:8805/
echo 请保留此窗口，并在浏览器打开上面的地址。
where py >nul 2>nul
if errorlevel 1 (
  python -X utf8 start_ui_fixed.py --port 8805
) else (
  py -3 -X utf8 start_ui_fixed.py --port 8805
)
pause
