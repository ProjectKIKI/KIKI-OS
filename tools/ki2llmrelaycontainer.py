"""Run the loopback relay in the build worker's SELinux domain, without changing its network."""
import argparse,json,subprocess,os
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assistant',type=Path,required=True);p.add_argument('--relay',type=Path,required=True);a=p.parse_args()
    worker=json.loads(subprocess.check_output(['podman','inspect','kiki-candidate-buildd']))[0]
    level=worker['ProcessLabel'].split(':',3)[-1]
    command=['podman','run','--rm','--replace','--name','kiki-build-llm-relay','--network','host','--read-only','--memory','128m','--memory-swap','128m','--pids-limit','64','--ulimit','nofile=256:256','--cap-drop','all',
             '--security-opt','no-new-privileges','--security-opt','label=level:'+level,'--user','0:0',
             '-v',str(a.assistant)+':/relay:z','-v',str(a.relay)+':/llmrelay.py:ro,z',
             '--entrypoint','python3',worker['Image'],'/llmrelay.py','--socket','/relay/llm.sock','--port','18080']
    os.execvp(command[0],command)

if __name__=='__main__':main()
