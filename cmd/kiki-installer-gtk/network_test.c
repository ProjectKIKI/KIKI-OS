#define main kiki_application_main
#include "main.c"
#undef main

static void fixture(const char *root, const char *name, gboolean hardware, gboolean carrier) {
    g_autofree char *dir = g_build_filename(root, name, NULL);
    g_mkdir_with_parents(dir, 0700);
    if (hardware) {
        g_autofree char *device = g_build_filename(dir, "device", NULL);
        g_mkdir(device, 0700);
    }
    const char *files[] = {"type", "address", "carrier"};
    const char *values[] = {"1\n", "00:15:5d:01:03:41\n", carrier ? "1\n" : "0\n"};
    for (guint i = 0; i < G_N_ELEMENTS(files); i++) {
        g_autofree char *path = g_build_filename(dir, files[i], NULL);
        g_assert_true(g_file_set_contents(path, values[i], -1, NULL));
    }
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    fixture(argv[1], "eth0", TRUE, TRUE);
    fixture(argv[1], "ens3", TRUE, FALSE);
    fixture(argv[1], "dummy0", FALSE, FALSE);
    g_autoptr(GPtrArray) found = kiki_network_devices(argv[1]);
    g_assert_cmpuint(found->len, ==, 2);
    g_assert_cmpstr(((KikiNic *)g_ptr_array_index(found, 0))->name, ==, "ens3");
    g_assert_cmpstr(((KikiNic *)g_ptr_array_index(found, 1))->name, ==, "eth0");
    g_autofree char *invalid = kiki_network_status("eth*");
    g_assert_nonnull(strstr(invalid, "실제 장치 이름"));
    if (!gtk_init_check()) { g_printerr("GTK display unavailable; UI tests not run\n"); return 77; }
    InstallerUI ui = {0};
    ui.network_mode = GTK_DROP_DOWN(gtk_drop_down_new_from_strings(network_mode_labels_en));
    ui.network_device = GTK_DROP_DOWN(gtk_drop_down_new_from_strings(NULL));
    ui.dns_mode = GTK_DROP_DOWN(gtk_drop_down_new_from_strings((const char *[]) {"auto", "manual", NULL}));
    ui.network_interface = GTK_ENTRY(gtk_entry_new());
    ui.address = GTK_ENTRY(gtk_entry_new()); ui.gateway = GTK_ENTRY(gtk_entry_new());
    ui.dns = GTK_ENTRY(gtk_entry_new()); ui.network_status = GTK_LABEL(gtk_label_new(NULL));
    network_refresh_from(&ui, argv[1]);
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui.network_interface)), ==, "eth0");
    g_assert_false(gtk_widget_get_sensitive(GTK_WIDGET(ui.network_interface)));
    g_assert_false(gtk_widget_get_sensitive(GTK_WIDGET(ui.address)));
    gtk_drop_down_set_selected(ui.network_device, 0);
    network_changed(NULL, NULL, &ui);
    network_refresh_from(&ui, argv[1]);
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui.network_interface)), ==, "ens3");
    gtk_drop_down_set_selected(ui.network_device, ui.network_devices->len);
    network_changed(NULL, NULL, &ui);
    gtk_editable_set_text(GTK_EDITABLE(ui.network_interface), "en* eth*");
    network_refresh_from(&ui, argv[1]);
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui.network_interface)), ==, "en* eth*");
    g_assert_true(gtk_widget_get_sensitive(GTK_WIDGET(ui.network_interface)));
    gtk_drop_down_set_selected(ui.network_mode, 1);
    gtk_drop_down_set_selected(ui.dns_mode, 1);
    network_changed(NULL, NULL, &ui);
    g_assert_true(gtk_widget_get_sensitive(GTK_WIDGET(ui.address)));
    g_assert_true(gtk_widget_get_sensitive(GTK_WIDGET(ui.dns)));
    gtk_editable_set_text(GTK_EDITABLE(ui.dns), " 1.1.1.1,8.8.8.8 ");
    g_assert_cmpstr(selected_dns(&ui), ==, "1.1.1.1 8.8.8.8");
    gtk_drop_down_set_selected(ui.dns_mode, 0);
    g_assert_cmpstr(selected_dns(&ui), ==, "");
    g_assert_cmpstr(selected_network_mode(&ui), ==, "static");
    gtk_drop_down_set_selected(ui.network_device, 0);
    network_changed(NULL, NULL, &ui);
    g_autofree char *removed = g_build_filename(argv[1], "ens3", "device", NULL);
    g_assert_cmpint(g_rmdir(removed), ==, 0);
    network_refresh_from(&ui, argv[1]);
    g_assert_cmpstr(gtk_editable_get_text(GTK_EDITABLE(ui.network_interface)), ==, "ens3");
    g_assert_cmpuint(gtk_drop_down_get_selected(ui.network_device), ==, ui.network_devices->len);
    g_clear_pointer(&ui.network_devices, g_ptr_array_unref);
    g_autofree char *empty = g_build_filename(argv[1], "empty", NULL);
    g_mkdir(empty, 0700);
    network_refresh_from(&ui, empty);
    g_assert_cmpstr(selected_network_mode(&ui), ==, "off");
    g_print("PASS: discovery, carrier preference, explicit/manual selection, DNS, static fields, offline\n");
    return 0;
}
