"""Fault injection for the actual init child-input forwarding function."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import ki2bootiso


class ChrootInputTests(unittest.TestCase):
    def test_input_failures_cannot_report_success(self):
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        source = ki2bootiso.INIT_C
        begin = source.index('static int run_chroot_program_input(')
        end = source.index('\nstatic int run_chroot_program(', begin)
        harness = r'''
#include <stddef.h>
#include <setjmp.h>
#include <sys/syscall.h>
#include <unistd.h>
#define EINTR 4
static int mode, closes, writes, waits, executed, exit_code;
static jmp_buf child_exit;
static void say(const char *message) { (void)message; }
static int kclose(int fd) {
    closes++;
    return !((mode == 4 && fd == 10) || (mode == 5 && fd == 11));
}
static int write_all(int fd, const char *input) {
    (void)fd; (void)input; writes++; return mode != 3;
}
static long ksys(long op, long a, long b, long c, long d, long e, long f) {
    (void)c; (void)d; (void)e; (void)f;
    if (op == SYS_pipe) {
        if (mode == 1) return -5;
        ((int*)a)[0]=10; ((int*)a)[1]=11; return 0;
    }
    if (op == SYS_fork) return mode == 2 ? -5 : (mode == 10 ? 0 : 42);
    if (op == SYS_wait4) {
        waits++;
        if (mode == 6) return -5;
        if (mode == 9 && waits == 1) return -EINTR;
        *(int*)b = mode == 7 ? 256 : (mode == 8 ? 9 : 0);
        return 42;
    }
    if (op == SYS_dup2) return -5;
    if (op == SYS_exit) { exit_code=(int)a; longjmp(child_exit, 1); }
    if (op == SYS_execve) executed++;
    return 0;
}
'''
        harness += source[begin:end]
        harness += r'''
int main(void) {
    char *argv[] = {"test", NULL};
    for (mode=0; mode<10; mode++) {
        closes=writes=waits=0;
        int result=run_chroot_program_input("mock-root", "mock", argv, "not-a-password\n");
        if (result != ((mode == 0 || mode == 9) ? 0 : 1)) return 1;
        if (mode == 1 && (closes || writes || waits)) return 2;
        if (mode == 2 && (closes != 2 || writes || waits)) return 3;
        if (mode >= 3 && (closes != 2 || writes != 1 || waits < 1)) return 4;
        if (mode == 9 && waits != 2) return 5;
    }
    mode=0; closes=writes=waits=0;
    if (run_chroot_program_input("mock-root", "mock", argv, "")) return 6;
    if (closes || writes || waits != 1) return 7;
    mode=10; executed=exit_code=0;
    if (!setjmp(child_exit)) {
        run_chroot_program_input("mock-root", "mock", argv, "not-a-password\n");
        return 8;
    }
    if (exit_code != 126 || executed) return 9;
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='kiki-child-input-') as tmp:
            path, binary = Path(tmp) / 'probe.c', Path(tmp) / 'probe'
            path.write_text(harness)
            subprocess.run([cc, '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
