"""Packaged XCB test with a private protocol peer; not a real X server test."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

PROBE = r'''
#include <xcb/xcb.h>
#include <xcb/xproto.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
static int transfer(int fd, void *buf, size_t n, int writing) {
    char *p=buf;
    while(n) { ssize_t r=writing?write(fd,p,n):read(fd,p,n);
        if(r<=0) return 0; p+=r; n-=r; }
    return 1;
}
static int peer(int fd) {
    unsigned char header[12];
    if(!transfer(fd,header,sizeof(header),0) || header[0]!='l' || header[2]!=11 ||
       header[6] || header[7] || header[8] || header[9]) return 1;
    xcb_setup_t setup={0};
    setup.status=1; setup.protocol_major_version=11; setup.length=8;
    setup.resource_id_base=0x200000; setup.resource_id_mask=0x1fffff;
    setup.maximum_request_length=65535;
    if(sizeof(setup)!=40 || !transfer(fd,&setup,sizeof(setup),1)) return 2;
    for(unsigned short seq=1;seq<=32;seq++) {
        unsigned char request[4];
        if(!transfer(fd,request,4,0) || request[0]!=43 || request[2]!=1 || request[3]) return 3;
        xcb_get_input_focus_reply_t reply={0};
        reply.response_type=1; reply.sequence=seq; reply.focus=seq;
        /* XCB exposes only the 12 useful bytes; X11 replies occupy 32 bytes. */
        unsigned char wire[32]={0};
        if(sizeof(reply)>sizeof(wire)) return 4;
        memcpy(wire,&reply,sizeof(reply));
        if(!transfer(fd,wire,sizeof(wire),1)) return 4;
    }
    /* Keep the server alive until the client has consumed its final reply. */
    unsigned char end;
    return read(fd,&end,1)==0 ? 0 : 5;
}
int main(void) {
    alarm(15);
    char *host=NULL; int display=-1,screen=-1;
    if(!xcb_parse_display("kiki.example:7.2",&host,&display,&screen) ||
       strcmp(host,"kiki.example") || display!=7 || screen!=2) return 1;
    free(host);
    if(xcb_parse_display("not-a-display",&host,&display,&screen)) return 2;
    int sockets[2]; if(socketpair(AF_UNIX,SOCK_STREAM,0,sockets)) return 3;
    pid_t child=fork(); if(child<0) return 4;
    if(!child) {close(sockets[0]); int code=peer(sockets[1]); close(sockets[1]); _exit(code);}
    close(sockets[1]);
    xcb_auth_info_t auth={0};
    xcb_connection_t *c=xcb_connect_to_fd(sockets[0],&auth);
    if(!c || xcb_connection_has_error(c) || xcb_get_setup(c)->protocol_major_version!=11) return 5;
    unsigned previous=xcb_generate_id(c);
    for(int i=0;i<32;i++) {
        unsigned id=xcb_generate_id(c);
        if(id==previous || (id&0xffe00000)!=0x200000) return 6;
        previous=id;
        xcb_generic_error_t *error=NULL;
        xcb_get_input_focus_cookie_t cookie=xcb_get_input_focus(c);
        xcb_get_input_focus_reply_t *reply=xcb_get_input_focus_reply(c,cookie,&error);
        if(error || !reply || reply->focus!=(unsigned)(i+1) || reply->sequence!=i+1) {
            fprintf(stderr,"reply %d: present=%d connection_error=%d\n",i+1,reply!=NULL,xcb_connection_has_error(c));
            return 7;
        }
        free(reply);
    }
    xcb_disconnect(c);
    int status; if(waitpid(child,&status,0)!=child || !WIFEXITED(status) || WEXITSTATUS(status)) return 8;
    c=xcb_connect_to_fd(-1,&auth);
    if(!c || !xcb_connection_has_error(c)) return 9;
    xcb_disconnect(c);
    return 0;
}
'''

@unittest.skipUnless(sys.platform=='linux' and os.environ.get('KIKI_TEST_XCB')=='1',
                     'set KIKI_TEST_XCB=1 on Linux as root')
class XcbRuntimeTests(unittest.TestCase):
    def test_private_protocol_peer_and_libraries(self):
        self.assertEqual(os.geteuid(),0)
        repo=Path(__file__).resolve().parents[1]
        recipes=ki2build.load_recipes(repo/'distro/recipes')
        with tempfile.TemporaryDirectory(prefix='kiki-xcb-runtime-') as tmp:
            work=Path(tmp); root=work/'root'
            for name in ki2build.dependency_closure(recipes,['libxcb','linux-headers'], 'x86_64',include_build_deps=False):
                ki2build.extract_package_rootfs(repo/'dist/ki2/packages/x86_64'/ki2build.package_filename(recipes[name],'x86_64'),root)
            def run(command):
                result=subprocess.run(command,env={'PATH':'/usr/sbin:/usr/bin:/bin','LC_ALL':'C'},
                                      capture_output=True,text=True,timeout=40)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return result.stdout
            flags=['cc','--sysroot='+str(root)]
            for sub in ('usr/lib','usr/lib64','lib','lib64'):
                path=str(root/sub); flags+=['-B'+path+'/', '-L'+path, '-Wl,-rpath-link,'+path]
            (work/'probe.c').write_text(PROBE)
            run(flags+[str(work/'probe.c'),'-lxcb','-o',str(root/'probe')])
            loaders=[p for p in root.rglob('ld-linux-x86-64.so.2') if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            base=['chroot',str(root),'/'+str(loaders[0].relative_to(root)), '--inhibit-cache',
                  '--library-path','/usr/lib:/usr/lib64:/lib:/lib64']
            libs=list((root/'usr/lib').glob('libxcb*.so'))
            self.assertGreater(len(libs),20)
            for library in libs:
                self.assertNotRegex(run(['readelf','-d',str(library)]),r'\((?:RPATH|RUNPATH)\)')
                run(base+['--list','/'+str(library.relative_to(root))])
            self.assertIn('libxcb.so.1 => /',run(base+['--list','/probe']))
            self.assertTrue((root/'usr/lib/libxcb-xkb.so.1').is_file())
            self.assertTrue((root/'usr/lib/libxcb-dri3.so.0').is_file())
            run(base+['/probe'])
            print('target XCB libraries checked:',len(libs))

if __name__=='__main__':
    unittest.main()
