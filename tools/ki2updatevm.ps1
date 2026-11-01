param(
    [Parameter(Mandatory=$true)][ValidateSet('inspect','checkpoint','start','recovery')][string]$Action,
    [Parameter(Mandatory=$true)][string]$VmName,
    [Parameter(Mandatory=$true)][Guid]$VmId,
    [string]$Nonce
)
$ErrorActionPreference='Stop'
$vm=Get-VM -Name $VmName
if ($vm.Id -ne $VmId -or $VmName -notmatch '^kiki-gnome-apps-r3-20261028$') { throw 'Unregistered update lab VM' }
$disks=@(Get-VMHardDiskDrive -VM $vm)
$expectedDisk=[IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp/kiki-gnome-apps-r3-20261028/install-test.vhdx'))
if ($disks.Count -ne 1) { throw 'Unexpected disks on update lab VM' }
$attached=[IO.Path]::GetFullPath($disks[0].Path)
$allowedDiskRoot=[IO.Path]::GetFullPath((Split-Path $expectedDisk -Parent))+[IO.Path]::DirectorySeparatorChar
if (-not $attached.StartsWith($allowedDiskRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Disk outside the dedicated test directory' }
if ($Nonce -and $Nonce -notmatch '^[a-f0-9]{32}$') { throw 'Invalid validation nonce' }
switch ($Action) {
    'inspect' { @{id=$vm.Id.ToString();name=$vm.Name;state=$vm.State.ToString();ip=@((Get-VMNetworkAdapter -VM $vm).IPAddresses | Where-Object {$_ -match '^172\.'})} | ConvertTo-Json -Compress }
    'checkpoint' {
        if ($vm.State -ne 'Off') { throw 'Shut down the lab VM before creating a disk-only checkpoint' }
        Set-VM -VM $vm -CheckpointType Standard
        $name='ki2-update-'+$Nonce
        if (Get-VMSnapshot -VM $vm -Name $name -ErrorAction SilentlyContinue) { throw 'Validation checkpoint already exists' }
        Checkpoint-VM -VM $vm -SnapshotName $name
        Write-Output $name
    }
    'start' { if ($vm.State -eq 'Off') { Start-VM -VM $vm | Out-Null }; Write-Output 'started' }
    'recovery' {
        $snapshot=Get-VMSnapshot -VM $vm -Name ('ki2-update-'+$Nonce)
        if ($vm.State -ne 'Off') { throw 'Stop the dedicated VM before restoring its validation checkpoint' }
        Restore-VMSnapshot -VMSnapshot $snapshot -Confirm:$false
        Start-VM -VMName $VmName | Out-Null
    }
}
