#!/usr/bin/env python3
"""Forward a server loopback port to the operator's existing Local LLM.

Keys and known-hosts stay on the operator PC. No public listener is requested.
"""
import argparse,json,os,select,socket,sys,threading,time
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ssh-config',type=Path,required=True)
    p.add_argument('--remote-port',type=int,default=18080);p.add_argument('--local-port',type=int,default=8080);p.add_argument('--status',type=Path)
    args=p.parse_args()
    if not all(1024<=port<=65535 for port in [args.remote_port,args.local_port]):p.error('use an unprivileged port')
    cfg=json.loads(args.ssh_config.read_text(encoding='utf-8-sig'))
    if cfg.get('ssh_library'):sys.path.insert(0,cfg['ssh_library'])
    import paramiko
    slots=threading.BoundedSemaphore(4)
    def status(connected,error=''):
        if args.status:
            data=dict(schema='kiki-llm-bridge-v1',pid=os.getpid(),connected=connected,remote_port=args.remote_port,local_port=args.local_port,error=error,at=time.time())
            args.status.parent.mkdir(parents=True,exist_ok=True);temp=args.status.with_suffix('.pending');temp.write_text(json.dumps(data)+'\n');temp.replace(args.status)
    def relay(channel):
        if not slots.acquire(blocking=False):channel.close();return
        connection=None
        try:
            connection=socket.create_connection(('127.0.0.1',args.local_port),timeout=5)
            last=time.monotonic()
            while time.monotonic()-last<120:
                readable,_,_=select.select([channel,connection],[],[],2)
                for source in readable:
                    chunk=source.recv(65536)
                    if not chunk:return
                    (connection if source is channel else channel).sendall(chunk);last=time.monotonic()
        except (OSError,EOFError):pass
        finally:
            channel.close()
            if connection:connection.close()
            slots.release()
    while True:
        client=paramiko.SSHClient();client.load_host_keys(cfg['server_known_hosts']);client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(cfg['server_host'],port=cfg['server_port'],username=cfg['server_user'],key_filename=cfg['server_key'],allow_agent=False,look_for_keys=False,timeout=15)
            transport=client.get_transport();transport.set_keepalive(20);transport.request_port_forward('127.0.0.1',args.remote_port)
            _,out,_=client.exec_command('ss -H -lnt "sport = :'+str(args.remote_port)+'"',timeout=10)
            addresses=[line.split()[3] for line in out.read().decode().splitlines() if len(line.split())>=5]
            if not addresses or any(address!='127.0.0.1:'+str(args.remote_port) for address in addresses):
                transport.cancel_port_forward('127.0.0.1',args.remote_port);raise ValueError('loopback listener verification failed')
            status(True);print('LOCAL_LLM_LOOPBACK_BRIDGE_CONNECTED',flush=True)
            while transport.is_active():
                channel=transport.accept(2)
                if channel:threading.Thread(target=relay,args=(channel,),daemon=True).start()
        except KeyboardInterrupt:break
        except Exception as error:status(False,type(error).__name__);print('LOCAL_LLM_BRIDGE_RETRY',type(error).__name__,flush=True)
        finally:client.close()
        time.sleep(10)
    status(False,'stopped')


if __name__=='__main__':main()
