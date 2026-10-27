"""Root-only disposable chroot test; no host accounts, mounts or devices changed."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import time
import unittest
import ki2build

PROBE = r'''
#include <security/pam_appl.h>
#include <crypt.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const char *password = "KikiSyntheticTest!42";
static int converse(int n, const struct pam_message **msg,
                    struct pam_response **reply, void *data) {
  (void)data;
  struct pam_response *r = calloc(n, sizeof(*r));
  if (!r) return PAM_BUF_ERR;
  for (int i=0; i<n; ++i) {
    if (msg[i]->msg_style == PAM_PROMPT_ECHO_OFF) r[i].resp = strdup(password);
    else if (msg[i]->msg_style != PAM_TEXT_INFO && msg[i]->msg_style != PAM_ERROR_MSG) {
      for (int j=0; j<i; ++j) free(r[j].resp);
      free(r); return PAM_CONV_ERR;
    }
  }
  *reply=r; return PAM_SUCCESS;
}
int main(int argc, char **argv) {
  if (argc != 2) return 1;
  if (!strcmp(argv[1], "hash")) {
    char *hash=crypt(password, "$6$kiki-fixture$");
    if (!hash || hash[0]=='*') return 2;
    puts(hash); return 0;
  }
  void *module=dlopen("/usr/lib/security/pam_unix.so", RTLD_NOW);
  if (!module) { fprintf(stderr,"pam_unix load: %s\n",dlerror()); return 5; }
  dlclose(module);
  const char *user=!strcmp(argv[1], "unknown") ? "absent-fixture" : "fixture";
  if (!strcmp(argv[1], "wrong")) password="WrongSyntheticPassword";
  if (!strcmp(argv[1], "empty")) password="";
  struct pam_conv conv={converse, NULL}; pam_handle_t *p=NULL;
  if (pam_start("kiki-fixture", user, &conv, &p) != PAM_SUCCESS) return 3;
  int auth=pam_authenticate(p, 0);
  int account=auth == PAM_SUCCESS ? pam_acct_mgmt(p, 0) : -1;
  int ok;
  if (!strcmp(argv[1], "valid")) ok=auth==PAM_SUCCESS && account==PAM_SUCCESS;
  else if (!strcmp(argv[1], "expired")) ok=auth==PAM_SUCCESS && account==PAM_ACCT_EXPIRED;
  else ok=auth!=PAM_SUCCESS;
  fprintf(stdout,"auth=%d account=%d\n",auth,account);
  pam_end(p, auth);
  return ok ? 0 : 4;
}
'''

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_PAM_UNIX") == "1",
                     "set KIKI_TEST_PAM_UNIX=1 as Linux root")
class PamUnixRuntimeTests(unittest.TestCase):
    def test_password_lock_and_expiration(self):
        self.check_policy(packaged_polkit=False)

    def test_packaged_polkit_password_policy(self):
        self.check_policy(packaged_polkit=True)

    def check_policy(self, *, packaged_polkit):
        self.assertEqual(os.geteuid(), 0)
        repo=Path(__file__).resolve().parents[1]
        recipes=ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-pam-unix-") as tmp:
            root=Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["linux-pam", "linux-headers"], "x86_64", include_build_deps=False):
                path=repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(path.is_file(), str(path))
                ki2build.extract_package_rootfs(path, root)
            def run(command):
                result=subprocess.run(command, env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},
                                      capture_output=True,text=True,timeout=40)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                return result.stdout.strip()
            (root / "tmp").mkdir(exist_ok=True)
            probe = PROBE.replace('"kiki-fixture"', '"polkit-1"') if packaged_polkit else PROBE
            source=root / "tmp/probe.c"; source.write_text(probe)
            flags=["cc", "--sysroot="+str(root)]
            for rel in ("usr/lib","usr/lib64","lib","lib64"):
                path=root / rel
                flags += ["-B"+str(path)+"/","-L"+str(path),"-Wl,-rpath-link,"+str(path)]
            run(flags+[str(source),"-lpam","-lcrypt","-o",str(root / "tmp/probe")])
            loaders=[p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders),1)
            loader="/"+str(loaders[0].relative_to(root))
            command=["chroot",str(root),loader,"--inhibit-cache","--library-path","/usr/lib:/usr/lib64:/lib:/lib64","/tmp/probe"]
            # pam_unix execs unix_chkpwd with an empty environment. The outer
            # loader's --library-path is not inherited by that fresh process.
            run(["chroot", str(root), "/sbin/ldconfig", "/usr/lib", "/usr/lib64", "/lib", "/lib64"])
            encoded=run(command+["hash"])
            self.assertTrue(encoded.startswith("$6$"))
            etc=root / "etc"; etc.mkdir(exist_ok=True)
            (etc / "pam.d").mkdir(exist_ok=True)
            if packaged_polkit:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes["polkit"], "x86_64")
                with tarfile.open(package, "r:gz") as archive:
                    policy = archive.extractfile("rootfs/etc/pam.d/polkit-1").read()
                self.assertEqual(policy, (repo / "distro/sources/polkit/etc/pam.d/polkit-1").read_bytes())
                (etc / "pam.d/polkit-1").write_bytes(policy)
            else:
                (etc / "pam.d/kiki-fixture").write_text("auth required /usr/lib/security/pam_unix.so nodelay\naccount required /usr/lib/security/pam_unix.so\n")
            (etc / "nsswitch.conf").write_text("passwd: files\ngroup: files\nshadow: files\n")
            (etc / "passwd").write_text("root:x:0:0:root:/root:/bin/sh\nfixture:x:1000:1000:fixture:/nonexistent:/bin/sh\n")
            (etc / "group").write_text("root:x:0:\nfixture:x:1000:\n")
            day=int(time.time() // 86400)
            passed = []
            cases = ("valid", "wrong", "locked", "unknown", "expired", "empty")
            for case in cases:
                with self.subTest(case=case):
                    digest="!"+encoded if case=="locked" else encoded
                    if case == "empty":
                        digest = ""
                    expiry=str(day-1) if case=="expired" else ""
                    shadow=etc / "shadow"
                    shadow.write_text(f"root:!:0:0:99999:7:::\nfixture:{digest}:{day}:0:99999:7::{expiry}:\n")
                    shadow.chmod(0o600)
                    run(command+[case])
                    passed.append(case)
            self.assertEqual(len(passed), len(cases), "not all authentication cases passed")
            if packaged_polkit:
                print("Polkit packaged PAM: 6 account/password cases passed in disposable chroot; not helper/session validation")
                return
            # Install this synthetic policy only inside the disposable chroot.
            # Start with a non-expired, unlocked account after the cases above.
            shadow.write_text(f"root:!:0:0:99999:7:::\nfixture:{encoded}:{day}:0:99999:7:::\n")
            records = root / "run/faillock"
            records.mkdir(parents=True, exist_ok=True)
            security = etc / "security"
            security.mkdir(exist_ok=True)
            (security / "faillock.conf").write_text(
                "dir = /run/faillock\ndeny = 3\nfail_interval = 900\nunlock_time = 0\nsilent\n")
            (etc / "pam.d/kiki-fixture").write_text(
                "auth requisite /usr/lib/security/pam_faillock.so preauth\n"
                "auth [success=1 default=bad] /usr/lib/security/pam_unix.so nodelay\n"
                "auth [default=die] /usr/lib/security/pam_faillock.so authfail\n"
                "auth sufficient /usr/lib/security/pam_faillock.so authsucc\n"
                "auth required /usr/lib/security/pam_deny.so\n"
                "account required /usr/lib/security/pam_unix.so\n")
            run(command + ["valid"])
            # A successful authentication must clear previous failures.
            for _ in range(2):
                run(command + ["wrong"])
                run(command + ["wrong"])
                run(command + ["valid"])
            for _ in range(3):
                run(command + ["wrong"])
            self.assertTrue((records / "fixture").is_file())
            # 'blocked' supplies the correct password but expects refusal.
            run(command + ["blocked"])
            run(command[:-1] + ["/usr/sbin/faillock", "--user", "fixture", "--reset"])
            run(command + ["valid"])
            print("KIKI PAM: 6 account cases and failure-counter reset/3-failure lock/admin reset passed; not a login/session test")

if __name__ == "__main__":
    unittest.main()
