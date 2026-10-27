#define main desktop_application_main
#include "main.c"
#undef main

static void settle(void) {
    gint64 until = g_get_monotonic_time() + 300000;
    do { while (g_main_context_iteration(NULL, FALSE)) {} g_usleep(1000); }
    while (g_get_monotonic_time() < until);
}

static void capture(GtkWindow *window, const char *directory, const char *name) {
    settle();
    GtkWidget *widget = GTK_WIDGET(window);
    g_autoptr(GdkPaintable) paintable = gtk_widget_paintable_new(widget);
    GtkSnapshot *snapshot = gtk_snapshot_new();
    gdk_paintable_snapshot(paintable, GDK_SNAPSHOT(snapshot), gtk_widget_get_width(widget), gtk_widget_get_height(widget));
    GskRenderNode *node = gtk_snapshot_free_to_node(snapshot);
    g_assert_nonnull(node);
    GskRenderer *renderer = gsk_renderer_new_for_surface(gtk_native_get_surface(GTK_NATIVE(window)));
    graphene_rect_t viewport = GRAPHENE_RECT_INIT(0, 0, gtk_widget_get_width(widget), gtk_widget_get_height(widget));
    g_autoptr(GdkTexture) texture = gsk_renderer_render_texture(renderer, node, &viewport);
    g_autofree char *path = g_build_filename(directory, name, NULL);
    g_assert_true(gdk_texture_save_to_png(texture, path));
    gsk_renderer_unrealize(renderer); g_object_unref(renderer); gsk_render_node_unref(node);
}

int main(int argc, char **argv) {
    g_assert_cmpint(argc, ==, 2);
    gtk_init(); korean = TRUE;
    g_autoptr(GtkApplication) app = gtk_application_new("org.kiki.Tools.Test", G_APPLICATION_NON_UNIQUE);
    g_assert_true(g_application_register(G_APPLICATION(app), NULL, NULL));
    show_settings(app);
    GtkWindow *settings = gtk_application_get_windows(app)->data;
    GtkWidget *root = gtk_window_get_child(settings);
    GtkWidget *grid = gtk_widget_get_first_child(root);
    while (grid && !GTK_IS_GRID(grid)) grid = gtk_widget_get_next_sibling(grid);
    g_assert_nonnull(grid);
    GtkDropDown *theme = GTK_DROP_DOWN(gtk_grid_get_child_at(GTK_GRID(grid), 1, 0));
    GSettings *interface = g_object_get_data(G_OBJECT(settings), "interface");
    gtk_drop_down_set_selected(theme, 1);
    g_autofree char *scheme = g_settings_get_string(interface, "color-scheme");
    g_assert_cmpstr(scheme, ==, "prefer-dark");
    GtkRange *scale = GTK_RANGE(gtk_grid_get_child_at(GTK_GRID(grid), 1, 1));
    gtk_range_set_value(scale, 1.3);
    g_assert_cmpfloat_with_epsilon(g_settings_get_double(interface, "text-scaling-factor"), 1.3, 0.001);
    GtkDropDown *input = GTK_DROP_DOWN(gtk_grid_get_child_at(GTK_GRID(grid), 1, 3));
    gtk_drop_down_set_selected(input, 1);
    GSettings *input_settings = g_object_get_data(G_OBJECT(settings), "input");
    g_autoptr(GVariant) sources = g_settings_get_value(input_settings, "sources");
    g_autofree char *printed = g_variant_print(sources, FALSE);
    g_assert_nonnull(strstr(printed, "hangul"));
    capture(settings, argv[1], "settings.png");
    show_files(app);
    GtkWindow *window = gtk_application_get_windows(app)->data;
    Files *ui = g_object_get_data(G_OBJECT(window), "files");
    g_assert_nonnull(ui);
    g_autofree char *fixture = g_dir_make_tmp("kiki-files-test-XXXXXX", NULL);
    g_autofree char *folder = g_build_filename(fixture, "Documents", NULL);
    g_autofree char *text = g_build_filename(fixture, "example.txt", NULL);
    g_autofree char *hidden = g_build_filename(fixture, ".hidden", NULL);
    g_mkdir(folder, 0700);
    g_assert_true(g_file_set_contents(text, "한글 파일 미리보기\n", -1, NULL));
    g_assert_true(g_file_set_contents(hidden, "hidden", -1, NULL));
    g_autoptr(GFile) directory = g_file_new_for_path(fixture);
    open_directory(ui, directory); settle();
    GtkListBoxRow *row = gtk_list_box_get_row_at_index(ui->files, 0);
    g_assert_cmpstr(g_object_get_data(G_OBJECT(row), "name"), ==, "Documents");
    g_assert_nonnull(gtk_list_box_get_row_at_index(ui->files, 1));
    g_assert_null(gtk_list_box_get_row_at_index(ui->files, 2));
    capture(window, argv[1], "files.png");
    g_signal_emit_by_name(ui->files, "row-activated", row); settle();
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui->location)), ==, folder);
    parent_clicked(NULL, ui); settle();
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui->location)), ==, fixture);
    row = gtk_list_box_get_row_at_index(ui->files, 1);
    g_signal_emit_by_name(ui->files, "row-activated", row); settle();
    GListModel *windows = gtk_window_get_toplevels();
    gboolean preview_found = FALSE;
    for (guint i = 0; i < g_list_model_get_n_items(windows); i++) {
        g_autoptr(GtkWindow) preview = g_list_model_get_item(windows, i);
        if (g_strcmp0(gtk_window_get_title(preview), "example.txt") != 0) continue;
        GtkTextView *view = GTK_TEXT_VIEW(gtk_scrolled_window_get_child(GTK_SCROLLED_WINDOW(gtk_window_get_child(preview))));
        GtkTextBuffer *buffer = gtk_text_view_get_buffer(view);
        GtkTextIter begin, end; gtk_text_buffer_get_bounds(buffer, &begin, &end);
        g_autofree char *contents = gtk_text_buffer_get_text(buffer, &begin, &end, FALSE);
        g_assert_nonnull(strstr(contents, "한글 파일 미리보기"));
        preview_found = TRUE;
        gtk_window_destroy(preview);
        break;
    }
    g_assert_true(preview_found);
    g_unlink(text); g_unlink(hidden); g_rmdir(folder); g_rmdir(fixture);
    while (gtk_application_get_windows(app)) gtk_window_destroy(gtk_application_get_windows(app)->data);
    g_print("PASS: settings persistence, input sources, directory navigation, sorting and text preview\n");
    return 0;
}
