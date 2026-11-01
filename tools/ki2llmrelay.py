#!/usr/bin/env python3
"""Private Unix socket relay for an offline build worker's Local LLM client."""
import argparse,os,select,socket,socketserver,stat,signal,threading
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--socket',type=Path,required=True);p.add_argument('--port',type=int,default=18080);args=p.parse_args()
    if not 1024<=args.port<=65535:p.error('use an unprivileged loopback port')
    target=args.socket.absolute();target.parent.mkdir(parents=True,exist_ok=True);target.parent.chmod(0o700)
    if target.exists():
        if not stat.S_ISSOCK(target.lstat().st_mode):raise ValueError('refusing to replace a non-socket path')
        probe=socket.socket(socket.AF_UNIX)
        try:probe.connect(str(target))
        except OSError:target.unlink()
        else:raise ValueError('relay is already running')
        finally:probe.close()
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            remote=None
            try:
                remote=socket.create_connection(('127.0.0.1',args.port),timeout=5);self.request.settimeout(90);remote.settimeout(90)
                while True:
                    readable,_,_=select.select([self.request,remote],[],[],90)
                    if not readable:return
                    for source in readable:
                        block=source.recv(65536)
                        if not block:return
                        (remote if source is self.request else self.request).sendall(block)
            except OSError:pass
            finally:
                if remote:remote.close()
    class Server(socketserver.ThreadingUnixStreamServer):daemon_threads=True
    os.umask(0o077)
    with Server(str(target),Handler) as server:
        target.chmod(0o600);print('PRIVATE_LOCAL_LLM_RELAY_READY',flush=True)
        signal.signal(signal.SIGTERM,lambda *_:threading.Thread(target=server.shutdown,daemon=True).start())
        try:server.serve_forever()
        finally:target.unlink(missing_ok=True)


if __name__=='__main__':main()
