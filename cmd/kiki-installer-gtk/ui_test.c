/* Runs the real GTK frontend and Go plan writer; backend paths are private fixtures. */
static const char *test_request_path, *test_request_tmp, *test_progress_path;
static const char *test_reboot_path, *test_reboot_tmp;
static const char *test_backend_path;
#define GUI_INSTALL_REQUEST_PATH test_request_path
#define GUI_INSTALL_REQUEST_TMP_PATH test_request_tmp
#define GUI_INSTALL_PROGRESS_PATH test_progress_path
#define GUI_REBOOT_REQUEST_PATH test_reboot_path
#define GUI_REBOOT_REQUEST_TMP_PATH test_reboot_tmp
#define GUI_INSTALL_BACKEND_LOG_PATH test_backend_path
#define main kiki_application_main
#include "main.c"
#undef main

static void settle(void) {
    gint64 until = g_get_monotonic_time() + 300000;
    do {
        while (g_main_context_iteration(NULL, FALSE)) {}
        g_usleep(1000);
    } while (g_get_monotonic_time() < until);
}

static void screenshot(InstallerUI *ui, const char *directory, const char *name) {
    settle();
    GtkWidget *window = GTK_WIDGET(ui->window);
    g_print("SCREEN %s: %dx%d\n", name, gtk_widget_get_width(window), gtk_widget_get_height(window));
    g_autoptr(GdkPaintable) paintable = gtk_widget_paintable_new(window);
    GtkSnapshot *snapshot = gtk_snapshot_new();
    gdk_paintable_snapshot(paintable, GDK_SNAPSHOT(snapshot), gtk_widget_get_width(window), gtk_widget_get_height(window));
    GskRenderNode *node = gtk_snapshot_free_to_node(snapshot);
    g_assert_nonnull(node);
    GskRenderer *renderer = gsk_renderer_new_for_surface(gtk_native_get_surface(GTK_NATIVE(ui->window)));
    graphene_rect_t viewport = GRAPHENE_RECT_INIT(0, 0, gtk_widget_get_width(window), gtk_widget_get_height(window));
    g_autoptr(GdkTexture) texture = gsk_renderer_render_texture(renderer, node, &viewport);
    g_autofree char *path = g_build_filename(directory, name, NULL);
    g_assert_true(gdk_texture_save_to_png(texture, path));
    gsk_renderer_unrealize(renderer);
    g_object_unref(renderer);
    gsk_render_node_unref(node);
}

static void assert_navigation_fits(InstallerUI *ui) {
    graphene_rect_t bounds;
    g_assert_true(gtk_widget_compute_bounds(ui->navigation, GTK_WIDGET(ui->window), &bounds));
    g_assert_cmpfloat(bounds.origin.y, >=, 0);
    g_assert_cmpfloat(bounds.origin.y + bounds.size.height, <=, gtk_widget_get_height(GTK_WIDGET(ui->window)));
    g_assert_cmpfloat(bounds.size.height, >, 30);
}

int main(int argc, char **argv) {
    g_assert_cmpint(argc, ==, 3);
    g_autofree char *fixture = g_dir_make_tmp("kiki-installer-ui-test-XXXXXX", NULL);
    g_assert_nonnull(fixture);
    g_autofree char *request = g_build_filename(fixture, "install.request", NULL);
    g_autofree char *temporary = g_build_filename(fixture, "install.request.tmp", NULL);
    g_autofree char *progress = g_build_filename(fixture, "progress.state", NULL);
    g_autofree char *reboot = g_build_filename(fixture, "reboot.request", NULL);
    g_autofree char *reboot_tmp = g_build_filename(fixture, "reboot.request.tmp", NULL);
    g_autofree char *plan = g_build_filename(fixture, "install-plan.yaml", NULL);
    g_autofree char *backend = g_build_filename(fixture, "backend.log", NULL);
    test_backend_path = backend;
    test_request_path = request; test_request_tmp = temporary; test_progress_path = progress;
    test_reboot_path = reboot; test_reboot_tmp = reboot_tmp;
    g_setenv("KIKI_INSTALLER_TUI", argv[1], TRUE);
    gtk_init();
    g_autoptr(GtkApplication) app = gtk_application_new("io.kiki.Installer.Test", G_APPLICATION_NON_UNIQUE);
    g_assert_true(g_application_register(G_APPLICATION(app), NULL, NULL));
    ui_korean = TRUE;
    build_installer_ui(app);
    GtkWindow *window = gtk_application_get_windows(app)->data;
    InstallerUI *ui = g_object_get_data(G_OBJECT(window), "kiki-ui");
    gtk_stack_set_transition_duration(ui->stack, 0);
    gtk_widget_set_size_request(GTK_WIDGET(window), 1024, 768);
    gtk_window_set_default_size(window, 1024, 768);
    settle();
    GtkWidget *reloaded_logo = brand_image();
    g_assert_nonnull(reloaded_logo);
    g_object_ref_sink(reloaded_logo);
    g_object_unref(reloaded_logo);
    g_assert_nonnull(gtk_window_get_titlebar(window));
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui->locale)), ==, "ko_KR.UTF-8");
    g_assert_false(gtk_stack_page_get_visible(gtk_stack_get_page(ui->stack, gtk_stack_get_child_by_name(ui->stack, "progress"))));
    assert_navigation_fits(ui);
    screenshot(ui, argv[2], "welcome-1024.png");
    g_signal_emit_by_name(ui->next_button, "clicked");
    g_assert_cmpstr(gtk_stack_get_visible_child_name(ui->stack), ==, "localization");
    g_signal_emit_by_name(ui->back_button, "clicked");
    g_assert_cmpstr(gtk_stack_get_visible_child_name(ui->stack), ==, "welcome");
    gtk_window_set_default_size(window, 800, 600);
    gtk_widget_set_size_request(GTK_WIDGET(window), 800, 600);
    settle();
    for (guint i = 0; i < G_N_ELEMENTS(wizard_pages); i++) {
        gtk_stack_set_visible_child_name(ui->stack, wizard_pages[i]);
        settle();
        g_assert_cmpint(gtk_widget_get_height(GTK_WIDGET(window)), <=, 600);
        assert_navigation_fits(ui);
    }
    screenshot(ui, argv[2], "review-800.png");
    gtk_stack_set_visible_child_name(ui->stack, "network");
    screenshot(ui, argv[2], "network-800.png");
    gtk_editable_set_text(GTK_EDITABLE(ui->hostname), "local-ui-test");
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui->disk)), ==, "");
    gtk_drop_down_set_selected(ui->disk_device, ui->disks->len + 1);
    gtk_editable_set_text(GTK_EDITABLE(ui->disk), "/dev/vda");
    gtk_editable_set_text(GTK_EDITABLE(ui->plan_path), plan);
    gtk_drop_down_set_selected(ui->network_mode, 2);
    gtk_stack_set_visible_child_name(ui->stack, "review");
    GtkTextIter begin, end;
    gtk_text_buffer_get_bounds(ui->review, &begin, &end);
    g_autofree char *review_text = gtk_text_buffer_get_text(ui->review, &begin, &end, FALSE);
    g_assert_nonnull(strstr(review_text, "local-ui-test"));
    g_autoptr(GError) error = NULL;
    ui->media_catalog = g_key_file_new();
    g_key_file_set_boolean(ui->media_catalog, "profile desktop-gnome", "available", TRUE);
    g_key_file_set_uint64(ui->media_catalog, "profile desktop-gnome", "packages", 170);
    g_key_file_set_uint64(ui->media_catalog, "profile desktop-gnome", "download_bytes", 1500000000);
    g_key_file_set_boolean(ui->media_catalog, "group development", "available", TRUE);
    g_assert_false(validate_gui(ui, &error)); /* The server profile is absent. */
    g_clear_error(&error);
    for (guint i = 0; profiles[i]; i++) {
        if (g_str_equal(profiles[i], "desktop-gnome")) gtk_drop_down_set_selected(ui->profile, i);
    }
    g_assert_cmpstr(dropdown_text(ui->ai_mode), ==, "off");
    g_assert_cmpstr(dropdown_text(ui->runtime), ==, "none");
    g_assert_cmpstr(selected_profile(ui), ==, "desktop-gnome");
    g_assert_cmpstr(dropdown_text(ui->profile), ==, "GNOME 데스크톱");
    g_assert_nonnull(strstr(gtk_label_get_text(ui->profile_status), "170"));
    for (guint i = 0; extra_group_ids[i]; i++) {
        if (g_str_equal(extra_group_ids[i], "development")) gtk_check_button_set_active(ui->extra_groups[i], TRUE);
    }
    gtk_stack_set_visible_child_name(ui->stack, "profile");
    settle();
    screenshot(ui, argv[2], "desktop-gnome-800.png");
    gtk_stack_set_visible_child_name(ui->stack, "review");
    g_assert_true(write_plan_file(ui, &error));
    g_assert_no_error(error);
    g_autofree char *desktop_plan = NULL;
    g_assert_true(g_file_get_contents(plan, &desktop_plan, NULL, NULL));
    g_assert_nonnull(strstr(desktop_plan, "kiki-gnome-desktop"));
    g_assert_nonnull(strstr(desktop_plan, "graphical.target"));
    g_assert_nonnull(strstr(desktop_plan, "\"make\""));
    gtk_editable_set_text(GTK_EDITABLE(ui->admin_password), "fixture-password-only");
    gtk_editable_set_text(GTK_EDITABLE(ui->admin_password_confirm), "fixture-password-only");
    g_assert_false(write_install_request(ui, &error));
    g_assert_nonnull(error);
    g_clear_error(&error);
    g_assert_false(g_file_test(request, G_FILE_TEST_EXISTS));
    g_assert_false(gtk_widget_get_sensitive(GTK_WIDGET(ui->install_button)));
    gtk_check_button_set_active(ui->destructive_confirm, TRUE);
    g_assert_true(gtk_widget_get_sensitive(GTK_WIDGET(ui->install_button)));
    g_assert_true(write_install_request(ui, &error));
    g_assert_no_error(error);
    g_autofree char *contents = NULL;
    g_assert_true(g_file_get_contents(request, &contents, NULL, NULL));
    g_assert_nonnull(strstr(contents, "package=base-files\n"));
    g_assert_nonnull(strstr(contents, "package=kiki-gnome-desktop\n"));
    g_assert_nonnull(strstr(contents, "profile=desktop-gnome\n"));
    g_assert_nonnull(strstr(contents, "ai=off\n"));
    GStatBuf info;
    g_assert_cmpint(g_stat(request, &info), ==, 0);
    g_assert_cmpuint(info.st_mode & 0777, ==, 0600);
    g_assert_false(write_install_request(ui, &error));
    g_clear_error(&error);
    g_autofree char *unchanged = NULL;
    g_assert_true(g_file_get_contents(request, &unchanged, NULL, NULL));
    g_assert_cmpstr(contents, ==, unchanged);
    g_assert_false(g_file_test(temporary, G_FILE_TEST_EXISTS));
    g_unlink(request);
    gtk_editable_set_text(GTK_EDITABLE(ui->disk), "/dev/vdb");
    g_assert_false(gtk_check_button_get_active(ui->destructive_confirm));
    gtk_check_button_set_active(ui->destructive_confirm, TRUE);
    start_install(NULL, ui);
    g_assert_true(ui->install_started);
    g_assert_cmpstr(gtk_stack_get_visible_child_name(ui->stack), ==, "progress");
    g_assert_true(installer_close_requested(window, ui));
    g_assert_false(gtk_widget_get_visible(ui->navigation));
    g_source_remove(ui->progress_source);
    ui->progress_source = 0;
    g_assert_true(g_file_set_contents(progress, "version=1\nstate=running\npercent=45\npackages_installed=1\npackages_total=2\nphase=패키지 설치\nmessage=설치 흐름 테스트\npackage=base-files\n", -1, NULL));
    g_assert_cmpint(poll_install_progress(ui), ==, G_SOURCE_CONTINUE);
    screenshot(ui, argv[2], "progress-800.png");
    g_assert_true(g_file_set_contents(progress, "version=1\nstate=failed\npercent=45\npackages_installed=1\npackages_total=2\nmessage=fixture failure\n", -1, NULL));
    g_assert_true(g_file_set_contents(backend, "Required AI package missing: fixture-package", -1, NULL));
    g_assert_cmpint(poll_install_progress(ui), ==, G_SOURCE_REMOVE);
    gtk_text_buffer_get_bounds(ui->progress_log, &begin, &end);
    g_autofree char *failure_log = gtk_text_buffer_get_text(ui->progress_log, &begin, &end, FALSE);
    g_assert_nonnull(strstr(failure_log, "fixture-package"));
    g_assert_false(installer_close_requested(window, ui));
    g_assert_true(g_file_set_contents(progress, "version=1\nstate=completed\npercent=100\npackages_installed=2\npackages_total=2\nmessage=fixture completed\n", -1, NULL));
    g_assert_cmpint(poll_install_progress(ui), ==, G_SOURCE_REMOVE);
    g_assert_true(ui->install_complete);
    g_assert_true(gtk_widget_get_visible(GTK_WIDGET(ui->reboot_button)));
    request_reboot(ui->reboot_button, ui);
    g_assert_true(g_file_test(reboot, G_FILE_TEST_IS_REGULAR));
    gtk_window_destroy(window);
    ui_korean = FALSE;
    build_installer_ui(app);
    window = gtk_application_get_windows(app)->data;
    ui = g_object_get_data(G_OBJECT(window), "kiki-ui");
    gtk_widget_set_size_request(GTK_WIDGET(window), 800, 600);
    gtk_window_set_default_size(window, 800, 600);
    settle();
    assert_navigation_fits(ui);
    screenshot(ui, argv[2], "welcome-en-800.png");
    gtk_window_destroy(window);
    g_unlink(request); g_unlink(progress); g_unlink(reboot); g_unlink(plan); g_unlink(backend); g_rmdir(fixture);
    g_print("PASS: rendered GTK, 800x600 navigation, fresh review, real Go plan, consent, exclusive request, progress, failure, completion, reboot request (isolated fixtures only)\n");
    return 0;
}
