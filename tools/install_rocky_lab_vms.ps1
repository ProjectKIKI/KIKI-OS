param([int]$Start = 2, [int]$End = 10, [switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
$labRoot = 'F:\hyper-v\kiki-iso-lab-20260928'
$rockyIso = 'F:\isos\Rocky-9.8-x86_64-minimal.iso'
$template = 'E:\dev\KIKI-OS\artifacts\hyperv-lab\rocky-lab-01.ks.cfg'
if (-not (Test-Path -LiteralPath $rockyIso)) { throw "Missing Rocky ISO: $rockyIso" }
if (-not (Test-Path -LiteralPath $template)) { throw "Missing Kickstart template: $template" }
if ($Start -lt 2 -or $End -gt 10 -or $Start -gt $End) { throw 'Only lab VMs 02..10 are permitted.' }
foreach ($i in $Start..$End) {
    $vmName = 'kiki-iso-lab-{0:D2}' -f $i
    $vm = Get-VM -Name $vmName -ErrorAction Stop
    if ($vm.State -ne 'Off' -or $vm.Generation -ne 2) { throw "VM must be Off and Generation 2: $vmName" }
    $disk = @(Get-VMHardDiskDrive -VMName $vmName)
    $expectedDisk = Join-Path $labRoot "$vmName.vhdx"
    if ($disk.Count -ne 1 -or $disk[0].Path -ne $expectedDisk) { throw "Unexpected disk on $vmName" }
    $vhd = Get-VHD -Path $expectedDisk
    if ($vhd.Size -ne 16GB -or $vhd.FileSize -gt 8MB) { throw "Disk is not blank: $expectedDisk" }
    $cfgPath = Join-Path $labRoot "$vmName.ks.cfg"
    $oemPath = Join-Path $labRoot "$vmName-oemdrv.iso"
    if (Test-Path -LiteralPath $oemPath) { throw "Refusing to overwrite existing OEMDRV: $oemPath" }
    $cfg = (Get-Content -LiteralPath $template -Raw).Replace('kiki-iso-lab-01', $vmName).Replace('rocky-lab-01', ('rocky-lab-{0:D2}' -f $i))
    [System.IO.File]::WriteAllText($cfgPath, $cfg, [System.Text.UTF8Encoding]::new($false))
    $wslCfg = '/mnt/f/hyper-v/kiki-iso-lab-20260928/' + "$vmName.ks.cfg"
    $wslOem = '/mnt/f/hyper-v/kiki-iso-lab-20260928/' + "$vmName-oemdrv.iso"
    & wsl -d Rocky-9 -- genisoimage -quiet -V OEMDRV -o $wslOem -graft-points "ks.cfg=$wslCfg"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $oemPath)) { throw "OEMDRV creation failed: $vmName" }
    if ($i -eq 2) { Set-VM -Name $vmName -MemoryStartupBytes 2GB }
    if ($i -eq 9) { Set-VMFirmware -VMName $vmName -EnableSecureBoot On -SecureBootTemplate MicrosoftUEFICertificateAuthority }
    $dvd = @(Get-VMDvdDrive -VMName $vmName)
    if ($dvd.Count -ne 1) { throw "Expected one DVD drive: $vmName" }
    Set-VMDvdDrive -VMName $vmName -ControllerNumber $dvd[0].ControllerNumber -ControllerLocation $dvd[0].ControllerLocation -Path $rockyIso
    Add-VMDvdDrive -VMName $vmName -ControllerNumber 0 -ControllerLocation 2 -Path $oemPath
    Set-VMFirmware -VMName $vmName -FirstBootDevice $disk[0]
    Write-Output "Prepared $vmName : $expectedDisk"
    if (-not $PrepareOnly) { Start-VM -Name $vmName; Write-Output "Started $vmName" }
}
