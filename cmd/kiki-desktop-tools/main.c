#include <gtk/gtk.h>
#include <glib/gstdio.h>
#include <locale.h>
#include <string.h>

/* Small native utilities for the initial GNOME installation. Settings are
 * per-user GSettings; file operations never run with elevated privileges. */
static gboolean korean;
#define T(ko,en) (korean ? (ko) : (en))

typedef struct {
    GtkWindow *window;
    GtkListBox *files;
    GtkEntry *location;
    GtkLabel *status;
    GFile *directory;
    GCancellable *enumeration;
    guint generation;
} Files;

typedef struct { Files *files; guint generation; } Scan;

static void file_error(Files *ui, const char *message) {
    gtk_label_set_text(ui->status, message);
}

static void show_file(Files *ui, GFile *file) {
    g_autoptr(GError) error = NULL;
    g_autofree char *text = NULL;
    gsize length = 0;
    g_autoptr(GFileInfo) info = g_file_query_info(file, G_FILE_ATTRIBUTE_STANDARD_SIZE "," G_FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE, 0, NULL, &error);
    if (!info) { file_error(ui, error->message); return; }
    const char *type = g_file_info_get_content_type(info);
    if (type && g_content_type_is_a(type, "text/plain") && g_file_info_get_size(info) <= 1024 * 1024 &&
        g_file_load_contents(file, NULL, &text, &length, NULL, &error) && g_utf8_validate(text, length, NULL)) {
        GtkWidget *preview = gtk_window_new();
        gtk_window_set_transient_for(GTK_WINDOW(preview), ui->window);
        gtk_window_set_default_size(GTK_WINDOW(preview), 720, 520);
        g_autofree char *name = g_file_get_basename(file);
        gtk_window_set_title(GTK_WINDOW(preview), name);
        GtkWidget *view = gtk_text_view_new();
        gtk_text_view_set_editable(GTK_TEXT_VIEW(view), FALSE);
        gtk_text_view_set_monospace(GTK_TEXT_VIEW(view), TRUE);
        gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(view), GTK_WRAP_WORD_CHAR);
        gtk_text_view_set_left_margin(GTK_TEXT_VIEW(view), 16);
        gtk_text_view_set_top_margin(GTK_TEXT_VIEW(view), 16);
        gtk_text_buffer_set_text(gtk_text_view_get_buffer(GTK_TEXT_VIEW(view)), text, length);
        GtkWidget *scroll = gtk_scrolled_window_new();
        gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll), view);
        gtk_window_set_child(GTK_WINDOW(preview), scroll);
        gtk_window_present(GTK_WINDOW(preview));
        return;
    }
    g_clear_error(&error);
    g_autofree char *uri = g_file_get_uri(file);
    if (!g_app_info_launch_default_for_uri(uri, NULL, &error)) file_error(ui, error->message);
}

static gint compare_rows(GtkListBoxRow *a, GtkListBoxRow *b, gpointer data) {
    (void)data;
    gboolean ad = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(a), "directory"));
    gboolean bd = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(b), "directory"));
    if (ad != bd) return bd - ad;
    return g_utf8_collate(g_object_get_data(G_OBJECT(a), "name"), g_object_get_data(G_OBJECT(b), "name"));
}

static void scan_done(GObject *source, GAsyncResult *result, gpointer data) {
    Scan *scan = data;
    Files *ui = scan->files;
    g_autoptr(GError) error = NULL;
    g_autoptr(GFileEnumerator) entries = g_file_enumerate_children_finish(G_FILE(source), result, &error);
    if (scan->generation != ui->generation) goto done;
    if (!entries) { file_error(ui, error->message); goto done; }
    guint count = 0;
    GFileInfo *info;
    while (count < 5000 && (info = g_file_enumerator_next_file(entries, ui->enumeration, &error))) {
        const char *name = g_file_info_get_name(info);
        if (name[0] != '.') {
            GFile *file = g_file_get_child(G_FILE(source), name);
            gboolean directory = g_file_info_get_file_type(info) == G_FILE_TYPE_DIRECTORY;
            GtkWidget *row = gtk_list_box_row_new();
            GtkWidget *box = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
            gtk_widget_set_margin_start(box, 12); gtk_widget_set_margin_end(box, 12);
            gtk_widget_set_margin_top(box, 9); gtk_widget_set_margin_bottom(box, 9);
            GtkWidget *icon = gtk_image_new_from_icon_name(directory ? "folder-symbolic" : "text-x-generic-symbolic");
            GtkWidget *label = gtk_label_new(g_file_info_get_display_name(info));
            gtk_label_set_xalign(GTK_LABEL(label), 0);
            gtk_label_set_ellipsize(GTK_LABEL(label), PANGO_ELLIPSIZE_MIDDLE);
            gtk_widget_set_hexpand(label, TRUE);
            gtk_box_append(GTK_BOX(box), icon); gtk_box_append(GTK_BOX(box), label);
            gtk_list_box_row_set_child(GTK_LIST_BOX_ROW(row), box);
            g_object_set_data_full(G_OBJECT(row), "file", file, g_object_unref);
            g_object_set_data_full(G_OBJECT(row), "name", g_strdup(name), g_free);
            g_object_set_data(G_OBJECT(row), "directory", GINT_TO_POINTER(directory));
            gtk_list_box_append(ui->files, row);
            count++;
        }
        g_object_unref(info);
    }
    if (error) file_error(ui, error->message);
    else {
        g_autofree char *summary = g_strdup_printf(T("%u개 항목%s", "%u items%s"), count, count == 5000 ? T(" · 처음 5,000개 표시", " · first 5,000 shown") : "");
        file_error(ui, summary);
    }
done:
    g_object_unref(ui->window);
    g_free(scan);
}

static void open_directory(Files *ui, GFile *directory) {
    if (ui->enumeration) g_cancellable_cancel(ui->enumeration);
    g_clear_object(&ui->enumeration);
    ui->enumeration = g_cancellable_new();
    ui->generation++;
    g_set_object(&ui->directory, directory);
    g_autofree char *path = g_file_get_path(directory);
    gtk_editable_set_text(GTK_EDITABLE(ui->location), path ? path : "");
    GtkWidget *row;
    while ((row = gtk_widget_get_first_child(GTK_WIDGET(ui->files)))) gtk_list_box_remove(ui->files, row);
    file_error(ui, T("폴더를 읽는 중…", "Reading folder…"));
    Scan *scan = g_new0(Scan, 1);
    scan->files = ui; scan->generation = ui->generation;
    g_object_ref(ui->window);
    g_file_enumerate_children_async(directory, "standard::name,standard::display-name,standard::type", G_FILE_QUERY_INFO_NONE,
                                   G_PRIORITY_DEFAULT, ui->enumeration, scan_done, scan);
}

static void row_activated(GtkListBox *list, GtkListBoxRow *row, gpointer data) {
    (void)list;
    Files *ui = data;
    GFile *file = g_object_get_data(G_OBJECT(row), "file");
    /* Navigation removes the row; keep the selected GFile alive through it. */
    g_object_ref(file);
    if (GPOINTER_TO_INT(g_object_get_data(G_OBJECT(row), "directory"))) open_directory(ui, file);
    else show_file(ui, file);
    g_object_unref(file);
}

static void location_activated(GtkEntry *entry, gpointer data) {
    g_autoptr(GFile) file = g_file_new_for_path(gtk_editable_get_text(GTK_EDITABLE(entry)));
    open_directory(data, file);
}

static void parent_clicked(GtkButton *button, gpointer data) {
    (void)button;
    Files *ui = data;
    g_autoptr(GFile) parent = g_file_get_parent(ui->directory);
    if (parent) open_directory(ui, parent);
}

static void home_clicked(GtkButton *button, gpointer data) {
    (void)button;
    g_autoptr(GFile) home = g_file_new_for_path(g_get_home_dir());
    open_directory(data, home);
}

static void files_free(gpointer data) {
    Files *ui = data;
    if (ui->enumeration) g_cancellable_cancel(ui->enumeration);
    g_clear_object(&ui->enumeration); g_clear_object(&ui->directory); g_free(ui);
}

static void show_files(GtkApplication *app) {
    Files *ui = g_new0(Files, 1);
    ui->window = GTK_WINDOW(gtk_application_window_new(app));
    gtk_window_set_title(ui->window, T("파일", "Files"));
    gtk_window_set_default_size(ui->window, 850, 560);
    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
    GtkWidget *toolbar = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_widget_set_margin_start(toolbar, 12); gtk_widget_set_margin_end(toolbar, 12);
    gtk_widget_set_margin_top(toolbar, 12); gtk_widget_set_margin_bottom(toolbar, 12);
    GtkWidget *up = gtk_button_new_from_icon_name("go-up-symbolic");
    gtk_widget_set_tooltip_text(up, T("상위 폴더", "Parent folder"));
    GtkWidget *home = gtk_button_new_from_icon_name("user-home-symbolic");
    gtk_widget_set_tooltip_text(home, T("홈 폴더", "Home folder"));
    ui->location = GTK_ENTRY(gtk_entry_new());
    gtk_widget_set_hexpand(GTK_WIDGET(ui->location), TRUE);
    gtk_box_append(GTK_BOX(toolbar), up); gtk_box_append(GTK_BOX(toolbar), home);
    gtk_box_append(GTK_BOX(toolbar), GTK_WIDGET(ui->location));
    ui->files = GTK_LIST_BOX(gtk_list_box_new());
    gtk_list_box_set_sort_func(ui->files, compare_rows, NULL, NULL);
    GtkWidget *scroll = gtk_scrolled_window_new();
    gtk_widget_set_vexpand(scroll, TRUE);
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll), GTK_WIDGET(ui->files));
    ui->status = GTK_LABEL(gtk_label_new(NULL));
    gtk_widget_set_margin_bottom(GTK_WIDGET(ui->status), 10);
    gtk_box_append(GTK_BOX(root), toolbar); gtk_box_append(GTK_BOX(root), scroll);
    gtk_box_append(GTK_BOX(root), GTK_WIDGET(ui->status));
    gtk_window_set_child(ui->window, root);
    g_signal_connect(up, "clicked", G_CALLBACK(parent_clicked), ui);
    g_signal_connect(home, "clicked", G_CALLBACK(home_clicked), ui);
    g_signal_connect(ui->location, "activate", G_CALLBACK(location_activated), ui);
    g_signal_connect(ui->files, "row-activated", G_CALLBACK(row_activated), ui);
    g_object_set_data_full(G_OBJECT(ui->window), "files", ui, files_free);
    home_clicked(NULL, ui);
    gtk_window_present(ui->window);
}

static void theme_changed(GObject *object, GParamSpec *spec, gpointer data) {
    (void)spec;
    const char *values[] = {"default", "prefer-dark", "prefer-light"};
    guint i = gtk_drop_down_get_selected(GTK_DROP_DOWN(object));
    if (i < G_N_ELEMENTS(values)) g_settings_set_string(G_SETTINGS(data), "color-scheme", values[i]);
}

static void scale_changed(GtkRange *range, gpointer data) {
    g_settings_set_double(G_SETTINGS(data), "text-scaling-factor", gtk_range_get_value(range));
}

static void input_changed(GObject *object, GParamSpec *spec, gpointer data) {
    (void)spec;
    GVariantBuilder builder;
    g_variant_builder_init(&builder, G_VARIANT_TYPE("a(ss)"));
    gboolean ko = gtk_drop_down_get_selected(GTK_DROP_DOWN(object)) == 1;
    g_variant_builder_add(&builder, "(ss)", "xkb", "us");
    if (ko) g_variant_builder_add(&builder, "(ss)", "ibus", "hangul");
    g_settings_set_value(G_SETTINGS(data), "sources", g_variant_builder_end(&builder));
}

static void launch_network(GtkButton *button, gpointer data) {
    (void)button;
    GtkLabel *status = data;
    const char *argv[] = {"/usr/bin/vte-2.91-gtk4", "--", "/usr/bin/sudo", "/usr/bin/kiki-netconfig", NULL};
    g_autoptr(GError) error = NULL;
    g_autoptr(GSubprocess) process = g_subprocess_newv(argv, G_SUBPROCESS_FLAGS_NONE, &error);
    if (!process) gtk_label_set_text(status, error->message);
}

static void settings_row(GtkGrid *grid, int row, const char *label, GtkWidget *control) {
    GtkWidget *text = gtk_label_new(label);
    gtk_label_set_xalign(GTK_LABEL(text), 0);
    gtk_widget_set_hexpand(control, TRUE);
    gtk_grid_attach(grid, text, 0, row, 1, 1); gtk_grid_attach(grid, control, 1, row, 1, 1);
}

static void show_settings(GtkApplication *app) {
    GtkWindow *window = GTK_WINDOW(gtk_application_window_new(app));
    gtk_window_set_title(window, T("KIKI 설정", "KIKI Settings"));
    gtk_window_set_default_size(window, 660, 480);
    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 20);
    gtk_widget_set_margin_start(root, 32); gtk_widget_set_margin_end(root, 32);
    gtk_widget_set_margin_top(root, 28); gtk_widget_set_margin_bottom(root, 28);
    GtkWidget *title = gtk_label_new(T("데스크톱 설정", "Desktop settings"));
    gtk_widget_add_css_class(title, "title-1"); gtk_widget_set_halign(title, GTK_ALIGN_START);
    gtk_box_append(GTK_BOX(root), title);
    GtkWidget *description = gtk_label_new(T("설정은 현재 사용자에게 적용되며 자동 저장됩니다.", "Changes apply to your account and are saved automatically."));
    gtk_label_set_wrap(GTK_LABEL(description), TRUE); gtk_label_set_xalign(GTK_LABEL(description), 0);
    gtk_box_append(GTK_BOX(root), description);
    GSettings *interface = g_settings_new("org.gnome.desktop.interface");
    GSettings *input = g_settings_new("org.gnome.desktop.input-sources");
    g_object_set_data_full(G_OBJECT(window), "interface", interface, g_object_unref);
    g_object_set_data_full(G_OBJECT(window), "input", input, g_object_unref);
    GtkGrid *grid = GTK_GRID(gtk_grid_new());
    gtk_grid_set_row_spacing(grid, 20); gtk_grid_set_column_spacing(grid, 32);
    const char *themes[] = {T("시스템 기본", "System default"), T("어둡게", "Dark"), T("밝게", "Light"), NULL};
    GtkWidget *theme = gtk_drop_down_new_from_strings(themes);
    g_autofree char *scheme = g_settings_get_string(interface, "color-scheme");
    gtk_drop_down_set_selected(GTK_DROP_DOWN(theme), g_str_equal(scheme, "prefer-dark") ? 1 : g_str_equal(scheme, "prefer-light") ? 2 : 0);
    g_signal_connect(theme, "notify::selected", G_CALLBACK(theme_changed), interface);
    settings_row(grid, 0, T("화면 테마", "Appearance"), theme);
    GtkWidget *scale = gtk_scale_new_with_range(GTK_ORIENTATION_HORIZONTAL, 0.8, 1.8, 0.1);
    gtk_range_set_value(GTK_RANGE(scale), g_settings_get_double(interface, "text-scaling-factor"));
    gtk_scale_set_digits(GTK_SCALE(scale), 1);
    g_signal_connect(scale, "value-changed", G_CALLBACK(scale_changed), interface);
    settings_row(grid, 1, T("글자 크기", "Text scale"), scale);
    GtkWidget *animations = gtk_switch_new(); gtk_widget_set_halign(animations, GTK_ALIGN_START);
    g_settings_bind(interface, "enable-animations", animations, "active", G_SETTINGS_BIND_DEFAULT);
    settings_row(grid, 2, T("화면 애니메이션", "Animations"), animations);
    const char *inputs[] = {T("영어", "English"), T("영어 + 한국어 (두벌식)", "English + Korean (Dubeolsik)"), NULL};
    GtkWidget *language = gtk_drop_down_new_from_strings(inputs);
    g_autoptr(GVariant) sources = g_settings_get_value(input, "sources");
    g_autofree char *printed = g_variant_print(sources, FALSE);
    gtk_drop_down_set_selected(GTK_DROP_DOWN(language), strstr(printed, "hangul") ? 1 : 0);
    g_signal_connect(language, "notify::selected", G_CALLBACK(input_changed), input);
    settings_row(grid, 3, T("입력 언어", "Input sources"), language);
    gtk_box_append(GTK_BOX(root), GTK_WIDGET(grid));
    GtkWidget *network = gtk_button_new_with_label(T("네트워크 설정 열기", "Open network configuration"));
    gtk_widget_set_halign(network, GTK_ALIGN_START);
    gtk_box_append(GTK_BOX(root), network);
    GtkWidget *status = gtk_label_new(T("입력 언어 전환: Super + Space · 한/영 전환: 한/영 키 또는 Shift + Space", "Switch input source: Super + Space · Toggle Hangul: Hangul key or Shift + Space"));
    gtk_label_set_wrap(GTK_LABEL(status), TRUE); gtk_label_set_xalign(GTK_LABEL(status), 0);
    gtk_widget_add_css_class(status, "dim-label");
    gtk_box_append(GTK_BOX(root), status);
    g_signal_connect(network, "clicked", G_CALLBACK(launch_network), status);
    gtk_window_set_child(window, root); gtk_window_present(window);
}

static void activate(GtkApplication *app, gpointer data) {
    if (GPOINTER_TO_INT(data)) show_files(app); else show_settings(app);
}

int main(int argc, char **argv) {
    setlocale(LC_ALL, "");
    korean = g_str_has_prefix(setlocale(LC_MESSAGES, NULL), "ko");
    gboolean files = argc > 1 && g_str_equal(argv[1], "--files");
    g_autoptr(GtkApplication) app = gtk_application_new(files ? "org.kiki.Files" : "org.kiki.Settings", (GApplicationFlags)0);
    g_signal_connect(app, "activate", G_CALLBACK(activate), GINT_TO_POINTER(files));
    return g_application_run(G_APPLICATION(app), 1, argv);
}
