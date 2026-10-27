#!/usr/bin/env python3
"""Rebuild Readline against the native wide-character ncurses supplier."""
import contextlib
import io
import json
import tomli
import ki2sessioncandidate as c

raw=tomli.loads((c.TARGET/'recipes/readline.toml').read_text())['recipe'][0]
raw['release']=str(int(raw['release'])+1)
src=next((c.WORK/'build/readline/source').glob('readline-*'))
out=src.parent/'build';out.mkdir(exist_ok=True)
dest=src.parent/'dest';dest.mkdir(exist_ok=True)
log=c.TARGET/'validation/readline-rebuild.log'
options=['--prefix=/usr','--build=x86_64-pc-linux-gnu','--host=x86_64-kiki-linux-gnu','--disable-static','--enable-shared','--with-curses','--with-shared-termcap-library']
env=dict(bash_cv_termcap_lib='libncursesw',CPPFLAGS=c.environment()['CPPFLAGS']+' -I'+str(c.SDK/'usr/include/ncursesw'))
c.run([str(src/'configure')]+options,out,log,env)
c.run(['make','-j2'],out,log,env)
c.run(['make','DESTDIR='+str(dest),'install'],out,log,env)
(dest/'usr/share/info/dir').unlink(missing_ok=True)
raw['dependencies']['runtime']=sorted(set(raw['dependencies']['runtime'])|{'ncurses','glibc'})
raw['build']=dict(system='gnu',configure_options=options,env=env)
with contextlib.redirect_stdout(io.StringIO()):c.package(raw,dest,dict(source_sha256=raw['source']['sha256'],native_termcap_supplier='ncursesw',source_native_rebuild=True))
print('Readline rebuilt against native ncursesw',flush=True)
