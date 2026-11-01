"""Write an install target's NetworkManager profile without changing the live host."""
import argparse
import ipaddress
from pathlib import Path
import re
import uuid


def render(*, interface, mac='', mode='dhcp', address='', gateway='', dns='', ipv6=True):
    if mode not in ('dhcp', 'static', 'disabled'):
        raise ValueError('unsupported network mode')
    # InstallPlan accepts networkd-style whitespace-separated interface globs.
    # Preserve that selection with NetworkManager's match setting as well.
    patterns=interface.split()
    if (any(c in interface for c in '\r\n\x00') or not 1<=len(patterns)<=8 or
            not all(re.fullmatch(r'[A-Za-z0-9_.:*?-]{1,15}',p) for p in patterns)):
        raise ValueError('invalid network interface')
    if mac and not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac):
        raise ValueError('invalid network MAC address')
    servers=[ipaddress.ip_address(value) for value in re.split(r'[\s,;]+',dns.strip()) if value]
    if mode=='static':
        if ipaddress.ip_interface(address).version!=4:
            raise ValueError('static address must be IPv4 with a prefix')
        if gateway and ipaddress.ip_address(gateway).version!=4:
            raise ValueError('gateway must be IPv4')
    active=mode!='disabled'
    lines=['[connection]','id=KIKI Wired',
           'uuid='+str(uuid.uuid5(uuid.NAMESPACE_URL,'kiki-wired:'+mac.lower() if mac else 'kiki-wired:'+interface)),
           'type=ethernet','autoconnect='+str(active).lower()]
    if not mac:
        if len(patterns)==1 and not any(c in patterns[0] for c in '*?'):
            lines.append('interface-name='+patterns[0])
        else:
            lines+=['','[match]','interface-name='+';'.join(patterns)+';']
    lines+=['','[ethernet]']
    if mac:lines.append('mac-address='+mac.lower())
    lines+=['','[ipv4]','method='+dict(dhcp='auto',static='manual',disabled='disabled')[mode]]
    if mode=='static':lines.append('address1='+address+(','+gateway if gateway else ''))
    for family,enabled in [(4,active),(6,active and ipv6)]:
        if family==6:lines+=['','[ipv6]','method='+('auto' if enabled else 'disabled')]
        if enabled:
            selected=[str(s) for s in servers if s.version==family]
            if selected:lines.append('dns='+';'.join(selected)+';')
            if servers:lines.append('ignore-auto-dns=true')
    return '\n'.join(lines)+'\n'


def write_target(root, *, ntp='', **options):
    root=Path(root).resolve(strict=True)
    if root==Path('/'):
        raise ValueError('refusing to configure the running host')
    text=render(**options)
    files={'etc/NetworkManager/system-connections/kiki-wired.nmconnection':(text,0o600),
           'etc/NetworkManager/conf.d/20-kiki.conf':(
               '[main]\ndns=systemd-resolved\nno-auto-default=*\n\n[connection]\nconnection.mdns=0\nconnection.llmnr=0\n',0o644)}
    if ntp:
        values=ntp.split()
        if not all(re.fullmatch(r'[A-Za-z0-9_.:-]+',v) for v in values):raise ValueError('invalid NTP server')
        files['etc/systemd/timesyncd.conf.d/20-kiki-network.conf']=('[Time]\nNTP='+' '.join(values)+'\n',0o644)
    for relative,(contents,permissions) in files.items():
        path=root/relative
        if not path.resolve().is_relative_to(root):raise ValueError('network configuration escapes target')
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.new')
        if temporary.is_symlink():raise ValueError('unsafe temporary network profile')
        temporary.write_text(contents,encoding='utf-8')
        temporary.chmod(permissions)
        temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-root',type=Path,required=True)
    parser.add_argument('--interface',required=True)
    parser.add_argument('--mode',choices=['dhcp','static','disabled'],required=True)
    for name in ['mac','address','gateway','dns','ntp']:parser.add_argument('--'+name,default='')
    parser.add_argument('--ipv6',choices=['auto','disabled'],default='auto')
    args=vars(parser.parse_args());root=args.pop('target_root');args['ipv6']=args['ipv6']=='auto'
    write_target(root,**args)


if __name__=='__main__':main()
