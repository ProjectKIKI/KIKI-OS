#!/usr/bin/env python3
"""Independently check a completed LLVM KI2 while Mesa continues compiling."""
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ki2remote_rebuild as build


def main():
    report=build.TARGET/'validation/llvm-build.json'
    if not report.exists():
        print('LLVM 패키지 생성 대기');return
    record=build.load(report);archive=Path(record['file'])
    if build.c.sha256_file(archive)!=record['sha256']:raise ValueError('완료 LLVM 패키지 SHA 불일치')
    records=build.records();records['llvm']=record;manifests={};order=[]
    def visit(name):
        if name in manifests:return
        r=records[name]
        if build.c.sha256_file(r['file'])!=r['sha256']:raise ValueError('의존 패키지 SHA 불일치: '+name)
        m=build.read_manifest(Path(r['file']));manifests[name]=m
        for dep in m['dependencies']['runtime']:visit(dep)
        order.append(name)
    visit('llvm')
    root=build.WORK/('llvm-runtime-audit-'+uuid.uuid4().hex[:8]);root.mkdir()
    for name in order:build.c.build.extract_package_rootfs(Path(records[name]['file']),root)
    subprocess.run(['chroot',str(root),'/sbin/ldconfig'],check=True)
    suppliers={Path(f['path']).name for m in manifests.values() for f in m['files'] if '.so' in Path(f['path']).name}
    needed=set()
    for f in manifests['llvm']['files']:
        p=root/f['path'].lstrip('/')
        if not p.is_file() or p.is_symlink():continue
        if build.c.sha256_file(p)!=f['sha256']:raise ValueError('LLVM 페이로드 SHA 불일치: '+f['path'])
        with p.open('rb') as stream:
            if stream.read(4)!=b'\x7fELF':continue
        dynamic=subprocess.check_output(['readelf','-d',str(p)],text=True)
        needed.update(re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic))
        for path in re.findall(r'\((?:RPATH|RUNPATH)\).*?\[(.*?)\]',dynamic):
            if any(part in path for part in ['/candidate-work','/work/','/home/','/mnt/','/tmp/','/opt/kiki-host']):raise ValueError('빌드 경로가 남은 LLVM ELF')
    if needed-suppliers:raise ValueError('LLVM ELF 의존 공급자 누락: '+str(needed-suppliers))
    binary=root/'tmp/llvm-probe';binary.parent.mkdir(exist_ok=True)
    source=next((build.WORK/'source/llvm').iterdir())/'llvm/include'
    command=['gcc','--sysroot='+str(build.c.SDK),'-I'+str(source),'-I'+str(build.WORK/'build/llvm/include'),'-O2',str(build.REPO/'tools/kiki_llvm_probe.c'),'-o',str(binary)]+build.env()['LDFLAGS'].split()+['-lLLVM']
    subprocess.run(command,env=build.env(),check=True)
    result=subprocess.run(['chroot',str(root),'/tmp/llvm-probe'],capture_output=True,text=True)
    value={'passed':result.returncode==0,'package_sha256':record['sha256'],'dependencies':order,'needed':sorted(needed),'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'scope':'독립 대상 루트에서 LLVM IR 검증과 네이티브 JIT 결과 42 확인; Mesa·VM 로그인과 별도'}
    build.save('llvm-independent-runtime.json',value);print(json.dumps(value,ensure_ascii=False,indent=2));result.check_returncode()
    if not json.loads(result.stdout)['passed']:raise ValueError('LLVM JIT 결과 불일치')


if __name__=='__main__':main()
