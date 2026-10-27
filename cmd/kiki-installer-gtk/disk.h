#ifndef KIKI_INSTALLER_DISK_H
#define KIKI_INSTALLER_DISK_H
#include <glib.h>

typedef struct { char *path, *label; } KikiDisk;
static void kiki_disk_free(gpointer value) {
    KikiDisk *disk = value;
    g_free(disk->path); g_free(disk->label); g_free(disk);
}
static char *kiki_disk_read(const char *root, const char *name, const char *file) {
    g_autofree char *path = g_build_filename(root, name, file, NULL);
    char *text = NULL;
    if (!g_file_get_contents(path, &text, NULL, NULL)) return g_strdup("");
    return g_strstrip(text);
}
static gint kiki_disk_compare(gconstpointer a, gconstpointer b) {
    return g_strcmp0((*(KikiDisk *const *)a)->path, (*(KikiDisk *const *)b)->path);
}
static GPtrArray *kiki_install_disks(const char *root) {
    GPtrArray *disks = g_ptr_array_new_with_free_func(kiki_disk_free);
    g_autoptr(GDir) dir = g_dir_open(root, 0, NULL);
    if (!dir) return disks;
    const char *name;
    while ((name = g_dir_read_name(dir))) {
        if (!g_regex_match_simple("^((sd|vd|xvd|hd)[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$", name, 0, 0)) continue;
        g_autofree char *partition = g_build_filename(root, name, "partition", NULL);
        if (g_file_test(partition, G_FILE_TEST_EXISTS)) continue;
        g_autofree char *readonly = kiki_disk_read(root, name, "ro");
        g_autofree char *size = kiki_disk_read(root, name, "size");
        guint64 sectors = 0;
        if (!g_str_equal(readonly, "0") ||
            !g_ascii_string_to_unsigned(size, 10, 1, G_MAXUINT64 / 512, &sectors, NULL)) continue;
        g_autofree char *model = kiki_disk_read(root, name, "device/model");
        g_autofree char *capacity = g_format_size(sectors * 512);
        KikiDisk *disk = g_new0(KikiDisk, 1);
        disk->path = g_strdup_printf("/dev/%s", name);
        disk->label = g_strdup_printf("%s · %s%s%s", disk->path, capacity, *model ? " · " : "", model);
        g_ptr_array_add(disks, disk);
    }
    g_ptr_array_sort(disks, kiki_disk_compare);
    return disks;
}
#endif
