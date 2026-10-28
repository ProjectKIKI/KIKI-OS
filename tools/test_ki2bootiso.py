import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import ki2bootiso


class Ki2BootIsoTests(unittest.TestCase):
    def test_installed_handoff_moves_root_before_exec_and_stops_on_failure(self):
        gcc=shutil.which('gcc')
        if not gcc:self.skipTest('gcc required')
        source=ki2bootiso.INIT_C
        start=source.index('static int handoff_to_installed_system(void)')
        end=source.index('static void installer_cli_menu(',start)
        harness=r'''
#include <assert.h>
#include <string.h>
#define SYS_chdir 80
#define SYS_chroot 161
#define SYS_mount 165
#define SYS_execve 59
#define MS_MOVE 8192
#define MS_REC 16384
#define MS_PRIVATE (1UL << 18)
static int phase, execs, chroots, fail_move, fail_api;
static int cmdline_value(const char *k,char *v,unsigned long n) { (void)k;(void)n;strcpy(v,"/dev/sda3");return 1; }
static void say(const char *s) { (void)s; }
static void mkdir_p(const char *s,long mode) { (void)s;(void)mode; }
static int file_exists(const char *s) { (void)s;return 1; }
static int mount_one(const char *a,const char *b,const char *c,long d,const char *e) {
 (void)a;(void)b;(void)c;(void)d;(void)e;return !fail_api;
}
static long ksys(long n,long a,long b,long c,long d,long e,long f) {
 (void)c;(void)e;(void)f;
 if(n==SYS_chdir && !strcmp((char*)a,"/sysroot")) { assert(phase==0);phase=1; }
 if(n==SYS_mount && d==(MS_REC|MS_PRIVATE)) { assert(phase==1);phase=2; }
 if(n==SYS_mount && d==MS_MOVE) { assert(phase==2);assert(!strcmp((char*)a,"."));assert(!strcmp((char*)b,"/"));if(fail_move)return -1;phase=3; }
 if(n==SYS_chroot) { assert(phase==3);assert(!strcmp((char*)a,"."));chroots++;phase=4; }
 if(n==SYS_chdir && !strcmp((char*)a,"/")) { assert(phase==4);phase=5; }
 if(n==SYS_execve) { assert(phase==5);execs++;return -1; }
 return 0;
}
'''
        main=r'''
int main(void) {
 handoff_to_installed_system();assert(phase==5 && execs==2 && chroots==1);
 phase=execs=chroots=0;fail_move=1;
 handoff_to_installed_system();assert(phase==2 && !execs && !chroots);
 phase=execs=chroots=0;fail_move=0;fail_api=1;
 handoff_to_installed_system();assert(!phase && !execs && !chroots);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            code,binary=Path(tmp)/'handoff.c',Path(tmp)/'handoff'
            code.write_text(harness+source[start:end]+main)
            subprocess.run([gcc,'-Wall','-Wextra','-Werror',str(code),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

    def test_gnome_preparation_mount_cleanup_and_service_activation(self):
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc required")
        start = ki2bootiso.INIT_C.index("static int prepare_gnome_target(void)")
        end = ki2bootiso.INIT_C.index("static int enable_default_systemd_units", start)
        harness = r'''
#include <assert.h>
#include <string.h>
#define SYS_umount2 166
static int selected, files, fail_mount, helper_status, mounts, unmounts, links, removals;
static int selected_index(const char *s) { (void)s; return selected ? 0 : -1; }
static int file_exists(const char *s) { (void)s; return files; }
static void say(const char *s) { (void)s; }
static int mount_one(const char *f,const char *p,const char *s,long flags,const char *d) {
 (void)f;(void)p;(void)s;(void)flags;(void)d; mounts++; return mounts != fail_mount;
}
static long ksys(long n,long a,long b,long c,long d,long e,long f) {
 (void)a;(void)b;(void)c;(void)d;(void)e;(void)f; assert(n==SYS_umount2); unmounts++; return 0;
}
static int run_chroot_program(const char *root,const char *path,char **argv) {
 assert(strcmp(root,"/mnt/target")==0);
 assert(strcmp(path,"/usr/libexec/kiki-desktop-prepare")==0);
 assert(argv[1]==0); return helper_status;
}
static void remove_file(const char *s) { assert(strstr(s,"/mnt/target/etc/systemd/system/")); removals++; }
static int required_unit_symlink(const char *s,const char *d) {
 assert(strstr(s,"graphical.target") || strstr(s,"gdm.service"));
 assert(strstr(d,"default.target") || strstr(d,"display-manager.service")); links++; return 1;
}
'''
        main = r'''
int main(void) {
 assert(prepare_gnome_target()==1 && mounts==0);
 selected=1; assert(prepare_gnome_target()==0 && mounts==0);
 files=1;
 for(int failure=1;failure<=3;failure++) {
  fail_mount=failure; mounts=unmounts=0;
  assert(prepare_gnome_target()==0); assert(unmounts==failure-1); assert(links==0);
 }
 fail_mount=0; mounts=unmounts=0; helper_status=1;
 assert(prepare_gnome_target()==0 && unmounts==3 && links==0);
 mounts=unmounts=0; helper_status=0;
 assert(prepare_gnome_target()==1 && unmounts==3 && links==2 && removals==4);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source, binary = Path(tmp) / "gnome.c", Path(tmp) / "gnome"
            source.write_text(harness + ki2bootiso.INIT_C[start:end] + main)
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_profile_media_validation_and_dependency_closure(self):
        import ki2installcatalog
        data = ki2installcatalog.load()
        roots = ki2installcatalog.expand(data, ['server'])['packages']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [{'name': n, 'size': 1, 'dependencies': {'runtime': []}} for n in roots]
            index = root / 'index.x86_64.json'
            index.write_text(json.dumps({'packages': entries}))
            result = ki2bootiso.verify_installer_default_packages(root, 'x86_64', 'server-core')
            server = next(p for p in result['profiles'] if p['id'] == 'server-core')
            self.assertTrue(server['available'])
            self.assertEqual(server['ai_default'], 'off')
            # A broken required runtime dependency must still block ISO creation.
            entries[0]['dependencies']['runtime'] = ['missing-required-library']
            index.write_text(json.dumps({'packages': entries}))
            with self.assertRaisesRegex(ki2bootiso.BootIsoError, 'missing-required-library'):
                ki2bootiso.verify_installer_default_packages(root, 'x86_64')
            roots = ki2installcatalog.expand(data, ['desktop-gnome'])['packages']
            entries = [{'name': n, 'size': 1, 'dependencies': {'runtime': []}} for n in roots]
            index.write_text(json.dumps({'packages': entries}))
            result = ki2bootiso.verify_installer_default_packages(root, 'x86_64', 'desktop-gnome')
            self.assertEqual(result['default_profile'], 'desktop-gnome')

    def test_rejects_stale_gui_title_in_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "installer.ki2"
            def write_binary(data):
                with tarfile.open(package, "w:gz") as archive:
                    member = tarfile.TarInfo("rootfs/usr/bin/kiki-installer-gtk")
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            write_binary(b"KIKI OS Installer Go/GTK4")
            with self.assertRaisesRegex(ki2bootiso.BootIsoError, "old installer name"):
                ki2bootiso.verify_installer_display_name(package)
            write_binary(b"KIKI OS Scratch Pad")
            ki2bootiso.verify_installer_display_name(package)
            write_binary(b"KIKI_INSTALLER_UI_V2 KIKI OS Installer")
            ki2bootiso.verify_installer_display_name(package)
            for stale in (b"KIKI OS Installer", b"KIKI_INSTALLER_UI_V2", b"KIKI_INSTALLER_UI_V2 KIKI OS Installer Scratch Pad"):
                write_binary(stale)
                with self.assertRaises(ki2bootiso.BootIsoError):
                    ki2bootiso.verify_installer_display_name(package)

    def test_gui_request_is_wiped_before_completion_wait(self):
        source = ki2bootiso.INIT_C
        start = source.index('say("GTK requested installation;')
        end = source.index('static int try_fullscreen_tui_installer(', start)
        body = source[start:end]
        wipe = 'for (size_t i = 0; i < sizeof(request); i++) ((volatile char *)&request)[i] = 0;'
        self.assertEqual(body.count(wipe), 1)
        self.assertLess(body.index('run_guided_package_installer_with_request(0, 0, &request)'), body.index(wipe))
        self.assertLess(body.index(wipe), body.index('for (;;)'))
        # The wipe must be outside both the failed-parse and successful-parse branches.
        self.assertIn('    if (logging && !restore_install_console(saved_console))', body)

    def test_request_reader_requires_complete_nul_free_text(self):
        gcc = shutil.which('gcc')
        if not gcc:
            self.skipTest('gcc is required')
        source = ki2bootiso.INIT_C
        start = source.index('static int read_install_request_text(')
        end = source.index('\n}\n', start) + 3
        harness = r'''
#include <stddef.h>
#include <string.h>
#define O_RDONLY 0
#define ksys(op,fd,dst,n,a,b,c) fake_read((char *)(dst), (size_t)(n))
static const char *input;
static size_t length, position;
static int mode, calls, closed;
static int kopen(const char *path, long flags) { (void)path; (void)flags; return mode == 1 ? -1 : 3; }
static int kclose(int fd) { if (fd >= 0) closed++; return mode != 2; }
static long fake_read(char *out, size_t size) {
    calls++;
    if (mode == 3 && calls == 1) return -4;
    if (mode == 4 && calls == 2) return -5;
    size_t count = length - position;
    if (count > size) count = size;
    if (count > 3) count = 3;
    memcpy(out, input + position, count);
    position += count;
    return (long)count;
}
'''
        harness += source[start:end]
        harness += r'''
static int run(const char *data, size_t len, int failure, int expected) {
    char buffer[8]; memset(buffer, 'X', sizeof(buffer));
    input=data; length=len; position=0; mode=failure; calls=closed=0;
    if (read_install_request_text("mock", buffer, sizeof(buffer)) != expected) return 1;
    if (closed != (failure == 1 ? 0 : 1)) return 2;
    if (expected) {
        if (memcmp(buffer, data, len) || buffer[len]) return 3;
    } else {
        for (size_t i=0; i<sizeof(buffer); i++) if (buffer[i]) return 4;
    }
    return 0;
}
int main(void) {
    if (run("abcdefg",7,0,1)) return 1;
    if (run("abcdefg",7,3,1)) return 2;
    if (run("abcdefgh",8,0,0)) return 3;
    if (run("abcdefghijk",11,0,0)) return 4;
    if (run("abc\0def",7,0,0)) return 5;
    if (run("",0,0,0)) return 6;
    if (run("abcdefg",7,1,0)) return 7;
    if (run("abcdefg",7,2,0)) return 8;
    if (run("abcdefg",7,4,0)) return 9;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / 'reader.c', Path(tmp) / 'reader'
            path.write_text(harness)
            subprocess.run([gcc, '-Wall', '-Wextra', '-Werror', str(path), '-o', str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)
        body = source.split('static int load_gui_install_request(', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('read_install_request_text(GUI_INSTALL_REQUEST_PATH', body)
        self.assertIn('request_fd < 0 || !kclose(request_fd)', body)
        self.assertIn('((volatile char *)request)[i] = 0;', body)

    def test_request_fields_reject_truncation_and_duplicates(self):
        source = ki2bootiso.INIT_C
        body = source.split("static int load_gui_install_request(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if (!fields_valid ||", body)
        self.assertIn("request->package_count >= MAX_SELECTED_PACKAGES", body)
        self.assertNotRegex(body, r"(?m)^    request_value\(buffer,")
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is required")
        start = source.index("static int request_value(")
        end = source.index("\n}\n", start) + 3
        harness = '#include <string.h>\nstatic size_t kstrlen(const char *s) { return strlen(s); }\n'
        harness += source[start:end]
        harness += r'''
int main(void) {
    char out[5];
    if (request_value("disk=abcd\n", "disk", out, sizeof(out)) != 1 || strcmp(out, "abcd")) return 1;
    if (request_value("disk=abcde\n", "disk", out, sizeof(out)) != -1 || out[0]) return 2;
    if (request_value("disk=a\ndisk=b\n", "disk", out, sizeof(out)) != -1 || out[0]) return 3;
    if (request_value("disk=a\r\ndisk=a\n", "disk", out, sizeof(out)) != -1) return 4;
    if (request_value("disk=\n", "disk", out, sizeof(out)) != 1 || out[0]) return 5;
    if (request_value("other=a\n", "disk", out, sizeof(out)) != 0 || out[0]) return 6;
    if (request_value("disk=a\n", "disk", out, 0) != -1) return 7;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "request.c", Path(tmp) / "request"
            path.write_text(harness, encoding="utf-8")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(path), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)

    def test_gsettings_cache_failure_blocks_install_success(self):
        source = ki2bootiso.INIT_C
        guided = source.split("static void run_guided_package_installer_with_request", 1)[1]
        self.assertLess(guided.index('if (!refresh_target_gsettings_cache("/mnt/target")) goto target_configuration_failed;'),
                        guided.index('say("\\nGuided install finished.'))
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is required")
        start = source.index("static int refresh_target_gsettings_cache(")
        end = source.index("\n}\n", start) + 3
        harness = r'''
#include <stddef.h>
#include <string.h>
static int result;
static void say(const char *s) { (void)s; }
static int run_chroot_program(const char *root, const char *program, char **argv) {
    if (strcmp(root, "/mnt/target") || strcmp(program, "/bin/sh") ||
        !strstr(argv[2], "exec /usr/bin/glib-compile-schemas --strict")) return 1;
    return result;
}
'''
        harness += source[start:end]
        harness += r'''
int main(void) {
    for (result = 0; result < 128; result++) {
        if (refresh_target_gsettings_cache("/mnt/target") != (result == 0)) return 1;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "schemas.c", Path(tmp) / "schemas"
            path.write_text(harness, encoding="utf-8")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(path), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)

    def test_timezone_replacement_and_failure_preserve_existing_link(self):
        if os.name != "posix" or not shutil.which("ln"):
            self.skipTest("POSIX shell and ln required")
        body = ki2bootiso.INIT_C.split("static int write_target_localization_and_ai(void)", 1)[1]
        line = re.search(r'"test -f .*ln -sfnT .*"', body).group(0)
        script = json.loads(line)
        self.assertIn('if (run_chroot_program("/mnt/target", "/bin/sh", argv) != 0)', body)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link, zone, old, empty = (root / n for n in ("localtime", "Seoul", "UTC", "empty"))
            zone.write_bytes(b"TZif-test-new")
            old.write_bytes(b"TZif-test-old")
            empty.touch()
            # Exercise the exact script with only its destination relocated; no host /etc changes.
            script = script.replace("/etc/localtime", '"$2"')
            def run(target):
                return subprocess.run(["/bin/sh", "-c", script, "kiki-set-timezone", str(target), str(link)],
                                      capture_output=True, timeout=10).returncode
            link.symlink_to(old)
            self.assertEqual(run(zone), 0)
            self.assertEqual(os.readlink(link), str(zone))
            for unavailable in (root / "absent", empty):
                self.assertNotEqual(run(unavailable), 0)
                self.assertEqual(os.readlink(link), str(zone))
            link.unlink()
            link.mkdir()
            self.assertNotEqual(run(zone), 0)
            self.assertEqual(list(link.iterdir()), [])
        sudo = ki2bootiso.INIT_C.split("static int write_target_sudoers(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('return write_text_file_mode(path, "%sudo ALL=(ALL:ALL) ALL\\n", 0440);', sudo)

    def test_file_write_and_copy_errors_are_not_success(self):
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is required")
        source = ki2bootiso.INIT_C
        harness = r'''
#include <stddef.h>
#include <string.h>
#define SYS_write 1
#define SYS_open 2
#define SYS_close 3
#define SYS_fsync 4
#define SYS_chmod 5
#define SYS_read 6
#define EINTR 4
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 2
#define O_TRUNC 4
#define O_APPEND 8
static int fault, closed, nextfd, readcalls, writecalls, syncalls, interrupts;
static char copy_buffer[8];
static size_t kstrlen(const char *s) { return strlen(s); }
static void say(const char *s) { (void)s; }
static long ksys(long nr, long a, long b, long c, long d, long e, long f) {
    (void)a; (void)d; (void)e; (void)f;
    if (nr == SYS_open) return fault == 1 ? -13 : ++nextfd;
    if (nr == SYS_write) {
        writecalls++;
        if (interrupts && writecalls == 1) return -EINTR;
        if (fault == 2) return -28;
        if (fault == 7) return 0;
        return c > 2 ? 2 : c;
    }
    if (nr == SYS_fsync) {
        syncalls++;
        if (interrupts && syncalls == 1) return -EINTR;
        return fault == 3 ? -5 : 0;
    }
    if (nr == SYS_close) { closed++; return fault == 4 ? -5 : 0; }
    if (nr == SYS_chmod) return fault == 5 ? -1 : 0;
    if (nr == SYS_read) {
        readcalls++;
        if (interrupts && readcalls == 1) return -EINTR;
        if (fault == 6) return -5;
        if (readcalls == 1 + interrupts) { memcpy((void *)b, "abc", 3); return 3; }
        return 0;
    }
    return -1;
}
static void reset(int injected, int interrupted) {
    fault = injected; interrupts = interrupted; closed = 0; nextfd = 2;
    readcalls = 0; writecalls = 0; syncalls = 0;
}
'''
        harness += source[source.index("static int write_bytes("):source.index("static void say(")]
        for name in ("write_text_file", "write_text_file_mode", "append_text_file_mode", "copy_file"):
            start = source.index(f"static int {name}(")
            end = source.index("\n}\n", start) + 3
            harness += source[start:end]
        harness += r'''
int main(void) {
    for (int interrupted = 0; interrupted < 2; interrupted++) {
        for (int injected = 0; injected <= 7; injected++) {
            for (int operation = 0; operation < 4; operation++) {
                reset(injected, interrupted);
                int result;
                if (operation == 0) result = write_text_file("/test", "abcdef");
                else if (operation == 1) result = write_text_file_mode("/test", "abcdef", 0600);
                else if (operation == 2) result = append_text_file_mode("/test", "abcdef", 0600);
                else result = copy_file("/source", "/dest");
                int expected = injected == 0 || (injected == 6 && operation != 3) ||
                    (injected == 5 && (operation == 0 || operation == 3));
                if (result != expected) return 10 + operation;
                if (closed != (injected == 1 ? 0 : operation == 3 ? 2 : 1)) return 20 + operation;
                if (expected && writecalls < 2) return 30;
            }
        }
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "writes.c", Path(tmp) / "writes"
            path.write_text(harness, encoding="utf-8")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(path), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)

    def test_all_required_unit_failures_propagate_for_each_mode(self):
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is required")
        source = ki2bootiso.INIT_C
        start = source.index("static int enable_default_systemd_units(void)")
        end = source.index("static int enable_catalog_group_units(", start)
        harness = r'''
#include <string.h>
static const char *selected_ai_mode;
static int containerd, calls, failure;
static int kstrcmp(const char *a, const char *b) { return strcmp(a, b); }
static int selected_runtime_is_containerd(void) { return containerd; }
static void mkdir_p(const char *p, long mode) { (void)p; (void)mode; }
static int required_unit_symlink(const char *target, const char *link) {
    (void)target; (void)link;
    return ++calls != failure;
}
'''
        harness += source[start:end]
        harness += r'''
int main(void) {
    const char *modes[] = {"off", "local", "remote"};
    for (int mode = 0; mode < 3; mode++) {
        selected_ai_mode = modes[mode]; failure = 0; calls = 0;
        if (!enable_default_systemd_units()) return 1;
        int count = calls;
        if (count < 10) return 2;
        for (failure = 1; failure <= count; failure++) {
            calls = 0;
            if (enable_default_systemd_units() || calls != count) return 3;
        }
    }
    for (containerd = 0; containerd < 2; containerd++) {
        calls = 0; failure = 0;
        if (!enable_kubernetes_systemd_units() || calls != 3) return 4;
        for (failure = 1; failure <= 3; failure++) {
            calls = 0;
            if (enable_kubernetes_systemd_units() || calls != 3) return 5;
        }
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "enable.c", Path(tmp) / "enable"
            path.write_text(harness, encoding="utf-8")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(path), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)

    def test_required_service_link_failures_block_success(self):
        source = ki2bootiso.INIT_C
        guided = source.split("static void run_guided_package_installer_with_request", 1)[1]
        success = guided.index('say("\\nGuided install finished.')
        for function in ("enable_default_systemd_units", "enable_kubernetes_systemd_units"):
            self.assertLess(guided.index(f"if (!{function}()) goto target_configuration_failed;"), success)
            body = source.split(f"static int {function}(void) {{", 1)[1].split("\n}\n", 1)[0]
            self.assertNotIn("\n    make_symlink(", body)
            self.assertIn("return ok;", body)
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is required for syscall failure injection")
        start = source.index("static int same_unit_link(")
        end = source.index("\n}\n", source.index("static int required_unit_symlink(")) + 3
        harness = r'''
#include <string.h>
#define SYS_symlink 88
#define SYS_readlink 89
static long create_result, read_result;
static const char *existing;
static int reads, unavailable, creates;
static int run_chroot_program(const char *root, const char *program, char **argv) {
    if (strcmp(root, "/mnt/target") || strcmp(program, "/bin/sh") ||
        strcmp(argv[2], "test -f \"$1\" && test -s \"$1\" && test -r \"$1\"")) return 1;
    return unavailable;
}
static int kstrcmp(const char *a, const char *b) { return strcmp(a, b); }
static int starts_with(const char *a, const char *b) { return strncmp(a, b, strlen(b)) == 0; }
static void say(const char *text) { (void)text; }
static long ksys(long nr, long a, long b, long c, long d, long e, long f) {
    (void)a; (void)c; (void)d; (void)e; (void)f;
    if (nr == SYS_symlink) { creates++; return create_result; }
    reads++;
    if (read_result > 0) memcpy((void *)b, existing, (size_t)read_result);
    return read_result;
}
'''
        harness += source[start:end]
        harness += r'''
int main(void) {
    const char *target = "/usr/lib/systemd/system/dbus.service";
    const char *link = "/mnt/target/etc/systemd/system/basic.target.wants/dbus.service";
    if (!same_unit_link(target, link, "../../../../usr/lib/systemd/system/dbus.service")) return 7;
    if (same_unit_link(target, link, "../../../../../usr/lib/systemd/system/dbus.service")) return 8;
    if (!same_unit_link("/etc/systemd/system/sshd.service",
        "/mnt/target/etc/systemd/system/multi-user.target.wants/sshd.service", "../sshd.service")) return 9;
    create_result = 0;
    if (!required_unit_symlink(target, "/test") || reads) return 1;
    create_result = -17; existing = target; read_result = (long)strlen(target);
    if (!required_unit_symlink(target, "/test") || reads != 1) return 2;
    existing = "/wrong"; read_result = 6;
    if (required_unit_symlink(target, "/test")) return 3;
    read_result = -22;
    if (required_unit_symlink(target, "/test")) return 4;
    create_result = -28; reads = 0;
    if (required_unit_symlink(target, "/test") || reads) return 5;
    create_result = -13;
    if (required_unit_symlink(target, "/test") || reads) return 6;
    unavailable = 1; creates = 0;
    if (required_unit_symlink(target, "/test") || creates) return 10;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "units.c", Path(tmp) / "units"
            path.write_text(harness, encoding="utf-8")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(path), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)

    def test_generated_installed_boot_config_passes_grub_parser(self):
        gcc = shutil.which('gcc')
        checker = shutil.which('grub2-script-check') or shutil.which('grub-script-check')
        if not gcc or not checker:
            self.skipTest('gcc and GRUB script checker are required')
        source = ki2bootiso.INIT_C
        harness = r'''
#include <stdio.h>
#include <string.h>
static void path3(char *out, size_t size, const char *a, const char *b, const char *c) {
    snprintf(out, size, "%s%s%s", a, b, c);
}
static void mkdir_p(const char *path, long mode) { (void)path; (void)mode; }
static int write_text_file(const char *path, const char *text) {
    if (strcmp(path, "/esp/boot/grub/kiki-installed.cfg")) return 0;
    return fputs(text, stdout) >= 0;
}
'''
        for name in ('static size_t append_string(', 'static int write_installed_boot_config('):
            start = source.index(name)
            end = source.index('\n}\n', start) + 3
            harness += source[start:end]
        harness += '\nint main(void) { return !write_installed_boot_config("/esp", "/dev/sda3"); }\n'
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / 'config.c', Path(tmp) / 'config'
            path.write_text(harness)
            subprocess.run([gcc, '-Wall', '-Wextra', '-Werror', str(path), '-o', str(output)], check=True)
            config = subprocess.check_output([str(output)], text=True, timeout=10)
            subprocess.run([checker], input=config, text=True, check=True, timeout=10)
        self.assertEqual(config.count('menuentry '), 2)
        self.assertIn('root=/dev/sda3 rw init=/init kiki.boot=installed', config)
        self.assertIn('set theme=/boot/grub/kiki/theme.txt', config)
        self.assertIn('terminal_output console', config)

    def test_installed_boot_branding_copy_failures_propagate(self):
        source = ki2bootiso.INIT_C
        config = source.split('static int write_installed_boot_config(', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('set theme=/boot/grub/kiki/theme.txt', config)
        self.assertIn('if insmod gfxmenu; then', config)
        self.assertIn('terminal_output console', config)
        install = source.split('static int install_uefi_boot_files(', 1)[1].split('\n}\n', 1)[0]
        self.assertIn('if (!install_target_boot_branding(media_root, esp_root))', install)
        gcc = shutil.which('gcc')
        if not gcc:
            self.skipTest('gcc is required')
        start = source.index('static int install_target_boot_branding(')
        end = source.index('\n}\n', start) + 3
        harness = r'''
#include <stdio.h>
#include <string.h>
static int mask, failure, calls, bad_path;
static void path3(char *out, size_t size, const char *a, const char *b, const char *c) {
    snprintf(out, size, "%s%s%s", a, b, c);
}
static int file_exists(const char *path) {
    if (!strcmp(path, "/media/boot/grub/kiki/theme.txt")) return mask & 1;
    if (!strcmp(path, "/media/boot/grub/kiki/logo.png")) return mask & 2;
    if (!strcmp(path, "/media/boot/grub/kiki/background.png")) return mask & 4;
    bad_path = 1; return 0;
}
static void mkdir_p(const char *path, long mode) {
    if (strcmp(path, "/esp/boot/grub/kiki") || mode != 0755) bad_path = 1;
}
static int copy_file(const char *src, const char *dst) {
    calls++;
    const char *name = calls == 1 ? "logo.png" : (mask & 4 && calls == 2 ? "background.png" : "theme.txt");
    char expected[128];
    snprintf(expected, sizeof(expected), "/media/boot/grub/kiki/%s", name);
    if (strcmp(src, expected)) bad_path = 1;
    snprintf(expected, sizeof(expected), "/esp/boot/grub/kiki/%s", name);
    if (strcmp(dst, expected)) bad_path = 1;
    return calls != failure;
}
'''
        harness += source[start:end]
        harness += r'''
int main(void) {
    for (mask = 0; mask < 8; mask++) {
        for (failure = 0; failure < 4; failure++) {
            calls = bad_path = 0;
            int count = mask & 4 ? 3 : 2;
            int expected = !(mask & 3) || ((mask & 3) == 3 && (failure == 0 || failure > count));
            if (install_target_boot_branding("/media", "/esp") != expected) return 1;
            if (bad_path) return 2;
            if (calls != ((mask & 3) == 3 ? (failure > 0 && failure < count ? failure : count) : 0)) return 3;
        }
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / 'branding.c', Path(tmp) / 'branding'
            path.write_text(harness)
            subprocess.run([gcc, '-Wall', '-Wextra', '-Werror', str(path), '-o', str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)

    def test_boot_branding_preserves_original_and_records_hashes(self):
        source = Path(__file__).resolve().parents[1] / "assets/brand"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = ki2bootiso.install_boot_branding(source, target)
            original = (source / "kikios-kiki-wordmark-boot-v2.png").read_bytes()
            self.assertEqual((target / result["logo"]).read_bytes(), original)
            self.assertEqual(result["logo_sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual((target / result["theme"]).read_bytes(), (source / "grub-theme.txt").read_bytes())
            self.assertEqual((target / result["background"]).read_bytes(), (source / "grub-background-v2.png").read_bytes())
        config = ki2bootiso.grub_cfg("server-core", "x86_64", installer=True)
        self.assertIn("if [ -f /boot/grub/kiki/theme.txt ]; then", config)
        self.assertIn("if insmod gfxmenu; then", config)
        self.assertIn("terminal_output console serial", config)
        self.assertIn("kiki.ui=cli", config)

    def test_boot_branding_missing_input_fails_before_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            with self.assertRaises(ki2bootiso.BootIsoError):
                ki2bootiso.install_boot_branding(Path(tmp) / "missing", target)
            self.assertFalse(target.exists())

    def test_boot_branding_rejects_distorted_theme(self):
        source = Path(__file__).resolve().parents[1] / "assets/brand"
        with tempfile.TemporaryDirectory() as tmp:
            brand = Path(tmp) / "brand"
            brand.mkdir()
            shutil.copy2(source / "kikios-kiki-wordmark-boot-v2.png", brand)
            shutil.copy2(source / "grub-background-v2.png", brand)
            theme = (source / "grub-theme.txt").read_text(encoding="utf-8")
            (brand / "grub-theme.txt").write_text(theme.replace("height = 100", "height = 101"), encoding="utf-8")
            with self.assertRaisesRegex(ki2bootiso.BootIsoError, "aspect ratio"):
                ki2bootiso.install_boot_branding(brand, Path(tmp) / "out")

    def test_finalize_mount_failures_block_success(self):
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is required")
        source = ki2bootiso.INIT_C
        start = source.index("static int finalize_target_mounts(")
        end = source.index("\n}\n", start) + 3
        harness = r'''
#define SYS_sync 1
#define SYS_umount2 2
static int failure, calls;
static void say(const char *s) { (void)s; }
static long ksys(long nr, long a, long b, long c, long d, long e, long f) {
    (void)a; (void)b; (void)c; (void)d; (void)e; (void)f;
    if (nr == SYS_sync) return 0;
    calls++;
    return failure & (1 << (calls - 1)) ? -16 : 0;
}
'''
        harness += source[start:end]
        harness += r'''
int main(void) {
    for (failure = 0; failure < 4; failure++) {
        calls = 0;
        if (finalize_target_mounts() != (failure == 0) || calls != 2) return 1;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / "finalize.c", Path(tmp) / "finalize"
            path.write_text(harness, encoding="utf-8")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(path), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)
        guided = source.split("static void run_guided_package_installer_with_request", 1)[1]
        success = guided.index('say("\\nGuided install finished.')
        self.assertLess(guided.index("if (!finalize_target_mounts()) return;"), success)
        self.assertLess(guided.index("if (!persist_install_plan_to_target()) goto target_configuration_failed;"), success)

    def test_media_verifier_c_exit_status_propagation(self):
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is required")
        source = ki2bootiso.INIT_C
        start = source.index("static int verify_install_media(")
        end = source.index("\n}\n", start) + 3
        harness = r'''
#include <stddef.h>
#include <string.h>
static int result = 0;
static int called = 0;
static void say(const char *s) { (void)s; }
#define MAX_SELECTED_PACKAGES 96
#define PACKAGE_NAME_LEN 64
static int selected_package_count = 1;
static char selected_packages[96][64] = {"app"};
static size_t append_string(char *b, size_t n, size_t o, const char *s) {
    size_t l = strlen(s); if (o + l >= n) return o;
    memcpy(b + o, s, l + 1); return o + l;
}
static void mkdir_p(const char *p, int m) { (void)p; (void)m; }
static int write_text_file_mode(const char *p, const char *s, int m) { (void)p; (void)s; (void)m; return 1; }
static void remove_file(const char *p) { (void)p; }
static int read_small_file_raw(const char *p, char *b, size_t n, long *len) {
    (void)p; (void)n; strcpy(b, "app\n"); *len = 4; return 1;
}
static void selected_clear(void) { selected_package_count = 0; }
static int selected_add(const char *s) { (void)s; selected_package_count++; return 1; }
static int run_program(const char *path, char **argv) {
    if (strcmp(path, "/usr/bin/python3") || strcmp(argv[4], "/test-media") ||
        strcmp(argv[6], "/etc/ki2/trust/installer-repo.ed25519.pub")) return 99;
    called++;
    return result;
}
'''
        harness += source[start:end]
        harness += r'''
int main(void) {
    int failures[] = {1, 127, 139, -1};
    for (unsigned i = 0; i < sizeof(failures)/sizeof(failures[0]); i++) {
        result = failures[i];
        if (verify_install_media("/test-media") != 0) return 1;
    }
    result = 0;
    if (verify_install_media("/test-media") != 1 || called != 5) return 2;
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verify.c"
            output = Path(tmp) / "verify"
            path.write_text(harness, encoding="utf-8")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror", str(path), "-o", str(output)], check=True)
            subprocess.run([str(output)], check=True, timeout=10)

    def test_runtime_package_selection_uses_exact_name_and_numeric_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("python-3.12.4-9.x86_64.ki2", "python-3.12.4-10.x86_64.ki2",
                         "python-setuptools-84.0.0-2.x86_64.ki2"):
                (root / name).touch()
            self.assertEqual(ki2bootiso.latest_package(root, "python").name,
                             "python-3.12.4-10.x86_64.ki2")

    def test_media_verification_precedes_guided_disk_writes(self):
        source = ki2bootiso.INIT_C
        guided = source.split("static void run_guided_package_installer_with_request", 1)[1]
        call = guided.index("if (!verify_install_media(media_root)) return;")
        self.assertLess(call, guided.index("run_partition_command(partition_command)"))
        self.assertLess(call, guided.index('run_program("/bin/sh", argv)'))
        self.assertLess(call, guided.index("write_guided_gpt(target"))
        self.assertLess(call, guided.index("format_esp_partition(esp_part)"))
        self.assertIn('"--public-key", "/etc/ki2/trust/installer-repo.ed25519.pub"', source)

    def test_package_media_rejects_missing_corrupt_and_unsafe_payloads(self):
        for case in ("missing", "corrupt", "size", "hash", "path", "duplicate", "entry"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo, packages, target = root / "repo", root / "packages", root / "target"
                repo.mkdir()
                packages.mkdir()
                payload = b"trusted-package"
                entry = {"file": "test-1.ki2", "size": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()}
                if case != "missing":
                    (packages / "test-1.ki2").write_bytes(
                        b"damaged-package" if case == "corrupt" else payload)
                if case == "size":
                    entry["size"] += 1
                if case == "hash":
                    entry.pop("sha256")
                if case == "path":
                    entry["file"] = "../test-1.ki2"
                entries = [entry, entry] if case == "duplicate" else [None] if case == "entry" else [entry]
                (repo / "index.x86_64.json").write_text(
                    json.dumps({"packages": entries}), encoding="utf-8")
                with self.assertRaises(ki2bootiso.BootIsoError):
                    ki2bootiso.copy_package_payloads(repo, packages, target, "x86_64")
                self.assertFalse((target / "manifest.json").exists())

    def test_required_configuration_failures_stop_install(self):
        source = ki2bootiso.INIT_C
        for message in (
            "Failed to install the verified repository public key.",
            "Failed to write target identity files.",
            "Failed to write target network configuration.",
            "Failed to write target localization or AI configuration.",
            "Failed to write target ld.so.conf.",
        ):
            with self.subTest(message=message):
                tail = source.split(message, 1)[1].split("}", 1)[0]
                self.assertIn("goto target_configuration_failed;", tail)
        cleanup = source.split("target_configuration_failed:", 1)[1].split("}", 1)[0]
        self.assertIn("SYS_sync", cleanup)
        self.assertIn('SYS_umount2, (long)"/mnt/esp"', cleanup)
        self.assertIn('SYS_umount2, (long)"/mnt/target"', cleanup)
        self.assertNotIn('"completed"', cleanup)

    def test_boot_file_failure_blocks_success_in_all_frontends(self):
        source = ki2bootiso.INIT_C
        self.assertNotIn("if (gui_request && !boot_files_ok)", source)
        self.assertIn("if (!boot_files_ok) return;", source)
        self.assertLess(source.index("if (!boot_files_ok) return;"),
                        source.index("Guided install finished."))

    @staticmethod
    def write_fake_package(path: Path, files: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as tar:
            for rel, payload in files.items():
                info = tarfile.TarInfo(f"rootfs/{rel}")
                info.size = len(payload)
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(payload))

    def test_iso_default_output_uses_date_and_revision_stamp(self):
        root = Path("/repo")
        build_info = {"stamp": ki2bootiso.format_iso_build_stamp("2026-05-26", "42")}

        output = ki2bootiso.default_iso_output(root, "stage2-v2", "installer", "x86_64", build_info)

        self.assertEqual(output, root / "dist/iso/kiki-stage2-v2-installer-x86_64-20260526-rev42.iso")

    def test_dirty_iso_build_stamp_can_be_made_unique(self):
        stamp = f"{ki2bootiso.format_iso_build_stamp('2026-08-25', '20')}-dirty-a6b3a3e"
        output = ki2bootiso.default_iso_output(
            Path("/repo"), "stage3-v3", "installer", "x86_64", {"stamp": stamp}
        )

        self.assertEqual(
            output,
            Path("/repo/dist/iso/kiki-stage3-v3-installer-x86_64-20260825-rev20-dirty-a6b3a3e.iso"),
        )

    def test_iso_release_name_prefers_repository_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "metadata.x86_64.json").write_text('{"channel":"stage2-v2"}\n', encoding="utf-8")

            self.assertEqual(ki2bootiso.iso_release_name(repo, "x86_64", "bootstrap-stage1"), "stage2-v2")
            self.assertEqual(ki2bootiso.iso_release_name(repo, "x86_64", "bootstrap-stage1", "testing"), "testing")

    def test_find_kernel_prefers_repository_package_over_stale_rootfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            packages = root / "packages"
            work = root / "work"
            (rootfs / "boot").mkdir(parents=True)
            packages.mkdir()
            (rootfs / "boot/vmlinuz-kiki").write_bytes(b"stale-rootfs-kernel")

            package = packages / "linux-6.9.9-3.x86_64.ki2"
            with tarfile.open(package, "w:gz") as tar:
                manifest = json.dumps({"name": "linux", "version": "6.9.9", "release": "3"}).encode()
                manifest_info = tarfile.TarInfo("manifest.json")
                manifest_info.size = len(manifest)
                tar.addfile(manifest_info, io.BytesIO(manifest))
                kernel = b"new-package-kernel"
                kernel_info = tarfile.TarInfo("rootfs/boot/vmlinuz-kiki")
                kernel_info.size = len(kernel)
                tar.addfile(kernel_info, io.BytesIO(kernel))

            selected = ki2bootiso.find_kernel(rootfs, packages, work)

            self.assertEqual(selected.read_bytes(), b"new-package-kernel")
            self.assertEqual(selected, work / "vmlinuz-kiki")

    def test_iso_release_name_uses_stage1_fallback_without_repository_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            self.assertEqual(ki2bootiso.iso_release_name(repo, "x86_64", "bootstrap-stage1"), "stage1-v1")

    def test_prepare_boot_iso_tree_writes_boot_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            repo = root / "repo"
            packages = root / "packages"
            tree = root / "iso-tree"
            kernel = root / "vmlinuz-kiki"
            initramfs = root / "initramfs-kiki.img"

            (rootfs / "etc").mkdir(parents=True)
            (repo / "packages").mkdir(parents=True)
            packages.mkdir()
            (rootfs / "etc/os-release").write_text("ID=kiki-test\n", encoding="utf-8")
            (repo / "index.x86_64.json").write_text(
                json.dumps({"packages": [{"name": "base-files", "file": "base-files-1-1.x86_64.ki2",
                    "size": len(b"fake-package"), "sha256": hashlib.sha256(b"fake-package").hexdigest()}]}),
                encoding="utf-8",
            )
            (packages / "base-files-1-1.x86_64.ki2").write_bytes(b"fake-package")
            kernel.write_bytes(b"fake-kernel")
            initramfs.write_bytes(b"fake-initramfs")

            manifest = ki2bootiso.prepare_boot_iso_tree(
                rootfs,
                repo,
                tree,
                kernel=kernel,
                initramfs=initramfs,
                arch="x86_64",
                profile="bootstrap-stage1",
                label="KIKI_TEST_BOOT",
                packages_dir=packages,
            )

            self.assertEqual(manifest["schema"], "ki2-bootiso-v1")
            self.assertTrue(manifest["bootable"])
            self.assertEqual(manifest["boot_mode"], "vm-smoke")
            self.assertTrue(manifest["firmware"]["bios"])
            self.assertTrue(manifest["firmware"]["uefi"])
            self.assertFalse(manifest["firmware"]["secure_boot"])
            self.assertTrue((tree / "boot/vmlinuz-kiki").exists())
            self.assertTrue((tree / "boot/initramfs-kiki.img").exists())
            self.assertTrue((tree / "kiki/rootfs.tar.gz").exists())
            self.assertEqual((tree / "kiki/packages/x86_64/base-files-1-1.x86_64.ki2").read_bytes(), b"fake-package")
            self.assertEqual(manifest["package_media"]["copied"], 1)
            self.assertIn("initrd /boot/initramfs-kiki.img", (tree / "boot/grub/grub.cfg").read_text())

            manifest_file = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest_file["profile"], "bootstrap-stage1")

    def test_prepare_boot_iso_tree_can_enable_installer_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            repo = root / "repo"
            tree = root / "iso-tree"
            kernel = root / "vmlinuz-kiki"
            initramfs = root / "initramfs-kiki.img"

            rootfs.mkdir()
            repo.mkdir()
            (repo / "index.x86_64.json").write_text(json.dumps({"packages": []}))
            kernel.write_bytes(b"fake-kernel")
            initramfs.write_bytes(b"fake-initramfs")
            install_image = root / "kiki-stage1.img"
            install_image.write_bytes(b"fake-install-image")
            installed_initramfs = root / "installed-initramfs.img"
            installed_initramfs.write_bytes(b"fake-installed-initramfs")
            efi_bootloader = root / "BOOTX64.EFI"
            efi_bootloader.write_bytes(b"fake-efi")

            manifest = ki2bootiso.prepare_boot_iso_tree(
                rootfs,
                repo,
                tree,
                kernel=kernel,
                initramfs=initramfs,
                arch="x86_64",
                profile="bootstrap-stage1",
                label="KIKI_TEST_INSTALLER",
                installer=True,
                install_image=install_image,
                installed_initramfs=installed_initramfs,
                efi_bootloader=efi_bootloader,
            )

            self.assertEqual(manifest["boot_mode"], "installer-stage1")
            self.assertTrue(manifest["installer"]["enabled"])
            self.assertEqual(
                manifest["installer"]["strategy"],
                "guided-disk-partition-format-extract-selected-packages-uefi-boot",
            )
            self.assertTrue(manifest["installer"]["package_selection"])
            self.assertEqual(manifest["installer"]["install_image"]["size"], len(b"fake-install-image"))
            self.assertEqual(manifest["installer"]["installed_initramfs"]["size"], len(b"fake-installed-initramfs"))
            self.assertEqual(manifest["installer"]["uefi_fallback_bootloader"]["size"], len(b"fake-efi"))
            self.assertEqual((tree / "install/kiki-stage1.img").read_bytes(), b"fake-install-image")
            self.assertEqual((tree / "boot/initramfs-kiki-installed.img").read_bytes(), b"fake-installed-initramfs")
            self.assertEqual((tree / "kiki/bootloader/EFI/BOOT/BOOTX64.EFI").read_bytes(), b"fake-efi")
            grub = (tree / "boot/grub/grub.cfg").read_text(encoding="utf-8")
            self.assertIn("loadfont /boot/grub/fonts/unicode.pf2", grub)
            self.assertIn("terminal_output gfxterm", grub)
            self.assertIn("terminal_output console serial", grub)
            self.assertIn("set default=0", grub)
            self.assertIn("kiki.boot=installer", grub)
            self.assertIn('menuentry "KIKI OS graphical installer (default)"', grub)
            self.assertIn("kiki.ui=gui", grub)
            self.assertIn('menuentry "KIKI OS full-screen TUI installer (x86_64)"', grub)
            self.assertIn("kiki.ui=tui", grub)
            self.assertIn('menuentry "KIKI OS CLI installer (x86_64, safe fallback)"', grub)
            self.assertIn("kiki.ui=cli", grub)
            self.assertLess(grub.index("kiki.ui=gui"), grub.index("kiki.ui=tui"))
            self.assertLess(grub.index("kiki.ui=tui"), grub.index("kiki.ui=cli"))
            self.assertEqual(manifest["installer"]["interface"], "gui-tui-cli")
            self.assertEqual(manifest["installer"]["interface_order"], ["gtk4", "fullscreen-tui", "cli"])
            self.assertIn("quiet loglevel=3", grub)
            self.assertIn("graphical installer (default)", grub)
            self.assertIn("UEFI framebuffer", grub)
            self.assertIn("Hyper-V framebuffer", grub)
            self.assertIn("BIOS VGA text", grub)
            self.assertIn("serial + VGA", grub)
            self.assertIn("debug Hyper-V EFI", grub)
            self.assertIn("set gfxpayload=keep", grub)
            self.assertIn("video=hyperv_fb:1024x768", grub)

    def test_prepare_boot_iso_tree_can_describe_installed_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rootfs = root / "rootfs"
            repo = root / "repo"
            tree = root / "iso-tree"
            kernel = root / "vmlinuz-kiki"
            initramfs = root / "initramfs-kiki.img"

            rootfs.mkdir()
            repo.mkdir()
            kernel.write_bytes(b"fake-kernel")
            initramfs.write_bytes(b"fake-initramfs")

            manifest = ki2bootiso.prepare_boot_iso_tree(
                rootfs,
                repo,
                tree,
                kernel=kernel,
                initramfs=initramfs,
                arch="x86_64",
                profile="bootstrap-stage1",
                label="KIKI_TEST_INSTALLED",
                installed=True,
            )

            self.assertEqual(manifest["boot_mode"], "installed-systemd-handoff")
            grub = (tree / "boot/grub/grub.cfg").read_text(encoding="utf-8")
            self.assertIn("kiki.boot=installed", grub)
            self.assertIn("quiet loglevel=3", grub)

    def test_generated_init_contains_stage1_prompt(self):
        self.assertIn("KIKI stage-1 prompt ready", ki2bootiso.INIT_C)
        self.assertIn('say("kiki# ");', ki2bootiso.INIT_C)
        self.assertIn("basic services:", ki2bootiso.INIT_C)
        self.assertIn("BOS/ki2 package media", ki2bootiso.INIT_C)
        self.assertIn("Network tools", ki2bootiso.INIT_C)
        self.assertIn("Disk tools", ki2bootiso.INIT_C)
        self.assertIn("Package selection", ki2bootiso.INIT_C)
        self.assertIn("Select minimal-systemd default package set", ki2bootiso.INIT_C)
        self.assertIn("Select server-core general OS package set", ki2bootiso.INIT_C)
        self.assertIn("Select kiki-kube-bootstrap package set", ki2bootiso.INIT_C)
        self.assertIn("Select kiki-kube-control package set", ki2bootiso.INIT_C)
        self.assertIn("Select kiki-kube-compute package set", ki2bootiso.INIT_C)
        self.assertIn("kiki-kube-bootstrap package set (first control-plane bootstrap)", ki2bootiso.INIT_C)
        self.assertIn("kiki-kube-control package set (additional control-plane node)", ki2bootiso.INIT_C)
        self.assertIn("kiki-kube-compute package set (compute node)", ki2bootiso.INIT_C)
        self.assertIn("Kubernetes profiles keep swap off", ki2bootiso.INIT_C)
        self.assertIn("ensure_selected_profile_packages", ki2bootiso.INIT_C)
        self.assertIn("Required Kubernetes package missing from repository index", ki2bootiso.INIT_C)
        self.assertIn("Kubernetes profile cannot be installed until all required packages are present", ki2bootiso.INIT_C)
        self.assertIn('"kubelet"', ki2bootiso.INIT_C)
        self.assertIn('"kubeadm"', ki2bootiso.INIT_C)
        self.assertIn('"kubectl"', ki2bootiso.INIT_C)
        self.assertIn('"kiki-kubeadm"', ki2bootiso.INIT_C)
        self.assertIn('"cri-o"', ki2bootiso.INIT_C)
        self.assertIn('"containerd"', ki2bootiso.INIT_C)
        self.assertIn('"kube-node-config-containerd"', ki2bootiso.INIT_C)
        self.assertIn('"kiki-netconfig"', ki2bootiso.INIT_C)
        self.assertIn('"server-core"', ki2bootiso.INIT_C)
        self.assertIn("Use containerd", ki2bootiso.INIT_C)
        self.assertIn("selected_container_runtime", ki2bootiso.INIT_C)
        self.assertIn("unique package names", ki2bootiso.INIT_C)
        self.assertIn("KIKI OS Scratch Pad TUI", ki2bootiso.INIT_C)
        self.assertIn("KIKI OS Scratch Pad", ki2bootiso.INIT_C)
        self.assertIn("1) Language / keyboard / timezone", ki2bootiso.INIT_C)
        self.assertIn("5) Package source / trust", ki2bootiso.INIT_C)
        self.assertIn("8) AI management console", ki2bootiso.INIT_C)
        self.assertIn("10) Start install", ki2bootiso.INIT_C)
        self.assertIn("s) Shell", ki2bootiso.INIT_C)
        self.assertIn("q) Power off", ki2bootiso.INIT_C)
        self.assertIn("Review install plan", ki2bootiso.INIT_C)
        self.assertIn("Declarative install plan preview", ki2bootiso.INIT_C)
        self.assertIn("kiki-install-plan-v1", ki2bootiso.INIT_C)
        self.assertIn("/run/kiki/install-plan.yaml", ki2bootiso.INIT_C)
        self.assertIn("/var/lib/ki2/install-plan.yaml", ki2bootiso.INIT_C)
        self.assertIn('"channel", "stage2-v2"', ki2bootiso.INIT_C)
        self.assertIn("selected_kubernetes_role", ki2bootiso.INIT_C)
        self.assertIn("selected_kubeadm_template", ki2bootiso.INIT_C)
        self.assertIn("kubeadm.k8s.io/v1beta4", ki2bootiso.INIT_C)
        self.assertIn("kubeadm init --config /etc/kubernetes/kiki/kubeadm.local.yaml", ki2bootiso.INIT_C)
        self.assertIn("kubeadm join --config /etc/kubernetes/kiki/kubeadm.local.yaml", ki2bootiso.INIT_C)
        self.assertIn("/etc/kubernetes/kiki/kubeadm-join-compute.yaml", ki2bootiso.INIT_C)
        self.assertIn("unix:///run/containerd/containerd.sock", ki2bootiso.INIT_C)
        self.assertIn("unix:///var/run/crio/crio.sock", ki2bootiso.INIT_C)
        self.assertIn("runtime-input-not-written-to-plan", ki2bootiso.INIT_C)
        self.assertIn("dependency_resolution", ki2bootiso.INIT_C)
        self.assertIn('"  localization:\\n"', ki2bootiso.INIT_C)
        self.assertIn('"require_approval"', ki2bootiso.INIT_C)
        self.assertIn("kiki-ai-console-kmscon@tty1.service", ki2bootiso.INIT_C)
        self.assertIn('"kiki-kmscon"', ki2bootiso.INIT_C)
        self.assertIn("getty@tty2.service", ki2bootiso.INIT_C)
        self.assertIn("ensure_selected_ai_packages", ki2bootiso.INIT_C)
        self.assertIn("Network setup", ki2bootiso.INIT_C)
        self.assertIn("systemd-networkd DHCP", ki2bootiso.INIT_C)
        self.assertIn("interface_match", ki2bootiso.INIT_C)
        self.assertIn("write_target_network_config", ki2bootiso.INIT_C)
        self.assertIn("RequiredForOnline=routable", ki2bootiso.INIT_C)
        self.assertIn("DHCP=ipv4", ki2bootiso.INIT_C)
        self.assertIn("show_saved_install_plan", ki2bootiso.INIT_C)
        self.assertIn("find_default_install_disk", ki2bootiso.INIT_C)
        self.assertIn("kiki.autoinstall", ki2bootiso.INIT_C)
        self.assertIn("kiki.profile", ki2bootiso.INIT_C)
        self.assertIn("kiki.runtime", ki2bootiso.INIT_C)
        self.assertIn("kiki.target", ki2bootiso.INIT_C)
        self.assertIn("kiki.hostname", ki2bootiso.INIT_C)
        self.assertIn("kiki.locale", ki2bootiso.INIT_C)
        self.assertIn("kiki.timezone", ki2bootiso.INIT_C)
        self.assertIn("kiki.ai-endpoint", ki2bootiso.INIT_C)
        self.assertIn("maybe_run_cmdline_autoinstall", ki2bootiso.INIT_C)
        self.assertIn("try_graphical_installer", ki2bootiso.INIT_C)
        self.assertIn("GTK installer is not present in this initramfs; falling back to the TUI", ki2bootiso.INIT_C)
        self.assertIn('"/usr/bin/cage"', ki2bootiso.INIT_C)
        self.assertIn('"XDG_RUNTIME_DIR=/run/kiki-wayland"', ki2bootiso.INIT_C)
        self.assertIn('"GDK_BACKEND=wayland"', ki2bootiso.INIT_C)
        self.assertIn('"LIBSEAT_BACKEND=builtin"', ki2bootiso.INIT_C)
        self.assertIn('"/usr/lib/systemd/systemd-udevd"', ki2bootiso.INIT_C)
        self.assertIn('"/usr/bin/udevadm"', ki2bootiso.INIT_C)
        self.assertIn('"/run/kiki/gui-installer.log"', ki2bootiso.INIT_C)
        self.assertIn('GUI_INSTALL_REQUEST_PATH "/run/kiki/gui-install.request"', ki2bootiso.INIT_C)
        self.assertIn('GUI_INSTALL_PROGRESS_PATH "/run/kiki/install-progress.state"', ki2bootiso.INIT_C)
        self.assertIn('GUI_REBOOT_REQUEST_PATH "/run/kiki/gui-reboot.request"', ki2bootiso.INIT_C)
        self.assertIn("load_gui_install_request", ki2bootiso.INIT_C)
        self.assertIn("run_guided_package_installer_with_request", ki2bootiso.INIT_C)
        self.assertIn("Graphical installer target disk", ki2bootiso.INIT_C)
        self.assertIn("configure_gui_network", ki2bootiso.INIT_C)
        self.assertIn('request_value(buffer, "password"', ki2bootiso.INIT_C)
        self.assertIn('kopen(GUI_INSTALL_REQUEST_PATH, O_WRONLY | O_TRUNC)', ki2bootiso.INIT_C)
        self.assertIn("Graphical confirmation accepted", ki2bootiso.INIT_C)
        self.assertIn("GTK installer validated the account password and destructive confirmation", ki2bootiso.INIT_C)
        self.assertIn("keeping the graphical progress screen active", ki2bootiso.INIT_C)
        self.assertIn("Graphical installer received explicit reboot confirmation", ki2bootiso.INIT_C)
        self.assertIn('write_gui_install_progress("completed", 100', ki2bootiso.INIT_C)
        self.assertIn('"\\npackages_installed="', ki2bootiso.INIT_C)
        self.assertIn("write_gui_package_progress(installed, selected_package_count", ki2bootiso.INIT_C)
        self.assertIn("write_guided_gpt(target, !has_swap", ki2bootiso.INIT_C)
        self.assertIn("graphical_status != 2", ki2bootiso.INIT_C)
        self.assertIn('mount_one("tmpfs", "/dev/shm", "tmpfs", 0, "mode=1777")', ki2bootiso.INIT_C)
        self.assertIn('service_line("tmpfs on /dev/shm", service_devshm)', ki2bootiso.INIT_C)
        self.assertIn('"WLR_RENDERER=pixman"', ki2bootiso.INIT_C)
        self.assertNotIn('"WLR_RENDERER=gles2"', ki2bootiso.INIT_C)
        self.assertIn('"WLR_RENDERER_ALLOW_SOFTWARE=1"', ki2bootiso.INIT_C)
        self.assertIn('"--ascii"', ki2bootiso.INIT_C)
        self.assertIn('"LANG=C.UTF-8"', ki2bootiso.INIT_C)
        self.assertIn("run_guided_package_installer(1, 1)", ki2bootiso.INIT_C)
        self.assertIn("select_named_package_profile", ki2bootiso.INIT_C)
        self.assertIn("Autoinstall target disk", ki2bootiso.INIT_C)
        self.assertIn("Press Enter or type yes to continue", ki2bootiso.INIT_C)
        self.assertIn("Hostname [localhost.localdomain]", ki2bootiso.INIT_C)
        self.assertIn("User setup", ki2bootiso.INIT_C)
        self.assertIn("Admin username [kiki]", ki2bootiso.INIT_C)
        self.assertIn("Disable direct root login", ki2bootiso.INIT_C)
        self.assertIn("KIKI_LAB_PASSWORD_HASH", ki2bootiso.INIT_C)
        self.assertIn("Writing lab default admin account directly", ki2bootiso.INIT_C)
        self.assertIn("write_target_lab_admin_account", ki2bootiso.INIT_C)
        self.assertIn('"/bin/sh"', ki2bootiso.INIT_C)
        self.assertIn("/usr/sbin/useradd", ki2bootiso.INIT_C)
        self.assertIn("/usr/sbin/chpasswd", ki2bootiso.INIT_C)
        self.assertIn("/etc/sudoers.d/kiki-admin", ki2bootiso.INIT_C)
        self.assertIn('"sudo"', ki2bootiso.INIT_C)
        self.assertIn("Automatic whole-disk layout: ESP + swap + root", ki2bootiso.INIT_C)
        self.assertIn("Manual partitions: use shell/fdisk/cfdisk first", ki2bootiso.INIT_C)
        self.assertIn("Disk actions", ki2bootiso.INIT_C)
        self.assertIn("Open cfdisk on a disk", ki2bootiso.INIT_C)
        self.assertIn("Open fdisk on a disk", ki2bootiso.INIT_C)
        self.assertIn("prompt_whole_disk", ki2bootiso.INIT_C)
        self.assertIn("run_partition_editor", ki2bootiso.INIT_C)

    def test_gtk_frontend_exposes_install_start_handoff(self):
        source = (Path(__file__).resolve().parents[1] / "cmd/kiki-installer-gtk/main.c").read_text(encoding="utf-8")

        self.assertIn('g_signal_connect(install_button, "clicked", G_CALLBACK(start_install), ui)', source)
        self.assertIn('GUI_INSTALL_REQUEST_PATH "/run/kiki/gui-install.request"', source)
        self.assertIn('GUI_INSTALL_PROGRESS_PATH "/run/kiki/install-progress.state"', source)
        self.assertIn('GUI_REBOOT_REQUEST_PATH "/run/kiki/gui-reboot.request"', source)
        self.assertIn("write_install_request", source)
        self.assertIn("poll_install_progress", source)
        self.assertIn('gtk_button_new_with_label(L("확인 후 재부팅", "Confirm and reboot"))', source)
        self.assertIn('"packages_installed"', source)
        self.assertIn('"packages_total"', source)
        self.assertIn("패키지 설치 완료:", source)
        self.assertIn('gtk_stack_set_visible_child_name(ui->stack, "progress")', source)
        self.assertIn("g_timeout_add(200, poll_install_progress", source)
        self.assertIn('append_request_field(request, "package"', source)
        self.assertIn('REQUEST_FIELD("password", password)', source)
        self.assertIn('REQUEST_FIELD("confirmed", expected)', source)
        self.assertIn('if (!gtk_check_button_get_active(ui->destructive_confirm))', source)
        self.assertIn('gtk_check_button_set_active(ui->destructive_confirm, FALSE)', source)
        self.assertIn('g_signal_connect(ui->disk, "changed", G_CALLBACK(target_disk_changed), ui)', source)
        self.assertNotIn('gtk_editable_get_text(GTK_EDITABLE(ui->destructive_confirm))', source)
        self.assertIn('form_entry(GTK_GRID(grid), 2, L("관리자 암호", "Administrator password")', source)
        self.assertIn('gtk_check_button_new_with_label(L("선택한 디스크의 모든 데이터가 삭제되는 것에 동의합니다."', source)
        self.assertIn('g_strdup_printf("INSTALL %s", disk)', source)
        self.assertIn('"ncurses"', ki2bootiso.INIT_C)
        self.assertIn('"cfdisk"', ki2bootiso.INIT_C)
        self.assertIn("preferred_install_disk", ki2bootiso.INIT_C)
        self.assertIn("Detected partition candidates from", ki2bootiso.INIT_C)
        self.assertIn("prompt_partition_path", ki2bootiso.INIT_C)
        self.assertIn("type none", ki2bootiso.INIT_C)
        self.assertIn("BLKRRPART", ki2bootiso.INIT_C)
        self.assertIn("fdisk /dev/<disk>", ki2bootiso.INIT_C)
        self.assertIn("Running partition command", ki2bootiso.INIT_C)
        self.assertIn("not a partition such as /dev/sda1", ki2bootiso.INIT_C)
        self.assertIn("Formatting swap partition", ki2bootiso.INIT_C)
        self.assertIn("/usr/sbin/mke2fs", ki2bootiso.INIT_C)
        self.assertIn("LABEL=KIKI_ROOT / ext4 defaults", ki2bootiso.INIT_C)
        self.assertIn("LABEL=KIKI_EFI /boot/efi", ki2bootiso.INIT_C)
        self.assertIn("LABEL=KIKI_SWAP none swap defaults,nofail,x-systemd.device-timeout=10s", ki2bootiso.INIT_C)
        self.assertIn("noauto,nofail,x-systemd.device-timeout=3s", ki2bootiso.INIT_C)
        self.assertIn("kiki-installer-tui", ki2bootiso.INIT_C)
        self.assertIn("Formatting root partition as ext4", ki2bootiso.INIT_C)
        self.assertIn("Switching to installed systemd PID 1", ki2bootiso.INIT_C)
        self.assertIn("/usr/lib/systemd", ki2bootiso.INIT_C)
        self.assertIn("Refreshing target shared-library cache", ki2bootiso.INIT_C)
        self.assertIn("-r", ki2bootiso.INIT_C)
        self.assertIn("ensure_target_baseline_layout", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/usr/sbin/sulogin", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/lib64/ld-linux-x86-64.so.2", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/lib64/libcrypt.so.2", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/etc/systemd/system/kiki-agent.service", ki2bootiso.INIT_C)
        self.assertIn("/mnt/target/var/tmp", ki2bootiso.INIT_C)
        self.assertIn("systemd-logind.service", ki2bootiso.INIT_C)
        self.assertIn("getty.target.wants", ki2bootiso.INIT_C)
        self.assertIn("systemd-networkd.socket", ki2bootiso.INIT_C)
        self.assertIn("kiki-boot-prepare.service", ki2bootiso.INIT_C)
        self.assertIn("KIKI OS installed (systemd handoff)", ki2bootiso.INIT_C)
        self.assertIn("/boot/grub/fonts/unicode.pf2", ki2bootiso.INIT_C)
        source = Path(ki2bootiso.__file__).read_text(encoding="utf-8")
        self.assertIn("lib/libncursesw.so", source)
        self.assertIn("lib/libtinfo.so", source)
        self.assertIn("static IPv4", source)
        self.assertIn("Address=", source)
        self.assertIn("Gateway=", source)

    def test_generated_init_c_has_valid_syntax_when_gcc_is_available(self):
        gcc = shutil.which("gcc")
        if not gcc:
            self.skipTest("gcc is not available")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "init.c"
            source.write_text(ki2bootiso.INIT_C, encoding="utf-8")

            subprocess.run([gcc, "-Wall", "-Wextra", "-fsyntax-only", str(source)], check=True)

    def test_partition_runtime_accepts_lib64_and_replaces_gtk_aliases(self):
        if os.name == "nt":
            self.skipTest("requires POSIX symlinks")
        for directory in ("lib", "lib64"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "root"
                (root / "lib64").mkdir(parents=True)
                (root / "lib").mkdir()
                (root / "lib/libfdisk.so.1").write_bytes(b"older-gtk-abi")
                (root / "lib64/libfdisk.so.1").symlink_to("../lib/libfdisk.so.1")
                package = Path(tmp) / "util-linux.ki2"
                self.write_fake_package(package, {
                    "sbin/sfdisk": b"partition-tool",
                    directory + "/libfdisk.so.1": b"matching-util-linux-abi",
                    directory + "/libfdisk.so.1.1.9": b"versioned-abi",
                })
                ki2bootiso.restore_installer_partition_runtime(root, package)
                self.assertEqual((root / "lib64/libfdisk.so.1").read_bytes(), b"matching-util-linux-abi")
                self.assertEqual((root / "lib64/libfdisk.so.1.1.9").read_bytes(), b"versioned-abi")
                self.assertEqual((root / "sbin/sfdisk").read_bytes(), b"partition-tool")

    def test_add_installer_runtime_includes_cfdisk_libraries(self):
        if os.name == "nt":
            self.skipTest("Windows symlink permissions can block busybox applet links")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = root / "packages"
            target = root / "initramfs-root"
            packages.mkdir()

            self.write_fake_package(
                packages / "glibc-2.40-1.x86_64.ki2",
                {
                    "etc/ld.so.cache": b"cache",
                    "lib64/ld-linux-x86-64.so.2": b"loader",
                },
            )
            self.write_fake_package(packages / "busybox-1.36-1.x86_64.ki2", {"bin/busybox": b"busybox"})
            self.write_fake_package(
                packages / "e2fsprogs-1.47-1.x86_64.ki2",
                {
                    "usr/sbin/mke2fs": b"mke2fs",
                    "usr/sbin/mkfs.ext4": b"mkfs.ext4",
                },
            )
            self.write_fake_package(
                packages / "util-linux-2.40-1.x86_64.ki2",
                {
                    "sbin/cfdisk": b"cfdisk",
                    "sbin/fdisk": b"fdisk",
                    "sbin/sfdisk": b"sfdisk",
                    "lib/libblkid.so.1": b"blkid",
                    "lib/libblkid.so.1.1.0": b"blkid-real",
                    "lib/libfdisk.so.1": b"fdisk-lib",
                    "lib/libfdisk.so.1.1.0": b"fdisk-real",
                    "lib/libmount.so.1": b"mount",
                    "lib/libmount.so.1.1.0": b"mount-real",
                    "lib/libsmartcols.so.1": b"smartcols",
                    "lib/libsmartcols.so.1.1.0": b"smartcols-real",
                    "lib/libuuid.so.1": b"uuid",
                    "lib/libuuid.so.1.3.0": b"uuid-real",
                },
            )
            self.write_fake_package(
                packages / "ncurses-6.5-1.x86_64.ki2",
                {
                    "lib/libncursesw.so.6": b"ncursesw",
                    "lib/libtinfo.so.6": b"tinfo",
                    "usr/share/terminfo/x/xterm": b"terminfo",
                },
            )
            self.write_fake_package(
                packages / "kiki-installer-tui-0.1.0-5.x86_64.ki2",
                {"usr/bin/kiki-installer-tui": b"static-tui"},
            )
            self.write_fake_package(
                packages / "kiki-installer-gtk-0.1.0-1.x86_64.ki2",
                {
                    "usr/bin/cage": b"cage",
                    "usr/bin/kiki-installer-gtk": b"KIKI OS Scratch Pad",
                    "usr/lib64/libwlroots.so.11": b"wlroots",
                    "usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc": b"font",
                },
            )

            runtime = ki2bootiso.add_installer_runtime(target, packages)

            self.assertEqual(runtime["packages"]["util-linux"], "util-linux-2.40-1.x86_64.ki2")
            self.assertEqual(runtime["packages"]["kiki-installer-tui"], "kiki-installer-tui-0.1.0-5.x86_64.ki2")
            self.assertEqual((target / "usr/bin/kiki-installer-tui").read_bytes(), b"static-tui")
            self.assertIn("/usr/bin/kiki-installer-tui", runtime["tools"])
            self.assertTrue(runtime["graphical"]["enabled"])
            self.assertEqual((target / "usr/bin/cage").read_bytes(), b"cage")
            self.assertEqual((target / "usr/bin/kiki-installer-gtk").read_bytes(), b"KIKI OS Scratch Pad")
            self.assertTrue((target / "usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc").exists())
            self.assertTrue((target / "sbin/cfdisk").exists())
            self.assertTrue((target / "lib/libsmartcols.so.1").exists())
            self.assertTrue((target / "lib/libsmartcols.so.1.1.0").exists())
            self.assertTrue((target / "lib/libtinfo.so.6").exists())
            self.assertTrue((target / "lib/libncursesw.so.6").exists())
            self.assertTrue((target / "lib64/libsmartcols.so.1").is_symlink())
            self.assertTrue((target / "lib64/libfdisk.so.1").is_symlink())
            self.assertEqual(os.readlink(target / "lib64/libsmartcols.so.1"), "../lib/libsmartcols.so.1")

    def test_extract_package_members_preserves_hardlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "e2fsprogs-test.ki2"
            target = root / "initramfs-root"
            payload = b"fake-mke2fs"

            with tarfile.open(package, "w:gz") as tar:
                info = tarfile.TarInfo("rootfs/usr/sbin/mke2fs")
                info.size = len(payload)
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(payload))

                link = tarfile.TarInfo("rootfs/usr/sbin/mkfs.ext4")
                link.type = tarfile.LNKTYPE
                link.linkname = "rootfs/usr/sbin/mke2fs"
                link.mode = 0o755
                tar.addfile(link)

            extracted = ki2bootiso.extract_package_members(
                package,
                target,
                {"usr/sbin/mke2fs", "usr/sbin/mkfs.ext4"},
            )

            self.assertEqual(extracted, 2)
            self.assertEqual((target / "usr/sbin/mke2fs").read_bytes(), payload)
            self.assertEqual((target / "usr/sbin/mkfs.ext4").read_bytes(), payload)

    def test_chmod_dynamic_loaders_marks_interpreter_executable(self):
        if os.name == "nt":
            self.skipTest("Windows chmod does not reliably expose executable mode bits")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loader = root / "lib64/ld-linux-x86-64.so.2"
            loader.parent.mkdir(parents=True)
            loader.write_bytes(b"fake-loader")
            loader.chmod(0o644)

            ki2bootiso.chmod_dynamic_loaders(root)

            self.assertEqual(loader.stat().st_mode & 0o777, 0o755)

    def test_default_hyperv_vhdx_output_uses_dist_iso(self):
        root = Path("/repo")
        output = ki2bootiso.default_hyperv_vhdx_output(root, "bootstrap-stage1", "x86_64")
        self.assertEqual(output, root / "dist/iso/kiki-stage1-v1-installed-hyperv-x86_64.vhdx")

    def test_newc_stream_preserves_archive_bytes_without_reading_whole_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            payload = b"archive-payload" * 100000
            entry = source / "init"
            entry.write_bytes(payload)
            st = entry.stat()
            reference = bytearray()
            ki2bootiso._add_newc_entry(reference, 1, "init", payload,
                                      stat.S_IFREG | (st.st_mode & 0o7777), int(st.st_mtime), 1)
            ki2bootiso._add_newc_entry(reference, 2, "TRAILER!!!", b"", 0, 0, 1)
            output = Path(tmp) / "initramfs.gz"
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file buffering")):
                ki2bootiso.write_newc_gzip(source, output)
            self.assertEqual(gzip.decompress(output.read_bytes()), bytes(reference))

    def test_write_newc_gzip_contains_init_and_trailer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "initramfs-root"
            output = root / "initramfs.img"
            source.mkdir()
            init = source / "init"
            init.write_text("#!/bin/sh\n", encoding="utf-8")
            init.chmod(0o755)

            ki2bootiso.write_newc_gzip(source, output)

            payload = gzip.decompress(output.read_bytes())
            self.assertIn(b"070701", payload)
            self.assertIn(b"init\x00", payload)
            self.assertIn(b"TRAILER!!!", payload)


if __name__ == "__main__":
    unittest.main()
