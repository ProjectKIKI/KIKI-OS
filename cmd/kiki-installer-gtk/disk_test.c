#include "disk.h"
#include <glib/gstdio.h>

static void fixture(const char *root, const char *name, const char *ro, const char *size) {
    g_autofree char *directory = g_build_filename(root, name, "device", NULL);
    g_mkdir_with_parents(directory, 0700);
    const char *files[] = {"ro", "size", "device/model"};
    const char *values[] = {ro, size, "Fixture Disk"};
    for (guint i = 0; i < G_N_ELEMENTS(files); i++) {
        g_autofree char *path = g_build_filename(root, name, files[i], NULL);
        g_assert_true(g_file_set_contents(path, values[i], -1, NULL));
    }
}
int main(int argc, char **argv) {
    g_assert_cmpint(argc, ==, 2);
    fixture(argv[1], "vda", "0", "33554432");
    fixture(argv[1], "nvme0n1", "0", "67108864");
    fixture(argv[1], "sda1", "0", "100");
    fixture(argv[1], "loop0", "0", "100");
    fixture(argv[1], "sr0", "0", "100");
    fixture(argv[1], "sdb", "1", "100");
    fixture(argv[1], "sdc", "0", "0");
    fixture(argv[1], "sdd", "0", "not-a-size");
    fixture(argv[1], "sde", "0", "18446744073709551615");
    g_autoptr(GPtrArray) disks = kiki_install_disks(argv[1]);
    g_assert_cmpuint(disks->len, ==, 2);
    g_assert_cmpstr(((KikiDisk *)g_ptr_array_index(disks, 0))->path, ==, "/dev/nvme0n1");
    g_assert_nonnull(strstr(((KikiDisk *)g_ptr_array_index(disks, 1))->label, "Fixture Disk"));
    g_print("PASS: whole writable disks only; partitions, optical, loop, empty and invalid sizes rejected\n");
    return 0;
}
