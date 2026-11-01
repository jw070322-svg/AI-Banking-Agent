@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python -X utf8 -B -m security_integration.self_assess
) else (
  py -3 -X utf8 -B -m security_integration.self_assess
)
if errorlevel 1 echo 本次失败，请查看上方提示，旧报告不代表本次通过。
pause
