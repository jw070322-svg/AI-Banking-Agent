$ErrorActionPreference = 'Stop'
$taskRoot = 'F:\AI_Banking\local-ai'
New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null
$release = Invoke-RestMethod 'https://api.github.com/repos/ollama/ollama/releases/latest'
$asset = $release.assets | Where-Object name -eq 'ollama-windows-amd64.zip' | Select-Object -First 1
if (-not $asset -or -not $asset.digest.StartsWith('sha256:')) { throw 'Missing official checksum' }
$archive = Join-Path $taskRoot ($release.tag_name + '-windows-amd64.zip')
if (-not (Test-Path -LiteralPath $archive) -or (Get-Item -LiteralPath $archive).Length -ne $asset.size) {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive -TimeoutSec 600 -UseBasicParsing
}
$checksum = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()
if ($checksum -ne $asset.digest.Substring(7)) { throw 'Checksum mismatch; refusing to run' }
$install = Join-Path $taskRoot $release.tag_name
if (-not (Test-Path -LiteralPath (Join-Path $install 'ollama.exe'))) {
    Expand-Archive -LiteralPath $archive -DestinationPath $install
}
@{version=$release.tag_name;path=$install;sha256=$checksum;source=$asset.browser_download_url} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot 'installation.json') -Encoding utf8
Write-Output ('Installed and verified: ' + $install)
