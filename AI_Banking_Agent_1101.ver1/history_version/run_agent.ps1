param([int]$Port = 8793)
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
python start.py --port $Port
