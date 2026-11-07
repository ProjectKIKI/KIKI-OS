/* Optional process-local styling. Standard GNOME launches remain unchanged. */
static void pixel_theme(AdwStyleManager *manager, GParamSpec *spec, gpointer data) {
    (void)spec;
    g_autofree char *common = NULL, *theme = NULL;
    if (!g_file_get_contents("/usr/share/kiki-paper-pixel/admin.css", &common, NULL, NULL)) return;
    if (!adw_style_manager_get_high_contrast(manager))
        g_file_get_contents(adw_style_manager_get_dark(manager)
            ? "/usr/share/kiki-paper-pixel/admin-dark.css" : "/usr/share/kiki-paper-pixel/admin-light.css", &theme, NULL, NULL);
    g_autofree char *combined = g_strconcat(theme ? theme : "", "\n", common, NULL);
    gtk_css_provider_load_from_string(GTK_CSS_PROVIDER(data), combined);
}

static void pixel_style(GApplication *app) {
    if (g_strcmp0(g_getenv("KIKI_PAPER_PIXEL"), "1") != 0) return;
    GtkCssProvider *provider = gtk_css_provider_new();
    gtk_style_context_add_provider_for_display(gdk_display_get_default(), GTK_STYLE_PROVIDER(provider), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    AdwStyleManager *manager = adw_style_manager_get_default();
    g_signal_connect_object(manager, "notify::dark", G_CALLBACK(pixel_theme), provider, 0);
    g_signal_connect_object(manager, "notify::high-contrast", G_CALLBACK(pixel_theme), provider, 0);
    pixel_theme(manager, NULL, provider);
    g_object_set_data_full(G_OBJECT(app), "pixel-style", provider, g_object_unref);
}
