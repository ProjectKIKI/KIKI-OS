param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^(kiki-iso-lab-\d\d|kiki-boot-r23-verify)$')]
    [string]$VMName,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$vm = Get-VM -Name $VMName -ErrorAction Stop
if ($vm.State -ne 'Running') { throw "$VMName is not running" }
$id = $vm.Id.ToString().ToUpperInvariant()
$setting = Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_VirtualSystemSettingData |
    Where-Object { $_.InstanceID -eq "Microsoft:$id" }
$service = Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_VirtualSystemManagementService |
    Select-Object -First 1
if (-not $setting -or -not $service) { throw 'Hyper-V thumbnail API unavailable' }
$result = Invoke-CimMethod -InputObject $service -MethodName GetVirtualSystemThumbnailImage -Arguments @{
    TargetSystem = $setting
    WidthPixels = [uint16]640
    HeightPixels = [uint16]480
}
if ($result.ReturnValue -ne 0 -or $result.ImageData.Length -ne 614404) {
    throw 'Unexpected thumbnail response'
}
Add-Type -AssemblyName System.Drawing
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
    $bitmap.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    $bitmap.Dispose()
}
[pscustomobject]@{ VM = $VMName; State = $vm.State; Uptime = $vm.Uptime; Capture = $OutputPath }
