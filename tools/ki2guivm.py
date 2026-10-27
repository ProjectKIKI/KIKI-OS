"""Control only a fresh disposable QEMU VM for actual installer UI acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
from ki2bootsmoke import qmp


def connect(root):
    state = json.loads((root / 'vm.json').read_text())
    if state['scope'] != 'isolated-gui-install' or Path(state['disk']).parent != root:
        raise ValueError('not an isolated GUI test')
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect(str(root / 'qmp.sock'))
    sock.recv(4096)
    qmp(sock, 'qmp_capabilities')
    return sock


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start','screen','key','text','click','status','eject','stop','record'])
    p.add_argument('--dir', type=Path, required=True)
    p.add_argument('--iso', type=Path)
    p.add_argument('--video', choices=['std','virtio','vmware'], default='std')
    p.add_argument('--value', default='')
    p.add_argument('--reviewed-completed-screen', action='store_true',
                   help='record explicit visual review, not an automatic completion detector')
    args = p.parse_args()
    root = args.dir.resolve()
    if args.action == 'record':
        if not args.reviewed_completed_screen:
            raise ValueError('completion screenshot must first be visually reviewed')
        if not args.value.replace('-','').replace('_','').isalnum():
            raise ValueError('provide screenshot basename')
        state = json.loads((root/'vm.json').read_text())
        screenshot = root / (args.value+'.ppm')
        if state['scope']!='isolated-gui-install' or Path(state['disk']).parent!=root:
            raise ValueError('not an isolated install test')
        report = {'success':True, 'iso':state['iso'], 'disk':state['disk'],
                  'scope':'actual GUI install; completion screen explicitly visually reviewed',
                  'screenshot':str(screenshot),
                  'screenshot_sha256':hashlib.sha256(screenshot.read_bytes()).hexdigest()}
        (root/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
        return
    if args.action == 'start':
        iso = args.iso.resolve(strict=True)
        if not iso.is_file(): raise ValueError('ISO must be a regular file')
        root.mkdir(parents=True, exist_ok=False)
        disk = root / 'install-test.qcow2'
        subprocess.run(['qemu-img','create','-f','qcow2',str(disk),'20G'],check=True)
        variables = root / 'OVMF_VARS.fd'
        shutil.copyfile('/usr/share/edk2/ovmf/OVMF_VARS.fd',variables)
        cmd = ['/usr/libexec/qemu-kvm','-machine','q35,accel=kvm','-cpu','host',
               '-m','2048','-smp','2','-display','none','-vga',args.video,
               '-serial',f'file:{root / "serial.log"}','-monitor','none',
               '-qmp',f'unix:{root / "qmp.sock"},server=on,wait=off',
               '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/edk2/ovmf/OVMF_CODE.fd',
               '-drive',f'if=pflash,format=raw,file={variables}',
               '-drive',f'file={disk},format=qcow2,if=none,id=osdisk',
               '-device','virtio-blk-pci,drive=osdisk,addr=0x3,bootindex=2',
               '-drive',f'file={iso},media=cdrom,readonly=on,if=none,id=installcd',
               '-device','ide-cd,drive=installcd,bootindex=1',
               '-netdev','user,id=net','-device','virtio-net-pci,netdev=net,addr=0x2',
               '-device','qemu-xhci','-device','usb-tablet']
        with (root / 'qemu.log').open('xb') as log:
            proc = subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        (root/'vm.json').write_text(json.dumps({'scope':'isolated-gui-install','pid':proc.pid,
            'iso':str(iso),'disk':str(disk),'command':cmd},indent=2)+'\n')
        time.sleep(.5)
        if proc.poll() is not None:
            raise RuntimeError('QEMU startup failed: ' + (root/'qemu.log').read_text())
        print('Started isolated VM',proc.pid)
        return
    with connect(root) as sock:
        if args.action == 'stop':
            qmp(sock,'quit'); print('Stopped isolated VM')
        elif args.action == 'status':
            print(qmp(sock,'query-status'))
        elif args.action == 'eject':
            qmp(sock,'eject',{'device':'installcd','force':True})
            print('Ejected installer ISO from isolated test VM')
        elif args.action == 'screen':
            name = args.value or 'screen'
            if not name.replace('-','').replace('_','').isalnum(): raise ValueError('invalid screenshot name')
            qmp(sock,'screendump',{'filename':str(root/(name+'.ppm'))})
            print(root/(name+'.ppm'))
        elif args.action in ('key','text'):
            keys = args.value.split() if args.action=='key' else [
                {'.':'dot','/':'slash','-':'minus','_':'shift-minus',' ':'spc',
                 '\n':'ret',':':'shift-semicolon','@':'shift-2'}.get(c,('shift-'+c.lower()) if c.isupper() else c)
                for c in args.value]
            for key in keys:
                qmp(sock,'human-monitor-command',{'command-line':'sendkey '+key})
                time.sleep(.15)
        elif args.action == 'click':
            x,y,w,h = map(int,args.value.split(','))
            events=[{'type':'abs','data':{'axis':'x','value':int(x*32767/w)}},
                    {'type':'abs','data':{'axis':'y','value':int(y*32767/h)}},
                    {'type':'btn','data':{'button':'left','down':True}}]
            qmp(sock,'input-send-event',{'events':events})
            qmp(sock,'input-send-event',{'events':[{'type':'btn','data':{'button':'left','down':False}}]})


if __name__ == '__main__':
    main()
