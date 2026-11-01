#define main kiki_admin_application_main
#include "main.c"
#undef main
#include <glib/gstdio.h>

static void settle(void) {
    gint64 until=g_get_monotonic_time()+250000;
    do { while(g_main_context_iteration(NULL,FALSE)) {} g_usleep(1000); } while(g_get_monotonic_time()<until);
}
static void capture(GtkWindow *window,const char *directory,const char *name) {
    settle(); GtkWidget *widget=GTK_WIDGET(window);
    g_autoptr(GdkPaintable) paintable=gtk_widget_paintable_new(widget);
    GtkSnapshot *snapshot=gtk_snapshot_new();
    gdk_paintable_snapshot(paintable,GDK_SNAPSHOT(snapshot),gtk_widget_get_width(widget),gtk_widget_get_height(widget));
    GskRenderNode *node=gtk_snapshot_free_to_node(snapshot); g_assert_nonnull(node);
    GskRenderer *renderer=gsk_renderer_new_for_surface(gtk_native_get_surface(GTK_NATIVE(window)));
    graphene_rect_t viewport=GRAPHENE_RECT_INIT(0,0,gtk_widget_get_width(widget),gtk_widget_get_height(widget));
    g_autoptr(GdkTexture) texture=gsk_renderer_render_texture(renderer,node,&viewport);
    g_autofree char *path=g_build_filename(directory,name,NULL); g_assert_true(gdk_texture_save_to_png(texture,path));
    gsk_renderer_unrealize(renderer); g_object_unref(renderer); gsk_render_node_unref(node);
}
static GtkWidget *find_type(GtkWidget *root,GType type) {
    if(G_TYPE_CHECK_INSTANCE_TYPE(root,type)) return root;
    for(GtkWidget *child=gtk_widget_get_first_child(root);child;child=gtk_widget_get_next_sibling(child)) {
        GtkWidget *result=find_type(child,type); if(result) return result;
    }
    return NULL;
}
int main(int argc,char **argv) {
    g_assert_cmpint(argc,==,3); setlocale(LC_ALL,""); adw_init();
    g_autoptr(AdwApplication) app=adw_application_new("org.kiki.Admin.Test",G_APPLICATION_NON_UNIQUE);
    g_assert_true(g_application_register(G_APPLICATION(app),NULL,NULL));
    Admin ui={0}; ui.snapshot=json_parser_new();
    g_assert_true(json_parser_load_from_file(ui.snapshot,argv[1],NULL));
    activate(G_APPLICATION(app),&ui); settle();
    GtkListBox *navigation=GTK_LIST_BOX(find_type(GTK_WIDGET(ui.window),GTK_TYPE_LIST_BOX));
    g_assert_nonnull(navigation);
    const char *names[]={"overview","packages","repositories","diagnostics"}, *files[]={"overview.png","packages.png","repositories.png","diagnostics.png"};
    for(guint i=0;i<4;i++) {
        gtk_list_box_select_row(navigation,gtk_list_box_get_row_at_index(navigation,i)); capture(ui.window,argv[2],files[i]);
        g_assert_cmpstr(gtk_stack_get_visible_child_name(ui.stack),==,names[i]);
    }
    GtkWidget *search=find_type(ui.pages[1],GTK_TYPE_SEARCH_ENTRY); g_assert_nonnull(search);
    GtkWidget *list=gtk_widget_get_next_sibling(search); g_assert_true(GTK_IS_LIST_BOX(list));
    gtk_editable_set_text(GTK_EDITABLE(search),"no-such-package-987654321"); g_signal_emit_by_name(search,"search-changed"); settle();
    for(GtkWidget *r=gtk_widget_get_first_child(list);r;r=gtk_widget_get_next_sibling(r)) g_assert_false(gtk_widget_get_child_visible(r));
    gtk_editable_set_text(GTK_EDITABLE(search),""); g_signal_emit_by_name(search,"search-changed"); settle();
    GtkWidget *first=gtk_widget_get_first_child(list); if(first) g_assert_true(gtk_widget_get_child_visible(first));
    g_autoptr(JsonParser) plan=json_parser_new();
    g_assert_true(json_parser_load_from_data(plan,"{\"action\":\"upgrade\",\"target\":\"\",\"token\":\"test-token\",\"description\":\"업데이트 계획\",\"details\":\"검토만 하는 화면입니다. 패키지를 변경하지 않습니다.\"}",-1,NULL));
    review(&ui,json_node_get_object(json_parser_get_root(plan))); settle();
    GtkWindow *dialog=NULL; GListModel *windows=gtk_window_get_toplevels();
    for(guint i=0;i<g_list_model_get_n_items(windows);i++) { GtkWindow *w=g_list_model_get_item(windows,i);
        if(g_strcmp0(gtk_window_get_title(w),"변경 내용 확인")==0) dialog=w; else g_object_unref(w); }
    g_assert_nonnull(dialog); g_assert_nonnull(g_object_get_data(G_OBJECT(dialog),"review"));
    capture(dialog,argv[2],"review.png"); gtk_window_destroy(dialog); g_object_unref(dialog);
    gtk_window_unmaximize(ui.window); settle();
    gtk_window_set_default_size(ui.window,800,600); gtk_list_box_select_row(navigation,gtk_list_box_get_row_at_index(navigation,0)); capture(ui.window,argv[2],"overview-compact.png");
    ui.busy=TRUE; g_assert_true(close_requested(ui.window,&ui)); ui.busy=FALSE;
    gtk_window_destroy(ui.window); g_clear_object(&ui.snapshot); g_clear_object(&ui.activity);
    g_print("PASS: four pages, package filtering, review/cancel, compact layout, busy close guard\n"); return 0;
}
