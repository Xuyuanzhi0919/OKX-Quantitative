$ErrorActionPreference = 'Stop'
$OkkRoot = Split-Path $PSScriptRoot -Parent
$OkkTools = Join-Path $env:LOCALAPPDATA 'Programs\OKKDev'
$OkkData = Join-Path $env:LOCALAPPDATA 'OKKDev'
$OkkNode = Join-Path $OkkTools 'node-v22.23.3-win-x64'
$OkkPg = Join-Path $OkkTools 'postgresql15\pgsql\bin'
$OkkRedis = Join-Path $OkkTools 'memurai'
$env:Path = "$OkkNode;$OkkPg;$OkkRedis;$env:APPDATA\npm;$env:Path"
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:OKX_CLI_BIN = Join-Path $OkkNode 'okx.cmd'
Get-Content (Join-Path $OkkRoot '.env.local') | ForEach-Object {
    if ($_ -match '^([A-Z_][A-Z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
