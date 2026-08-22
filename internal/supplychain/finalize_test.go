package supplychain

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fakeRunner struct {
	artifacts string
	calls     []string
}

func (runner *fakeRunner) Run(name string, args ...string) error {
	runner.calls = append(runner.calls, name+" "+strings.Join(args, " "))
	if name == "syft" {
		for _, arg := range args {
			if strings.HasPrefix(arg, "spdx-json=") {
				return os.WriteFile(strings.TrimPrefix(arg, "spdx-json="), []byte(`{"spdxVersion":"SPDX-2.3"}`), 0o640)
			}
		}
	}
	if name == "grype" {
		for index, arg := range args {
			if arg == "--file" {
				return os.WriteFile(args[index+1], []byte(`{"matches":[]}`), 0o640)
			}
		}
	}
	if name == "cosign" && len(args) > 1 && (args[0] == "sign" || args[0] == "sign-blob") {
		for index, arg := range args {
			if arg == "--bundle" {
				return os.WriteFile(args[index+1], []byte(`{"verificationMaterial":{}}`), 0o640)
			}
		}
	}
	return nil
}

func TestFinalizeFileGeneratesSignedEvidence(t *testing.T) {
	directory := t.TempDir()
	artifact := filepath.Join(directory, "kiki.iso")
	if err := os.WriteFile(artifact, []byte("ISO-CONTENT"), 0o640); err != nil {
		t.Fatal(err)
	}
	runner := &fakeRunner{artifacts: directory}
	evidence, err := FinalizeFile(FileFinalizeOptions{BuildID: "image-0001", Artifact: artifact, Source: "https://git.example.com/kiki/os.git", Revision: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", Artifacts: filepath.Join(directory, "evidence"), PackageType: "iso", Now: func() time.Time { return time.Date(2026, 7, 31, 0, 0, 0, 0, time.UTC) }, Runner: runner})
	if err != nil {
		t.Fatal(err)
	}
	if evidence.SizeBytes != int64(len("ISO-CONTENT")) || !shaPattern.MatchString(evidence.Digest) || !shaPattern.MatchString(evidence.SignatureDigest) {
		t.Fatalf("invalid file evidence: %#v", evidence)
	}
	if len(runner.calls) != 3 || !strings.Contains(runner.calls[0], "file:"+artifact) || !strings.Contains(runner.calls[1], "sbom:") || !strings.HasPrefix(runner.calls[2], "cosign sign-blob ") {
		t.Fatalf("unexpected commands: %#v", runner.calls)
	}
	data, err := os.ReadFile(evidence.ProvenancePath)
	if err != nil || !strings.Contains(string(data), evidence.Digest[len("sha256:"):]) {
		t.Fatalf("provenance does not bind artifact digest: %s (%v)", data, err)
	}
}

func TestFinalizeGeneratesSupplyChainEvidence(t *testing.T) {
	directory := t.TempDir()
	metadata := filepath.Join(directory, "metadata.json")
	if err := os.WriteFile(metadata, []byte(`{"containerimage.digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","containerimage.descriptor":{"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","size":812,"mediaType":"application/vnd.oci.image.manifest.v1+json"}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	runner := &fakeRunner{artifacts: directory}
	evidence, err := Finalize(FinalizeOptions{BuildID: "build-oci-1", Image: "registry.example.com/kiki/app:build-build-oci-1", Metadata: metadata, Source: "https://git.example.com/app.git", Revision: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", Artifacts: directory, PackageType: "cpm", Now: func() time.Time { return time.Date(2026, 7, 31, 0, 0, 0, 0, time.UTC) }, Runner: runner})
	if err != nil {
		t.Fatal(err)
	}
	if evidence.ImageRef != "registry.example.com/kiki/app@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" {
		t.Fatalf("unexpected immutable ref: %s", evidence.ImageRef)
	}
	if !shaPattern.MatchString(evidence.SBOMDigest) || !shaPattern.MatchString(evidence.ScanDigest) || !shaPattern.MatchString(evidence.ProvenanceDigest) || !shaPattern.MatchString(evidence.SignatureDigest) {
		t.Fatalf("invalid evidence: %#v", evidence)
	}
	if len(runner.calls) != 4 || !strings.HasPrefix(runner.calls[0], "syft ") || !strings.HasPrefix(runner.calls[1], "grype ") || !strings.HasPrefix(runner.calls[2], "cosign sign ") || !strings.HasPrefix(runner.calls[3], "cosign attest ") {
		t.Fatalf("unexpected commands: %#v", runner.calls)
	}
	provenance, err := os.ReadFile(evidence.ProvenancePath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(provenance), "slsa.dev/provenance/v1") || !strings.Contains(string(provenance), "bbbbbbbb") {
		t.Fatalf("invalid provenance: %s", provenance)
	}
}

func TestFinalizeRejectsUnpinnedMetadata(t *testing.T) {
	directory := t.TempDir()
	metadata := filepath.Join(directory, "metadata.json")
	if err := os.WriteFile(metadata, []byte(`{"containerimage.digest":"latest","containerimage.descriptor":{"digest":"latest","size":1,"mediaType":"x"}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := Finalize(FinalizeOptions{BuildID: "build-oci-1", Image: "registry.example.com/kiki/app:tag", Metadata: metadata, Source: "https://git.example.com/app.git", Revision: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", Artifacts: directory, PackageType: "oci", Runner: &fakeRunner{}})
	if err == nil {
		t.Fatal("mutable digest accepted")
	}
}
