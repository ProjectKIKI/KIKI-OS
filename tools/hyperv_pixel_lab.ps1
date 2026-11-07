param(
    [Parameter(Mandatory=$true)][ValidateSet('create','start','status','stop')][string]$Action,
    [ValidateSet('baseline','candidate')][string]$Role='baseline'
)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$root=Join-Path $repo 'artifacts/server-shell/20261105-stage1'
$name="kiki-paper-pixel-$Role-20261105"
$statePath=Join-Path $root "$Role/vm.json"
if($Action -eq 'create') {
    if((Test-Path -LiteralPath $statePath) -or (Get-VM -Name $name -ErrorAction SilentlyContinue)){throw 'Refusing to reuse VM'}
    $source=Get-VM -Name 'kiki-build-v1-ga-hyperv-20261101'
    if($source.Id.ToString() -ne 'b3089726-4b58-4c91-bdf8-4f8633984585' -or $source.State -ne 'Off'){throw 'Source VM must be the preserved powered-off baseline'}
    $sourceDisk=(Get-VMHardDiskDrive -VM $source).Path
    if(@($sourceDisk).Count -ne 1){throw 'Unexpected source disk count'}
    $chain=@(); $current=$sourceDisk
    while($current){
        $vhd=Get-VHD -Path $current
        $chain+=@{path=$current;sha256=(Get-FileHash -LiteralPath $current -Algorithm SHA256).Hash.ToLowerInvariant()}
        $current=$vhd.ParentPath
    }
    $dir=Join-Path $root $Role
    if(Test-Path -LiteralPath $dir){throw 'Refusing to reuse work directory'}
    New-Item -ItemType Directory -Path $dir | Out-Null
    $disk=Join-Path $dir 'independent.vhdx'
    Convert-VHD -Path $sourceDisk -DestinationPath $disk -VHDType Dynamic
    if((Get-VHD -Path $disk).ParentPath){throw 'Clone still depends on original'}
    $vm=New-VM -Name $name -Generation 2 -Path $dir -MemoryStartupBytes 4GB -NoVHD -SwitchName 'Default Switch'
    Set-VMProcessor -VM $vm -Count 2
    Set-VMMemory -VM $vm -DynamicMemoryEnabled $false
    Set-VM -VM $vm -AutomaticCheckpointsEnabled $false -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
    Add-VMHardDiskDrive -VM $vm -Path $disk
    Set-VMFirmware -VM $vm -EnableSecureBoot Off -FirstBootDevice (Get-VMHardDiskDrive -VM $vm)
    # Preserve the installed MAC-bound NetworkManager profile; only one clone
    # may run, and the source VM must remain off. No source VM settings change.
    $mac=(Get-VMNetworkAdapter -VM $source).MacAddress
    Set-VMNetworkAdapter -VM $vm -StaticMacAddress $mac
    Set-VMComPort -VM $vm -Number 1 -Path "\\.\pipe\$name-com1"
    @{name=$name;id=$vm.Id.ToString();disk=$disk;scope='isolated-paper-pixel-stage1';role=$Role;
      source_vm=$source.Name;source_chain=$chain;mac=$mac;created_from='independent conversion of preserved GA installed disk, not a fresh ISO installation'} |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8
    Write-Output $statePath
    return
}
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$vm=Get-VM -Name $name
if($state.scope -ne 'isolated-paper-pixel-stage1' -or $state.id -ne $vm.Id.ToString()){throw 'VM identity mismatch'}
$disks=@(Get-VMHardDiskDrive -VM $vm)
if($disks.Count -ne 1 -or $disks[0].Path -ne $state.disk){throw 'VM disk identity mismatch'}
switch($Action){
    'start' {
        $other=Get-VM -Name 'kiki-paper-pixel-*-20261105' | Where-Object {$_.Name -ne $name -and $_.State -ne 'Off'}
        if($other -or (Get-VM -Name $state.source_vm).State -ne 'Off'){throw 'Only one MAC-preserving clone may run'}
        Start-VM -VM $vm
    }
    'status' { $vm | Select-Object Name,State,Id,Uptime,MemoryAssigned; Get-VMNetworkAdapter -VM $vm | Select-Object IPAddresses }
    'stop' { if($vm.State -eq 'Running'){Stop-VM -VM $vm} }
}
