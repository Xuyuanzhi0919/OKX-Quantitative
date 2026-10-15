param(
    [ValidateSet('start', 'stop', 'status')][string]$Action = 'start',
    [switch]$EnableBackgroundTasks
)
. "$PSScriptRoot\windows-env.ps1"
$stateDir = Join-Path $OkkRoot '.dev-windows'
New-Item -ItemType Directory -Force $stateDir | Out-Null
$stateFile = Join-Path $stateDir 'services.json'
$services = @{}
if (Test-Path $stateFile) {
    $saved = Get-Content $stateFile -Raw | ConvertFrom-Json
    foreach ($prop in $saved.PSObject.Properties) { $services[$prop.Name] = $prop.Value }
}
function Test-OwnedProcess($record) {
    if (-not $record) { return $false }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.Id)" -ErrorAction SilentlyContinue
    return ($proc -and $proc.ExecutablePath -eq $record.Executable -and $proc.CreationDate.ToUniversalTime() -eq ([datetime]$record.Created).ToUniversalTime())
}
function Start-App($name, $exe, $arguments, $folder, $port) {
    if (Test-OwnedProcess $services[$name]) { return }
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already occupied; stop its existing process first."
    }
    $proc = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $folder -WindowStyle Hidden `
        -RedirectStandardOutput "$stateDir\$name.out.log" -RedirectStandardError "$stateDir\$name.err.log" -PassThru
    $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)"
    $services[$name] = @{ Id=$proc.Id; Executable=$info.ExecutablePath; Created=$info.CreationDate.ToString('o') }
    $services | ConvertTo-Json | Set-Content $stateFile -Encoding utf8
}
if ($Action -eq 'stop') {
    foreach ($name in @('frontend','tradekit','backend')) {
        if (Test-OwnedProcess $services[$name]) { & taskkill.exe /PID $services[$name].Id /T /F | Out-Null }
    }
    $listener = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener[0].OwningProcess)"
        if ($proc.ExecutablePath -eq "$OkkRedis\memurai.exe") { & "$OkkRedis\memurai-cli.exe" shutdown }
    }
    & "$OkkPg\pg_ctl.exe" -D "$OkkData\postgres-data" -m fast -w stop
    Write-Output 'Local development services stopped.'
    exit
}
if ($Action -eq 'start') {
    & "$OkkPg\pg_ctl.exe" -D "$OkkData\postgres-data" status *> $null
    if ($LASTEXITCODE -ne 0) {
        & "$OkkPg\pg_ctl.exe" -D "$OkkData\postgres-data" -l "$OkkData\postgres.log" -w start
        if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed' }
    }
    if (-not (Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue)) {
        Start-App 'redis' "$OkkRedis\memurai.exe" '--bind 127.0.0.1 --port 6379 --protected-mode yes' "$OkkData\redis-data" 6379
    }
    & "$OkkRoot\backend\.venv\Scripts\python.exe" "$PSScriptRoot\init_windows_db.py"
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed' }
    $backendArgs = '"' + "$PSScriptRoot\run_windows_backend.py" + '"'
    if ($EnableBackgroundTasks) { $backendArgs += ' --background-tasks' }
    Start-App 'backend' "$OkkRoot\backend\.venv\Scripts\python.exe" $backendArgs "$OkkRoot\backend" 8000
    Start-App 'tradekit' "$OkkRoot\tradekit\.venv\Scripts\python.exe" '-m uvicorn app.main:app --host 127.0.0.1 --port 8010' "$OkkRoot\tradekit" 8010
    Start-App 'frontend' "$OkkNode\node.exe" 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort' "$OkkRoot\frontend" 5173
    foreach ($url in @('http://127.0.0.1:8000/health','http://127.0.0.1:8010/health','http://127.0.0.1:5173/')) {
        $ready = $false
        for ($attempt=0; $attempt -lt 30; $attempt++) {
            try { $null = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2; $ready=$true; break } catch { Start-Sleep -Seconds 1 }
        }
        if (-not $ready) { throw "Service failed to become ready: $url. See $stateDir logs." }
    }
}
foreach ($item in @(@('PostgreSQL',5432),@('Redis',6379),@('Backend',8000),@('TradeKit',8010),@('Frontend',5173))) {
    $listening = [bool](Get-NetTCPConnection -LocalPort $item[1] -State Listen -ErrorAction SilentlyContinue)
    Write-Output "$($item[0]): port $($item[1]), listening=$listening"
}
Write-Output 'Frontend: http://127.0.0.1:5173'
Write-Output 'API docs: http://127.0.0.1:8000/docs'
