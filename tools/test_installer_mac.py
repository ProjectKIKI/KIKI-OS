import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import ki2bootiso


class InstallerMACTests(unittest.TestCase):
    def test_actual_c_mac_selector_and_pattern_fallback(self):
        if not shutil.which('cc'):
            self.skipTest('C compiler required')
        source = ki2bootiso.INIT_C
        start = source.index('static int selected_network_mac(')
        end = source.index('static int write_target_network_config(', start)
        harness = r'''
#include <stdio.h>
#include <string.h>
#define kstrlen strlen
#define kstrcmp strcmp
static const char *test_mac = "52:54:00:12:34:56";
static char seen[256];
static void path3(char *dst, size_t n, const char *a, const char *b, const char *c) {
    snprintf(dst, n, "%s%s%s", a, b, c);
}
static void copy_string(char *dst, size_t n, const char *s) { snprintf(dst, n, "%s", s); }
static int read_text_file(const char *path, char *out, size_t n) {
    snprintf(seen, sizeof(seen), "%s", path);
    snprintf(out, n, "%s", test_mac);
    return 1;
}
''' + source[start:end] + r'''
int main(void) {
    char mac[18];
    if (!selected_network_mac("/fixture", "eth0", mac, sizeof(mac))) return 1;
    if (strcmp(mac, test_mac) || strcmp(seen, "/fixture/eth0/address")) return 2;
    const char *invalid[] = {"", "en* eth*", "eth*", "../eth0", ".", "..", "abcdefghijklmnop"};
    for (size_t i=0; i<sizeof(invalid)/sizeof(invalid[0]); i++)
        if (selected_network_mac("/fixture", invalid[i], mac, sizeof(mac))) return 3;
    const char *bad[] = {"00:00:00:00:00:00", "garbage", "52:54:00:12:34:zz"};
    for (size_t i=0; i<sizeof(bad)/sizeof(bad[0]); i++) {
        test_mac=bad[i];
        if (selected_network_mac("/fixture", "eth0", mac, sizeof(mac))) return 4;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='kiki-mac-test-') as tmp:
            src, binary = Path(tmp)/'test.c', Path(tmp)/'test'
            src.write_text(harness)
            subprocess.run(['cc','-Wall','-Wextra','-Werror',str(src),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
        self.assertIn('"MACAddress="', source[end:])
        self.assertIn('network->match_name : "en* eth*"', source[end:])
