/* Reviewed clipboard handoff to the existing web question form; no API credentials. */
#define INCIDENT_URL "https://incident-ai.lab.terminal-lab.kr/#ask"
static void incident_include_changed(GtkCheckButton *button,gpointer data);
static void incident_reset_include(Ops *ui) {
    g_signal_handlers_block_by_func(ui->incident_include,G_CALLBACK(incident_include_changed),ui);
    gtk_check_button_set_active(GTK_CHECK_BUTTON(ui->incident_include),FALSE);
    g_signal_handlers_unblock_by_func(ui->incident_include,G_CALLBACK(incident_include_changed),ui);
}
static gsize incident_length(const char *s) {
    glong length=0;g_autofree gunichar2 *utf16=g_utf8_to_utf16(s,-1,NULL,&length,NULL);
    return utf16 ? (gsize)length : G_MAXSIZE;
}
static char *incident_draft(Ops *ui) {
    GtkTextIter a,b;gtk_text_buffer_get_bounds(ui->incident_buffer,&a,&b);
    return gtk_text_buffer_get_text(ui->incident_buffer,&a,&b,FALSE);
}
static void incident_clear_clipboard(Ops *ui) {
    if(!ui->incident_clipboard)return;
    GdkClipboard *clipboard=gtk_widget_get_clipboard(GTK_WIDGET(ui->window));
    if(gdk_clipboard_get_content(clipboard)==ui->incident_clipboard)gdk_clipboard_set_content(clipboard,NULL);
    g_clear_object(&ui->incident_clipboard);
}
static gboolean incident_ready(Ops *ui) {
    if(!ui->incident_buffer || !ui->unit || ui->closing || ui->connection || !ui->incident_url
        || ui->incident_valid_generation!=ui->selection_generation)return FALSE;
    g_autofree char *draft=incident_draft(ui);gsize length=incident_length(draft);
    return length>0 && length<=1000;
}
static void incident_controls(Ops *ui) {
    if(!ui->incident_copy)return;
    gboolean ready=incident_ready(ui);
    g_autoptr(GAppInfo) browser=g_app_info_get_default_for_uri_scheme("https");
    gtk_widget_set_sensitive(ui->incident_copy,ready);
    gtk_widget_set_sensitive(ui->incident_open,ready && browser);
    gtk_widget_set_sensitive(ui->incident_prepare,ui->unit && !ui->closing && !ui->connection);
    gtk_widget_set_sensitive(ui->incident_include,ui->unit && ui->log_loaded && !ui->closing);
    gtk_text_view_set_editable(GTK_TEXT_VIEW(ui->incident_editor),ui->incident_url && !ui->connection && !ui->closing);
}
static void incident_changed(GtkTextBuffer *buffer,gpointer data) {
    (void)buffer;Ops *ui=data;incident_clear_clipboard(ui);
    g_autofree char *draft=incident_draft(ui);gsize length=incident_length(draft);
    g_autofree char *counter=g_strdup_printf("웹 질문 길이: %" G_GSIZE_FORMAT " / 1,000자 · UTF-16 기준",length);
    set(ui->incident_counter,counter);
    if(length>1000)set(ui->incident_notice,"웹 질문 제한을 초과했습니다. 문맥을 1,000자 이내로 줄이세요.");
    else if(ui->incident_valid_generation)set(ui->incident_notice,"전달 내용을 검토하세요. 열린 웹 질문란에 Ctrl+V로 붙여넣은 뒤 정상 로그인 상태에서 전송합니다.");
    incident_controls(ui);
}
static void incident_invalidate(Ops *ui) {
    if(!ui->incident_buffer)return;
    ui->incident_revision++;ui->incident_valid_generation=0;incident_clear_clipboard(ui);
    g_clear_pointer(&ui->incident_url,g_free);gtk_text_buffer_set_text(ui->incident_buffer,"",-1);
    set(ui->incident_unit,ui->unit ? ui->unit : "서비스를 먼저 선택하세요.");
    set(ui->incident_scope,ui->log_loaded ? (ui->log_system_result ? "현재 로그: Polkit 인증 시스템 로그 · 포함 여부를 직접 선택하세요." : "현재 로그: 사용자에게 보이는 범위 · 포함 여부를 직접 선택하세요.") : "현재 선택한 서비스의 로그를 아직 조회하지 않았습니다. 서비스 정보만 전달할 수 있습니다.");
    set(ui->incident_notice,"선택 서비스의 문맥을 준비하세요. 로그를 포함하려면 로그 화면에서 먼저 조회하세요.");
    incident_controls(ui);
}
static void incident_context_changed(Ops *ui) {
    if(!ui->incident_buffer)return;
    incident_invalidate(ui);incident_reset_include(ui);
}
static void incident_logs_changed(Ops *ui) {
    if(!ui->incident_buffer)return;
    incident_invalidate(ui);
    if(!ui->log_loaded)incident_reset_include(ui);
    if(g_strcmp0(gtk_stack_get_visible_child_name(GTK_STACK(ui->stack)),"incident")==0)ui->want_incident=TRUE;
}
static char *incident_input(Ops *ui) {
    gboolean include=ui->log_loaded && gtk_check_button_get_active(GTK_CHECK_BUTTON(ui->incident_include));
    g_autofree char *logs=NULL;gboolean truncated=FALSE;
    if(include) {
        GtkTextIter a,b;gtk_text_buffer_get_bounds(ui->log_buffer,&a,&b);logs=gtk_text_buffer_get_text(ui->log_buffer,&a,&b,FALSE);
        glong count=g_utf8_strlen(logs,-1);
        if(count>64000) { char *tail=g_strdup(g_utf8_offset_to_pointer(logs,count-64000));g_free(logs);logs=tail;truncated=TRUE; }
    }
    const char *hostname=ui->data ? text(json_node_get_object(json_parser_get_root(ui->data)),"hostname") : g_get_host_name();
    g_autoptr(JsonBuilder) builder=json_builder_new();json_builder_begin_object(builder);
    json_builder_set_member_name(builder,"hostname");json_builder_add_string_value(builder,hostname);
    json_builder_set_member_name(builder,"scope");json_builder_add_string_value(builder,include ? (ui->log_system_result ? "system" : "user") : "none");
    json_builder_set_member_name(builder,"observed_at");json_builder_add_string_value(builder,include && ui->log_observed_at ? ui->log_observed_at : "");
    json_builder_set_member_name(builder,"logs");json_builder_add_string_value(builder,logs ? logs : "");
    json_builder_set_member_name(builder,"source_truncated");json_builder_add_boolean_value(builder,truncated);json_builder_end_object(builder);
    g_autoptr(JsonNode) node=json_builder_get_root(builder);g_autoptr(JsonGenerator) generator=json_generator_new();json_generator_set_root(generator,node);
    return json_generator_to_data(generator,NULL);
}
static void incident_result(Ops *ui,JsonObject *o) {
    const char *draft=text(o,"draft"),*url=text(o,"url");
    if(strcmp(url,INCIDENT_URL) || !*draft || incident_length(draft)>1000) {
        set(ui->incident_notice,"분석 화면 주소와 전달 문맥을 확인할 수 없습니다.");return;
    }
    g_free(ui->incident_url);ui->incident_url=g_strdup(url);ui->incident_valid_generation=ui->selection_generation;
    gtk_text_buffer_set_text(ui->incident_buffer,draft,-1);
    g_autofree char *notice=g_strdup_printf("로그 %" G_GINT64_FORMAT "줄 중 %" G_GINT64_FORMAT "줄 발췌 · 패턴 마스킹 %" G_GINT64_FORMAT "곳%s. 마스킹은 완전하지 않으므로 내용을 검토·편집하세요.",
        json_object_get_int_member(o,"source_lines"),json_object_get_int_member(o,"included_lines"),json_object_get_int_member(o,"redactions"),json_object_get_boolean_member(o,"truncated") ? " · 일부 생략" : "");
    g_autoptr(GAppInfo) browser=g_app_info_get_default_for_uri_scheme("https");
    g_autofree char *status=browser ? g_strdup(notice) : g_strconcat(notice," HTTPS 기본 브라우저가 없습니다. 문맥 복사는 사용할 수 있습니다.",NULL);
    set(ui->incident_notice,status);incident_controls(ui);
}
static void incident_prepare(GtkButton *button,gpointer data) {
    (void)button;Ops *ui=data;if(!ui->unit)return;
    incident_invalidate(ui);ui->want_incident=TRUE;
    if(ui->connection && ui->connection_kind==CONN_INCIDENT)g_subprocess_force_exit(ui->connection);
    connections_schedule(ui);
}
static void incident_include_changed(GtkCheckButton *button,gpointer data) { (void)button;incident_prepare(NULL,data); }
static gboolean incident_copy_context(Ops *ui) {
    if(!incident_ready(ui))return FALSE;
    g_autofree char *draft=incident_draft(ui);GdkClipboard *clipboard=gtk_widget_get_clipboard(GTK_WIDGET(ui->window));
    gdk_clipboard_set_text(clipboard,draft);g_set_object(&ui->incident_clipboard,gdk_clipboard_get_content(clipboard));
    set(ui->incident_notice,"문맥을 클립보드에 복사했습니다. incident-ai ‘AI에게 묻기’ 질문란에 붙여넣어 검토하고 전송하세요.");return TRUE;
}
static void incident_copy(GtkButton *button,gpointer data) { (void)button;incident_copy_context(data); }
static void incident_launch(GtkButton *button,gpointer data) {
    (void)button;Ops *ui=data;g_autoptr(GAppInfo) browser=g_app_info_get_default_for_uri_scheme("https");
    if(!browser) { set(ui->incident_notice,"HTTPS 기본 브라우저가 없습니다. 브라우저 설치·기본 앱 등록 후 다시 시도하세요.");return; }
    if(!incident_copy_context(ui))return;
    g_autoptr(GError) error=NULL;g_autoptr(GdkAppLaunchContext) context=gdk_display_get_app_launch_context(gtk_widget_get_display(GTK_WIDGET(ui->window)));
    if(!g_app_info_launch_default_for_uri(ui->incident_url,G_APP_LAUNCH_CONTEXT(context),&error))set(ui->incident_notice,error ? error->message : "분석 화면을 열지 못했습니다. 문맥은 클립보드에 있습니다.");
    else set(ui->incident_notice,"분석 화면을 열고 문맥을 복사했습니다. 웹 질문란에 Ctrl+V로 붙여넣으세요. 전송은 정상 로그인 후 웹에서 선택합니다.");
}
static void incident_clear(GtkButton *button,gpointer data) {
    (void)button;Ops *ui=data;ui->want_incident=FALSE;incident_invalidate(ui);
    if(ui->connection && ui->connection_kind==CONN_INCIDENT)g_subprocess_force_exit(ui->connection);
    set(ui->incident_notice,"초안과 이 앱이 소유한 클립보드 문맥을 지웠습니다.");
}
static void incident_open_page(GtkButton *button,gpointer data) { (void)button;connections_show(data,"incident",4); }
static GtkWidget *incident_page(Ops *ui) {
    GtkWidget *root=box(GTK_ORIENTATION_VERTICAL,10);gtk_widget_add_css_class(root,"workspace");append(root,label("incident-ai 분석 연결","title"));
    append(root,wrap("전달 위치: " INCIDENT_URL,"code"));ui->incident_unit=wrap("서비스를 먼저 선택하세요.","section-title");append(root,ui->incident_unit);
    ui->incident_scope=wrap("현재 선택한 서비스의 로그를 아직 조회하지 않았습니다.","muted");append(root,ui->incident_scope);
    ui->incident_include=gtk_check_button_new_with_label("조회한 로그 발췌 포함");g_signal_connect(ui->incident_include,"toggled",G_CALLBACK(incident_include_changed),ui);append(root,ui->incident_include);
    GtkWidget *prepare=box(GTK_ORIENTATION_HORIZONTAL,10);ui->incident_prepare=button("문맥 다시 준비",G_CALLBACK(incident_prepare),ui);append(prepare,ui->incident_prepare);append(prepare,button("관련 로그 보기",G_CALLBACK(connections_open_logs),ui));append(root,prepare);
    append(root,wrap("서비스·조회 범위·시각과 최근 로그 발췌를 검토하세요. 문맥은 클립보드로 복사되며, 웹에서 붙여넣고 전송합니다.","muted"));
    ui->incident_editor=gtk_text_view_new();gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(ui->incident_editor),GTK_WRAP_WORD_CHAR);ui->incident_buffer=gtk_text_view_get_buffer(GTK_TEXT_VIEW(ui->incident_editor));
    GtkWidget *scroll=gtk_scrolled_window_new();gtk_widget_set_vexpand(scroll,TRUE);gtk_widget_add_css_class(scroll,"card");gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll),ui->incident_editor);append(root,scroll);
    ui->incident_counter=label("웹 질문 길이: 0 / 1,000자 · UTF-16 기준","muted");append(root,ui->incident_counter);
    ui->incident_notice=wrap("선택 서비스의 문맥을 준비하세요.","muted");append(root,ui->incident_notice);
    GtkWidget *actions=box(GTK_ORIENTATION_HORIZONTAL,10);ui->incident_copy=button("문맥만 복사",G_CALLBACK(incident_copy),ui);ui->incident_open=button("문맥 복사·분석 화면 열기",G_CALLBACK(incident_launch),ui);gtk_widget_add_css_class(ui->incident_open,"suggested");append(actions,ui->incident_copy);append(actions,ui->incident_open);append(actions,button("문맥 지우기",G_CALLBACK(incident_clear),ui));append(root,actions);
    g_signal_connect(ui->incident_buffer,"changed",G_CALLBACK(incident_changed),ui);incident_controls(ui);return root;
}
static void incident_stop(Ops *ui) { incident_clear_clipboard(ui); }
