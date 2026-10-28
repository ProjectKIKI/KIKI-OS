param(
    [Parameter(Mandatory=$true)][ValidateSet('create','start','status','capture','text','key','select-all','click','stop','eject','media','boot-media','tty','chord')][string]$Action,
    [string]$Value=''
)
$ErrorActionPreference='Stop'
$taskRoot='E:\dev\KIKI-OS\artifacts\gnome-native-apps-20261028\vm-r2'
$vmName='kiki-gnome-apps-r2-20261028'
$stateFile=Join-Path $taskRoot 'vm.json'
if ($Action -eq 'create') {
    if (Test-Path -LiteralPath $taskRoot) { throw 'Refusing to reuse an existing VM directory' }
    if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) { throw 'VM name already exists' }
    $iso=(Resolve-Path -LiteralPath $Value).Path
    $expectedRoot='E:\dev\KIKI-OS\artifacts\gnome-native-apps-20261028\'
    if (-not $iso.StartsWith($expectedRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'ISO outside candidate' }
    $manifest=Get-Content -LiteralPath ($iso+'.sha256.json') -Raw | ConvertFrom-Json
    if ((Get-FileHash -LiteralPath $iso -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'ISO SHA mismatch' }
    New-Item -ItemType Directory -Path $taskRoot | Out-Null
    $diskRoot=Join-Path $env:LOCALAPPDATA 'Temp\kiki-gnome-apps-r2-20261028'
    if (Test-Path -LiteralPath $diskRoot) { throw 'Refusing to reuse a VM disk directory' }
    New-Item -ItemType Directory -Path $diskRoot | Out-Null
    $disk=Join-Path $diskRoot 'install-test.vhdx'
    New-VHD -Path $disk -Dynamic -SizeBytes 32GB | Out-Null
    $vm=New-VM -Name $vmName -Generation 2 -Path $taskRoot -MemoryStartupBytes 4GB -NoVHD -SwitchName 'Default Switch'
    Set-VMProcessor -VMName $vmName -Count 2
    Set-VMMemory -VMName $vmName -DynamicMemoryEnabled $false
    Set-VM -Name $vmName -AutomaticCheckpointsEnabled $false -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
    Add-VMHardDiskDrive -VMName $vmName -Path $disk
    Add-VMDvdDrive -VMName $vmName -Path $iso
    $bootDisk=Get-VMDvdDrive -VMName $vmName
    Set-VMFirmware -VMName $vmName -EnableSecureBoot Off -FirstBootDevice $bootDisk
    Set-VMComPort -VMName $vmName -Number 1 -Path '\\.\pipe\kiki-gnome-apps-r2-20261028-com1'
    @{name=$vmName;id=$vm.Id.ToString();scope='fresh-gnome-apps-r2-20261028';root=$taskRoot;disk=$disk;iso=$iso;iso_sha256=$manifest.sha256} | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
    Write-Output 'Created new isolated VM; no existing VM or disk attached.'
    return
}
$state=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$vm=Get-VM -Name $vmName
if ($state.scope -ne 'fresh-gnome-apps-r2-20261028' -or $state.id -ne $vm.Id.ToString()) { throw 'VM identity mismatch' }
$disks=@(Get-VMHardDiskDrive -VMName $vmName)
if ($disks.Count -ne 1 -or $disks[0].Path -ne $state.disk) { throw 'Unexpected attached disk' }
switch ($Action) {
    'chord' {
        $keyMap=@{CTRL=17;ALT=18;SHIFT=16;SUPER=91;SPACE=32;A=65;L=76;F2=113;F3=114;F4=115;ENTER=13;TAB=9;N=78;C=67;V=86;DELETE=46;ESC=27}
        $parts=$Value.Split('+')
        if ($parts.Count -lt 2 -or $parts.Count -gt 4) { throw 'Invalid key chord' }
        foreach ($part in $parts) { if (-not $keyMap.ContainsKey($part)) { throw 'Unsupported key name' } }
        $keyboard=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_Keyboard | Where-Object {$_.SystemName -eq $vm.Id.ToString()} | Select-Object -First 1
        $pressedKeys=@()
        try {
            for ($keyIndex=0; $keyIndex -lt $parts.Count-1; $keyIndex++) {
                $keyCode=[uint32]$keyMap[$parts[$keyIndex]]
                $result=Invoke-CimMethod -InputObject $keyboard -MethodName PressKey -Arguments @{keyCode=$keyCode}
                if ($result.ReturnValue -ne 0) { throw 'Modifier key failed' }
                $pressedKeys+=,$keyCode
            }
            $result=Invoke-CimMethod -InputObject $keyboard -MethodName TypeKey -Arguments @{keyCode=[uint32]$keyMap[$parts[-1]]}
            if ($result.ReturnValue -ne 0) { throw 'Key chord failed' }
        } finally {
            foreach ($keyCode in $pressedKeys) { $null=Invoke-CimMethod -InputObject $keyboard -MethodName ReleaseKey -Arguments @{keyCode=$keyCode} }
        }
    }
    'tty' {
        if ($Value -notmatch '^[1-6]$') { throw 'Expected guest VT number 1-6' }
        $keyboard=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_Keyboard | Where-Object {$_.SystemName -eq $vm.Id.ToString()} | Select-Object -First 1
        if (-not $keyboard) { throw 'VM keyboard unavailable' }
        $null=Invoke-CimMethod -InputObject $keyboard -MethodName PressKey -Arguments @{keyCode=[uint32]17}
        $null=Invoke-CimMethod -InputObject $keyboard -MethodName PressKey -Arguments @{keyCode=[uint32]18}
        try { $result=Invoke-CimMethod -InputObject $keyboard -MethodName TypeKey -Arguments @{keyCode=[uint32](111+[int]$Value)} }
        finally {
            $null=Invoke-CimMethod -InputObject $keyboard -MethodName ReleaseKey -Arguments @{keyCode=[uint32]18}
            $null=Invoke-CimMethod -InputObject $keyboard -MethodName ReleaseKey -Arguments @{keyCode=[uint32]17}
        }
        if ($result.ReturnValue -ne 0) { throw 'Guest VT key input failed' }
    }
    'boot-media' {
        if ($vm.State -ne 'Off') { throw 'Lab VM must be stopped before recovery boot selection' }
        $iso=(Resolve-Path -LiteralPath $Value).Path
        $candidateRoot='E:\dev\KIKI-OS\artifacts\gnome-native-apps-20261028\'
        if (-not $iso.StartsWith($candidateRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'ISO outside candidate' }
        $manifest=Get-Content -LiteralPath ($iso+'.sha256.json') -Raw | ConvertFrom-Json
        if ((Get-FileHash -LiteralPath $iso -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'ISO SHA mismatch' }
        Set-VMDvdDrive -VMName $vmName -Path $iso
        Set-VMFirmware -VMName $vmName -FirstBootDevice (Get-VMDvdDrive -VMName $vmName)
    }
    'media' {
        $iso=(Resolve-Path -LiteralPath $Value).Path
        $candidateRoot='E:\dev\KIKI-OS\artifacts\gnome-native-apps-20261028\'
        if (-not $iso.StartsWith($candidateRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'ISO outside candidate' }
        $manifest=Get-Content -LiteralPath ($iso+'.sha256.json') -Raw | ConvertFrom-Json
        if ((Get-FileHash -LiteralPath $iso -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'ISO SHA mismatch' }
        Set-VMDvdDrive -VMName $vmName -Path $iso
    }
    'start' { Start-VM -VMName $vmName }
    'stop' { if ($vm.State -eq 'Running') { Stop-VM -VMName $vmName -TurnOff -Confirm:$false } }
    'eject' { Set-VMDvdDrive -VMName $vmName -Path $null; Set-VMFirmware -VMName $vmName -FirstBootDevice $disks[0] }
    'status' { $vm | Format-List Name,State,Uptime,CPUUsage,MemoryAssigned }
    'text' {
        $keyboard=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_Keyboard | Where-Object {$_.SystemName -eq $vm.Id.ToString()} | Select-Object -First 1
        if (-not $keyboard) { throw 'VM keyboard unavailable' }
        foreach ($character in $Value.ToCharArray()) {
            $symbol=[string]$character
            $shift=$false
            if ($symbol -cmatch '^[a-z]$') { $code=[int][char]$symbol.ToUpperInvariant() }
            elseif ($symbol -cmatch '^[A-Z]$') { $code=[int][char]$character; $shift=$true }
            elseif ($symbol -match '^[0-9]$') { $code=[int][char]$character }
            else {
                $mapping=@{' '=32;'.'=190;'/'=191;'-'=189;'\'=220;':'=186;'_'=189;'!'=49;'@'=50;'='=187;'<'=188;'>'=190}
                if (-not $mapping.ContainsKey($symbol)) { throw "Unsupported lab input character: $symbol" }
                $code=$mapping[$symbol]; $shift=$symbol -in @(':','_','!','@','<','>')
            }
            if ($shift) { $null=Invoke-CimMethod -InputObject $keyboard -MethodName PressKey -Arguments @{keyCode=[uint32]16} }
            try { $result=Invoke-CimMethod -InputObject $keyboard -MethodName TypeKey -Arguments @{keyCode=[uint32]$code} }
            finally { if ($shift) { $null=Invoke-CimMethod -InputObject $keyboard -MethodName ReleaseKey -Arguments @{keyCode=[uint32]16} } }
            if ($result.ReturnValue -ne 0) { throw 'Virtual key input failed' }
            Start-Sleep -Milliseconds 80
        }
        Start-Sleep -Milliseconds 300
    }
    'key' {
        $keyboard=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_Keyboard | Where-Object {$_.SystemName -eq $vm.Id.ToString()} | Select-Object -First 1
        if (-not $keyboard) { throw 'VM keyboard unavailable' }
        $result=Invoke-CimMethod -InputObject $keyboard -MethodName TypeKey -Arguments @{keyCode=[uint32]$Value}
        if ($result.ReturnValue -ne 0) { throw 'TypeKey failed' }
    }
    'select-all' {
        $keyboard=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_Keyboard | Where-Object {$_.SystemName -eq $vm.Id.ToString()} | Select-Object -First 1
        if (-not $keyboard) { throw 'VM keyboard unavailable' }
        $pressed=Invoke-CimMethod -InputObject $keyboard -MethodName PressKey -Arguments @{keyCode=[uint32]17}
        try { $typed=Invoke-CimMethod -InputObject $keyboard -MethodName TypeKey -Arguments @{keyCode=[uint32]65} }
        finally { $released=Invoke-CimMethod -InputObject $keyboard -MethodName ReleaseKey -Arguments @{keyCode=[uint32]17} }
        if ($pressed.ReturnValue -ne 0 -or $typed.ReturnValue -ne 0 -or $released.ReturnValue -ne 0) { throw 'Ctrl+A failed' }
    }
    'click' {
        if ($Value -notmatch '^(\d+),(\d+)$') { throw 'Expected pixel coordinates x,y' }
        $px=[int]$Matches[1]; $py=[int]$Matches[2]
        if ($px -ge 1024 -or $py -ge 768) { throw 'Coordinates outside observed 1024x768 screen' }
        $mouse=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_SyntheticMouse | Where-Object {$_.SystemName -eq $vm.Id.ToString()} | Select-Object -First 1
        if (-not $mouse) { throw 'VM mouse unavailable' }
        $moved=Invoke-CimMethod -InputObject $mouse -MethodName SetAbsolutePosition -Arguments @{HorizontalPosition=[int32]$px;VerticalPosition=[int32]$py}
        if ($moved.ReturnValue -ne 0) { throw 'Mouse move failed' }
        $clicked=Invoke-CimMethod -InputObject $mouse -MethodName ClickButton -Arguments @{ButtonIndex=[uint32]1}
        if ($clicked.ReturnValue -ne 0) { throw 'Mouse click failed' }
        Start-Sleep -Milliseconds 500
    }
    'capture' {
        if ($Value -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid screenshot basename' }
        Start-Sleep -Milliseconds 350
        $id=$vm.Id.ToString().ToUpperInvariant()
        $setting=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_VirtualSystemSettingData | Where-Object {$_.InstanceID -eq "Microsoft:$id"}
        $service=Get-CimInstance -Namespace root/virtualization/v2 -ClassName Msvm_VirtualSystemManagementService | Select-Object -First 1
        $image=Invoke-CimMethod -InputObject $service -MethodName GetVirtualSystemThumbnailImage -Arguments @{TargetSystem=$setting;WidthPixels=[uint16]1024;HeightPixels=[uint16]768}
        if ($image.ReturnValue -ne 0 -or $image.ImageData.Length -ne 1572868) { throw 'Unexpected screenshot response' }
        Add-Type -AssemblyName System.Drawing
        $bitmap=[System.Drawing.Bitmap]::new(1024,768,[System.Drawing.Imaging.PixelFormat]::Format16bppRgb565)
        try {
            $pixels=$bitmap.LockBits([System.Drawing.Rectangle]::new(0,0,1024,768),[System.Drawing.Imaging.ImageLockMode]::WriteOnly,[System.Drawing.Imaging.PixelFormat]::Format16bppRgb565)
            try { [System.Runtime.InteropServices.Marshal]::Copy([byte[]]$image.ImageData,4,$pixels.Scan0,1572864) } finally { $bitmap.UnlockBits($pixels) }
            $bitmap.Save((Join-Path $taskRoot ($Value+'.png')),[System.Drawing.Imaging.ImageFormat]::Png)
        } finally { $bitmap.Dispose() }
        Write-Output (Join-Path $taskRoot ($Value+'.png'))
    }
}
