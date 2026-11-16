package main

import (
 "bytes"
 "encoding/json"
 "os"
 "path/filepath"
 "strings"
 "testing"
)

func TestPlanningOriginMatchesMediaAndEntryPath(t *testing.T) {
 root := t.TempDir(); repo := filepath.Join(root,"kiki","repo")
 if err := os.MkdirAll(repo,0755); err != nil { t.Fatal(err) }
 write := func(path string, data []byte) { t.Helper(); if err := os.WriteFile(path,data,0600); err != nil { t.Fatal(err) } }
 index := []byte(`{}`); meta := []byte(`{"channel":"v13-metadata-test"}`)
 write(filepath.Join(repo,"index.x86_64.json"),index);write(filepath.Join(repo,"metadata.x86_64.json"),meta)
 receipt,_ := json.Marshal(map[string]string{"source_commit":strings.Repeat("b",40),"source_state":"modified-candidate","source_archive_sha256":strings.Repeat("c",64),"source_tree_sha256":strings.Repeat("d",64)})
 write(filepath.Join(root,"kiki","build-inputs.json"),receipt)
 origin := installerOrigin{Schema:"kiki-installer-origin-v1",Channel:"v13-metadata-test",MetadataSHA256:dataSHA(meta),IndexSHA256:dataSHA(index),SourceCommit:strings.Repeat("b",40),SourceState:"modified-candidate",ArchiveSHA256:strings.Repeat("c",64),TreeSHA256:strings.Repeat("d",64),InputSHA256:dataSHA(receipt)}
 raw,_ := json.Marshal(origin); originPath:=filepath.Join(root,"origin.json");write(originPath,raw)
 t.Setenv("KIKI_INSTALLER_ORIGIN",originPath)
 plan:=NewDefaultPlan("server-core");plan.Source.MediaRoot=root
 for _, frontend:=range []string{"gtk","tui","cli","unattended"} {
  t.Setenv("KIKI_INSTALLER_FRONTEND",frontend)
  var out bytes.Buffer
  if err:=WritePlanYAML(&out,plan);err!=nil {t.Fatal(err)}
  for _, expected:=range []string{`channel: "v13-metadata-test"`,`frontend: "`+frontend+`"`,`source_commit: "`+strings.Repeat("b",40)+`"`,`input_manifest_sha256: "`+dataSHA(receipt)+`"`,`executor: "pending"`} {
   if !strings.Contains(out.String(),expected){t.Fatalf("missing %s",expected)}
  }
 }
 t.Setenv("KIKI_INSTALLER_FRONTEND","");plan.Mode="unattended"
 var out bytes.Buffer
 if err:=WritePlanYAML(&out,plan);err!=nil || !strings.Contains(out.String(),`frontend: "unattended"`){t.Fatalf("unattended path: %v",err)}
 write(filepath.Join(repo,"metadata.x86_64.json"),[]byte(`{"channel":"wrong"}`))
 target:=filepath.Join(root,"keep.yaml");write(target,[]byte("preserve existing plan"))
 if err:=WritePlanFile(target,plan);err==nil {t.Fatal("tampered media accepted")}
 preserved,_:=os.ReadFile(target);if string(preserved)!="preserve existing plan"{t.Fatal("existing plan overwritten on origin failure")}
}

func TestMissingExplicitOriginFails(t *testing.T) {
 t.Setenv("KIKI_INSTALLER_ORIGIN",filepath.Join(t.TempDir(),"missing.json"))
 t.Setenv("KIKI_INSTALLER_FRONTEND","gtk")
 var out bytes.Buffer
 if err:=WritePlanYAML(&out,NewDefaultPlan("server-core"));err==nil {t.Fatal("missing explicit origin accepted")}
 if out.Len()!=0 {t.Fatal("partial plan emitted before origin validation")}
}
