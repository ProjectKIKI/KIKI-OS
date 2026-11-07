# Sends one bounded navigation key to the isolated Linux VM's virtual keyboard.
# Uses VMMS, never a Windows app/window, SendInput, clipboard, or host focus.
param([ValidateSet('Return','Escape','Tab','Space','Up','Down')][string]$Key='Return',[ValidateSet('candidate','candidate-r4')][string]$Role='candidate')
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$state=Get-Content -LiteralPath (Join-Path $repo "artifacts/server-shell/20261105-stage1/$Role/vm.json") -Raw | ConvertFrom-Json
$vm=Get-VM -Id $state.id
if($state.scope -ne 'isolated-paper-pixel-stage1' -or $vm.Name -ne $state.name -or $vm.State -ne 'Running'){throw 'Candidate identity/state mismatch'}
if((Get-VM -Name $state.source_vm).State -ne 'Off'){throw 'Source VM must remain off'}
$keyboard=@(Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_Keyboard -Filter "SystemName='$($state.id)'")
if($keyboard.Count -ne 1){throw 'Expected one candidate virtual keyboard'}
$codes=@{Return=13;Escape=27;Tab=9;Space=32;Up=38;Down=40}
$result=Invoke-CimMethod -InputObject $keyboard[0] -MethodName TypeKey -Arguments @{keyCode=[uint32]$codes[$Key]}
if($result.ReturnValue -ne 0){throw "Guest Enter failed: $($result.ReturnValue)"}
Write-Output "$Key sent only to candidate virtual keyboard; host input untouched"
