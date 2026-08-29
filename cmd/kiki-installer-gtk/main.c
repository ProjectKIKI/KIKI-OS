#include <gtk/gtk.h>
#include <glib/gstdio.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

#define GUI_INSTALL_REQUEST_PATH "/run/kiki/gui-install.request"
#define GUI_INSTALL_REQUEST_TMP_PATH "/run/kiki/gui-install.request.tmp"
#define GUI_INSTALL_PROGRESS_PATH "/run/kiki/install-progress.state"
#define GUI_REBOOT_REQUEST_PATH "/run/kiki/gui-reboot.request"
#define GUI_REBOOT_REQUEST_TMP_PATH "/run/kiki/gui-reboot.request.tmp"

typedef struct {
    GtkWindow *window;
    GtkEntry *plan_path;
    GtkEntry *disk;
    GtkEntry *hostname;
    GtkEntry *admin_user;
    GtkEntry *admin_password;
    GtkEntry *admin_password_confirm;
    GtkEntry *destructive_confirm;
    GtkEntry *locale;
    GtkEntry *keymap;
    GtkEntry *timezone;
    GtkEntry *network_interface;
    GtkEntry *address;
    GtkEntry *gateway;
    GtkEntry *dns;
    GtkEntry *source_location;
    GtkEntry *verify_key;
    GtkEntry *ai_endpoint;
    GtkEntry *package_groups;
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
    GtkProgressBar *progress;
    GtkLabel *progress_phase;
    GtkLabel *package_count;
    GtkLabel *progress_message;
    GtkTextBuffer *progress_log;
    GtkButton *reboot_button;
    char *last_progress_message;
    guint progress_source;
    gboolean install_started;
    gboolean install_complete;
} InstallerUI;

static const char *install_modes[] = {"guided", "unattended", NULL};
static const char *swap_modes[] = {"auto", "on", "off", NULL};
static const char *network_modes[] = {"dhcp", "static", "off", NULL};
static const char *source_types[] = {"local", "remote", "mirror", NULL};
static const char *profiles[] = {
    "server-core",
    "minimal-systemd",
    "kiki-kube-bootstrap",
    "kiki-kube-bootstrap-containerd",
    "kiki-kube-control",
    "kiki-kube-control-containerd",
    "kiki-kube-compute",
    "kiki-kube-compute-containerd",
    NULL,
};
static const char *runtimes[] = {"profile-default", "none", "crio", "containerd", NULL};
static const char *ai_modes[] = {"local", "remote", "off", NULL};

static const char *dropdown_text(GtkDropDown *dropdown) {
    GtkStringObject *item = GTK_STRING_OBJECT(gtk_drop_down_get_selected_item(dropdown));
    return item ? gtk_string_object_get_string(item) : "";
}

static GtkWidget *page_new(const char *title, const char *description) {
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
    gtk_widget_add_css_class(box, "kiki-page");
    GtkWidget *heading = gtk_label_new(title);
    gtk_widget_add_css_class(heading, "title-2");
    gtk_label_set_xalign(GTK_LABEL(heading), 0.0f);
    gtk_box_append(GTK_BOX(box), heading);
    GtkWidget *body = gtk_label_new(description);
    gtk_widget_add_css_class(body, "dim-label");
    gtk_label_set_wrap(GTK_LABEL(body), TRUE);
    gtk_label_set_xalign(GTK_LABEL(body), 0.0f);
    gtk_box_append(GTK_BOX(box), body);
    return box;
}

static GtkWidget *form_new(void) {
    GtkWidget *grid = gtk_grid_new();
    gtk_grid_set_row_spacing(GTK_GRID(grid), 10);
    gtk_grid_set_column_spacing(GTK_GRID(grid), 16);
    gtk_widget_set_hexpand(grid, TRUE);
    return grid;
}

static GtkEntry *form_entry(GtkGrid *grid, int row, const char *label, const char *value) {
    GtkWidget *name = gtk_label_new(label);
    gtk_label_set_xalign(GTK_LABEL(name), 1.0f);
    GtkWidget *entry = gtk_entry_new();
    gtk_editable_set_text(GTK_EDITABLE(entry), value);
    gtk_widget_set_hexpand(entry, TRUE);
    gtk_grid_attach(grid, name, 0, row, 1, 1);
    gtk_grid_attach(grid, entry, 1, row, 1, 1);
    return GTK_ENTRY(entry);
}

static GtkDropDown *form_dropdown(GtkGrid *grid, int row, const char *label, const char *const *items) {
    GtkWidget *name = gtk_label_new(label);
    gtk_label_set_xalign(GTK_LABEL(name), 1.0f);
    GtkWidget *dropdown = gtk_drop_down_new_from_strings(items);
    gtk_widget_set_hexpand(dropdown, TRUE);
    gtk_grid_attach(grid, name, 0, row, 1, 1);
    gtk_grid_attach(grid, dropdown, 1, row, 1, 1);
    return GTK_DROP_DOWN(dropdown);
}

static void stack_page(GtkStack *stack, GtkWidget *page, const char *name, const char *title) {
    gtk_stack_add_titled(stack, page, name, title);
}

static void update_review(InstallerUI *ui) {
    const char *network = dropdown_text(ui->network_mode);
    const char *source = dropdown_text(ui->source_type);
    const char *ai = dropdown_text(ui->ai_mode);
    g_autofree char *expected = g_strdup_printf(
        "INSTALL %s", gtk_editable_get_text(GTK_EDITABLE(ui->disk)));
    if (ui->destructive_confirm)
        gtk_entry_set_placeholder_text(ui->destructive_confirm, expected);
    g_autofree char *text = g_strdup_printf(
        "설치 모드: %s\n"
        "대상 디스크: %s (swap: %s)\n"
        "언어: %s / %s / %s\n"
        "네트워크: %s (%s)\n"
        "계정: %s / %s\n"
        "패키지 소스: %s / %s\n"
        "프로필: %s\n"
        "추가 패키지 그룹: %s\n"
        "컨테이너 런타임: %s\n"
        "AI 에이전트: %s / 명령 승인 필수\n"
        "설치 확인 문자열: %s\n"
        "계획 파일: %s\n\n"
        "주의: auto-whole-disk 설치는 선택한 디스크의 기존 데이터를 삭제합니다.\n"
        "GTK 화면과 TUI/무인 설치는 동일한 InstallPlan 생성기를 사용합니다.",
        dropdown_text(ui->install_mode),
        gtk_editable_get_text(GTK_EDITABLE(ui->disk)), dropdown_text(ui->swap_mode),
        gtk_editable_get_text(GTK_EDITABLE(ui->locale)),
        gtk_editable_get_text(GTK_EDITABLE(ui->keymap)),
        gtk_editable_get_text(GTK_EDITABLE(ui->timezone)),
        network, gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)),
        gtk_editable_get_text(GTK_EDITABLE(ui->admin_user)),
        gtk_editable_get_text(GTK_EDITABLE(ui->hostname)),
        source, gtk_editable_get_text(GTK_EDITABLE(ui->source_location)),
        dropdown_text(ui->profile), gtk_editable_get_text(GTK_EDITABLE(ui->package_groups)),
        dropdown_text(ui->runtime), ai, expected,
        gtk_editable_get_text(GTK_EDITABLE(ui->plan_path)));
    gtk_text_buffer_set_text(ui->review, text, -1);
}

static void add_arg(GPtrArray *args, const char *name, const char *value) {
    g_ptr_array_add(args, (gpointer)name);
    g_ptr_array_add(args, (gpointer)(value ? value : ""));
}

static gboolean validate_gui(InstallerUI *ui, GError **error) {
    const char *disk = gtk_editable_get_text(GTK_EDITABLE(ui->disk));
    gboolean partition = g_regex_match_simple(
        "^/dev/((sd|vd|xvd|hd)[a-z]+[0-9]+|(nvme[0-9]+n[0-9]+|mmcblk[0-9]+|md[0-9]+)p[0-9]+)$",
        disk, 0, 0);
    if (!g_str_has_prefix(disk, "/dev/") || disk[5] == '\0' || partition) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "대상은 /dev/sda 또는 /dev/nvme0n1 같은 전체 디스크여야 합니다.");
        return FALSE;
    }
    if (g_str_equal(dropdown_text(ui->network_mode), "static") &&
        gtk_editable_get_text(GTK_EDITABLE(ui->address))[0] == '\0') {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "고정 네트워크에는 CIDR 주소가 필요합니다.");
        return FALSE;
    }
    if (g_str_equal(dropdown_text(ui->source_type), "remote") &&
        gtk_editable_get_text(GTK_EDITABLE(ui->verify_key))[0] == '\0') {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "원격 저장소에는 검증 공개키를 지정해야 합니다.");
        return FALSE;
    }
    if (g_str_equal(dropdown_text(ui->ai_mode), "remote") &&
        gtk_editable_get_text(GTK_EDITABLE(ui->ai_endpoint))[0] == '\0') {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "원격 AI 모드에는 OpenAI 호환 엔드포인트가 필요합니다.");
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
    add_arg(args, "--profile", dropdown_text(ui->profile));
    if (gtk_editable_get_text(GTK_EDITABLE(ui->package_groups))[0] != '\0')
        add_arg(args, "--groups", gtk_editable_get_text(GTK_EDITABLE(ui->package_groups)));
    add_arg(args, "--disk", gtk_editable_get_text(GTK_EDITABLE(ui->disk)));
    add_arg(args, "--swap", dropdown_text(ui->swap_mode));
    add_arg(args, "--hostname", gtk_editable_get_text(GTK_EDITABLE(ui->hostname)));
    add_arg(args, "--user", gtk_editable_get_text(GTK_EDITABLE(ui->admin_user)));
    add_arg(args, "--locale", gtk_editable_get_text(GTK_EDITABLE(ui->locale)));
    add_arg(args, "--keymap", gtk_editable_get_text(GTK_EDITABLE(ui->keymap)));
    add_arg(args, "--timezone", gtk_editable_get_text(GTK_EDITABLE(ui->timezone)));
    add_arg(args, "--network", dropdown_text(ui->network_mode));
    add_arg(args, "--network-interface", gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)));
    add_arg(args, "--address", gtk_editable_get_text(GTK_EDITABLE(ui->address)));
    add_arg(args, "--gateway", gtk_editable_get_text(GTK_EDITABLE(ui->gateway)));
    add_arg(args, "--dns", gtk_editable_get_text(GTK_EDITABLE(ui->dns)));
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
        gtk_label_set_text(ui->status, *error ? (*error)->message : (stderr_text && *stderr_text ? stderr_text : "계획 생성 실패"));
        gtk_widget_add_css_class(GTK_WIDGET(ui->status), "error");
        return FALSE;
    }
    gtk_widget_remove_css_class(GTK_WIDGET(ui->status), "error");
    gtk_label_set_text(ui->status, stdout_text && *stdout_text ? stdout_text : "설치 계획을 저장했습니다.");
    update_review(ui);
    return TRUE;
}

static void write_plan(GtkButton *button, gpointer data) {
    (void)button;
    InstallerUI *ui = data;
    g_autoptr(GError) error = NULL;
    write_plan_file(ui, &error);
}

static gboolean append_request_field(GString *request, const char *key, const char *value, GError **error) {
    value = value ? value : "";
    if (strchr(value, '\n') || strchr(value, '\r')) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "%s 값에는 줄바꿈을 사용할 수 없습니다.", key);
        return FALSE;
    }
    g_string_append_printf(request, "%s=%s\n", key, value);
    return TRUE;
}

static gboolean write_install_request(InstallerUI *ui, GError **error) {
    const char *password = gtk_editable_get_text(GTK_EDITABLE(ui->admin_password));
    const char *password_confirm = gtk_editable_get_text(GTK_EDITABLE(ui->admin_password_confirm));
    const char *destructive_confirm = gtk_editable_get_text(GTK_EDITABLE(ui->destructive_confirm));
    const char *disk = gtk_editable_get_text(GTK_EDITABLE(ui->disk));
    g_autofree char *expected = g_strdup_printf("INSTALL %s", disk);
    gsize password_bytes = strlen(password);
    if (password_bytes < 8 || password_bytes > 95) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "관리자 암호는 UTF-8 기준 8~95바이트로 입력하세요.");
        return FALSE;
    }
    if (!g_str_equal(password, password_confirm)) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "관리자 암호 확인이 일치하지 않습니다.");
        return FALSE;
    }
    if (!g_str_equal(destructive_confirm, expected)) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "디스크 삭제 확인란에 '%s'를 정확히 입력하세요.", expected);
        return FALSE;
    }
    if (!g_str_equal(dropdown_text(ui->source_type), "local")) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_NOT_SUPPORTED,
                    "현재 ISO 설치 실행은 로컬 설치 미디어만 지원합니다.");
        return FALSE;
    }
    if (g_str_has_prefix(dropdown_text(ui->profile), "kiki-kube-") &&
        g_str_equal(dropdown_text(ui->swap_mode), "on")) {
        g_set_error(error, G_IO_ERROR, G_IO_ERROR_INVALID_ARGUMENT,
                    "Kubernetes 프로필은 swap을 켠 상태로 설치할 수 없습니다.");
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
    REQUEST_FIELD("confirmed", destructive_confirm);
    REQUEST_FIELD("locale", gtk_editable_get_text(GTK_EDITABLE(ui->locale)));
    REQUEST_FIELD("keymap", gtk_editable_get_text(GTK_EDITABLE(ui->keymap)));
    REQUEST_FIELD("timezone", gtk_editable_get_text(GTK_EDITABLE(ui->timezone)));
    REQUEST_FIELD("network", dropdown_text(ui->network_mode));
    REQUEST_FIELD("network_interface", gtk_editable_get_text(GTK_EDITABLE(ui->network_interface)));
    REQUEST_FIELD("address", gtk_editable_get_text(GTK_EDITABLE(ui->address)));
    REQUEST_FIELD("gateway", gtk_editable_get_text(GTK_EDITABLE(ui->gateway)));
    REQUEST_FIELD("dns", gtk_editable_get_text(GTK_EDITABLE(ui->dns)));
    REQUEST_FIELD("profile", dropdown_text(ui->profile));
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
    int request_fd = g_open(GUI_INSTALL_REQUEST_TMP_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (request_fd < 0) {
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(errno),
                    "설치 요청 파일을 열 수 없습니다: %s", g_strerror(errno));
        return FALSE;
    }
    if (fchmod(request_fd, 0600) != 0) {
        int saved_errno = errno;
        close(request_fd);
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(saved_errno),
                    "설치 요청 파일 권한을 설정할 수 없습니다: %s", g_strerror(saved_errno));
        return FALSE;
    }
    gsize written = 0;
    while (written < request->len) {
        ssize_t amount = write(request_fd, request->str + written, request->len - written);
        if (amount < 0 && errno == EINTR) continue;
        if (amount <= 0) {
            int saved_errno = errno;
            close(request_fd);
            g_set_error(error, G_IO_ERROR, g_io_error_from_errno(saved_errno),
                        "설치 요청 파일을 쓸 수 없습니다: %s", g_strerror(saved_errno));
            return FALSE;
        }
        written += (gsize)amount;
    }
    if (close(request_fd) != 0) {
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(errno),
                    "설치 요청 파일을 닫을 수 없습니다: %s", g_strerror(errno));
        return FALSE;
    }
    if (g_rename(GUI_INSTALL_REQUEST_TMP_PATH, GUI_INSTALL_REQUEST_PATH) != 0) {
        int saved_errno = errno;
        g_unlink(GUI_INSTALL_REQUEST_TMP_PATH);
        g_set_error(error, G_IO_ERROR, g_io_error_from_errno(saved_errno),
                    "설치 요청을 전달할 수 없습니다: %s", g_strerror(saved_errno));
        return FALSE;
    }
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

static void append_progress_log(InstallerUI *ui, const char *message) {
    if (!message || !*message || g_strcmp0(message, ui->last_progress_message) == 0) return;
    GtkTextIter end;
    gtk_text_buffer_get_end_iter(ui->progress_log, &end);
    gtk_text_buffer_insert(ui->progress_log, &end, message, -1);
    gtk_text_buffer_insert(ui->progress_log, &end, "\n", 1);
    g_free(ui->last_progress_message);
    ui->last_progress_message = g_strdup(message);
}

static gboolean poll_install_progress(gpointer data) {
    InstallerUI *ui = data;
    g_autofree char *contents = NULL;
    gsize length = 0;
    if (!g_file_get_contents(GUI_INSTALL_PROGRESS_PATH, &contents, &length, NULL))
        return G_SOURCE_CONTINUE;

    g_autofree char *state = progress_value(contents, "state");
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
    gtk_label_set_text(ui->progress_phase, phase && *phase ? phase : "설치 준비");
    if (packages_total > 0) {
        g_autofree char *package_text = NULL;
        if (packages_installed < packages_total && package && *package) {
            package_text = g_strdup_printf(
                "패키지 설치 완료: %" G_GINT64_FORMAT " / %" G_GINT64_FORMAT "개 · 현재: %s",
                packages_installed, packages_total, package);
        } else {
            package_text = g_strdup_printf(
                "패키지 설치 완료: %" G_GINT64_FORMAT " / %" G_GINT64_FORMAT "개",
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
        gtk_label_set_text(ui->progress_phase, "설치 완료");
        gtk_label_set_text(ui->progress_message,
                           "설치가 완료되었습니다. ISO를 분리한 뒤 아래 버튼을 눌러 재부팅하세요.");
        gtk_widget_set_visible(GTK_WIDGET(ui->reboot_button), TRUE);
        gtk_widget_set_sensitive(GTK_WIDGET(ui->reboot_button), TRUE);
        ui->progress_source = 0;
        return G_SOURCE_REMOVE;
    }
    if (g_str_equal(state, "failed")) {
        gtk_widget_add_css_class(GTK_WIDGET(ui->progress_phase), "error");
        gtk_label_set_text(ui->progress_phase, "설치 실패");
        gtk_label_set_text(ui->progress_message,
                           message && *message ? message : "설치에 실패했습니다. 콘솔 로그를 확인하세요.");
        gtk_button_set_label(ui->reboot_button, "설치기 종료");
        gtk_widget_set_visible(GTK_WIDGET(ui->reboot_button), TRUE);
        gtk_widget_set_sensitive(GTK_WIDGET(ui->reboot_button), TRUE);
        gtk_window_set_deletable(ui->window, TRUE);
        ui->progress_source = 0;
        return G_SOURCE_REMOVE;
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
                           error ? error->message : "재부팅 요청을 전달할 수 없습니다.");
        gtk_widget_add_css_class(GTK_WIDGET(ui->progress_message), "error");
        g_unlink(GUI_REBOOT_REQUEST_TMP_PATH);
        return;
    }
    gtk_widget_set_sensitive(GTK_WIDGET(button), FALSE);
    gtk_button_set_label(button, "재부팅 중…");
    gtk_label_set_text(ui->progress_message, "재부팅을 요청했습니다. 잠시 기다려 주세요.");
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
    gtk_label_set_text(ui->status, "관리자 암호와 디스크 삭제 확인이 완료되었습니다. 설치를 시작합니다.");
    gtk_editable_set_text(GTK_EDITABLE(ui->admin_password), "");
    gtk_editable_set_text(GTK_EDITABLE(ui->admin_password_confirm), "");
    ui->install_started = TRUE;
    gtk_window_set_deletable(ui->window, FALSE);
    gtk_widget_set_sensitive(ui->sidebar, FALSE);
    gtk_stack_set_visible_child_name(ui->stack, "progress");
    gtk_progress_bar_set_fraction(ui->progress, 0.01);
    gtk_progress_bar_set_text(ui->progress, "1%");
    gtk_label_set_text(ui->progress_phase, "설치 요청 전달");
    gtk_label_set_text(ui->progress_message, "설치 백엔드가 요청을 확인하고 있습니다.");
    append_progress_log(ui, "설치 요청을 안전하게 전달했습니다.");
    if (!ui->progress_source)
        ui->progress_source = g_timeout_add(200, poll_install_progress, ui);
}

static void review_clicked(GtkButton *button, gpointer data) {
    (void)button;
    update_review(data);
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

static void activate(GtkApplication *application, gpointer data) {
    (void)data;
    InstallerUI *ui = g_new0(InstallerUI, 1);
    load_css();

    ui->window = GTK_WINDOW(gtk_application_window_new(application));
    gtk_window_set_title(ui->window, "KIKI OS 설치기");
    gtk_window_set_default_size(ui->window, 980, 680);

    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkWidget *header = gtk_header_bar_new();
    GtkWidget *title = gtk_label_new("KIKI OS Installer");
    gtk_widget_add_css_class(title, "title-3");
    gtk_header_bar_set_title_widget(GTK_HEADER_BAR(header), title);
    gtk_box_append(GTK_BOX(root), header);

    GtkWidget *content = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
    GtkWidget *stack = gtk_stack_new();
    ui->stack = GTK_STACK(stack);
    gtk_stack_set_transition_type(GTK_STACK(stack), GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    gtk_widget_set_hexpand(stack, TRUE);
    gtk_widget_set_vexpand(stack, TRUE);
    GtkWidget *sidebar = gtk_stack_sidebar_new();
    ui->sidebar = sidebar;
    gtk_stack_sidebar_set_stack(GTK_STACK_SIDEBAR(sidebar), GTK_STACK(stack));
    gtk_widget_add_css_class(sidebar, "kiki-sidebar");
    gtk_box_append(GTK_BOX(content), sidebar);
    gtk_box_append(GTK_BOX(content), stack);
    gtk_box_append(GTK_BOX(root), content);

    GtkWidget *page = page_new("시작", "GTK 화면, TUI, CLI 및 무인 설치가 하나의 InstallPlan 계약을 공유합니다.");
    GtkWidget *grid = form_new();
    ui->install_mode = form_dropdown(GTK_GRID(grid), 0, "설치 모드", install_modes);
    ui->plan_path = form_entry(GTK_GRID(grid), 1, "계획 파일", "/run/kiki/install-plan.yaml");
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "welcome", "시작");

    page = page_new("언어 및 지역", "설치할 시스템의 로케일, 콘솔 키맵과 시간대를 설정합니다.");
    grid = form_new();
    ui->locale = form_entry(GTK_GRID(grid), 0, "로케일", "ko_KR.UTF-8");
    ui->keymap = form_entry(GTK_GRID(grid), 1, "키맵", "kr");
    ui->timezone = form_entry(GTK_GRID(grid), 2, "시간대", "Asia/Seoul");
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "localization", "언어 및 지역");

    page = page_new("디스크", "자동 설치는 선택한 전체 디스크를 다시 파티셔닝합니다.");
    grid = form_new();
    ui->disk = form_entry(GTK_GRID(grid), 0, "대상 디스크", "/dev/sda");
    ui->swap_mode = form_dropdown(GTK_GRID(grid), 1, "Swap", swap_modes);
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "disk", "디스크");

    page = page_new("네트워크", "systemd-networkd에 적용할 초기 네트워크 설정입니다.");
    grid = form_new();
    ui->network_mode = form_dropdown(GTK_GRID(grid), 0, "모드", network_modes);
    ui->network_interface = form_entry(GTK_GRID(grid), 1, "인터페이스", "en* eth*");
    ui->address = form_entry(GTK_GRID(grid), 2, "주소/CIDR", "");
    ui->gateway = form_entry(GTK_GRID(grid), 3, "게이트웨이", "");
    ui->dns = form_entry(GTK_GRID(grid), 4, "DNS", "");
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "network", "네트워크");

    page = page_new("계정", "초기 관리자, 시스템 호스트명과 암호를 설정합니다. 암호는 InstallPlan에 저장하지 않습니다.");
    grid = form_new();
    ui->admin_user = form_entry(GTK_GRID(grid), 0, "관리자", "kiki");
    ui->hostname = form_entry(GTK_GRID(grid), 1, "호스트명", "kiki.local");
    ui->admin_password = form_entry(GTK_GRID(grid), 2, "관리자 암호", "");
    ui->admin_password_confirm = form_entry(GTK_GRID(grid), 3, "암호 확인", "");
    gtk_entry_set_visibility(ui->admin_password, FALSE);
    gtk_entry_set_visibility(ui->admin_password_confirm, FALSE);
    gtk_entry_set_input_purpose(ui->admin_password, GTK_INPUT_PURPOSE_PASSWORD);
    gtk_entry_set_input_purpose(ui->admin_password_confirm, GTK_INPUT_PURPOSE_PASSWORD);
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "account", "계정");

    page = page_new("패키지 소스", "로컬 미디어, 원격 저장소 또는 오프라인 미러를 선택합니다.");
    grid = form_new();
    ui->source_type = form_dropdown(GTK_GRID(grid), 0, "소스", source_types);
    ui->source_location = form_entry(GTK_GRID(grid), 1, "위치", "/run/install-media");
    ui->verify_key = form_entry(GTK_GRID(grid), 2, "검증 공개키", "");
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "source", "패키지 소스");

    page = page_new("프로필 및 AI", "서버 역할, 컨테이너 런타임과 AI 관리 콘솔을 구성합니다.");
    grid = form_new();
    ui->profile = form_dropdown(GTK_GRID(grid), 0, "프로필", profiles);
    ui->runtime = form_dropdown(GTK_GRID(grid), 1, "런타임", runtimes);
    ui->ai_mode = form_dropdown(GTK_GRID(grid), 2, "AI", ai_modes);
    ui->ai_endpoint = form_entry(GTK_GRID(grid), 3, "AI 엔드포인트", "http://127.0.0.1:8080/v1/chat/completions");
    ui->package_groups = form_entry(GTK_GRID(grid), 4, "추가 그룹(쉼표)", "");
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "profile", "프로필 및 AI");

    page = page_new("검토", "계획을 확인한 뒤 저장하거나 실제 설치를 시작합니다. 설치 시작 전 디스크 삭제 확인 문자열을 정확히 입력해야 합니다.");
    GtkWidget *scroller = gtk_scrolled_window_new();
    gtk_widget_set_vexpand(scroller, TRUE);
    GtkWidget *text = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(text), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(text), GTK_WRAP_WORD_CHAR);
    ui->review = gtk_text_view_get_buffer(GTK_TEXT_VIEW(text));
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroller), text);
    gtk_box_append(GTK_BOX(page), scroller);
    grid = form_new();
    ui->destructive_confirm = form_entry(GTK_GRID(grid), 0, "디스크 삭제 확인", "");
    gtk_box_append(GTK_BOX(page), grid);
    GtkWidget *actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *review_button = gtk_button_new_with_label("계획 새로고침");
    GtkWidget *write_button = gtk_button_new_with_label("설치 계획 저장");
    GtkWidget *install_button = gtk_button_new_with_label("설치 시작");
    gtk_widget_add_css_class(install_button, "suggested-action");
    gtk_box_append(GTK_BOX(actions), review_button);
    gtk_box_append(GTK_BOX(actions), write_button);
    gtk_box_append(GTK_BOX(actions), install_button);
    gtk_box_append(GTK_BOX(page), actions);
    ui->status = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_wrap(ui->status, TRUE);
    gtk_label_set_xalign(ui->status, 0.0f);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->status));
    g_signal_connect(review_button, "clicked", G_CALLBACK(review_clicked), ui);
    g_signal_connect(write_button, "clicked", G_CALLBACK(write_plan), ui);
    g_signal_connect(install_button, "clicked", G_CALLBACK(start_install), ui);
    stack_page(GTK_STACK(stack), page, "review", "검토 및 설치");

    page = page_new("설치 진행", "설치 중에는 시스템을 끄거나 대상 디스크를 분리하지 마세요.");
    ui->progress_phase = GTK_LABEL(gtk_label_new("설치 대기"));
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
    ui->progress_message = GTK_LABEL(gtk_label_new("설치 시작 전입니다."));
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
    ui->reboot_button = GTK_BUTTON(gtk_button_new_with_label("확인 후 재부팅"));
    gtk_widget_add_css_class(GTK_WIDGET(ui->reboot_button), "suggested-action");
    gtk_widget_set_halign(GTK_WIDGET(ui->reboot_button), GTK_ALIGN_END);
    gtk_widget_set_visible(GTK_WIDGET(ui->reboot_button), FALSE);
    g_signal_connect(ui->reboot_button, "clicked", G_CALLBACK(request_reboot), ui);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->reboot_button));
    stack_page(GTK_STACK(stack), page, "progress", "설치 진행");

    update_review(ui);
    gtk_window_set_child(ui->window, root);
    g_object_set_data_full(G_OBJECT(ui->window), "kiki-ui", ui, g_free);
    gtk_window_present(ui->window);
}

int main(int argc, char **argv) {
    g_autoptr(GtkApplication) application = gtk_application_new(
        "io.kiki.Installer", G_APPLICATION_FLAGS_NONE);
    g_signal_connect(application, "activate", G_CALLBACK(activate), NULL);
    return g_application_run(G_APPLICATION(application), argc, argv);
}
