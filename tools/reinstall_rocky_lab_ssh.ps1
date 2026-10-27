param([int]$Start = 1, [int]$End = 10)
$ErrorActionPreference = 'Stop'
$labRoot = 'F:\hyper-v\kiki-iso-lab-20260928'
$backupRoot = Join-Path $labRoot 'pre-ssh-reinstall'
$rockyIso = 'F:\isos\Rocky-9.8-x86_64-minimal.iso'
$template = 'E:\dev\KIKI-OS\artifacts\hyperv-lab\rocky-lab-ssh.ks.cfg'
if ($Start -lt 1 -or $End -gt 10 -or $Start -gt $End) { throw 'Only lab VMs 01..10 are permitted.' }
if (-not (Test-Path -LiteralPath $rockyIso) -or -not (Test-Path -LiteralPath $template)) { throw 'Missing installation media or template.' }
if (-not (Test-Path -LiteralPath $backupRoot)) { New-Item -ItemType Directory -Path $backupRoot | Out-Null }

# Validate all requested targets before changing any of them.
foreach ($i in $Start..$End) {
    $n = 'kiki-iso-lab-{0:D2}' -f $i
    $vm = Get-VM -Name $n -ErrorAction Stop
    $h = @(Get-VMHardDiskDrive -VMName $n)
    $a = @(Get-VMNetworkAdapter -VMName $n)
    $expected = Join-Path $labRoot "$n.vhdx"
    if ($vm.Generation -ne 2 -or $h.Count -ne 1 -or $h[0].Path -ne $expected) { throw "Unexpected VM/disk: $n" }
    if ($a.Count -ne 1 -or $a[0].SwitchName -ne 'Default Switch') { throw "Unexpected NIC: $n" }
    if ((Get-VHD -Path $expected).Size -ne 16GB) { throw "Unexpected VHD size: $n" }
    if (Test-Path -LiteralPath (Join-Path $backupRoot "$n.vhdx")) { throw "Backup already exists: $n" }
    if (Test-Path -LiteralPath (Join-Path $labRoot "$n-ssh-oemdrv.iso")) { throw "SSH OEMDRV already exists: $n" }
}

foreach ($i in $Start..$End) {
    $n = 'kiki-iso-lab-{0:D2}' -f $i
    $diskPath = Join-Path $labRoot "$n.vhdx"
    $backupPath = Join-Path $backupRoot "$n.vhdx"
    $cfgPath = Join-Path $labRoot "$n-ssh.ks.cfg"
    $oemPath = Join-Path $labRoot "$n-ssh-oemdrv.iso"
    $cfg = (Get-Content -LiteralPath $template -Raw).Replace('rocky-lab-01', ('rocky-lab-{0:D2}' -f $i))
    [System.IO.File]::WriteAllText($cfgPath, $cfg, [System.Text.UTF8Encoding]::new($false))
    $wslCfg = '/mnt/f/hyper-v/kiki-iso-lab-20260928/' + "$n-ssh.ks.cfg"
    $wslOem = '/mnt/f/hyper-v/kiki-iso-lab-20260928/' + "$n-ssh-oemdrv.iso"
    & wsl -d Rocky-9 -- genisoimage -quiet -V OEMDRV -o $wslOem -graft-points "ks.cfg=$wslCfg"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $oemPath)) { throw "OEMDRV creation failed: $n" }
    Stop-VM -Name $n
    if ((Get-VM -Name $n).State -ne 'Off') { throw "VM did not stop: $n" }
    Move-Item -LiteralPath $diskPath -Destination $backupPath
    New-VHD -Path $diskPath -SizeBytes 16GB -Dynamic | Out-Null
    $ds = @(Get-VMDvdDrive -VMName $n | Sort-Object ControllerLocation)
    if ($ds.Count -ne 2) { throw "Expected two DVD drives: $n" }
    Set-VMDvdDrive -VMName $n -ControllerNumber $ds[0].ControllerNumber -ControllerLocation $ds[0].ControllerLocation -Path $rockyIso
    Set-VMDvdDrive -VMName $n -ControllerNumber $ds[1].ControllerNumber -ControllerLocation $ds[1].ControllerLocation -Path $oemPath
    Set-VMFirmware -VMName $n -FirstBootDevice (Get-VMHardDiskDrive -VMName $n)
    Start-VM -Name $n
    Write-Output "Reinstalling $n; backup $backupPath"
}
