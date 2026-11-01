@echo off
cd /d "%~dp0"
python -X utf8 -B start_live_product_quotes.py --port 8807
pause
