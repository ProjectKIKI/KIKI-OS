param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference='Stop'
$config=(Resolve-Path -LiteralPath $ConfigPath).Path
$workspace=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $config.StartsWith($workspace+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Validator configuration must be inside this workspace' }
$python=(Get-Command pythonw.exe).Source
$runner=Join-Path $PSScriptRoot 'ki2updatevm.py'
$action=New-ScheduledTaskAction -Execute $python -Argument ('"'+$runner+'" --config "'+$config+'"') -WorkingDirectory $workspace
$triggers=@((New-ScheduledTaskTrigger -AtLogOn -User ($env:USERDOMAIN+'\'+$env:USERNAME)),(New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 2)))
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN+'\'+$env:USERNAME) -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'KIKI Update VM Validation' -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Validate explicitly requested KIKI update candidates in the registered Hyper-V lab VM and sign their evidence. No stable promotion.' -Force | Out-Null
Get-ScheduledTask -TaskName 'KIKI Update VM Validation' | Select-Object TaskName,State
