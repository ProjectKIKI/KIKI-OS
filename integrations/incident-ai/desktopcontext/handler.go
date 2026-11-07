// Package desktopcontext imports a reviewed desktop question without executing it.
package desktopcontext

import (
 "bytes"
 "encoding/json"
 "io"
 "net/http"
 "os"
 "strings"
 "unicode/utf16"
 "unicode/utf8"
)

// Register adds one public, non-executing renderer before the existing file server.
// Authentication and CSRF on all analysis APIs must remain unchanged.
func Register(mux *http.ServeMux, indexPath string) {
 mux.Handle("/desktop-context", Handler(indexPath))
}

func Handler(indexPath string) http.Handler {
 return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
  w.Header().Set("Cache-Control", "no-store")
  w.Header().Set("Referrer-Policy", "no-referrer")
  w.Header().Set("X-Content-Type-Options", "nosniff")
  w.Header().Set("X-Frame-Options", "DENY")
  if r.URL.Path!="/desktop-context" || r.URL.RawQuery!="" { http.Error(w,"잘못된 가져오기 경로",400);return }
  if r.Method!="POST" { w.Header().Set("Allow","POST");http.Error(w,"운영 앱에서 다시 열어주세요",405);return }
  if r.Header.Get("Origin")!="null" && r.Header.Get("Origin")!="https://incident-ai.lab.terminal-lab.kr" { http.Error(w,"허용되지 않은 가져오기 출처",403);return }
  if r.Header.Get("Content-Type")!="application/x-www-form-urlencoded" { http.Error(w,"잘못된 문맥 형식",415);return }
  r.Body=http.MaxBytesReader(w,r.Body,16384)
  body,err:=io.ReadAll(r.Body);if err!=nil { http.Error(w,"문맥 크기 초과",413);return }
  r.Body=io.NopCloser(bytes.NewReader(body))
  if err=r.ParseForm();err!=nil || len(r.PostForm)!=2 || len(r.PostForm["question"])!=1 || len(r.PostForm["version"])!=1 || r.PostForm.Get("version")!="1" { http.Error(w,"잘못된 가져오기 계약",400);return }
  draft:=r.PostForm.Get("question")
  if !utf8.ValidString(draft) || strings.TrimSpace(draft)=="" || len(utf16.Encode([]rune(draft)))>1000 || strings.ContainsRune(draft,0) { http.Error(w,"질문은 1,000자 이내여야 합니다",400);return }
  page,err:=os.ReadFile(indexPath);if err!=nil { http.Error(w,"분석 화면을 준비할 수 없습니다",503);return }
  if !bytes.Contains(page,[]byte(`id="conversation-question"`)) { http.Error(w,"호환되지 않는 분석 화면",503);return }
  // encoding/json escapes HTML delimiters, including </script>, and U+2028/2029.
  data,_:=json.Marshal(draft)
  script:=[]byte("<script>"+strings.ReplaceAll(receiver,"DRAFT_JSON",string(data))+"</script>")
  page=bytes.Replace(page,[]byte("</html>"),append(script,[]byte("</html>")...),1)
  w.Header().Set("Content-Type","text/html; charset=utf-8")
  w.Write(page)
 })
}

const receiver = `(function(){
 'use strict';
 const input=document.getElementById('conversation-question');
 const form=document.getElementById('conversation-question-form');
 if(!input||!form)return;
 const notice=document.createElement('div');notice.setAttribute('role','status');
 const title=document.createElement('p');title.textContent='KIKI 운영에서 가져온 문맥입니다. 호스트·서비스·로그를 검토하세요. 아직 분석 요청을 전송하지 않았습니다.';
 const label=document.createElement('label'),approve=document.createElement('input');approve.type='checkbox';approve.id='desktop-context-approve';
 label.append(approve,document.createTextNode(' 이 문맥을 검토했으며 분석 요청 전송을 승인합니다.'));
 notice.append(title,label);form.prepend(notice);
 input.value=DRAFT_JSON;input.dispatchEvent(new Event('input',{bubbles:true}));
 input.addEventListener('input',()=>{approve.checked=false});
 form.addEventListener('submit',e=>{if(!approve.checked){e.preventDefault();e.stopImmediatePropagation();title.textContent='문맥을 검토하고 전송 승인 항목을 선택하세요.';approve.focus()}},true);
 // Replacing the POST history entry prevents reload from replaying its body.
 history.replaceState(null,'','/#ask');
 if(typeof selectView==='function')selectView();
 })();`
