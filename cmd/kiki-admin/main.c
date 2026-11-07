#include <adwaita.h>
#include <json-glib/json-glib.h>
#include <locale.h>
#include <string.h>
#include "pixel.h"

typedef struct {
    AdwApplication *app;
    GtkWindow *window;
    GtkStack *stack;
    GtkListBox *navigation;
    GtkWidget *pages[4], *refresh, *spinner;
    GtkLabel *status;
    GtkTextBuffer *activity;
    JsonParser *snapshot;
    gboolean busy;
} Admin;

typedef struct { Admin *ui; char *kind, *action, *target; } Request;
typedef struct { Admin *ui; char *action, *target, *token; GtkWindow *window; } Review;

static void request(Admin *, const char *, const char *, const char *, const char *);
static void render(Admin *);
static const char *str(JsonObject *o, const char *key) {
    return json_object_has_member(o, key) && !json_object_get_null_member(o, key) ? json_object_get_string_member(o, key) : "";
}
static gboolean boolean(JsonObject *o, const char *key) { return json_object_has_member(o,key) && json_object_get_boolean_member(o,key); }
static JsonArray *array(JsonObject *o, const char *key) { return json_object_has_member(o,key) ? json_object_get_array_member(o,key) : NULL; }
static guint length(JsonArray *a) { return a ? json_array_get_length(a) : 0; }

static GtkWidget *label(const char *text, const char *css) {
    GtkWidget *w = gtk_label_new(text);
    gtk_label_set_xalign(GTK_LABEL(w), 0); gtk_label_set_wrap(GTK_LABEL(w), TRUE);
    if (css) gtk_widget_add_css_class(w, css);
    return w;
}
static GtkWidget *group(GtkWidget *page, const char *title, const char *description) {
    GtkWidget *g = adw_preferences_group_new();
    adw_preferences_group_set_title(ADW_PREFERENCES_GROUP(g), title);
    if (description) adw_preferences_group_set_description(ADW_PREFERENCES_GROUP(g), description);
    gtk_box_append(GTK_BOX(page), g); return g;
}
static GtkWidget *row(GtkWidget *g, const char *title, const char *subtitle, const char *icon) {
    GtkWidget *r = adw_action_row_new();
    adw_preferences_row_set_title(ADW_PREFERENCES_ROW(r), title);
    adw_preferences_row_set_use_markup(ADW_PREFERENCES_ROW(r), FALSE);
    adw_action_row_set_subtitle(ADW_ACTION_ROW(r), subtitle ? subtitle : "");
    adw_action_row_set_subtitle_lines(ADW_ACTION_ROW(r), 3);
    if (icon) adw_action_row_add_prefix(ADW_ACTION_ROW(r), gtk_image_new_from_icon_name(icon));
    adw_preferences_group_add(ADW_PREFERENCES_GROUP(g), r); return r;
}
static void note(GtkWidget *r, const char *value, const char *css) {
    GtkWidget *w = label(value, css ? css : "dim-label");
    gtk_label_set_wrap(GTK_LABEL(w), FALSE);
    gtk_label_set_single_line_mode(GTK_LABEL(w), TRUE);
    gtk_widget_set_valign(w, GTK_ALIGN_CENTER); adw_action_row_add_suffix(ADW_ACTION_ROW(r), w);
}
static void clicked(GtkButton *b, gpointer data) {
    Admin *ui = data;
    request(ui, g_object_get_data(G_OBJECT(b), "kind"), g_object_get_data(G_OBJECT(b), "action"),
            g_object_get_data(G_OBJECT(b), "target"), NULL);
}
static GtkWidget *button(Admin *ui, const char *title, const char *kind, const char *action, const char *target) {
    GtkWidget *b = gtk_button_new_with_label(title); gtk_widget_set_valign(b, GTK_ALIGN_CENTER);
    g_object_set_data_full(G_OBJECT(b), "kind", g_strdup(kind), g_free);
    g_object_set_data_full(G_OBJECT(b), "action", g_strdup(action ? action : ""), g_free);
    g_object_set_data_full(G_OBJECT(b), "target", g_strdup(target ? target : ""), g_free);
    g_signal_connect(b, "clicked", G_CALLBACK(clicked), ui); return b;
}
static void action(Admin *ui, GtkWidget *r, const char *title, const char *kind, const char *op, const char *target) {
    adw_action_row_add_suffix(ADW_ACTION_ROW(r), button(ui,title,kind,op,target));
}
static void heading(GtkWidget *page, const char *title, const char *subtitle) {
    gtk_box_append(GTK_BOX(page), label(title,"title-1"));
    gtk_box_append(GTK_BOX(page), label(subtitle,"dim-label"));
}
static void show_text(Admin *ui, const char *title, const char *text) {
    GtkWidget *window = gtk_window_new();
    gtk_window_set_application(GTK_WINDOW(window), GTK_APPLICATION(ui->app));
    gtk_window_set_transient_for(GTK_WINDOW(window), ui->window); gtk_window_set_modal(GTK_WINDOW(window), TRUE);
    gtk_window_set_title(GTK_WINDOW(window),title); gtk_window_set_default_size(GTK_WINDOW(window),800,520);
    GtkWidget *root = gtk_box_new(GTK_ORIENTATION_VERTICAL,0);
    gtk_box_append(GTK_BOX(root),adw_header_bar_new());
    GtkWidget *view = gtk_text_view_new(); gtk_text_view_set_editable(GTK_TEXT_VIEW(view),FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(view),FALSE); gtk_text_view_set_monospace(GTK_TEXT_VIEW(view),TRUE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(view),GTK_WRAP_WORD_CHAR);
    gtk_text_view_set_left_margin(GTK_TEXT_VIEW(view),20); gtk_text_view_set_right_margin(GTK_TEXT_VIEW(view),20);
    gtk_text_view_set_top_margin(GTK_TEXT_VIEW(view),16); gtk_text_view_set_bottom_margin(GTK_TEXT_VIEW(view),16);
    gtk_text_buffer_set_text(gtk_text_view_get_buffer(GTK_TEXT_VIEW(view)),text,-1);
    GtkWidget *scroll=gtk_scrolled_window_new(); gtk_widget_set_vexpand(scroll,TRUE);
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll),view); gtk_box_append(GTK_BOX(root),scroll);
    gtk_window_set_child(GTK_WINDOW(window),root); gtk_window_present(GTK_WINDOW(window));
}
static void review_free(gpointer data) {
    Review *r=data; g_free(r->action); g_free(r->target); g_free(r->token); g_free(r);
}
static void review_apply(GtkButton *b, gpointer data) {
    (void)b; Review *r=data;
    request(r->ui,"apply",r->action,r->target,r->token); gtk_window_destroy(r->window);
}
static void review(Admin *ui, JsonObject *plan) {
    Review *r=g_new0(Review,1); r->ui=ui; r->action=g_strdup(str(plan,"action"));
    r->target=g_strdup(str(plan,"target")); r->token=g_strdup(str(plan,"token"));
    GtkWidget *w=gtk_window_new(); r->window=GTK_WINDOW(w);
    gtk_window_set_application(r->window,GTK_APPLICATION(ui->app)); gtk_window_set_transient_for(r->window,ui->window);
    gtk_window_set_modal(r->window,TRUE); gtk_window_set_default_size(r->window,700,540);
    gtk_window_set_title(r->window,"변경 내용 확인");
    GtkWidget *root=gtk_box_new(GTK_ORIENTATION_VERTICAL,16);
    gtk_box_append(GTK_BOX(root),adw_header_bar_new());
    GtkWidget *content=gtk_box_new(GTK_ORIENTATION_VERTICAL,12);
    gtk_widget_set_margin_start(content,24); gtk_widget_set_margin_end(content,24);
    gtk_box_append(GTK_BOX(content),label(str(plan,"description"),"title-3"));
    gtk_box_append(GTK_BOX(content),label("아래 작업을 검토하세요. 적용 시 시스템의 관리자 인증을 요청합니다.","dim-label"));
    GtkWidget *text=gtk_text_view_new(); gtk_text_view_set_editable(GTK_TEXT_VIEW(text),FALSE);
    gtk_text_view_set_monospace(GTK_TEXT_VIEW(text),TRUE); gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(text),GTK_WRAP_WORD_CHAR);
    gtk_text_buffer_set_text(gtk_text_view_get_buffer(GTK_TEXT_VIEW(text)),str(plan,"details"),-1);
    GtkWidget *scroll=gtk_scrolled_window_new(); gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll),text);
    gtk_widget_set_vexpand(scroll,TRUE); gtk_box_append(GTK_BOX(content),scroll);
    GtkWidget *apply=gtk_button_new_with_label("인증하고 적용"); gtk_widget_add_css_class(apply,"suggested-action");
    gtk_widget_set_halign(apply,GTK_ALIGN_END); g_signal_connect(apply,"clicked",G_CALLBACK(review_apply),r);
    gtk_box_append(GTK_BOX(content),apply); gtk_widget_set_margin_bottom(content,24); gtk_widget_set_vexpand(content,TRUE);
    gtk_box_append(GTK_BOX(root),content); gtk_window_set_child(r->window,root);
    g_object_set_data_full(G_OBJECT(w),"review",r,review_free); gtk_window_present(r->window);
}
static void finished(GObject *source, GAsyncResult *result, gpointer data) {
    Request *r=data; Admin *ui=r->ui; g_autoptr(GError) error=NULL;
    g_autofree char *out=NULL, *err=NULL;
    gboolean communicated=g_subprocess_communicate_utf8_finish(G_SUBPROCESS(source),result,&out,&err,&error);
    ui->busy=FALSE; gtk_spinner_stop(GTK_SPINNER(ui->spinner)); gtk_widget_set_sensitive(ui->refresh,TRUE);
    for (guint i=0;i<4;i++) gtk_widget_set_sensitive(ui->pages[i],TRUE);
    g_autoptr(JsonParser) parser=json_parser_new(); JsonObject *object=NULL;
    if (communicated && out && json_parser_load_from_data(parser,out,-1,&error)) {
        JsonNode *node=json_parser_get_root(parser); if (JSON_NODE_HOLDS_OBJECT(node)) object=json_node_get_object(node);
    }
    if (!object || !boolean(object,"ok") || !g_subprocess_get_successful(G_SUBPROCESS(source))) {
        const char *message=object ? str(object,"error") : (err && *err ? err : (error ? error->message : "작업이 취소됐거나 완료되지 않았습니다."));
        gtk_label_set_text(ui->status,"작업을 완료하지 못했습니다. 상세 내용을 확인하세요.");
        gtk_widget_add_css_class(GTK_WIDGET(ui->status),"error");
        show_text(ui,"작업 결과",message);
    } else if (!strcmp(r->kind,"snapshot")) {
        g_set_object(&ui->snapshot,parser); render(ui);
        g_autofree char *stamp=g_strdup_printf("최근 확인 · %s",str(object,"observed_at"));
        gtk_label_set_text(ui->status,stamp); gtk_widget_remove_css_class(GTK_WIDGET(ui->status),"error");
    } else if (!strcmp(r->kind,"plan")) {
        gtk_label_set_text(ui->status,"변경 계획을 준비했습니다."); review(ui,object);
    } else if (!strcmp(r->kind,"apply")) {
        gtk_text_buffer_set_text(ui->activity,str(object,"output"),-1);
        show_text(ui,"관리 작업 완료",str(object,"output")); request(ui,"snapshot","","",NULL);
    } else if (!strcmp(r->kind,"logs")) {
        g_autofree char *body=g_strdup_printf("%s\n\n%s",str(object,"notice"),str(object,"output"));
        show_text(ui,*r->action ? r->action : "이번 부팅의 경고·오류 로그",body);
        gtk_label_set_text(ui->status,"현재 사용자에게 허용된 로그를 조회했습니다.");
    } else if (!strcmp(r->kind,"diagnose")) {
        g_autoptr(GString) body=g_string_new(str(object,"summary"));
        const char *sections[]={"issues","warnings"};
        for (guint s=0;s<2;s++) {
            JsonArray *items=array(object,sections[s]);
            for (guint i=0;i<length(items);i++) g_string_append_printf(body,"\n\n• %s",json_array_get_string_element(items,i));
        }
        show_text(ui,"시스템 진단 결과",body->str); gtk_label_set_text(ui->status,str(object,"observed_at"));
    }
    g_object_unref(source); g_free(r->kind); g_free(r->action); g_free(r->target); g_free(r);
}
static void request(Admin *ui,const char *kind,const char *action_name,const char *target,const char *token) {
    if (ui->busy) return;
    action_name=action_name ? action_name : ""; target=target ? target : "";
    const char *normal[]={"/usr/bin/kiki-adminctl",kind,action_name,target,NULL};
    const char *privileged[]={"/usr/bin/pkexec","/usr/libexec/kiki-admin-helper",action_name,target,token,NULL};
    g_autoptr(GError) error=NULL;
    GSubprocess *process=g_subprocess_newv(!strcmp(kind,"apply") ? privileged : normal,
                                         G_SUBPROCESS_FLAGS_STDOUT_PIPE|G_SUBPROCESS_FLAGS_STDERR_PIPE,&error);
    if (!process) { show_text(ui,"실행 오류",error->message); return; }
    ui->busy=TRUE; gtk_spinner_start(GTK_SPINNER(ui->spinner)); gtk_widget_set_sensitive(ui->refresh,FALSE);
    for(guint i=0;i<4;i++) gtk_widget_set_sensitive(ui->pages[i],FALSE);
    gtk_label_set_text(ui->status,!strcmp(kind,"apply") ? "관리 작업 실행 중 · 완료될 때까지 기다려 주세요…" : "정보를 확인하는 중…");
    Request *r=g_new0(Request,1); r->ui=ui; r->kind=g_strdup(kind); r->action=g_strdup(action_name); r->target=g_strdup(target);
    g_subprocess_communicate_utf8_async(process,NULL,NULL,finished,r);
}
static gboolean search_filter(GtkListBoxRow *r,gpointer data) {
    const char *name=g_object_get_data(G_OBJECT(r),"search");
    g_autofree char *term=g_utf8_casefold(gtk_editable_get_text(GTK_EDITABLE(data)),-1);
    return name && (!*term || strstr(name,term));
}
static void search_changed(GtkSearchEntry *entry,gpointer data) { (void)entry; gtk_list_box_invalidate_filter(GTK_LIST_BOX(data)); }
static void overview(Admin *ui, JsonObject *data) {
    GtkWidget *p=ui->pages[0]; heading(p,"시스템 개요","KIKI OS의 상태와 확인이 필요한 항목을 한곳에서 살펴보세요.");
    GtkWidget *hero=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,16); gtk_widget_add_css_class(hero,"card");
    gtk_widget_set_margin_top(hero,8);
    GtkWidget *icon=gtk_image_new_from_icon_name("org.kiki.Admin"); gtk_image_set_pixel_size(GTK_IMAGE(icon),64);
    gtk_widget_set_margin_start(icon,20); gtk_box_append(GTK_BOX(hero),icon);
    GtkWidget *copy=gtk_box_new(GTK_ORIENTATION_VERTICAL,6); gtk_widget_set_margin_top(copy,16); gtk_widget_set_margin_bottom(copy,16);
    gtk_box_append(GTK_BOX(copy),label(str(data,"os"),"title-2"));
    g_autofree char *identity=g_strdup_printf("%s · %s",str(data,"hostname"),str(data,"kernel"));
    gtk_box_append(GTK_BOX(copy),label(identity,"dim-label")); gtk_box_append(GTK_BOX(hero),copy); gtk_box_append(GTK_BOX(p),hero);
    GtkWidget *g=group(p,"상태 요약",NULL);
    GtkWidget *r=row(g,"실패한 서비스",length(array(data,"failed")) ? "로그를 확인하고 필요한 서비스를 복구하세요." : "실패한 시스템 서비스가 없습니다.","emblem-system-symbolic");
    g_autofree char *count=g_strdup_printf("%u개",length(array(data,"failed"))); note(r,count,length(array(data,"failed")) ? "error" : "success");
    r=row(g,"패키지 업데이트",boolean(data,"cached") ? "현재 저장된 저장소 목록 기준입니다." : "먼저 저장소 목록을 동기화하세요.","software-update-available-symbolic");
    g_autofree char *updates=g_strdup_printf("%" G_GINT64_FORMAT "개",json_object_get_int_member(data,"updates")); note(r,updates,NULL);
    r=row(g,"설치된 패키지","KI2가 기록한 설치 내역","package-x-generic-symbolic");
    g_autofree char *packages=g_strdup_printf("%u개",length(array(data,"installed"))); note(r,packages,NULL);
    g=group(p,"저장 장치","파일시스템에서 실제 사용할 수 있는 여유 공간입니다.");
    JsonArray *disks=array(data,"disks");
    if (!length(disks)) row(g,"저장 장치 정보 없음","마운트 목록을 읽지 못했거나 지원하는 로컬 파일시스템이 없습니다.","drive-harddisk-symbolic");
    for(guint i=0;i<length(disks);i++) {
        JsonObject *disk=json_array_get_object_element(disks,i);
        double total=json_object_get_int_member(disk,"total"), free=json_object_get_int_member(disk,"free");
        g_autofree char *summary=g_strdup_printf("%.1f GiB 여유 / %.1f GiB · %s",free/1073741824.,total/1073741824.,str(disk,"source"));
        r=row(g,str(disk,"mount"),summary,"drive-harddisk-symbolic");
        GtkWidget *bar=gtk_level_bar_new_for_interval(0,1); gtk_level_bar_set_value(GTK_LEVEL_BAR(bar),total ? 1-free/total : 0);
        gtk_widget_set_size_request(bar,110,-1); gtk_widget_set_valign(bar,GTK_ALIGN_CENTER); adw_action_row_add_suffix(ADW_ACTION_ROW(r),bar);
    }
    JsonArray *warnings=array(data,"warnings");
    if(length(warnings)) { g=group(p,"조회 시 확인할 사항",NULL); for(guint i=0;i<length(warnings);i++) row(g,"일부 정보를 읽지 못했습니다",json_array_get_string_element(warnings,i),"dialog-warning-symbolic"); }
}
static void packages(Admin *ui,JsonObject *data) {
    GtkWidget *p=ui->pages[1]; heading(p,"패키지","그룹 단위로 환경을 설치하고 KI2 업데이트를 관리하세요.");
    GtkWidget *g=group(p,"업데이트",boolean(data,"cached") ? "서명된 저장소 목록을 동기화한 뒤 새 버전을 확인하세요." : "저장소 목록이 아직 없습니다. 먼저 목록을 동기화하세요.");
    GtkWidget *r=row(g,"저장소 목록 동기화","서명과 인덱스 해시를 검증합니다.","view-refresh-symbolic"); action(ui,r,"동기화 계획","plan","refresh","");
    r=row(g,"패키지 업데이트","변경될 패키지를 먼저 확인할 수 있습니다.","software-update-available-symbolic"); action(ui,r,"변경 내용 확인","plan","upgrade","");
    g=group(p,"환경 그룹","설치 여부와 필수·기본 패키지의 구성 상태입니다. 부분 설치는 별도로 표시합니다.");
    JsonArray *groups=array(data,"groups");
    for(guint i=0;i<length(groups);i++) {
        JsonObject *item=json_array_get_object_element(groups,i);
        g_autofree char *description=g_strdup_printf("%s\n%s · %" G_GINT64_FORMAT "/%" G_GINT64_FORMAT "개 구성됨",str(item,"description"),str(item,"id"),json_object_get_int_member(item,"present"),json_object_get_int_member(item,"total"));
        r=row(g,str(item,"name"),description,"package-x-generic-symbolic");
        note(r,boolean(item,"installed") ? "등록됨" : (boolean(item,"configured") ? "구성됨" : "미설치"),NULL);
        if(boolean(item,"available")) action(ui,r,boolean(item,"installed") ? "구성 갱신" : (boolean(item,"configured") ? "그룹 등록 계획" : "설치 계획"),"plan",boolean(item,"installed") ? "group-upgrade" : "group-install",str(item,"id"));
        else { GtkWidget *missing=gtk_image_new_from_icon_name("dialog-information-symbolic"); gtk_widget_set_tooltip_text(missing,str(item,"unavailable_reason")); adw_action_row_add_suffix(ADW_ACTION_ROW(r),missing); }
    }
    g=group(p,"설치된 패키지","검색 결과에서 현재 버전과 업데이트 후보를 확인할 수 있습니다.");
    GtkWidget *search=gtk_search_entry_new(); gtk_widget_set_tooltip_text(search,"설치된 패키지 검색");
    gtk_box_append(GTK_BOX(p),search);
    GtkWidget *list=gtk_list_box_new(); gtk_widget_add_css_class(list,"boxed-list"); gtk_list_box_set_selection_mode(GTK_LIST_BOX(list),GTK_SELECTION_NONE);
    gtk_box_append(GTK_BOX(p),list); JsonArray *items=array(data,"installed");
    for(guint i=0;i<length(items);i++) {
        JsonObject *item=json_array_get_object_element(items,i); r=adw_action_row_new();
        adw_preferences_row_set_title(ADW_PREFERENCES_ROW(r),str(item,"name")); adw_preferences_row_set_use_markup(ADW_PREFERENCES_ROW(r),FALSE);
        g_autofree char *versions=boolean(item,"update") ? g_strdup_printf("%s → %s",str(item,"version"),str(item,"available")) : g_strdup(str(item,"version"));
        adw_action_row_set_subtitle(ADW_ACTION_ROW(r),versions);
        g_object_set_data_full(G_OBJECT(r),"search",g_utf8_casefold(str(item,"name"),-1),g_free);
        if(boolean(item,"update")) note(r,"업데이트 가능","accent");
        gtk_list_box_append(GTK_LIST_BOX(list),r);
    }
    gtk_list_box_set_filter_func(GTK_LIST_BOX(list),search_filter,search,NULL); g_signal_connect(search,"search-changed",G_CALLBACK(search_changed),list);
}
static void repo_save(GtkButton *b,gpointer data) {
    Admin *ui=data; GtkWidget *w=g_object_get_data(G_OBJECT(b),"window");
    const char *fields[]={"name","url","key"}; g_autoptr(JsonBuilder) builder=json_builder_new(); json_builder_begin_object(builder);
    for(guint i=0;i<3;i++) { GtkWidget *entry=g_object_get_data(G_OBJECT(w),fields[i]); json_builder_set_member_name(builder,fields[i]); json_builder_add_string_value(builder,gtk_editable_get_text(GTK_EDITABLE(entry))); }
    json_builder_end_object(builder); g_autoptr(JsonGenerator) gen=json_generator_new(); g_autoptr(JsonNode) root=json_builder_get_root(builder);
    json_generator_set_root(gen,root); g_autofree char *target=json_generator_to_data(gen,NULL);
    request(ui,"plan","repo-set",target,NULL); gtk_window_destroy(GTK_WINDOW(w));
}
static void repo_add(GtkButton *b,gpointer data) {
    (void)b; Admin *ui=data; GtkWidget *w=gtk_window_new(); gtk_window_set_application(GTK_WINDOW(w),GTK_APPLICATION(ui->app));
    gtk_window_set_transient_for(GTK_WINDOW(w),ui->window); gtk_window_set_modal(GTK_WINDOW(w),TRUE); gtk_window_set_default_size(GTK_WINDOW(w),560,380);
    gtk_window_set_title(GTK_WINDOW(w),"저장소 추가·수정"); GtkWidget *root=gtk_box_new(GTK_ORIENTATION_VERTICAL,12); gtk_box_append(GTK_BOX(root),adw_header_bar_new());
    GtkWidget *content=gtk_box_new(GTK_ORIENTATION_VERTICAL,12); gtk_widget_set_margin_start(content,24); gtk_widget_set_margin_end(content,24); gtk_widget_set_margin_bottom(content,24);
    gtk_box_append(GTK_BOX(content),label("HTTPS 주소와 설치된 서명 공개키를 지정하세요. 같은 이름의 저장소는 새 설정으로 갱신합니다.","dim-label"));
    const char *fields[]={"name","url","key"}, *titles[]={"저장소 이름","HTTPS 주소","공개키 경로 (/etc/ki2/trust 아래)"};
    for(guint i=0;i<3;i++) { GtkWidget *entry=adw_entry_row_new(); adw_preferences_row_set_title(ADW_PREFERENCES_ROW(entry),titles[i]); gtk_box_append(GTK_BOX(content),entry); g_object_set_data(G_OBJECT(w),fields[i],entry); }
    GtkWidget *save=gtk_button_new_with_label("변경 내용 확인"); gtk_widget_add_css_class(save,"suggested-action"); g_object_set_data(G_OBJECT(save),"window",w);
    g_signal_connect(save,"clicked",G_CALLBACK(repo_save),ui); gtk_box_append(GTK_BOX(content),save); gtk_box_append(GTK_BOX(root),content); gtk_window_set_child(GTK_WINDOW(w),root); gtk_window_present(GTK_WINDOW(w));
}
static void repositories(Admin *ui,JsonObject *data) {
    GtkWidget *p=ui->pages[2]; heading(p,"저장소","패키지 공급 주소와 서명 공개키, 저장된 목록의 상태를 확인하세요.");
    GtkWidget *g=group(p,"등록된 저장소","패키지를 가져올 주소와 설치된 공개키를 사용합니다.");
    JsonArray *repos=array(data,"repos");
    if(!length(repos)) row(g,"등록된 저장소가 없습니다","HTTPS 저장소와 서명 공개키를 추가하세요.","folder-remote-symbolic");
    for(guint i=0;i<length(repos);i++) {
        JsonObject *item=json_array_get_object_element(repos,i);
        g_autofree char *description=g_strdup_printf("%s\n공개키: %s\n목록: %s",str(item,"url"),*str(item,"key") ? str(item,"key") : "설정되지 않음",boolean(item,"cached") ? str(item,"cache_time") : "아직 동기화하지 않음");
        GtkWidget *r=row(g,str(item,"name"),description,"folder-remote-symbolic");
        note(r,boolean(item,"signed") ? "공개키 설정됨" : "공개키 필요",boolean(item,"signed") ? "success" : "warning");
        action(ui,r,"제거 계획","plan","repo-remove",str(item,"name"));
    }
    GtkWidget *add=gtk_button_new_with_label("저장소 추가·수정"); gtk_widget_set_halign(add,GTK_ALIGN_START);
    g_signal_connect(add,"clicked",G_CALLBACK(repo_add),ui); gtk_box_append(GTK_BOX(p),add);
}
static void diagnostics(Admin *ui,JsonObject *data) {
    GtkWidget *p=ui->pages[3]; heading(p,"진단 및 복구","문제의 근거를 확인하고 필요한 작업만 실행하세요.");
    GtkWidget *security_group=group(p,"보안 설정 검사","OpenSCAP · KIKI 전용 정책 · 읽기 전용 검사");
    GtkWidget *security_row=row(security_group,"SSH·계정·권한·커널·방화벽 설정","security-audit 그룹이 필요합니다. 관리자 인증 후 검사하며 설정 불일치와 관측 오류를 구분합니다.","security-high-symbolic");
    action(ui,security_row,"검사 계획","plan","security-scan","");
    GtkWidget *g=group(p,"진단",NULL); GtkWidget *r=row(g,"시스템 검사","여유 공간, 실패 서비스, 저장소와 미완료 패키지 작업을 확인합니다.","utilities-system-monitor-symbolic");
    action(ui,r,"진단 실행","diagnose","","");
    r=row(g,"이번 부팅의 경고·오류 로그","최근 200줄 · 현재 사용자에게 허용된 로그만 표시합니다.","text-x-generic-symbolic"); action(ui,r,"로그 보기","logs","","");
    r=row(g,"시스템 서비스 로그","관리자 인증 후 이번 부팅의 시스템 경고·오류 200줄을 조회합니다.","dialog-password-symbolic"); action(ui,r,"조회 계획","plan","system-logs","");
    r=row(g,"패키지 후처리 복구","남은 캐시·색인 갱신 작업의 실행 계획을 검토합니다.","view-refresh-symbolic"); action(ui,r,"후처리 계획","plan","hooks","");
    g=group(p,"실패한 서비스","서비스별 로그를 확인한 뒤 다시 시작할 수 있습니다.");
    JsonArray *failed=array(data,"failed");
    if(!length(failed)) row(g,"실패한 서비스가 없습니다","시스템이 보고한 현재 서비스 상태입니다.","emblem-ok-symbolic");
    for(guint i=0;i<length(failed);i++) {
        JsonObject *item=json_array_get_object_element(failed,i); r=row(g,str(item,"unit"),str(item,"description"),"dialog-warning-symbolic");
        action(ui,r,"시스템 로그","plan","system-logs",str(item,"unit")); action(ui,r,"복구 계획","plan","restart",str(item,"unit"));
    }
    g=group(p,"확장 기능","컨테이너·Kubernetes·AI 관리는 후속 단계에서 연결합니다.");
    row(g,"컨테이너 · Kubernetes · AI","현재 버전은 시스템·패키지·진단 관리에 집중합니다.","applications-system-symbolic");
}
static void render(Admin *ui) {
    JsonObject *data=json_node_get_object(json_parser_get_root(ui->snapshot));
    for(guint i=0;i<4;i++) { GtkWidget *child; while((child=gtk_widget_get_first_child(ui->pages[i]))) gtk_box_remove(GTK_BOX(ui->pages[i]),child); }
    overview(ui,data); packages(ui,data); repositories(ui,data); diagnostics(ui,data);
}
static void selected(GtkListBox *box,GtkListBoxRow *r,gpointer data) {
    (void)box; if(r) gtk_stack_set_visible_child_name(((Admin*)data)->stack,g_object_get_data(G_OBJECT(r),"page"));
}
static gboolean close_requested(GtkWindow *window,gpointer data) {
    (void)window; Admin *ui=data;
    if(ui->busy) gtk_label_set_text(ui->status,"진행 중인 작업이 끝난 뒤 창을 닫을 수 있습니다.");
    return ui->busy;
}
static void activate(GApplication *app,gpointer data) {
    Admin *ui=data;
    if(ui->window) { gtk_window_present(ui->window); return; }
    ui->app=ADW_APPLICATION(app); ui->window=GTK_WINDOW(adw_application_window_new(GTK_APPLICATION(app)));
    pixel_style(app);
    gtk_window_set_title(ui->window,"KIKI 관리자"); gtk_window_set_default_size(ui->window,1080,760);
    g_object_add_weak_pointer(G_OBJECT(ui->window),(gpointer*)&ui->window);
    g_signal_connect(ui->window,"close-request",G_CALLBACK(close_requested),ui);
    GtkWidget *root=gtk_box_new(GTK_ORIENTATION_VERTICAL,0), *header=adw_header_bar_new();
    GtkWidget *title=adw_window_title_new("KIKI 관리자","시스템 · 패키지 · 진단"); adw_header_bar_set_title_widget(ADW_HEADER_BAR(header),title);
    ui->spinner=gtk_spinner_new(); adw_header_bar_pack_end(ADW_HEADER_BAR(header),ui->spinner);
    ui->refresh=button(ui,"새로 확인","snapshot","",""); gtk_widget_add_css_class(ui->refresh,"flat"); adw_header_bar_pack_end(ADW_HEADER_BAR(header),ui->refresh);
    gtk_box_append(GTK_BOX(root),header); GtkWidget *body=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,0); gtk_widget_set_vexpand(body,TRUE);
    GtkWidget *sidebar=gtk_box_new(GTK_ORIENTATION_VERTICAL,16); gtk_widget_add_css_class(sidebar,"sidebar"); gtk_widget_set_size_request(sidebar,210,-1);
    GtkWidget *brand=label("KIKI OS","title-3"); gtk_widget_set_margin_start(brand,20); gtk_widget_set_margin_top(brand,24); gtk_box_append(GTK_BOX(sidebar),brand);
    GtkWidget *nav=gtk_list_box_new(); gtk_widget_add_css_class(nav,"navigation-sidebar"); gtk_box_append(GTK_BOX(sidebar),nav);
    ui->navigation=GTK_LIST_BOX(nav);
    const char *names[]={"overview","packages","repositories","diagnostics"}, *titles[]={"시스템 개요","패키지","저장소","진단 및 복구"}, *icons[]={"computer-symbolic","package-x-generic-symbolic","folder-remote-symbolic","utilities-system-monitor-symbolic"};
    for(guint i=0;i<4;i++) { GtkWidget *r=gtk_list_box_row_new(), *line=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,12);
        gtk_widget_set_margin_top(line,10); gtk_widget_set_margin_bottom(line,10); gtk_widget_set_margin_start(line,12);
        gtk_box_append(GTK_BOX(line),gtk_image_new_from_icon_name(icons[i])); gtk_box_append(GTK_BOX(line),label(titles[i],NULL));
        gtk_list_box_row_set_child(GTK_LIST_BOX_ROW(r),line); g_object_set_data(G_OBJECT(r),"page",(gpointer)names[i]); gtk_list_box_append(GTK_LIST_BOX(nav),r); }
    GtkWidget *foot=label("KIKI 관리자 0.1\nGNOME 데스크톱용","dim-label"); gtk_widget_set_vexpand(foot,TRUE); gtk_widget_set_valign(foot,GTK_ALIGN_END);
    gtk_widget_set_margin_start(foot,20); gtk_widget_set_margin_bottom(foot,20); gtk_box_append(GTK_BOX(sidebar),foot);
    gtk_box_append(GTK_BOX(body),sidebar); gtk_box_append(GTK_BOX(body),gtk_separator_new(GTK_ORIENTATION_VERTICAL));
    ui->stack=GTK_STACK(gtk_stack_new()); gtk_widget_set_hexpand(GTK_WIDGET(ui->stack),TRUE); gtk_stack_set_transition_type(ui->stack,GTK_STACK_TRANSITION_TYPE_CROSSFADE);
    for(guint i=0;i<4;i++) { GtkWidget *scroll=gtk_scrolled_window_new(), *clamp=adw_clamp_new();
        ui->pages[i]=gtk_box_new(GTK_ORIENTATION_VERTICAL,16); gtk_widget_set_margin_top(ui->pages[i],24); gtk_widget_set_margin_bottom(ui->pages[i],24);
        gtk_widget_set_margin_start(ui->pages[i],30); gtk_widget_set_margin_end(ui->pages[i],30);
        adw_clamp_set_maximum_size(ADW_CLAMP(clamp),1000); adw_clamp_set_child(ADW_CLAMP(clamp),ui->pages[i]); gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scroll),clamp);
        gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll),GTK_POLICY_NEVER,GTK_POLICY_AUTOMATIC); gtk_stack_add_named(ui->stack,scroll,names[i]); }
    gtk_box_append(GTK_BOX(body),GTK_WIDGET(ui->stack)); gtk_box_append(GTK_BOX(root),body);
    gtk_box_append(GTK_BOX(root),gtk_separator_new(GTK_ORIENTATION_HORIZONTAL)); ui->status=GTK_LABEL(label("시스템 정보를 불러오는 중…","dim-label"));
    gtk_widget_set_margin_start(GTK_WIDGET(ui->status),20); gtk_widget_set_margin_top(GTK_WIDGET(ui->status),10); gtk_widget_set_margin_bottom(GTK_WIDGET(ui->status),10);
    gtk_box_append(GTK_BOX(root),GTK_WIDGET(ui->status)); adw_application_window_set_content(ADW_APPLICATION_WINDOW(ui->window),root);
    ui->activity=gtk_text_buffer_new(NULL); g_signal_connect(nav,"row-selected",G_CALLBACK(selected),ui);
    gtk_list_box_select_row(GTK_LIST_BOX(nav),gtk_list_box_get_row_at_index(GTK_LIST_BOX(nav),0));
    gtk_window_present(ui->window);
    if(ui->snapshot) {
        render(ui);
        JsonObject *data=json_node_get_object(json_parser_get_root(ui->snapshot));
        g_autofree char *stamp=g_strdup_printf("최근 확인 · %s",str(data,"observed_at"));
        gtk_label_set_text(ui->status,stamp);
    } else request(ui,"snapshot","","",NULL);
}
static int command_line(GApplication *app,GApplicationCommandLine *line,gpointer data) {
    const char *page="overview", *requested=NULL;
    if(g_variant_dict_lookup(g_application_command_line_get_options_dict(line),"page","&s",&requested)) page=requested;
    const char *names[]={"overview","packages","repositories","diagnostics"};
    guint i=0;
    for(;i<G_N_ELEMENTS(names);i++) if(!strcmp(page,names[i])) break;
    if(i==G_N_ELEMENTS(names)) { g_application_command_line_printerr(line,"Unknown administrator page\n"); return 2; }
    g_application_activate(app); Admin *ui=data;
    gtk_list_box_select_row(ui->navigation,gtk_list_box_get_row_at_index(ui->navigation,i));
    return 0;
}
int main(int argc,char **argv) {
    setlocale(LC_ALL,""); Admin ui={0}; g_autoptr(AdwApplication) app=adw_application_new("org.kiki.Admin",G_APPLICATION_HANDLES_COMMAND_LINE);
    g_application_add_main_option(G_APPLICATION(app),"page",0,G_OPTION_FLAG_NONE,G_OPTION_ARG_STRING,"Open overview, packages, repositories or diagnostics","PAGE");
    g_signal_connect(app,"command-line",G_CALLBACK(command_line),&ui);
    g_signal_connect(app,"activate",G_CALLBACK(activate),&ui); int code=g_application_run(G_APPLICATION(app),argc,argv);
    g_clear_object(&ui.snapshot); g_clear_object(&ui.activity); return code;
}
