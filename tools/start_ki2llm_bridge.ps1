param(
    [string]$Python = 'C:\Python314\python.exe',
    [string]$SshConfig = (Join-Path $PSScriptRoot '..\artifacts\update-validation-20261028\config.json')
)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskScript = Join-Path $PSScriptRoot 'ki2llmbridge.py'
$taskStatus = Join-Path $taskRoot 'artifacts\build-v1-llm-bridge-status.json'
if (Test-Path -LiteralPath $taskStatus) {
    $taskPrevious = Get-Content -LiteralPath $taskStatus -Raw | ConvertFrom-Json
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskPrevious.pid)" -ErrorAction SilentlyContinue
    if ($taskProcess -and $taskProcess.CommandLine.Contains('ki2llmbridge.py') -and $taskProcess.CommandLine.Contains('build-v1-llm-bridge-status.json')) {
        Stop-Process -Id $taskPrevious.pid
    } elseif ($taskProcess) { throw 'Status PID belongs to another process.' }
}
$taskArguments = @('-X','utf8',('"'+$taskScript+'"'),'--ssh-config',('"'+(Resolve-Path -LiteralPath $SshConfig).Path+'"'),'--remote-port','18080','--local-port','8080','--status',('"'+$taskStatus+'"'))
$taskBridge = Start-Process -FilePath $Python -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot 'artifacts\build-v1-llm-bridge.log') -RedirectStandardError (Join-Path $taskRoot 'artifacts\build-v1-llm-bridge-error.log')
Write-Output "Local LLM bridge started (PID $($taskBridge.Id)). Status: $taskStatus"
