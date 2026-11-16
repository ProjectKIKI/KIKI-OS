package main

import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "flag"
 "fmt"
 "os"
 "path/filepath"
 "regexp"
)

type GenerationPlan struct {
 Frontend, Planner, Executor string
 SourceCommit, SourceState, SourceArchiveSHA256, SourceTreeSHA256, InputManifestSHA256 string
}

type installerOrigin struct {
 Schema string `json:"schema"`
 Channel string `json:"channel"`
 MetadataSHA256 string `json:"metadata_sha256"`
 IndexSHA256 string `json:"repository_index_sha256"`
 SourceCommit string `json:"source_commit"`
 SourceState string `json:"source_state"`
 ArchiveSHA256 string `json:"source_archive_sha256"`
 TreeSHA256 string `json:"source_tree_sha256"`
 InputSHA256 string `json:"input_manifest_sha256"`
}

func dataSHA(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func applyInstallerOrigin(plan InstallPlan) (InstallPlan, error) {
 frontend := os.Getenv("KIKI_INSTALLER_FRONTEND")
 if frontend == "" {
  frontend = "cli"
  if f := flag.Lookup("fullscreen"); f != nil && f.Value.String() == "true" { frontend = "tui" }
  if plan.Mode == "unattended" { frontend = "unattended" }
 }
 if frontend != "gtk" && frontend != "tui" && frontend != "cli" && frontend != "unattended" { return plan, fmt.Errorf("invalid installer frontend") }
 plan.Generation = GenerationPlan{Frontend: frontend, Planner: "kiki-installer-tui", Executor: "pending"}
 if plan.Source.Type != "local-installer-media" { return plan, nil }
 path := os.Getenv("KIKI_INSTALLER_ORIGIN")
 explicit := path != ""
 if path == "" { path = "/etc/kiki/installer-origin.json" }
 raw, err := os.ReadFile(path)
 if os.IsNotExist(err) && !explicit { return plan, nil }
 if err != nil { return plan, err }
 var origin installerOrigin
 if err = json.Unmarshal(raw, &origin); err != nil { return plan, err }
 if origin.Schema != "kiki-installer-origin-v1" || !regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+-]{0,94}$`).MatchString(origin.Channel) { return plan, fmt.Errorf("invalid installer origin") }
 verify := func(path, expected string) error {
  data, err := os.ReadFile(path)
  if err != nil { return err }
  if dataSHA(data) != expected { return fmt.Errorf("installer origin SHA mismatch: %s", filepath.Base(path)) }
  return nil
 }
 repo := filepath.Join(plan.Source.MediaRoot, "kiki", "repo")
 if err = verify(filepath.Join(repo, "metadata.x86_64.json"), origin.MetadataSHA256); err != nil { return plan, err }
 if err = verify(filepath.Join(repo, "index.x86_64.json"), origin.IndexSHA256); err != nil { return plan, err }
 metaBytes, err := os.ReadFile(filepath.Join(repo, "metadata.x86_64.json")); if err != nil { return plan, err }
 var meta struct { Channel string `json:"channel"` }
 if err = json.Unmarshal(metaBytes, &meta); err != nil || meta.Channel != origin.Channel { return plan, fmt.Errorf("actual media channel differs from origin") }
 if origin.InputSHA256 != "" {
  receiptPath := filepath.Join(plan.Source.MediaRoot, "kiki", "build-inputs.json")
  if err = verify(receiptPath, origin.InputSHA256); err != nil { return plan, err }
  receiptBytes, err := os.ReadFile(receiptPath); if err != nil { return plan, err }
  var receipt installerOrigin
  // The build receipt uses source_archive_sha256/source_tree_sha256 rather than the compact names.
  if err = json.Unmarshal(receiptBytes, &receipt); err != nil { return plan, err }
  if receipt.SourceCommit != origin.SourceCommit || receipt.SourceState != origin.SourceState || receipt.ArchiveSHA256 != origin.ArchiveSHA256 || receipt.TreeSHA256 != origin.TreeSHA256 { return plan, fmt.Errorf("source receipt differs from installer origin") }
  if !regexp.MustCompile(`^[0-9a-f]{40}$`).MatchString(origin.SourceCommit) { return plan, fmt.Errorf("invalid source commit") }
  for _, hash := range []string{origin.ArchiveSHA256, origin.TreeSHA256, origin.InputSHA256} {
   if !regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(hash) { return plan, fmt.Errorf("invalid source SHA") }
  }
 }
 plan.Source.Channel = origin.Channel
 plan.Generation.SourceCommit = origin.SourceCommit
 plan.Generation.SourceState = origin.SourceState
 plan.Generation.SourceArchiveSHA256 = origin.ArchiveSHA256
 plan.Generation.SourceTreeSHA256 = origin.TreeSHA256
 plan.Generation.InputManifestSHA256 = origin.InputSHA256
 return plan, nil
}
