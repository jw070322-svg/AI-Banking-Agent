@echo off
setlocal
cd /d "%~dp0"
for /d %%D in (*) do if exist "%%D\start_security_integrated.py" (
    pushd "%%D"
    where py >nul 2>nul
    if errorlevel 1 (
        python -X utf8 start_security_integrated.py
    ) else (
        py -3 -X utf8 start_security_integrated.py
    )
    popd
    pause
    exit /b
)
echo Application folder missing. Extract the entire ZIP before starting.
pause
exit /b 1
