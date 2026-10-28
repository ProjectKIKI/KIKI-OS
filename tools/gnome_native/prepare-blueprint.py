import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'))
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
source=next((a.work/'blueprint-compiler/source').iterdir())
tools=a.work/'host-tools';tools.mkdir(exist_ok=True)
program=tools/'blueprint-compiler.py'
text=(source/'blueprint-compiler.py').read_text()
for key,value in [('VERSION','0.20.4'),('MODULE_PATH',str(source)),('LIBDIR',str(a.sdk/'usr/lib')),('DATADIR',str(a.sdk/'usr/share'))]:
    text=text.replace('@'+key+'@',value)
program.write_text(text)
launcher=tools/'blueprint-compiler'
launcher.write_text('#!/bin/sh\nexport PYTHONHOME='+str(a.sdk/'usr')+'\nexport GI_TYPELIB_PATH='+str(a.sdk/'usr/lib/girepository-1.0')+'\nexec '+str(a.sdk/'lib64/ld-linux-x86-64.so.2')+' --library-path '+':'.join(map(str,a.libdirs))+' '+str(a.sdk/'usr/bin/python3')+' '+str(program)+' "$@"\n')
launcher.chmod(0o755)
a.run([launcher,'--version'])
