#include <gtk/gtk.h>

typedef struct {
    GtkWindow *window;
    GtkEntry *plan_path;
    GtkEntry *disk;
    GtkEntry *hostname;
    GtkEntry *admin_user;
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
    GtkDropDown *install_mode;
    GtkDropDown *swap_mode;
    GtkDropDown *network_mode;
    GtkDropDown *source_type;
    GtkDropDown *profile;
    GtkDropDown *runtime;
    GtkDropDown *ai_mode;
    GtkTextBuffer *review;
    GtkLabel *status;
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
    g_autofree char *text = g_strdup_printf(
        "설치 모드: %s\n"
        "대상 디스크: %s (swap: %s)\n"
        "언어: %s / %s / %s\n"
        "네트워크: %s (%s)\n"
        "계정: %s / %s\n"
        "패키지 소스: %s / %s\n"
        "프로필: %s\n"
        "컨테이너 런타임: %s\n"
        "AI 에이전트: %s / 명령 승인 필수\n"
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
        dropdown_text(ui->profile), dropdown_text(ui->runtime), ai,
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

static void write_plan(GtkButton *button, gpointer data) {
    (void)button;
    InstallerUI *ui = data;
    g_autoptr(GError) error = NULL;
    if (!validate_gui(ui, &error)) {
        gtk_label_set_text(ui->status, error->message);
        gtk_widget_add_css_class(GTK_WIDGET(ui->status), "error");
        return;
    }

    const char *tool = g_getenv("KIKI_INSTALLER_TUI");
    if (!tool || !*tool) tool = "kiki-installer-tui";
    g_autoptr(GPtrArray) args = g_ptr_array_new();
    g_ptr_array_add(args, (gpointer)tool);
    g_ptr_array_add(args, "--write");
    add_arg(args, "--plan", gtk_editable_get_text(GTK_EDITABLE(ui->plan_path)));
    add_arg(args, "--mode", dropdown_text(ui->install_mode));
    add_arg(args, "--profile", dropdown_text(ui->profile));
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
        &error);
    if (!process) {
        gtk_label_set_text(ui->status, error->message);
        return;
    }
    g_autofree char *stdout_text = NULL;
    g_autofree char *stderr_text = NULL;
    if (!g_subprocess_communicate_utf8(process, NULL, NULL, &stdout_text, &stderr_text, &error) ||
        !g_subprocess_get_successful(process)) {
        gtk_label_set_text(ui->status, error ? error->message : (stderr_text && *stderr_text ? stderr_text : "계획 생성 실패"));
        gtk_widget_add_css_class(GTK_WIDGET(ui->status), "error");
        return;
    }
    gtk_widget_remove_css_class(GTK_WIDGET(ui->status), "error");
    gtk_label_set_text(ui->status, stdout_text && *stdout_text ? stdout_text : "설치 계획을 저장했습니다.");
    update_review(ui);
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
    gtk_stack_set_transition_type(GTK_STACK(stack), GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    gtk_widget_set_hexpand(stack, TRUE);
    gtk_widget_set_vexpand(stack, TRUE);
    GtkWidget *sidebar = gtk_stack_sidebar_new();
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

    page = page_new("계정", "초기 관리자와 시스템 호스트명을 설정합니다. 비밀번호는 계획 파일에 저장하지 않습니다.");
    grid = form_new();
    ui->admin_user = form_entry(GTK_GRID(grid), 0, "관리자", "kiki");
    ui->hostname = form_entry(GTK_GRID(grid), 1, "호스트명", "kiki.local");
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
    gtk_box_append(GTK_BOX(page), grid);
    stack_page(GTK_STACK(stack), page, "profile", "프로필 및 AI");

    page = page_new("검토", "파괴적인 작업 전에 계획을 확인하고 YAML로 저장합니다.");
    GtkWidget *scroller = gtk_scrolled_window_new();
    gtk_widget_set_vexpand(scroller, TRUE);
    GtkWidget *text = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(text), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(text), GTK_WRAP_WORD_CHAR);
    ui->review = gtk_text_view_get_buffer(GTK_TEXT_VIEW(text));
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroller), text);
    gtk_box_append(GTK_BOX(page), scroller);
    GtkWidget *actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    GtkWidget *review_button = gtk_button_new_with_label("계획 새로고침");
    GtkWidget *write_button = gtk_button_new_with_label("설치 계획 저장");
    gtk_widget_add_css_class(write_button, "suggested-action");
    gtk_box_append(GTK_BOX(actions), review_button);
    gtk_box_append(GTK_BOX(actions), write_button);
    gtk_box_append(GTK_BOX(page), actions);
    ui->status = GTK_LABEL(gtk_label_new(""));
    gtk_label_set_wrap(ui->status, TRUE);
    gtk_label_set_xalign(ui->status, 0.0f);
    gtk_box_append(GTK_BOX(page), GTK_WIDGET(ui->status));
    g_signal_connect(review_button, "clicked", G_CALLBACK(review_clicked), ui);
    g_signal_connect(write_button, "clicked", G_CALLBACK(write_plan), ui);
    stack_page(GTK_STACK(stack), page, "review", "검토 및 저장");

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
