#!/usr/bin/env python3
"""Create separately scoped fresh-install VM helpers from our isolated lab helpers."""
from pathlib import Path

repo=Path(__file__).resolve().parents[1]
ps=(repo/'tools/hyperv_session_lab.ps1').read_text()
start=ps.index("    $parentDisk=")
end=ps.index('    $vm=New-VM',start)
ps=ps[:start]+"    New-VHD -Path $disk -Dynamic -SizeBytes 32GB | Out-Null\n"+ps[end:]
ps=ps.replace('$bootDisk=Get-VMHardDiskDrive -VMName $vmName','$bootDisk=Get-VMDvdDrive -VMName $vmName')
for old,new in [('gnome50-session-vm-20261017','gnome50-install-vm-20261017'),('kiki-gnome50-session-20261017','kiki-gnome50-install-20261017'),('fresh-disposable-gnome50-session','fresh-disposable-gnome50-install')]:ps=ps.replace(old,new)
if '$parentDisk' in ps or '4fd5dc94-3796-4bb1-92da-eae7b09f302b' in ps:raise ValueError('Fresh helper retained parent-disk references')
out=repo/'tools/hyperv_gnome_install_lab.ps1'
if out.exists():raise FileExistsError(out)
out.write_text(ps)
serial=(repo/'tools/hyperv_session_serial.py').read_text()
for old,new in [('gnome50-session-vm-20261017','gnome50-install-vm-20261017'),('kiki-gnome50-session-20261017','kiki-gnome50-install-20261017'),('fresh-disposable-gnome50-session','fresh-disposable-gnome50-install')]:serial=serial.replace(old,new)
out=repo/'tools/hyperv_gnome_install_serial.py'
if out.exists():raise FileExistsError(out)
out.write_text(serial)
print('Created separate fresh empty-disk installer VM helpers; no parent or existing VM reused')
