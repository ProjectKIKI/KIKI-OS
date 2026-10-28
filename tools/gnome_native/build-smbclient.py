import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess

spec=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
root=a.work/'samba';src=next((root/'source').iterdir())
os.chdir(src)
for filename in ['et_compile_wrapper.sh','asn1_compile_wrapper.sh']:
    import tarfile
    script=src/'third_party/heimdal_build'/filename
    with tarfile.open(a.records['samba']['file']) as archive:
        member=next(m for m in archive if m.name.endswith('/third_party/heimdal_build/'+filename))
        text=archive.extractfile(member).read().decode()
    # These configure/build generators were built for the KIKI target. Execute
    # them through the matching loader rather than Rocky's older host libc.
    text=text.replace('"${CMD}" "${FILE}"', '"'+str(a.wrapper)+'" "${CMD}" "${FILE}"')
    text=text.replace('${ABS_BUILDDIR}/${CMD} ${OPTIONS}', '"'+str(a.wrapper)+'" ${ABS_BUILDDIR}/${CMD} ${OPTIONS}')
    assert str(a.wrapper) in text
    script.write_text(text)
wscript=src/'third_party/heimdal_build/wscript_build'
text=wscript.read_text()
if str(a.wrapper) not in text:
    text=text.replace(' "${ASN1_COMPILE}" ${OPTION_FILE}', ' "'+str(a.wrapper)+'" "${ASN1_COMPILE}" ${OPTION_FILE}')
    assert str(a.wrapper) in text
    wscript.write_text(text)
extra=dict(CC='gcc --sysroot='+str(a.sdk),HOSTCC='gcc',PYTHON='/usr/bin/python3',PYTHONHASHSEED='1')
options=['--prefix=/usr','--libdir=/usr/lib','--sysconfdir=/etc','--enable-fhs','--without-ad-dc','--without-ads',
         '--without-ldap','--without-pam','--without-systemd','--without-json','--without-gpgme','--without-libarchive',
         '--without-winbind','--without-ldb-lmdb','--disable-python','--hostcc=gcc','--cross-compile','--cross-execute='+str(a.wrapper)]
if not (root/'hostcc-configured').exists():
    a.run([src/'configure',*options],extra)
    (root/'hostcc-configured').touch()
a.run([src/'buildtools/bin/waf','build','--targets=smbclient','-j4'],extra)
# Bundle the new client's ELF dependency closure under a private runtime path.
# Libraries already supplied by the KIKI SDK keep their original package owner.
objects={}
for p in (src/'bin').rglob('*'):
    if p.is_file() and '.so' in p.name:
        objects.setdefault(p.name,p)
main=next(p for n,p in objects.items() if n=='libsmbclient.so.0')
dest=root/'dest';lib=dest/'usr/lib';private=lib/'samba/private';private.mkdir(parents=True,exist_ok=True)
pending=[main];seen=set()
while pending:
    p=pending.pop()
    if p.name in seen:continue
    seen.add(p.name)
    target=(lib if p==main else private)/p.name
    shutil.copy2(p.resolve(),target)
    a.run([a.tools/'patchelf','--set-rpath','$ORIGIN:$ORIGIN/samba/private' if p==main else '$ORIGIN:$ORIGIN/../..',target])
    dynamic=subprocess.check_output(['readelf','-d',str(p)],text=True)
    for name in re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic):
        if any((d/name).exists() for d in a.libdirs):continue
        if name not in objects:raise RuntimeError('Missing Samba private library '+name)
        pending.append(objects[name])
link=lib/'libsmbclient.so'
if not link.exists():link.symlink_to(main.name)
headers=dest/'usr/include/samba-4.0';headers.mkdir(parents=True,exist_ok=True)
shutil.copy2(src/'source3/include/libsmbclient.h',headers/'libsmbclient.h')
pc=lib/'pkgconfig';pc.mkdir(exist_ok=True)
(pc/'smbclient.pc').write_text('prefix=/usr\nlibdir=${prefix}/lib\nincludedir=${prefix}/include\nName: smbclient\nDescription: Samba client library\nVersion: 4.24.5\nLibs: -L${libdir} -lsmbclient\nCflags: -I${includedir}/samba-4.0\n')
a.package('smbclient','4.24.5',dest,['glibc','gnutls','libgcc'],a.records['samba'],license='GPL-3.0-or-later')
