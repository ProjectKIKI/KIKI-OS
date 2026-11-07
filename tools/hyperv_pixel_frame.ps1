param([Parameter(Mandatory=$true)][string]$Output,[ValidateSet('candidate','candidate-r4')][string]$Role='candidate')
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
$state=Get-Content -LiteralPath (Join-Path $repo "artifacts/server-shell/20261105-stage1/$Role/vm.json") -Raw | ConvertFrom-Json
$vm=Get-VM -Id $state.id
if($state.scope -ne 'isolated-paper-pixel-stage1' -or $vm.Name -ne $state.name -or $vm.State -ne 'Running'){throw 'Candidate VM identity/state mismatch'}
$destination=[IO.Path]::GetFullPath($Output)
$allowed=[IO.Path]::GetFullPath((Join-Path $repo "artifacts/server-shell/20261105-stage1/$Role"))+[IO.Path]::DirectorySeparatorChar
if(-not $destination.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Capture output must stay in candidate evidence directory'}
$ns='root/virtualization/v2'
$computer=Get-CimInstance -Namespace $ns -ClassName Msvm_ComputerSystem -Filter "Name='$($state.id)'"
$settings=@(Get-CimAssociatedInstance -InputObject $computer -ResultClassName Msvm_VirtualSystemSettingData | Where-Object {$_.VirtualSystemType -eq 'Microsoft:Hyper-V:System:Realized'})
if($settings.Count -ne 1){throw 'Expected one realized candidate setting'}
$service=Get-CimInstance -Namespace $ns -ClassName Msvm_VirtualSystemManagementService
$width=1024; $height=768
$result=Invoke-CimMethod -InputObject $service -MethodName GetVirtualSystemThumbnailImage -Arguments @{TargetSystem=$settings[0];WidthPixels=[uint16]$width;HeightPixels=[uint16]$height}
if($result.ReturnValue -ne 0){throw "VM frame read failed: $($result.ReturnValue)"}
$offset=0
if($result.ImageData.Length -eq $width*$height*2+4){
 # This host adds a four-byte thumbnail header before the RGB565 pixels.
 $offset=4
}
if($result.ImageData.Length-$offset -ne $width*$height*2){throw "Unexpected RGB565 frame size: $($result.ImageData.Length)"}
Add-Type -AssemblyName System.Drawing
$bitmap=[Drawing.Bitmap]::new($width,$height,[Drawing.Imaging.PixelFormat]::Format16bppRgb565)
try {
 $data=$bitmap.LockBits([Drawing.Rectangle]::new(0,0,$width,$height),[Drawing.Imaging.ImageLockMode]::WriteOnly,[Drawing.Imaging.PixelFormat]::Format16bppRgb565)
 try {[Runtime.InteropServices.Marshal]::Copy([byte[]]$result.ImageData,$offset,$data.Scan0,$width*$height*2)} finally {$bitmap.UnlockBits($data)}
 $bitmap.Save($destination,[Drawing.Imaging.ImageFormat]::Png)
} finally {$bitmap.Dispose()}
Write-Output $destination
