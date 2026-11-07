#include <gtk/gtk.h>
#include <json-glib/json-glib.h>
#define G_SETTINGS_ENABLE_BACKEND
#include <gio/gsettingsbackend.h>
#include <glib/gstdio.h>
#include <locale.h>

#define DATA "/usr/share/kiki-operations/"
typedef struct {
    GtkApplication *app;
    GtkWindow *window;
    GtkWidget *stack, *list, *search, *filter, *paned, *detail;
    GtkWidget *cpu, *memory, *disk, *failed, *status, *host, *warning, *selected, *details, *count;
    GtkWidget *bars[3], *light, *dark;
    GSettings *settings;
    GtkCssProvider *css;
    GSubprocess *runtime, *summary;
    guint timer, layout_timer, deadline[2];
    gboolean closing, compact;
    JsonParser *data;
    char *unit;
    GtkWidget *navigation[5], *log_unit, *log_notice, *log_scope, *log_refresh, *log_system;
    GtkWidget *terminal_unit, *terminal_preview, *terminal_launch, *terminal_mode, *terminal_notice;
    GtkTextBuffer *log_buffer;
    GtkWindow *log_review;
    GSubprocess *connection;
    guint connection_deadline;
    guint64 selection_generation, terminal_generation;
    int connection_kind;
    gboolean want_logs, want_terminal;
    char **terminal_argv;
    gboolean log_loaded, log_system_result, want_incident;
    char *log_observed_at, *incident_url;
    GtkWidget *incident_unit, *incident_scope, *incident_include, *incident_notice, *incident_counter;
    GtkWidget *incident_editor, *incident_copy, *incident_open, *incident_prepare;
    GtkTextBuffer *incident_buffer;
    guint64 incident_revision, incident_valid_generation;
    GdkContentProvider *incident_clipboard;
} Ops;
typedef struct { Ops *ui; gboolean summary; } Request;

static const char *text(JsonObject *o,const char *key) {
    if(!json_object_has_member(o,key) || JSON_NODE_HOLDS_NULL(json_object_get_member(o,key))) return "";
    return json_object_get_string_member(o,key);
}
static gboolean value(JsonObject *o,const char *key,double *out) {
    if(!json_object_has_member(o,key) || JSON_NODE_HOLDS_NULL(json_object_get_member(o,key))) return FALSE;
    *out=json_object_get_double_member(o,key); return TRUE;
}
static GtkWidget *label(const char *s,const char *css) {
    GtkWidget *w=gtk_label_new(s); gtk_label_set_xalign(GTK_LABEL(w),0);
    if(css) gtk_widget_add_css_class(w,css);
    return w;
}
static GtkWidget *wrap(const char *s,const char *css) {
    GtkWidget *w=label(s,css); gtk_label_set_wrap(GTK_LABEL(w),TRUE);gtk_label_set_wrap_mode(GTK_LABEL(w),PANGO_WRAP_WORD_CHAR);return w;
}
static GtkWidget *box(GtkOrientation orientation,int spacing) { return gtk_box_new(orientation,spacing); }
static void append(GtkWidget *parent,GtkWidget *child) { gtk_box_append(GTK_BOX(parent),child); }
static void set(GtkWidget *w,const char *s) { gtk_label_set_text(GTK_LABEL(w),s); }
static GtkWidget *button(const char *s,GCallback callback,Ops *ui);
static void incident_controls(Ops *ui);
static void incident_context_changed(Ops *ui);
static void incident_logs_changed(Ops *ui);
static void incident_result(Ops *ui,JsonObject *o);
static char *incident_input(Ops *ui);
static void incident_open_page(GtkButton *b,gpointer data);
#include "connections.h"
#include "incident.h"
static const char *state(JsonObject *row) {
    const char *active=text(row,"active"), *sub=text(row,"sub");
    if(!strcmp(active,"failed")) return "■ 실패";
    if(!strcmp(active,"active")) return !strcmp(sub,"exited") ? "■ 활성 · 완료" : "■ 실행 중";
    if(!strcmp(active,"inactive")) return "□ 중지";
    if(!strcmp(active,"activating")) return "▷ 시작 중";
    if(!strcmp(active,"deactivating")) return "□ 중지 중";
    return active;
}
static void detail(Ops *ui) {
    set(ui->selected,ui->unit ? ui->unit : "서비스 선택");
    if(!ui->unit || !ui->data) { set(ui->details,"목록에서 서비스를 선택하면 실제 상태와 설명을 표시합니다."); return; }
    JsonObject *root=json_node_get_object(json_parser_get_root(ui->data));
    JsonArray *rows=json_object_get_array_member(root,"services");
    for(guint i=0; rows && i<json_array_get_length(rows); i++) {
        JsonObject *row=json_array_get_object_element(rows,i);
        if(strcmp(text(row,"unit"),ui->unit)) continue;
        g_autofree char *s=g_strdup_printf("%s\n\n%s\n\n로드: %s\n하위 상태: %s",state(row),text(row,"description"),text(row,"load"),text(row,"sub"));
        set(ui->details,s); return;
    }
    set(ui->details,"이 서비스는 최신 목록에서 확인되지 않습니다. 다시 선택하세요.");
}
static void selected(GtkListBox *list,GtkListBoxRow *row,gpointer data) {
    (void)list; Ops *ui=data;
    if(!row) return;
    const char *unit=g_object_get_data(G_OBJECT(row),"unit");
    gboolean changed=g_strcmp0(ui->unit,unit)!=0;
    g_free(ui->unit); ui->unit=g_strdup(unit); detail(ui);
    if(changed)connections_context_changed(ui);
}
static gboolean filter_row(GtkListBoxRow *row,gpointer data) {
    Ops *ui=data;
    if(gtk_check_button_get_active(GTK_CHECK_BUTTON(ui->filter)) && !GPOINTER_TO_INT(g_object_get_data(G_OBJECT(row),"failed"))) return FALSE;
    const char *needle=gtk_editable_get_text(GTK_EDITABLE(ui->search));
    g_autofree char *hay=g_utf8_casefold(g_object_get_data(G_OBJECT(row),"search"),-1);
    g_autofree char *lower=g_utf8_casefold(needle,-1);
    return !*lower || strstr(hay,lower)!=NULL;
}
static void search_changed(GtkSearchEntry *entry,gpointer data) { (void)entry; gtk_list_box_invalidate_filter(GTK_LIST_BOX(((Ops*)data)->list)); }
static void filter_changed(GtkCheckButton *button,gpointer data) {
    Ops *ui=data; gtk_list_box_invalidate_filter(GTK_LIST_BOX(ui->list));
    if(ui->settings) g_settings_set_boolean(ui->settings,"failed-only",gtk_check_button_get_active(button));
}
static void theme(Ops *ui,gboolean dark) {
    g_autofree char *base=NULL,*palette=NULL,*name=NULL;
    g_file_get_contents(DATA "style.css",&base,NULL,NULL);
    g_object_get(gtk_settings_get_default(),"gtk-theme-name",&name,NULL);
    gboolean contrast=name && strstr(name,"HighContrast");
    if(!contrast)g_file_get_contents(dark ? DATA "dark.css" : DATA "light.css",&palette,NULL,NULL);
    g_autofree char *css=g_strconcat(base ? base : "", "\n",palette ? palette : ".kiki-operations .muted { opacity: 1; }",NULL);
    gtk_css_provider_load_from_string(ui->css,css);
    if(ui->settings && !g_settings_set_string(ui->settings,"theme",dark ? "dark" : "light") && ui->status)
        set(ui->status,"테마 설정을 저장하지 못했습니다.");
}
static void system_theme_changed(GtkSettings *settings,GParamSpec *spec,gpointer data) {
    (void)settings;(void)spec;Ops *ui=data;
    if(!ui->closing)theme(ui,gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(ui->dark)));
}
static void theme_toggled(GtkToggleButton *button,gpointer data) {
    Ops *ui=data; if(gtk_toggle_button_get_active(button)) theme(ui,GTK_WIDGET(button)==ui->dark);
}
static void launch_admin(GtkButton *button,gpointer data) {
    (void)button; Ops *ui=data;
    g_autoptr(GError) error=NULL;
    g_autoptr(GAppInfo) app=g_app_info_create_from_commandline("/usr/bin/kiki-admin --page diagnostics","KIKI 관리자",G_APP_INFO_CREATE_SUPPORTS_STARTUP_NOTIFICATION,&error);
    g_autoptr(GdkAppLaunchContext) context=gdk_display_get_app_launch_context(gtk_widget_get_display(GTK_WIDGET(ui->window)));
    if(!app || !g_app_info_launch(app,NULL,G_APP_LAUNCH_CONTEXT(context),&error)) set(ui->status,error ? error->message : "관리자를 열 수 없습니다.");
}
static GtkWidget *button(const char *s,GCallback callback,Ops *ui) {
    GtkWidget *w=gtk_button_new_with_label(s);
    if(callback) g_signal_connect(w,"clicked",callback,ui);
    return w;
}
static void navigate(GtkButton *button,gpointer data) {
    Ops *ui=data; const char *page=g_object_get_data(G_OBJECT(button),"page");
    gtk_stack_set_visible_child_name(GTK_STACK(ui->stack),!strcmp(page,"services") ? "overview" : page);
    if(!strcmp(page,"services")) gtk_widget_grab_focus(ui->search);
    connections_page_changed(ui);
}
static void render(Ops *ui,JsonParser *parser) {
    JsonObject *root=json_node_get_object(json_parser_get_root(parser));
    double n;
    if(value(root,"cpu_percent",&n)) {
        g_autofree char *s=g_strdup_printf("%.1f%%",n); set(ui->cpu,s); gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(ui->bars[0]),CLAMP(n/100,0,1));
    } else { set(ui->cpu,"조회 불가"); gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(ui->bars[0]),0); }
    for(int i=0;i<2;i++) {
        const char *key=i==0 ? "memory" : "disk"; GtkWidget *w=i==0 ? ui->memory : ui->disk;
        JsonNode *node=json_object_get_member(root,key);
        if(node && !JSON_NODE_HOLDS_NULL(node)) {
            JsonObject *o=json_node_get_object(node); double percent=0,total=0,used=0;
            value(o,"percent",&percent); value(o,"total_bytes",&total); value(o,"used_bytes",&used);
            g_autofree char *s=i==0 ? g_strdup_printf("%.1f / %.1f GiB",used/1073741824,total/1073741824) : g_strdup_printf("%.1f%%",percent);
            set(w,s); gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(ui->bars[i+1]),CLAMP(percent/100,0,1));
        } else { set(w,"조회 불가"); gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(ui->bars[i+1]),0); }
    }
    g_autofree char *host=g_strdup_printf("로컬 · %s",text(root,"hostname")); set(ui->host,host);
    if(value(root,"failed_count",&n)) { g_autofree char *s=g_strdup_printf("%.0f개",n);set(ui->failed,s); }
    else set(ui->failed,"조회 불가");
    JsonArray *warnings=json_object_get_array_member(root,"warnings");
    g_autoptr(GString) warning=g_string_new("");
    for(guint i=0;warnings && i<json_array_get_length(warnings);i++) { if(i)g_string_append(warning,"\n");g_string_append(warning,json_array_get_string_element(warnings,i)); }
    set(ui->warning,warning->str);gtk_widget_set_visible(ui->warning,warning->len>0);
    g_autofree char *status=g_strdup_printf("%s · %s",warning->len ? "일부 조회 제한" : "갱신 완료",text(root,"observed_at")); set(ui->status,status);
    JsonNode *node=json_object_get_member(root,"services");
    if(!node || JSON_NODE_HOLDS_NULL(node)) { set(ui->count,"서비스 조회 실패 · 이전 목록은 최신 상태가 아닙니다.");return; }
    g_set_object(&ui->data,parser);
    GtkWidget *child;while((child=gtk_widget_get_first_child(ui->list)))gtk_list_box_remove(GTK_LIST_BOX(ui->list),child);
    JsonArray *rows=json_node_get_array(node); GtkListBoxRow *restore=NULL;
    for(guint i=0;i<json_array_get_length(rows);i++) {
        JsonObject *o=json_array_get_object_element(rows,i);GtkWidget *row=gtk_list_box_row_new(),*line=box(GTK_ORIENTATION_HORIZONTAL,12);
        gtk_widget_add_css_class(line,"service-row");
        GtkWidget *unit=label(text(o,"unit"),"code");gtk_label_set_ellipsize(GTK_LABEL(unit),PANGO_ELLIPSIZE_END);
        gtk_widget_set_size_request(unit,170,-1);gtk_widget_set_hexpand(unit,TRUE); append(line,unit);
        GtkWidget *st=label(state(o),!strcmp(text(o,"active"),"failed") ? "bad" : NULL);gtk_widget_set_size_request(st,105,-1);append(line,st);
        GtkWidget *desc=label(text(o,"description"),"muted");gtk_label_set_ellipsize(GTK_LABEL(desc),PANGO_ELLIPSIZE_END);gtk_widget_set_hexpand(desc,TRUE);append(line,desc);
        gtk_list_box_row_set_child(GTK_LIST_BOX_ROW(row),line);
        g_object_set_data_full(G_OBJECT(row),"unit",g_strdup(text(o,"unit")),g_free);
        g_object_set_data_full(G_OBJECT(row),"search",g_strdup_printf("%s %s",text(o,"unit"),text(o,"description")),g_free);
        g_object_set_data(G_OBJECT(row),"failed",GINT_TO_POINTER(!strcmp(text(o,"active"),"failed")));
        gtk_list_box_append(GTK_LIST_BOX(ui->list),row);
        if(ui->unit && !strcmp(ui->unit,text(o,"unit")))restore=GTK_LIST_BOX_ROW(row);
    }
    if(restore)gtk_list_box_select_row(GTK_LIST_BOX(ui->list),restore);
    else if(ui->unit) { g_clear_pointer(&ui->unit,g_free);connections_context_changed(ui); }
    g_autofree char *count=g_strdup_printf("로드된 서비스 %u개 · 실제 상태 조회",json_array_get_length(rows));set(ui->count,count);detail(ui);
}
static gboolean runtime_deadline(gpointer data) { Ops *ui=data;ui->deadline[0]=0;if(ui->runtime)g_subprocess_force_exit(ui->runtime);return G_SOURCE_REMOVE; }
static gboolean summary_deadline(gpointer data) { Ops *ui=data;ui->deadline[1]=0;if(ui->summary)g_subprocess_force_exit(ui->summary);return G_SOURCE_REMOVE; }
static void finished(GObject *source,GAsyncResult *result,gpointer data) {
    Request *r=data;Ops *ui=r->ui;g_autofree char *out=NULL,*err=NULL;g_autoptr(GError) error=NULL;
    gboolean success=g_subprocess_communicate_utf8_finish(G_SUBPROCESS(source),result,&out,&err,&error);
    int slot=r->summary ? 1 : 0;
    if(ui->deadline[slot]) { g_source_remove(ui->deadline[slot]);ui->deadline[slot]=0; }
    if(!ui->closing) {
        g_autoptr(JsonParser) parser=json_parser_new();JsonObject *o=NULL;
        if(success && out && strlen(out)<2*1024*1024 && json_parser_load_from_data(parser,out,-1,NULL) && JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser)))o=json_node_get_object(json_parser_get_root(parser));
        if(!o || !g_subprocess_get_successful(G_SUBPROCESS(source)) || !json_object_has_member(o,"ok") || !json_object_get_boolean_member(o,"ok") || strcmp(text(o,"schema"),"kiki-operations-v1"))
            set(ui->status,r->summary ? "관리자 요약 조회 실패 · 상태 조회는 계속됩니다." : "상태 조회 실패 · 이전 표시 값은 최신 상태가 아닙니다.");
        else if(r->summary) {
            g_autofree char *s=g_strdup_printf("%s · %s · 설치 %.0f개",text(o,"os"),text(o,"kernel"),json_object_get_double_member(o,"installed_count"));
            gtk_widget_set_tooltip_text(ui->host,s);
        } else render(ui,parser);
    }
    g_clear_object(r->summary ? &ui->summary : &ui->runtime);
    g_application_release(G_APPLICATION(ui->app));g_free(r);
}
static void request(Ops *ui,gboolean summary) {
    if(ui->closing || (summary ? ui->summary : ui->runtime))return;
    g_autoptr(GError) error=NULL;
    GSubprocess *p=g_subprocess_new(G_SUBPROCESS_FLAGS_STDOUT_PIPE|G_SUBPROCESS_FLAGS_STDERR_PIPE,&error,"/usr/bin/kiki-operationsctl",summary ? "summary" : "runtime",NULL);
    if(!p) { set(ui->status,error->message);return; }
    if(summary)ui->summary=p;else ui->runtime=p;
    Request *r=g_new0(Request,1);r->ui=ui;r->summary=summary;
    g_application_hold(G_APPLICATION(ui->app));
    ui->deadline[summary ? 1 : 0]=g_timeout_add_seconds(summary ? 30 : 12,summary ? summary_deadline : runtime_deadline,ui);
    g_subprocess_communicate_utf8_async(p,NULL,NULL,finished,r);
}
static gboolean refresh(gpointer data) { request(data,FALSE);return G_SOURCE_CONTINUE; }
static void manual(GtkButton *b,gpointer data) { (void)b;request(data,FALSE);request(data,TRUE); }
static gboolean layout(gpointer data) {
    Ops *ui=data;gboolean compact=gtk_widget_get_width(ui->stack)<820;
    if(compact!=ui->compact) {
        ui->compact=compact;gtk_orientable_set_orientation(GTK_ORIENTABLE(ui->paned),compact ? GTK_ORIENTATION_VERTICAL : GTK_ORIENTATION_HORIZONTAL);
        gtk_widget_set_size_request(ui->detail,compact ? -1 : 255,-1);
        gtk_paned_set_position(GTK_PANED(ui->paned),compact ? 330 : 760);
    }
    return G_SOURCE_CONTINUE;
}
static gboolean closing(GtkWindow *w,gpointer data) {
    (void)w;Ops *ui=data;ui->closing=TRUE;
    connections_stop(ui);
    incident_stop(ui);
    if(ui->timer)g_source_remove(ui->timer);
    ui->timer=0;
    if(ui->layout_timer)g_source_remove(ui->layout_timer);
    ui->layout_timer=0;
    if(ui->runtime)g_subprocess_force_exit(ui->runtime);
    if(ui->summary)g_subprocess_force_exit(ui->summary);
    return FALSE;
}
static GtkWidget *metric(const char *title,GtkWidget **number,GtkWidget **bar) {
    GtkWidget *w=box(GTK_ORIENTATION_VERTICAL,7);gtk_widget_add_css_class(w,"metric");append(w,label(title,NULL));
    *number=label("—","value");append(w,*number);
    if(bar) { *bar=gtk_progress_bar_new();append(w,*bar); }return w;
}
static GtkWidget *placeholder(const char *title,const char *description,Ops *ui,gboolean admin) {
    GtkWidget *w=box(GTK_ORIENTATION_VERTICAL,18);gtk_widget_add_css_class(w,"workspace");append(w,label(title,"title"));append(w,wrap(description,NULL));
    if(admin)append(w,button("기존 관리자에서 확인 ↗",G_CALLBACK(launch_admin),ui));
    return w;
}
static void activate(GApplication *app,gpointer data) {
    Ops *ui=data;if(ui->closing)return;if(ui->window) { gtk_window_present(ui->window);return; }
    ui->app=GTK_APPLICATION(app);ui->window=GTK_WINDOW(gtk_application_window_new(ui->app));
    gtk_window_set_title(ui->window,"KIKI 운영");gtk_window_set_default_size(ui->window,1320,850);
    gtk_widget_add_css_class(GTK_WIDGET(ui->window),"kiki-operations");g_signal_connect(ui->window,"close-request",G_CALLBACK(closing),ui);
    ui->css=gtk_css_provider_new();gtk_style_context_add_provider_for_display(gtk_widget_get_display(GTK_WIDGET(ui->window)),GTK_STYLE_PROVIDER(ui->css),GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    GSettingsSchemaSource *source=g_settings_schema_source_get_default();
    GSettingsSchema *schema=source ? g_settings_schema_source_lookup(source,"org.kiki.Operations",TRUE) : NULL;
    if(schema) {
        g_autofree char *directory=g_build_filename(g_get_user_config_dir(),"kiki-operations",NULL);
        g_mkdir_with_parents(directory,0700);
        g_autofree char *path=g_build_filename(directory,"settings.ini",NULL);
        g_autoptr(GSettingsBackend) backend=g_keyfile_settings_backend_new(path,"/org/kiki/operations/","preferences");
        ui->settings=g_settings_new_full(schema,backend,NULL);g_settings_schema_unref(schema);
    }
    GtkWidget *header=gtk_header_bar_new();gtk_window_set_titlebar(ui->window,header);
    GtkWidget *brand=box(GTK_ORIENTATION_HORIZONTAL,10),*icon=gtk_image_new_from_file("/usr/share/icons/hicolor/scalable/apps/org.kiki.Operations.svg");gtk_image_set_pixel_size(GTK_IMAGE(icon),28);append(brand,icon);append(brand,label("KIKI 운영","section-title"));gtk_header_bar_pack_start(GTK_HEADER_BAR(header),brand);
    ui->host=label("로컬 · 확인 중",NULL);gtk_header_bar_set_title_widget(GTK_HEADER_BAR(header),ui->host);
    gtk_header_bar_pack_end(GTK_HEADER_BAR(header),button("새로 확인",G_CALLBACK(manual),ui));
    ui->light=gtk_toggle_button_new_with_label("라이트");ui->dark=gtk_toggle_button_new_with_label("다크");gtk_toggle_button_set_group(GTK_TOGGLE_BUTTON(ui->dark),GTK_TOGGLE_BUTTON(ui->light));
    gtk_header_bar_pack_end(GTK_HEADER_BAR(header),ui->dark);gtk_header_bar_pack_end(GTK_HEADER_BAR(header),ui->light);
    g_signal_connect(ui->light,"toggled",G_CALLBACK(theme_toggled),ui);g_signal_connect(ui->dark,"toggled",G_CALLBACK(theme_toggled),ui);
    g_signal_connect(gtk_settings_get_default(),"notify::gtk-theme-name",G_CALLBACK(system_theme_changed),ui);
    g_autofree char *mode=ui->settings ? g_settings_get_string(ui->settings,"theme") : g_strdup("light");gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(!strcmp(mode,"dark") ? ui->dark : ui->light),TRUE);
    GtkWidget *outer=box(GTK_ORIENTATION_VERTICAL,0),*body=box(GTK_ORIENTATION_HORIZONTAL,0);gtk_window_set_child(ui->window,outer);gtk_widget_set_vexpand(body,TRUE);append(outer,body);
    GtkWidget *nav=box(GTK_ORIENTATION_VERTICAL,9);gtk_widget_add_css_class(nav,"sidebar");gtk_widget_set_size_request(nav,148,-1);append(body,nav);
    const char *names[]={"overview","services","logs","terminal","incident"},*titles[]={"▦  운영 개요","▤  서비스","▥  로그","›_  터미널","↗  incident-ai"};
    GtkToggleButton *group=NULL;
    for(guint i=0;i<5;i++) {
        GtkWidget *b=gtk_toggle_button_new_with_label(titles[i]);
        if(group)gtk_toggle_button_set_group(GTK_TOGGLE_BUTTON(b),group);else group=GTK_TOGGLE_BUTTON(b);
        g_signal_connect(b,"clicked",G_CALLBACK(navigate),ui);
        gtk_widget_add_css_class(b,"nav");g_object_set_data(G_OBJECT(b),"page",(gpointer)names[i]);append(nav,b);
        ui->navigation[i]=b;
        if(i==0)gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(b),TRUE);
    }
    GtkWidget *spacer=box(GTK_ORIENTATION_VERTICAL,0);gtk_widget_set_vexpand(spacer,TRUE);append(nav,spacer);append(nav,label("■ 로컬 연결","muted"));append(nav,button("기존 관리자 ↗",G_CALLBACK(launch_admin),ui));
    ui->stack=gtk_stack_new();gtk_stack_set_hhomogeneous(GTK_STACK(ui->stack),FALSE);gtk_stack_set_vhomogeneous(GTK_STACK(ui->stack),FALSE);gtk_widget_set_hexpand(ui->stack,TRUE);gtk_widget_set_vexpand(ui->stack,TRUE);append(body,ui->stack);
    GtkWidget *overview=box(GTK_ORIENTATION_VERTICAL,12),*viewport=gtk_scrolled_window_new();gtk_widget_add_css_class(overview,"workspace");gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(viewport),overview);gtk_stack_add_named(GTK_STACK(ui->stack),viewport,"overview");
    append(overview,label("운영 개요","title"));append(overview,label("로컬 서버의 실제 상태와 서비스를 확인하세요.","muted"));
    GtkWidget *metrics=gtk_flow_box_new();gtk_flow_box_set_selection_mode(GTK_FLOW_BOX(metrics),GTK_SELECTION_NONE);gtk_flow_box_set_min_children_per_line(GTK_FLOW_BOX(metrics),2);gtk_flow_box_set_max_children_per_line(GTK_FLOW_BOX(metrics),4);gtk_flow_box_set_homogeneous(GTK_FLOW_BOX(metrics),TRUE);gtk_flow_box_set_column_spacing(GTK_FLOW_BOX(metrics),10);gtk_flow_box_set_row_spacing(GTK_FLOW_BOX(metrics),10);
    gtk_flow_box_insert(GTK_FLOW_BOX(metrics),metric("▦ CPU",&ui->cpu,&ui->bars[0]),-1);gtk_flow_box_insert(GTK_FLOW_BOX(metrics),metric("▤ 메모리",&ui->memory,&ui->bars[1]),-1);gtk_flow_box_insert(GTK_FLOW_BOX(metrics),metric("□ 디스크 /",&ui->disk,&ui->bars[2]),-1);gtk_flow_box_insert(GTK_FLOW_BOX(metrics),metric("! 실패 서비스",&ui->failed,NULL),-1);append(overview,metrics);
    ui->warning=wrap("","warning");gtk_widget_set_visible(ui->warning,FALSE);append(overview,ui->warning);
    ui->paned=gtk_paned_new(GTK_ORIENTATION_HORIZONTAL);gtk_widget_set_vexpand(ui->paned,TRUE);append(overview,ui->paned);
    GtkWidget *table=box(GTK_ORIENTATION_VERTICAL,9);gtk_widget_add_css_class(table,"card");gtk_paned_set_start_child(GTK_PANED(ui->paned),table);gtk_paned_set_shrink_start_child(GTK_PANED(ui->paned),FALSE);
    append(table,label("서비스","section-title"));GtkWidget *tools=box(GTK_ORIENTATION_HORIZONTAL,9);append(table,tools);
    ui->search=gtk_search_entry_new();gtk_widget_set_hexpand(ui->search,TRUE);gtk_widget_set_tooltip_text(ui->search,"서비스 이름과 설명 검색");append(tools,ui->search);g_signal_connect(ui->search,"search-changed",G_CALLBACK(search_changed),ui);
    ui->filter=gtk_check_button_new_with_label("실패만");append(tools,ui->filter);g_signal_connect(ui->filter,"toggled",G_CALLBACK(filter_changed),ui);
    GtkWidget *scroll=gtk_scrolled_window_new();gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll),GTK_POLICY_NEVER,GTK_POLICY_AUTOMATIC);gtk_widget_set_vexpand(scroll,TRUE);gtk_widget_set_size_request(scroll,-1,120);append(table,scroll);ui->list=gtk_list_box_new();gtk_list_box_set_filter_func(GTK_LIST_BOX(ui->list),filter_row,ui,NULL);g_signal_connect(ui->list,"row-selected",G_CALLBACK(selected),ui);gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll),ui->list);
    GtkWidget *empty=wrap("표시할 서비스가 없습니다. 검색·실패 필터와 조회 상태를 확인하세요.","muted");gtk_list_box_set_placeholder(GTK_LIST_BOX(ui->list),empty);
    ui->count=label("서비스를 읽는 중…","muted");append(table,ui->count);
    ui->detail=box(GTK_ORIENTATION_VERTICAL,10);gtk_widget_set_size_request(ui->detail,255,-1);gtk_widget_add_css_class(ui->detail,"card");gtk_paned_set_end_child(GTK_PANED(ui->paned),ui->detail);gtk_paned_set_shrink_end_child(GTK_PANED(ui->paned),FALSE);
    append(ui->detail,label("선택한 서비스","section-title"));ui->selected=wrap("서비스 선택","section-title");append(ui->detail,ui->selected);ui->details=wrap("목록에서 서비스를 선택하세요.",NULL);append(ui->detail,ui->details);append(ui->detail,button("기존 관리자에서 점검 ↗",G_CALLBACK(launch_admin),ui));append(ui->detail,wrap("로그·복구 작업은 기존 관리자에서 확인할 수 있습니다.","muted"));
    append(ui->detail,button("관련 로그",G_CALLBACK(connections_open_logs),ui));
    append(ui->detail,button("Console 점검",G_CALLBACK(connections_open_terminal),ui));
    append(ui->detail,button("incident-ai 분석 준비",G_CALLBACK(incident_open_page),ui));
    gtk_stack_add_named(GTK_STACK(ui->stack),placeholder("서비스","운영 개요의 서비스 목록에서 검색·실패 필터·실제 상태를 확인할 수 있습니다.",ui,FALSE),"services");
    gtk_stack_add_named(GTK_STACK(ui->stack),connections_logs_page(ui),"logs");
    gtk_stack_add_named(GTK_STACK(ui->stack),connections_terminal_page(ui),"terminal");
    gtk_stack_add_named(GTK_STACK(ui->stack),incident_page(ui),"incident");
    ui->status=label("로컬 상태를 읽는 중…","footer");gtk_label_set_ellipsize(GTK_LABEL(ui->status),PANGO_ELLIPSIZE_END);append(outer,ui->status);
    if(ui->settings)gtk_check_button_set_active(GTK_CHECK_BUTTON(ui->filter),g_settings_get_boolean(ui->settings,"failed-only"));
    ui->compact=TRUE;
    gtk_window_present(ui->window);gtk_window_maximize(ui->window);request(ui,FALSE);request(ui,TRUE);
    ui->timer=g_timeout_add_seconds(3,refresh,ui);ui->layout_timer=g_timeout_add(500,layout,ui);
}
int main(int argc,char **argv) {
    setlocale(LC_ALL,"");Ops ui={0};g_autoptr(GtkApplication) app=gtk_application_new("org.kiki.Operations",G_APPLICATION_DEFAULT_FLAGS);
    g_signal_connect(app,"activate",G_CALLBACK(activate),&ui);int code=g_application_run(G_APPLICATION(app),argc,argv);
    g_clear_object(&ui.data);g_clear_object(&ui.settings);g_clear_object(&ui.css);g_strfreev(ui.terminal_argv);g_free(ui.unit);g_free(ui.log_observed_at);g_free(ui.incident_url);return code;
}
