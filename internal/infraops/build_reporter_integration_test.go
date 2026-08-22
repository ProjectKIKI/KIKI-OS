package infraops_test

import (
	"context"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"example.com/aos-pkg/internal/buildsystem"
	"example.com/aos-pkg/internal/infraops"
	"example.com/aos-pkg/internal/supplychain"
)

const pinnedBuildImage = "registry.local/kiki/build@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func TestTrustedBuildReporterPublishesArtifactEvidence(t *testing.T) {
	config := buildsystem.Config{
		GitImage: pinnedBuildImage, BOSBuilderImage: pinnedBuildImage, SupplyChainImage: pinnedBuildImage,
		AllowedGitHosts: []string{"git.example.com"}, EgressProxyURL: "http://proxy:8080", EgressProxyCIDR: "10.20.0.10/32",
		SigningSecret: "signing", BuildTokenSecret: "kiki-build-reporter", InfraOpsURL: "http://kiki-infraops:8090",
	}
	store, err := infraops.NewStore(filepath.Join(t.TempDir(), "state.json"), infraops.RuntimeImages{}, config)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.CreateBuild("operator", infraops.BuildRequest{
		ID: "build-reporter-1", Type: "bos",
		Source:      buildsystem.Source{URL: "https://git.example.com/kiki/packages.git", Revision: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
		ContextPath: "packages/agent", OutputName: "kiki-agent.bos", ArtifactPVC: "artifacts", Platforms: []string{"linux/amd64"},
		Security: infraops.BuildSecurity{GenerateSBOM: true, GenerateProvenance: true, Sign: true},
	})
	if err != nil {
		t.Fatal(err)
	}
	handler, err := infraops.NewServerWithPrincipals(store, []infraops.Principal{{Token: "build-token", Actor: "build-worker", Roles: []string{"build-worker"}}})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	defer server.Close()
	reporter := supplychain.Reporter{BaseURL: server.URL, Token: "build-token", Actor: "build-worker", HTTP: server.Client()}
	if err := reporter.Advance(context.Background(), "build-reporter-1", "Fetching", "Validating", "Building", "Testing", "Scanning", "Signing", "Publishing"); err != nil {
		t.Fatal(err)
	}
	result := supplychain.BuildReport{
		Phase: "Succeeded", Digest: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", SizeBytes: 2048,
		MediaType:        "application/vnd.kiki.bos.v1+gzip",
		SBOMDigest:       "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
		ScanDigest:       "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
		ProvenanceDigest: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
		SignatureDigest:  "sha256:1111111111111111111111111111111111111111111111111111111111111111",
	}
	if err := reporter.Report(context.Background(), "build-reporter-1", result); err != nil {
		t.Fatal(err)
	}
	artifacts := store.ListArtifacts()
	if len(artifacts) != 1 || artifacts[0].Digest != result.Digest || artifacts[0].SignatureDigest != result.SignatureDigest {
		t.Fatalf("artifact evidence was not persisted: %#v", artifacts)
	}
}
