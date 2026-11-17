param([string]$OutputDir = ('output/run-' + [guid]::NewGuid().ToString('N').Substring(0, 8)))
Set-Location -LiteralPath $PSScriptRoot
python -m ethan_toolkit demo --output-dir $OutputDir
