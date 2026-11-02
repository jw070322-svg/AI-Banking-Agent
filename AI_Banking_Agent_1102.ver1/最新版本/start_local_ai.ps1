$ErrorActionPreference = 'Stop'

# ASCII only on purpose: Windows PowerShell 5.1 parses .ps1 as ANSI, so non-ASCII
# literals can corrupt the script. State names are machine-readable; the Chinese
# wording for users is produced by first_agent/local_ai_bootstrap.py.
#
$assetRoot   = Join-Path $PSScriptRoot 'model-assets'
$taskRoot    = Join-Path $PSScriptRoot 'runtime'
[IO.Directory]::CreateDirectory($taskRoot) | Out-Null
$keyFile     = Join-Path $taskRoot 'local-model.key'
$statusFile  = Join-Path $taskRoot 'local-ai-status.json'
$alias       = 'banking-finance-lora'
$port        = 8811
$adapter     = 'training/lora-finance-qwen05b-full/adapter-qwen2.gguf'
$serverFile  = Join-Path $assetRoot 'llama-b11900/llama-server.exe'
$modelFile   = 'model-assets/qwen2.5-0.5b-instruct-q4_k_m.gguf'
$stdoutLog   = Join-Path $taskRoot 'llama-server.stdout.log'
$stderrLog   = Join-Path $taskRoot 'llama-server.stderr.log'

$script:keySource = 'unset'
$script:key = ''

function Write-Status([string]$state, [string]$detail, $extra) {
    $doc = [ordered]@{
        state = $state; detail = $detail; at = (Get-Date).ToString('o')
        key_source = $script:keySource; adapter = $adapter; port = $port
    }
    if ($extra) { foreach ($k in $extra.Keys) { $doc[$k] = $extra[$k] } }
    [IO.File]::WriteAllText($statusFile, ($doc | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
}

function Get-ServerStatus {
    # returns ready | wrong_alias:<ids> | auth | down
    try {
        $models = Invoke-RestMethod "http://127.0.0.1:$port/v1/models" -Headers @{Authorization = "Bearer $script:key"} -TimeoutSec 2
        $ids = @($models.data | ForEach-Object { $_.id })
        if ($ids -contains $alias) { return 'ready' }
        return 'wrong_alias:' + ($ids -join ',')
    } catch {
        # PS 5.1 raises System.Net.WebException, PS 7 raises HttpResponseException.
        # Both expose .Response.StatusCode; a connection refusal exposes neither.
        $code = $null
        try { if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode } } catch { }
        if ($code -eq 401 -or $code -eq 403) { return 'auth' }
        return 'down'
    }
}

# --- the adapter is mandatory: never silently serve the un-tuned base model ---
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $adapter))) {
    Write-Status 'refused_adapter' 'adapter file missing; refusing to start the base model'
    Write-Output 'adapter missing; refusing to start the base model'
    exit 2
}

# Refuse truncated files or a Git LFS pointer in place of the model.
Write-Status 'checking' 'checking portable model assets'
$receipt = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $assetRoot 'manifest.json') | ConvertFrom-Json
function Get-AssetHash([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $hasher.Dispose() }
}
foreach ($asset in $receipt.files) {
    $path = Join-Path $PSScriptRoot $asset.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-AssetHash $path) -ne $asset.sha256) {
        Write-Status 'failed' ('Missing or damaged model asset: ' + $asset.path)
        exit 8
    }
}

# Publish a fully-written per-installation key atomically. Concurrent starts
# always end up reading the same key.
$script:keySource = 'installation'
if (-not (Test-Path -LiteralPath $keyFile)) {
    $temporary = Join-Path $taskRoot ([Guid]::NewGuid().ToString('N') + '.key')
    try {
        [IO.File]::WriteAllText($temporary, ([Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')))
        try { [IO.File]::Move($temporary, $keyFile); $script:keySource = 'generated' }
        catch [IO.IOException] { if (-not (Test-Path -LiteralPath $keyFile)) { throw } }
    } finally { if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) } }
}
$script:key = [IO.File]::ReadAllText($keyFile).Trim()
if ($script:key -notmatch '^[a-fA-F0-9]{64}$') {
    Write-Status 'failed' 'Invalid installation key'
    exit 9
}

# --- inspect the port first; never spawn a second server onto an occupied port ---
$before = Get-ServerStatus
switch -Regex ($before) {
    '^ready$' {
        Write-Status 'already_ready' 'trained model already serving with this key' @{ pid = $null }
        Write-Output 'trained local model is already ready'
        exit 0
    }
    '^wrong_alias:' {
        $seen = $before.Substring('wrong_alias:'.Length)
        Write-Status 'port_conflict' ("port $port answers with alias: " + $seen) @{ alias = $seen }
        Write-Output ("Port $port belongs to a different model service: " + $seen)
        exit 3
    }
    '^auth$' {
        Write-Status 'key_conflict' ("port $port is served with a different key") @{ pid = $null }
        Write-Output "Port $port is held by a server started with a different key; stop it first"
        exit 4
    }
}

# --- start, then poll until ready instead of assuming success ------------------
Remove-Item -LiteralPath $stdoutLog,$stderrLog -ErrorAction SilentlyContinue
$process = Start-Process -FilePath $serverFile -WorkingDirectory $PSScriptRoot -ArgumentList @(
    '--model', ('"' + $modelFile + '"'),
    '--lora', ('"' + $adapter + '"'),
    '--api-key-file', 'runtime/local-model.key',
    '--cors-origins', 'localhost',
    '--alias', $alias,
    '--host', '127.0.0.1',
    '--port', "$port",
    '--ctx-size', '2048',
    '--parallel', '1',
    '--threads', '4',
    '--n-gpu-layers', '0'
) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) {
        $tail = ''
        if (Test-Path -LiteralPath $stderrLog) { $tail = (Get-Content -LiteralPath $stderrLog -Tail 20 -Encoding UTF8) -join "`n" }
        if ($tail -match 'lora|adapter') {
            Write-Status 'refused_adapter' 'llama-server exited while loading the adapter' @{ exit_code = $process.ExitCode; stderr_tail = $tail }
            Write-Output 'adapter failed to load; the base model was not started'
            exit 5
        }
        Write-Status 'failed' 'llama-server exited right after start' @{ exit_code = $process.ExitCode; stderr_tail = $tail }
        Write-Output ("llama-server exited with code " + $process.ExitCode)
        exit 6
    }
    if ((Get-ServerStatus) -eq 'ready') {
        Write-Status 'started' 'trained model started and ready' @{ pid = $process.Id }
        Write-Output ('Started trained local model process ' + $process.Id)
        exit 0
    }
}

if (-not $process.HasExited) { $process.Kill() }
Write-Status 'timeout' ("not ready within 30s; killed pid " + $process.Id) @{ pid = $process.Id }
Write-Output 'local model did not become ready within 30s'
exit 7
