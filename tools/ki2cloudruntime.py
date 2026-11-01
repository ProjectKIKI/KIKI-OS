"""Rebuild installer runtime tools/helper from a hash-pinned parent ISO."""
import copy
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import shutil
import ki2initramfs


def refresh(lib,job,manifest,binaries,cpu):
    from ki2release import read,save,sha,now
    parent_id=job['values']['runtime_patch_from']
    if not re.fullmatch(r'[a-f0-9]{32}',parent_id):raise ValueError('invalid parent ISO job')
    parent=lib.job(parent_id);values=job['values']
    if parent['kind']!='iso' or parent['status']!='succeeded':raise ValueError('parent ISO must have passed build validation')
    for key in ['snapshot','profile','release_version','cpu_profile']:
        if values.get(key)!=parent['values'].get(key):raise ValueError('runtime-only rebuild cannot change pinned inputs: '+key)
    previous=parent['result'];source=lib.root/'jobs'/parent_id/previous['file'];dest=lib.root/'jobs'/job['id']
    if Path(previous['file']).name!=previous['file'] or sha(source)!=previous['sha256'] or previous['snapshot_manifest_sha256']!=sha(lib.root/'snapshots'/manifest['id']/'manifest.json'):
        raise ValueError('parent ISO/snapshot identity mismatch')
    lib.update(job,phase='이전 ISO SHA 확인 · 설치 도우미·서명된 실행 도구 보완')
    initrd=dest/'source-initramfs.img';lib.run(['xorriso','-osirrox','on','-indev',source,'-extract','/boot/initramfs-kiki.img',initrd],job)
    wanted={'init','usr/lib/kiki-installer/ki2cloudseed.py','sbin/blkid','usr/sbin/blkid'}
    before=ki2initramfs.inspect(initrd,wanted)
    helper='usr/lib/kiki-installer/ki2cloudseed.py'
    if before.get(helper,{}).get('sha256')!=previous['cloud_install_helper_sha256']:raise ValueError('parent cloud installer helper mismatch')
    record=binaries['util-linux'];package=lib.root/'snapshots'/manifest['id']/'packages'/record['file']
    if sha(package)!=record['sha256']:raise ValueError('signed runtime package changed')
    with tarfile.open(package) as tar:
        member=next(m for m in tar.getmembers() if m.name in ['rootfs/sbin/blkid','rootfs/usr/sbin/blkid'] and m.isfile())
        data=tar.extractfile(member).read();metadata=lib.repo.read_package_manifest(package)
    path=member.name[len('rootfs/'):];digest=hashlib.sha256(data).hexdigest()
    expected=next(entry for entry in metadata['files'] if entry['path'].lstrip('/')==path)
    if not data.startswith(b'\x7fELF') or digest!=expected['sha256'] or member.mode&0o111==0:raise ValueError('runtime tool payload verification failed')
    if path in before and before[path]['sha256']!=digest:raise ValueError('refusing to replace a different existing runtime tool')
    current_helper=Path(__file__).with_name('ki2cloudseed.py').read_bytes()
    helper_sha=hashlib.sha256(current_helper).hexdigest()
    updates={path:(data,member.mode&0o777)}
    if helper_sha!=previous['cloud_install_helper_sha256']:
        updates[helper]=(current_helper,0o755)
    updated=dest/'runtime-initramfs.img';ki2initramfs.append(initrd,updated,updates)
    after=ki2initramfs.inspect(updated,wanted)
    if after['init']!=before['init'] or after[helper]['sha256']!=helper_sha or after.get(path,{}).get('sha256')!=digest:raise ValueError('new initramfs validation failed')
    receipt={'schema':'kiki-installer-runtime-dependency-v1','parent_job':parent_id,'parent_iso_sha256':previous['sha256'],
             'package_file':record['file'],'package_sha256':record['sha256'],'path':'/'+path,'file_sha256':digest,
             'original_helper_sha256':previous['cloud_install_helper_sha256'],'helper_sha256':helper_sha,
             'original_initramfs_sha256':sha(initrd),'initramfs_sha256':sha(updated),'format':'concatenated gzip/newc; kernel supported'}
    save(dest/'runtime-dependency.json',receipt)
    iso_manifest=dest/'iso-manifest.json';lib.run(['xorriso','-osirrox','on','-indev',source,'-extract','/manifest.json',iso_manifest],job)
    tree=read(iso_manifest)
    if tree['package_media']['copied']!=len(binaries) or tree['package_media']['missing']:raise ValueError('parent media package inventory mismatch')
    tree.update(created_at=now(),runtime_dependency=receipt);save(iso_manifest,tree)
    filename='kiki-'+values['release_version']+'-'+values['profile']+'-'+cpu['id']+'-'+job['id'][:8]+'.iso';output=dest/filename
    # Recreate the boot records through the same GRUB builder as a full ISO.
    # Replaying old hybrid GPT records can produce overlapping EFI partitions.
    tree_dir=dest/'iso-tree';lib.run(['xorriso','-osirrox','on','-indev',source,'-extract','/',tree_dir],job)
    shutil.copyfile(updated,tree_dir/'boot/initramfs-kiki.img');shutil.copyfile(iso_manifest,tree_dir/'manifest.json')
    builder=shutil.which('grub-mkrescue') or shutil.which('grub2-mkrescue')
    if not builder:raise ValueError('GRUB ISO builder unavailable')
    lib.run([builder,'-o',output,tree_dir],job)
    check=subprocess.run(['xorriso','-indev',str(output),'-report_el_torito','plain'],capture_output=True,text=True,check=True)
    save(dest/'boot-catalog.json',{'stdout':check.stdout,'stderr':check.stderr})
    if 'BIOS' not in check.stdout+check.stderr or 'UEFI' not in check.stdout+check.stderr:raise ValueError('rebuilt ISO boot catalogue is incomplete')
    verify=dest/'verified-initramfs.img';lib.run(['xorriso','-osirrox','on','-indev',output,'-extract','/boot/initramfs-kiki.img',verify],job)
    if sha(verify)!=receipt['initramfs_sha256']:raise ValueError('ISO embedded initramfs hash mismatch')
    for filename,key in [('index.x86_64.json','index_sha256'),('metadata.x86_64.json','metadata_sha256')]:
        target=dest/('verified-'+filename);lib.run(['xorriso','-osirrox','on','-indev',output,'-extract','/kiki/repo/'+filename,target],job)
        if sha(target)!=manifest[key]:raise ValueError('rebuilt ISO changed signed repository metadata')
    result=copy.deepcopy(previous)
    for key in list(result):
        if key.startswith(('fresh_','tested_')) or key in ['configuration_scan_summary','installed_test_packages','openstack_install_report_sha256']:result.pop(key)
    result.update(file=output.name,sha256=sha(output),bytes=output.stat().st_size,cloud_install_supported=True,cloud_install_helper_sha256=helper_sha,fresh_install_tested=False,gdm_login_tested=False,
                  runtime_dependency=receipt,validation='서명 패키지·원본 설치기·추가 도구 SHA·BIOS/UEFI·내장 initramfs·저장소 메타데이터 검사 통과 · VM 설치 검증 대기')
    save(dest/'result.json',result);(dest/(output.name+'.sha256')).write_text(result['sha256']+'  '+output.name+'\n')
    return result
