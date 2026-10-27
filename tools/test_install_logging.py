"""Fault injection for GUI backend output redirection; no actual installation."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import ki2bootiso


class InstallLoggingTests(unittest.TestCase):
    def test_tui_uses_checked_log_setup_before_install(self):
        source = ki2bootiso.INIT_C
        body = source.split('static int try_fullscreen_tui_installer(', 1)[1].split('static int handoff_to_installed_system(', 1)[0]
        self.assertIn('if (!start_install_log("/run/kiki/tui-install.log", saved_console)) {', body)
        self.assertIn('remove_file(GUI_INSTALL_REQUEST_PATH);', body)
        self.assertIn('if (!restore_install_console(saved_console))', body)
        self.assertNotIn('SYS_dup2', body)
        self.assertLess(body.index('start_install_log('), body.index('load_gui_install_request('))
        self.assertIn('} else {\n                if (load_gui_install_request(&request))', body)

    def test_actual_log_is_private_and_captures_both_streams(self):
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        source = ki2bootiso.INIT_C
        begin = source.index('static int restore_install_console(')
        end = source.index('static int try_graphical_installer(', begin)
        harness = r'''
#define _GNU_SOURCE
#include <sys/syscall.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
static long ksys(long op,long a,long b,long c,long d,long e,long f) {
    long result=syscall(op,a,b,c,d,e,f); return result < 0 ? -errno : result;
}
static int kclose(int fd) { return fd < 0 || close(fd) == 0; }
static int kopen_mode(const char *path,long flags,long mode) { return open(path,flags,mode); }
'''
        harness += source[begin:end]
        harness += r'''
int main(int argc,char **argv) {
    if (argc != 2) return 1;
    umask(0);
    int saved[2];
    if (!start_install_log(argv[1],saved)) return 2;
    int written=write(1,"out\n",4)==4 && write(2,"err\n",4)==4;
    if (!restore_install_console(saved) || !written) return 3;
    struct stat st;
    if (stat(argv[1],&st) || (st.st_mode & 0777) != 0600) return 4;
    int fd=open(argv[1],O_RDONLY); char data[16];
    if (fd < 0) return 5;
    ssize_t length=read(fd,data,sizeof(data)); close(fd);
    if (length != 8 || memcmp(data,"out\nerr\n",8)) return 6;
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='kiki-real-log-') as tmp:
            path, binary = Path(tmp) / 'probe.c', Path(tmp) / 'probe'
            path.write_text(harness)
            subprocess.run([cc, '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary), str(Path(tmp) / 'backend.log')], check=True, timeout=10)

    def test_log_setup_restores_both_streams_on_failure(self):
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        source = ki2bootiso.INIT_C
        begin = source.index('static int restore_install_console(')
        end = source.index('static int try_graphical_installer(', begin)
        harness = r'''
#include <sys/syscall.h>
#include <unistd.h>
#include <fcntl.h>
static int mode, duplicate_count, streams[32], closed[32], permission;
static int kclose(int fd) {
    closed[fd]++; return !(mode == 6 && fd == 20);
}
static int kopen_mode(const char *path, long flags, long perms) {
    (void)path; (void)flags; permission=(int)perms;
    streams[20]=999; return mode == 3 ? -5 : 20;
}
static long ksys(long op, long a, long b, long c, long d, long e, long f) {
    (void)c; (void)d; (void)e; (void)f;
    if (op == SYS_dup) {
        duplicate_count++;
        if ((mode == 1 && a == 1) || (mode == 2 && a == 2)) return -5;
        streams[9+duplicate_count]=streams[a]; return 9+duplicate_count;
    }
    if (op == SYS_dup2) {
        if (a == 20 && ((mode == 4 && b == 1) || (mode == 5 && b == 2))) return -5;
        if (mode == 7 && a == 10) return -5;
        streams[b]=streams[a]; return b;
    }
    return -5;
}
'''
        harness += source[begin:end]
        harness += r'''
int main(void) {
    for (mode=0; mode<8; mode++) {
        duplicate_count=permission=0;
        for (int i=0;i<32;i++) streams[i]=closed[i]=0;
        streams[1]=101; streams[2]=202;
        int saved[2];
        int ok=start_install_log("mock", saved);
        if (ok != (mode == 0 || mode == 7)) return 1;
        if (mode >= 3 && permission != 0600) return 2;
        if (ok) {
            if (streams[1] != 999 || streams[2] != 999) return 3;
            if (restore_install_console(saved) != (mode != 7)) return 4;
        }
        if (saved[0] >= 0 || saved[1] >= 0) return 5;
        if (mode != 7 && (streams[1] != 101 || streams[2] != 202)) return 6;
        for (int i=0;i<32;i++) if (closed[i] > 1) return 7;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='kiki-log-test-') as tmp:
            path, binary = Path(tmp) / 'probe.c', Path(tmp) / 'probe'
            path.write_text(harness)
            subprocess.run([cc, '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)
        gui = source[end:source.index('static int try_fullscreen_tui_installer(', end)]
        self.assertIn('if (!logging) {\n        remove_file(GUI_INSTALL_REQUEST_PATH);', gui)
        self.assertIn('} else if (!load_gui_install_request(&request))', gui)
        self.assertLess(gui.index('start_install_log('), gui.index('run_guided_package_installer_with_request('))


if __name__ == '__main__':
    unittest.main()
