#ifndef KIKI_INSTALLER_NETWORK_H
#define KIKI_INSTALLER_NETWORK_H
#include <glib.h>
#include <stdio.h>
#include <string.h>
#include <ifaddrs.h>
#include <arpa/inet.h>

typedef struct { char *name, *label; gboolean carrier; } KikiNic;
static void kiki_nic_free(gpointer value) {
    KikiNic *nic = value;
    g_free(nic->name); g_free(nic->label); g_free(nic);
}
static char *kiki_net_read(const char *root, const char *name, const char *file) {
    g_autofree char *path = g_build_filename(root, name, file, NULL);
    char *text = NULL;
    if (!g_file_get_contents(path, &text, NULL, NULL)) return g_strdup("");
    return g_strstrip(text);
}
static gint kiki_nic_compare(gconstpointer a, gconstpointer b) {
    return g_strcmp0((*(KikiNic *const *)a)->name, (*(KikiNic *const *)b)->name);
}
static GPtrArray *kiki_network_devices(const char *root) {
    GPtrArray *devices = g_ptr_array_new_with_free_func(kiki_nic_free);
    g_autoptr(GDir) dir = g_dir_open(root, 0, NULL);
    if (!dir) return devices;
    const char *name;
    while ((name = g_dir_read_name(dir))) {
        g_autofree char *device = g_build_filename(root, name, "device", NULL);
        g_autofree char *wireless = g_build_filename(root, name, "wireless", NULL);
        g_autofree char *type = kiki_net_read(root, name, "type");
        /* Include physical and hypervisor NICs, not loopback, bridges or tunnels.
         * Wi-Fi needs authentication support; it remains an advanced/manual option. */
        if (!g_str_equal(type, "1") || !g_file_test(device, G_FILE_TEST_EXISTS) ||
            g_file_test(wireless, G_FILE_TEST_EXISTS)) continue;
        g_autofree char *mac = kiki_net_read(root, name, "address");
        g_autofree char *carrier = kiki_net_read(root, name, "carrier");
        g_autofree char *driver_path = g_build_filename(device, "driver", NULL);
        g_autofree char *driver_link = g_file_read_link(driver_path, NULL);
        g_autofree char *driver = driver_link ? g_path_get_basename(driver_link) : g_strdup("Ethernet");
        KikiNic *nic = g_new0(KikiNic, 1);
        nic->name = g_strdup(name);
        nic->carrier = g_str_equal(carrier, "1");
        nic->label = g_strdup_printf("%s — %s · %s · %s", name,
            g_str_equal(driver, "hv_netvsc") ? "Hyper-V" : driver,
            nic->carrier ? "연결됨" : "연결 없음", mac);
        g_ptr_array_add(devices, nic);
    }
    g_ptr_array_sort(devices, kiki_nic_compare);
    return devices;
}
static char *kiki_network_status(const char *name) {
    /* Read only: do not apply unconfirmed settings or disrupt installation media. */
    if (!name || !*name || strpbrk(name, "*?[] /\t\n"))
        return g_strdup("현재 연결 확인은 eth0 같은 실제 장치 이름을 지정해야 합니다.");
    struct ifaddrs *addresses = NULL;
    GString *text = g_string_new("현재 설치 환경의 연결 상태 (입력한 설정을 적용하지 않음)\n");
    g_autofree char *carrier = kiki_net_read("/sys/class/net", name, "carrier");
    g_string_append_printf(text, "%s: 링크 %s\n", name, g_str_equal(carrier, "1") ? "연결됨" : "연결 없음");
    gboolean ipv4 = FALSE;
    if (getifaddrs(&addresses) == 0) {
        for (struct ifaddrs *item = addresses; item; item = item->ifa_next) {
            if (!item->ifa_addr || strcmp(item->ifa_name, name) || item->ifa_addr->sa_family != AF_INET) continue;
            char ip[INET_ADDRSTRLEN];
            struct sockaddr_in *addr = (struct sockaddr_in *)item->ifa_addr;
            if (inet_ntop(AF_INET, &addr->sin_addr, ip, sizeof(ip))) {
                g_string_append_printf(text, "IPv4: %s\n", ip); ipv4 = TRUE;
            }
        }
        freeifaddrs(addresses);
    }
    if (!ipv4) g_string_append(text, "IPv4 주소 없음\n");
    g_autofree char *routes = NULL;
    gboolean gateway = FALSE;
    if (g_file_get_contents("/proc/net/route", &routes, NULL, NULL)) {
        g_auto(GStrv) lines = g_strsplit(routes, "\n", -1);
        for (guint i = 1; lines[i]; i++) {
            char iface[64]; unsigned long dest, gw, flags;
            if (sscanf(lines[i], "%63s %lx %lx %lx", iface, &dest, &gw, &flags) == 4 &&
                strcmp(iface, name) == 0 && dest == 0 && (flags & 3) == 3) gateway = TRUE;
        }
    }
    g_string_append(text, gateway ? "IPv4 기본 경로 있음\n" : "IPv4 기본 경로 없음\n");
    g_string_append(text, "DNS 및 외부 통신 성공 여부는 별도 확인이 필요합니다.");
    return g_string_free(text, FALSE);
}
#endif
