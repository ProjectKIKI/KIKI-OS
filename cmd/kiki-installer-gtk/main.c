#include <gtk/gtk.h>
#include <glib/gstdio.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>
#include <stdio.h>
#include "network.h"
#include "disk.h"
#include "catalog.generated.h"

#ifndef GUI_INSTALL_REQUEST_PATH
#define GUI_INSTALL_REQUEST_PATH "/run/kiki/gui-install.request"
#endif
#ifndef GUI_INSTALL_REQUEST_TMP_PATH
#define GUI_INSTALL_REQUEST_TMP_PATH "/run/kiki/gui-install.request.tmp"
#endif
#ifndef GUI_INSTALL_PROGRESS_PATH
#define GUI_INSTALL_PROGRESS_PATH "/run/kiki/install-progress.state"
#endif
#ifndef GUI_INSTALL_BACKEND_LOG_PATH
#define GUI_INSTALL_BACKEND_LOG_PATH "/run/kiki/gui-install-backend.log"
#endif
#ifndef GUI_REBOOT_REQUEST_PATH
#define GUI_REBOOT_REQUEST_PATH "/run/kiki/gui-reboot.request"
#endif
#ifndef GUI_REBOOT_REQUEST_TMP_PATH
#define GUI_REBOOT_REQUEST_TMP_PATH "/run/kiki/gui-reboot.request.tmp"
#endif

static gboolean ui_korean = FALSE;
#define L(ko, en) (ui_korean ? (ko) : (en))

typedef struct {
    GtkWindow *window;
    GtkEntry *plan_path;
    GtkEntry *disk;
    GtkDropDown *disk_device;
    GPtrArray *disks;
    GtkEntry *hostname;
    GtkEntry *admin_user;
    GtkEntry *admin_password;
    GtkEntry *admin_password_confirm;
    GtkCheckButton *destructive_confirm;
    GtkEntry *locale;
    GtkEntry *keymap;
    GtkEntry *timezone;
    GtkEntry *network_interface;
    GtkDropDown *network_device;
    GtkDropDown *dns_mode;
    GPtrArray *network_devices;
    GtkLabel *network_status;
    gboolean refreshing_network;
    GtkEntry *address;
    GtkEntry *gateway;
    GtkEntry *dns;
    GtkEntry *source_location;
    GtkEntry *verify_key;
    GtkEntry *ai_endpoint;
    GtkEntry *package_groups;
    GtkCheckButton *extra_groups[16];
    GtkLabel *profile_status;
    GKeyFile *media_catalog;
    GtkDropDown *install_mode;
    GtkDropDown *swap_mode;
    GtkDropDown *network_mode;
    GtkDropDown *source_type;
    GtkDropDown *profile;
    GtkDropDown *runtime;
    GtkDropDown *ai_mode;
    GtkTextBuffer *review;
    GtkLabel *status;
    GtkStack *stack;
    GtkWidget *sidebar;
    GtkWidget *navigation;
    GtkWidget *footer;
    GtkButton *install_button;
    GtkButton *back_button;
    GtkButton *next_button;
    GtkLabel *step_label;
    GtkProgressBar *progress;
    GtkLabel *progress_phase;
    GtkLabel *package_count;
    GtkLabel *progress_message;
    GtkTextBuffer *progress_log;
    GtkButton *reboot_button;
    char *last_progress_message;
    char progress_fingerprint[65];
    gint64 progress_changed_at;
    guint progress_source;
    gboolean install_started;
    gboolean install_complete;
    gboolean install_failed;
} InstallerUI;

static void installer_ui_free(gpointer data) {
    InstallerUI *ui = data;
    if (ui->progress_source) g_source_remove(ui->progress_source);
    g_free(ui->last_progress_message);
    g_clear_pointer(&ui->network_devices, g_ptr_array_unref);
    g_clear_pointer(&ui->disks, g_ptr_array_unref);
    g_clear_pointer(&ui->media_catalog, g_key_file_unref);
    g_free(ui);
}

static const char *install_modes[] = {"guided", "unattended", NULL};
static const char *swap_modes[] = {"auto", "on", "off", NULL};
static const char *network_modes[] = {"dhcp", "static", "off", NULL};
static const char *network_mode_labels_ko[] = {"자동 (DHCP)", "고정 IP", "사용 안 함 (오프라인)", NULL};
static const char *network_mode_labels_en[] = {"Automatic (DHCP)", "Static IP", "Offline", NULL};
static const char *source_types[] = {"local", "remote", "mirror", NULL};
static const char *runtimes[] = {"profile-default", "none", "crio", "containerd", NULL};
static const char *ai_modes[] = {"local", "remote", "off", NULL};

static void desktop_profile_selected(GObject *object, GParamSpec *spec, gpointer data);

static const char *dropdown_text(GtkDropDown *dropdown) {
    GtkStringObject *item = GTK_STRING_OBJECT(gtk_drop_down_get_selected_item(dropdown));
    return item ? gtk_string_object_get_string(item) : "";
}

static const char *selected_profile(InstallerUI *ui) {
    guint index = gtk_drop_down_get_selected(ui->profile);
    return index < G_N_ELEMENTS(profiles) - 1 ? profiles[index] : "";
}

static gboolean media_available(InstallerUI *ui, const char *kind, const char *id) {
    if (!ui->media_catalog) return TRUE; /* Standalone plan editing has no medium. */
    g_autofree char *section = g_strdup_printf("%s %s", kind, id);
    return g_key_file_get_boolean(ui->media_catalog, section, "available", NULL);
}

static void update_profile_status(InstallerUI *ui) {
    if (!ui->profile_status) return;
    const char *id = selected_profile(ui);
    gboolean available = media_available(ui, "profile", id);
    g_autofree char *section = g_strdup_printf("profile %s", id);
    g_autofree char *message = NULL;
    if (!ui->media_catalog) {
        message = g_strdup(L("설치 미디어를 연결하면 패키지 포함 여부를 확인합니다.", "Connect installation media to check package availability."));
    } else if (available) {
        guint64 count = g_key_file_get_uint64(ui->media_catalog, section, "packages", NULL);
        guint64 bytes = g_key_file_get_uint64(ui->media_catalog, section, "download_bytes", NULL);
        g_autofree char *size = g_format_size(bytes);
        message = g_strdup_printf(L("이 미디어에서 설치 가능 · 패키지 %lu개 · 압축 크기 %s", "Available on this media · %lu packages · %s compressed"), (unsigned long)count, size);
    } else {
        g_autofree char *reason = g_key_file_get_string(ui->media_catalog, section, "reason", NULL);
        message = g_strdup_printf(L("이 미디어에 필요한 패키지가 없습니다. %s", "Required packages are missing from this media. %s"), reason ? reason : id);
    }
    gtk_label_set_text(ui->profile_status, message);
    if (available) gtk_widget_remove_css_class(GTK_WIDGET(ui->profile_status), "error");
    else gtk_widget_add_css_class(GTK_WIDGET(ui->profile_status), "error");
}

static void extra_groups_changed(GtkCheckButton *button, gpointer data) {
    (void)button;
    InstallerUI *ui = data;
    g_autoptr(GString) selected = g_string_new(NULL);
    for (guint i = 0; extra_group_ids[i]; i++) {
        if (!ui->extra_groups[i] || !gtk_check_button_get_active(ui->extra_groups[i])) continue;
        if (selected->len) g_string_append_c(selected, ',');
        g_string_append(selected, extra_group_ids[i]);
        if (g_str_equal(extra_group_ids[i], "desktop-gnome")) {
            gtk_drop_down_set_selected(ui->ai_mode, 2);
            gtk_drop_down_set_selected(ui->runtime, 1);
        }
    }
    gtk_editable_set_text(GTK_EDITABLE(ui->package_groups), selected->str);
}

static void profile_option_setup(GtkSignalListItemFactory *factory, GtkListItem *item, gpointer data) {
    (void)factory; (void)data;
    GtkWidget *label = gtk_label_new(NULL);
    gtk_label_set_xalign(GTK_LABEL(label), 0);
    gtk_list_item_set_child(item, label);
}

static void profile_option_bind(GtkSignalListItemFactory *factory, GtkListItem *item, gpointer data) {
    (void)factory;
    InstallerUI *ui = data;
    guint i = gtk_list_item_get_position(item);
    if (i >= G_N_ELEMENTS(profiles) - 1) return;
    gboolean available = media_available(ui, "profile", profiles[i]);
    gtk_label_set_text(GTK_LABEL(gtk_list_item_get_child(item)), ui_korean ? profile_labels_ko[i] : profile_labels_en[i]);
    gtk_list_item_set_selectable(item, available);
    gtk_list_item_set_activatable(item, available);
    gtk_widget_set_sensitive(gtk_list_item_get_child(item), available);
}

static const char *selected_network_mode(InstallerUI *ui) {
    guint selected = gtk_drop_down_get_selected(ui->network_mode);
    return selected < 3 ? network_modes[selected] : "off";
}

static GtkWidget *page_new(const char *title, const char *description) {
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 20);
    gtk_widget_add_css_class(box, "kiki-page");
    GtkWidget *heading = gtk_label_new(title);
    gtk_widget_add_css_class(heading, "kiki-heading");
    gtk_label_set_xalign(GTK_LABEL(heading), 0.0f);
    gtk_box_append(GTK_BOX(box), heading);
    GtkWidget *body = gtk_label_new(description);
    gtk_widget_add_css_class(body, "dim-label");
    gtk_label_set_wrap(GTK_LABEL(body), TRUE);
    gtk_label_set_max_width_chars(GTK_LABEL(body), 64);
    gtk_label_set_xalign(GTK_LABEL(body), 0.0f);
    gtk_box_append(GTK_BOX(box), body);
    return box;
}

static GtkWidget *form_new(void) {
    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 10);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 16);
    gtk_widget_set_hexpand(grid, TRUE);
    gtk_widget_add_css_class(grid, "kiki-form");
    return grid;
}

static GtkEntry *form_entry(GtkGrid *grid, int row, const char *label, const char *value) {
    GtkWidget *name = gtk_label_new(label);
    gtk_label_set_xalign(GTK_LABEL(name), 0.0f);
    gtk_widget_set_size_request(name, 116, -1);
    GtkWidget *entry = gtk_entry_new();
    gtk_editable_set_text(GTK_EDITABLE(entry), value);
    gtk_widget_set_hexpand(entry, TRUE);
    gtk_grid_attach(grid, name, 0, row, 1, 1);
    gtk_grid_attach(grid, entry, 1, row, 1, 1);
    return GTK_ENTRY(entry);
}

static GtkDropDown *form_dropdown(GtkGrid *grid, int row, const char *label, const char *const *items) {
    GtkWidget *name = gtk_label_new(label);
    gtk_label_set_xalign(GTK_LABEL(name), 0.0f);
    gtk_widget_set_size_request(name, 116, -1);
    GtkWidget *dropdown = gtk_drop_down_new_from_strings(items);
    gtk_widget_set_hexpand(dropdown, TRUE);
    gtk_grid_attach(grid, name, 0, row, 1, 1);
    gtk_grid_attach(grid, dropdown, 1, row, 1, 1);
    return GTK_DROP_DOWN(dropdown);
}

static GtkStackPage *stack_page(GtkStack *stack, GtkWidget *page, const char *name, const char *title) {
    GtkWidget *scroller = gtk_scrolled_window_new();
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroller), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroller), page);
    return gtk_stack_add_titled(stack, scroller, name, title);
}

static const char *selected_dns(InstallerUI *ui) {
    if (g_str_equal(selected_network_mode(ui), "off") ||
        gtk_drop_down_get_selected(ui->dns_mode) != 1) return "";
    g_autofree char *normalized = g_strdup(gtk_editable_get_text(GTK_EDITABLE(ui->dns)));
    g_strdelimit(normalized, ",\t\r\n", ' ');
    g_strstrip(normalized);
    if (!g_str_equal(normalized, gtk_editable_get_text(GTK_EDITABLE(ui->dns))))
        gtk_editable_set_text(GTK_EDITABLE(ui->dns), normalized);
    return gtk_editable_get_text(GTK_EDITABLE(ui->dns));
}

static void network_changed(GObject *object, GParamSpec *spec, gpointer data) {
    (void)object; (void)spec;
    InstallerUI *ui = data;
    if (ui->refreshing_network || !ui->network_devices) return;
    guint selected = gtk_drop_down_get_selected(ui->network_device);
    gboolean manual = selected >= ui->network_devices->len;
    gboolean enabled = !g_str_equal(selected_network_mode(ui), "off");
    gboolean fixed = g_str_equal(selected_network_mode(ui), "static");
    if (!manual) {
        KikiNic *nic = g_ptr_array_index(ui->network_devices, selected);
        gtk_editable_set_text(GTK_EDITABLE(ui->network_interface), nic->name);
    }
    gtk_widget_set_sensitive(GTK_WIDGET(ui->network_device), enabled);
    gtk_widget_set_sensitive(GTK_WIDGET(ui->network_interface), enabled && manual);
    gtk_widget_set_sensitive(GTK_WIDGET(ui->address), fixed);
    gtk_widget_set_sensitive(GTK_WIDGET(ui->gateway), fixed);
    gtk_widget_set_sensitive(GTK_WIDGET(ui->dns_mode), enabled);
    gtk_widget_set_sensitive(GTK_WIDGET(ui->dns), enabled && gtk_drop_down_get_selected(ui->dns_mode) == 1);
}

static void network_refresh_from(InstallerUI *ui, const char *sysfs) {
    gboolean initial = ui->network_devices == NULL;
    g_autofree char *previous = g_strdup(gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)));
    gboolean was_manual = !initial && gtk_drop_down_get_selected(ui->network_device) >= ui->network_devices->len;
    ui->refreshing_network = TRUE;
    g_clear_pointer(&ui->network_devices, g_ptr_array_unref);
    ui->network_devices = kiki_network_devices(sysfs);
    g_autoptr(GtkStringList) choices = gtk_string_list_new(NULL);
    guint selected = ui->network_devices->len;
    for (guint i = 0; i < ui->network_devices->len; i++) {
        KikiNic *nic = g_ptr_array_index(ui->network_devices, i);
        gtk_string_list_append(choices, nic->label);
        if (initial && selected == ui->network_devices->len && nic->carrier) selected = i;
        if (!initial && !was_manual && g_str_equal(previous, nic->name)) selected = i;
    }
    if (initial && selected == ui->network_devices->len && ui->network_devices->len) selected = 0;
    gtk_string_list_append(choices, L("고급: 직접 지정 (장치 이름 또는 패턴)", "Advanced: enter device name or pattern"));
    gtk_drop_down_set_model(ui->network_device, G_LIST_MODEL(choices));
    gtk_drop_down_set_selected(ui->network_device, selected);
    if (initial && !ui->network_devices->len) gtk_drop_down_set_selected(ui->network_mode, 2);
    gtk_label_set_text(ui->network_status, !ui->network_devices->len ?
        L("유선 장치를 감지하지 못했습니다. 오프라인 설치 또는 고급 직접 지정을 선택하세요.", "No wired device detected. Choose offline mode or enter a device manually.") :
        (!initial && !was_manual && selected == ui->network_devices->len ?
         L("이전에 선택한 장치가 사라졌습니다. 다른 장치를 선택하거나 직접 지정 값을 확인하세요.", "The selected device disappeared. Choose another device or check the manual pattern.") :
         L("사용할 관리용 NIC를 선택하세요. 다른 NIC의 설정은 변경하지 않습니다.", "Choose the management NIC. Other NICs will not be changed.")));
    ui->refreshing_network = FALSE;
    network_changed(NULL, NULL, ui);
}

static void network_refresh(GtkButton *button, gpointer data) {
    (void)button;
    network_refresh_from(data, "/sys/class/net");
}

static void network_test(GtkButton *button, gpointer data) {
    (void)button;
    InstallerUI *ui = data;
    g_autofree char *status = kiki_network_status(gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)));
    gtk_label_set_text(ui->network_status, status);
}

static void disk_changed(GObject *object, GParamSpec *spec, gpointer data) {
    (void)object; (void)spec;
    InstallerUI *ui = data;
    guint selected = gtk_drop_down_get_selected(ui->disk_device);
    gboolean manual = selected == ui->disks->len + 1;
    gtk_widget_set_sensitive(GTK_WIDGET(ui->disk), manual);
    if (!manual) {
        const char *path = selected > 0 && selected <= ui->disks->len ?
            ((KikiDisk *)g_ptr_array_index(ui->disks, selected - 1))->path : "";
        gtk_editable_set_text(GTK_EDITABLE(ui->disk), path);
    }
}

static void update_review(InstallerUI *ui) {
    const char *network = selected_network_mode(ui);
    const char *source = dropdown_text(ui->source_type);
    const char *ai = dropdown_text(ui->ai_mode);
    g_autofree char *text = g_strdup_printf(
        L("설치 모드: %s\n"
        "대상 디스크: %s (swap: %s)\n"
        "언어: %s / %s / %s\n"
        "네트워크: %s (%s)\n"
        "IP/CIDR: %s / 게이트웨이: %s\n"
        "DNS: %s\n"
        "계정: %s / %s\n"
        "패키지 소스: %s / %s\n"
        "프로필: %s\n"
        "추가 패키지 그룹: %s\n"
        "컨테이너 런타임: %s\n"
        "AI 에이전트: %s / 명령 승인 필수\n"
        "계획 파일: %s\n\n"
        "주의: auto-whole-disk 설치는 선택한 디스크의 기존 데이터를 삭제합니다.\n"
        "GTK 화면과 TUI/무인 설치는 동일한 InstallPlan 생성기를 사용합니다.",
        "Install mode: %s\n"
        "Target disk: %s (swap: %s)\n"
        "System language: %s / %s / %s\n"
        "Network: %s (%s)\n"
        "IP/CIDR: %s / gateway: %s\n"
        "DNS: %s\n"
        "Account: %s / %s\n"
        "Package source: %s / %s\n"
        "Profile: %s\n"
        "Extra package groups: %s\n"
        "Container runtime: %s\n"
        "AI agent: %s / command approval required\n"
        "Plan file: %s\n\n"
        "Warning: whole-disk installation erases existing data on the selected disk.\n"
        "The graphical, text, and unattended installers share one InstallPlan generator."),
        dropdown_text(ui->install_mode),
        gtk_editable_get_text(GTK_EDITABLE(ui->disk)), dropdown_text(ui->swap_mode),
        gtk_editable_get_text(GTK_EDITABLE(ui->locale)),
        gtk_editable_get_text(GTK_EDITABLE(ui->keymap)),
        gtk_editable_get_text(GTK_EDITABLE(ui->timezone)),
        network, gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)),
        g_str_equal(network, "static") ? gtk_editable_get_text(GTK_EDITABLE(ui->address)) : L("자동 / 사용 안 함", "Automatic / disabled"),
        g_str_equal(network, "static") ? gtk_editable_get_text(GTK_EDITABLE(ui->gateway)) : L("자동 / 사용 안 함", "Automatic / disabled"),
        selected_dns(ui)[0] ? selected_dns(ui) : L("자동 / 사용 안 함", "Automatic / disabled"),
        gtk_editable_get_text(GTK_EDITABLE(ui->admin_user)),
        gtk_editable_get_text(GTK_EDITABLE(ui->hostname)),
        source, gtk_editable_get_text(GTK_EDITABLE(ui->source_location)),
        dropdown_text(ui->profile), gtk_editable_get_text(GTK_EDITABLE(ui->package_groups)),
        dropdown_text(ui->runtime), ai,
        gtk_editable_get_text(GTK_EDITABLE(ui->plan_path)));
    gtk_text_buffer_set_text(ui->review, text, -1);
    if (g_str_equal(selected_profile(ui), "desktop-gnome") || strstr(gtk_editable_get_text(GTK_EDITABLE(ui->package_groups)), "desktop-gnome")) {
        gtk_text_buffer_insert_at_cursor(ui->review, L("\n\n로그인 화면: GDM · 기본 부팅: 그래픽 데스크톱 · 복구 콘솔: tty2", "\n\nLogin: GDM · Default boot: graphical desktop · Recovery console: tty2"), -1);
    }
}

static void desktop_profile_selected(GObject *object, GParamSpec *spec, gpointer data) {
    (void)object;
    (void)spec;
    InstallerUI *ui = data;
    if (g_str_equal(selected_profile(ui), "desktop-gnome")) {
        gtk_drop_down_set_selected(ui->ai_mode, 2);
        gtk_drop_down_set_selected(ui->runtime, 1);
    }
    update_profile_status(ui);
}

static void add_arg(GPtrArray *args, const char *name, const char *value) {
    g_ptr_array_add(args, (gpointer)name);
    g_ptr_array_add(args, (gpointer)(value ? value : ""));
}

static gboolean validate_gui(InstallerUI *ui, GError **error) {
    if (g_str_equal(dropdown_text(ui->source_type), "local")) {
        if (!media_available(ui, "profile", selected_profile(ui))) {
            g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT, L("선택한 설치 환경은 이 미디어에서 설치할 수 없습니다.", "The selected environment is not available on this media."));
            return FALSE;
        }
        for (guint i = 0; extra_group_ids[i]; i++) {
            if (gtk_check_button_get_active(ui->extra_groups[i]) && !media_available(ui, "group", extra_group_ids[i])) {
                g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT, "Unavailable package group: %s", extra_group_ids[i]);
                return FALSE;
            }
        }
        if (!g_str_equal(dropdown_text(ui->ai_mode), "off") && !media_available(ui, "group", g_str_equal(dropdown_text(ui->ai_mode), "local") ? "ai-console" : "ai-console-remote")) {
            g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT, L("이 미디어에는 AI 콘솔 패키지가 없습니다. AI를 사용 안 함으로 설정하세요.", "AI console packages are absent. Select AI off."));
            return FALSE;
        }
    }
    if (!g_str_equal(selected_network_mode(ui), "off") &&
        !gtk_editable_get_text(GTK_EDITABLE(ui->network_interface))[0]) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT, L("네트워크 장치를 선택하거나 오프라인 모드를 선택하세요.", "Choose a network device or offline mode."));
        return FALSE;
    }
    if (!g_str_equal(selected_network_mode(ui), "off") &&
        gtk_drop_down_get_selected(ui->dns_mode) == 1 && !selected_dns(ui)[0]) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT, L("직접 지정할 DNS 주소를 입력하세요.", "Enter DNS addresses for manual DNS mode."));
        return FALSE;
    }
    const char *disk = gtk_editable_get_text(GTK_EDITABLE(ui->disk));
    gboolean partition = g_regex_match_simple(
        "^/dev/((sd|vd|xvd|hd)[a-z]+[0-9]+|(nvme[0-9]+n[0-9]+|mmcblk[0-9]+|md[0-9]+)p[0-9]+)$",
        disk, 0, 0);
    if (!g_str_has_prefix(disk, "/dev/") || disk[5] == '\0' || partition) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("대상은 /dev/sda 또는 /dev/nvme0n1 같은 전체 디스크여야 합니다.", "Select a whole disk such as /dev/sda or /dev/nvme0n1."));
        return FALSE;
    }
    if (g_str_equal(selected_network_mode(ui), "static") &&
        gtk_editable_get_text(GTK_EDITABLE(ui->address))[0] == '\0') {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("고정 네트워크에는 CIDR 주소가 필요합니다.", "Static networking requires a CIDR address."));
        return FALSE;
    }
    if (g_str_equal(dropdown_text(ui->source_type), "remote") &&
        gtk_editable_get_text(GTK_EDITABLE(ui->verify_key))[0] == '\0') {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("원격 저장소에는 검증 공개키를 지정해야 합니다.", "A remote repository requires a verification public key."));
        return FALSE;
    }
    if (g_str_equal(dropdown_text(ui->ai_mode), "remote") &&
        gtk_editable_get_text(GTK_EDITABLE(ui->ai_endpoint))[0] == '\0') {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("원격 AI 모드에는 OpenAI 호환 엔드포인트가 필요합니다.", "Remote AI mode requires an OpenAI-compatible endpoint."));
        return FALSE;
    }
    return TRUE;
}

static gboolean write_plan_file(InstallerUI *ui, GError **error) {
    if (!validate_gui(ui, error)) {
        gtk_label_set_text(ui->status, (*error)->message);
        gtk_widget_add_css_class(GTK_WIDGET(ui->status), "error");
        return FALSE;
    }

    const char *tool = g_getenv("KIKI_INSTALLER_TUI");
    if (!tool || !*tool) tool = "kiki-installer-tui";
    g_autoptr(GPtrArray) args = g_ptr_array_new();
    g_ptr_array_add(args, (gpointer)tool);
    g_ptr_array_add(args, "--write");
    add_arg(args, "--plan", gtk_editable_get_text(GTK_EDITABLE(ui->plan_path)));
    add_arg(args, "--mode", dropdown_text(ui->install_mode));
    add_arg(args, "--profile", selected_profile(ui));
    if (gtk_editable_get_text(GTK_EDITABLE(ui->package_groups))[0] != '\0')
        add_arg(args, "--groups", gtk_editable_get_text(GTK_EDITABLE(ui->package_groups)));
    add_arg(args, "--disk", gtk_editable_get_text(GTK_EDITABLE(ui->disk)));
    add_arg(args, "--swap", dropdown_text(ui->swap_mode));
    add_arg(args, "--hostname", gtk_editable_get_text(GTK_EDITABLE(ui->hostname)));
    add_arg(args, "--user", gtk_editable_get_text(GTK_EDITABLE(ui->admin_user)));
    add_arg(args, "--locale", gtk_editable_get_text(GTK_EDITABLE(ui->locale)));
    add_arg(args, "--keymap", gtk_editable_get_text(GTK_EDITABLE(ui->keymap)));
    add_arg(args, "--timezone", gtk_editable_get_text(GTK_EDITABLE(ui->timezone)));
    add_arg(args, "--network", selected_network_mode(ui));
    add_arg(args, "--network-interface", gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)));
    add_arg(args, "--address", gtk_editable_get_text(GTK_EDITABLE(ui->address)));
    add_arg(args, "--gateway", gtk_editable_get_text(GTK_EDITABLE(ui->gateway)));
    add_arg(args, "--dns", selected_dns(ui));
    add_arg(args, "--source", dropdown_text(ui->source_type));
    add_arg(args, "--source-location", gtk_editable_get_text(GTK_EDITABLE(ui->source_location)));
    add_arg(args, "--verify-key", gtk_editable_get_text(GTK_EDITABLE(ui->verify_key)));
    if (!g_str_equal(dropdown_text(ui->runtime), "profile-default"))
        add_arg(args, "--runtime", dropdown_text(ui->runtime));
    add_arg(args, "--ai", dropdown_text(ui->ai_mode));
    add_arg(args, "--ai-endpoint", gtk_editable_get_text(GTK_EDITABLE(ui->ai_endpoint)));
    g_ptr_array_add(args, NULL);

    g_autoptr(GSubprocess) process = g_subprocess_newv(
        (const char *const *)args->pdata,
        G_SUBPROCESS_FLAGS_STDOUT_PIPE | G_SUBPROCESS_FLAGS_STDERR_PIPE,
        error);
    if (!process) {
        gtk_label_set_text(ui->status, (*error)->message);
        return FALSE;
    }
    g_autofree char *stdout_text = NULL;
    g_autofree char *stderr_text = NULL;
    if (!g_subprocess_communicate_utf8(process, NULL, NULL, &stdout_text, &stderr_text, error) ||
        !g_subprocess_get_successful(process)) {
        gtk_label_set_text(ui->status, *error ? (*error)->message : (stderr_text && *stderr_text ? stderr_text : L("계획 생성 실패", "Could not generate the plan")));
        gtk_widget_add_css_class(GTK_WIDGET(ui->status), "error");
        return FALSE;
    }
    gtk_widget_remove_css_class(GTK_WIDGET(ui->status), "error");
    gtk_label_set_text(ui->status, stdout_text && *stdout_text ? stdout_text : L("설치 계획을 저장했습니다.", "Installation plan saved."));
    update_review(ui);
    return TRUE;
}

static void write_plan(GtkButton *button, gpointer data) {
    (void)button;
    InstallerUI *ui = data;
    g_autoptr(GError) error = NULL;
    write_plan_file(ui, &error);
}

static void target_disk_changed(GtkEditable *editable, gpointer data) {
    (void)editable;
    InstallerUI *ui = data;
    gtk_check_button_set_active(ui->destructive_confirm, FALSE);
    update_review(ui);
}

static void consent_changed(GtkCheckButton *button, gpointer data) {
    InstallerUI *ui = data;
    gtk_widget_set_sensitive(GTK_WIDGET(ui->install_button), gtk_check_button_get_active(button));
}

static gboolean append_request_field(GString *request, const char *key, const char *value, GError **error) {
    value = value ? value : "";
    if (strchr(value, '\n') || strchr(value, '\r')) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("%s 값에는 줄바꿈을 사용할 수 없습니다.", "%s cannot contain a newline."), key);
        return FALSE;
    }
    g_string_append_printf(request, "%s=%s\n", key, value);
    return TRUE;
}

static gboolean write_install_request(InstallerUI *ui, GError **error) {
    const char *password = gtk_editable_get_text(GTK_EDITABLE(ui->admin_password));
    const char *password_confirm = gtk_editable_get_text(GTK_EDITABLE(ui->admin_password_confirm));
    const char *disk = gtk_editable_get_text(GTK_EDITABLE(ui->disk));
    g_autofree char *expected = g_strdup_printf("INSTALL %s", disk);
    gsize password_bytes = strlen(password);
    if (password_bytes < 8 || password_bytes > 95) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("관리자 암호는 UTF-8 기준 8~95바이트로 입력하세요.", "Administrator password must be 8–95 UTF-8 bytes."));
        return FALSE;
    }
    if (!g_str_equal(password, password_confirm)) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("관리자 암호 확인이 일치하지 않습니다.", "Administrator passwords do not match."));
        return FALSE;
    }
    if (!gtk_check_button_get_active(ui->destructive_confirm)) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("선택한 디스크의 데이터 삭제에 동의해 주세요.", "Confirm that data on the selected disk may be erased."));
        return FALSE;
    }
    if (!g_str_equal(dropdown_text(ui->source_type), "local")) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_NOT_SUPPORTED,
                    L("현재 ISO 설치 실행은 로컬 설치 미디어만 지원합니다.", "This ISO installer currently supports local installation media only."));
        return FALSE;
    }
    if (g_str_has_prefix(selected_profile(ui), "kiki-kube-") &&
        g_str_equal(dropdown_text(ui->swap_mode), "on")) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    L("Kubernetes 프로필은 swap을 켠 상태로 설치할 수 없습니다.", "Kubernetes profiles cannot be installed with swap enabled."));
        return FALSE;
    }

    const char *plan_path = gtk_editable_get_text(GTK_EDITABLE(ui->plan_path));
    g_autofree char *plan = NULL;
    gsize plan_size = 0;
    if (!g_file_get_contents(plan_path, &plan, &plan_size, error)) return FALSE;

    g_autoptr(GString) request = g_string_new("version=2\n");
#define REQUEST_FIELD(key, value) \
    do { if (!append_request_field(request, key, value, error)) return FALSE; } while (0)
    REQUEST_FIELD("plan", plan_path);
    REQUEST_FIELD("disk", gtk_editable_get_text(GTK_EDITABLE(ui->disk)));
    REQUEST_FIELD("swap", dropdown_text(ui->swap_mode));
    REQUEST_FIELD("hostname", gtk_editable_get_text(GTK_EDITABLE(ui->hostname)));
    REQUEST_FIELD("user", gtk_editable_get_text(GTK_EDITABLE(ui->admin_user)));
    REQUEST_FIELD("password", password);
    REQUEST_FIELD("confirmed", expected);
    REQUEST_FIELD("locale", gtk_editable_get_text(GTK_EDITABLE(ui->locale)));
    REQUEST_FIELD("keymap", gtk_editable_get_text(GTK_EDITABLE(ui->keymap)));
    REQUEST_FIELD("timezone", gtk_editable_get_text(GTK_EDITABLE(ui->timezone)));
    REQUEST_FIELD("network", selected_network_mode(ui));
    REQUEST_FIELD("network_interface", gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)));
    REQUEST_FIELD("address", gtk_editable_get_text(GTK_EDITABLE(ui->address)));
    REQUEST_FIELD("gateway", gtk_editable_get_text(GTK_EDITABLE(ui->gateway)));
    REQUEST_FIELD("dns", selected_dns(ui));
    REQUEST_FIELD("profile", selected_profile(ui));
    REQUEST_FIELD("runtime", dropdown_text(ui->runtime));
    REQUEST_FIELD("ai", dropdown_text(ui->ai_mode));
    REQUEST_FIELD("ai_endpoint", gtk_editable_get_text(GTK_EDITABLE(ui->ai_endpoint)));
#undef REQUEST_FIELD

    gboolean selected = FALSE;
    g_auto(GStrv) lines = g_strsplit(plan, "\n", -1);
    for (gsize i = 0; lines[i]; i++) {
        if (g_str_equal(lines[i], "    selected:")) {
            selected = TRUE;
            continue;
        }
        if (selected && !g_str_has_prefix(lines[i], "      - \"")) break;
        if (selected) {
            const char *start = lines[i] + 9;
            const char *end = strrchr(start, '"');
            if (end && end > start) {
                g_autofree char *package = g_strndup(start, end - start);
                if (!append_request_field(request, "package", package, error)) return FALSE;
            }
        }
    }
    int request_fd = g_open(GUI_INSTALL_REQUEST_TMP_PATH, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (request_fd < 0) {
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(errno),
                    L("설치 요청 파일을 열 수 없습니다: %s", "Cannot open installation request: %s"), g_strerror(errno));
        return FALSE;
    }
    if (fchmod(request_fd, 0600) != 0) {
        int saved_errno = errno;
        close(request_fd);
        g_unlink(GUI_INSTALL_REQUEST_TMP_PATH);
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(saved_errno),
                    L("설치 요청 파일 권한을 설정할 수 없습니다: %s", "Cannot set installation request permissions: %s"), g_strerror(saved_errno));
        return FALSE;
    }
    gsize written = 0;
    while (written < request->len) {
        ssize_t amount = write(request_fd, request->str + written, request->len - written);
        if (amount < 0 && errno == EINTR) continue;
        if (amount <= 0) {
            int saved_errno = errno;
            close(request_fd);
            g_unlink(GUI_INSTALL_REQUEST_TMP_PATH);
            g_set_error(error, G_IO_ERROR, g_io_error_from_errno(saved_errno),
                        L("설치 요청 파일을 쓸 수 없습니다: %s", "Cannot write installation request: %s"), g_strerror(saved_errno));
            return FALSE;
        }
        written += (gsize)amount;
    }
    if (close(request_fd) != 0) {
        int saved_errno = errno;
        g_unlink(GUI_INSTALL_REQUEST_TMP_PATH);
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(saved_errno),
                    L("설치 요청 파일을 닫을 수 없습니다: %s", "Cannot close installation request: %s"), g_strerror(saved_errno));
        return FALSE;
    }
    if (link(GUI_INSTALL_REQUEST_TMP_PATH, GUI_INSTALL_REQUEST_PATH) != 0) {
        int saved_errno = errno;
        g_unlink(GUI_INSTALL_REQUEST_TMP_PATH);
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(saved_errno),
                    L("설치 요청을 전달할 수 없습니다: %s", "Cannot submit installation request: %s"), g_strerror(saved_errno));
        return FALSE;
    }
    g_unlink(GUI_INSTALL_REQUEST_TMP_PATH);
    return TRUE;
}

static char *progress_value(const char *contents, const char *key) {
    g_autofree char *prefix = g_strdup_printf("%s=", key);
    g_auto(GStrv) lines = g_strsplit(contents ? contents : "", "\n", -1);
    for (gsize i = 0; lines[i]; i++) {
        if (g_str_has_prefix(lines[i], prefix)) return g_strdup(lines[i] + strlen(prefix));
    }
    return g_strdup("");
}

static gboolean valid_install_progress(const char *contents, gsize length) {
    if (!contents || length == 0 || length > 16384 || memchr(contents, 0, length) ||
        !g_utf8_validate(contents, length, NULL)) return FALSE;
    g_autoptr(GHashTable) fields = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_free);
    g_auto(GStrv) lines = g_strsplit(contents, "\n", -1);
    for (gsize i = 0; lines[i]; i++) {
        if (!*lines[i]) continue;
        char *separator = strchr(lines[i], '=');
        if (!separator || separator == lines[i]) return FALSE;
        *separator = 0;
        if (g_hash_table_contains(fields, lines[i])) return FALSE;
        g_hash_table_insert(fields, g_strdup(lines[i]), g_strdup(separator + 1));
    }
    const char *version = g_hash_table_lookup(fields, "version");
    const char *state = g_hash_table_lookup(fields, "state");
    if (g_strcmp0(version, "1") != 0 || !state) return FALSE;
    if (strcmp(state, "running") && strcmp(state, "failed") &&
        strcmp(state, "completed") && strcmp(state, "rebooting")) return FALSE;
    const char *keys[] = {"percent", "packages_installed", "packages_total"};
    guint64 numbers[3];
    for (gsize i = 0; i < G_N_ELEMENTS(keys); i++) {
        const char *value = g_hash_table_lookup(fields, keys[i]);
        if (!value || !*value) return FALSE;
        for (const char *p = value; *p; p++) if (*p < '0' || *p > '9') return FALSE;
        if (!g_ascii_string_to_unsigned(value, 10, 0, G_MAXINT64, &numbers[i], NULL)) return FALSE;
    }
    if (numbers[0] > 100 || numbers[1] > numbers[2]) return FALSE;
    if ((!strcmp(state, "completed") || !strcmp(state, "rebooting")) &&
        (numbers[0] != 100 || numbers[1] != numbers[2])) return FALSE;
    return TRUE;
}

static void append_progress_log(InstallerUI *ui, const char *message) {
    if (!message || !*message || g_strcmp0(message, ui->last_progress_message) == 0) return;
    GtkTextIter end;
    gtk_text_buffer_get_end_iter(ui->progress_log, &end);
    gtk_text_buffer_insert(ui->progress_log, &end, message, -1);
    gtk_text_buffer_insert(ui->progress_log, &end, "\n", 1);
    g_free(ui->last_progress_message);
    ui->last_progress_message = g_strdup(message);
}

static void append_backend_failure(InstallerUI *ui) {
    g_autoptr(GFile) file = g_file_new_for_path(GUI_INSTALL_BACKEND_LOG_PATH);
    g_autoptr(GFileInputStream) stream = g_file_read(file, NULL, NULL);
    if (!stream) return;
    if (!g_seekable_seek(G_SEEKABLE(stream), -4096, G_SEEK_END, NULL, NULL))
        g_seekable_seek(G_SEEKABLE(stream), 0, G_SEEK_SET, NULL, NULL);
    char buffer[4097];
    gssize length = g_input_stream_read(G_INPUT_STREAM(stream), buffer, sizeof(buffer) - 1, NULL, NULL);
    if (length <= 0) return;
    buffer[length] = '\0';
    g_autofree char *text = g_utf8_make_valid(buffer, length);
    append_progress_log(ui, text);
}

/* Lack of progress is advisory, never evidence that disk writes have stopped. */
static gboolean progress_is_stale(char fingerprint[65], gint64 *changed_at,
                                  const char *contents, gsize length, gint64 now) {
    g_autofree char *digest = g_compute_checksum_for_data(
        G_CHECKSUM_SHA256, (const guchar *)contents, length);
    if (strcmp(fingerprint, digest) != 0 || now < *changed_at) {
        g_strlcpy(fingerprint, digest, 65);
        *changed_at = now;
        return FALSE;
    }
    return now - *changed_at >= 120 * G_USEC_PER_SEC;
}

static gboolean poll_install_progress(gpointer data) {
    InstallerUI *ui = data;
    g_autofree char *contents = NULL;
    gsize length = 0;
    if (!g_file_get_contents(GUI_INSTALL_PROGRESS_PATH, &contents, &length, NULL) ||
        !valid_install_progress(contents, length)) {
        gtk_label_set_text(ui->progress_message,
                           L("진행 상태를 확인할 수 없습니다. 설치가 계속 진행 중일 수 있으므로 재부팅하지 말고 복구 콘솔에서 로그를 확인하세요.", "Cannot read installation progress. Installation may still be running. Do not reboot; check the log in the recovery console."));
        return G_SOURCE_CONTINUE;
    }

    g_autofree char *state = progress_value(contents, "state");
    gboolean stale = progress_is_stale(ui->progress_fingerprint, &ui->progress_changed_at,
                                       contents, length, g_get_monotonic_time());
    g_autofree char *percent_text = progress_value(contents, "percent");
    g_autofree char *phase = progress_value(contents, "phase");
    g_autofree char *message = progress_value(contents, "message");
    g_autofree char *packages_installed_text = progress_value(contents, "packages_installed");
    g_autofree char *packages_total_text = progress_value(contents, "packages_total");
    g_autofree char *package = progress_value(contents, "package");
    gint64 percent = g_ascii_strtoll(percent_text, NULL, 10);
    gint64 packages_installed = g_ascii_strtoll(packages_installed_text, NULL, 10);
    gint64 packages_total = g_ascii_strtoll(packages_total_text, NULL, 10);
    percent = CLAMP(percent, 0, 100);
    gtk_progress_bar_set_fraction(ui->progress, (double)percent / 100.0);
    gtk_progress_bar_set_show_text(ui->progress, TRUE);
    g_autofree char *progress_text = g_strdup_printf("%" G_GINT64_FORMAT "%%", percent);
    gtk_progress_bar_set_text(ui->progress, progress_text);
    gtk_label_set_text(ui->progress_phase, phase && *phase ? phase : L("설치 준비", "Preparing installation"));
    if (packages_total > 0) {
        g_autofree char *package_text = NULL;
        if (packages_installed < packages_total && package && *package) {
            package_text = g_strdup_printf(
                L("패키지 설치 완료: %" G_GINT64_FORMAT " / %" G_GINT64_FORMAT "개 · 현재: %s", "Packages installed: %" G_GINT64_FORMAT " / %" G_GINT64_FORMAT " · current: %s"),
                packages_installed, packages_total, package);
        } else {
            package_text = g_strdup_printf(
                L("패키지 설치 완료: %" G_GINT64_FORMAT " / %" G_GINT64_FORMAT "개", "Packages installed: %" G_GINT64_FORMAT " / %" G_GINT64_FORMAT),
                packages_installed, packages_total);
        }
        gtk_label_set_text(ui->package_count, package_text);
        gtk_widget_set_visible(GTK_WIDGET(ui->package_count), TRUE);
    }
    gtk_label_set_text(ui->progress_message, message);
    append_progress_log(ui, message);

    if (g_str_equal(state, "completed")) {
        ui->install_complete = TRUE;
        gtk_progress_bar_set_fraction(ui->progress, 1.0);
        gtk_progress_bar_set_text(ui->progress, "100%");
        gtk_label_set_text(ui->progress_phase, L("설치 완료", "Installation complete"));
        gtk_label_set_text(ui->progress_message,
                           L("설치가 완료되었습니다. ISO를 분리한 뒤 아래 버튼을 눌러 재부팅하세요.", "Installation complete. Detach the ISO, then select the button below to reboot."));
        gtk_widget_set_visible(GTK_WIDGET(ui->reboot_button), TRUE);
        gtk_widget_set_sensitive(GTK_WIDGET(ui->reboot_button), TRUE);
        ui->progress_source = 0;
        return G_SOURCE_REMOVE;
    }
    if (g_str_equal(state, "failed")) {
        ui->install_failed = TRUE;
        append_backend_failure(ui);
        gtk_widget_add_css_class(GTK_WIDGET(ui->progress_phase), "error");
        gtk_label_set_text(ui->progress_phase, L("설치 실패", "Installation failed"));
        gtk_label_set_text(ui->progress_message,
                           message && *message ? message : L("설치에 실패했습니다. 콘솔 로그를 확인하세요.", "Installation failed. Check the console log."));
        gtk_button_set_label(ui->reboot_button, L("인스톨러 종료", "Close installer"));
        gtk_widget_set_visible(GTK_WIDGET(ui->reboot_button), TRUE);
        gtk_widget_set_sensitive(GTK_WIDGET(ui->reboot_button), TRUE);
        gtk_window_set_deletable(ui->window, TRUE);
        ui->progress_source = 0;
        return G_SOURCE_REMOVE;
    }
    if (stale) {
        const char *notice = L("2분 이상 진행 상태가 바뀌지 않았습니다. 작업이 오래 걸리는 중일 수 있습니다. 재부팅하지 말고 복구 콘솔에서 /run/kiki/gui-install-backend.log를 확인하세요.", "Progress has not changed for over two minutes. The task may be slow. Do not reboot; inspect /run/kiki/gui-install-backend.log in the recovery console.");
        gtk_label_set_text(ui->progress_message, notice);
    }
    return G_SOURCE_CONTINUE;
}

static void request_reboot(GtkButton *button, gpointer data) {
    InstallerUI *ui = data;
    if (!ui->install_complete) {
        g_application_quit(g_application_get_default());
        return;
    }
    g_autoptr(GError) error = NULL;
    if (!g_file_set_contents(GUI_REBOOT_REQUEST_TMP_PATH, "confirm=yes\n", -1, &error) ||
        g_chmod(GUI_REBOOT_REQUEST_TMP_PATH, 0600) != 0 ||
        g_rename(GUI_REBOOT_REQUEST_TMP_PATH, GUI_REBOOT_REQUEST_PATH) != 0) {
        gtk_label_set_text(ui->progress_message,
                           error ? error->message : L("재부팅 요청을 전달할 수 없습니다.", "Cannot request a reboot."));
        gtk_widget_add_css_class(GTK_WIDGET(ui->progress_message), "error");
        g_unlink(GUI_REBOOT_REQUEST_TMP_PATH);
        return;
    }
    gtk_widget_set_sensitive(GTK_WIDGET(button), FALSE);
    gtk_button_set_label(button, L("재부팅 중…", "Rebooting…"));
    gtk_label_set_text(ui->progress_message, L("재부팅을 요청했습니다. 잠시 기다려 주세요.", "Reboot requested. Please wait."));
}

static void start_install(GtkButton *button, gpointer data) {
    (void)button;
    InstallerUI *ui = data;
    g_autoptr(GError) error = NULL;
    if (!write_plan_file(ui, &error) || !write_install_request(ui, &error)) {
        if (error) gtk_label_set_text(ui->status, error->message);
        gtk_widget_add_css_class(GTK_WIDGET(ui->status), "error");
        return;
    }
    gtk_widget_remove_css_class(GTK_WIDGET(ui->status), "error");
    gtk_label_set_text(ui->status, L("관리자 암호와 디스크 삭제 확인이 완료되었습니다. 설치를 시작합니다.", "Password and disk erasure confirmation accepted. Starting installation."));
    gtk_editable_set_text(GTK_EDITABLE(ui->admin_password), "");
    gtk_editable_set_text(GTK_EDITABLE(ui->admin_password_confirm), "");
    ui->install_started = TRUE;
    ui->progress_fingerprint[0] = '\0';
    ui->progress_changed_at = g_get_monotonic_time();
    gtk_window_set_deletable(ui->window, FALSE);
    gtk_widget_set_sensitive(ui->sidebar, FALSE);
    gtk_stack_page_set_visible(gtk_stack_get_page(ui->stack, gtk_stack_get_child_by_name(ui->stack, "progress")), TRUE);
    gtk_stack_set_visible_child_name(ui->stack, "progress");
    gtk_progress_bar_set_fraction(ui->progress, 0.01);
    gtk_progress_bar_set_text(ui->progress, "1%");
    gtk_label_set_text(ui->progress_phase, L("설치 요청 전달", "Submitting installation request"));
    gtk_label_set_text(ui->progress_message, L("설치 백엔드가 요청을 확인하고 있습니다.", "The installation backend is processing the request."));
    append_progress_log(ui, L("설치 요청을 안전하게 전달했습니다.", "Installation request submitted securely."));
    if (!ui->progress_source)
        ui->progress_source = g_timeout_add(200, poll_install_progress, ui);
}

static void review_clicked(GtkButton *button, gpointer data) {
    (void)button;
    update_review(data);
}

static const char *wizard_pages[] = {
    "welcome", "localization", "disk", "network", "account", "source", "profile", "review"
};

static void navigation_changed(GObject *object, GParamSpec *spec, gpointer data) {
    (void)object; (void)spec;
    InstallerUI *ui = data;
    const char *name = gtk_stack_get_visible_child_name(ui->stack);
    gboolean progress = g_strcmp0(name, "progress") == 0;
    gtk_widget_set_visible(ui->navigation, !progress);
    gtk_widget_set_visible(ui->footer, !progress);
    if (progress) return;
    guint index = 0;
    for (guint i = 0; i < G_N_ELEMENTS(wizard_pages); i++)
        if (g_strcmp0(name, wizard_pages[i]) == 0) index = i;
    g_autofree char *step = g_strdup_printf(L("%u / %u 단계", "Step %u of %u"), index + 1, (guint)G_N_ELEMENTS(wizard_pages));
    gtk_label_set_text(ui->step_label, step);
    gtk_widget_set_sensitive(GTK_WIDGET(ui->back_button), index > 0);
    gtk_widget_set_visible(GTK_WIDGET(ui->next_button), index + 1 < G_N_ELEMENTS(wizard_pages));
    gtk_button_set_label(ui->next_button, index == 0 ? L("설정 시작", "Get started") : L("다음", "Continue"));
    if (g_strcmp0(name, "review") == 0) update_review(ui);
}

static void navigate(GtkButton *button, gpointer data) {
    InstallerUI *ui = data;
    if (ui->install_started) return;
    const char *name = gtk_stack_get_visible_child_name(ui->stack);
    for (guint i = 0; i < G_N_ELEMENTS(wizard_pages); i++) {
        if (g_strcmp0(name, wizard_pages[i]) != 0) continue;
        int next = (int)i + (button == ui->back_button ? -1 : 1);
        if (next >= 0 && next < (int)G_N_ELEMENTS(wizard_pages))
            gtk_stack_set_visible_child_name(ui->stack, wizard_pages[next]);
        return;
    }
}

static gboolean installer_close_requested(GtkWindow *window, gpointer data) {
    (void)window;
    InstallerUI *ui = data;
    return ui->install_started && !ui->install_complete && !ui->install_failed;
}

static GtkWidget *welcome_item(const char *number, const char *title, const char *description) {
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 10);
    gtk_widget_add_css_class(box, "welcome-item");
    GtkWidget *badge = gtk_label_new(number);
    gtk_widget_add_css_class(badge, "step-badge");
    gtk_widget_set_halign(badge, GTK_ALIGN_START);
    gtk_box_append(GTK_BOX(box), badge);
    GtkWidget *heading = gtk_label_new(title);
    gtk_label_set_xalign(GTK_LABEL(heading), 0);
    gtk_widget_add_css_class(heading, "card-title");
    gtk_box_append(GTK_BOX(box), heading);
    GtkWidget *body = gtk_label_new(description);
    gtk_label_set_wrap(GTK_LABEL(body), TRUE);
    gtk_label_set_xalign(GTK_LABEL(body), 0);
    gtk_label_set_max_width_chars(GTK_LABEL(body), 22);
    gtk_widget_add_css_class(body, "dim-label");
    gtk_box_append(GTK_BOX(box), body);
    return box;
}

static void status_changed(GObject *object, GParamSpec *spec, gpointer data) {
    (void)spec; (void)data;
    GtkLabel *label = GTK_LABEL(object);
    gtk_widget_set_visible(GTK_WIDGET(label), gtk_label_get_text(label)[0] != '\0');
}

static void load_css(void) {
    GtkCssProvider *provider = gtk_css_provider_new();
    const char *path = g_getenv("KIKI_INSTALLER_CSS");
    if (!path || !*path) path = "/usr/share/kiki-installer-gtk/style.css";
    if (g_file_test(path, G_FILE_TEST_EXISTS)) {
        gtk_css_provider_load_from_path(provider, path);
    } else if (g_file_test("cmd/kiki-installer-gtk/style.css", G_FILE_TEST_EXISTS)) {
        gtk_css_provider_load_from_path(provider, "cmd/kiki-installer-gtk/style.css");
    }
    gtk_style_context_add_provider_for_display(
        gdk_display_get_default(), GTK_STYLE_PROVIDER(provider),
        GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    g_object_unref(provider);
}

static GtkWidget *brand_image(void) {
    const char *path = g_getenv("KIKI_INSTALLER_LOGO");
    if (!path || !*path) {
        path = "/usr/share/pixmaps/kiki-installer.png";
        if (!g_file_test(path, G_FILE_TEST_IS_REGULAR))
            path = "assets/brand/kikios-kiki-wordmark-v1.png";
    }
    g_autoptr(GError) error = NULL;
    g_autoptr(GdkTexture) texture = gdk_texture_new_from_filename(path, &error);
    if (!texture) {
        g_warning("Installer logo unavailable: %s", error ? error->message : "unknown error");
        return NULL;
    }
    /* GTK's native PNG loader remains available after GTK disables the
     * overlapping GdkPixbuf format loaders during the language chooser. */
    GtkSnapshot *snapshot = gtk_snapshot_new();
    float scale = MIN(96.0f / gdk_texture_get_width(texture), 32.0f / gdk_texture_get_height(texture));
    float width = gdk_texture_get_width(texture) * scale;
    float height = gdk_texture_get_height(texture) * scale;
    graphene_rect_t bounds = GRAPHENE_RECT_INIT((96 - width) / 2, (32 - height) / 2, width, height);
    gtk_snapshot_append_texture(snapshot, texture, &bounds);
    graphene_size_t size = GRAPHENE_SIZE_INIT(96, 32);
    g_autoptr(GdkPaintable) paintable = gtk_snapshot_free_to_paintable(snapshot, &size);
    GtkWidget *image = gtk_picture_new_for_paintable(paintable);
    gtk_picture_set_content_fit(GTK_PICTURE(image), GTK_CONTENT_FIT_CONTAIN);
    gtk_widget_set_size_request(image, 96, 32);
    gtk_widget_add_css_class(image, "kiki-brand");
    gtk_accessible_update_property(GTK_ACCESSIBLE(image),
                                   GTK_ACCESSIBLE_PROPERTY_LABEL, "KIKI 키키 로고", -1);
    return image;
}

static void build_installer_ui(GtkApplication *application) {
    InstallerUI *ui = g_new0(InstallerUI, 1);
    load_css();

    ui->window = GTK_WINDOW(gtk_application_window_new(application));
    g_object_set_data(G_OBJECT(ui->window), "kiki-ui-version", (gpointer)"KIKI_INSTALLER_UI_V2");
    gtk_window_set_title(ui->window, L("KIKI OS 인스톨러", "KIKI OS Installer"));
    gtk_window_set_icon_name(ui->window, "kiki-installer");
    gtk_window_set_default_size(ui->window, 980, 680);

    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkWidget *header = gtk_header_bar_new();
    gtk_widget_add_css_class(header, "kiki-header");
    GtkWidget *brand = brand_image();
    if (brand) gtk_header_bar_pack_start(GTK_HEADER_BAR(header), brand);
    GtkWidget *title = gtk_label_new(L("KIKI OS 설치", "KIKI OS Installer"));
    gtk_widget_add_css_class(title, "title-3");
    gtk_header_bar_set_title_widget(GTK_HEADER_BAR(header), title);
    gtk_window_set_titlebar(ui->window, header);

    GtkWidget *content = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    gtk_widget_set_vexpand(content, TRUE);
    GtkWidget *stack = gtk_stack_new();
    ui->stack = GTK_STACK(stack);
    gtk_stack_set_transition_type(GTK_STACK(stack), GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    gtk_stack_set_vhomogeneous(GTK_STACK(stack), FALSE);
    gtk_stack_set_hhomogeneous(GTK_STACK(stack), FALSE);
    gtk_widget_set_hexpand(stack, TRUE);
    gtk_widget_set_vexpand(stack, TRUE);
    GtkWidget *sidebar = gtk_stack_sidebar_new();
    ui->sidebar = sidebar;
    gtk_stack_sidebar_set_stack(GTK_STACK_SIDEBAR(sidebar), GTK_STACK(stack));
    gtk_widget_add_css_class(sidebar, "kiki-sidebar");
    gtk_box_append(GTK_BOX(content), sidebar);
    gtk_box_append(GTK_BOX(content), stack);
    gtk_box_append(GTK_BOX(root), content);

    GtkWidget *page = page_new(L("KIKI OS를 설치합니다", "Make this computer yours"), L("언어, 설치할 디스크와 계정을 설정하세요. 마지막 단계에서 설정을 확인한 뒤 설치를 시작합니다.", "Choose your language, installation disk, and account. Review your settings before starting installation."));
    GtkWidget *overview = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_box_set_homogeneous(GTK_BOX(overview), TRUE);
    gtk_box_append(GTK_BOX(overview), welcome_item("01", L("환경 설정", "Personalize"), L("언어와 지역, 네트워크를 설정합니다.", "Set your language, region, and network.")));
    gtk_box_append(GTK_BOX(overview), welcome_item("02", L("시스템 구성", "Configure"), L("설치할 디스크와 관리자 계정을 선택합니다.", "Choose a disk and administrator account.")));
    gtk_box_append(GTK_BOX(overview), welcome_item("03", L("확인 후 설치", "Review & install"), L("설정을 검토하고 설치를 시작합니다.", "Review your choices and begin installation.")));
    gtk_box_append(GTK_BOX(page), overview);
    GtkWidget *grid = form_new();
    ui->install_mode = form_dropdown(GTK_GRID(grid), 0, L("설치 모드", "Install mode"), install_modes);
    ui->plan_path = form_entry(GTK_GRID(grid), 1, L("계획 파일", "Plan file"), "/run/kiki/install-plan.yaml");
    GtkWidget *advanced = gtk_expander_new(L("고급 설치 옵션", "Advanced installation options"));
    gtk_expander_set_child(GTK_EXPANDER(advanced), grid);
    gtk_box_append(GTK_BOX(page), advanced);
    stack_page(GTK_STACK(stack), page, "welcome", L("시작", "Welcome"));

    page = page_new(L("언어 및 지역", "Language and region"), L("설치한 시스템에서 사용할 언어, 키보드와 시간대를 선택하세요.", "Choose the language, keyboard, and timezone for your installed system."));
    grid = form_new();
    ui->locale = form_entry(GTK_GRID(grid), 0, L("시스템 언어", "System locale"), ui_korean ? "ko_KR.UTF-8" : "en_US.UTF-8");
    ui->keymap = form_entry(GTK_GRID(grid), 1, L("키보드", "Keyboard"), ui_korean ? "kr" : "us");
    ui->timezone = form_entry(GTK_GRID(grid), 2, L("시간대", "Timezone"), ui_korean ? "Asia/Seoul" : "UTC");
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "localization", L("언어 및 지역", "System language"));

    page = page_new(L("디스크", "Disk"), L("자동 설치는 선택한 전체 디스크를 다시 파티셔닝합니다.", "Installation repartitions the entire selected disk."));
    grid = form_new();
    ui->disks = kiki_install_disks("/sys/class/block");
    g_autoptr(GtkStringList) disk_choices = gtk_string_list_new(NULL);
    gtk_string_list_append(disk_choices, L("설치할 디스크를 선택하세요", "Choose an installation disk"));
    for (guint i = 0; i < ui->disks->len; i++)
        gtk_string_list_append(disk_choices, ((KikiDisk *)g_ptr_array_index(ui->disks, i))->label);
    gtk_string_list_append(disk_choices, L("고급: 장치 경로 직접 입력", "Advanced: enter device path"));
    const char *empty_disks[] = {NULL};
    ui->disk_device = form_dropdown(GTK_GRID(grid), 0, L("설치할 디스크", "Install to"), empty_disks);
    gtk_drop_down_set_model(ui->disk_device, G_LIST_MODEL(disk_choices));
    gtk_drop_down_set_selected(ui->disk_device, 0);
    ui->disk = form_entry(GTK_GRID(grid), 1, L("장치 경로", "Device path"), "");
    gtk_entry_set_placeholder_text(ui->disk, "/dev/sda, /dev/vda, /dev/nvme0n1");
    gtk_widget_set_sensitive(GTK_WIDGET(ui->disk), FALSE);
    g_signal_connect(ui->disk_device, "notify::selected", G_CALLBACK(disk_changed), ui);
    ui->swap_mode = form_dropdown(GTK_GRID(grid), 2, "Swap", swap_modes);
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "disk", L("디스크", "Disk"));

    page = page_new(L("네트워크", "Network"), L("인터넷에 연결할 장치를 선택하세요. 연결 없이 설치하려면 오프라인을 선택할 수 있습니다.", "Choose a network device, or select offline to install without a connection."));
    grid = form_new();
    ui->network_mode = form_dropdown(GTK_GRID(grid), 0, L("모드", "Mode"), ui_korean ? network_mode_labels_ko : network_mode_labels_en);
    const char *device_items[] = {L("장치 검색 중", "Detecting devices"), NULL};
    const char *dns_items[] = {L("자동 (DHCP/RA)", "Automatic (DHCP/RA)"), L("직접 입력", "Manual"), NULL};
    ui->network_device = form_dropdown(GTK_GRID(grid), 1, L("네트워크 장치", "Network device"), device_items);
    ui->network_interface = form_entry(GTK_GRID(grid), 2, L("장치 / 고급 패턴", "Device / advanced pattern"), "");
    ui->address = form_entry(GTK_GRID(grid), 3, L("주소/CIDR", "Address/CIDR"), "");
    ui->gateway = form_entry(GTK_GRID(grid), 4, L("게이트웨이", "Gateway"), "");
    ui->dns_mode = form_dropdown(GTK_GRID(grid), 5, L("DNS 설정", "DNS mode"), dns_items);
    ui->dns = form_entry(GTK_GRID(grid), 6, L("DNS 주소", "DNS addresses"), "");
    GtkWidget *net_buttons = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *refresh = gtk_button_new_with_label(L("장치 새로고침", "Refresh devices"));
    GtkWidget *test = gtk_button_new_with_label(L("현재 연결 확인", "Test connection"));
    gtk_box_append(GTK_BOX(net_buttons), refresh);
    gtk_box_append(GTK_BOX(net_buttons), test);
    gtk_grid_attach(GTK_GRID(grid), net_buttons, 1, 7, 1, 1);
    ui->network_status = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_wrap(ui->network_status, TRUE);
    gtk_label_set_xalign(ui->network_status, 0);
    gtk_grid_attach(GTK_GRID(grid), GTK_WIDGET(ui->network_status), 0, 8, 2, 1);
    g_signal_connect(refresh, "clicked", G_CALLBACK(network_refresh), ui);
    g_signal_connect(test, "clicked", G_CALLBACK(network_test), ui);
    g_signal_connect(ui->network_device, "notify::selected", G_CALLBACK(network_changed), ui);
    g_signal_connect(ui->network_mode, "notify::selected", G_CALLBACK(network_changed), ui);
    g_signal_connect(ui->dns_mode, "notify::selected", G_CALLBACK(network_changed), ui);
    network_refresh(NULL, ui);
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "network", L("네트워크", "Network"));

    page = page_new(L("내 계정 만들기", "Create your account"), L("로그인할 관리자 계정과 이 컴퓨터의 이름을 설정하세요. 암호는 8~95바이트로 입력합니다.", "Set your administrator login and this computer's name. Use a password of 8–95 UTF-8 bytes."));
    grid = form_new();
    ui->admin_user = form_entry(GTK_GRID(grid), 0, L("관리자", "Administrator"), "kiki");
    ui->hostname = form_entry(GTK_GRID(grid), 1, L("호스트명", "Hostname"), "kiki.local");
    ui->admin_password = form_entry(GTK_GRID(grid), 2, L("관리자 암호", "Administrator password"), "");
    ui->admin_password_confirm = form_entry(GTK_GRID(grid), 3, L("암호 확인", "Confirm password"), "");
    gtk_entry_set_visibility(ui->admin_password, FALSE);
    gtk_entry_set_visibility(ui->admin_password_confirm, FALSE);
    gtk_entry_set_input_purpose(ui->admin_password, GTK_INPUT_PURPOSE_PASSWORD);
    gtk_entry_set_input_purpose(ui->admin_password_confirm, GTK_INPUT_PURPOSE_PASSWORD);
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "account", L("계정", "Account"));

    page = page_new(L("패키지 소스", "Package source"), L("로컬 미디어, 원격 저장소 또는 오프라인 미러를 선택합니다.", "Choose local media, a remote repository, or an offline mirror."));
    grid = form_new();
    ui->source_type = form_dropdown(GTK_GRID(grid), 0, L("소스", "Source"), source_types);
    ui->source_location = form_entry(GTK_GRID(grid), 1, L("위치", "Location"), "/run/install-media");
    ui->verify_key = form_entry(GTK_GRID(grid), 2, L("검증 공개키", "Verification public key"), "");
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "source", L("패키지 소스", "Package source"));

    page = page_new(L("프로필 및 AI", "Profile and AI"), L("desktop-gnome은 기존 GNOME 50 · GDM · Wayland 환경을 설치합니다. GNOME 패키지가 포함된 미디어가 필요합니다.", "desktop-gnome installs the existing GNOME 50, GDM and Wayland environment. Media must include its desktop packages."));
    grid = form_new();
    ui->profile = form_dropdown(GTK_GRID(grid), 0, L("설치 환경", "Installation environment"), ui_korean ? profile_labels_ko : profile_labels_en);
    const char *catalog_path = g_getenv("KIKI_INSTALLER_MEDIA_CATALOG");
    if (!catalog_path) catalog_path = "/etc/kiki/installer-media.ini";
    if (g_file_test(catalog_path, G_FILE_TEST_EXISTS)) {
        ui->media_catalog = g_key_file_new();
        if (!g_key_file_load_from_file(ui->media_catalog, catalog_path, G_KEY_FILE_NONE, NULL)) {
            /* A malformed media catalogue must not silently permit all profiles. */
            g_key_file_remove_group(ui->media_catalog, "media", NULL);
        }
    }
    GtkListItemFactory *profile_factory = gtk_signal_list_item_factory_new();
    g_signal_connect(profile_factory, "setup", G_CALLBACK(profile_option_setup), ui);
    g_signal_connect(profile_factory, "bind", G_CALLBACK(profile_option_bind), ui);
    gtk_drop_down_set_list_factory(ui->profile, profile_factory);
    g_object_unref(profile_factory);
    ui->runtime = form_dropdown(GTK_GRID(grid), 1, L("런타임", "Runtime"), runtimes);
    ui->ai_mode = form_dropdown(GTK_GRID(grid), 2, "AI", ai_modes);
    ui->ai_endpoint = form_entry(GTK_GRID(grid), 3, L("AI 엔드포인트", "AI endpoint"), "http://127.0.0.1:8080/v1/chat/completions");
    ui->package_groups = form_entry(GTK_GRID(grid), 4, L("추가 구성", "Additional packages"), "");
    gtk_widget_set_visible(GTK_WIDGET(ui->package_groups), FALSE);
    ui->profile_status = GTK_LABEL(gtk_label_new(NULL));
    gtk_label_set_wrap(ui->profile_status, TRUE);
    gtk_label_set_xalign(ui->profile_status, 0);
    gtk_grid_attach(GTK_GRID(grid), GTK_WIDGET(ui->profile_status), 0, 5, 2, 1);
    GtkWidget *extras = gtk_flow_box_new();
    gtk_flow_box_set_selection_mode(GTK_FLOW_BOX(extras), GTK_SELECTION_NONE);
    gtk_flow_box_set_max_children_per_line(GTK_FLOW_BOX(extras), 2);
    for (guint i = 0; extra_group_ids[i]; i++) {
        ui->extra_groups[i] = GTK_CHECK_BUTTON(gtk_check_button_new_with_label(ui_korean ? extra_group_labels_ko[i] : extra_group_labels_en[i]));
        gboolean available = media_available(ui, "group", extra_group_ids[i]);
        gtk_widget_set_sensitive(GTK_WIDGET(ui->extra_groups[i]), available);
        if (!available) gtk_widget_set_tooltip_text(GTK_WIDGET(ui->extra_groups[i]), L("현재 미디어에 필요한 패키지가 없습니다.", "Required packages are not on this media."));
        g_signal_connect(ui->extra_groups[i], "toggled", G_CALLBACK(extra_groups_changed), ui);
        gtk_flow_box_insert(GTK_FLOW_BOX(extras), GTK_WIDGET(ui->extra_groups[i]), -1);
    }
    gtk_grid_attach(GTK_GRID(grid), extras, 0, 6, 2, 1);
    g_signal_connect(ui->profile, "notify::selected", G_CALLBACK(desktop_profile_selected), ui);
    if (ui->media_catalog) {
        for (guint i = 0; profiles[i]; i++) {
            if (media_available(ui, "profile", profiles[i])) { gtk_drop_down_set_selected(ui->profile, i); break; }
        }
    }
    desktop_profile_selected(NULL, NULL, ui);
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "profile", L("프로필 및 AI", "Profile and AI"));

    page = page_new(L("검토", "Review"), L("대상 디스크와 계획을 확인하세요. 데이터 삭제에 동의한 뒤 설치를 시작할 수 있습니다.", "Review the target disk and plan. Confirm data erasure before installation."));
    GtkWidget *scroller = gtk_scrolled_window_new();
    gtk_widget_set_vexpand(scroller, TRUE);
    GtkWidget *text = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(text), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(text), GTK_WRAP_WORD_CHAR);
    ui->review = gtk_text_view_get_buffer(GTK_TEXT_VIEW(text));
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroller), text);
    gtk_box_append(GTK_BOX(page), scroller);
    ui->destructive_confirm = GTK_CHECK_BUTTON(gtk_check_button_new_with_label(L("선택한 디스크의 모든 데이터가 삭제되는 것에 동의합니다.", "I agree that all data on the selected disk will be erased.")));
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->destructive_confirm));
    g_signal_connect(ui->disk, "changed", G_CALLBACK(target_disk_changed), ui);
    GtkWidget *actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *review_button = gtk_button_new_with_label(L("계획 새로고침", "Refresh plan"));
    GtkWidget *write_button = gtk_button_new_with_label(L("설치 계획 저장", "Save plan"));
    GtkWidget *install_button = gtk_button_new_with_label(L("디스크 지우고 설치", "Erase disk and install"));
    ui->install_button = GTK_BUTTON(install_button);
    gtk_widget_set_sensitive(install_button, FALSE);
    g_signal_connect(ui->destructive_confirm, "toggled", G_CALLBACK(consent_changed), ui);
    gtk_widget_add_css_class(install_button, "destructive-action");
    gtk_box_append(GTK_BOX(actions), review_button);
    gtk_box_append(GTK_BOX(actions), write_button);
    gtk_box_append(GTK_BOX(actions), install_button);
    gtk_box_append(GTK_BOX(page), actions);
    g_signal_connect(review_button, "clicked", G_CALLBACK(review_clicked), ui);
    g_signal_connect(write_button, "clicked", G_CALLBACK(write_plan), ui);
    g_signal_connect(install_button, "clicked", G_CALLBACK(start_install), ui);
    stack_page(GTK_STACK(stack), page, "review", L("검토 및 설치", "Review and install"));

    page = page_new(L("설치 진행", "Installation progress"), L("설치 중에는 시스템을 끄거나 대상 디스크를 분리하지 마세요.", "Do not power off or disconnect the target disk during installation."));
    ui->progress_phase = GTK_LABEL(gtk_label_new(L("설치 대기", "Waiting to install")));
    gtk_widget_add_css_class(GTK_WIDGET(ui->progress_phase), "title-2");
    gtk_label_set_xalign(ui->progress_phase, 0.0f);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->progress_phase));
    ui->progress = GTK_PROGRESS_BAR(gtk_progress_bar_new());
    gtk_progress_bar_set_show_text(ui->progress, TRUE);
    gtk_progress_bar_set_text(ui->progress, "0%");
    gtk_widget_set_hexpand(GTK_WIDGET(ui->progress), TRUE);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->progress));
    ui->package_count = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_xalign(ui->package_count, 0.0f);
    gtk_widget_add_css_class(GTK_WIDGET(ui->package_count), "package-count");
    gtk_widget_set_visible(GTK_WIDGET(ui->package_count), FALSE);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->package_count));
    ui->progress_message = GTK_LABEL(gtk_label_new(L("설치 시작 전입니다.", "Installation has not started.")));
    gtk_label_set_wrap(ui->progress_message, TRUE);
    gtk_label_set_xalign(ui->progress_message, 0.0f);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->progress_message));
    scroller = gtk_scrolled_window_new();
    gtk_widget_set_vexpand(scroller, TRUE);
    text = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(text), FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(text), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(text), GTK_WRAP_WORD_CHAR);
    ui->progress_log = gtk_text_view_get_buffer(GTK_TEXT_VIEW(text));
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroller), text);
    gtk_box_append(GTK_BOX(page), scroller);
    ui->reboot_button = GTK_BUTTON(gtk_button_new_with_label(L("확인 후 재부팅", "Confirm and reboot")));
    gtk_widget_add_css_class(GTK_WIDGET(ui->reboot_button), "suggested-action");
    gtk_widget_set_halign(GTK_WIDGET(ui->reboot_button), GTK_ALIGN_END);
    gtk_widget_set_visible(GTK_WIDGET(ui->reboot_button), FALSE);
    g_signal_connect(ui->reboot_button, "clicked", G_CALLBACK(request_reboot), ui);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->reboot_button));
    GtkStackPage *progress_page = stack_page(GTK_STACK(stack), page, "progress", L("설치 진행", "Progress"));
    gtk_stack_page_set_visible(progress_page, FALSE);

    GtkWidget *footer = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    ui->footer = footer;
    gtk_widget_add_css_class(footer, "kiki-footer");
    ui->status = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_wrap(ui->status, TRUE);
    gtk_label_set_lines(ui->status, 3);
    gtk_label_set_xalign(ui->status, 0);
    gtk_widget_set_visible(GTK_WIDGET(ui->status), FALSE);
    g_signal_connect(ui->status, "notify::label", G_CALLBACK(status_changed), NULL);
    gtk_box_append(GTK_BOX(footer), GTK_WIDGET(ui->status));
    ui->navigation = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 10);
    ui->step_label = GTK_LABEL(gtk_label_new(""));
    gtk_widget_add_css_class(GTK_WIDGET(ui->step_label), "dim-label");
    gtk_label_set_xalign(ui->step_label, 0);
    gtk_widget_set_hexpand(GTK_WIDGET(ui->step_label), TRUE);
    gtk_box_append(GTK_BOX(ui->navigation), GTK_WIDGET(ui->step_label));
    ui->back_button = GTK_BUTTON(gtk_button_new_with_label(L("이전", "Back")));
    ui->next_button = GTK_BUTTON(gtk_button_new_with_label(L("설정 시작", "Get started")));
    gtk_widget_add_css_class(GTK_WIDGET(ui->next_button), "suggested-action");
    gtk_box_append(GTK_BOX(ui->navigation), GTK_WIDGET(ui->back_button));
    gtk_box_append(GTK_BOX(ui->navigation), GTK_WIDGET(ui->next_button));
    g_signal_connect(ui->back_button, "clicked", G_CALLBACK(navigate), ui);
    g_signal_connect(ui->next_button, "clicked", G_CALLBACK(navigate), ui);
    gtk_box_append(GTK_BOX(footer), ui->navigation);
    gtk_box_append(GTK_BOX(root), footer);
    g_signal_connect(stack, "notify::visible-child-name", G_CALLBACK(navigation_changed), ui);
    g_signal_connect(ui->window, "close-request", G_CALLBACK(installer_close_requested), ui);
    navigation_changed(NULL, NULL, ui);

    update_review(ui);
    gtk_window_set_child(ui->window, root);
    g_object_set_data_full(G_OBJECT(ui->window), "kiki-ui", ui, installer_ui_free);
    gtk_window_present(ui->window);
}

static void choose_ui_language(GtkButton *button, gpointer data) {
    GtkApplication *application = GTK_APPLICATION(data);
    ui_korean = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(button), "kiki-language")) != 0;
    GtkWindow *chooser = GTK_WINDOW(gtk_widget_get_root(GTK_WIDGET(button)));
    build_installer_ui(application);
    gtk_window_destroy(chooser);
}

static void activate(GtkApplication *application, gpointer data) {
    (void)data;
    GtkWindow *chooser = GTK_WINDOW(gtk_application_window_new(application));
    load_css();
    gtk_window_set_title(chooser, "KIKI OS — Language / 언어");
    gtk_window_set_default_size(chooser, 540, 280);
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 16);
    gtk_widget_set_margin_top(box, 28);
    gtk_widget_set_margin_bottom(box, 28);
    gtk_widget_set_margin_start(box, 28);
    gtk_widget_set_margin_end(box, 28);
    gtk_box_append(GTK_BOX(box), gtk_label_new("Installer language / 인스톨러 언어"));
    gtk_box_append(GTK_BOX(box), gtk_label_new("The installed OS language is selected separately. / 설치할 OS의 언어는 별도로 선택합니다."));
    GtkWidget *english = gtk_button_new_with_label("English");
    GtkWidget *korean = gtk_button_new_with_label("한국어");
    gtk_widget_add_css_class(english, "suggested-action");
    g_object_set_data(G_OBJECT(english), "kiki-language", GINT_TO_POINTER(0));
    g_object_set_data(G_OBJECT(korean), "kiki-language", GINT_TO_POINTER(1));
    g_signal_connect(english, "clicked", G_CALLBACK(choose_ui_language), application);
    g_signal_connect(korean, "clicked", G_CALLBACK(choose_ui_language), application);
    gtk_box_append(GTK_BOX(box), english);
    gtk_box_append(GTK_BOX(box), korean);
    gtk_window_set_child(chooser, box);
    gtk_window_present(chooser);
}

int main(int argc, char **argv) {
    g_autoptr(GtkApplication) application = gtk_application_new(
        "io.kiki.Installer", G_APPLICATION_FLAGS_NONE);
    g_signal_connect(application, "activate", G_CALLBACK(activate), NULL);
    return g_application_run(G_APPLICATION(application), argc, argv);
}
