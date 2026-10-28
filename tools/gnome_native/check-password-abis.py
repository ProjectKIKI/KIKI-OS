import importlib.util,json,subprocess
from pathlib import Path
s=importlib.util.spec_from_file_location('context',Path(__file__).with_name('context.py'));a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
root=a.work/'media/rootfs';source=a.work/'password-abis.c';binary=root/'tmp/password-abis'
source.write_text(r'''#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
int main(void) {
  void *one=dlopen("/usr/lib/libcrypt.so.1",RTLD_NOW|RTLD_LOCAL);
  void *two=dlopen("/usr/lib/libcrypt.so.2",RTLD_NOW|RTLD_LOCAL);
  if(!one||!two){fprintf(stderr,"%s\n",dlerror());return 1;}
  char *(*legacy)(const char*,const char*)=dlsym(one,"crypt");
  char *(*modern)(const char*,const char*)=dlsym(two,"crypt");
  if(!legacy||!modern)return 2;
  char expected[256];snprintf(expected,sizeof(expected),"%s",legacy("kiki-abi-test","$6$kiki$"));
  const char *actual=modern("kiki-abi-test","$6$kiki$");
  if(expected[0]!='$'||strcmp(expected,actual))return 3;
  if(!strcmp(expected,modern("wrong-password","$6$kiki$")))return 4;
  puts("Legacy and modern password ABIs agree; wrong password rejected");return 0;
}
''')
a.run(['gcc',*a.env['CFLAGS'].split(),source,'-o',binary,*a.env['LDFLAGS'].split(),'-ldl'])
result=subprocess.run(['/usr/sbin/chroot',str(root),'/tmp/password-abis'],capture_output=True,text=True)
report=dict(passed=result.returncode==0,code=result.returncode,stdout=result.stdout,stderr=result.stderr)
Path(__file__).with_name('password-abis.json').write_text(json.dumps(report,indent=2)+'\n')
print(report);assert report['passed']
binary.unlink()
