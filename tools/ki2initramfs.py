"""Read bounded newc records, including concatenated gzip initramfs members."""
import gzip
import hashlib
from pathlib import Path
import shutil
import stat
from pathlib import PurePosixPath


def archive(files):
    output=bytearray()
    for number,(name,(data,permissions)) in enumerate([*files.items(),('TRAILER!!!',(b'',0))],1):
        if name!='TRAILER!!!' and (PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or not name):raise ValueError('unsafe CPIO path')
        if not isinstance(data,bytes) or len(data)>8*1024**2:raise ValueError('CPIO dependency exceeds bound')
        encoded=name.encode()+b'\x00';mode=stat.S_IFREG|permissions if name!='TRAILER!!!' else 0
        fields=[number,mode,0,0,1,0,len(data),0,0,0,0,len(encoded),0]
        header=b'070701'+b''.join(f'{value:08x}'.encode() for value in fields)
        output+=header+encoded;output+=b'\x00'*((-(len(header)+len(encoded)))%4)
        output+=data;output+=b'\x00'*((-len(data))%4)
    return gzip.compress(bytes(output),mtime=0)


def append(source, destination, files):
    # Kernel initramfs supports independent concatenated gzip/newc archives.
    # Existing init, helper code, repository keys and packages stay byte-exact.
    shutil.copyfile(source,destination)
    with Path(destination).open('ab') as stream:stream.write(archive(files))


def inspect(path, wanted):
    found={}
    with gzip.open(path,'rb') as stream:
        while True:
            first=stream.read(1)
            while first==b'\x00':first=stream.read(1)
            if not first:break
            header=first+stream.read(109)
            if len(header)!=110 or header[:6] not in [b'070701',b'070702']:raise ValueError('invalid initramfs CPIO header')
            fields=[int(header[6+n*8:14+n*8],16) for n in range(13)]
            mode,size,namesize=fields[1],fields[6],fields[11]
            if not 1<=namesize<=4096 or not 0<=size<=1024**3:raise ValueError('initramfs record exceeds bounds')
            raw=stream.read(namesize)
            if len(raw)!=namesize or raw[-1:]!=b'\x00':raise ValueError('invalid CPIO filename')
            name=raw.rstrip(b'\x00').decode('utf-8');stream.read((-(110+namesize))%4)
            digest=hashlib.sha256();left=size
            while left:
                block=stream.read(min(left,1024**2))
                if not block:raise ValueError('truncated CPIO payload')
                if name in wanted:digest.update(block)
                left-=len(block)
            stream.read((-size)%4)
            if name in wanted:found[name]={'sha256':digest.hexdigest(),'bytes':size,'mode':mode}
    return found
