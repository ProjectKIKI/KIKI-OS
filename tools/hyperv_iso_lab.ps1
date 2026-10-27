param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 10)]
    [int[]]$Numbers,
    [ValidateRange(5, 120)]
    [int]$BootSeconds = 35,
    [string]$ExpectedIso = 'E:\dev\KIKI-OS\dist\iso\kiki-stage3-v3-installer-x86_64-20260928-r20.iso',
    [string]$CaptureSuffix = ''
)

$ErrorActionPreference = 'Stop'
$lab = 'F:\hyper-v\kiki-iso-lab-20260928'
$output = 'E:\dev\KIKI-OS\artifacts\hyperv-lab'
Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Path $output -Force | Out-Null

$names = @($Numbers | ForEach-Object { 'kiki-iso-lab-{0:D2}' -f $_ })
foreach ($name in $names) {
    $vm = Get-VM -Name $name -ErrorAction Stop
    if ($vm.State -ne 'Off' -or -not $vm.Path.StartsWith($lab + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected state or path for $name"
    }
    $dvd = Get-VMDvdDrive -VMName $name
    if ($dvd.Path -ne $ExpectedIso) { throw "Unexpected ISO for $name" }
}

try {
    foreach ($name in $names) {
        Start-VM -Name $name
        Write-Output "$name started"
    }
    Start-Sleep -Seconds $BootSeconds

    $service = Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_VirtualSystemManagementService |
        Select-Object -First 1
    foreach ($name in $names) {
        $vm = Get-VM -Name $name -ErrorAction Stop
        $id = $vm.Id.ToString().ToUpperInvariant()
        $setting = Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_VirtualSystemSettingData |
            Where-Object { $_.InstanceID -eq "Microsoft:$id" }
        if (-not $setting) { throw "No current settings for $name" }
        $result = Invoke-CimMethod -InputObject $service -MethodName GetVirtualSystemThumbnailImage -Arguments @{
            TargetSystem = $setting
            WidthPixels = [uint16]640
            HeightPixels = [uint16]480
        }
        if ($result.ReturnValue -ne 0 -or $result.ImageData.Length -ne 614404) {
            throw "Unexpected thumbnail response for $name"
        }
        $bitmap = [System.Drawing.Bitmap]::new(640, 480, [System.Drawing.Imaging.PixelFormat]::Format16bppRgb565)
        try {
            $rectangle = [System.Drawing.Rectangle]::new(0, 0, 640, 480)
            $pixels = $bitmap.LockBits($rectangle, [System.Drawing.Imaging.ImageLockMode]::WriteOnly,
                [System.Drawing.Imaging.PixelFormat]::Format16bppRgb565)
            try {
                [System.Runtime.InteropServices.Marshal]::Copy([byte[]]$result.ImageData, 4, $pixels.Scan0, 614400)
            } finally {
                $bitmap.UnlockBits($pixels)
            }
            $imagePath = Join-Path $output ($name + $CaptureSuffix + '.png')
            $bitmap.Save($imagePath, [System.Drawing.Imaging.ImageFormat]::Png)
        } finally {
            $bitmap.Dispose()
        }
        [pscustomobject]@{
            Name = $name
            State = $vm.State
            UptimeSeconds = [math]::Round($vm.Uptime.TotalSeconds)
            Capture = $imagePath
        }
    }
} finally {
    foreach ($name in $names) {
        $vm = Get-VM -Name $name -ErrorAction SilentlyContinue
        if ($vm -and $vm.State -eq 'Running') {
            Stop-VM -Name $name -TurnOff -Confirm:$false
        }
    }
}
