package desktopcontext

import("net/http/httptest";"net/url";"os";"path/filepath";"strings";"testing")

func TestImport(t *testing.T){
 p:=filepath.Join(t.TempDir(),"index.html");os.WriteFile(p,[]byte(`<html><textarea id="conversation-question"></textarea><form id="conversation-question-form"></form></html>`),0600)
 for _,tc:=range []struct{name,question,origin,version string;status int}{
  {"normal","호스트: local\n서비스: sshd.service\n로그 < & 정상","null","1",200},
  {"html injection","</script><script>alert(1)</script>","null","1",200},
  {"too long",strings.Repeat("😀",501),"null","1",400},
  {"boundary",strings.Repeat("😀",500),"null","1",200},
  {"empty"," ","null","1",400},
  {"origin","example","https://evil.example","1",403},
  {"missing origin","example","","1",403},
  {"version","example","null","2",400},
 }{t.Run(tc.name,func(t *testing.T){
  r:=httptest.NewRequest("POST","/desktop-context",strings.NewReader(url.Values{"question":{tc.question},"version":{tc.version}}.Encode()));r.Header.Set("Origin",tc.origin);r.Header.Set("Content-Type","application/x-www-form-urlencoded")
  w:=httptest.NewRecorder();Handler(p).ServeHTTP(w,r);if w.Code!=tc.status{t.Fatalf("status=%d",w.Code)}
  if w.Header().Get("Cache-Control")!="no-store"{t.Fatal("cache")}
  if tc.status==200 && strings.Contains(w.Body.String(),"<script>alert(1)</script>"){t.Fatal("HTML injection")}
 })}
 for _,method:=range []string{"GET","PUT","DELETE"}{r:=httptest.NewRequest(method,"/desktop-context",nil);w:=httptest.NewRecorder();Handler(p).ServeHTTP(w,r);if w.Code!=405{t.Fatal(w.Code)}}
}
