# Paste the guest clipboard through VMMS only. Never uses host input or clipboard.
param([ValidateSet('candidate-r4')][string]$Role='candidate-r4', [ValidateSet('Paste','NextField','SwitchWindow')][string]$Combination='Paste')
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$state=Get-Content -LiteralPath (Join-Path $repo "artifacts/server-shell/20261105-stage1/$Role/vm.json") -Raw | ConvertFrom-Json
$vm=Get-VM -Id $state.id
if($state.scope -ne 'isolated-paper-pixel-stage1' -or $vm.Name -ne $state.name -or $vm.State -ne 'Running'){throw 'Candidate identity/state mismatch'}
if((Get-VM -Name $state.source_vm).State -ne 'Off'){throw 'Source VM must remain off'}
$keyboard=@(Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_Keyboard -Filter "SystemName='$($state.id)'")
if($keyboard.Count -ne 1){throw 'Expected one candidate virtual keyboard'}
$modifier=if($Combination -eq 'SwitchWindow'){18}else{17}
$keyCode=if($Combination -eq 'Paste'){86}else{9}
try {
    $result=Invoke-CimMethod -InputObject $keyboard[0] -MethodName PressKey -Arguments @{KeyCode=[uint32]$modifier}
    if($result.ReturnValue -ne 0){throw 'Guest Control press failed'}
    $result=Invoke-CimMethod -InputObject $keyboard[0] -MethodName TypeKey -Arguments @{KeyCode=[uint32]$keyCode}
    if($result.ReturnValue -ne 0){throw 'Guest V key failed'}
} finally {
    $release=Invoke-CimMethod -InputObject $keyboard[0] -MethodName ReleaseKey -Arguments @{KeyCode=[uint32]$modifier}
    if($release.ReturnValue -ne 0){throw 'Guest Control release failed'}
}
Write-Output "$Combination sent only to the candidate virtual keyboard; host input and clipboard untouched"
