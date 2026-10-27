#!/usr/bin/env python3
"""Continue the current source build through clean-root checks, stopping before VM changes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

repo=Path('/mnt/e/dev/KIKI-OS')
work=Path('/home/tang/kiki-build/mesa-native-20261017')
target=repo/'dist/ki2/stage3-6.1.187-mesa-native-candidate-20261017'
parent=int(sys.argv[1])
while True:
    try:os.kill(parent,0)
    except ProcessLookupError:break
    time.sleep(5)
if not (target/'validation/llvm-build.json').exists():raise SystemExit('LLVM build exited without producing an audited package')
steps=[('mesa','ki2mesanative.py','mesa'),('root','ki2mesacandidate.py','root'),('elf','ki2mesacandidate.py','elf'),('render','ki2mesacandidate.py','probe'),('media','ki2mesacandidate.py','media')]
for name,script,action in steps:
    print('MESA_PIPELINE_START',name,flush=True)
    subprocess.run([str(work/'venv/bin/python'),'-B',str(repo/'tools'/script),action],check=True)
    print('MESA_PIPELINE_OK',name,flush=True)
print('MESA_PIPELINE_READY_FOR_VM: no VM mutation or index promotion performed',flush=True)
