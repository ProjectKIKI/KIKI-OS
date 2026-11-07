#define main operations_application_main
#include "main.c"
#undef main

static void settle(void) {
    gint64 until=g_get_monotonic_time()+450000;
    do { while(g_main_context_iteration(NULL,FALSE)){}g_usleep(1000); }while(g_get_monotonic_time()<until);
}
static void capture(Ops *ui,const char *directory,const char *name) {
    settle();GtkWidget *widget=GTK_WIDGET(ui->window);
    g_autoptr(GdkPaintable) paintable=gtk_widget_paintable_new(widget);GskRenderNode *node=NULL;
    gint64 deadline=g_get_monotonic_time()+5000000;
    while(!node && g_get_monotonic_time()<deadline) {
        gtk_widget_queue_draw(widget);settle();GtkSnapshot *snapshot=gtk_snapshot_new();
        gdk_paintable_snapshot(paintable,GDK_SNAPSHOT(snapshot),gtk_widget_get_width(widget),gtk_widget_get_height(widget));
        node=gtk_snapshot_free_to_node(snapshot);
    }
    g_print("Capture %s: %dx%d mapped=%d\n",name,gtk_widget_get_width(widget),gtk_widget_get_height(widget),gtk_widget_get_mapped(widget));g_assert_nonnull(node);
    GskRenderer *renderer=gsk_renderer_new_for_surface(gtk_native_get_surface(GTK_NATIVE(ui->window)));
    graphene_rect_t viewport=GRAPHENE_RECT_INIT(0,0,gtk_widget_get_width(widget),gtk_widget_get_height(widget));
    g_autoptr(GdkTexture) texture=gsk_renderer_render_texture(renderer,node,&viewport);
    g_autofree char *path=g_build_filename(directory,name,NULL);g_assert_true(gdk_texture_save_to_png(texture,path));
    gsk_renderer_unrealize(renderer);g_object_unref(renderer);gsk_render_node_unref(node);
}
static guint visible_rows(Ops *ui) {
    guint n=0;for(GtkWidget *p=gtk_widget_get_first_child(ui->list);p;p=gtk_widget_get_next_sibling(p))if(GTK_IS_LIST_BOX_ROW(p)&&gtk_widget_get_child_visible(p))n++;return n;
}
int main(int argc,char **argv) {
    g_assert_cmpint(argc,==,2);setlocale(LC_ALL,"");
    g_autofree char *suffix=g_strdup_printf("test-config-%" G_GINT64_FORMAT,g_get_monotonic_time());
    g_autofree char *config=g_build_filename(argv[1],suffix,NULL);g_mkdir_with_parents(config,0700);g_setenv("XDG_CONFIG_HOME",config,TRUE);gtk_init();
    g_autoptr(GtkApplication) app=gtk_application_new("org.kiki.Operations.Test",G_APPLICATION_NON_UNIQUE);
    g_assert_true(g_application_register(G_APPLICATION(app),NULL,NULL));Ops ui={0};activate(G_APPLICATION(app),&ui);
    gint64 deadline=g_get_monotonic_time()+15000000;
    while((!ui.data || ui.summary) && g_get_monotonic_time()<deadline)settle();
    g_assert_nonnull(ui.data);g_assert_nonnull(ui.settings);g_assert_cmpuint(visible_rows(&ui),>,0);
    if(ui.timer)g_source_remove(ui.timer);
    ui.timer=0;
    GtkListBoxRow *row=gtk_list_box_get_row_at_index(GTK_LIST_BOX(ui.list),0);g_assert_nonnull(row);gtk_list_box_select_row(GTK_LIST_BOX(ui.list),row);
    g_assert_cmpstr(gtk_label_get_text(GTK_LABEL(ui.selected)),==,g_object_get_data(G_OBJECT(row),"unit"));
    gtk_editable_set_text(GTK_EDITABLE(ui.search),"definitely-no-such-kiki-service-123456");g_signal_emit_by_name(ui.search,"search-changed");g_assert_cmpuint(visible_rows(&ui),==,0);
    gtk_editable_set_text(GTK_EDITABLE(ui.search),"");g_signal_emit_by_name(ui.search,"search-changed");g_assert_cmpuint(visible_rows(&ui),>,0);
    gtk_check_button_set_active(GTK_CHECK_BUTTON(ui.filter),TRUE);
    for(GtkWidget *p=gtk_widget_get_first_child(ui.list);p;p=gtk_widget_get_next_sibling(p))if(GTK_IS_LIST_BOX_ROW(p)&&gtk_widget_get_child_visible(p))g_assert_true(GPOINTER_TO_INT(g_object_get_data(G_OBJECT(p),"failed")));
    capture(&ui,argv[1],"failed-filter.png");gtk_check_button_set_active(GTK_CHECK_BUTTON(ui.filter),FALSE);
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(ui.light),TRUE);capture(&ui,argv[1],"operations-light.png");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(ui.dark),TRUE);capture(&ui,argv[1],"operations-dark.png");
    g_settings_sync();
    g_autofree char *saved=NULL,*settings_file=g_build_filename(config,"kiki-operations","settings.ini",NULL);
    g_assert_true(g_file_get_contents(settings_file,&saved,NULL,NULL));g_assert_nonnull(strstr(saved,"theme='dark'"));
    GtkListBoxRow *second=gtk_list_box_get_row_at_index(GTK_LIST_BOX(ui.list),1);g_assert_nonnull(second);
    g_autofree char *first_unit=g_strdup(ui.unit);
    guint64 old_generation=ui.selection_generation;
    connections_open_logs(NULL,&ui);
    gtk_text_buffer_set_text(ui.log_buffer,"PRIVATE_PREVIOUS_SERVICE",-1);
    gtk_list_box_select_row(GTK_LIST_BOX(ui.list),second);
    g_assert_cmpuint(ui.selection_generation,>,old_generation);
    GtkTextIter start,end;gtk_text_buffer_get_bounds(ui.log_buffer,&start,&end);
    g_autofree char *cleared=gtk_text_buffer_get_text(ui.log_buffer,&start,&end,FALSE);g_assert_cmpstr(cleared,==,"");
    Connection stale={.ui=&ui,.unit=first_unit,.generation=old_generation,.kind=CONN_SYSTEM};g_assert_false(connections_current(&ui,&stale));
    deadline=g_get_monotonic_time()+20000000;while(ui.connection&&g_get_monotonic_time()<deadline)settle();g_assert_null(ui.connection);
    g_assert_cmpstr(gtk_label_get_text(GTK_LABEL(ui.log_unit)),==,ui.unit);g_assert_nonnull(strstr(gtk_label_get_text(GTK_LABEL(ui.log_scope)),"사용자 로그"));capture(&ui,argv[1],"service-user-logs.png");
    connections_system(NULL,&ui);deadline=g_get_monotonic_time()+20000000;while(ui.connection&&g_get_monotonic_time()<deadline)settle();g_assert_nonnull(ui.log_review);connections_review_cancel(NULL,&ui);g_assert_null(ui.log_review);
    connections_open_terminal(NULL,&ui);deadline=g_get_monotonic_time()+20000000;while(ui.connection&&g_get_monotonic_time()<deadline)settle();g_assert_nonnull(ui.terminal_argv);g_assert_cmpstr(ui.terminal_argv[4],==,ui.unit);
    gtk_drop_down_set_selected(GTK_DROP_DOWN(ui.terminal_mode),1);deadline=g_get_monotonic_time()+20000000;while(ui.connection&&g_get_monotonic_time()<deadline)settle();g_assert_nonnull(ui.terminal_argv);g_assert_cmpstr(ui.terminal_argv[3],==,"logs");capture(&ui,argv[1],"service-console-plan.png");
    gtk_text_buffer_set_text(ui.log_buffer,"SERVICE_CONTEXT_SECOND\npassword=fixture-secret\nRECENT_LOG_END",-1);ui.log_loaded=TRUE;ui.log_system_result=FALSE;incident_logs_changed(&ui);
    incident_open_page(NULL,&ui);deadline=g_get_monotonic_time()+20000000;while(ui.connection&&g_get_monotonic_time()<deadline)settle();g_assert_nonnull(ui.incident_url);
    g_autofree char *without_logs=incident_draft(&ui);g_assert_null(strstr(without_logs,"SERVICE_CONTEXT_SECOND"));
    gtk_check_button_set_active(GTK_CHECK_BUTTON(ui.incident_include),TRUE);deadline=g_get_monotonic_time()+20000000;while(ui.connection&&g_get_monotonic_time()<deadline)settle();
    g_autofree char *draft=incident_draft(&ui);g_assert_nonnull(strstr(draft,ui.unit));g_assert_nonnull(strstr(draft,"SERVICE_CONTEXT_SECOND"));g_assert_null(strstr(draft,"fixture-secret"));g_assert_cmpuint(incident_length(draft),<=,1000);
    g_assert_true(incident_ready(&ui));g_assert_true(incident_copy_context(&ui));g_assert_nonnull(ui.incident_clipboard);
    capture(&ui,argv[1],"incident-context-review.png");
    g_autofree char *oversized=g_strnfill(1001,'a');gtk_text_buffer_set_text(ui.incident_buffer,oversized,-1);g_assert_false(incident_ready(&ui));g_assert_false(gtk_widget_get_sensitive(ui.incident_copy));g_assert_null(ui.incident_clipboard);
    gtk_text_buffer_set_text(ui.incident_buffer,draft,-1);g_assert_true(incident_copy_context(&ui));
    gtk_list_box_select_row(GTK_LIST_BOX(ui.list),gtk_list_box_get_row_at_index(GTK_LIST_BOX(ui.list),0));
    g_assert_null(ui.incident_clipboard);g_autofree char *empty_draft=incident_draft(&ui);g_assert_cmpstr(empty_draft,==,"");
    deadline=g_get_monotonic_time()+20000000;while(ui.connection&&g_get_monotonic_time()<deadline)settle();
    gtk_stack_set_visible_child_name(GTK_STACK(ui.stack),"overview");gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(ui.navigation[0]),TRUE);connections_page_changed(&ui);
    settle();settle();
    int minimum=0,natural=0;gtk_widget_measure(GTK_WIDGET(ui.window),GTK_ORIENTATION_HORIZONTAL,-1,&minimum,&natural,NULL,NULL);
    g_print("Before resize: minimum=%d natural=%d maximized=%d\n",minimum,natural,gtk_window_is_maximized(ui.window));
    gtk_window_unmaximize(ui.window);deadline=g_get_monotonic_time()+5000000;
    while(gtk_window_is_maximized(ui.window)&&g_get_monotonic_time()<deadline)settle();
    gtk_window_set_default_size(ui.window,900,700);deadline=g_get_monotonic_time()+5000000;
    while(gtk_widget_get_width(GTK_WIDGET(ui.window))>930&&g_get_monotonic_time()<deadline)settle();
    layout(&ui);capture(&ui,argv[1],"operations-compact.png");
    g_print("Compact actual size: %dx%d\n",gtk_widget_get_width(GTK_WIDGET(ui.window)),gtk_widget_get_height(GTK_WIDGET(ui.window)));
    g_assert_cmpint(gtk_widget_get_width(GTK_WIDGET(ui.window)),<=,930);
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(ui.light),TRUE);
    g_object_set(gtk_settings_get_default(),"gtk-theme-name","HighContrast",NULL);capture(&ui,argv[1],"operations-high-contrast.png");
    request(&ui,FALSE);connections_begin(&ui,CONN_USER,NULL);closing(ui.window,&ui);gtk_window_destroy(ui.window);
    deadline=g_get_monotonic_time()+5000000;
    while((ui.runtime || ui.summary || ui.connection) && g_get_monotonic_time()<deadline)settle();
    g_assert_null(ui.runtime);g_assert_null(ui.summary);g_assert_cmpuint(ui.timer,==,0);g_assert_cmpuint(ui.layout_timer,==,0);
    g_assert_null(ui.connection);
    g_clear_object(&ui.data);g_clear_object(&ui.settings);g_clear_object(&ui.css);g_strfreev(ui.terminal_argv);g_free(ui.unit);g_free(ui.log_observed_at);g_free(ui.incident_url);
    g_print("PASS: runtime, service logs, Console plan, reviewed incident context, masking, UTF-16 limit, clipboard invalidation, themes, compact, close during query\n");return 0;
}
