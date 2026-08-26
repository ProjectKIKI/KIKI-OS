#!/usr/bin/env python3
"""Create a bootable KIKI VM smoke or stage-1 installer ISO image.

This is intentionally an early boot/install milestone. The ISO boots the
KIKI-built kernel with a generated initramfs. Smoke mode proves the bootloader,
kernel, and init handoff. Installer mode adds a console TUI that mounts the
installer media, lets the operator select an initial package set from the
bundled ki2 repository, partitions a VM disk, formats ESP/root filesystems,
extracts selected packages, and installs UEFI fallback boot files after
explicit confirmation. A legacy stage-1 image writer remains available as a
rescue path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


UTC = dt.timezone.utc
DEFAULT_STAGE1_RELEASE = "stage1-v1"

INIT_C = r"""
typedef unsigned long size_t;
typedef long ssize_t;
typedef unsigned long long u64;

#define NULL ((void *)0)
#define STDIN_FILENO 0
#define STDOUT_FILENO 1
#define STDERR_FILENO 2

#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_CREAT 0100
#define O_APPEND 02000
#define O_TRUNC 01000
#define O_NOCTTY 0400
#define O_NONBLOCK 04000
#define O_DIRECTORY 0200000

#define MS_RDONLY 1
#define EBUSY 16
#define EINTR 4

#define SYS_read 0
#define SYS_write 1
#define SYS_open 2
#define SYS_close 3
#define SYS_ioctl 16
#define SYS_pipe 22
#define SYS_select 23
#define SYS_nanosleep 35
#define SYS_dup2 33
#define SYS_pause 34
#define SYS_fork 57
#define SYS_execve 59
#define SYS_wait4 61
#define SYS_fsync 74
#define SYS_chdir 80
#define SYS_mkdir 83
#define SYS_symlink 88
#define SYS_chmod 90
#define SYS_chown 92
#define SYS_setsid 112
#define SYS_chroot 161
#define SYS_sync 162
#define SYS_mount 165
#define SYS_umount2 166
#define SYS_reboot 169
#define SYS_getdents64 217
#define SYS_exit 60

#define BLKRRPART 0x125f

#define LINUX_REBOOT_MAGIC1 0xfee1dead
#define LINUX_REBOOT_MAGIC2 672274793
#define LINUX_REBOOT_CMD_RESTART 0x01234567
#define LINUX_REBOOT_CMD_POWER_OFF 0x4321fedc

struct ktimespec {
    long tv_sec;
    long tv_nsec;
};

struct linux_dirent64 {
    u64 d_ino;
    long long d_off;
    unsigned short d_reclen;
    unsigned char d_type;
    char d_name[];
};

static long ksys(long n, long a, long b, long c, long d, long e, long f) {
    register long r10 __asm__("r10") = d;
    register long r8 __asm__("r8") = e;
    register long r9 __asm__("r9") = f;
    long ret;
    __asm__ volatile(
        "syscall"
        : "=a"(ret)
        : "a"(n), "D"(a), "S"(b), "d"(c), "r"(r10), "r"(r8), "r"(r9)
        : "rcx", "r11", "memory");
    return ret;
}

static char copy_buffer[1024 * 1024];
static char preferred_install_disk[128];

static size_t kstrlen(const char *text) {
    size_t len = 0;
    while (text && text[len]) {
        len++;
    }
    return len;
}

static int kstrcmp(const char *a, const char *b) {
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return (unsigned char)*a - (unsigned char)*b;
}

static int starts_with(const char *value, const char *prefix) {
    while (*prefix) {
        if (*value++ != *prefix++) {
            return 0;
        }
    }
    return 1;
}

static int ends_with(const char *value, const char *suffix) {
    size_t value_len = kstrlen(value);
    size_t suffix_len = kstrlen(suffix);
    if (suffix_len > value_len) {
        return 0;
    }
    return kstrcmp(value + value_len - suffix_len, suffix) == 0;
}

static int contains(const char *value, const char *needle) {
    if (!*needle) {
        return 1;
    }
    for (; *value; value++) {
        const char *a = value;
        const char *b = needle;
        while (*a && *b && *a == *b) {
            a++;
            b++;
        }
        if (!*b) {
            return 1;
        }
    }
    return 0;
}

static void copy_string(char *out, size_t out_size, const char *value) {
    size_t i = 0;
    if (out_size == 0) {
        return;
    }
    while (value[i] && i + 1 < out_size) {
        out[i] = value[i];
        i++;
    }
    out[i] = 0;
}

static size_t append_string(char *out, size_t out_size, size_t pos, const char *value) {
    while (*value && pos + 1 < out_size) {
        out[pos++] = *value++;
    }
    if (out_size) {
        out[pos < out_size ? pos : out_size - 1] = 0;
    }
    return pos;
}

static size_t append_u64(char *out, size_t out_size, size_t pos, u64 value) {
    char tmp[32];
    size_t used = 0;
    if (value == 0) {
        tmp[used++] = '0';
    } else {
        while (value && used < sizeof(tmp)) {
            tmp[used++] = (char)('0' + (value % 10));
            value /= 10;
        }
    }
    while (used && pos + 1 < out_size) {
        out[pos++] = tmp[--used];
    }
    if (out_size) {
        out[pos < out_size ? pos : out_size - 1] = 0;
    }
    return pos;
}

static size_t append_char(char *out, size_t out_size, size_t pos, char value) {
    if (pos + 1 < out_size) {
        out[pos++] = value;
    }
    if (out_size) {
        out[pos < out_size ? pos : out_size - 1] = 0;
    }
    return pos;
}

static size_t append_yaml_value(char *out, size_t out_size, size_t pos, const char *value) {
    if (!value || !value[0]) {
        return append_string(out, out_size, pos, "null");
    }
    pos = append_char(out, out_size, pos, '"');
    for (const char *p = value; *p; p++) {
        if (*p == '"' || *p == '\\') {
            pos = append_char(out, out_size, pos, '\\');
            pos = append_char(out, out_size, pos, *p);
        } else if (*p == '\n' || *p == '\r') {
            pos = append_char(out, out_size, pos, ' ');
        } else {
            pos = append_char(out, out_size, pos, *p);
        }
    }
    return append_char(out, out_size, pos, '"');
}

static u64 parse_u64(const char *value) {
    u64 result = 0;
    while (*value >= '0' && *value <= '9') {
        result = result * 10 + (u64)(*value - '0');
        value++;
    }
    return result;
}

static void write_bytes(int fd, const char *data, size_t len) {
    while (len) {
        long written = ksys(SYS_write, fd, (long)data, (long)len, 0, 0, 0);
        if (written <= 0) {
            return;
        }
        data += written;
        len -= (size_t)written;
    }
}

static void write_all(int fd, const char *text) {
    write_bytes(fd, text, kstrlen(text));
}

static int kopen(const char *path, long flags) {
    return (int)ksys(SYS_open, (long)path, flags, 0, 0, 0, 0);
}

static int kopen_mode(const char *path, long flags, long mode) {
    return (int)ksys(SYS_open, (long)path, flags, mode, 0, 0, 0);
}

static void kclose(int fd) {
    if (fd >= 0) {
        ksys(SYS_close, fd, 0, 0, 0, 0, 0);
    }
}

static void say(const char *text) {
    write_all(STDOUT_FILENO, text);
}

static void attach_console(void) {
    const char *targets[] = {"/dev/console", "/dev/tty0", "/dev/ttyS0", NULL};
    for (int i = 0; targets[i]; i++) {
        int console = kopen(targets[i], O_RDWR | O_NOCTTY);
        if (console >= 0) {
            ksys(SYS_dup2, console, STDIN_FILENO, 0, 0, 0, 0);
            ksys(SYS_dup2, console, STDOUT_FILENO, 0, 0, 0, 0);
            ksys(SYS_dup2, console, STDERR_FILENO, 0, 0, 0, 0);
            if (console > STDERR_FILENO) {
                kclose(console);
            }
            return;
        }
    }
}

static void mkdir_one(const char *path, long mode) {
    ksys(SYS_mkdir, (long)path, mode, 0, 0, 0, 0);
}

static void mkdir_p(const char *path, long mode) {
    char tmp[384];
    size_t len = 0;
    if (!path || !path[0]) {
        return;
    }
    copy_string(tmp, sizeof(tmp), path);
    while (tmp[len]) {
        len++;
    }
    for (size_t i = 1; i < len; i++) {
        if (tmp[i] == '/') {
            tmp[i] = 0;
            if (tmp[0]) {
                mkdir_one(tmp, mode);
            }
            tmp[i] = '/';
        }
    }
    mkdir_one(tmp, mode);
}

static int write_text_file(const char *path, const char *text) {
    int fd = kopen_mode(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        return 0;
    }
    write_all(fd, text);
    ksys(SYS_fsync, fd, 0, 0, 0, 0, 0);
    kclose(fd);
    return 1;
}

static int write_text_file_mode(const char *path, const char *text, long mode) {
    int fd = kopen_mode(path, O_WRONLY | O_CREAT | O_TRUNC, mode);
    if (fd < 0) {
        return 0;
    }
    write_all(fd, text);
    ksys(SYS_fsync, fd, 0, 0, 0, 0, 0);
    kclose(fd);
    ksys(SYS_chmod, (long)path, mode, 0, 0, 0, 0);
    return 1;
}

static int append_text_file_mode(const char *path, const char *text, long mode) {
    int fd = kopen_mode(path, O_WRONLY | O_CREAT | O_APPEND, mode);
    if (fd < 0) {
        return 0;
    }
    write_all(fd, text);
    ksys(SYS_fsync, fd, 0, 0, 0, 0, 0);
    kclose(fd);
    ksys(SYS_chmod, (long)path, mode, 0, 0, 0, 0);
    return 1;
}

static void make_symlink(const char *target, const char *linkpath) {
    ksys(SYS_symlink, (long)target, (long)linkpath, 0, 0, 0, 0);
}

static void chmod_path(const char *path, long mode) {
    ksys(SYS_chmod, (long)path, mode, 0, 0, 0, 0);
}

static void chown_path(const char *path, long uid, long gid) {
    ksys(SYS_chown, (long)path, uid, gid, 0, 0, 0);
}

static int copy_file(const char *source_path, const char *dest_path) {
    int source = kopen(source_path, O_RDONLY);
    if (source < 0) {
        say("Cannot open source file: ");
        say(source_path);
        say("\n");
        return 0;
    }
    int dest = kopen_mode(dest_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (dest < 0) {
        say("Cannot create destination file: ");
        say(dest_path);
        say("\n");
        kclose(source);
        return 0;
    }
    for (;;) {
        long got = ksys(SYS_read, source, (long)copy_buffer, sizeof(copy_buffer), 0, 0, 0);
        if (got == 0) {
            break;
        }
        if (got < 0) {
            kclose(source);
            kclose(dest);
            return 0;
        }
        long left = got;
        char *ptr = copy_buffer;
        while (left > 0) {
            long written = ksys(SYS_write, dest, (long)ptr, left, 0, 0, 0);
            if (written <= 0) {
                kclose(source);
                kclose(dest);
                return 0;
            }
            ptr += written;
            left -= written;
        }
    }
    ksys(SYS_fsync, dest, 0, 0, 0, 0, 0);
    kclose(source);
    kclose(dest);
    return 1;
}

static void sleep_msec(long msec) {
    struct ktimespec ts;
    ts.tv_sec = msec / 1000;
    ts.tv_nsec = (msec % 1000) * 1000000L;
    ksys(SYS_nanosleep, (long)&ts, 0, 0, 0, 0, 0);
}

static int run_program(const char *path, char **argv) {
    static char *envp[] = {
        "PATH=/bin:/sbin:/usr/bin:/usr/sbin",
        "HOME=/",
        "TERM=linux",
        "LANG=C",
        NULL,
    };
    long pid = ksys(SYS_fork, 0, 0, 0, 0, 0, 0);
    if (pid < 0) {
        say("fork failed\n");
        return 1;
    }
    if (pid == 0) {
        ksys(SYS_execve, (long)path, (long)argv, (long)envp, 0, 0, 0);
        say("exec failed: ");
        say(path);
        say("\n");
        ksys(SYS_exit, 127, 0, 0, 0, 0, 0);
        for (;;) {
        }
    }

    int status = 0;
    for (;;) {
        long waited = ksys(SYS_wait4, pid, (long)&status, 0, 0, 0, 0);
        if (waited >= 0) {
            break;
        }
        if (waited != -EINTR) {
            return 1;
        }
    }
    return status == 0 ? 0 : 1;
}

static int run_graphical_program(const char *path, char **argv) {
    static char *envp[] = {
        "PATH=/bin:/sbin:/usr/bin:/usr/sbin",
        "HOME=/root",
        "TERM=xterm-256color",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "XDG_RUNTIME_DIR=/run/kiki-wayland",
        "GDK_BACKEND=wayland",
        "GSK_RENDERER=cairo",
        "LIBSEAT_BACKEND=builtin",
        "WLR_BACKENDS=drm,libinput",
        "WLR_RENDERER=gles2",
        "XKB_DEFAULT_LAYOUT=kr",
        "FONTCONFIG_PATH=/etc/fonts",
        "KIKI_INSTALLER_TUI=/usr/bin/kiki-installer-tui",
        NULL,
    };
    long pid = ksys(SYS_fork, 0, 0, 0, 0, 0, 0);
    if (pid < 0) {
        say("graphical installer fork failed\n");
        return 1;
    }
    if (pid == 0) {
        int log_fd = kopen_mode("/run/kiki/gui-installer.log", O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (log_fd >= 0) {
            ksys(SYS_dup2, log_fd, STDOUT_FILENO, 0, 0, 0, 0);
            ksys(SYS_dup2, log_fd, STDERR_FILENO, 0, 0, 0, 0);
            if (log_fd > STDERR_FILENO) {
                ksys(SYS_close, log_fd, 0, 0, 0, 0, 0);
            }
        }
        ksys(SYS_execve, (long)path, (long)argv, (long)envp, 0, 0, 0);
        say("graphical installer exec failed: ");
        say(path);
        say("\n");
        ksys(SYS_exit, 127, 0, 0, 0, 0, 0);
        for (;;) {
        }
    }
    int status = 0;
    for (;;) {
        long waited = ksys(SYS_wait4, pid, (long)&status, 0, 0, 0, 0);
        if (waited >= 0) {
            break;
        }
        if (waited != -EINTR) {
            return 1;
        }
    }
    if ((status & 0x7f) == 0) {
        return (status >> 8) & 0xff;
    }
    return 128 + (status & 0x7f);
}

static int run_chroot_program_input(const char *root, const char *path, char **argv, const char *input) {
    static char *envp[] = {
        "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME=/",
        "TERM=linux",
        "LANG=C",
        NULL,
    };
    int pipes[2] = {-1, -1};
    int has_input = input && input[0];
    if (has_input && ksys(SYS_pipe, (long)pipes, 0, 0, 0, 0, 0) < 0) {
        say("pipe failed\n");
        return 1;
    }
    long pid = ksys(SYS_fork, 0, 0, 0, 0, 0, 0);
    if (pid < 0) {
        if (has_input) {
            kclose(pipes[0]);
            kclose(pipes[1]);
        }
        say("fork failed\n");
        return 1;
    }
    if (pid == 0) {
        if (has_input) {
            kclose(pipes[1]);
            ksys(SYS_dup2, pipes[0], STDIN_FILENO, 0, 0, 0, 0);
            if (pipes[0] > STDERR_FILENO) {
                kclose(pipes[0]);
            }
        }
        if (ksys(SYS_chroot, (long)root, 0, 0, 0, 0, 0) < 0 || ksys(SYS_chdir, (long)"/", 0, 0, 0, 0, 0) < 0) {
            say("chroot failed: ");
            say(root);
            say("\n");
            ksys(SYS_exit, 126, 0, 0, 0, 0, 0);
        }
        ksys(SYS_execve, (long)path, (long)argv, (long)envp, 0, 0, 0);
        say("exec failed in target root: ");
        say(path);
        say("\n");
        ksys(SYS_exit, 127, 0, 0, 0, 0, 0);
        for (;;) {
        }
    }

    if (has_input) {
        kclose(pipes[0]);
        write_all(pipes[1], input);
        kclose(pipes[1]);
    }

    int status = 0;
    for (;;) {
        long waited = ksys(SYS_wait4, pid, (long)&status, 0, 0, 0, 0);
        if (waited >= 0) {
            break;
        }
        if (waited != -EINTR) {
            return 1;
        }
    }
    return status == 0 ? 0 : 1;
}

static int run_chroot_program(const char *root, const char *path, char **argv) {
    return run_chroot_program_input(root, path, argv, "");
}

static int mount_one(const char *type, const char *target, const char *source, unsigned long flags, const char *data) {
    mkdir_one(target, 0755);
    if (ksys(SYS_mount, (long)source, (long)target, (long)type, (long)flags, (long)data, 0) < 0) {
        return 0;
    }
    return 1;
}

static int service_devtmpfs = 0;
static int service_proc = 0;
static int service_sysfs = 0;
static int service_console = 0;

static void setup_mounts(void) {
    mkdir_one("/dev", 0755);
    mkdir_one("/proc", 0755);
    mkdir_one("/run", 0755);
    mkdir_one("/sys", 0755);
    mkdir_one("/tmp", 01777);
    service_devtmpfs = mount_one("devtmpfs", "/dev", "devtmpfs", 0, "mode=0755");
    attach_console();
    service_console = 1;
    service_proc = mount_one("proc", "/proc", "proc", 0, "");
    service_sysfs = mount_one("sysfs", "/sys", "sysfs", 0, "");
}

static void logo(void) {
    say("\033[2J\033[H");
    say(" _  ___ _  ___ ___   ___  ____  \n");
    say("| |/ (_) |/ (_) _ \\ / _ \\/ ___| \n");
    say("| ' /| | ' /| | | | | | |\\___ \\ \n");
    say("| . \\| | . \\| |_| | |_| |___) |\n");
    say("|_|\\_\\_|_|\\_\\___/ \\___/|____/ \n");
    say("\n");
#ifdef KIKI_ENABLE_INSTALLER
    say("KIKI OS stage-1 installer\n");
#elif defined(KIKI_INSTALLED_STAGE1)
    say("KIKI OS installed systemd handoff\n");
#else
    say("KIKI OS boot smoke media\n");
#endif
    say("=========================\n\n");
}

static void fd_zero(unsigned long *set, size_t count) {
    for (size_t i = 0; i < count; i++) {
        set[i] = 0;
    }
}

static void fd_set_one(unsigned long *set, int fd) {
    set[(unsigned long)fd / (8 * sizeof(unsigned long))] |= 1UL << ((unsigned long)fd % (8 * sizeof(unsigned long)));
}

static int fd_is_set(unsigned long *set, int fd) {
    return (set[(unsigned long)fd / (8 * sizeof(unsigned long))] & (1UL << ((unsigned long)fd % (8 * sizeof(unsigned long))))) != 0;
}

static int read_line(char *buffer, size_t size) {
    if (!size) {
        return -1;
    }
    buffer[0] = 0;

    int fds[8];
    int count = 0;
    fds[count++] = STDIN_FILENO;
    const char *targets[] = {"/dev/tty0", "/dev/console", "/dev/ttyS0", NULL};
    for (int i = 0; targets[i] && count < (int)(sizeof(fds) / sizeof(fds[0])); i++) {
        int fd = kopen(targets[i], O_RDONLY | O_NOCTTY | O_NONBLOCK);
        if (fd >= 0) {
            fds[count++] = fd;
        }
    }

    size_t used = 0;
    for (;;) {
        unsigned long set[16];
        fd_zero(set, 16);
        int max_fd = -1;
        for (int i = 0; i < count; i++) {
            fd_set_one(set, fds[i]);
            if (fds[i] > max_fd) {
                max_fd = fds[i];
            }
        }

        long selected = ksys(SYS_select, max_fd + 1, (long)set, 0, 0, 0, 0);
        if (selected < 0) {
            if (selected == -EINTR) {
                continue;
            }
            break;
        }

        for (int i = 0; i < count; i++) {
            if (!fd_is_set(set, fds[i])) {
                continue;
            }
            char ch = 0;
            long got = ksys(SYS_read, fds[i], (long)&ch, 1, 0, 0, 0);
            if (got <= 0) {
                continue;
            }
            if (ch == '\n' || ch == '\r') {
                buffer[used] = 0;
                for (int j = 1; j < count; j++) {
                    kclose(fds[j]);
                }
                return 0;
            }
            if ((ch == '\b' || ch == 127) && used > 0) {
                buffer[--used] = 0;
                continue;
            }
            if (used + 1 < size) {
                buffer[used++] = ch;
                buffer[used] = 0;
            }
        }
    }

    for (int i = 1; i < count; i++) {
        kclose(fds[i]);
    }
    return -1;
}

static void tui_clear(void) {
    say("\033[2J\033[H");
}

static void tui_header(const char *title) {
    tui_clear();
    say("KIKI OS installer TUI\n");
    say("=====================\n");
    say(title);
    say("\n\n");
}

static void tui_wait(void) {
    char ignored[8];
    say("\nPress Enter to return to the installer menu...");
    read_line(ignored, sizeof(ignored));
}

static int is_candidate_disk(const char *name) {
    return !(starts_with(name, "loop") || starts_with(name, "ram") || starts_with(name, "sr") || starts_with(name, "fd"));
}

static int is_forbidden_install_target(const char *path) {
    return contains(path, "/dev/sr") || contains(path, "/dev/loop") || contains(path, "/dev/ram");
}

static void path3(char *out, size_t out_size, const char *a, const char *b, const char *c) {
    size_t pos = 0;
    pos = append_string(out, out_size, pos, a);
    pos = append_string(out, out_size, pos, b);
    append_string(out, out_size, pos, c);
}

static int file_exists(const char *path);

static int read_text_file(const char *path, char *buffer, size_t size) {
    if (size == 0) {
        return 0;
    }
    int fd = kopen(path, O_RDONLY);
    if (fd < 0) {
        buffer[0] = 0;
        return 0;
    }
    long got = ksys(SYS_read, fd, (long)buffer, (long)(size - 1), 0, 0, 0);
    kclose(fd);
    if (got <= 0) {
        buffer[0] = 0;
        return 0;
    }
    while (got > 0 && (buffer[got - 1] == '\n' || buffer[got - 1] == '\r' || buffer[got - 1] == ' ' || buffer[got - 1] == '\t')) {
        got--;
    }
    buffer[got] = 0;
    return 1;
}

static const char *base_name(const char *path) {
    const char *base = path;
    for (const char *p = path; *p; p++) {
        if (*p == '/') {
            base = p + 1;
        }
    }
    return base;
}

static int read_block_sectors(const char *target, u64 *out_sectors) {
    char path[256];
    char buffer[64];
    const char *name = base_name(target);
    path3(path, sizeof(path), "/sys/class/block/", name, "/size");
    if (!read_text_file(path, buffer, sizeof(buffer))) {
        path3(path, sizeof(path), "/sys/block/", name, "/size");
        if (!read_text_file(path, buffer, sizeof(buffer))) {
            return 0;
        }
    }
    *out_sectors = parse_u64(buffer);
    return *out_sectors > 0;
}

static int is_partition_path(const char *target) {
    char path[256];
    const char *name = base_name(target);
    path3(path, sizeof(path), "/sys/class/block/", name, "/partition");
    return file_exists(path);
}

static int is_whole_disk_path(const char *target) {
    char path[256];
    const char *name = base_name(target);
    if (!starts_with(target, "/dev/") || is_forbidden_install_target(target)) {
        return 0;
    }
    path3(path, sizeof(path), "/sys/block/", name, "/size");
    if (!file_exists(path)) {
        return 0;
    }
    return !is_partition_path(target);
}

static u64 read_mem_total_mib(void) {
    char buffer[512];
    if (!read_text_file("/proc/meminfo", buffer, sizeof(buffer))) {
        return 0;
    }
    const char *needle = "MemTotal:";
    for (char *p = buffer; *p; p++) {
        if (!starts_with(p, needle)) {
            continue;
        }
        p += kstrlen(needle);
        while (*p == ' ' || *p == '\t') {
            p++;
        }
        return parse_u64(p) / 1024ULL;
    }
    return 0;
}

static void put_le32(unsigned char *out, u64 value) {
    out[0] = (unsigned char)(value & 0xff);
    out[1] = (unsigned char)((value >> 8) & 0xff);
    out[2] = (unsigned char)((value >> 16) & 0xff);
    out[3] = (unsigned char)((value >> 24) & 0xff);
}

static void write_mbr_entry(unsigned char *entry, unsigned char type, u64 start, u64 sectors) {
    entry[0] = 0x00;
    entry[1] = 0xfe;
    entry[2] = 0xff;
    entry[3] = 0xff;
    entry[4] = type;
    entry[5] = 0xfe;
    entry[6] = 0xff;
    entry[7] = 0xff;
    put_le32(entry + 8, start);
    put_le32(entry + 12, sectors);
}

static void calculate_auto_partition_layout(u64 total_mib, u64 mem_mib, int omit_swap, u64 *esp_mib, u64 *swap_mib, u64 *root_mib) {
    u64 root_min_mib = 2048ULL;
    u64 reserve_mib = 1ULL;
    u64 desired_swap = mem_mib ? mem_mib * 2ULL : 1024ULL;
    *esp_mib = total_mib >= 8192ULL ? 768ULL : 512ULL;
    if (omit_swap) {
        *swap_mib = 0;
        *root_mib = total_mib > *esp_mib + reserve_mib ? total_mib - *esp_mib - reserve_mib : 0;
        return;
    }
    if (desired_swap < 512ULL) {
        desired_swap = 512ULL;
    }
    if (desired_swap > 16384ULL) {
        desired_swap = 16384ULL;
    }
    if (total_mib <= *esp_mib + root_min_mib + reserve_mib) {
        *swap_mib = 0;
        *root_mib = 0;
        return;
    }
    u64 available_for_swap = total_mib - *esp_mib - root_min_mib - reserve_mib;
    *swap_mib = desired_swap <= available_for_swap ? desired_swap : available_for_swap;
    if (*swap_mib < 512ULL) {
        *swap_mib = 0;
    }
    *root_mib = total_mib - *esp_mib - *swap_mib - reserve_mib;
}

static void show_auto_partition_layout(const char *target, const char *esp_part, const char *swap_part, const char *root_part, u64 disk_mib, u64 mem_mib, u64 esp_mib, u64 swap_mib, u64 root_mib, int omit_swap) {
    char line[256];
    size_t out = 0;
    say("\nAutomatic partition plan\n");
    say("------------------------\n");
    out = append_string(line, sizeof(line), out, "target disk: ");
    out = append_string(line, sizeof(line), out, target);
    out = append_string(line, sizeof(line), out, " (");
    out = append_u64(line, sizeof(line), out, disk_mib);
    append_string(line, sizeof(line), out, " MiB)\n");
    say(line);
    out = 0;
    out = append_string(line, sizeof(line), out, "memory: ");
    out = append_u64(line, sizeof(line), out, mem_mib);
    append_string(line, sizeof(line), out, " MiB, swap target: memory x2 capped at 16384 MiB\n");
    say(line);
    out = 0;
    out = append_string(line, sizeof(line), out, "  1) ");
    out = append_string(line, sizeof(line), out, esp_part);
    out = append_string(line, sizeof(line), out, "  EFI/FAT32  ");
    out = append_u64(line, sizeof(line), out, esp_mib);
    append_string(line, sizeof(line), out, " MiB\n");
    say(line);
    if (swap_mib > 0) {
        out = 0;
        out = append_string(line, sizeof(line), out, "  2) ");
        out = append_string(line, sizeof(line), out, swap_part);
        out = append_string(line, sizeof(line), out, "  Linux swap ");
        out = append_u64(line, sizeof(line), out, swap_mib);
        append_string(line, sizeof(line), out, " MiB\n");
        say(line);
        out = 0;
        out = append_string(line, sizeof(line), out, "  3) ");
        out = append_string(line, sizeof(line), out, root_part);
        out = append_string(line, sizeof(line), out, "  ext4 root  ");
        out = append_u64(line, sizeof(line), out, root_mib);
        append_string(line, sizeof(line), out, " MiB\n");
        say(line);
    } else {
        out = 0;
        out = append_string(line, sizeof(line), out, "  2) ");
        out = append_string(line, sizeof(line), out, root_part);
        out = append_string(line, sizeof(line), out, "  ext4 root  ");
        out = append_u64(line, sizeof(line), out, root_mib);
        append_string(line, sizeof(line), out, " MiB\n");
        say(line);
        if (omit_swap) {
            say("  swap omitted by Kubernetes profile policy.\n");
        } else {
            say("  swap omitted because the disk is too small for a useful swap partition.\n");
        }
    }
}

static int write_guided_mbr(const char *target, int omit_swap, u64 *esp_start, u64 *esp_sectors, u64 *swap_start, u64 *swap_sectors, u64 *root_start, u64 *root_sectors, u64 *disk_mib, u64 *mem_mib, u64 *esp_mib, u64 *swap_mib, u64 *root_mib) {
    u64 total_sectors = 0;
    if (!read_block_sectors(target, &total_sectors)) {
        say("Cannot read target disk size from sysfs.\n");
        return 0;
    }
    *disk_mib = total_sectors / 2048ULL;
    *mem_mib = read_mem_total_mib();
    calculate_auto_partition_layout(*disk_mib, *mem_mib, omit_swap, esp_mib, swap_mib, root_mib);
    if (*root_mib < 2048ULL) {
        say("Target disk is too small; need at least about 3 GiB for ESP + root.\n");
        return 0;
    }

    *esp_start = 2048ULL;
    *esp_sectors = *esp_mib * 2048ULL;
    *swap_start = *esp_start + *esp_sectors;
    *swap_sectors = *swap_mib * 2048ULL;
    *root_start = *swap_start + *swap_sectors;
    if (total_sectors <= *root_start + 2048ULL) {
        say("Target disk has no room for root partition.\n");
        return 0;
    }
    *root_sectors = total_sectors - *root_start - 2048ULL;

    unsigned char mbr[512];
    for (int i = 0; i < 512; i++) {
        mbr[i] = 0;
    }
    write_mbr_entry(mbr + 446, 0xef, *esp_start, *esp_sectors);
    if (*swap_sectors > 0) {
        write_mbr_entry(mbr + 462, 0x82, *swap_start, *swap_sectors);
        write_mbr_entry(mbr + 478, 0x83, *root_start, *root_sectors);
    } else {
        write_mbr_entry(mbr + 462, 0x83, *root_start, *root_sectors);
    }
    mbr[510] = 0x55;
    mbr[511] = 0xaa;

    int fd = kopen(target, O_RDWR);
    if (fd < 0) {
        say("Cannot open target disk for partitioning.\n");
        return 0;
    }
    long written = ksys(SYS_write, fd, (long)mbr, sizeof(mbr), 0, 0, 0);
    ksys(SYS_fsync, fd, 0, 0, 0, 0, 0);
    ksys(SYS_ioctl, fd, BLKRRPART, 0, 0, 0, 0);
    kclose(fd);
    if (written != (long)sizeof(mbr)) {
        say("Failed to write MBR partition table.\n");
        return 0;
    }
    return 1;
}

static void partition_path(const char *target, int partno, char *out, size_t out_size) {
    size_t pos = 0;
    const char *base = base_name(target);
    pos = append_string(out, out_size, pos, target);
    size_t len = kstrlen(base);
    if (len > 0 && base[len - 1] >= '0' && base[len - 1] <= '9') {
        pos = append_string(out, out_size, pos, "p");
    }
    append_u64(out, out_size, pos, (u64)partno);
}

static int wait_for_file(const char *path) {
    for (int i = 0; i < 50; i++) {
        if (file_exists(path)) {
            return 1;
        }
        sleep_msec(100);
    }
    return 0;
}

static u64 disk_size_bytes(const char *name) {
    char path[256];
    char buffer[64];
    path3(path, sizeof(path), "/sys/block/", name, "/size");
    int fd = kopen(path, O_RDONLY);
    if (fd < 0) {
        return 0;
    }
    long got = ksys(SYS_read, fd, (long)buffer, sizeof(buffer) - 1, 0, 0, 0);
    kclose(fd);
    if (got <= 0) {
        return 0;
    }
    buffer[got] = 0;
    return parse_u64(buffer) * 512ULL;
}

static void list_disks(void) {
    int fd = kopen("/sys/block", O_RDONLY | O_DIRECTORY);
    if (fd < 0) {
        say("Cannot read /sys/block.\n");
        return;
    }

    char buf[4096];
    say("Candidate target disks:\n");
    for (;;) {
        long got = ksys(SYS_getdents64, fd, (long)buf, sizeof(buf), 0, 0, 0);
        if (got <= 0) {
            break;
        }
        long pos = 0;
        while (pos < got) {
            struct linux_dirent64 *entry = (struct linux_dirent64 *)(buf + pos);
            const char *name = entry->d_name;
            if (name[0] != '.' && is_candidate_disk(name)) {
                char line[256];
                size_t out = 0;
                out = append_string(line, sizeof(line), out, "  /dev/");
                out = append_string(line, sizeof(line), out, name);
                out = append_string(line, sizeof(line), out, "  ");
                out = append_u64(line, sizeof(line), out, disk_size_bytes(name) / 1024ULL / 1024ULL);
                append_string(line, sizeof(line), out, " MiB\n");
                say(line);
            }
            pos += entry->d_reclen;
        }
    }
    kclose(fd);
}

static int find_default_install_disk(char *out, size_t out_size) {
    int fd = kopen("/sys/block", O_RDONLY | O_DIRECTORY);
    if (fd < 0) {
        return 0;
    }

    char buf[4096];
    char best[96];
    u64 best_mib = 0;
    best[0] = 0;
    for (;;) {
        long got = ksys(SYS_getdents64, fd, (long)buf, sizeof(buf), 0, 0, 0);
        if (got <= 0) {
            break;
        }
        long pos = 0;
        while (pos < got) {
            struct linux_dirent64 *entry = (struct linux_dirent64 *)(buf + pos);
            const char *name = entry->d_name;
            if (name[0] != '.' && is_candidate_disk(name)) {
                u64 mib = disk_size_bytes(name) / 1024ULL / 1024ULL;
                if (mib >= 3072ULL && mib > best_mib) {
                    best_mib = mib;
                    copy_string(best, sizeof(best), name);
                }
            }
            pos += entry->d_reclen;
        }
    }
    kclose(fd);
    if (!best[0]) {
        return 0;
    }
    size_t pos = 0;
    pos = append_string(out, out_size, pos, "/dev/");
    append_string(out, out_size, pos, best);
    return 1;
}

static int get_default_install_disk(char *out, size_t out_size) {
    if (preferred_install_disk[0] && is_whole_disk_path(preferred_install_disk)) {
        copy_string(out, out_size, preferred_install_disk);
        return 1;
    }
    return find_default_install_disk(out, out_size);
}

static void remember_preferred_install_disk(const char *target) {
    if (target && target[0] && is_whole_disk_path(target)) {
        copy_string(preferred_install_disk, sizeof(preferred_install_disk), target);
    }
}

static int file_exists(const char *path) {
    int fd = kopen(path, O_RDONLY);
    if (fd < 0) {
        return 0;
    }
    kclose(fd);
    return 1;
}

static int remember_install_image(const char *path, char *out, size_t out_size) {
    if (!file_exists(path)) {
        return 0;
    }
    copy_string(out, out_size, path);
    return 1;
}

static int remember_media_root(const char *root, char *out, size_t out_size) {
    char path[384];
    path3(path, sizeof(path), root, "/manifest.json", "");
    if (file_exists(path)) {
        copy_string(out, out_size, root);
        return 1;
    }
    path3(path, sizeof(path), root, "/kiki/repo/index.x86_64.json", "");
    if (file_exists(path)) {
        copy_string(out, out_size, root);
        return 1;
    }
    path3(path, sizeof(path), root, "/install/kiki-stage1.img", "");
    if (file_exists(path)) {
        copy_string(out, out_size, root);
        return 1;
    }
    return 0;
}

static int try_mount_media_root(const char *device, char *out, size_t out_size) {
    mkdir_one("/run/install-media", 0755);
    int mounted_here = 0;
    long mounted = ksys(SYS_mount, (long)device, (long)"/run/install-media", (long)"iso9660", MS_RDONLY, (long)"", 0);
    if (mounted < 0) {
        if (mounted != -EBUSY) {
            return 0;
        }
    } else {
        mounted_here = 1;
    }
    if (remember_media_root("/run/install-media", out, out_size)) {
        return 1;
    }
    if (mounted_here) {
        ksys(SYS_umount2, (long)"/run/install-media", 0, 0, 0, 0, 0);
    }
    return 0;
}

static int find_install_media_root(char *out, size_t out_size) {
    if (remember_media_root("/run/install-media", out, out_size)) {
        return 1;
    }

    const char *fixed[] = {"/dev/cdrom", "/dev/sr0", "/dev/sr1", "/dev/sr2", "/dev/sr3", "/dev/hdc", "/dev/hdd", NULL};
    for (int i = 0; fixed[i]; i++) {
        if (try_mount_media_root(fixed[i], out, out_size)) {
            return 1;
        }
    }

    int fd = kopen("/sys/block", O_RDONLY | O_DIRECTORY);
    if (fd < 0) {
        return 0;
    }
    char buf[4096];
    int found = 0;
    for (;;) {
        long got = ksys(SYS_getdents64, fd, (long)buf, sizeof(buf), 0, 0, 0);
        if (got <= 0) {
            break;
        }
        long pos = 0;
        while (pos < got) {
            struct linux_dirent64 *entry = (struct linux_dirent64 *)(buf + pos);
            if (starts_with(entry->d_name, "sr")) {
                char dev[320];
                path3(dev, sizeof(dev), "/dev/", entry->d_name, "");
                if (try_mount_media_root(dev, out, out_size)) {
                    found = 1;
                    break;
                }
            }
            pos += entry->d_reclen;
        }
        if (found) {
            break;
        }
    }
    kclose(fd);
    return found;
}

static int try_mount_install_media(const char *device, char *out, size_t out_size) {
    mkdir_one("/run/install-media", 0755);
    int mounted_here = 0;
    long mounted = ksys(SYS_mount, (long)device, (long)"/run/install-media", (long)"iso9660", MS_RDONLY, (long)"", 0);
    if (mounted < 0) {
        if (mounted != -EBUSY) {
            return 0;
        }
    } else {
        mounted_here = 1;
    }
    if (remember_install_image("/run/install-media/install/kiki-stage1.img", out, out_size)) {
        return 1;
    }
    if (mounted_here) {
        ksys(SYS_umount2, (long)"/run/install-media", 0, 0, 0, 0, 0);
    }
    return 0;
}

static int find_install_image(char *out, size_t out_size) {
    if (remember_install_image("/install/kiki-stage1.img", out, out_size)) {
        return 1;
    }
    if (remember_install_image("/run/install-media/install/kiki-stage1.img", out, out_size)) {
        return 1;
    }

    const char *fixed[] = {"/dev/cdrom", "/dev/sr0", "/dev/sr1", "/dev/sr2", "/dev/sr3", "/dev/hdc", "/dev/hdd", NULL};
    for (int i = 0; fixed[i]; i++) {
        if (try_mount_install_media(fixed[i], out, out_size)) {
            return 1;
        }
    }

    int fd = kopen("/sys/block", O_RDONLY | O_DIRECTORY);
    if (fd < 0) {
        return 0;
    }
    char buf[4096];
    int found = 0;
    for (;;) {
        long got = ksys(SYS_getdents64, fd, (long)buf, sizeof(buf), 0, 0, 0);
        if (got <= 0) {
            break;
        }
        long pos = 0;
        while (pos < got) {
            struct linux_dirent64 *entry = (struct linux_dirent64 *)(buf + pos);
            if (starts_with(entry->d_name, "sr")) {
                char dev[320];
                path3(dev, sizeof(dev), "/dev/", entry->d_name, "");
                if (try_mount_install_media(dev, out, out_size)) {
                    found = 1;
                    break;
                }
            }
            pos += entry->d_reclen;
        }
        if (found) {
            break;
        }
    }
    kclose(fd);
    return found;
}

static int copy_image_to_disk(const char *image, const char *target) {
    int source = kopen(image, O_RDONLY);
    if (source < 0) {
        say("Cannot open install image: ");
        say(image);
        say("\n");
        return 1;
    }
    int dest = kopen(target, O_WRONLY);
    if (dest < 0) {
        say("Cannot open target: ");
        say(target);
        say("\n");
        kclose(source);
        return 1;
    }

    u64 total = 0;
    u64 next_report = 64ULL * 1024ULL * 1024ULL;
    for (;;) {
        long got = ksys(SYS_read, source, (long)copy_buffer, sizeof(copy_buffer), 0, 0, 0);
        if (got == 0) {
            break;
        }
        if (got < 0) {
            say("Read from source media failed.\n");
            kclose(source);
            kclose(dest);
            return 1;
        }
        long left = got;
        char *ptr = copy_buffer;
        while (left > 0) {
            long written = ksys(SYS_write, dest, (long)ptr, left, 0, 0, 0);
            if (written <= 0) {
                say("Write to target disk failed.\n");
                kclose(source);
                kclose(dest);
                return 1;
            }
            ptr += written;
            left -= written;
        }
        total += (u64)got;
        if (total >= next_report) {
            char line[128];
            size_t out = 0;
            out = append_string(line, sizeof(line), out, "Copied ");
            out = append_u64(line, sizeof(line), out, total / 1024ULL / 1024ULL);
            append_string(line, sizeof(line), out, " MiB...\n");
            say(line);
            next_report += 64ULL * 1024ULL * 1024ULL;
        }
    }

    ksys(SYS_fsync, dest, 0, 0, 0, 0, 0);
    kclose(source);
    kclose(dest);

    char line[160];
    size_t out = 0;
    out = append_string(line, sizeof(line), out, "Install copy complete: ");
    out = append_u64(line, sizeof(line), out, total / 1024ULL / 1024ULL);
    append_string(line, sizeof(line), out, " MiB written.\n");
    say(line);
    return 0;
}

static void smoke_status(void) {
    say("kernel: online\n");
    say("initramfs: online\n");
    say("init: /init handoff completed\n\n");
}

static void show_cmdline(void) {
    int fd = kopen("/proc/cmdline", O_RDONLY);
    if (fd >= 0) {
        char buffer[1024];
        long got = ksys(SYS_read, fd, (long)buffer, sizeof(buffer) - 1, 0, 0, 0);
        kclose(fd);
        if (got > 0) {
            buffer[got] = 0;
            say("cmdline: ");
            say(buffer);
            say("\n");
        }
    }
}

static void service_line(const char *name, int ok) {
    say(ok ? "[ OK ] " : "[FAIL] ");
    say(name);
    say("\n");
}

static void show_services(void) {
    say("basic services:\n");
    service_line("devtmpfs on /dev", service_devtmpfs);
    service_line("console attached", service_console);
    service_line("procfs on /proc", service_proc);
    service_line("sysfs on /sys", service_sysfs);
    service_line("runtime directories /run /tmp", 1);
    say("\n");
}

static void show_file(const char *label, const char *path) {
    int fd = kopen(path, O_RDONLY);
    if (fd < 0) {
        say("Cannot open ");
        say(path);
        say("\n");
        return;
    }
    if (label && label[0]) {
        say(label);
        say(":\n");
    }
    char buffer[768];
    for (;;) {
        long got = ksys(SYS_read, fd, (long)buffer, sizeof(buffer), 0, 0, 0);
        if (got <= 0) {
            break;
        }
        write_bytes(STDOUT_FILENO, buffer, (size_t)got);
    }
    kclose(fd);
    say("\n");
}

static void show_disk_tools(void) {
    say("\nDisk tools\n");
    say("----------\n");
    list_disks();
    say("\nKernel partition table:\n");
    show_file("", "/proc/partitions");
    say("Guided install partitions the whole selected disk into ESP + root and extracts selected packages.\n");
}

static void show_network_tools(void) {
    int fd = kopen("/sys/class/net", O_RDONLY | O_DIRECTORY);
    say("\nNetwork tools\n");
    say("-------------\n");
    say("installed default: systemd-networkd DHCP on wired interfaces (en* eth*)\n");
    say("install-time modes: dhcp, static IPv4, or off\n");
    if (fd < 0) {
        say("Cannot read /sys/class/net.\n");
        return;
    }

    char buf[4096];
    int count = 0;
    for (;;) {
        long got = ksys(SYS_getdents64, fd, (long)buf, sizeof(buf), 0, 0, 0);
        if (got <= 0) {
            break;
        }
        long pos = 0;
        while (pos < got) {
            struct linux_dirent64 *entry = (struct linux_dirent64 *)(buf + pos);
            const char *name = entry->d_name;
            if (name[0] != '.') {
                char state_path[256];
                char mac_path[256];
                char carrier_path[256];
                char state[64];
                char mac[64];
                char carrier[16];
                path3(state_path, sizeof(state_path), "/sys/class/net/", name, "/operstate");
                path3(mac_path, sizeof(mac_path), "/sys/class/net/", name, "/address");
                path3(carrier_path, sizeof(carrier_path), "/sys/class/net/", name, "/carrier");
                if (!read_text_file(state_path, state, sizeof(state))) {
                    copy_string(state, sizeof(state), "unknown");
                }
                if (!read_text_file(mac_path, mac, sizeof(mac))) {
                    copy_string(mac, sizeof(mac), "unknown");
                }
                if (!read_text_file(carrier_path, carrier, sizeof(carrier))) {
                    copy_string(carrier, sizeof(carrier), "n/a");
                }
                say("  ");
                say(name);
                say("  state=");
                say(state);
                say("  carrier=");
                say(carrier);
                say("  mac=");
                say(mac);
                say("\n");
                count++;
            }
            pos += entry->d_reclen;
        }
    }
    kclose(fd);
    if (!count) {
        say("  no network interfaces found\n");
    }
    say("\nThe installer writes a systemd-networkd profile into the target rootfs.\n");
}

static char package_index_buffer[128 * 1024];
#define MAX_SELECTED_PACKAGES 96
#define PACKAGE_NAME_LEN 64
static char selected_packages[MAX_SELECTED_PACKAGES][PACKAGE_NAME_LEN];
static int selected_package_count = 0;
static char selected_package_profile[PACKAGE_NAME_LEN] = "minimal-systemd";
static char selected_container_runtime[32] = "none";
static char selected_locale[64] = "ko_KR.UTF-8";
static char selected_keymap[32] = "kr";
static char selected_timezone[64] = "Asia/Seoul";
static char selected_ai_mode[16] = "local";
static char selected_ai_endpoint[256] = "http://127.0.0.1:8080/v1/chat/completions";
static char selected_ai_model[64] = "kiki-ops";

static int read_small_file_raw(const char *path, char *buffer, size_t size, long *out_len) {
    if (size == 0) {
        return 0;
    }
    int fd = kopen(path, O_RDONLY);
    if (fd < 0) {
        buffer[0] = 0;
        return 0;
    }
    long got = ksys(SYS_read, fd, (long)buffer, (long)(size - 1), 0, 0, 0);
    kclose(fd);
    if (got <= 0) {
        buffer[0] = 0;
        return 0;
    }
    buffer[got] = 0;
    if (out_len) {
        *out_len = got;
    }
    return 1;
}

static void show_package_names_from_index(const char *path) {
    long len = 0;
    if (!read_small_file_raw(path, package_index_buffer, sizeof(package_index_buffer), &len)) {
        say("Cannot read package repository index.\n");
        return;
    }

    char unique[MAX_SELECTED_PACKAGES][PACKAGE_NAME_LEN];
    int records = 0;
    int unique_count = 0;
    int shown = 0;
    for (int i = 0; i < MAX_SELECTED_PACKAGES; i++) {
        unique[i][0] = 0;
    }
    for (long i = 0; i < len; i++) {
        if (!starts_with(package_index_buffer + i, "\"name\"")) {
            continue;
        }
        records++;
        if (shown < 16) {
            char *p = package_index_buffer + i;
            while (*p && *p != ':') {
                p++;
            }
            while (*p && *p != '"') {
                p++;
            }
            if (*p == '"') {
                p++;
            }
            char *value = p;
            while (*p && *p != '"') {
                p++;
            }
            say("  - ");
            write_bytes(STDOUT_FILENO, value, (size_t)(p - value));
            say("\n");
            shown++;
        }
        char value[PACKAGE_NAME_LEN];
        char *p = package_index_buffer + i;
        while (*p && *p != ':') {
            p++;
        }
        while (*p && *p != '"') {
            p++;
        }
        if (*p == '"') {
            p++;
        }
        size_t used = 0;
        while (*p && *p != '"' && used + 1 < sizeof(value)) {
            value[used++] = *p++;
        }
        value[used] = 0;
        int seen = 0;
        for (int j = 0; j < unique_count; j++) {
            if (kstrcmp(unique[j], value) == 0) {
                seen = 1;
                break;
            }
        }
        if (!seen && unique_count < MAX_SELECTED_PACKAGES) {
            copy_string(unique[unique_count], PACKAGE_NAME_LEN, value);
            unique_count++;
        }
    }

    char line[96];
    size_t out = 0;
    out = append_string(line, sizeof(line), out, "package records: ");
    out = append_u64(line, sizeof(line), out, (u64)records);
    out = append_string(line, sizeof(line), out, "\nunique package names: ");
    out = append_u64(line, sizeof(line), out, (u64)unique_count);
    append_string(line, sizeof(line), out, "\n");
    say(line);
    if (records > shown) {
        say("  ...more packages are listed in the repository index.\n");
    }
}

static int json_name_value_at(char *p, char *out, size_t out_size) {
    if (!starts_with(p, "\"name\"")) {
        return 0;
    }
    while (*p && *p != ':') {
        p++;
    }
    if (*p != ':') {
        return 0;
    }
    p++;
    while (*p && *p != '"') {
        p++;
    }
    if (*p != '"') {
        return 0;
    }
    p++;
    size_t used = 0;
    while (*p && *p != '"' && used + 1 < out_size) {
        out[used++] = *p++;
    }
    out[used] = 0;
    return used > 0;
}

static int json_file_value_before_name(char *buffer, long name_offset, char *out, size_t out_size) {
    long start = name_offset > 1024 ? name_offset - 1024 : 0;
    char *best = NULL;
    for (long i = start; i < name_offset; i++) {
        if (starts_with(buffer + i, "\"file\"")) {
            best = buffer + i;
        }
    }
    if (!best) {
        return 0;
    }
    while (*best && *best != ':') {
        best++;
    }
    if (*best != ':') {
        return 0;
    }
    best++;
    while (*best && *best != '"') {
        best++;
    }
    if (*best != '"') {
        return 0;
    }
    best++;
    size_t used = 0;
    while (*best && *best != '"' && used + 1 < out_size) {
        out[used++] = *best++;
    }
    out[used] = 0;
    return used > 0;
}

static int find_package_index_path(char *out, size_t out_size) {
    char root[256];
    if (!find_install_media_root(root, sizeof(root))) {
        return 0;
    }
    path3(out, out_size, root, "/kiki/repo/index.x86_64.json", "");
    return file_exists(out);
}

static int selected_index(const char *name) {
    for (int i = 0; i < selected_package_count; i++) {
        if (kstrcmp(selected_packages[i], name) == 0) {
            return i;
        }
    }
    return -1;
}

static void selected_clear(void) {
    selected_package_count = 0;
    for (int i = 0; i < MAX_SELECTED_PACKAGES; i++) {
        selected_packages[i][0] = 0;
    }
}

static void selected_set_profile(const char *profile) {
    copy_string(selected_package_profile, sizeof(selected_package_profile), profile && profile[0] ? profile : "custom");
}

static void selected_set_runtime(const char *runtime) {
    copy_string(selected_container_runtime, sizeof(selected_container_runtime), runtime && runtime[0] ? runtime : "none");
}

static int selected_profile_is_kubernetes(void) {
    return starts_with(selected_package_profile, "kiki-kube-");
}

static int selected_profile_is_kube_compute(void) {
    return kstrcmp(selected_package_profile, "kiki-kube-compute") == 0 ||
           kstrcmp(selected_package_profile, "kiki-kube-compute-containerd") == 0 ||
           kstrcmp(selected_package_profile, "kiki-kube-node") == 0;
}

static int selected_runtime_is_containerd(void) {
    return kstrcmp(selected_container_runtime, "containerd") == 0;
}

static const char *selected_kubernetes_role(void) {
    if (!selected_profile_is_kubernetes()) {
        return "none";
    }
    if (starts_with(selected_package_profile, "kiki-kube-bootstrap")) {
        return "bootstrap-control-plane";
    }
    if (starts_with(selected_package_profile, "kiki-kube-control") ||
        kstrcmp(selected_package_profile, "kiki-kube-controller") == 0) {
        return "control-plane";
    }
    return "compute";
}

static const char *selected_kubeadm_action(void) {
    if (!selected_profile_is_kubernetes()) {
        return "";
    }
    return kstrcmp(selected_kubernetes_role(), "bootstrap-control-plane") == 0 ? "init" : "join";
}

static const char *selected_kubeadm_template(void) {
    const char *role = selected_kubernetes_role();
    if (kstrcmp(role, "bootstrap-control-plane") == 0) {
        return "/etc/kubernetes/kiki/kubeadm-init.yaml";
    }
    if (kstrcmp(role, "control-plane") == 0) {
        return "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml";
    }
    if (kstrcmp(role, "compute") == 0) {
        return "/etc/kubernetes/kiki/kubeadm-join-compute.yaml";
    }
    return "";
}

static const char *selected_kubeadm_command(void) {
    if (!selected_profile_is_kubernetes()) {
        return "";
    }
    return kstrcmp(selected_kubeadm_action(), "init") == 0 ?
        "kubeadm init --config /etc/kubernetes/kiki/kubeadm.local.yaml" :
        "kubeadm join --config /etc/kubernetes/kiki/kubeadm.local.yaml";
}

static const char *selected_kubeadm_cri_socket(void) {
    if (!selected_profile_is_kubernetes()) {
        return "";
    }
    return selected_runtime_is_containerd() ?
        "unix:///run/containerd/containerd.sock" :
        "unix:///var/run/crio/crio.sock";
}

static int selected_kubernetes_control_plane(void) {
    const char *role = selected_kubernetes_role();
    return kstrcmp(role, "bootstrap-control-plane") == 0 || kstrcmp(role, "control-plane") == 0;
}

static int selected_add(const char *name) {
    if (!name || !name[0]) {
        return 0;
    }
    if (selected_index(name) >= 0) {
        return 0;
    }
    if (selected_package_count >= MAX_SELECTED_PACKAGES) {
        say("Selected package list is full.\n");
        return 0;
    }
    copy_string(selected_packages[selected_package_count], PACKAGE_NAME_LEN, name);
    selected_package_count++;
    return 1;
}

static int selected_remove(const char *name) {
    int removed = 0;
    for (int i = 0; i < selected_package_count; i++) {
        if (kstrcmp(selected_packages[i], name) != 0) {
            continue;
        }
        for (int j = i; j + 1 < selected_package_count; j++) {
            copy_string(selected_packages[j], PACKAGE_NAME_LEN, selected_packages[j + 1]);
        }
        selected_package_count--;
        selected_packages[selected_package_count][0] = 0;
        i--;
        removed++;
    }
    return removed;
}

static void apply_ai_to_selected_packages(void) {
    if (kstrcmp(selected_ai_mode, "off") == 0) {
        selected_remove("kiki-ai-console");
        selected_remove("llama-cpp");
        return;
    }
    selected_add("kiki-ai-console");
    if (kstrcmp(selected_ai_mode, "local") == 0) {
        selected_add("llama-cpp");
    } else {
        selected_remove("llama-cpp");
    }
}

static void show_selected_packages(void) {
    char line[128];
    if (selected_package_count == 0) {
        say("  no packages selected\n");
        return;
    }
    for (int i = 0; i < selected_package_count; i++) {
        size_t out = 0;
        out = append_string(line, sizeof(line), out, "  ");
        out = append_u64(line, sizeof(line), out, (u64)(i + 1));
        out = append_string(line, sizeof(line), out, ") ");
        out = append_string(line, sizeof(line), out, selected_packages[i]);
        append_string(line, sizeof(line), out, "\n");
        say(line);
    }
}

static int package_exists_in_index(const char *index_path, const char *name) {
    long len = 0;
    if (!read_small_file_raw(index_path, package_index_buffer, sizeof(package_index_buffer), &len)) {
        return 0;
    }
    for (long i = 0; i < len; i++) {
        char value[PACKAGE_NAME_LEN];
        if (json_name_value_at(package_index_buffer + i, value, sizeof(value)) && kstrcmp(value, name) == 0) {
            return 1;
        }
    }
    return 0;
}

static int find_package_file_for_name(const char *index_path, const char *media_root, const char *name, char *out, size_t out_size) {
    long len = 0;
    char filename[128];
    char selected[128];
    selected[0] = 0;
    if (!read_small_file_raw(index_path, package_index_buffer, sizeof(package_index_buffer), &len)) {
        return 0;
    }
    for (long i = 0; i < len; i++) {
        char value[PACKAGE_NAME_LEN];
        if (json_name_value_at(package_index_buffer + i, value, sizeof(value)) && kstrcmp(value, name) == 0) {
            if (json_file_value_before_name(package_index_buffer, i, filename, sizeof(filename))) {
                copy_string(selected, sizeof(selected), filename);
            }
        }
    }
    if (!selected[0]) {
        return 0;
    }
    path3(out, out_size, media_root, "/kiki/packages/x86_64/", selected);
    return file_exists(out);
}

static int select_all_packages_from_index(const char *index_path) {
    long len = 0;
    int added = 0;
    if (!read_small_file_raw(index_path, package_index_buffer, sizeof(package_index_buffer), &len)) {
        say("Cannot read package repository index.\n");
        return 0;
    }
    for (long i = 0; i < len; i++) {
        char value[PACKAGE_NAME_LEN];
        if (json_name_value_at(package_index_buffer + i, value, sizeof(value))) {
            if (selected_add(value)) {
                added++;
            }
        }
    }
    return added;
}

static int select_package_set(const char *index_path, const char *profile, const char *label, const char *const packages[]) {
    int added = 0;
    selected_set_profile(profile);
    for (int i = 0; packages[i]; i++) {
        if (!index_path[0] || package_exists_in_index(index_path, packages[i])) {
            if (selected_add(packages[i])) {
                added++;
            }
        }
    }
    apply_ai_to_selected_packages();
    char line[128];
    size_t out = 0;
    out = append_string(line, sizeof(line), out, label);
    out = append_string(line, sizeof(line), out, " selected: ");
    out = append_u64(line, sizeof(line), out, (u64)selected_package_count);
    append_string(line, sizeof(line), out, " packages\n");
    say(line);
    if (added == 0) {
        say("No new packages were added.\n");
    }
    return added;
}

static void select_minimal_systemd_packages(const char *index_path) {
    selected_set_runtime("none");
    const char *const defaults[] = {
        "base-files", "linux", "glibc", "libxcrypt", "zlib", "expat", "openssl",
        "attr", "libcap", "libseccomp", "acl", "ncurses", "util-linux", "cfdisk", "xz", "zstd",
        "kmod", "dbus", "systemd", "bash", "busybox", "coreutils", "findutils",
        "grep", "sed", "gawk", "tar", "gzip", "python", "e2fsprogs", "shadow",
        "sudo", "iproute2", "ca-certificates", "openssh", "curl", "ki2ctl", "kiki-agent", "kiki-netconfig", "kiki-installer-tui",
        NULL,
    };
    select_package_set(index_path, "minimal-systemd", "minimal-systemd package set", defaults);
}

static void select_server_core_packages(const char *index_path) {
    selected_set_runtime("none");
    const char *const defaults[] = {
        "base-files", "linux", "glibc", "libxcrypt", "zlib", "expat", "openssl",
        "attr", "libcap", "libseccomp", "acl", "ncurses", "util-linux", "cfdisk", "xz", "zstd",
        "kmod", "dbus", "systemd", "bash", "busybox", "coreutils", "findutils",
        "grep", "sed", "gawk", "tar", "gzip", "python", "e2fsprogs", "shadow",
        "sudo", "iproute2", "ca-certificates", "openssh", "curl", "ki2ctl", "kiki-agent", "kiki-netconfig", "kiki-installer-tui",
        "bridge-utils", "ethtool", "nftables", "iptables", "conntrack-tools", "firewalld", "chrony",
        NULL,
    };
    select_package_set(index_path, "server-core", "server-core general server package set", defaults);
}

static void select_kube_profile_packages(const char *index_path, const char *profile, const char *label) {
    if (kstrcmp(selected_container_runtime, "none") == 0) {
        selected_set_runtime("cri-o");
    }
    const char *const common[] = {
        "base-files", "linux", "glibc", "libxcrypt", "zlib", "expat", "openssl",
        "attr", "libcap", "libseccomp", "acl", "ncurses", "util-linux", "cfdisk", "xz", "zstd",
        "kmod", "dbus", "systemd", "bash", "busybox", "coreutils", "findutils",
        "grep", "sed", "gawk", "tar", "gzip", "python", "e2fsprogs", "shadow",
        "sudo", "iproute2", "ca-certificates", "openssh", "curl", "ki2ctl", "kiki-agent", "kiki-netconfig", "kiki-installer-tui",
        "bridge-utils", "ethtool", "nftables", "iptables", "conntrack-tools", "firewalld",
        "cni-plugins", "cri-tools", "socat", "chrony",
        "kubelet", "kubeadm", "kubectl", "kiki-kubeadm",
        NULL,
    };
    const char *const crio_runtime[] = {
        "conmon", "crun", "cri-o", "kube-node-config",
        NULL,
    };
    const char *const containerd_runtime[] = {
        "runc", "containerd", "kube-node-config-containerd",
        NULL,
    };
    select_package_set(index_path, profile, label, common);
    if (selected_runtime_is_containerd()) {
        select_package_set(index_path, profile, "containerd runtime package set", containerd_runtime);
        say("runtime selected: containerd, cgroup driver systemd, swap off for Kubernetes.\n");
    } else {
        selected_set_runtime("cri-o");
        select_package_set(index_path, profile, "CRI-O runtime package set", crio_runtime);
        say("runtime selected: CRI-O, cgroup driver systemd, swap off for Kubernetes.\n");
    }
}

static void select_kube_bootstrap_packages(const char *index_path) {
    select_kube_profile_packages(index_path, "kiki-kube-bootstrap", "kiki-kube-bootstrap package set (first control-plane bootstrap)");
}

static void select_kube_control_packages(const char *index_path) {
    select_kube_profile_packages(index_path, "kiki-kube-control", "kiki-kube-control package set (additional control-plane node)");
}

static void select_kube_compute_packages(const char *index_path) {
    select_kube_profile_packages(index_path, "kiki-kube-compute", "kiki-kube-compute package set (compute node)");
}

static int select_named_package_profile(const char *index_path, const char *profile, const char *runtime_override) {
    char effective_profile[96];
    int want_containerd = 0;
    int want_crio = 0;
    copy_string(effective_profile, sizeof(effective_profile), profile && profile[0] ? profile : "minimal-systemd");

    if (runtime_override && runtime_override[0]) {
        if (kstrcmp(runtime_override, "containerd") == 0) {
            want_containerd = 1;
        } else if (kstrcmp(runtime_override, "cri-o") == 0 || kstrcmp(runtime_override, "crio") == 0) {
            want_crio = 1;
        } else if (kstrcmp(runtime_override, "none") != 0) {
            say("Invalid kiki.runtime value. Use cri-o, crio, containerd, or none.\n");
            return 0;
        }
    }

    selected_clear();
    if (kstrcmp(effective_profile, "minimal-systemd") == 0) {
        if (want_containerd || want_crio) {
            say("Runtime override ignored for minimal-systemd; Kubernetes profiles own CRI selection.\n");
        }
        select_minimal_systemd_packages(index_path);
        return 1;
    }
    if (kstrcmp(effective_profile, "server-core") == 0) {
        if (want_containerd || want_crio) {
            say("Runtime override ignored for server-core; use server-container for container runtime profiles.\n");
        }
        select_server_core_packages(index_path);
        return 1;
    }

    if (kstrcmp(effective_profile, "kiki-kube-controller") == 0) {
        copy_string(effective_profile, sizeof(effective_profile), "kiki-kube-control");
    } else if (kstrcmp(effective_profile, "kiki-kube-node") == 0) {
        copy_string(effective_profile, sizeof(effective_profile), "kiki-kube-compute");
    }

    if (!starts_with(effective_profile, "kiki-kube-")) {
        say("Unknown kiki.profile value. Use minimal-systemd, server-core, or a kiki-kube-* profile.\n");
        return 0;
    }

    if (ends_with(effective_profile, "-containerd")) {
        want_containerd = 1;
    }
    if (want_containerd && !ends_with(effective_profile, "-containerd")) {
        size_t out = kstrlen(effective_profile);
        append_string(effective_profile, sizeof(effective_profile), out, "-containerd");
    }
    if (want_crio && ends_with(effective_profile, "-containerd")) {
        size_t trim = kstrlen(effective_profile) - kstrlen("-containerd");
        effective_profile[trim] = 0;
    }

    if (ends_with(effective_profile, "-containerd")) {
        selected_set_runtime("containerd");
    } else {
        selected_set_runtime("cri-o");
    }

    if (starts_with(effective_profile, "kiki-kube-bootstrap")) {
        select_kube_profile_packages(index_path, effective_profile, "kiki-kube-bootstrap autoinstall package set");
        return 1;
    }
    if (starts_with(effective_profile, "kiki-kube-control")) {
        select_kube_profile_packages(index_path, effective_profile, "kiki-kube-control autoinstall package set");
        return 1;
    }
    if (starts_with(effective_profile, "kiki-kube-compute")) {
        select_kube_profile_packages(index_path, effective_profile, "kiki-kube-compute autoinstall package set");
        return 1;
    }

    say("Unknown kiki.profile value. Use kiki-kube-bootstrap/control/compute with optional -containerd.\n");
    return 0;
}

static int ensure_selected_profile_packages(const char *index_path) {
    if (!selected_profile_is_kubernetes()) {
        return 1;
    }
    const char *const common[] = {
        "base-files", "linux", "glibc", "libxcrypt", "zlib", "expat", "openssl",
        "attr", "libcap", "libseccomp", "acl", "ncurses", "util-linux", "cfdisk", "xz", "zstd",
        "kmod", "dbus", "systemd", "bash", "busybox", "coreutils", "findutils",
        "grep", "sed", "gawk", "tar", "gzip", "python", "e2fsprogs", "shadow",
        "sudo", "iproute2", "ca-certificates", "openssh", "curl", "ki2ctl", "kiki-agent", "kiki-netconfig", "kiki-installer-tui",
        "bridge-utils", "ethtool", "nftables", "iptables", "conntrack-tools", "firewalld",
        "cni-plugins", "cri-tools", "socat", "chrony",
        "kubelet", "kubeadm", "kubectl", "kiki-kubeadm",
        NULL,
    };
    const char *const crio_runtime[] = {
        "conmon", "crun", "cri-o", "kube-node-config",
        NULL,
    };
    const char *const containerd_runtime[] = {
        "runc", "containerd", "kube-node-config-containerd",
        NULL,
    };
    const char *const *sets[] = {common, selected_runtime_is_containerd() ? containerd_runtime : crio_runtime, NULL};
    int missing = 0;
    int added = 0;
    char line[160];
    for (int set = 0; sets[set]; set++) {
        const char *const *required = sets[set];
        for (int i = 0; required[i]; i++) {
            if (!package_exists_in_index(index_path, required[i])) {
                size_t out = 0;
                out = append_string(line, sizeof(line), out, "Required Kubernetes package missing from repository index: ");
                out = append_string(line, sizeof(line), out, required[i]);
                append_string(line, sizeof(line), out, "\n");
                say(line);
                missing++;
                continue;
            }
            if (selected_add(required[i])) {
                added++;
            }
        }
    }
    if (missing) {
        say("Kubernetes profile cannot be installed until all required packages are present on the media.\n");
        return 0;
    }
    if (added) {
        size_t out = 0;
        out = append_string(line, sizeof(line), out, "Added missing Kubernetes profile packages before install: ");
        out = append_u64(line, sizeof(line), out, (u64)added);
        append_string(line, sizeof(line), out, "\n");
        say(line);
    }
    return 1;
}

static int ensure_selected_ai_packages(const char *index_path) {
    if (kstrcmp(selected_ai_mode, "off") == 0) {
        return 1;
    }
    const char *const local_packages[] = {"kiki-ai-console", "llama-cpp", NULL};
    const char *const remote_packages[] = {"kiki-ai-console", NULL};
    const char *const *required = kstrcmp(selected_ai_mode, "local") == 0 ? local_packages : remote_packages;
    for (int i = 0; required[i]; i++) {
        if (!package_exists_in_index(index_path, required[i])) {
            say("Required AI package missing from repository index: ");
            say(required[i]);
            say("\n");
            return 0;
        }
        selected_add(required[i]);
    }
    return 1;
}

static void apply_runtime_to_selected_packages(const char *runtime) {
    if (!selected_profile_is_kubernetes()) {
        selected_set_runtime("none");
        return;
    }
    selected_set_runtime(runtime);
    selected_remove("conmon");
    selected_remove("crun");
    selected_remove("cri-o");
    selected_remove("kube-node-config");
    selected_remove("runc");
    selected_remove("containerd");
    selected_remove("kube-node-config-containerd");
    if (selected_runtime_is_containerd()) {
        selected_add("runc");
        selected_add("containerd");
        selected_add("kube-node-config-containerd");
    } else {
        selected_set_runtime("cri-o");
        selected_add("conmon");
        selected_add("crun");
        selected_add("cri-o");
        selected_add("kube-node-config");
    }
}

static void show_runtime_status(void);
static void show_package_media(void);

static void runtime_menu(void) {
    char choice[16];
    tui_header("Runtime");
    show_runtime_status();
    if (!selected_profile_is_kubernetes()) {
        say("Select a Kubernetes profile before choosing CRI runtime.\n");
        tui_wait();
        return;
    }
    say("\nRuntime actions\n");
    say("---------------\n");
    say("1) Use CRI-O\n");
    say("2) Use containerd\n");
    say("3) Back to installer\n");
    say("\nSelect [3]: ");
    if (read_line(choice, sizeof(choice)) != 0) {
        return;
    }
    if (kstrcmp(choice, "1") == 0) {
        apply_runtime_to_selected_packages("cri-o");
        say("Runtime set to CRI-O.\n");
    } else if (kstrcmp(choice, "2") == 0) {
        apply_runtime_to_selected_packages("containerd");
        say("Runtime set to containerd.\n");
    }
    tui_wait();
}

static void localization_menu(void) {
    char value[96];
    tui_header("Language / keyboard / timezone");
    say("Locale [");
    say(selected_locale);
    say("]: ");
    if (read_line(value, sizeof(value)) == 0 && value[0]) {
        copy_string(selected_locale, sizeof(selected_locale), value);
    }
    say("Keyboard map [");
    say(selected_keymap);
    say("]: ");
    if (read_line(value, sizeof(value)) == 0 && value[0]) {
        copy_string(selected_keymap, sizeof(selected_keymap), value);
    }
    say("Timezone [");
    say(selected_timezone);
    say("]: ");
    if (read_line(value, sizeof(value)) == 0 && value[0]) {
        if (value[0] == '/' || contains(value, "..")) {
            say("Timezone must be a relative IANA name such as Asia/Seoul.\n");
        } else {
            copy_string(selected_timezone, sizeof(selected_timezone), value);
        }
    }
    say("Localization settings saved for this installer session.\n");
    tui_wait();
}

static void source_trust_menu(void) {
    tui_header("Package source / trust");
    show_package_media();
    say("\nStage-1 installs only from the attached, verified local media.\n");
    say("Remote repository plans can be authored by the CLI or GTK frontend and must include a verification key.\n");
    tui_wait();
}

static void ai_menu(void) {
    char choice[16];
    char endpoint[256];
    tui_header("AI management console");
    say("1) Local CPU llama.cpp model (tty1 AI, tty2 recovery shell)\n");
    say("2) Remote OpenAI-compatible endpoint (tty1 AI, tty2 recovery shell)\n");
    say("3) Disable AI console (tty1 and tty2 login shells)\n");
    say("\nSelect [1]: ");
    if (read_line(choice, sizeof(choice)) != 0) {
        return;
    }
    if (!choice[0] || kstrcmp(choice, "1") == 0) {
        copy_string(selected_ai_mode, sizeof(selected_ai_mode), "local");
        copy_string(selected_ai_endpoint, sizeof(selected_ai_endpoint), "http://127.0.0.1:8080/v1/chat/completions");
        copy_string(selected_ai_model, sizeof(selected_ai_model), "kiki-ops");
    } else if (kstrcmp(choice, "2") == 0) {
        say("Endpoint (http:// or https://): ");
        if (read_line(endpoint, sizeof(endpoint)) != 0 || contains(endpoint, "\"") || contains(endpoint, "\\") ||
            !(starts_with(endpoint, "http://") || starts_with(endpoint, "https://"))) {
            say("A valid HTTP(S) endpoint is required.\n");
            tui_wait();
            return;
        }
        copy_string(selected_ai_mode, sizeof(selected_ai_mode), "remote");
        copy_string(selected_ai_endpoint, sizeof(selected_ai_endpoint), endpoint);
        copy_string(selected_ai_model, sizeof(selected_ai_model), "kiki-ops");
    } else if (kstrcmp(choice, "3") == 0) {
        copy_string(selected_ai_mode, sizeof(selected_ai_mode), "off");
        selected_ai_endpoint[0] = 0;
        selected_ai_model[0] = 0;
    } else {
        say("Unknown selection.\n");
        tui_wait();
        return;
    }
    apply_ai_to_selected_packages();
    say("AI mode set to: ");
    say(selected_ai_mode);
    say("\nCommands always require explicit operator approval before execution.\n");
    tui_wait();
}

static void show_package_media(void);

static void package_selection_menu(void) {
    char choice[32];
    char name[PACKAGE_NAME_LEN];
    char index_path[384];
    index_path[0] = 0;
    if (!find_package_index_path(index_path, sizeof(index_path))) {
        say("Cannot find ki2 repository index on installer media.\n");
        return;
    }

    for (;;) {
        char line[128];
        size_t out = 0;
        say("\nPackage selection\n");
        say("-----------------\n");
        out = append_string(line, sizeof(line), out, "selected packages: ");
        out = append_u64(line, sizeof(line), out, (u64)selected_package_count);
        append_string(line, sizeof(line), out, "\n");
        say(line);
        say("1) Show package repository\n");
        say("2) Select minimal-systemd default package set\n");
        say("3) Select server-core general OS package set\n");
        say("4) Select kiki-kube-bootstrap package set\n");
        say("5) Select kiki-kube-control package set\n");
        say("6) Select kiki-kube-compute package set\n");
        say("7) Select every package on media\n");
        say("8) Add one package by name\n");
        say("9) Clear selected packages\n");
        say("10) Show selected packages\n");
        say("11) Save package selection and return\n");
        say("\nSelect: ");
        if (read_line(choice, sizeof(choice)) != 0) {
            continue;
        }
        if (kstrcmp(choice, "1") == 0) {
            show_package_media();
        } else if (kstrcmp(choice, "2") == 0) {
            selected_clear();
            select_minimal_systemd_packages(index_path);
        } else if (kstrcmp(choice, "3") == 0) {
            selected_clear();
            select_server_core_packages(index_path);
        } else if (kstrcmp(choice, "4") == 0) {
            selected_clear();
            select_kube_bootstrap_packages(index_path);
        } else if (kstrcmp(choice, "5") == 0) {
            selected_clear();
            select_kube_control_packages(index_path);
        } else if (kstrcmp(choice, "6") == 0) {
            selected_clear();
            select_kube_compute_packages(index_path);
        } else if (kstrcmp(choice, "7") == 0) {
            selected_clear();
            selected_set_profile("world");
            selected_set_runtime("none");
            int added = select_all_packages_from_index(index_path);
            apply_ai_to_selected_packages();
            out = 0;
            out = append_string(line, sizeof(line), out, "selected unique packages from media: ");
            out = append_u64(line, sizeof(line), out, (u64)added);
            append_string(line, sizeof(line), out, "\n");
            say(line);
        } else if (kstrcmp(choice, "8") == 0) {
            say("Package name: ");
            if (read_line(name, sizeof(name)) != 0 || !name[0]) {
                say("No package name entered.\n");
            } else if (!package_exists_in_index(index_path, name)) {
                say("Package not found in repository index.\n");
            } else if (selected_add(name)) {
                selected_set_profile("custom");
                selected_set_runtime("none");
                say("Package selected.\n");
            } else {
                say("Package is already selected or selection is full.\n");
            }
        } else if (kstrcmp(choice, "9") == 0) {
            selected_clear();
            selected_set_profile("custom");
            selected_set_runtime("none");
            say("Package selection cleared.\n");
        } else if (kstrcmp(choice, "10") == 0) {
            show_selected_packages();
        } else if (kstrcmp(choice, "11") == 0) {
            say("Package selection saved for this installer session.\n");
            return;
        } else {
            say("Unknown selection.\n");
        }
    }
}

static void show_package_media(void) {
    char root[256];
    char path[384];
    say("\nBOS/ki2 package media\n");
    say("---------------------\n");
    if (!find_install_media_root(root, sizeof(root))) {
        say("Cannot find installer media. Attach the ISO or use an installed image with media mounted.\n");
        return;
    }
    say("media root: ");
    say(root);
    say("\n");

    path3(path, sizeof(path), root, "/manifest.json", "");
    if (file_exists(path)) {
        say("media manifest: present\n");
    } else {
        say("media manifest: missing\n");
    }

    path3(path, sizeof(path), root, "/kiki/rootfs.tar.gz", "");
    say(file_exists(path) ? "rootfs payload: present\n" : "rootfs payload: missing\n");

    path3(path, sizeof(path), root, "/install/kiki-stage1.img", "");
    say(file_exists(path) ? "stage-1 disk image: present\n" : "stage-1 disk image: missing\n");

    path3(path, sizeof(path), root, "/kiki/repo/index.x86_64.json", "");
    if (file_exists(path)) {
        say("repository index: ");
        say(path);
        say("\n");
        show_package_names_from_index(path);
    } else {
        say("repository index: missing\n");
    }

    path3(path, sizeof(path), root, "/kiki/packages/x86_64", "");
    say(file_exists(path) ? "package payload directory: present\n" : "package payload directory: missing\n");
    say("\nUse the package selection menu to choose the install package set.\n");
}

static void prompt_help(void) {
    say("commands:\n");
    say("  help      show this help\n");
    say("  status    show kernel/init status\n");
    say("  services  show basic service status\n");
    say("  packages  inspect BOS/ki2 package media\n");
    say("  plan      show installed declarative install plan\n");
    say("  network   list network interfaces\n");
    say("  disk      show disk and partition inventory\n");
    say("  lsblk     list visible VM disks\n");
    say("  mounts    show /proc/mounts\n");
    say("  cmdline   show kernel command line\n");
    say("  os        show /etc/os-release\n");
    say("  uptime    show /proc/uptime\n");
    say("  clear     redraw the KIKI banner\n");
    say("  reboot    reboot the VM\n");
    say("  poweroff  power off the VM\n");
    say("\n");
}

static int run_busybox_tar_extract(const char *package_path, const char *target_dir) {
    char *argv[] = {
        "/bin/busybox",
        "tar",
        "-xzf",
        (char *)package_path,
        "-C",
        (char *)target_dir,
        "--strip-components=1",
        "--numeric-owner",
        NULL,
    };
    return run_program("/bin/busybox", argv);
}

static int format_esp_partition(const char *esp_part) {
    char *argv[] = {
        "/bin/busybox",
        "mkfs.vfat",
        "-F",
        "32",
        "-n",
        "KIKI_EFI",
        (char *)esp_part,
        NULL,
    };
    say("Formatting EFI system partition as FAT32...\n");
    return run_program("/bin/busybox", argv) == 0;
}

static int format_root_partition(const char *root_part) {
    char *argv[] = {
        "/usr/sbin/mke2fs",
        "-F",
        "-t",
        "ext4",
        "-L",
        "KIKI_ROOT",
        (char *)root_part,
        NULL,
    };
    say("Formatting root partition as ext4...\n");
    return run_program("/usr/sbin/mke2fs", argv) == 0;
}

static int format_swap_partition(const char *swap_part) {
    char *argv[] = {
        "/bin/busybox",
        "mkswap",
        "-L",
        "KIKI_SWAP",
        (char *)swap_part,
        NULL,
    };
    say("Formatting swap partition...\n");
    return run_program("/bin/busybox", argv) == 0;
}

static int install_selected_packages_to_target(const char *media_root, const char *index_path, const char *target_root) {
    char package_path[512];
    char line[192];
    int installed = 0;
    mkdir_p("/mnt/target/var/lib/ki2", 0755);
    if (selected_package_count == 0) {
        select_minimal_systemd_packages(index_path);
    }
    if (!ensure_selected_profile_packages(index_path)) {
        return 0;
    }
    for (int i = 0; i < selected_package_count; i++) {
        size_t out = 0;
        if (!find_package_file_for_name(index_path, media_root, selected_packages[i], package_path, sizeof(package_path))) {
            out = append_string(line, sizeof(line), out, "Package payload missing: ");
            out = append_string(line, sizeof(line), out, selected_packages[i]);
            append_string(line, sizeof(line), out, "\n");
            say(line);
            return 0;
        }
        out = 0;
        out = append_string(line, sizeof(line), out, "Installing package ");
        out = append_u64(line, sizeof(line), out, (u64)(i + 1));
        out = append_string(line, sizeof(line), out, "/");
        out = append_u64(line, sizeof(line), out, (u64)selected_package_count);
        out = append_string(line, sizeof(line), out, ": ");
        out = append_string(line, sizeof(line), out, selected_packages[i]);
        append_string(line, sizeof(line), out, "\n");
        say(line);
        if (run_busybox_tar_extract(package_path, target_root) != 0) {
            say("Package extraction failed.\n");
            return 0;
        }
        installed++;
    }

    char list_path[256];
    path3(list_path, sizeof(list_path), target_root, "/var/lib/ki2/installed.list", "");
    int fd = kopen_mode(list_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        for (int i = 0; i < selected_package_count; i++) {
            write_all(fd, selected_packages[i]);
            write_all(fd, "\n");
        }
        ksys(SYS_fsync, fd, 0, 0, 0, 0, 0);
        kclose(fd);
    }

    char repo_copy[256];
    path3(repo_copy, sizeof(repo_copy), target_root, "/var/lib/ki2/repo-index.x86_64.json", "");
    copy_file(index_path, repo_copy);

    size_t out = 0;
    out = append_string(line, sizeof(line), out, "Installed package count: ");
    out = append_u64(line, sizeof(line), out, (u64)installed);
    append_string(line, sizeof(line), out, "\n");
    say(line);
    return 1;
}

static int write_installed_boot_config(const char *esp_root, const char *root_part) {
    char cfg_path[256];
    char cfg[4096];
    size_t out = 0;
    path3(cfg_path, sizeof(cfg_path), esp_root, "/boot/grub/kiki-installed.cfg", "");
    mkdir_p("/mnt/esp/boot/grub", 0755);
    mkdir_p("/mnt/esp/boot/grub/fonts", 0755);
    out = append_string(cfg, sizeof(cfg), out, "insmod all_video\n");
    out = append_string(cfg, sizeof(cfg), out, "insmod font\n");
    out = append_string(cfg, sizeof(cfg), out, "insmod gfxterm\n");
    out = append_string(cfg, sizeof(cfg), out, "if loadfont /boot/grub/fonts/unicode.pf2; then\n");
    out = append_string(cfg, sizeof(cfg), out, "    terminal_output gfxterm console\n");
    out = append_string(cfg, sizeof(cfg), out, "else\n");
    out = append_string(cfg, sizeof(cfg), out, "    terminal_output console\n");
    out = append_string(cfg, sizeof(cfg), out, "fi\n");
    out = append_string(cfg, sizeof(cfg), out, "terminal_input console\n");
    out = append_string(cfg, sizeof(cfg), out, "set gfxmode=1024x768,800x600,auto\n");
    out = append_string(cfg, sizeof(cfg), out, "set gfxpayload=keep\n");
    out = append_string(cfg, sizeof(cfg), out, "set timeout=3\n");
    out = append_string(cfg, sizeof(cfg), out, "set default=0\n");
    out = append_string(cfg, sizeof(cfg), out, "menuentry 'KIKI OS installed (systemd handoff)' {\n");
    out = append_string(cfg, sizeof(cfg), out, "    set gfxpayload=keep\n");
    out = append_string(cfg, sizeof(cfg), out, "    linux /boot/vmlinuz-kiki console=tty0 keep_bootcon loglevel=4 root=");
    out = append_string(cfg, sizeof(cfg), out, root_part);
    out = append_string(cfg, sizeof(cfg), out, " rw init=/init kiki.boot=installed\n");
    out = append_string(cfg, sizeof(cfg), out, "    initrd /boot/initramfs-kiki.img\n");
    out = append_string(cfg, sizeof(cfg), out, "}\n");
    out = append_string(cfg, sizeof(cfg), out, "menuentry 'KIKI OS installed (BIOS text fallback)' {\n");
    out = append_string(cfg, sizeof(cfg), out, "    set gfxpayload=text\n");
    out = append_string(cfg, sizeof(cfg), out, "    linux /boot/vmlinuz-kiki console=tty0 quiet loglevel=3 nomodeset vga=normal root=");
    out = append_string(cfg, sizeof(cfg), out, root_part);
    out = append_string(cfg, sizeof(cfg), out, " rw init=/init kiki.boot=installed\n");
    out = append_string(cfg, sizeof(cfg), out, "    initrd /boot/initramfs-kiki.img\n");
    append_string(cfg, sizeof(cfg), out, "}\n");
    return write_text_file(cfg_path, cfg);
}

static int write_target_fstab_and_identity(const char *target_root, const char *esp_part, const char *root_part, const char *swap_part, const char *hostname) {
    char path[256];
    char fstab[768];
    size_t out = 0;
    (void)esp_part;
    (void)root_part;
    mkdir_p("/mnt/target/etc", 0755);
    path3(path, sizeof(path), target_root, "/etc/fstab", "");
    out = append_string(fstab, sizeof(fstab), out, "# KIKI installer generated fstab\n");
    out = append_string(fstab, sizeof(fstab), out, "LABEL=KIKI_ROOT / ext4 defaults 0 1\n");
    out = append_string(fstab, sizeof(fstab), out, "LABEL=KIKI_EFI /boot/efi vfat noauto,nofail,x-systemd.device-timeout=3s,umask=0077 0 0\n");
    if (swap_part && swap_part[0]) {
        out = append_string(fstab, sizeof(fstab), out, "LABEL=KIKI_SWAP none swap defaults,nofail,x-systemd.device-timeout=10s 0 0\n");
    }
    if (!write_text_file(path, fstab)) {
        return 0;
    }
    path3(path, sizeof(path), target_root, "/etc/hostname", "");
    char hostname_file[96];
    out = 0;
    out = append_string(hostname_file, sizeof(hostname_file), out, hostname && hostname[0] ? hostname : "localhost.localdomain");
    append_string(hostname_file, sizeof(hostname_file), out, "\n");
    if (!write_text_file(path, hostname_file)) {
        return 0;
    }
    path3(path, sizeof(path), target_root, "/boot/efi", "");
    mkdir_p(path, 0755);
    return 1;
}

static int write_target_ld_so_config(const char *target_root) {
    char path[256];
    path3(path, sizeof(path), target_root, "/etc/ld.so.conf", "");
    const char *config =
        "/lib\n"
        "/lib64\n"
        "/usr/lib\n"
        "/usr/lib64\n"
        "/usr/lib/systemd\n"
        "include /etc/ld.so.conf.d/*.conf\n";
    return write_text_file(path, config);
}

static int refresh_target_ld_cache(const char *target_root) {
    char ldconfig_path[256];
    path3(ldconfig_path, sizeof(ldconfig_path), target_root, "/sbin/ldconfig", "");
    if (!file_exists(ldconfig_path)) {
        path3(ldconfig_path, sizeof(ldconfig_path), target_root, "/usr/sbin/ldconfig", "");
    }
    if (!file_exists(ldconfig_path)) {
        say("ldconfig not found in target root; installed system may miss shared-library cache.\n");
        return 0;
    }
    char *argv[] = {
        ldconfig_path,
        "-r",
        (char *)target_root,
        NULL,
    };
    say("Refreshing target shared-library cache...\n");
    return run_program(ldconfig_path, argv) == 0;
}

static void ensure_target_baseline_layout(void) {
    mkdir_p("/mnt/target/tmp", 01777);
    chmod_path("/mnt/target/tmp", 01777);
    mkdir_p("/mnt/target/var", 0755);
    mkdir_p("/mnt/target/var/tmp", 01777);
    chmod_path("/mnt/target/var/tmp", 01777);
    mkdir_p("/mnt/target/run", 0755);
    mkdir_p("/mnt/target/usr/sbin", 0755);
    mkdir_p("/mnt/target/lib64", 0755);
    if (file_exists("/mnt/target/sbin/sulogin") && !file_exists("/mnt/target/usr/sbin/sulogin")) {
        make_symlink("../../sbin/sulogin", "/mnt/target/usr/sbin/sulogin");
    }
    if (file_exists("/mnt/target/usr/lib/libcrypt.so.1.1.0") && !file_exists("/mnt/target/lib64/libcrypt.so.2")) {
        make_symlink("../usr/lib/libcrypt.so.1.1.0", "/mnt/target/lib64/libcrypt.so.2");
    }
    if (file_exists("/mnt/target/usr/lib/libcrypt.so.1.1.0") && !file_exists("/mnt/target/lib64/libcrypt.so.1")) {
        make_symlink("../usr/lib/libcrypt.so.1.1.0", "/mnt/target/lib64/libcrypt.so.1");
    }
    if (file_exists("/mnt/target/lib64/ld-linux-x86-64.so.2")) {
        chmod_path("/mnt/target/lib64/ld-linux-x86-64.so.2", 0755);
    }
    if (file_exists("/mnt/target/lib/ld-linux-x86-64.so.2")) {
        chmod_path("/mnt/target/lib/ld-linux-x86-64.so.2", 0755);
    }
    if (file_exists("/mnt/target/lib/ld-linux.so.2")) {
        chmod_path("/mnt/target/lib/ld-linux.so.2", 0755);
    }
    if (file_exists("/mnt/target/usr/lib64/ld-linux-x86-64.so.2")) {
        chmod_path("/mnt/target/usr/lib64/ld-linux-x86-64.so.2", 0755);
    }
    if (file_exists("/mnt/target/etc/systemd/system/default.target")) {
        chmod_path("/mnt/target/etc/systemd/system/default.target", 0644);
    }
    if (file_exists("/mnt/target/etc/systemd/system/tmp.mount")) {
        chmod_path("/mnt/target/etc/systemd/system/tmp.mount", 0644);
    }
    if (file_exists("/mnt/target/etc/systemd/system/kiki-boot-prepare.service")) {
        chmod_path("/mnt/target/etc/systemd/system/kiki-boot-prepare.service", 0644);
    }
    if (file_exists("/mnt/target/etc/systemd/system/sshd.service")) {
        chmod_path("/mnt/target/etc/systemd/system/sshd.service", 0644);
    }
    if (file_exists("/mnt/target/etc/systemd/system/kiki-agent.service")) {
        chmod_path("/mnt/target/etc/systemd/system/kiki-agent.service", 0644);
    }
}

static void enable_default_systemd_units(void) {
    mkdir_p("/mnt/target/etc/systemd/system/basic.target.wants", 0755);
    mkdir_p("/mnt/target/etc/systemd/system/getty.target.wants", 0755);
    mkdir_p("/mnt/target/etc/systemd/system/multi-user.target.wants", 0755);
    mkdir_p("/mnt/target/etc/systemd/system/network-online.target.wants", 0755);
    mkdir_p("/mnt/target/etc/systemd/system/sockets.target.wants", 0755);
    mkdir_p("/mnt/target/etc/systemd/system/sysinit.target.wants", 0755);
    make_symlink("/usr/lib/systemd/system/dbus.service", "/mnt/target/etc/systemd/system/basic.target.wants/dbus.service");
    if (kstrcmp(selected_ai_mode, "off") == 0) {
        make_symlink("/usr/lib/systemd/system/getty@.service", "/mnt/target/etc/systemd/system/getty.target.wants/getty@tty1.service");
    } else {
        make_symlink("/etc/systemd/system/kiki-ai-console@.service", "/mnt/target/etc/systemd/system/getty.target.wants/kiki-ai-console@tty1.service");
        if (kstrcmp(selected_ai_mode, "local") == 0) {
            make_symlink("/etc/systemd/system/kiki-llama-server.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/kiki-llama-server.service");
        }
    }
    make_symlink("/usr/lib/systemd/system/getty@.service", "/mnt/target/etc/systemd/system/getty.target.wants/getty@tty2.service");
    make_symlink("/usr/lib/systemd/system/systemd-logind.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/systemd-logind.service");
    make_symlink("/usr/lib/systemd/system/systemd-networkd.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/systemd-networkd.service");
    make_symlink("/usr/lib/systemd/system/systemd-networkd.socket", "/mnt/target/etc/systemd/system/sockets.target.wants/systemd-networkd.socket");
    make_symlink("/usr/lib/systemd/system/systemd-network-generator.service", "/mnt/target/etc/systemd/system/sysinit.target.wants/systemd-network-generator.service");
    make_symlink("/usr/lib/systemd/system/systemd-networkd-wait-online.service", "/mnt/target/etc/systemd/system/network-online.target.wants/systemd-networkd-wait-online.service");
    make_symlink("/usr/lib/systemd/system/systemd-resolved.service", "/mnt/target/etc/systemd/system/sysinit.target.wants/systemd-resolved.service");
    make_symlink("/etc/systemd/system/kiki-boot-prepare.service", "/mnt/target/etc/systemd/system/sysinit.target.wants/kiki-boot-prepare.service");
    make_symlink("/etc/systemd/system/sshd.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/sshd.service");
    make_symlink("/etc/systemd/system/kiki-agent.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/kiki-agent.service");
    make_symlink("/usr/lib/systemd/system/dbus-org.freedesktop.login1.service", "/mnt/target/etc/systemd/system/dbus-org.freedesktop.login1.service");
    make_symlink("/usr/lib/systemd/system/systemd-networkd.service", "/mnt/target/etc/systemd/system/dbus-org.freedesktop.network1.service");
    make_symlink("/usr/lib/systemd/system/systemd-resolved.service", "/mnt/target/etc/systemd/system/dbus-org.freedesktop.resolve1.service");
}

static void enable_kubernetes_systemd_units(void) {
    mkdir_p("/mnt/target/etc/systemd/system/multi-user.target.wants", 0755);
    if (!selected_runtime_is_containerd() && file_exists("/mnt/target/usr/lib/systemd/system/crio.service")) {
        make_symlink("/usr/lib/systemd/system/crio.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/crio.service");
    }
    if (selected_runtime_is_containerd() && file_exists("/mnt/target/usr/lib/systemd/system/containerd.service")) {
        make_symlink("/usr/lib/systemd/system/containerd.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/containerd.service");
    }
    if (file_exists("/mnt/target/usr/lib/systemd/system/kubelet.service")) {
        make_symlink("/usr/lib/systemd/system/kubelet.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/kubelet.service");
    }
    if (file_exists("/mnt/target/usr/lib/systemd/system/chronyd.service")) {
        make_symlink("/usr/lib/systemd/system/chronyd.service", "/mnt/target/etc/systemd/system/multi-user.target.wants/chronyd.service");
    }
}

static int install_uefi_boot_files(const char *media_root, const char *target_root, const char *esp_root, const char *root_part) {
    char src[512];
    char dst[512];
    mkdir_p("/mnt/esp/EFI/BOOT", 0755);
    mkdir_p("/mnt/esp/boot", 0755);
    mkdir_p("/mnt/esp/boot/grub/fonts", 0755);
    mkdir_p("/mnt/target/boot", 0755);

    path3(src, sizeof(src), media_root, "/kiki/bootloader/EFI/BOOT/BOOTX64.EFI", "");
    path3(dst, sizeof(dst), esp_root, "/EFI/BOOT/BOOTX64.EFI", "");
    if (!copy_file(src, dst)) {
        say("UEFI fallback bootloader copy failed.\n");
        return 0;
    }

    path3(src, sizeof(src), media_root, "/boot/grub/fonts/unicode.pf2", "");
    path3(dst, sizeof(dst), esp_root, "/boot/grub/fonts/unicode.pf2", "");
    copy_file(src, dst);

    path3(src, sizeof(src), media_root, "/boot/vmlinuz-kiki", "");
    path3(dst, sizeof(dst), esp_root, "/boot/vmlinuz-kiki", "");
    if (!copy_file(src, dst)) {
        say("Kernel copy to ESP failed.\n");
        return 0;
    }
    path3(dst, sizeof(dst), target_root, "/boot/vmlinuz-kiki", "");
    copy_file(src, dst);

    path3(src, sizeof(src), media_root, "/boot/initramfs-kiki-installed.img", "");
    if (!file_exists(src)) {
        path3(src, sizeof(src), media_root, "/boot/initramfs-kiki.img", "");
    }
    path3(dst, sizeof(dst), esp_root, "/boot/initramfs-kiki.img", "");
    if (!copy_file(src, dst)) {
        say("Installed initramfs copy to ESP failed.\n");
        return 0;
    }
    path3(dst, sizeof(dst), target_root, "/boot/initramfs-kiki.img", "");
    copy_file(src, dst);

    if (!write_installed_boot_config(esp_root, root_part)) {
        say("Installed GRUB config write failed.\n");
        return 0;
    }
    return 1;
}

static int run_partition_command(const char *command) {
    char tool[32];
    char device[128];
    size_t i = 0;
    size_t used = 0;
    while (command[i] == ' ' || command[i] == '\t') {
        i++;
    }
    while (command[i] && command[i] != ' ' && command[i] != '\t' && used + 1 < sizeof(tool)) {
        tool[used++] = command[i++];
    }
    tool[used] = 0;
    while (command[i] == ' ' || command[i] == '\t') {
        i++;
    }
    used = 0;
    while (command[i] && command[i] != ' ' && command[i] != '\t' && used + 1 < sizeof(device)) {
        device[used++] = command[i++];
    }
    device[used] = 0;
    if (!device[0] || !starts_with(device, "/dev/")) {
        say("Partition command needs a disk path, for example: fdisk /dev/sda\n");
        return 0;
    }
    if (is_whole_disk_path(device)) {
        remember_preferred_install_disk(device);
    }
    if (kstrcmp(tool, "fdisk") == 0) {
        char *argv[] = {"/sbin/fdisk", device, NULL};
        return run_program("/sbin/fdisk", argv) == 0;
    }
    if (kstrcmp(tool, "cfdisk") == 0) {
        char *argv[] = {"/sbin/cfdisk", device, NULL};
        return run_program("/sbin/cfdisk", argv) == 0;
    }
    say("Unsupported partition command. Use fdisk or cfdisk.\n");
    return 0;
}

static int prompt_whole_disk(char *target, size_t target_size) {
    char default_target[128];
    target[0] = 0;
    default_target[0] = 0;
    get_default_install_disk(default_target, sizeof(default_target));
    if (default_target[0]) {
        say("Target whole disk [");
        say(default_target);
        say("]: ");
    } else {
        say("Target whole disk, for example /dev/sda or /dev/vda: ");
    }
    if (read_line(target, target_size) != 0) {
        return 0;
    }
    if (!target[0] && default_target[0]) {
        copy_string(target, target_size, default_target);
    }
    if (!is_whole_disk_path(target)) {
        say("Invalid target disk. Enter a whole disk such as /dev/sda, not a partition such as /dev/sda1.\n");
        return 0;
    }
    remember_preferred_install_disk(target);
    return 1;
}

static void run_partition_editor(const char *tool) {
    char target[128];
    char command[192];
    size_t out = 0;
    if (!prompt_whole_disk(target, sizeof(target))) {
        return;
    }
    say("\nOpening ");
    say(tool);
    say(" for ");
    say(target);
    say(". Save/write inside the editor when you are done.\n");
    say("After leaving the editor, the installer will refresh the kernel partition view.\n\n");
    out = append_string(command, sizeof(command), out, tool);
    out = append_string(command, sizeof(command), out, " ");
    append_string(command, sizeof(command), out, target);
    if (run_partition_command(command)) {
        say("\nPartition editor exited successfully.\n");
    } else {
        say("\nPartition editor exited with an error or without changes.\n");
    }
    remember_preferred_install_disk(target);
    ksys(SYS_sync, 0, 0, 0, 0, 0, 0);
    int fd = kopen(target, O_RDONLY);
    if (fd >= 0) {
        ksys(SYS_ioctl, fd, BLKRRPART, 0, 0, 0, 0);
        kclose(fd);
    }
    sleep_msec(600);
    show_disk_tools();
}

static void disk_menu(void) {
    char choice[16];
    for (;;) {
        tui_header("Disk");
        show_disk_tools();
        say("\nDisk actions\n");
        say("------------\n");
        say("1) Open cfdisk on a disk\n");
        say("2) Open fdisk on a disk\n");
        say("3) Refresh disk and partition status\n");
        say("4) Back to installer\n");
        say("\nSelect [1]: ");
        if (read_line(choice, sizeof(choice)) != 0) {
            continue;
        }
        if (!choice[0] || kstrcmp(choice, "1") == 0) {
            run_partition_editor("cfdisk");
            tui_wait();
        } else if (kstrcmp(choice, "2") == 0) {
            run_partition_editor("fdisk");
            tui_wait();
        } else if (kstrcmp(choice, "3") == 0) {
            continue;
        } else if (kstrcmp(choice, "4") == 0 || kstrcmp(choice, "b") == 0 || kstrcmp(choice, "B") == 0 || kstrcmp(choice, "q") == 0 || kstrcmp(choice, "Q") == 0) {
            return;
        } else {
            say("Unknown selection.\n");
            tui_wait();
        }
    }
}

static void detect_manual_partition_defaults(char *disk, size_t disk_size, char *esp_part, size_t esp_size, char *swap_part, size_t swap_size, char *root_part, size_t root_size) {
    char candidate1[160];
    char candidate2[160];
    char candidate3[160];
    disk[0] = 0;
    esp_part[0] = 0;
    swap_part[0] = 0;
    root_part[0] = 0;
    if (!get_default_install_disk(disk, disk_size)) {
        return;
    }
    partition_path(disk, 1, candidate1, sizeof(candidate1));
    partition_path(disk, 2, candidate2, sizeof(candidate2));
    partition_path(disk, 3, candidate3, sizeof(candidate3));
    if (is_partition_path(candidate1)) {
        copy_string(esp_part, esp_size, candidate1);
    }
    if (is_partition_path(candidate3)) {
        if (is_partition_path(candidate2)) {
            copy_string(swap_part, swap_size, candidate2);
        }
        copy_string(root_part, root_size, candidate3);
    } else if (is_partition_path(candidate2)) {
        copy_string(root_part, root_size, candidate2);
    }
}

static void show_manual_partition_defaults(const char *disk, const char *esp_part, const char *swap_part, const char *root_part) {
    if (!disk[0] || (!esp_part[0] && !swap_part[0] && !root_part[0])) {
        return;
    }
    say("\nDetected partition candidates from ");
    say(disk);
    say(":\n");
    if (esp_part[0]) {
        say("  ESP:  ");
        say(esp_part);
        say("\n");
    }
    if (swap_part[0]) {
        say("  swap: ");
        say(swap_part);
        say("\n");
    }
    if (root_part[0]) {
        say("  root: ");
        say(root_part);
        say("\n");
    }
}

static int prompt_partition_path(const char *label, const char *example, const char *default_path, char *out, size_t out_size, int required) {
    out[0] = 0;
    say(label);
    if (default_path && default_path[0] && is_partition_path(default_path)) {
        say(" [");
        say(default_path);
        say("]");
    } else if (example && example[0]) {
        say(", for example ");
        say(example);
    }
    if (!required) {
        say(" or type none");
    }
    say(": ");
    if (read_line(out, out_size) != 0) {
        return 0;
    }
    if (!out[0] && default_path && default_path[0] && is_partition_path(default_path)) {
        copy_string(out, out_size, default_path);
    }
    if (!required && (out[0] == 0 || kstrcmp(out, "none") == 0 || kstrcmp(out, "NONE") == 0 || kstrcmp(out, "no") == 0 || kstrcmp(out, "NO") == 0)) {
        out[0] = 0;
        return 1;
    }
    if (!out[0] || !starts_with(out, "/dev/") || !is_partition_path(out)) {
        say("Invalid partition path. Enter a partition such as ");
        say(example);
        say(required ? ".\n" : ", or type none.\n");
        return 0;
    }
    return 1;
}

struct account_setup {
    char admin_user[32];
    char admin_password[96];
    int lock_root;
};

struct network_setup {
    int enabled;
    int dhcp4;
    int ipv6_ra;
    char match_name[96];
    char address[96];
    char gateway[96];
    char dns[160];
    char ntp[160];
};

#define INSTALL_PLAN_PATH "/run/kiki/install-plan.yaml"
#define TARGET_INSTALL_PLAN_PATH "/mnt/target/var/lib/ki2/install-plan.yaml"

struct install_plan {
    int quick_mode;
    int unattended_mode;
    int auto_layout;
    int has_swap;
    char media_root[256];
    char index_path[384];
    char target_disk[128];
    char esp_part[160];
    char swap_part[160];
    char root_part[160];
    char hostname[64];
    u64 disk_mib;
    u64 mem_mib;
    u64 esp_mib;
    u64 swap_mib;
    u64 root_mib;
    struct account_setup account;
    struct network_setup network;
};

static int is_lower_alpha(char ch) {
    return ch >= 'a' && ch <= 'z';
}

static int is_digit(char ch) {
    return ch >= '0' && ch <= '9';
}

static int is_valid_username(const char *value) {
    size_t len = kstrlen(value);
    if (len < 1 || len > 31 || kstrcmp(value, "root") == 0) {
        return 0;
    }
    if (!(is_lower_alpha(value[0]) || value[0] == '_')) {
        return 0;
    }
    for (size_t i = 1; value[i]; i++) {
        char ch = value[i];
        if (!(is_lower_alpha(ch) || is_digit(ch) || ch == '_' || ch == '-')) {
            return 0;
        }
    }
    return 1;
}

static void collect_account_setup(struct account_setup *account, int quick_mode, int unattended_mode) {
    char input[128];
    char confirm[128];
    copy_string(account->admin_user, sizeof(account->admin_user), "kiki");
    copy_string(account->admin_password, sizeof(account->admin_password), "kiki");
    account->lock_root = 1;

    say("\nUser setup\n");
    say("----------\n");
    say("Root login is disabled by default. The kiki user is added to the sudo group.\n");
    say("Password input is visible on this early installer console.\n");
    if (unattended_mode) {
        say("Autoinstall uses lab defaults: user kiki, password kiki, root locked.\n");
        return;
    }
    say("Admin username [kiki]: ");
    if (read_line(input, sizeof(input)) == 0 && input[0]) {
        if (!is_valid_username(input)) {
            say("Invalid username. Use lowercase letters, digits, '_' or '-', and do not use root.\n");
            say("Using default admin user: kiki\n");
        } else {
            copy_string(account->admin_user, sizeof(account->admin_user), input);
        }
    }

    if (quick_mode) {
        say("Admin password [kiki]: ");
    } else {
        say("Admin password [kiki for lab]: ");
    }
    if (read_line(input, sizeof(input)) == 0 && input[0]) {
        say("Confirm admin password: ");
        if (read_line(confirm, sizeof(confirm)) == 0 && kstrcmp(input, confirm) == 0) {
            copy_string(account->admin_password, sizeof(account->admin_password), input);
        } else {
            say("Password confirmation did not match. Using lab default password: kiki\n");
        }
    }

    say("Disable direct root login? [Y/n]: ");
    if (read_line(input, sizeof(input)) == 0 && (kstrcmp(input, "n") == 0 || kstrcmp(input, "N") == 0)) {
        account->lock_root = 0;
        say("Root login will be enabled with the same password as the admin user.\n");
    }
}

static void collect_network_setup(struct network_setup *network, int quick_mode) {
    char input[192];
    copy_string(network->match_name, sizeof(network->match_name), "en* eth*");
    copy_string(network->address, sizeof(network->address), "");
    copy_string(network->gateway, sizeof(network->gateway), "");
    copy_string(network->dns, sizeof(network->dns), "");
    copy_string(network->ntp, sizeof(network->ntp), "");
    network->enabled = 1;
    network->dhcp4 = 1;
    network->ipv6_ra = 1;

    say("\nNetwork setup\n");
    say("-------------\n");
    say("Default: systemd-networkd DHCP for wired interfaces (en* eth*).\n");
    if (quick_mode) {
        say("Quick VM install uses the default DHCP profile.\n");
        return;
    }

    say("Network mode [dhcp] (dhcp/static/off): ");
    if (read_line(input, sizeof(input)) == 0 && input[0]) {
        if (kstrcmp(input, "off") == 0 || kstrcmp(input, "none") == 0 || kstrcmp(input, "disabled") == 0) {
            network->enabled = 0;
            network->dhcp4 = 0;
            network->ipv6_ra = 0;
            say("Network autoconfiguration will be disabled in the target rootfs.\n");
            return;
        }
        if (kstrcmp(input, "static") == 0 || kstrcmp(input, "STATIC") == 0) {
            network->dhcp4 = 0;
            network->ipv6_ra = 0;
            say("Interface match [en* eth*]: ");
            if (read_line(input, sizeof(input)) == 0 && input[0]) {
                copy_string(network->match_name, sizeof(network->match_name), input);
            }
            say("Static IPv4 address with prefix, for example 192.168.122.50/24: ");
            if (read_line(input, sizeof(input)) != 0 || !input[0]) {
                say("No static address entered. Falling back to DHCP.\n");
                network->dhcp4 = 1;
                network->ipv6_ra = 1;
                return;
            }
            copy_string(network->address, sizeof(network->address), input);
            say("Gateway [none]: ");
            if (read_line(input, sizeof(input)) == 0 && input[0] && kstrcmp(input, "none") != 0) {
                copy_string(network->gateway, sizeof(network->gateway), input);
            }
            say("DNS servers, space separated [none]: ");
            if (read_line(input, sizeof(input)) == 0 && input[0] && kstrcmp(input, "none") != 0) {
                copy_string(network->dns, sizeof(network->dns), input);
            }
            say("NTP servers, space separated [none]: ");
            if (read_line(input, sizeof(input)) == 0 && input[0] && kstrcmp(input, "none") != 0) {
                copy_string(network->ntp, sizeof(network->ntp), input);
            }
            say("Static network profile will be written to the target rootfs.\n");
            return;
        }
        if (kstrcmp(input, "dhcp") != 0 && kstrcmp(input, "DHCP") != 0) {
            say("Unknown network mode. Using DHCP.\n");
        }
    }

    say("Interface match [en* eth*]: ");
    if (read_line(input, sizeof(input)) == 0 && input[0]) {
        copy_string(network->match_name, sizeof(network->match_name), input);
    }

    say("Accept IPv6 router advertisements? [Y/n]: ");
    if (read_line(input, sizeof(input)) == 0 && (kstrcmp(input, "n") == 0 || kstrcmp(input, "N") == 0)) {
        network->ipv6_ra = 0;
    }
}

static int write_target_network_config(const char *target_root, const struct network_setup *network) {
    char path[256];
    char text[1536];
    size_t out = 0;
    mkdir_p("/mnt/target/etc/systemd/network", 0755);
    path3(path, sizeof(path), target_root, "/etc/systemd/network/20-wired.network", "");

    out = append_string(text, sizeof(text), out, "# KIKI installer generated systemd-networkd profile\n");
    if (!network->enabled) {
        out = append_string(text, sizeof(text), out, "# Network autoconfiguration disabled by installer plan.\n");
        return write_text_file(path, text);
    }
    out = append_string(text, sizeof(text), out, "\n[Match]\nName=");
    out = append_string(text, sizeof(text), out, network->match_name[0] ? network->match_name : "en* eth*");
    out = append_string(text, sizeof(text), out, "\n\n[Link]\nRequiredForOnline=routable\n\n[Network]\n");
    if (network->dhcp4) {
        out = append_string(text, sizeof(text), out, "DHCP=ipv4\n");
    } else {
        out = append_string(text, sizeof(text), out, "DHCP=no\n");
        if (network->address[0]) {
            out = append_string(text, sizeof(text), out, "Address=");
            out = append_string(text, sizeof(text), out, network->address);
            out = append_string(text, sizeof(text), out, "\n");
        }
        if (network->gateway[0]) {
            out = append_string(text, sizeof(text), out, "Gateway=");
            out = append_string(text, sizeof(text), out, network->gateway);
            out = append_string(text, sizeof(text), out, "\n");
        }
        if (network->dns[0]) {
            out = append_string(text, sizeof(text), out, "DNS=");
            out = append_string(text, sizeof(text), out, network->dns);
            out = append_string(text, sizeof(text), out, "\n");
        }
        if (network->ntp[0]) {
            out = append_string(text, sizeof(text), out, "NTP=");
            out = append_string(text, sizeof(text), out, network->ntp);
            out = append_string(text, sizeof(text), out, "\n");
        }
    }
    out = append_string(text, sizeof(text), out, "IPv6AcceptRA=");
    out = append_string(text, sizeof(text), out, network->ipv6_ra ? "yes\n" : "no\n");
    out = append_string(text, sizeof(text), out, "LinkLocalAddressing=ipv6\n");
    out = append_string(text, sizeof(text), out, "LLDP=yes\n");
    out = append_string(text, sizeof(text), out, "EmitLLDP=nearest-bridge\n");
    out = append_string(text, sizeof(text), out, "LLMNR=no\n");
    out = append_string(text, sizeof(text), out, "MulticastDNS=no\n");
    if (network->dhcp4) {
        out = append_string(text, sizeof(text), out, "\n[DHCPv4]\nClientIdentifier=mac\nUseDNS=yes\nUseNTP=yes\nUseHostname=no\nRouteMetric=100\n");
    }
    if (!write_text_file(path, text)) {
        return 0;
    }

    path3(path, sizeof(path), target_root, "/etc/systemd/resolved.conf", "");
    const char *resolved =
        "[Resolve]\n"
        "DNSStubListener=yes\n"
        "LLMNR=no\n"
        "MulticastDNS=no\n"
        "DNSSEC=allow-downgrade\n"
        "Cache=yes\n";
    if (!write_text_file(path, resolved)) {
        return 0;
    }

    path3(path, sizeof(path), target_root, "/etc/resolv.conf", "");
    const char *resolv =
        "# Managed by KIKI base-files and systemd-resolved.\n"
        "nameserver 127.0.0.53\n"
        "options edns0 trust-ad\n";
    return write_text_file(path, resolv);
}

#define KIKI_LAB_PASSWORD_HASH "$6$kikios$KUKwYGxYpK8DOS7AuW2xnrcIqxFBDlgxcpg0h4RTgaE/cYUCvO1cYJNm3j2VHBOCpdvJ1Dvlt0BYdN8.SOew00"

static int line_name_matches(const char *line, long line_len, const char *name) {
    long i = 0;
    while (name[i]) {
        if (i >= line_len || line[i] != name[i]) {
            return 0;
        }
        i++;
    }
    return i < line_len && line[i] == ':';
}

static int file_has_named_entry(const char *path, const char *name) {
    long len = 0;
    if (!read_small_file_raw(path, package_index_buffer, sizeof(package_index_buffer), &len)) {
        return 0;
    }
    long start = 0;
    for (long pos = 0; pos <= len; pos++) {
        if (pos == len || package_index_buffer[pos] == '\n') {
            if (line_name_matches(package_index_buffer + start, pos - start, name)) {
                return 1;
            }
            start = pos + 1;
        }
    }
    return 0;
}

static int ensure_named_line(const char *path, const char *name, const char *line, long mode) {
    if (file_has_named_entry(path, name)) {
        chmod_path(path, mode);
        return 1;
    }
    return append_text_file_mode(path, line, mode);
}

static int line_has_group_member(const char *line, long line_len, const char *member) {
    int colon_count = 0;
    long start = -1;
    long member_len = (long)kstrlen(member);
    for (long i = 0; i < line_len; i++) {
        if (line[i] == ':') {
            colon_count++;
            if (colon_count == 3) {
                start = i + 1;
                break;
            }
        }
    }
    if (start < 0) {
        return 0;
    }
    for (long pos = start; pos <= line_len; pos++) {
        if (pos == line_len || line[pos] == ',') {
            long token_len = pos - start;
            if (token_len == member_len) {
                int same = 1;
                for (long j = 0; j < member_len; j++) {
                    if (line[start + j] != member[j]) {
                        same = 0;
                        break;
                    }
                }
                if (same) {
                    return 1;
                }
            }
            start = pos + 1;
        }
    }
    return 0;
}

static size_t append_bytes(char *out, size_t out_size, size_t pos, const char *data, long len) {
    for (long i = 0; i < len && pos + 1 < out_size; i++) {
        out[pos++] = data[i];
    }
    if (out_size) {
        out[pos < out_size ? pos : out_size - 1] = 0;
    }
    return pos;
}

static int add_group_member(const char *path, const char *group, const char *gid, const char *member) {
    long len = 0;
    size_t out = 0;
    int found = 0;
    if (!read_small_file_raw(path, package_index_buffer, sizeof(package_index_buffer), &len)) {
        out = append_string(copy_buffer, sizeof(copy_buffer), out, group);
        out = append_string(copy_buffer, sizeof(copy_buffer), out, ":x:");
        out = append_string(copy_buffer, sizeof(copy_buffer), out, gid);
        out = append_string(copy_buffer, sizeof(copy_buffer), out, ":");
        out = append_string(copy_buffer, sizeof(copy_buffer), out, member);
        out = append_string(copy_buffer, sizeof(copy_buffer), out, "\n");
        return write_text_file_mode(path, copy_buffer, 0644);
    }

    long start = 0;
    for (long pos = 0; pos <= len; pos++) {
        if (pos == len || package_index_buffer[pos] == '\n') {
            if (pos == len && start == len) {
                break;
            }
            long line_len = pos - start;
            if (line_name_matches(package_index_buffer + start, line_len, group)) {
                found = 1;
                out = append_bytes(copy_buffer, sizeof(copy_buffer), out, package_index_buffer + start, line_len);
                if (!line_has_group_member(package_index_buffer + start, line_len, member)) {
                    if (line_len > 0 && package_index_buffer[start + line_len - 1] != ':' && package_index_buffer[start + line_len - 1] != ',') {
                        out = append_char(copy_buffer, sizeof(copy_buffer), out, ',');
                    }
                    out = append_string(copy_buffer, sizeof(copy_buffer), out, member);
                }
                out = append_char(copy_buffer, sizeof(copy_buffer), out, '\n');
            } else {
                out = append_bytes(copy_buffer, sizeof(copy_buffer), out, package_index_buffer + start, line_len);
                out = append_char(copy_buffer, sizeof(copy_buffer), out, '\n');
            }
            start = pos + 1;
        }
    }
    if (!found) {
        out = append_string(copy_buffer, sizeof(copy_buffer), out, group);
        out = append_string(copy_buffer, sizeof(copy_buffer), out, ":x:");
        out = append_string(copy_buffer, sizeof(copy_buffer), out, gid);
        out = append_string(copy_buffer, sizeof(copy_buffer), out, ":");
        out = append_string(copy_buffer, sizeof(copy_buffer), out, member);
        out = append_string(copy_buffer, sizeof(copy_buffer), out, "\n");
    }
    return write_text_file_mode(path, copy_buffer, 0644);
}

static int write_target_lab_admin_account(const char *target_root, const struct account_setup *account) {
    char path[256];
    char line[384];
    char home[256];
    size_t out = 0;

    path3(home, sizeof(home), target_root, "/home/", account->admin_user);
    mkdir_p(home, 0750);
    chown_path(home, 1000, 1000);
    chmod_path(home, 0750);

    path3(path, sizeof(path), target_root, "/etc/passwd", "");
    out = 0;
    out = append_string(line, sizeof(line), out, account->admin_user);
    out = append_string(line, sizeof(line), out, ":x:1000:1000:KIKI Administrator:/home/");
    out = append_string(line, sizeof(line), out, account->admin_user);
    out = append_string(line, sizeof(line), out, ":/bin/sh\n");
    if (!ensure_named_line(path, account->admin_user, line, 0644)) {
        say("Failed to write admin passwd entry.\n");
        return 0;
    }

    path3(path, sizeof(path), target_root, "/etc/group", "");
    out = 0;
    out = append_string(line, sizeof(line), out, account->admin_user);
    out = append_string(line, sizeof(line), out, ":x:1000:\n");
    if (!ensure_named_line(path, account->admin_user, line, 0644)) {
        say("Failed to write admin group entry.\n");
        return 0;
    }
    if (!add_group_member(path, "sudo", "27", account->admin_user)) {
        say("Failed to add admin user to sudo group.\n");
        return 0;
    }

    path3(path, sizeof(path), target_root, "/etc/shadow", "");
    out = 0;
    out = append_string(line, sizeof(line), out, account->admin_user);
    out = append_string(line, sizeof(line), out, ":");
    out = append_string(line, sizeof(line), out, KIKI_LAB_PASSWORD_HASH);
    out = append_string(line, sizeof(line), out, ":20000:0:99999:7:::\n");
    if (!ensure_named_line(path, account->admin_user, line, 0600)) {
        say("Failed to write admin shadow entry.\n");
        return 0;
    }

    path3(path, sizeof(path), target_root, "/etc/gshadow", "");
    out = 0;
    out = append_string(line, sizeof(line), out, account->admin_user);
    out = append_string(line, sizeof(line), out, ":!::\n");
    ensure_named_line(path, account->admin_user, line, 0600);
    return 1;
}

static int write_target_login_notice(const char *target_root, const struct account_setup *account) {
    char path[256];
    char text[512];
    size_t out = 0;
    path3(path, sizeof(path), target_root, "/etc/issue", "");
    out = append_string(text, sizeof(text), out, "KIKI OS \\r (\\l)\n\n");
    out = append_string(text, sizeof(text), out, "Login with the KIKI administrator account created by the installer:\n");
    out = append_string(text, sizeof(text), out, "  user: ");
    out = append_string(text, sizeof(text), out, account->admin_user);
    out = append_string(text, sizeof(text), out, "\n");
    out = append_string(text, sizeof(text), out, "  password: configured during installation");
    if (kstrcmp(account->admin_password, "kiki") == 0) {
        out = append_string(text, sizeof(text), out, " (lab default: kiki)");
    }
    append_string(text, sizeof(text), out, "\n\n");
    return write_text_file(path, text);
}

static int write_target_sudoers(const char *target_root) {
    char path[256];
    mkdir_p("/mnt/target/etc/sudoers.d", 0750);
    path3(path, sizeof(path), target_root, "/etc/sudoers.d/kiki-admin", "");
    if (!write_text_file(path, "%sudo ALL=(ALL:ALL) ALL\n")) {
        return 0;
    }
    chmod_path(path, 0440);
    return 1;
}

static int apply_target_account_setup(const char *target_root, const struct account_setup *account) {
    char chpasswd_input[256];
    size_t out = 0;
    char *argv_useradd[] = {
        "/usr/sbin/useradd",
        "-m",
        "-G",
        "sudo",
        "-s",
        "/bin/sh",
        (char *)account->admin_user,
        NULL,
    };
    char *argv_chpasswd[] = {"/usr/sbin/chpasswd", NULL};
    char *argv_lock_root[] = {"/usr/bin/passwd", "-l", "root", NULL};

    say("Creating admin user: ");
    say(account->admin_user);
    say("\n");
    if (account->lock_root && kstrcmp(account->admin_password, "kiki") == 0) {
        say("Writing lab default admin account directly for deterministic VM login.\n");
        if (!write_target_lab_admin_account(target_root, account)) {
            return 0;
        }
        if (!write_target_sudoers(target_root)) {
            say("Failed to write sudoers policy.\n");
            return 0;
        }
        write_target_login_notice(target_root, account);
        if (!file_exists("/mnt/target/usr/bin/sudo") && !file_exists("/mnt/target/bin/sudo")) {
            say("sudo binary is not installed yet; sudoers policy is ready for the sudo package.\n");
        }
        return 1;
    }

    if (run_chroot_program(target_root, "/usr/sbin/useradd", argv_useradd) != 0) {
        say("Admin user creation failed.\n");
        return 0;
    }

    out = append_string(chpasswd_input, sizeof(chpasswd_input), out, account->admin_user);
    out = append_string(chpasswd_input, sizeof(chpasswd_input), out, ":");
    out = append_string(chpasswd_input, sizeof(chpasswd_input), out, account->admin_password);
    append_string(chpasswd_input, sizeof(chpasswd_input), out, "\n");
    if (run_chroot_program_input(target_root, "/usr/sbin/chpasswd", argv_chpasswd, chpasswd_input) != 0) {
        say("Admin password setup failed.\n");
        return 0;
    }

    if (account->lock_root) {
        say("Locking direct root login...\n");
        if (run_chroot_program(target_root, "/usr/bin/passwd", argv_lock_root) != 0) {
            say("Root lock failed.\n");
            return 0;
        }
    } else {
        out = 0;
        out = append_string(chpasswd_input, sizeof(chpasswd_input), out, "root:");
        out = append_string(chpasswd_input, sizeof(chpasswd_input), out, account->admin_password);
        append_string(chpasswd_input, sizeof(chpasswd_input), out, "\n");
        if (run_chroot_program_input(target_root, "/usr/sbin/chpasswd", argv_chpasswd, chpasswd_input) != 0) {
            say("Root password setup failed.\n");
            return 0;
        }
    }

    if (!write_target_sudoers(target_root)) {
        say("Failed to write sudoers policy.\n");
        return 0;
    }
    write_target_login_notice(target_root, account);
    if (!file_exists("/mnt/target/usr/bin/sudo") && !file_exists("/mnt/target/bin/sudo")) {
        say("sudo binary is not installed yet; sudoers policy is ready for the sudo package.\n");
    }
    return 1;
}

static size_t append_yaml_kv_string(char *yaml, size_t yaml_size, size_t out, const char *indent, const char *key, const char *value) {
    out = append_string(yaml, yaml_size, out, indent);
    out = append_string(yaml, yaml_size, out, key);
    out = append_string(yaml, yaml_size, out, ": ");
    out = append_yaml_value(yaml, yaml_size, out, value);
    return append_string(yaml, yaml_size, out, "\n");
}

static size_t append_yaml_kv_bool(char *yaml, size_t yaml_size, size_t out, const char *indent, const char *key, int value) {
    out = append_string(yaml, yaml_size, out, indent);
    out = append_string(yaml, yaml_size, out, key);
    out = append_string(yaml, yaml_size, out, ": ");
    out = append_string(yaml, yaml_size, out, value ? "true" : "false");
    return append_string(yaml, yaml_size, out, "\n");
}

static size_t append_yaml_kv_u64(char *yaml, size_t yaml_size, size_t out, const char *indent, const char *key, u64 value) {
    out = append_string(yaml, yaml_size, out, indent);
    out = append_string(yaml, yaml_size, out, key);
    out = append_string(yaml, yaml_size, out, ": ");
    out = append_u64(yaml, yaml_size, out, value);
    return append_string(yaml, yaml_size, out, "\n");
}

static void build_install_plan(struct install_plan *plan, int quick_mode, int unattended_mode, int auto_layout, int has_swap, const char *media_root, const char *index_path, const char *target, const char *esp_part, const char *swap_part, const char *root_part, const char *hostname, u64 disk_mib, u64 mem_mib, u64 esp_mib, u64 swap_mib, u64 root_mib, const struct account_setup *account, const struct network_setup *network) {
    plan->quick_mode = quick_mode;
    plan->unattended_mode = unattended_mode;
    plan->auto_layout = auto_layout;
    plan->has_swap = has_swap;
    plan->disk_mib = disk_mib;
    plan->mem_mib = mem_mib;
    plan->esp_mib = esp_mib;
    plan->swap_mib = swap_mib;
    plan->root_mib = root_mib;
    copy_string(plan->media_root, sizeof(plan->media_root), media_root);
    copy_string(plan->index_path, sizeof(plan->index_path), index_path);
    copy_string(plan->target_disk, sizeof(plan->target_disk), auto_layout ? target : "");
    copy_string(plan->esp_part, sizeof(plan->esp_part), esp_part);
    copy_string(plan->swap_part, sizeof(plan->swap_part), has_swap ? swap_part : "");
    copy_string(plan->root_part, sizeof(plan->root_part), root_part);
    copy_string(plan->hostname, sizeof(plan->hostname), hostname && hostname[0] ? hostname : "localhost.localdomain");
    copy_string(plan->account.admin_user, sizeof(plan->account.admin_user), account->admin_user);
    copy_string(plan->account.admin_password, sizeof(plan->account.admin_password), "");
    plan->account.lock_root = account->lock_root;
    plan->network.enabled = network->enabled;
    plan->network.dhcp4 = network->dhcp4;
    plan->network.ipv6_ra = network->ipv6_ra;
    copy_string(plan->network.match_name, sizeof(plan->network.match_name), network->match_name);
    copy_string(plan->network.address, sizeof(plan->network.address), network->address);
    copy_string(plan->network.gateway, sizeof(plan->network.gateway), network->gateway);
    copy_string(plan->network.dns, sizeof(plan->network.dns), network->dns);
    copy_string(plan->network.ntp, sizeof(plan->network.ntp), network->ntp);
}

static int write_install_plan_yaml(const char *path, const struct install_plan *plan) {
    static char yaml[32768];
    size_t out = 0;
    mkdir_p("/run/kiki", 0755);

    out = append_string(yaml, sizeof(yaml), out, "install_plan:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "  ", "schema", "kiki-install-plan-v1");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "  ", "api_version", "kiki.io/v1alpha1");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "  ", "kind", "InstallPlan");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "  ", "generated_by", "kiki-stage1-tui");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "  ", "mode", plan->unattended_mode ? "unattended" : plan->quick_mode ? "quick-vm" : "guided");
    out = append_string(yaml, sizeof(yaml), out, "  source:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "type", "local-installer-media");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "media_root", plan->media_root);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "repo_index", plan->index_path);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "channel", "stage2-v2");
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "    ", "disconnected_install", 1);
    out = append_string(yaml, sizeof(yaml), out, "  target:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "disk", plan->target_disk);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "partitioning", plan->auto_layout ? "auto-whole-disk" : "manual-existing-partitions");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "partition_table", plan->auto_layout ? "mbr" : "operator-managed");
    out = append_yaml_kv_u64(yaml, sizeof(yaml), out, "    ", "disk_mib", plan->disk_mib);
    out = append_yaml_kv_u64(yaml, sizeof(yaml), out, "    ", "memory_mib", plan->mem_mib);
    out = append_string(yaml, sizeof(yaml), out, "    filesystems:\n");
    out = append_string(yaml, sizeof(yaml), out, "      esp:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "path", plan->esp_part);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "type", "vfat");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "mountpoint", "/boot/efi");
    out = append_yaml_kv_u64(yaml, sizeof(yaml), out, "        ", "size_mib", plan->esp_mib);
    out = append_string(yaml, sizeof(yaml), out, "      swap:\n");
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "        ", "enabled", plan->has_swap);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "path", plan->swap_part);
    out = append_yaml_kv_u64(yaml, sizeof(yaml), out, "        ", "size_mib", plan->has_swap ? plan->swap_mib : 0);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "policy", selected_profile_is_kubernetes() ? "kubernetes-off" : plan->has_swap ? "system" : "disabled");
    out = append_string(yaml, sizeof(yaml), out, "      root:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "path", plan->root_part);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "type", "ext4");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "        ", "mountpoint", "/");
    out = append_yaml_kv_u64(yaml, sizeof(yaml), out, "        ", "size_mib", plan->root_mib);
    out = append_string(yaml, sizeof(yaml), out, "  identity:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "hostname", plan->hostname);
    out = append_string(yaml, sizeof(yaml), out, "  localization:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "locale", selected_locale);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "keymap", selected_keymap);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "timezone", selected_timezone);
    out = append_string(yaml, sizeof(yaml), out, "  network:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "manager", "systemd-networkd");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "resolver", "systemd-resolved");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "mode", !plan->network.enabled ? "off" : plan->network.dhcp4 ? "dhcp" : "static");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "interface_match", plan->network.match_name);
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "    ", "dhcp4", plan->network.dhcp4);
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "    ", "ipv6_accept_ra", plan->network.ipv6_ra);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "address", plan->network.address);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "gateway", plan->network.gateway);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "dns", plan->network.dns);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "ntp", plan->network.ntp);
    out = append_string(yaml, sizeof(yaml), out, "  users:\n");
    out = append_string(yaml, sizeof(yaml), out, "    admin:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "name", plan->account.admin_user);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "primary_group", plan->account.admin_user);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "shell", "/bin/sh");
    out = append_string(yaml, sizeof(yaml), out, "      supplementary_groups:\n");
    out = append_string(yaml, sizeof(yaml), out, "        - sudo\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "password", "runtime-input-not-written-to-plan");
    out = append_string(yaml, sizeof(yaml), out, "    root:\n");
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "      ", "locked", plan->account.lock_root);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "password", plan->account.lock_root ? "disabled" : "runtime-input-not-written-to-plan");
    out = append_string(yaml, sizeof(yaml), out, "  ai:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "mode", selected_ai_mode);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "endpoint", selected_ai_endpoint);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "model", selected_ai_model);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "console_tty", "tty1");
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "    ", "require_approval", 1);
    out = append_string(yaml, sizeof(yaml), out, "  packages:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "profile", selected_package_profile);
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "    ", "dependency_resolution", 0);
    if (selected_package_count == 0) {
        out = append_string(yaml, sizeof(yaml), out, "    selected: []\n");
    } else {
        out = append_string(yaml, sizeof(yaml), out, "    selected:\n");
        for (int i = 0; i < selected_package_count; i++) {
            out = append_string(yaml, sizeof(yaml), out, "      - ");
            out = append_yaml_value(yaml, sizeof(yaml), out, selected_packages[i]);
            out = append_string(yaml, sizeof(yaml), out, "\n");
        }
    }
    out = append_string(yaml, sizeof(yaml), out, "  services:\n");
    out = append_string(yaml, sizeof(yaml), out, "    enable:\n");
    out = append_string(yaml, sizeof(yaml), out, "      - dbus.service\n");
    if (kstrcmp(selected_ai_mode, "off") == 0) {
        out = append_string(yaml, sizeof(yaml), out, "      - getty@tty1.service\n");
    } else {
        if (kstrcmp(selected_ai_mode, "local") == 0) {
            out = append_string(yaml, sizeof(yaml), out, "      - kiki-llama-server.service\n");
        }
        out = append_string(yaml, sizeof(yaml), out, "      - kiki-ai-console@tty1.service\n");
    }
    out = append_string(yaml, sizeof(yaml), out, "      - getty@tty2.service\n");
    out = append_string(yaml, sizeof(yaml), out, "      - systemd-logind.service\n");
    out = append_string(yaml, sizeof(yaml), out, "      - systemd-networkd.service\n");
    out = append_string(yaml, sizeof(yaml), out, "      - systemd-resolved.service\n");
    out = append_string(yaml, sizeof(yaml), out, "      - sshd.service\n");
    out = append_string(yaml, sizeof(yaml), out, "      - kiki-agent.service\n");
    if (selected_profile_is_kubernetes()) {
        if (selected_runtime_is_containerd()) {
            out = append_string(yaml, sizeof(yaml), out, "      - containerd.service\n");
        } else {
            out = append_string(yaml, sizeof(yaml), out, "      - crio.service\n");
        }
        out = append_string(yaml, sizeof(yaml), out, "      - kubelet.service\n");
        out = append_string(yaml, sizeof(yaml), out, "      - chronyd.service\n");
    }
    out = append_string(yaml, sizeof(yaml), out, "  boot:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "loader", "uefi-fallback-bootx64");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "kernel", "/boot/vmlinuz-kiki");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "initramfs", "/boot/initramfs-kiki.img");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "root", plan->root_part);
    out = append_string(yaml, sizeof(yaml), out, "  runtime:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "container_runtime", selected_profile_is_kubernetes() ? selected_container_runtime : "none");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "cgroup_driver", "systemd");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "swap_policy", selected_profile_is_kubernetes() ? "kubernetes-off" : plan->has_swap ? "system" : "disabled");
    out = append_string(yaml, sizeof(yaml), out, "  kubernetes:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "role", selected_kubernetes_role());
    out = append_string(yaml, sizeof(yaml), out, "    kubeadm:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "config_api", "kubeadm.k8s.io/v1beta4");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "action", selected_kubeadm_action());
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "config_template", selected_kubeadm_template());
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "config_output", "/etc/kubernetes/kiki/kubeadm.local.yaml");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "command", selected_kubeadm_command());
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "      ", "control_plane", selected_kubernetes_control_plane());
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "      ", "cri_socket", selected_kubeadm_cri_socket());
    out = append_string(yaml, sizeof(yaml), out, "  firewall:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "backend", "nftables");
    out = append_yaml_kv_bool(yaml, sizeof(yaml), out, "    ", "firewalld", selected_profile_is_kubernetes() && !selected_profile_is_kube_compute());
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "bridge_tool", "iproute2 bridge");
    out = append_string(yaml, sizeof(yaml), out, "  artifacts:\n");
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "runtime_plan", INSTALL_PLAN_PATH);
    out = append_yaml_kv_string(yaml, sizeof(yaml), out, "    ", "installed_plan", "/var/lib/ki2/install-plan.yaml");

    return write_text_file(path, yaml);
}

static void show_saved_install_plan(void) {
    if (!file_exists(INSTALL_PLAN_PATH)) {
        say("No install plan has been generated yet.\n");
        say("Use Start install to create and review one.\n");
        return;
    }
    show_file("install-plan.yaml", INSTALL_PLAN_PATH);
}

static void show_account_status(void) {
    say("\nAccount\n");
    say("-------\n");
    say("default admin user: kiki\n");
    say("sudo: enabled\n");
    say("direct root login: locked by default\n");
    say("password: collected during Start install and not written to install-plan.yaml\n");
}

static void show_runtime_status(void) {
    say("\nRuntime\n");
    say("-------\n");
    if (selected_profile_is_kubernetes()) {
        say("selected runtime: ");
        say(selected_container_runtime);
        say("\n");
    } else {
        say("selected runtime: none\n");
    }
    say("Kubernetes bootstrap/control/compute profiles support CRI-O or containerd with systemd cgroup driver.\n");
    say("firewall backend direction: nftables/firewalld packages\n");
    say("Kubernetes profiles keep swap off; minimal-systemd keeps normal swap.\n");
}

static int write_target_localization_and_ai(void) {
    char path[384];
    char content[512];
    size_t out = 0;
    mkdir_p("/mnt/target/etc/kiki", 0755);

    out = append_string(content, sizeof(content), out, "LANG=");
    out = append_string(content, sizeof(content), out, selected_locale);
    append_string(content, sizeof(content), out, "\n");
    if (!write_text_file("/mnt/target/etc/locale.conf", content)) {
        return 0;
    }
    out = 0;
    out = append_string(content, sizeof(content), out, "KEYMAP=");
    out = append_string(content, sizeof(content), out, selected_keymap);
    append_string(content, sizeof(content), out, "\n");
    if (!write_text_file("/mnt/target/etc/vconsole.conf", content)) {
        return 0;
    }
    out = 0;
    out = append_string(content, sizeof(content), out, selected_timezone);
    append_string(content, sizeof(content), out, "\n");
    if (!write_text_file("/mnt/target/etc/timezone", content)) {
        return 0;
    }
    path3(path, sizeof(path), "/mnt/target/usr/share/zoneinfo/", selected_timezone, "");
    if (file_exists(path)) {
        char zone_source[160];
        size_t zone_out = 0;
        zone_out = append_string(zone_source, sizeof(zone_source), zone_out, "/usr/share/zoneinfo/");
        append_string(zone_source, sizeof(zone_source), zone_out, selected_timezone);
        make_symlink(zone_source, "/mnt/target/etc/localtime");
    }

    if (kstrcmp(selected_ai_mode, "off") != 0) {
        out = 0;
        out = append_string(content, sizeof(content), out, "{\n  \"endpoint\": \"");
        out = append_string(content, sizeof(content), out, selected_ai_endpoint);
        out = append_string(content, sizeof(content), out, "\",\n  \"model\": \"");
        out = append_string(content, sizeof(content), out, selected_ai_model);
        out = append_string(content, sizeof(content), out, "\",\n  \"audit_log\": \"/var/log/kiki/ai-console.jsonl\"\n}\n");
        if (!write_text_file("/mnt/target/etc/kiki/ai-console.json", content)) {
            return 0;
        }
    }
    return 1;
}

static void run_installer_shell(void) {
    char *argv[] = {"/bin/sh", NULL};
    say("\nStarting installer shell. Type exit to return to the installer.\n\n");
    run_program("/bin/sh", argv);
    say("\nReturned from shell.\n");
}

static void show_installer_dashboard(void) {
    tui_clear();
    say("KIKI OS Installer CLI (safe fallback)\n\n");
    say("Install Plan: " INSTALL_PLAN_PATH "\n\n");
    say("[OK] Locale      ");
    say(selected_locale);
    say(", ");
    say(selected_keymap);
    say(", ");
    say(selected_timezone);
    say("\n");
    say("[!] Disk        auto partition: target disk, ESP + root, swap policy\n");
    say("[OK] Network   DHCP default, static available, systemd-networkd\n");
    say("[OK] Account   user: kiki, sudo enabled, root locked\n");
    say("[OK] Source    verified local installer media\n");
    if (selected_package_count > 0) {
        char line[96];
        size_t out = 0;
        out = append_string(line, sizeof(line), out, "[OK] Profile    ");
        out = append_string(line, sizeof(line), out, selected_package_profile);
        out = append_string(line, sizeof(line), out, ": ");
        out = append_u64(line, sizeof(line), out, (u64)selected_package_count);
        out = append_string(line, sizeof(line), out, " packages");
        append_string(line, sizeof(line), out, "\n");
        say(line);
    } else {
        say("[ ] Profile    minimal-systemd\n");
    }
    if (selected_profile_is_kubernetes()) {
        say("[OK] Runtime    ");
        say(selected_container_runtime);
        say(", swap off for Kubernetes\n");
    } else {
        say("[ ] Runtime    none\n");
    }
    say("[OK] AI         ");
    say(selected_ai_mode);
    say(kstrcmp(selected_ai_mode, "off") == 0 ? ", tty1/tty2 login shells\n" : ", tty1 AI + tty2 recovery shell, approval required\n");
    say(file_exists(INSTALL_PLAN_PATH) ? "[OK] Review     ready\n" : "[ ] Review     not ready\n");
    say("\n");
}

static void persist_install_plan_to_target(void) {
    if (!file_exists(INSTALL_PLAN_PATH)) {
        return;
    }
    mkdir_p("/mnt/target/var/lib/ki2", 0755);
    if (copy_file(INSTALL_PLAN_PATH, TARGET_INSTALL_PLAN_PATH)) {
        say("Saved declarative install plan to /var/lib/ki2/install-plan.yaml\n");
    } else {
        say("Failed to save declarative install plan to target root.\n");
    }
}

static int cmdline_value(const char *key, char *out, size_t out_size);

static void run_guided_package_installer(int quick_mode, int unattended_mode) {
    char media_root[256];
    char index_path[384];
    char target[128];
    char esp_part[160];
    char swap_part[160];
    char root_part[160];
    char confirm[192];
    char hostname[64];
    char layout_choice[32];
    char partition_command[160];
    char cmdline_profile[96];
    char cmdline_runtime[32];
    char cmdline_target[128];
    char cmdline_hostname[64];
    char cmdline_locale[64];
    char cmdline_keymap[32];
    char cmdline_timezone[64];
    char cmdline_ai[16];
    char cmdline_ai_endpoint[256];
    struct account_setup account;
    struct network_setup network;
    int auto_layout = 1;
    int has_swap = 0;
    u64 esp_start = 0;
    u64 esp_sectors = 0;
    u64 swap_start = 0;
    u64 swap_sectors = 0;
    u64 root_start = 0;
    u64 root_sectors = 0;
    u64 disk_mib = 0;
    u64 mem_mib = 0;
    u64 esp_mib = 0;
    u64 swap_mib = 0;
    u64 root_mib = 0;
    target[0] = 0;
    esp_part[0] = 0;
    swap_part[0] = 0;
    root_part[0] = 0;
    partition_command[0] = 0;
    cmdline_profile[0] = 0;
    cmdline_runtime[0] = 0;
    cmdline_target[0] = 0;
    cmdline_hostname[0] = 0;
    cmdline_locale[0] = 0;
    cmdline_keymap[0] = 0;
    cmdline_timezone[0] = 0;
    cmdline_ai[0] = 0;
    cmdline_ai_endpoint[0] = 0;

    if (unattended_mode) {
        tui_header("Autoinstall");
        say("Automatic path from kernel command line: kiki.autoinstall=erase|quick-vm.\n");
        say("This mode is destructive and intended for controlled VM or lab automation.\n\n");
    } else if (quick_mode) {
        tui_header("Quick VM install");
        say("Automatic path: pick the largest VM disk, create ESP + swap + root, then install the selected package set.\n");
        say("This mode is intended for disposable VM testing.\n\n");
    } else {
        say("\nKIKI guided package installer\n");
        say("-----------------------------\n");
        say("This path formats ESP/root/swap as requested, extracts selected .ki2 packages, and installs UEFI fallback boot files.\n");
        say("BIOS/MBR bootloader installation is still a later milestone; use UEFI VMs for this guided path.\n\n");
    }

    if (!find_install_media_root(media_root, sizeof(media_root))) {
        say("Cannot find installer media.\n");
        return;
    }
    path3(index_path, sizeof(index_path), media_root, "/kiki/repo/index.x86_64.json", "");
    if (!file_exists(index_path)) {
        say("Cannot find package repository index on installer media.\n");
        return;
    }
    if (unattended_mode) {
        cmdline_value("kiki.profile", cmdline_profile, sizeof(cmdline_profile));
        cmdline_value("kiki.runtime", cmdline_runtime, sizeof(cmdline_runtime));
        cmdline_value("kiki.locale", cmdline_locale, sizeof(cmdline_locale));
        cmdline_value("kiki.keymap", cmdline_keymap, sizeof(cmdline_keymap));
        cmdline_value("kiki.timezone", cmdline_timezone, sizeof(cmdline_timezone));
        cmdline_value("kiki.ai", cmdline_ai, sizeof(cmdline_ai));
        cmdline_value("kiki.ai-endpoint", cmdline_ai_endpoint, sizeof(cmdline_ai_endpoint));
        if (cmdline_locale[0]) {
            copy_string(selected_locale, sizeof(selected_locale), cmdline_locale);
        }
        if (cmdline_keymap[0]) {
            copy_string(selected_keymap, sizeof(selected_keymap), cmdline_keymap);
        }
        if (cmdline_timezone[0]) {
            if (cmdline_timezone[0] == '/' || contains(cmdline_timezone, "..")) {
                say("Invalid kiki.timezone value. Use a relative IANA name such as Asia/Seoul.\n");
                return;
            }
            copy_string(selected_timezone, sizeof(selected_timezone), cmdline_timezone);
        }
        if (cmdline_ai[0]) {
            if (kstrcmp(cmdline_ai, "local") == 0) {
                copy_string(selected_ai_mode, sizeof(selected_ai_mode), "local");
                copy_string(selected_ai_endpoint, sizeof(selected_ai_endpoint), "http://127.0.0.1:8080/v1/chat/completions");
                copy_string(selected_ai_model, sizeof(selected_ai_model), "kiki-ops");
            } else if (kstrcmp(cmdline_ai, "remote") == 0) {
                if (!(starts_with(cmdline_ai_endpoint, "http://") || starts_with(cmdline_ai_endpoint, "https://")) ||
                    contains(cmdline_ai_endpoint, "\"") || contains(cmdline_ai_endpoint, "\\")) {
                    say("kiki.ai=remote requires a safe HTTP(S) kiki.ai-endpoint value.\n");
                    return;
                }
                copy_string(selected_ai_mode, sizeof(selected_ai_mode), "remote");
                copy_string(selected_ai_endpoint, sizeof(selected_ai_endpoint), cmdline_ai_endpoint);
                copy_string(selected_ai_model, sizeof(selected_ai_model), "kiki-ops");
            } else if (kstrcmp(cmdline_ai, "off") == 0) {
                copy_string(selected_ai_mode, sizeof(selected_ai_mode), "off");
                selected_ai_endpoint[0] = 0;
                selected_ai_model[0] = 0;
            } else {
                say("Invalid kiki.ai value. Use local, remote, or off.\n");
                return;
            }
        }
        if (!select_named_package_profile(index_path, cmdline_profile[0] ? cmdline_profile : "minimal-systemd", cmdline_runtime)) {
            return;
        }
    } else if (selected_package_count == 0) {
        select_minimal_systemd_packages(index_path);
    }
    say("Selected package install plan:\n");
    show_selected_packages();

    if (!quick_mode && !unattended_mode) {
        say("\nPartitioning mode\n");
        say("-----------------\n");
        say("1) Automatic whole-disk layout: ESP + swap + root\n");
        say("2) Manual partitions: use shell/fdisk/cfdisk first, then enter ESP/root/swap paths\n");
        say("\nSelect [1]: ");
        if (read_line(layout_choice, sizeof(layout_choice)) == 0) {
            if (!layout_choice[0] || kstrcmp(layout_choice, "1") == 0) {
                auto_layout = 1;
            } else if (kstrcmp(layout_choice, "2") == 0) {
                auto_layout = 0;
            } else if (starts_with(layout_choice, "fdisk ") || starts_with(layout_choice, "cfdisk ")) {
                auto_layout = 0;
                copy_string(partition_command, sizeof(partition_command), layout_choice);
            } else {
                say("Invalid partitioning mode. Select 1, 2, or type fdisk /dev/<disk>.\n");
                return;
            }
        } else {
            return;
        }
    } else {
        auto_layout = 1;
    }

    if (auto_layout) {
        u64 total_sectors = 0;
        list_disks();
        say("\n");
        if (unattended_mode) {
            if (cmdline_value("kiki.target", cmdline_target, sizeof(cmdline_target))) {
                if (!is_whole_disk_path(cmdline_target)) {
                    say("Invalid kiki.target value. Use a whole disk such as /dev/sda.\n");
                    return;
                }
                copy_string(target, sizeof(target), cmdline_target);
            } else if (!get_default_install_disk(target, sizeof(target))) {
                say("No default install disk was found for autoinstall.\n");
                return;
            }
            remember_preferred_install_disk(target);
            say("Autoinstall target disk: ");
            say(target);
            say("\n");
        } else {
            if (!prompt_whole_disk(target, sizeof(target))) {
                return;
            }
        }
        if (!read_block_sectors(target, &total_sectors)) {
            say("Cannot read target disk size from sysfs.\n");
            return;
        }
        disk_mib = total_sectors / 2048ULL;
        mem_mib = read_mem_total_mib();
        calculate_auto_partition_layout(disk_mib, mem_mib, selected_profile_is_kubernetes(), &esp_mib, &swap_mib, &root_mib);
        if (root_mib < 2048ULL) {
            say("Target disk is too small; need at least about 3 GiB for ESP + root.\n");
            return;
        }
        has_swap = swap_mib > 0;
        partition_path(target, 1, esp_part, sizeof(esp_part));
        if (has_swap) {
            partition_path(target, 2, swap_part, sizeof(swap_part));
            partition_path(target, 3, root_part, sizeof(root_part));
        } else {
            partition_path(target, 2, root_part, sizeof(root_part));
        }
        show_auto_partition_layout(target, esp_part, swap_part, root_part, disk_mib, mem_mib, esp_mib, swap_mib, root_mib, selected_profile_is_kubernetes());
    } else {
        char run_shell[16];
        char manual_disk[128];
        char default_esp_part[160];
        char default_swap_part[160];
        char default_root_part[160];
        list_disks();
        say("\nManual mode keeps your partition table and only formats the partitions you enter.\n");
        say("Use a GPT disk with an EFI System Partition, an ext4 root partition, and optional swap.\n");
        if (partition_command[0]) {
            say("\nRunning partition command: ");
            say(partition_command);
            say("\n");
            run_partition_command(partition_command);
        }
        if (!partition_command[0]) {
            say("Open a partitioning shell now? [y/N]: ");
            if (read_line(run_shell, sizeof(run_shell)) == 0 && (kstrcmp(run_shell, "y") == 0 || kstrcmp(run_shell, "Y") == 0)) {
                char *argv[] = {"/bin/sh", NULL};
                say("\nPartitioning shell. Use fdisk/cfdisk if available, then type exit to return.\n");
                say("Example: fdisk /dev/sda\n\n");
                run_program("/bin/sh", argv);
                say("\nReturned from shell.\n");
            }
        }
        ksys(SYS_sync, 0, 0, 0, 0, 0, 0);
        sleep_msec(400);
        detect_manual_partition_defaults(manual_disk, sizeof(manual_disk), default_esp_part, sizeof(default_esp_part), default_swap_part, sizeof(default_swap_part), default_root_part, sizeof(default_root_part));
        show_manual_partition_defaults(manual_disk, default_esp_part, default_swap_part, default_root_part);
        if (!prompt_partition_path("EFI/FAT32 partition path", "/dev/sda1", default_esp_part, esp_part, sizeof(esp_part), 1)) {
            return;
        }
        if (!prompt_partition_path("Root ext4 partition path", "/dev/sda3", default_root_part, root_part, sizeof(root_part), 1)) {
            return;
        }
        if (!prompt_partition_path("Swap partition path", "/dev/sda2", default_swap_part, swap_part, sizeof(swap_part), 0)) {
            return;
        }
        has_swap = swap_part[0] ? 1 : 0;
    }

    if (unattended_mode) {
        if (!cmdline_value("kiki.hostname", cmdline_hostname, sizeof(cmdline_hostname)) || !cmdline_hostname[0]) {
            copy_string(hostname, sizeof(hostname), "localhost.localdomain");
        } else {
            copy_string(hostname, sizeof(hostname), cmdline_hostname);
        }
        say("Hostname: ");
        say(hostname);
        say("\n");
    } else {
        say("Hostname [localhost.localdomain]: ");
        if (read_line(hostname, sizeof(hostname)) != 0 || !hostname[0]) {
            copy_string(hostname, sizeof(hostname), "localhost.localdomain");
        }
    }
    collect_network_setup(&network, quick_mode || unattended_mode);
    collect_account_setup(&account, quick_mode, unattended_mode);
    if (!ensure_selected_ai_packages(index_path) || !ensure_selected_profile_packages(index_path)) {
        return;
    }

    struct install_plan plan;
    build_install_plan(&plan, quick_mode, unattended_mode, auto_layout, has_swap, media_root, index_path, target, esp_part, swap_part, root_part, hostname, disk_mib, mem_mib, esp_mib, swap_mib, root_mib, &account, &network);
    if (!write_install_plan_yaml(INSTALL_PLAN_PATH, &plan)) {
        say("Failed to write declarative install plan.\n");
        return;
    }
    say("\nDeclarative install plan preview\n");
    say("--------------------------------\n");
    say("The installer will execute this plan after confirmation.\n");
    say("Password values are runtime-only and are not written to the plan file.\n\n");
    show_saved_install_plan();

    char expected[192];
    size_t out = 0;
    out = append_string(expected, sizeof(expected), out, "INSTALL ");
    append_string(expected, sizeof(expected), out, auto_layout ? target : root_part);
    if (unattended_mode) {
        say("\nAutoinstall confirmation\n");
        say("------------------------\n");
        say("kiki.autoinstall requested destructive installation without console prompts.\n");
    } else if (quick_mode) {
        say("\nVM test confirmation\n");
        say("--------------------\n");
        say("This will erase and repartition ");
        say(target);
        say(". Press Enter or type yes to continue; type cancel to stop.\n> ");
        if (read_line(confirm, sizeof(confirm)) != 0) {
            return;
        }
        if (confirm[0] && kstrcmp(confirm, "y") != 0 && kstrcmp(confirm, "Y") != 0 && kstrcmp(confirm, "yes") != 0 && kstrcmp(confirm, "YES") != 0) {
            say("Install cancelled.\n");
            return;
        }
    } else {
        say("\nDestructive confirmation required.\n");
        say(auto_layout ? "The selected disk will be repartitioned and formatted.\n" : "The entered partitions will be formatted.\n");
        say("Type exactly: ");
        say(expected);
        say("\n> ");
        if (read_line(confirm, sizeof(confirm)) != 0 || kstrcmp(confirm, expected) != 0) {
            say("Confirmation did not match. Install cancelled.\n");
            return;
        }
    }

    if (auto_layout) {
        say(selected_profile_is_kubernetes() ? "\nWriting MBR partition table: ESP + ext4 root (Kubernetes swap off)...\n" : "\nWriting MBR partition table: ESP + swap + ext4 root...\n");
        if (!write_guided_mbr(target, selected_profile_is_kubernetes(), &esp_start, &esp_sectors, &swap_start, &swap_sectors, &root_start, &root_sectors, &disk_mib, &mem_mib, &esp_mib, &swap_mib, &root_mib)) {
            return;
        }
        has_swap = swap_sectors > 0;
        if (!has_swap) {
            swap_part[0] = 0;
        }
    }
    if (!wait_for_file(esp_part) || !wait_for_file(root_part) || (has_swap && !wait_for_file(swap_part))) {
        say("Partition device nodes did not appear. Reboot and retry if the hypervisor is slow to rescan disks.\n");
        return;
    }
    if (!format_esp_partition(esp_part) || (has_swap && !format_swap_partition(swap_part)) || !format_root_partition(root_part)) {
        say("Filesystem creation failed.\n");
        return;
    }

    mkdir_p("/mnt/target", 0755);
    mkdir_p("/mnt/esp", 0755);
    if (!mount_one("ext4", "/mnt/target", root_part, 0, "")) {
        say("Cannot mount target root partition.\n");
        return;
    }
    if (!mount_one("vfat", "/mnt/esp", esp_part, 0, "")) {
        say("Cannot mount EFI system partition.\n");
        ksys(SYS_umount2, (long)"/mnt/target", 0, 0, 0, 0, 0);
        return;
    }

    if (!install_selected_packages_to_target(media_root, index_path, "/mnt/target")) {
        say("Package install failed. Target disk is partially installed.\n");
        ksys(SYS_umount2, (long)"/mnt/esp", 0, 0, 0, 0, 0);
        ksys(SYS_umount2, (long)"/mnt/target", 0, 0, 0, 0, 0);
        return;
    }
    persist_install_plan_to_target();
    if (!write_target_fstab_and_identity("/mnt/target", esp_part, root_part, has_swap ? swap_part : "", hostname)) {
        say("Failed to write target identity files.\n");
    }
    if (!write_target_network_config("/mnt/target", &network)) {
        say("Failed to write target network configuration.\n");
    }
    if (!write_target_localization_and_ai()) {
        say("Failed to write target localization or AI configuration.\n");
    }
    if (!write_target_ld_so_config("/mnt/target")) {
        say("Failed to write target ld.so.conf.\n");
    }
    ensure_target_baseline_layout();
    if (!refresh_target_ld_cache("/mnt/target")) {
        say("Continuing without a refreshed ld.so.cache.\n");
    }
    if (!apply_target_account_setup("/mnt/target", &account)) {
        say("Account setup failed. Target disk is partially installed.\n");
        ksys(SYS_umount2, (long)"/mnt/esp", 0, 0, 0, 0, 0);
        ksys(SYS_umount2, (long)"/mnt/target", 0, 0, 0, 0, 0);
        return;
    }
    enable_default_systemd_units();
    if (selected_profile_is_kubernetes()) {
        enable_kubernetes_systemd_units();
    }
    if (!install_uefi_boot_files(media_root, "/mnt/target", "/mnt/esp", root_part)) {
        say("Boot file install failed. The root filesystem was installed but may not boot yet.\n");
    }

    ksys(SYS_sync, 0, 0, 0, 0, 0, 0);
    ksys(SYS_umount2, (long)"/mnt/esp", 0, 0, 0, 0, 0);
    ksys(SYS_umount2, (long)"/mnt/target", 0, 0, 0, 0, 0);
    say("\nGuided install finished. Remove the ISO and boot the VM in UEFI mode with Secure Boot disabled.\n");
    if (quick_mode) {
        say("Return to the TUI and choose Reboot when you are ready.\n");
    }
}

static void run_image_installer(void) {
    char image_path[256];
    char target[128];
    char confirm[192];

    say("\nKIKI legacy stage-1 image writer\n");
    say("--------------------------------\n");
    if (selected_package_count == 0) {
        char index_path[384];
        index_path[0] = 0;
        if (find_package_index_path(index_path, sizeof(index_path))) {
            select_minimal_systemd_packages(index_path);
        }
    }
    say("Selected package install plan:\n");
    show_selected_packages();
    say("\nThis legacy path writes the bundled bootable KIKI stage-1 disk image to a VM disk.\n");
    say("The media also carries the selected ki2 package repository for follow-up package installation.\n");
    say("It will erase the selected target disk completely.\n\n");
    if (!find_install_image(image_path, sizeof(image_path))) {
        say("Cannot find /install/kiki-stage1.img on initramfs or installer media.\n");
        say("The ISO may be incomplete or the kernel may not include ISO/CD-ROM support.\n");
        return;
    }
    list_disks();
    say("\nTarget disk path, for example /dev/vda or /dev/sda: ");
    if (read_line(target, sizeof(target)) != 0 || !is_whole_disk_path(target)) {
        say("Invalid target disk. Enter a whole disk such as /dev/sda, not a partition such as /dev/sda1.\n");
        return;
    }

    char expected[192];
    size_t out = 0;
    out = append_string(expected, sizeof(expected), out, "ERASE ");
    append_string(expected, sizeof(expected), out, target);
    say("\nDestructive confirmation required.\n");
    say("Type exactly: ");
    say(expected);
    say("\n> ");
    if (read_line(confirm, sizeof(confirm)) != 0 || kstrcmp(confirm, expected) != 0) {
        say("Confirmation did not match. Install cancelled.\n");
        return;
    }

    say("\nWriting KIKI stage-1 disk image to target disk...\n");
    if (copy_image_to_disk(image_path, target) == 0) {
        say("\nInstall finished. Remove the ISO and boot the VM from the target disk.\n");
    } else {
        say("\nInstall failed. The target disk may be partially written.\n");
    }
}

static void poweroff_now(void) {
    ksys(SYS_sync, 0, 0, 0, 0, 0, 0);
    ksys(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2, LINUX_REBOOT_CMD_POWER_OFF, 0, 0, 0);
    for (;;) {
        ksys(SYS_pause, 0, 0, 0, 0, 0, 0);
    }
}

static void reboot_now(void) {
    ksys(SYS_sync, 0, 0, 0, 0, 0, 0);
    ksys(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2, LINUX_REBOOT_CMD_RESTART, 0, 0, 0);
    for (;;) {
        ksys(SYS_pause, 0, 0, 0, 0, 0, 0);
    }
}

static int cmdline_value(const char *key, char *out, size_t out_size) {
    char buffer[1024];
    if (!read_text_file("/proc/cmdline", buffer, sizeof(buffer))) {
        return 0;
    }
    size_t key_len = kstrlen(key);
    for (size_t i = 0; buffer[i]; i++) {
        if (i > 0 && buffer[i - 1] != ' ') {
            continue;
        }
        size_t k = 0;
        while (key[k] && buffer[i + k] == key[k]) {
            k++;
        }
        if (k == key_len && buffer[i + k] == '=') {
            size_t pos = i + k + 1;
            size_t used = 0;
            while (buffer[pos] && buffer[pos] != ' ' && used + 1 < out_size) {
                out[used++] = buffer[pos++];
            }
            out[used] = 0;
            return used > 0;
        }
    }
    return 0;
}

static int maybe_run_cmdline_autoinstall(void) {
    char mode[32];
    if (!cmdline_value("kiki.autoinstall", mode, sizeof(mode))) {
        return 0;
    }
    if (kstrcmp(mode, "erase") == 0 || kstrcmp(mode, "quick-vm") == 0 || kstrcmp(mode, "yes") == 0 || kstrcmp(mode, "1") == 0) {
        run_guided_package_installer(1, 1);
        return 1;
    }
    say("Ignoring unknown kiki.autoinstall value. Use erase or quick-vm.\n");
    return 0;
}

static int try_graphical_installer(void) {
    char ui[16];
    if (!cmdline_value("kiki.ui", ui, sizeof(ui)) || kstrcmp(ui, "gui") != 0) {
        return 0;
    }
    say("Graphical installer requested by the bootloader.\n");
    if (!file_exists("/usr/bin/kiki-installer-gtk")) {
        say("GTK installer is not present in this initramfs; falling back to the TUI.\n");
        return 0;
    }
    if (!file_exists("/usr/bin/kiki-installer-tui")) {
        say("Shared InstallPlan generator is missing; falling back to the TUI.\n");
        return 0;
    }
    if (!file_exists("/usr/bin/cage")) {
        say("Wayland kiosk compositor is missing; falling back to the TUI.\n");
        return 0;
    }
    mkdir_p("/run/kiki-wayland", 0700);
    mkdir_p("/run/kiki", 0755);
    mkdir_p("/run/udev", 0755);
    mkdir_p("/root", 0700);
    char *mdev_argv[] = {"/sbin/mdev", "-s", NULL};
    run_program("/sbin/mdev", mdev_argv);
    if (file_exists("/usr/lib/systemd/systemd-udevd") && file_exists("/usr/bin/udevadm")) {
        char *udevd_argv[] = {
            "/usr/lib/systemd/systemd-udevd",
            "--daemon",
            "--resolve-names=never",
            NULL,
        };
        if (run_program("/usr/lib/systemd/systemd-udevd", udevd_argv) == 0) {
            char *trigger_subsystems_argv[] = {
                "/usr/bin/udevadm", "trigger", "--type=subsystems", "--action=add", NULL,
            };
            char *trigger_devices_argv[] = {
                "/usr/bin/udevadm", "trigger", "--type=devices", "--action=add", NULL,
            };
            char *settle_argv[] = {"/usr/bin/udevadm", "settle", "--timeout=8", NULL};
            run_program("/usr/bin/udevadm", trigger_subsystems_argv);
            run_program("/usr/bin/udevadm", trigger_devices_argv);
            run_program("/usr/bin/udevadm", settle_argv);
        } else {
            say("udevd could not start; Cage will use the existing device nodes.\n");
        }
    } else {
        say("udev runtime is unavailable; Cage will use the existing device nodes.\n");
    }
    char *argv[] = {"/usr/bin/cage", "--", "/usr/bin/kiki-installer-gtk", NULL};
    say("Starting GTK installer with the cage Wayland compositor.\n");
    int status = run_graphical_program("/usr/bin/cage", argv);
    say("Graphical installer exited with status ");
    char status_line[32];
    size_t out = 0;
    out = append_u64(status_line, sizeof(status_line), out, (u64)status);
    append_string(status_line, sizeof(status_line), out, "; returning to the TUI.\n");
    say(status_line);
    if (status != 0) {
        show_file("GUI failure log", "/run/kiki/gui-installer.log");
        say("The fallback TUI uses ASCII because the Linux kernel VT has no Korean glyph renderer.\n");
        sleep_msec(2500);
    }
    return 1;
}

static int try_fullscreen_tui_installer(void) {
    char ui[16];
    if (!cmdline_value("kiki.ui", ui, sizeof(ui))) {
        return 0;
    }
    if (kstrcmp(ui, "gui") != 0 && kstrcmp(ui, "tui") != 0) {
        return 0;
    }
    if (!file_exists("/usr/bin/kiki-installer-tui")) {
        say("Full-screen TUI is not present in this initramfs; falling back to the CLI.\n");
        return 0;
    }
    char *argv[] = {
        "/usr/bin/kiki-installer-tui",
        "--fullscreen",
        "--ascii",
        "--plan",
        "/run/kiki/install-plan.yaml",
        NULL,
    };
    mkdir_p("/run/kiki", 0755);
    say("Starting the full-screen installer TUI. Press c or q to enter the CLI fallback.\n");
    int status = run_program("/usr/bin/kiki-installer-tui", argv);
    say("Full-screen TUI exited with status ");
    char status_line[32];
    size_t out = 0;
    out = append_u64(status_line, sizeof(status_line), out, (u64)status);
    append_string(status_line, sizeof(status_line), out, "; entering the CLI fallback.\n");
    say(status_line);
    return 1;
}

static int handoff_to_installed_system(void) {
    char rootdev[160];
    if (!cmdline_value("root", rootdev, sizeof(rootdev))) {
        say("No root= kernel argument found; staying in stage-1 prompt.\n");
        return 0;
    }
    say("Mounting installed root: ");
    say(rootdev);
    say("\n");
    mkdir_p("/sysroot", 0755);
    if (!mount_one("ext4", "/sysroot", rootdev, 0, "")) {
        say("Cannot mount installed root. Staying in stage-1 prompt.\n");
        return 0;
    }
    mkdir_p("/sysroot/dev", 0755);
    mkdir_p("/sysroot/proc", 0755);
    mkdir_p("/sysroot/sys", 0755);
    mkdir_p("/sysroot/run", 0755);
    mkdir_p("/sysroot/tmp", 01777);
    mount_one("devtmpfs", "/sysroot/dev", "devtmpfs", 0, "mode=0755");
    mount_one("proc", "/sysroot/proc", "proc", 0, "");
    mount_one("sysfs", "/sysroot/sys", "sysfs", 0, "");
    mount_one("tmpfs", "/sysroot/run", "tmpfs", 0, "mode=0755");

    say("Switching to installed systemd PID 1...\n");
    ksys(SYS_chroot, (long)"/sysroot", 0, 0, 0, 0, 0);
    ksys(SYS_chdir, (long)"/", 0, 0, 0, 0, 0);
    char *argv_systemd[] = {"/usr/lib/systemd/systemd", NULL};
    char *argv_init[] = {"/usr/sbin/init", NULL};
    static char *envp[] = {
        "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME=/",
        "TERM=linux",
        NULL,
    };
    if (file_exists("/usr/lib/systemd/systemd")) {
        ksys(SYS_execve, (long)"/usr/lib/systemd/systemd", (long)argv_systemd, (long)envp, 0, 0, 0);
    }
    ksys(SYS_execve, (long)"/usr/sbin/init", (long)argv_init, (long)envp, 0, 0, 0);
    say("Could not exec installed systemd/init. PID 1 fallback prompt will continue.\n");
    return 0;
}

static void installer_cli_menu(void) {
    char choice[16];
    for (;;) {
        show_installer_dashboard();
        say("1) Language / keyboard / timezone\n");
        say("2) Disk\n");
        say("3) Network\n");
        say("4) Account\n");
        say("5) Package source / trust\n");
        say("6) Profile\n");
        say("7) Runtime\n");
        say("8) AI management console\n");
        say("9) Review install plan\n");
        say("10) Start install\n");
        say("s) Shell\n");
        say("q) Power off\n");
        say("\nSelect: ");
        if (read_line(choice, sizeof(choice)) != 0) {
            continue;
        }
        if (kstrcmp(choice, "1") == 0) {
            localization_menu();
        } else if (kstrcmp(choice, "2") == 0) {
            disk_menu();
        } else if (kstrcmp(choice, "3") == 0) {
            tui_header("Network");
            show_network_tools();
            tui_wait();
        } else if (kstrcmp(choice, "4") == 0) {
            tui_header("Account");
            show_account_status();
            tui_wait();
        } else if (kstrcmp(choice, "5") == 0) {
            source_trust_menu();
        } else if (kstrcmp(choice, "6") == 0) {
            package_selection_menu();
        } else if (kstrcmp(choice, "7") == 0) {
            runtime_menu();
        } else if (kstrcmp(choice, "8") == 0) {
            ai_menu();
        } else if (kstrcmp(choice, "9") == 0) {
            tui_header("Install plan");
            show_saved_install_plan();
            tui_wait();
        } else if (kstrcmp(choice, "10") == 0) {
            run_guided_package_installer(0, 0);
            tui_wait();
        } else if (kstrcmp(choice, "s") == 0 || kstrcmp(choice, "S") == 0) {
            run_installer_shell();
            tui_wait();
        } else if (kstrcmp(choice, "q") == 0 || kstrcmp(choice, "Q") == 0 || kstrcmp(choice, "0") == 0) {
            poweroff_now();
        } else if (kstrcmp(choice, "x") == 0 || kstrcmp(choice, "X") == 0) {
            run_guided_package_installer(1, 0);
            tui_wait();
        } else if (kstrcmp(choice, "r") == 0 || kstrcmp(choice, "R") == 0) {
            reboot_now();
        } else {
            say("Unknown selection.\n");
            tui_wait();
        }
    }
}

static void installed_prompt(void) {
    char command[96];
    say("\nKIKI stage-1 prompt ready. Type 'help' for commands.\n\n");
    for (;;) {
        say("kiki# ");
        if (read_line(command, sizeof(command)) != 0) {
            say("\n");
            continue;
        }
        if (command[0] == 0) {
            continue;
        }
        if (kstrcmp(command, "help") == 0 || kstrcmp(command, "?") == 0) {
            prompt_help();
        } else if (kstrcmp(command, "status") == 0) {
            smoke_status();
            show_cmdline();
        } else if (kstrcmp(command, "services") == 0) {
            show_services();
        } else if (kstrcmp(command, "packages") == 0 || kstrcmp(command, "package") == 0 || kstrcmp(command, "bos") == 0) {
            show_package_media();
        } else if (kstrcmp(command, "plan") == 0 || kstrcmp(command, "install-plan") == 0) {
            show_file("install-plan", "/var/lib/ki2/install-plan.yaml");
        } else if (kstrcmp(command, "network") == 0 || kstrcmp(command, "net") == 0) {
            show_network_tools();
        } else if (kstrcmp(command, "disk") == 0 || kstrcmp(command, "disks") == 0) {
            show_disk_tools();
        } else if (kstrcmp(command, "lsblk") == 0 || kstrcmp(command, "disks") == 0) {
            list_disks();
        } else if (kstrcmp(command, "mounts") == 0) {
            show_file("mounts", "/proc/mounts");
        } else if (kstrcmp(command, "cmdline") == 0) {
            show_cmdline();
        } else if (kstrcmp(command, "os") == 0) {
            show_file("os-release", "/etc/os-release");
        } else if (kstrcmp(command, "uptime") == 0) {
            show_file("uptime", "/proc/uptime");
        } else if (kstrcmp(command, "clear") == 0) {
            logo();
        } else if (kstrcmp(command, "poweroff") == 0 || kstrcmp(command, "halt") == 0) {
            poweroff_now();
        } else if (kstrcmp(command, "reboot") == 0) {
            reboot_now();
        } else if (kstrcmp(command, "exit") == 0 || kstrcmp(command, "logout") == 0) {
            say("PID 1 cannot exit here. Use 'poweroff' or 'reboot'.\n");
        } else {
            say("Unknown command. Type 'help'.\n");
        }
    }
}

static int kmain(void) {
    ksys(SYS_setsid, 0, 0, 0, 0, 0, 0);
    setup_mounts();
    logo();
    show_services();
    smoke_status();
    show_cmdline();

#ifdef KIKI_ENABLE_INSTALLER
    if (!maybe_run_cmdline_autoinstall()) {
        try_graphical_installer();
        try_fullscreen_tui_installer();
        installer_cli_menu();
    }
#elif defined(KIKI_INSTALLED_STAGE1)
    handoff_to_installed_system();
    installed_prompt();
#else
    say("\nThe VM will stay here for inspection. Power it off from the hypervisor.\n");
    for (;;) {
        ksys(SYS_pause, 0, 0, 0, 0, 0, 0);
    }
#endif
    return 0;
}

void _start(void) {
    int rc = kmain();
    ksys(SYS_exit, rc, 0, 0, 0, 0, 0);
    for (;;) {
    }
}
"""


class BootIsoError(RuntimeError):
    pass


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def safe_filename_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip())
    cleaned = cleaned.strip("-_")
    return cleaned or "unknown"


def git_output(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def format_iso_build_stamp(build_date: str, revision: str) -> str:
    clean_date = "".join(ch for ch in build_date if ch.isdigit())[:8] or "00000000"
    clean_revision = "".join(ch for ch in revision if ch.isalnum() or ch in ("-", "_")) or "revunknown"
    if not clean_revision.startswith("rev"):
        clean_revision = f"rev{clean_revision}"
    return f"{clean_date}-{clean_revision}"


def iso_build_info(repo_root: Path) -> dict[str, Any]:
    build_date = os.environ.get("KIKI_ISO_DATE") or dt.datetime.now().strftime("%Y%m%d")
    revision = os.environ.get("KIKI_ISO_REV") or git_output(repo_root, "rev-list", "--count", "HEAD") or "unknown"
    commit = git_output(repo_root, "rev-parse", "--short", "HEAD") or "unknown"
    status = git_output(repo_root, "status", "--porcelain")
    stamp = format_iso_build_stamp(build_date, revision)
    if status:
        stamp = f"{stamp}-dirty-{safe_filename_component(commit)}"
    return {
        "date": build_date,
        "revision": f"rev{revision}" if not str(revision).startswith("rev") else str(revision),
        "commit": commit,
        "dirty": bool(status),
        "stamp": stamp,
    }


def read_repo_channel(repo_dir: Path, arch: str) -> str | None:
    metadata = repo_dir / f"metadata.{arch}.json"
    if not metadata.exists():
        return None
    try:
        data = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    channel = str(data.get("channel") or "").strip()
    return channel or None


def profile_release_name(profile: str) -> str:
    if profile == "bootstrap-stage1":
        return DEFAULT_STAGE1_RELEASE
    return profile


def iso_release_name(repo_dir: Path, arch: str, profile: str, override: str | None = None) -> str:
    if override:
        return safe_filename_component(override)
    return safe_filename_component(read_repo_channel(repo_dir, arch) or profile_release_name(profile))


def default_iso_output(
    repo_root: Path,
    release_name: str,
    suffix: str,
    arch: str,
    build_info: dict[str, Any],
) -> Path:
    return repo_root / "dist" / "iso" / f"kiki-{release_name}-{suffix}-{arch}-{build_info['stamp']}.iso"


def copytree_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir()):
        dest = target / child.name
        if child.is_dir():
            shutil.copytree(child, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, dest)


def read_repo_index(repo_dir: Path, arch: str) -> dict[str, Any]:
    index = repo_dir / f"index.{arch}.json"
    if not index.exists():
        return {"packages": []}
    return json.loads(index.read_text(encoding="utf-8"))


def copy_package_payloads(repo_dir: Path, packages_dir: Path | None, target: Path, arch: str) -> dict[str, Any]:
    if packages_dir is None or not packages_dir.exists():
        return {
            "path": None,
            "copied": 0,
            "missing": [],
            "total_size": 0,
        }

    index = read_repo_index(repo_dir, arch)
    package_entries = index.get("packages", [])
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    total_size = 0
    missing: list[str] = []
    seen: set[str] = set()
    for item in package_entries:
        if not isinstance(item, dict):
            continue
        filename = item.get("file")
        if not isinstance(filename, str) or not filename.endswith(".ki2") or filename in seen:
            continue
        seen.add(filename)
        source = packages_dir / filename
        if not source.exists():
            missing.append(filename)
            continue
        shutil.copy2(source, target / filename)
        copied += 1
        total_size += source.stat().st_size

    manifest = {
        "schema": "ki2-package-media-v1",
        "arch": arch,
        "copied": copied,
        "missing": missing,
        "total_size": total_size,
        "path": f"kiki/packages/{arch}",
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def write_rootfs_tar(rootfs_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        for path in sorted(rootfs_dir.rglob("*")):
            rel = path.relative_to(rootfs_dir).as_posix()
            tar.add(path, arcname=rel, recursive=False)


def read_package_manifest(package: Path) -> dict[str, Any]:
    with tarfile.open(package, "r:gz") as tar:
        member = tar.getmember("manifest.json")
        handle = tar.extractfile(member)
        if handle is None:
            raise BootIsoError(f"package manifest is unreadable: {package}")
        return json.loads(handle.read().decode("utf-8"))


def latest_package(packages_dir: Path, name: str) -> Path:
    matches = sorted(packages_dir.glob(f"{name}-*.ki2"))
    if not matches:
        raise BootIsoError(f"installer runtime package not found: {name}")
    return matches[-1]


def extract_package_members(package: Path, target_root: Path, wanted: set[str], prefixes: tuple[str, ...] = ()) -> int:
    extracted = 0
    with tarfile.open(package, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.startswith("rootfs/"):
                continue
            rel = member.name[len("rootfs/") :]
            if not rel:
                continue
            include = rel in wanted or any(rel.startswith(prefix) for prefix in prefixes)
            if not include:
                continue
            dest = target_root / rel
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                dest.chmod(member.mode & 0o7777)
                extracted += 1
            elif member.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                with dest.open("wb") as out:
                    shutil.copyfileobj(handle, out)
                dest.chmod(member.mode & 0o7777)
                extracted += 1
            elif member.issym():
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() or dest.is_symlink():
                    dest.unlink()
                dest.symlink_to(member.linkname)
                extracted += 1
            elif member.islnk():
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() or dest.is_symlink():
                    dest.unlink()
                linkname = member.linkname
                if linkname.startswith("rootfs/"):
                    linkname = linkname[len("rootfs/") :]
                target = target_root / linkname
                try:
                    if target.exists():
                        os.link(target, dest)
                    else:
                        dest.symlink_to(linkname)
                except OSError:
                    if target.exists() and target.is_file():
                        shutil.copy2(target, dest)
                    else:
                        dest.symlink_to(linkname)
                extracted += 1
    return extracted


def chmod_dynamic_loaders(root: Path) -> None:
    for rel in (
        "lib64/ld-linux-x86-64.so.2",
        "lib/ld-linux-x86-64.so.2",
        "lib/ld-linux.so.2",
        "usr/lib64/ld-linux-x86-64.so.2",
    ):
        path = root / rel
        if path.exists() and not path.is_symlink():
            path.chmod(0o755)


def link_installer_runtime_lib64(root: Path) -> None:
    lib = root / "lib"
    lib64 = root / "lib64"
    if not lib.exists():
        return
    lib64.mkdir(parents=True, exist_ok=True)
    for path in sorted(lib.glob("*.so*")):
        if not path.is_file() and not path.is_symlink():
            continue
        dest = lib64 / path.name
        if dest.exists() or dest.is_symlink():
            continue
        dest.symlink_to(Path("../lib") / path.name)


def add_installer_runtime(root: Path, packages_dir: Path) -> dict[str, Any]:
    runtime = {
        "schema": "ki2-installer-runtime-v1",
        "packages": {},
        "tools": [
            "/bin/busybox",
            "/bin/tar",
            "/usr/bin/kiki-installer-tui",
            "/sbin/mkfs.vfat",
            "/sbin/fdisk",
            "/sbin/cfdisk",
            "/sbin/mkswap",
            "/sbin/swapon",
            "/usr/sbin/mke2fs",
            "/usr/sbin/mkfs.ext4",
        ],
    }
    glibc = latest_package(packages_dir, "glibc")
    busybox = latest_package(packages_dir, "busybox")
    e2fsprogs = latest_package(packages_dir, "e2fsprogs")
    util_linux = latest_package(packages_dir, "util-linux")
    ncurses = latest_package(packages_dir, "ncurses")
    installer_tui = latest_package(packages_dir, "kiki-installer-tui")
    try:
        installer_gtk = latest_package(packages_dir, "kiki-installer-gtk")
    except BootIsoError:
        installer_gtk = None

    runtime["packages"] = {
        "glibc": glibc.name,
        "busybox": busybox.name,
        "e2fsprogs": e2fsprogs.name,
        "util-linux": util_linux.name,
        "ncurses": ncurses.name,
        "kiki-installer-tui": installer_tui.name,
    }
    if installer_gtk is not None:
        runtime["packages"]["kiki-installer-gtk"] = installer_gtk.name
        runtime["tools"].extend(["/usr/bin/cage", "/usr/bin/kiki-installer-gtk"])

    extract_package_members(
        glibc,
        root,
        {
            "etc/ld.so.cache",
        },
        prefixes=("lib64/",),
    )
    chmod_dynamic_loaders(root)
    extract_package_members(busybox, root, {"bin/busybox"})
    extract_package_members(
        util_linux,
        root,
        {
            "sbin/cfdisk",
            "sbin/fdisk",
            "sbin/sfdisk",
            "lib/libblkid.so.1",
            "lib/libblkid.so.1.1.0",
            "lib/libfdisk.so.1",
            "lib/libfdisk.so.1.1.0",
            "lib/libmount.so.1",
            "lib/libmount.so.1.1.0",
            "lib/libsmartcols.so.1",
            "lib/libsmartcols.so.1.1.0",
            "lib/libuuid.so.1",
            "lib/libuuid.so.1.3.0",
        },
    )
    extract_package_members(
        ncurses,
        root,
        set(),
        prefixes=(
            "lib/libncursesw.so",
            "lib/libtinfo.so",
            "usr/share/terminfo/",
        ),
    )
    extract_package_members(
        e2fsprogs,
        root,
        {
            "usr/etc/mke2fs.conf",
            "usr/sbin/mke2fs",
            "usr/sbin/mkfs.ext4",
        },
    )
    extract_package_members(installer_tui, root, {"usr/bin/kiki-installer-tui"})
    if installer_gtk is not None:
        extract_package_members(installer_gtk, root, set(), prefixes=("",))
        runtime["graphical"] = {
            "enabled": True,
            "frontend": "/usr/bin/kiki-installer-gtk",
            "compositor": "/usr/bin/cage",
            "locale": "C.UTF-8",
            "font": "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        }
    else:
        runtime["graphical"] = {"enabled": False, "fallback": "tui"}
    link_installer_runtime_lib64(root)

    for dirname in ("bin", "sbin", "usr/bin", "usr/sbin", "usr/etc", "install"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    applets = {
        root / "bin" / "sh": "busybox",
        root / "bin" / "tar": "busybox",
        root / "bin" / "gzip": "busybox",
        root / "bin" / "gunzip": "busybox",
        root / "bin" / "cat": "busybox",
        root / "bin" / "ls": "busybox",
        root / "bin" / "mkdir": "busybox",
        root / "bin" / "mount": "busybox",
        root / "bin" / "umount": "busybox",
        root / "bin" / "sync": "busybox",
        root / "sbin" / "mdev": "../bin/busybox",
        root / "sbin" / "mkfs.vfat": "../bin/busybox",
        root / "sbin" / "mkswap": "../bin/busybox",
        root / "sbin" / "swapon": "../bin/busybox",
    }
    for link, target in applets.items():
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)
    (root / "install" / "runtime-manifest.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return runtime


def extract_kernel_from_package(package: Path, target: Path) -> Path | None:
    with tarfile.open(package, "r:gz") as tar:
        try:
            manifest = read_package_manifest(package)
        except (KeyError, json.JSONDecodeError, BootIsoError):
            return None
        if manifest.get("name") != "linux":
            return None

        candidates = [
            member
            for member in tar.getmembers()
            if member.isfile()
            and member.name.startswith("rootfs/boot/")
            and Path(member.name).name.startswith(("vmlinuz", "bzImage"))
        ]
        if not candidates:
            return None

        member = sorted(candidates, key=lambda item: item.name)[0]
        handle = tar.extractfile(member)
        if handle is None:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as out:
            shutil.copyfileobj(handle, out)
        target.chmod(0o644)
        return target


def find_kernel(rootfs_dir: Path, packages_dir: Path, work_dir: Path, requested: Path | None = None) -> Path:
    if requested:
        if not requested.exists():
            raise BootIsoError(f"kernel image not found: {requested}")
        return requested

    direct = rootfs_dir / "boot" / "vmlinuz-kiki"
    if direct.exists():
        return direct

    boot_dir = rootfs_dir / "boot"
    if boot_dir.exists():
        for candidate in sorted(boot_dir.glob("vmlinuz*")) + sorted(boot_dir.glob("bzImage*")):
            if candidate.is_file():
                return candidate

    if packages_dir.exists():
        for package in sorted(packages_dir.glob("linux-*.ki2"), reverse=True):
            extracted = extract_kernel_from_package(package, work_dir / "vmlinuz-kiki")
            if extracted:
                return extracted

    raise BootIsoError(
        f"kernel image not found in {rootfs_dir / 'boot'} or {packages_dir}; build the linux package first"
    )


def require_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise BootIsoError(f"required tool not found: {name}")
    return found


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compile_static_init(
    output: Path,
    work_dir: Path,
    *,
    cc: str,
    installer: bool = False,
    installed: bool = False,
) -> None:
    compiler = shutil.which(cc) or (cc if Path(cc).exists() else None)
    if not compiler:
        raise BootIsoError(f"C compiler not found: {cc}")

    source = work_dir / "kiki-init.c"
    source.write_text(INIT_C.strip() + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        compiler,
        "-Os",
        "-static",
        "-nostdlib",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-fno-pic",
        "-no-pie",
        "-march=x86-64",
        "-mno-sse",
        "-mno-sse2",
        "-s",
        "-Wall",
        "-Wextra",
        "-Wno-unused-function",
        "-Wl,--build-id=none",
    ]
    if installer:
        cmd.append("-DKIKI_ENABLE_INSTALLER=1")
    if installed:
        cmd.append("-DKIKI_INSTALLED_STAGE1=1")
    cmd.extend(["-o", str(output), str(source)])
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise BootIsoError("static /init build failed; install gcc in the builder") from exc
    output.chmod(0o755)


def _pad4(buffer: bytearray) -> None:
    buffer.extend(b"\0" * ((4 - (len(buffer) % 4)) % 4))


def _add_newc_entry(buffer: bytearray, ino: int, name: str, data: bytes, mode: int, mtime: int, nlink: int) -> None:
    name_bytes = name.encode("utf-8") + b"\0"
    fields = [
        "070701",
        f"{ino:08x}",
        f"{mode:08x}",
        f"{0:08x}",
        f"{0:08x}",
        f"{nlink:08x}",
        f"{mtime:08x}",
        f"{len(data):08x}",
        f"{0:08x}",
        f"{0:08x}",
        f"{0:08x}",
        f"{0:08x}",
        f"{len(name_bytes):08x}",
        f"{0:08x}",
    ]
    buffer.extend("".join(fields).encode("ascii"))
    buffer.extend(name_bytes)
    _pad4(buffer)
    buffer.extend(data)
    _pad4(buffer)


def write_newc_gzip(source_dir: Path, output: Path) -> None:
    archive = bytearray()
    ino = 1
    for path in sorted(source_dir.rglob("*")):
        rel = path.relative_to(source_dir).as_posix()
        st = os.lstat(path)
        perm = stat.S_IMODE(st.st_mode)
        mtime = int(st.st_mtime)
        if path.is_dir():
            _add_newc_entry(archive, ino, rel, b"", stat.S_IFDIR | perm, mtime, 2)
        elif path.is_symlink():
            _add_newc_entry(archive, ino, rel, os.readlink(path).encode("utf-8"), stat.S_IFLNK | 0o777, mtime, 1)
        elif path.is_file():
            _add_newc_entry(archive, ino, rel, path.read_bytes(), stat.S_IFREG | perm, mtime, 1)
        ino += 1
    _add_newc_entry(archive, ino, "TRAILER!!!", b"", 0, 0, 1)

    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(filename=str(output), mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(archive)


def build_initramfs(
    output: Path,
    work_dir: Path,
    *,
    arch: str,
    profile: str,
    cc: str,
    installer: bool = False,
    installed: bool = False,
    install_image: Path | None = None,
    packages_dir: Path | None = None,
) -> None:
    root = work_dir / "initramfs-root"
    if root.exists():
        shutil.rmtree(root)
    for dirname in ("dev", "etc", "proc", "run", "sys", "tmp"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    (root / "tmp").chmod(0o1777)

    compile_static_init(root / "init", work_dir, cc=cc, installer=installer, installed=installed)
    installer_runtime: dict[str, Any] | None = None
    if installer:
        if packages_dir is None or not packages_dir.exists():
            raise BootIsoError("installer mode needs built glibc, busybox, and e2fsprogs packages for the runtime")
        installer_runtime = add_installer_runtime(root, packages_dir)
    if install_image:
        install_dir = root / "install"
        install_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(install_image, install_dir / "kiki-stage1.img")
        (install_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": "ki2-install-image-v1",
                    "path": "/install/kiki-stage1.img",
                    "size": install_image.stat().st_size,
                    "sha256": sha256_file(install_image),
                    "mode": "installed-stage1",
                    "installer_runtime": installer_runtime,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    (root / "etc" / "os-release").write_text(
        "\n".join(
            [
                f'NAME="KIKI OS {"Installer" if installer else "Installed Systemd Handoff" if installed else "Boot Smoke"}"',
                "ID=kiki",
                f'VERSION="{profile}"',
                f'KIKI_ARCH="{arch}"',
                f'KIKI_INSTALLER="{"1" if installer else "0"}"',
                f'KIKI_SYSTEMD_HANDOFF="{"1" if installed else "0"}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "README").write_text(
        "This initramfs is generated by tools/ki2bootiso.py for KIKI VM boot media.\n",
        encoding="utf-8",
    )
    write_newc_gzip(root, output)


def grub_cfg(profile: str, arch: str, *, installer: bool = False, installed: bool = False) -> str:
    title = "installer" if installer else "installed systemd handoff" if installed else "boot smoke"
    boot_flag = "installer" if installer else "installed" if installed else "smoke"
    ui_default = " kiki.ui=gui" if installer else ""
    auto_args = f"keep_bootcon loglevel=4 panic=-1 init=/init kiki.boot={boot_flag}{ui_default}"
    tui_args = f"keep_bootcon loglevel=4 panic=-1 init=/init kiki.boot={boot_flag} kiki.ui=tui"
    cli_args = f"keep_bootcon loglevel=4 panic=-1 init=/init kiki.boot={boot_flag} kiki.ui=cli"
    uefi_args = f"{auto_args} video=efifb:1024x768"
    hyperv_args = f"{auto_args} video=hyperv_fb:1024x768 video=efifb:1024x768 fbcon=map:0"
    bios_args = f"quiet loglevel=3 nomodeset vga=normal panic=-1 init=/init kiki.boot={boot_flag} kiki.ui=cli"
    debug_args = (
        f"keep_bootcon ignore_loglevel loglevel=7 panic=-1 init=/init kiki.boot={boot_flag} "
        "video=hyperv_fb:1024x768 video=efifb:1024x768 fbcon=map:0 efi=debug kiki.ui=cli"
    )
    return "\n".join(
        [
            "insmod all_video",
            "insmod efi_gop",
            "insmod efi_uga",
            "insmod font",
            "insmod gfxterm",
            "serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1",
            "if loadfont /boot/grub/fonts/unicode.pf2; then",
            "    terminal_output gfxterm console serial",
            "else",
            "    terminal_output console serial",
            "fi",
            "terminal_input console serial",
            "set gfxmode=1024x768,800x600,auto",
            "set gfxpayload=keep",
            "set timeout=4",
            "set default=0",
            "",
            f'menuentry "KIKI OS {"graphical installer (default)" if installer else title + " (" + arch + ", auto console)"}" {{',
            "    set gfxpayload=keep",
            f"    linux /boot/vmlinuz-kiki console=tty0 {auto_args}",
            "    initrd /boot/initramfs-kiki.img",
            "}",
            "",
            *(
                [
                    f'menuentry "KIKI OS full-screen TUI installer ({arch})" {{',
                    "    set gfxpayload=keep",
                    f"    linux /boot/vmlinuz-kiki console=tty0 {tui_args}",
                    "    initrd /boot/initramfs-kiki.img",
                    "}",
                    "",
                    f'menuentry "KIKI OS CLI installer ({arch}, safe fallback)" {{',
                    "    set gfxpayload=text",
                    f"    linux /boot/vmlinuz-kiki console=tty0 {cli_args}",
                    "    initrd /boot/initramfs-kiki.img",
                    "}",
                    "",
                ]
                if installer
                else []
            ),
            f'menuentry "KIKI OS {title} ({arch}, UEFI framebuffer)" {{',
            "    set gfxpayload=keep",
            f"    linux /boot/vmlinuz-kiki console=tty0 {uefi_args}",
            "    initrd /boot/initramfs-kiki.img",
            "}",
            "",
            f'menuentry "KIKI OS {title} ({arch}, Hyper-V framebuffer)" {{',
            "    set gfxpayload=keep",
            f"    linux /boot/vmlinuz-kiki console=tty0 {hyperv_args}",
            "    initrd /boot/initramfs-kiki.img",
            "}",
            "",
            f'menuentry "KIKI OS {title} ({arch}, BIOS VGA text)" {{',
            "    set gfxpayload=text",
            f"    linux /boot/vmlinuz-kiki console=tty0 {bios_args}",
            "    initrd /boot/initramfs-kiki.img",
            "}",
            "",
            f'menuentry "KIKI OS {title} ({arch}, serial + VGA)" {{',
            "    set gfxpayload=keep",
            f"    linux /boot/vmlinuz-kiki console=tty0 console=ttyS0,115200n8 {cli_args}",
            "    initrd /boot/initramfs-kiki.img",
            "}",
            "",
            f'menuentry "KIKI OS {title} ({arch}, serial console)" {{',
            f"    linux /boot/vmlinuz-kiki console=ttyS0,115200n8 {bios_args}",
            "    initrd /boot/initramfs-kiki.img",
            "}",
            "",
            f'menuentry "KIKI OS {title} ({arch}, debug Hyper-V EFI)" {{',
            "    set gfxpayload=keep",
            f"    linux /boot/vmlinuz-kiki console=tty0 console=ttyS0,115200n8 earlyprintk=efi,keep earlycon=uart8250,io,0x3f8,115200n8 {debug_args}",
            "    initrd /boot/initramfs-kiki.img",
            "}",
            "",
        ]
    )


def prepare_boot_iso_tree(
    rootfs_dir: Path,
    repo_dir: Path,
    tree_dir: Path,
    *,
    kernel: Path,
    initramfs: Path,
    arch: str,
    profile: str,
    label: str,
    include_payload: bool = True,
    installer: bool = False,
    installed: bool = False,
    install_image: Path | None = None,
    packages_dir: Path | None = None,
    installed_initramfs: Path | None = None,
    efi_bootloader: Path | None = None,
    build_info: dict[str, Any] | None = None,
    release_name: str | None = None,
) -> dict[str, Any]:
    if not rootfs_dir.exists():
        raise BootIsoError(f"rootfs directory not found: {rootfs_dir}")
    if include_payload and not repo_dir.exists():
        raise BootIsoError(f"repository directory not found: {repo_dir}")
    if not kernel.exists():
        raise BootIsoError(f"kernel image not found: {kernel}")
    if not initramfs.exists():
        raise BootIsoError(f"initramfs not found: {initramfs}")

    if tree_dir.exists():
        shutil.rmtree(tree_dir)
    (tree_dir / "boot" / "grub").mkdir(parents=True)
    (tree_dir / "kiki").mkdir(parents=True)

    shutil.copy2(kernel, tree_dir / "boot" / "vmlinuz-kiki")
    shutil.copy2(initramfs, tree_dir / "boot" / "initramfs-kiki.img")
    installed_initramfs_meta: dict[str, Any] | None = None
    if installer and installed_initramfs:
        if not installed_initramfs.exists():
            raise BootIsoError(f"installed initramfs not found: {installed_initramfs}")
        shutil.copy2(installed_initramfs, tree_dir / "boot" / "initramfs-kiki-installed.img")
        installed_initramfs_meta = {
            "path": "boot/initramfs-kiki-installed.img",
            "size": installed_initramfs.stat().st_size,
            "sha256": sha256_file(installed_initramfs),
        }
    (tree_dir / "boot" / "grub" / "grub.cfg").write_text(
        grub_cfg(profile, arch, installer=installer, installed=installed),
        encoding="utf-8",
    )

    efi_bootloader_meta: dict[str, Any] | None = None
    if installer and efi_bootloader:
        if not efi_bootloader.exists():
            raise BootIsoError(f"UEFI bootloader not found: {efi_bootloader}")
        efi_target = tree_dir / "kiki" / "bootloader" / "EFI" / "BOOT" / "BOOTX64.EFI"
        efi_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(efi_bootloader, efi_target)
        efi_bootloader_meta = {
            "path": "kiki/bootloader/EFI/BOOT/BOOTX64.EFI",
            "size": efi_bootloader.stat().st_size,
            "sha256": sha256_file(efi_bootloader),
        }

    payload: dict[str, str] = {}
    package_media: dict[str, Any] = {
        "path": None,
        "copied": 0,
        "missing": [],
        "total_size": 0,
    }
    if include_payload:
        copytree_contents(repo_dir, tree_dir / "kiki" / "repo")
        package_media = copy_package_payloads(repo_dir, packages_dir, tree_dir / "kiki" / "packages" / arch, arch)
        write_rootfs_tar(rootfs_dir, tree_dir / "kiki" / "rootfs.tar.gz")
        payload = {"rootfs": "kiki/rootfs.tar.gz", "repo": "kiki/repo"}
        if package_media.get("copied", 0):
            payload["packages"] = f"kiki/packages/{arch}"

    install_image_meta: dict[str, Any] | None = None
    if installer and install_image:
        if not install_image.exists():
            raise BootIsoError(f"install image not found: {install_image}")
        install_dir = tree_dir / "install"
        install_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(install_image, install_dir / "kiki-stage1.img")
        install_image_meta = {
            "path": "install/kiki-stage1.img",
            "size": install_image.stat().st_size,
            "sha256": sha256_file(install_image),
        }

    boot_mode = "installer-stage1" if installer else "installed-systemd-handoff" if installed else "vm-smoke"
    manifest = {
        "schema": "ki2-bootiso-v1",
        "arch": arch,
        "profile": profile,
        "release": release_name or profile,
        "label": label,
        "created_at": dt.datetime.now(UTC).isoformat(),
        "build": build_info or {},
        "bootable": True,
        "bootloader": "grub-mkrescue",
        "firmware": {
            "bios": True,
            "uefi": True,
            "secure_boot": False,
            "secure_boot_note": "Disable Secure Boot for Hyper-V Generation 2 and other UEFI VMs; this development media is not signed.",
        },
        "kernel": "boot/vmlinuz-kiki",
        "initramfs": "boot/initramfs-kiki.img",
        "boot_mode": boot_mode,
        "installer": {
            "enabled": installer,
            "interface": "gui-tui-cli" if installer else None,
            "interface_order": ["gtk4", "fullscreen-tui", "cli"] if installer else [],
            "strategy": "guided-disk-partition-format-extract-selected-packages-uefi-boot" if installer else None,
            "confirmation": "INSTALL <target-disk>" if installer else None,
            "install_image": install_image_meta,
            "package_selection": installer,
            "installed_initramfs": installed_initramfs_meta,
            "uefi_fallback_bootloader": efi_bootloader_meta,
        },
        "payload": payload,
        "package_media": package_media,
        "notes": [
            (
                "This image tries GTK 4 first, then the full-screen TUI, and finally the stage-1 CLI fallback."
                if installer
                else "This image is an installed systemd handoff boot target."
                if installed
                else "This image is bootable in a VM and stops at a generated smoke-test /init."
            ),
            "The guided installer currently installs UEFI fallback boot files; BIOS disk GRUB installation is a later milestone.",
        ],
    }
    (tree_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (tree_dir / "README.txt").write_text(
        "\n".join(
            [
                "KIKI OS installer media" if installer else "KIKI OS installed systemd handoff media" if installed else "KIKI OS boot smoke media",
                "",
                f"Profile: {profile}",
                f"Architecture: {arch}",
                "",
                "Boot path:",
                "- Firmware: BIOS/MBR or UEFI without Secure Boot",
                "- GRUB loads /boot/vmlinuz-kiki",
                "- GRUB loads /boot/initramfs-kiki.img",
                "- Linux runs the generated /init program",
                "",
                (
                    "The GTK installer is the default boot choice and automatically falls back to the TUI; the shared installer can select packages, partition a disk, format ESP/root filesystems, extract selected packages, and install UEFI fallback boot files."
                    if installer
                    else "This is the installed systemd handoff boot target."
                    if installed
                    else "This proves boot media generation. Disk installation is a later milestone."
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def find_grub_mkrescue() -> str:
    for name in ("grub-mkrescue", "grub2-mkrescue"):
        found = shutil.which(name)
        if found:
            return found
    raise BootIsoError("GRUB rescue ISO builder not found; install grub2-tools-extra and xorriso")


def find_grub_mkstandalone() -> str | None:
    for name in ("grub-mkstandalone", "grub2-mkstandalone"):
        found = shutil.which(name)
        if found:
            return found
    return None


def find_grub_unicode_font() -> Path | None:
    candidates = [
        Path("/usr/share/grub/unicode.pf2"),
        Path("/usr/share/grub2/unicode.pf2"),
        Path("/boot/grub/fonts/unicode.pf2"),
        Path("/boot/grub2/fonts/unicode.pf2"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def find_qemu_img() -> str | None:
    return shutil.which("qemu-img")


def tool_supports_option(tool: str, option: str) -> bool:
    try:
        result = subprocess.run(
            [tool, "--help"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError:
        return False
    return option in result.stdout


def build_boot_iso(tree_dir: Path, output: Path) -> None:
    tool = find_grub_mkrescue()
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(output.suffix + ".tmp")
    if tmp_output.exists():
        tmp_output.unlink()
    cmd = [tool]
    if tool_supports_option(tool, "--disable-shim-lock"):
        cmd.append("--disable-shim-lock")
    cmd.extend(["-o", str(tmp_output), str(tree_dir)])
    subprocess.run(cmd, check=True)
    tmp_output.replace(output)


def build_uefi_fallback_bootloader(output: Path, work_dir: Path) -> bool:
    tool = find_grub_mkstandalone()
    if not tool:
        return False
    cfg = work_dir / "uefi-fallback-grub.cfg"
    cfg.write_text(
        "\n".join(
            [
                "insmod part_gpt",
                "insmod part_msdos",
                "insmod fat",
                "insmod ext2",
                "insmod search_fs_file",
                "insmod configfile",
                "insmod all_video",
                "insmod font",
                "insmod gfxterm",
                "serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1",
                "if loadfont /boot/grub/fonts/unicode.pf2; then",
                "    terminal_output gfxterm console serial",
                "else",
                "    terminal_output console serial",
                "fi",
                "terminal_input console serial",
                "set gfxmode=1024x768,800x600,auto",
                "set gfxpayload=keep",
                "set timeout=3",
                "search --file --set=root /boot/grub/kiki-installed.cfg",
                "if [ -e /boot/grub/kiki-installed.cfg ]; then",
                "    configfile /boot/grub/kiki-installed.cfg",
                "fi",
                "echo 'KIKI installed boot config was not found.'",
                "echo 'Check that the EFI system partition contains /boot/grub/kiki-installed.cfg.'",
                "sleep --interruptible 10",
                "",
            ]
        ),
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        tool,
        "-O",
        "x86_64-efi",
        "--modules=part_gpt part_msdos fat ext2 normal configfile search search_fs_file linux all_video efi_gop efi_uga gfxterm font serial terminal",
        "-o",
        str(output),
        f"boot/grub/grub.cfg={cfg}",
    ]
    font = find_grub_unicode_font()
    if font:
        cmd.append(f"boot/grub/fonts/unicode.pf2={font}")
    subprocess.run(cmd, check=True)
    return True


def build_hyperv_vhdx(source_image: Path, output: Path, *, required: bool = False) -> bool:
    tool = find_qemu_img()
    if not tool:
        if required:
            raise BootIsoError("qemu-img not found; install qemu-img to create Hyper-V VHDX media")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(output.suffix + ".tmp")
    if tmp_output.exists():
        tmp_output.unlink()
    try:
        subprocess.run(
            [
                tool,
                "convert",
                "-f",
                "raw",
                "-O",
                "vhdx",
                "-o",
                "subformat=dynamic",
                str(source_image),
                str(tmp_output),
            ],
            check=True,
        )
        tmp_output.replace(output)
    except OSError as exc:
        if required:
            raise BootIsoError(f"Hyper-V VHDX media could not be written: {exc}") from exc
        if tmp_output.exists():
            tmp_output.unlink()
        return False
    return True


def default_hyperv_vhdx_output(repo_root: Path, profile: str, arch: str) -> Path:
    return repo_root / "dist" / "iso" / f"kiki-{profile_release_name(profile)}-installed-hyperv-{arch}.vhdx"


def command_build(args: argparse.Namespace) -> None:
    repo_root = args.repo_root.resolve()
    rootfs_dir = (args.rootfs_dir or repo_root / "dist" / "rootfs" / args.profile).resolve()
    repo_dir = (args.repo_dir or repo_root / "dist" / "ki2" / "repo").resolve()
    packages_dir = (args.packages_dir or repo_root / "dist" / "ki2" / "packages" / args.arch).resolve()
    suffix = "installer" if args.mode == "installer" else "installed" if args.mode == "installed" else "boot"
    build_info = iso_build_info(repo_root)
    release_name = iso_release_name(repo_dir, args.arch, args.profile, args.release_name)
    output = (args.output or default_iso_output(repo_root, release_name, suffix, args.arch, build_info)).resolve()
    label = args.label or f"KIKI_{args.profile}_{suffix}_{args.arch}".replace("-", "_").upper()
    installer = args.mode == "installer"
    installed = args.mode == "installed"
    hyperv_vhdx = args.hyperv_vhdx.resolve() if args.hyperv_vhdx else default_hyperv_vhdx_output(repo_root, args.profile, args.arch).resolve()
    wrote_hyperv_vhdx = False
    installed_initramfs: Path | None = None
    efi_bootloader: Path | None = None

    with tempfile.TemporaryDirectory(prefix="ki2bootiso-") as tmp:
        work_dir = Path(tmp)
        kernel = find_kernel(rootfs_dir, packages_dir, work_dir / "kernel", requested=args.kernel)
        install_image = args.install_image.resolve() if args.install_image else None
        if installer:
            installed_initramfs = work_dir / "installed-initramfs-kiki.img"
            build_initramfs(
                installed_initramfs,
                work_dir / "installed-initramfs",
                arch=args.arch,
                profile=args.profile,
                cc=args.cc,
                installed=True,
            )
            efi_bootloader = work_dir / "BOOTX64.EFI"
            if not build_uefi_fallback_bootloader(efi_bootloader, work_dir):
                efi_bootloader = None
                print("ki2bootiso: grub-mkstandalone not found; guided UEFI bootloader payload skipped", file=sys.stderr)
        if installer and install_image is None and not args.no_install_image:
            installed_tree = work_dir / "installed-iso-tree"
            install_image = work_dir / f"kiki-{args.profile}-installed-{args.arch}.img"
            prepare_boot_iso_tree(
                rootfs_dir,
                repo_dir,
                installed_tree,
                kernel=kernel,
                initramfs=installed_initramfs,
                arch=args.arch,
                profile=args.profile,
                label=f"KIKI_{args.profile}_INSTALLED_{args.arch}".replace("-", "_").upper(),
                include_payload=not args.no_payload,
                installed=True,
                packages_dir=packages_dir,
                build_info=build_info,
                release_name=release_name,
            )
            if not args.dry_run:
                build_boot_iso(installed_tree, install_image)
                if not args.no_hyperv_vhdx:
                    wrote_hyperv_vhdx = build_hyperv_vhdx(
                        install_image,
                        hyperv_vhdx,
                        required=args.hyperv_vhdx is not None,
                    )
                    if not wrote_hyperv_vhdx:
                        print("ki2bootiso: qemu-img not found; skipped Hyper-V VHDX media", file=sys.stderr)

        external_install_image = (
            install_image
            if installer and not args.no_install_image and install_image is not None and install_image.exists()
            else None
        )
        if installer and external_install_image and not wrote_hyperv_vhdx and not args.no_hyperv_vhdx and not args.dry_run:
            wrote_hyperv_vhdx = build_hyperv_vhdx(
                external_install_image,
                hyperv_vhdx,
                required=args.hyperv_vhdx is not None,
            )
            if not wrote_hyperv_vhdx:
                print("ki2bootiso: qemu-img not found; skipped Hyper-V VHDX media", file=sys.stderr)
        embed_install_image = external_install_image if args.embed_install_image else None
        initramfs = args.initramfs or work_dir / "initramfs-kiki.img"
        if args.initramfs is None:
            build_initramfs(
                initramfs,
                work_dir / "outer-initramfs",
                arch=args.arch,
                profile=args.profile,
                cc=args.cc,
                installer=installer,
                installed=installed,
                install_image=embed_install_image,
                packages_dir=packages_dir if installer else None,
            )

        tree_dir = args.keep_tree or work_dir / "iso-tree"
        manifest = prepare_boot_iso_tree(
            rootfs_dir,
            repo_dir,
            tree_dir,
            kernel=kernel,
            initramfs=initramfs,
            arch=args.arch,
            profile=args.profile,
            label=label,
            include_payload=not args.no_payload,
            installer=installer,
            installed=installed,
            install_image=external_install_image,
            packages_dir=packages_dir,
            installed_initramfs=installed_initramfs,
            efi_bootloader=efi_bootloader,
            build_info=build_info,
            release_name=release_name,
        )
        if args.dry_run:
            print(f"would build bootable ISO: {output}")
            if installer and not args.no_install_image and not args.no_hyperv_vhdx:
                print(f"would build Hyper-V VHDX: {hyperv_vhdx}")
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return
        build_boot_iso(tree_dir, output)

    print(f"ki2bootiso: wrote {output}")
    if wrote_hyperv_vhdx:
        print(f"ki2bootiso: wrote {hyperv_vhdx}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a bootable KIKI VM smoke ISO")
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--profile", default="bootstrap-stage1")
    parser.add_argument("--release-name", default=None, help="release/channel name for default ISO filenames; defaults to repository metadata channel")
    parser.add_argument("--rootfs-dir", type=Path, default=None)
    parser.add_argument("--repo-dir", type=Path, default=None)
    parser.add_argument("--packages-dir", type=Path, default=None)
    parser.add_argument("--kernel", type=Path, default=None)
    parser.add_argument("--initramfs", type=Path, default=None)
    parser.add_argument("--install-image", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--label", default=None)
    parser.add_argument("--keep-tree", type=Path, default=None)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--mode", choices=("smoke", "installer", "installed"), default="smoke")
    parser.add_argument("--no-payload", action="store_true")
    parser.add_argument("--no-install-image", action="store_true")
    parser.add_argument("--embed-install-image", action="store_true")
    parser.add_argument("--hyperv-vhdx", type=Path, default=None)
    parser.add_argument("--no-hyperv-vhdx", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(func=command_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (BootIsoError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
