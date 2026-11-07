/* App-local connection flow. Privilege remains in the unchanged administrator helper. */
enum { CONN_USER, CONN_PLAN, CONN_SYSTEM, CONN_TERMINAL, CONN_INCIDENT };
typedef struct { Ops *ui;char *unit;guint64 generation, revision;int kind; } Connection;
typedef struct { Ops *ui;char *unit,*token;guint64 generation; } LogReview;

static void connections_schedule(Ops *ui);
static void connections_begin(Ops *ui,int kind,const char *token);
static void connections_controls(Ops *ui) {
    if(!ui->log_refresh)return;
    gboolean ready=ui->unit && !ui->connection && !ui->closing;
    gtk_widget_set_sensitive(ui->log_refresh,ready);gtk_widget_set_sensitive(ui->log_system,ready);
    gtk_widget_set_sensitive(ui->terminal_launch,ready && ui->terminal_argv && ui->terminal_generation==ui->selection_generation);
    incident_controls(ui);
}
static gboolean connections_current(Ops *ui,const Connection *r) {
    return !ui->closing && ui->selection_generation==r->generation && g_strcmp0(ui->unit,r->unit)==0
        && (r->kind!=CONN_INCIDENT || r->revision==ui->incident_revision);
}
static void connections_close_review(Ops *ui) {
    GtkWindow *w=ui->log_review;ui->log_review=NULL;if(w)gtk_window_destroy(w);
}
static void connections_review_free(gpointer data) {
    LogReview *r=data;g_free(r->unit);g_free(r->token);g_free(r);
}
static gboolean connections_review_closed(GtkWindow *w,gpointer data) {
    Ops *ui=data;if(ui->log_review==w)ui->log_review=NULL;return FALSE;
}
static void connections_review_cancel(GtkButton *b,gpointer data) { (void)b;connections_close_review(data); }
static void connections_authorize(GtkButton *b,gpointer data) {
    (void)b;LogReview *r=data;Ops *ui=r->ui;
    if(ui->closing || ui->selection_generation!=r->generation || g_strcmp0(ui->unit,r->unit)) {
        connections_close_review(ui);return;
    }
    g_autofree char *token=g_strdup(r->token);connections_close_review(ui);connections_begin(ui,CONN_SYSTEM,token);
}
static void connections_review(Ops *ui,JsonObject *o) {
    const char *token=text(o,"token");
    if(strcmp(text(o,"action"),"system-logs") || strlen(token)!=64 || strspn(token,"0123456789abcdef")!=64) {
        set(ui->log_notice,"시스템 로그 조회 계획을 확인할 수 없습니다.");return;
    }
    connections_close_review(ui);LogReview *r=g_new0(LogReview,1);r->ui=ui;r->unit=g_strdup(ui->unit);r->token=g_strdup(token);r->generation=ui->selection_generation;
    GtkWindow *w=GTK_WINDOW(gtk_window_new());ui->log_review=w;gtk_window_set_application(w,ui->app);
    gtk_window_set_title(w,"시스템 로그 조회 확인");gtk_window_set_transient_for(w,ui->window);gtk_window_set_destroy_with_parent(w,TRUE);gtk_window_set_modal(w,TRUE);gtk_window_set_default_size(w,620,340);
    gtk_widget_add_css_class(GTK_WIDGET(w),"kiki-operations");
    GtkWidget *root=box(GTK_ORIENTATION_VERTICAL,16);gtk_widget_add_css_class(root,"workspace");
    append(root,label("시스템 로그 인증 조회","title"));append(root,wrap(r->unit,"section-title"));
    append(root,wrap("이번 부팅의 선택한 서비스 로그 최근 200줄을 조회합니다. 기존 KIKI 관리자 인증을 사용하며 서비스 설정은 변경하지 않습니다.",NULL));
    append(root,wrap(text(o,"details"),"code"));
    GtkWidget *actions=box(GTK_ORIENTATION_HORIZONTAL,12);append(actions,button("취소",G_CALLBACK(connections_review_cancel),ui));
    GtkWidget *confirm=gtk_button_new_with_label("인증하고 조회");g_signal_connect(confirm,"clicked",G_CALLBACK(connections_authorize),r);gtk_widget_add_css_class(confirm,"suggested");append(actions,confirm);append(root,actions);
    gtk_window_set_child(w,root);g_signal_connect(w,"close-request",G_CALLBACK(connections_review_closed),ui);
    g_object_set_data_full(G_OBJECT(w),"kiki-log-review",r,connections_review_free);gtk_window_present(w);
}
static gboolean connections_deadline(gpointer data) {
    Ops *ui=data;ui->connection_deadline=0;if(ui->connection)g_subprocess_force_exit(ui->connection);return G_SOURCE_REMOVE;
}
static gboolean connections_terminal_valid(Ops *ui,JsonObject *o) {
    JsonArray *a=json_object_get_array_member(o,"argv");
    const char *mode=gtk_drop_down_get_selected(GTK_DROP_DOWN(ui->terminal_mode))==0 ? "status" : "logs";
    if(!a || json_array_get_length(a)!=5 || strcmp(text(o,"mode"),mode))return FALSE;
    const char *expected[]={"/usr/bin/kgx","--","/usr/libexec/kiki-operations-console",mode,ui->unit};
    for(guint i=0;i<5;i++) {
        JsonNode *v=json_array_get_element(a,i);
        if(!JSON_NODE_HOLDS_VALUE(v) || json_node_get_value_type(v)!=G_TYPE_STRING || g_strcmp0(json_node_get_string(v),expected[i]))return FALSE;
    }
    g_clear_pointer(&ui->terminal_argv,g_strfreev);ui->terminal_argv=g_new0(char*,6);
    for(guint i=0;i<5;i++)ui->terminal_argv[i]=g_strdup(expected[i]);
    ui->terminal_generation=ui->selection_generation;return TRUE;
}
static void connections_finished(GObject *source,GAsyncResult *result,gpointer data) {
    Connection *r=data;Ops *ui=r->ui;g_autofree char *out=NULL,*err=NULL;g_autoptr(GError) error=NULL;
    gboolean communicated=g_subprocess_communicate_utf8_finish(G_SUBPROCESS(source),result,&out,&err,&error);
    if(ui->connection_deadline) { g_source_remove(ui->connection_deadline);ui->connection_deadline=0; }
    if(connections_current(ui,r)) {
        g_autoptr(JsonParser) parser=json_parser_new();JsonObject *o=NULL;
        if(communicated && out && strlen(out)<2*1024*1024 && json_parser_load_from_data(parser,out,-1,NULL) && JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser)))o=json_node_get_object(json_parser_get_root(parser));
        gboolean ok=o && json_object_has_member(o,"ok") && json_object_get_boolean_member(o,"ok") && g_subprocess_get_successful(G_SUBPROCESS(source));
        if(ok && r->kind==CONN_SYSTEM)ok=strcmp(text(o,"action"),"system-logs")==0;
        else if(ok)ok=strcmp(text(o,"schema"),"kiki-operations-v1")==0 && g_strcmp0(text(o,"unit"),r->unit)==0;
        if(!ok) {
            int status=g_subprocess_get_if_exited(G_SUBPROCESS(source)) ? g_subprocess_get_exit_status(G_SUBPROCESS(source)) : -1;
            const char *message=(r->kind==CONN_SYSTEM && (status==126 || status==127)) ? "시스템 로그 인증이 취소되거나 거부되었습니다. 새 조회를 선택하세요."
                : o && *text(o,"error") ? text(o,"error") : error ? error->message : err && *err ? err : "조회하지 못했습니다. 다시 시도하세요.";
            set(r->kind==CONN_INCIDENT ? ui->incident_notice : r->kind==CONN_TERMINAL ? ui->terminal_notice : ui->log_notice,message);
            if(r->kind==CONN_SYSTEM)set(ui->log_scope,"시스템 로그 조회 실패 · 표시할 인증 결과 없음");
        } else if(r->kind==CONN_INCIDENT)incident_result(ui,o);
        else if(r->kind==CONN_PLAN)connections_review(ui,o);
        else if(r->kind==CONN_TERMINAL) {
            if(connections_terminal_valid(ui,o)) { set(ui->terminal_preview,text(o,"preview"));set(ui->terminal_notice,"일반 사용자 권한 · 아래 명령만 Console에서 실행합니다."); }
            else set(ui->terminal_notice,"점검 명령을 확인할 수 없습니다.");
        } else {
            gtk_text_buffer_set_text(ui->log_buffer,text(o,"output"),-1);
            set(ui->log_scope,r->kind==CONN_SYSTEM ? "시스템 로그 · 인증 완료 · 이번 부팅 최근 200줄" : "사용자 로그 · 현재 사용자에게 보이는 범위 · 이번 부팅 최근 200줄");
            set(ui->log_notice,r->kind==CONN_SYSTEM ? "인증된 결과는 현재 선택한 서비스에만 표시됩니다." : text(o,"notice"));
            ui->log_loaded=TRUE;ui->log_system_result=r->kind==CONN_SYSTEM;
            g_autoptr(GDateTime) now=g_date_time_new_now_local();g_free(ui->log_observed_at);ui->log_observed_at=g_date_time_format_iso8601(now);
            incident_logs_changed(ui);
        }
    }
    g_clear_object(&ui->connection);
    if(!ui->closing) { connections_controls(ui);connections_schedule(ui); }
    g_application_release(G_APPLICATION(ui->app));g_free(r->unit);g_free(r);
}
static void connections_begin(Ops *ui,int kind,const char *token) {
    if(ui->closing || !ui->unit || ui->connection)return;
    const char *mode=ui->terminal_mode && gtk_drop_down_get_selected(GTK_DROP_DOWN(ui->terminal_mode))==1 ? "logs" : "status";
    const char *normal[]={"/usr/bin/kiki-operationsctl",kind==CONN_USER ? "logs" : kind==CONN_PLAN ? "log-plan" : kind==CONN_INCIDENT ? "incident-plan" : "terminal-plan",ui->unit,kind==CONN_TERMINAL ? mode : NULL,NULL};
    const char *privileged[]={"/usr/bin/pkexec","/usr/libexec/kiki-admin-helper","system-logs",ui->unit,token,NULL};
    if(kind==CONN_SYSTEM && (!token || strlen(token)!=64))return;
    g_autoptr(GError) error=NULL;
    g_autofree char *input=kind==CONN_INCIDENT ? incident_input(ui) : NULL;
    ui->connection=g_subprocess_newv(kind==CONN_SYSTEM ? privileged : normal,G_SUBPROCESS_FLAGS_STDOUT_PIPE|G_SUBPROCESS_FLAGS_STDERR_PIPE|(kind==CONN_INCIDENT ? G_SUBPROCESS_FLAGS_STDIN_PIPE : 0),&error);
    if(!ui->connection) { set(kind==CONN_INCIDENT ? ui->incident_notice : ui->log_notice,error->message);return; }
    ui->connection_kind=kind;Connection *r=g_new0(Connection,1);r->ui=ui;r->unit=g_strdup(ui->unit);r->generation=ui->selection_generation;r->revision=ui->incident_revision;r->kind=kind;
    if(kind==CONN_SYSTEM) { ui->log_loaded=FALSE;incident_logs_changed(ui);gtk_text_buffer_set_text(ui->log_buffer,"",-1);set(ui->log_scope,"시스템 로그 · 관리자 인증 대기"); }
    set(kind==CONN_INCIDENT ? ui->incident_notice : kind==CONN_TERMINAL ? ui->terminal_notice : ui->log_notice,kind==CONN_SYSTEM ? "정상 인증 창에서 승인하거나 취소할 수 있습니다." : "선택한 서비스 정보를 조회하는 중…");
    g_application_hold(G_APPLICATION(ui->app));ui->connection_deadline=g_timeout_add_seconds(kind==CONN_SYSTEM ? 150 : 35,connections_deadline,ui);
    connections_controls(ui);g_subprocess_communicate_utf8_async(ui->connection,input,NULL,connections_finished,r);
}
static void connections_schedule(Ops *ui) {
    if(ui->closing || ui->connection || !ui->unit)return;
    if(ui->want_logs) { ui->want_logs=FALSE;connections_begin(ui,CONN_USER,NULL); }
    else if(ui->want_terminal) { ui->want_terminal=FALSE;connections_begin(ui,CONN_TERMINAL,NULL); }
    else if(ui->want_incident) { ui->want_incident=FALSE;connections_begin(ui,CONN_INCIDENT,NULL); }
}
static void connections_page_changed(Ops *ui) {
    const char *page=gtk_stack_get_visible_child_name(GTK_STACK(ui->stack));
    ui->want_logs=g_strcmp0(page,"logs")==0;ui->want_terminal=g_strcmp0(page,"terminal")==0;ui->want_incident=g_strcmp0(page,"incident")==0;connections_schedule(ui);
}
static void connections_context_changed(Ops *ui) {
    ui->selection_generation++;connections_close_review(ui);
    ui->log_loaded=FALSE;ui->log_system_result=FALSE;g_clear_pointer(&ui->log_observed_at,g_free);incident_context_changed(ui);
    g_clear_pointer(&ui->terminal_argv,g_strfreev);
    gtk_text_buffer_set_text(ui->log_buffer,"",-1);
    set(ui->log_unit,ui->unit ? ui->unit : "서비스를 먼저 선택하세요.");set(ui->terminal_unit,ui->unit ? ui->unit : "서비스를 먼저 선택하세요.");
    set(ui->log_scope,"선택한 서비스 · 아직 조회되지 않음");set(ui->log_notice,"");set(ui->terminal_preview,"점검 명령을 선택하세요.");set(ui->terminal_notice,"");
    if(ui->connection && ui->connection_kind!=CONN_SYSTEM)g_subprocess_force_exit(ui->connection);
    connections_controls(ui);connections_page_changed(ui);
}
static void connections_reload(GtkButton *b,gpointer data) { (void)b;Ops *ui=data;ui->want_logs=TRUE;connections_schedule(ui); }
static void connections_system(GtkButton *b,gpointer data) { (void)b;Ops *ui=data;ui->want_logs=FALSE;connections_begin(ui,CONN_PLAN,NULL); }
static void connections_show(Ops *ui,const char *page,int nav) {
    gtk_stack_set_visible_child_name(GTK_STACK(ui->stack),page);gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(ui->navigation[nav]),TRUE);connections_page_changed(ui);
}
static void connections_open_logs(GtkButton *b,gpointer data) { (void)b;connections_show(data,"logs",2); }
static void connections_open_terminal(GtkButton *b,gpointer data) { (void)b;connections_show(data,"terminal",3); }
static void connections_mode_changed(GObject *o,GParamSpec *spec,gpointer data) {
    (void)o;(void)spec;Ops *ui=data;g_clear_pointer(&ui->terminal_argv,g_strfreev);ui->want_terminal=TRUE;
    if(ui->connection && ui->connection_kind==CONN_TERMINAL)g_subprocess_force_exit(ui->connection);
    connections_controls(ui);connections_schedule(ui);
}
static void connections_launch(GtkButton *b,gpointer data) {
    (void)b;Ops *ui=data;
    if(!ui->terminal_argv || ui->terminal_generation!=ui->selection_generation || !ui->unit)return;
    g_autoptr(GString) command=g_string_new("");
    for(int i=0;ui->terminal_argv[i];i++) { g_autofree char *quoted=g_shell_quote(ui->terminal_argv[i]);if(i)g_string_append_c(command,' ');g_string_append(command,quoted); }
    g_autoptr(GError) error=NULL;
    g_autoptr(GAppInfo) app=g_app_info_create_from_commandline(command->str,"KIKI Console 점검",G_APP_INFO_CREATE_SUPPORTS_STARTUP_NOTIFICATION,&error);
    g_autoptr(GdkAppLaunchContext) context=gdk_display_get_app_launch_context(gtk_widget_get_display(GTK_WIDGET(ui->window)));
    if(!app || !g_app_info_launch(app,NULL,G_APP_LAUNCH_CONTEXT(context),&error))set(ui->terminal_notice,error ? error->message : "Console을 실행할 수 없습니다.");
    else set(ui->terminal_notice,"Console에서 선택한 서비스의 읽기 전용 점검을 실행했습니다. 결과를 읽은 후 Enter로 점검을 마치고 창을 닫으세요.");
}
static GtkWidget *connections_logs_page(Ops *ui) {
    GtkWidget *root=box(GTK_ORIENTATION_VERTICAL,12);gtk_widget_add_css_class(root,"workspace");append(root,label("서비스 로그","title"));
    ui->log_unit=wrap("서비스를 먼저 선택하세요.","section-title");append(root,ui->log_unit);
    ui->log_scope=wrap("선택한 서비스 · 아직 조회되지 않음","muted");append(root,ui->log_scope);
    GtkWidget *actions=box(GTK_ORIENTATION_HORIZONTAL,10);ui->log_refresh=button("사용자 로그 조회",G_CALLBACK(connections_reload),ui);ui->log_system=button("시스템 로그 인증 조회",G_CALLBACK(connections_system),ui);append(actions,ui->log_refresh);append(actions,ui->log_system);append(actions,button("incident-ai 분석 준비",G_CALLBACK(incident_open_page),ui));append(root,actions);
    ui->log_notice=wrap("현재 사용자 로그와 인증된 시스템 로그를 구분해 표시합니다.","muted");append(root,ui->log_notice);
    GtkWidget *view=gtk_text_view_new();gtk_text_view_set_editable(GTK_TEXT_VIEW(view),FALSE);gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(view),FALSE);gtk_text_view_set_monospace(GTK_TEXT_VIEW(view),TRUE);ui->log_buffer=gtk_text_view_get_buffer(GTK_TEXT_VIEW(view));
    GtkWidget *scroll=gtk_scrolled_window_new();gtk_widget_set_vexpand(scroll,TRUE);gtk_widget_add_css_class(scroll,"card");gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll),view);append(root,scroll);return root;
}
static GtkWidget *connections_terminal_page(Ops *ui) {
    GtkWidget *root=box(GTK_ORIENTATION_VERTICAL,16);gtk_widget_add_css_class(root,"workspace");append(root,label("Console 점검","title"));ui->terminal_unit=wrap("서비스를 먼저 선택하세요.","section-title");append(root,ui->terminal_unit);
    const char *modes[]={"서비스 상태 확인","최근 로그 · 사용자 권한",NULL};ui->terminal_mode=gtk_drop_down_new_from_strings(modes);g_signal_connect(ui->terminal_mode,"notify::selected",G_CALLBACK(connections_mode_changed),ui);append(root,ui->terminal_mode);
    ui->terminal_preview=wrap("점검 명령을 선택하세요.","code");gtk_widget_add_css_class(ui->terminal_preview,"card");append(root,ui->terminal_preview);
    ui->terminal_notice=wrap("일반 사용자 권한으로 실행합니다. 시스템 로그는 로그 화면의 인증 조회를 사용하세요.","muted");append(root,ui->terminal_notice);
    ui->terminal_launch=button("Console에서 점검 실행",G_CALLBACK(connections_launch),ui);gtk_widget_add_css_class(ui->terminal_launch,"suggested");append(root,ui->terminal_launch);connections_controls(ui);return root;
}
static void connections_stop(Ops *ui) {
    connections_close_review(ui);ui->want_logs=ui->want_terminal=ui->want_incident=FALSE;
    if(ui->connection)g_subprocess_force_exit(ui->connection);
}
