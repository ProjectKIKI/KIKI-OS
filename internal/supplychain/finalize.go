package supplychain

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type FinalizeOptions struct {
	BuildID     string
	Image       string
	Metadata    string
	Source      string
	Revision    string
	Artifacts   string
	PackageType string
	SigningKey  string
	Now         func() time.Time
	Runner      Runner
}

type Evidence struct {
	ImageRef         string `json:"image_ref"`
	Digest           string `json:"digest"`
	SBOMPath         string `json:"sbom_path"`
	SBOMDigest       string `json:"sbom_digest"`
	ScanPath         string `json:"scan_path"`
	ScanDigest       string `json:"scan_digest"`
	ProvenancePath   string `json:"provenance_path"`
	ProvenanceDigest string `json:"provenance_digest"`
	SignaturePath    string `json:"signature_path"`
	SignatureDigest  string `json:"signature_digest"`
	SizeBytes        uint64 `json:"size_bytes"`
	MediaType        string `json:"media_type"`
}

type FileFinalizeOptions struct {
	BuildID     string
	Artifact    string
	Source      string
	Revision    string
	Artifacts   string
	PackageType string
	SigningKey  string
	Now         func() time.Time
	Runner      Runner
}

type FileEvidence struct {
	ArtifactPath     string `json:"artifact_path"`
	Digest           string `json:"digest"`
	SizeBytes        int64  `json:"size_bytes"`
	SBOMPath         string `json:"sbom_path"`
	SBOMDigest       string `json:"sbom_digest"`
	ScanPath         string `json:"scan_path"`
	ScanDigest       string `json:"scan_digest"`
	ProvenancePath   string `json:"provenance_path"`
	ProvenanceDigest string `json:"provenance_digest"`
	SignaturePath    string `json:"signature_path"`
	SignatureDigest  string `json:"signature_digest"`
}

type Runner interface {
	Run(name string, args ...string) error
}

type ExecRunner struct{}

func (ExecRunner) Run(name string, args ...string) error {
	command := exec.Command(name, args...)
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	return command.Run()
}

var shaPattern = regexp.MustCompile(`^sha256:[a-f0-9]{64}$`)
var revisionPattern = regexp.MustCompile(`^[a-f0-9]{40}([a-f0-9]{24})?$`)
var buildIDPattern = regexp.MustCompile(`^[a-z0-9]([-a-z0-9.]{0,61}[a-z0-9])?$`)

func Finalize(options FinalizeOptions) (Evidence, error) {
	if !buildIDPattern.MatchString(options.BuildID) || !revisionPattern.MatchString(options.Revision) {
		return Evidence{}, errors.New("invalid build ID or source revision")
	}
	if options.PackageType != "oci" && options.PackageType != "cpm" && options.PackageType != "model" {
		return Evidence{}, errors.New("package type must be oci, cpm, or model")
	}
	if options.Runner == nil {
		options.Runner = ExecRunner{}
	}
	if options.Now == nil {
		options.Now = time.Now
	}
	if options.SigningKey == "" {
		options.SigningKey = "/run/secrets/signing/cosign.key"
	}
	if err := os.MkdirAll(options.Artifacts, 0o750); err != nil {
		return Evidence{}, err
	}
	digest, size, mediaType, err := readBuildKitDescriptor(options.Metadata)
	if err != nil {
		return Evidence{}, err
	}
	imageRef, err := immutableImageRef(options.Image, digest)
	if err != nil {
		return Evidence{}, err
	}

	sbomPath := filepath.Join(options.Artifacts, options.BuildID+".spdx.json")
	scanPath := filepath.Join(options.Artifacts, options.BuildID+".vulnerabilities.json")
	provenancePath := filepath.Join(options.Artifacts, options.BuildID+".provenance.json")
	signaturePath := filepath.Join(options.Artifacts, options.BuildID+".sigstore.json")
	if err := options.Runner.Run("syft", imageRef, "-o", "spdx-json="+sbomPath); err != nil {
		return Evidence{}, fmt.Errorf("generate SBOM: %w", err)
	}
	if err := options.Runner.Run("grype", imageRef, "-o", "json", "--file", scanPath); err != nil {
		return Evidence{}, fmt.Errorf("scan vulnerabilities: %w", err)
	}
	provenance := map[string]any{
		"_type": "https://in-toto.io/Statement/v1", "predicateType": "https://slsa.dev/provenance/v1",
		"subject": []any{map[string]any{"name": strings.Split(imageRef, "@")[0], "digest": map[string]any{"sha256": strings.TrimPrefix(digest, "sha256:")}}},
		"predicate": map[string]any{
			"buildDefinition": map[string]any{"buildType": "https://kiki.io/build/" + options.PackageType + "/v1", "externalParameters": map[string]any{"source": options.Source, "revision": options.Revision}},
			"runDetails":      map[string]any{"builder": map[string]any{"id": "https://kiki.io/builders/kiki-supplychain/v1"}, "metadata": map[string]any{"invocationId": options.BuildID, "finishedOn": options.Now().UTC().Format(time.RFC3339)}},
		},
	}
	data, err := json.MarshalIndent(provenance, "", "  ")
	if err != nil {
		return Evidence{}, err
	}
	if err := os.WriteFile(provenancePath, data, 0o640); err != nil {
		return Evidence{}, err
	}
	if err := options.Runner.Run("cosign", "sign", "--yes", "--key", options.SigningKey, "--bundle", signaturePath, imageRef); err != nil {
		return Evidence{}, fmt.Errorf("sign image: %w", err)
	}
	if err := options.Runner.Run("cosign", "attest", "--yes", "--key", options.SigningKey, "--type", "slsaprovenance", "--predicate", provenancePath, imageRef); err != nil {
		return Evidence{}, fmt.Errorf("attest provenance: %w", err)
	}

	sbomDigest, err := fileDigest(sbomPath)
	if err != nil {
		return Evidence{}, err
	}
	scanDigest, err := fileDigest(scanPath)
	if err != nil {
		return Evidence{}, err
	}
	provenanceDigest, err := fileDigest(provenancePath)
	if err != nil {
		return Evidence{}, err
	}
	signatureDigest, err := fileDigest(signaturePath)
	if err != nil {
		return Evidence{}, err
	}
	return Evidence{ImageRef: imageRef, Digest: digest, SizeBytes: size, MediaType: mediaType, SBOMPath: sbomPath, SBOMDigest: sbomDigest, ScanPath: scanPath, ScanDigest: scanDigest, ProvenancePath: provenancePath, ProvenanceDigest: provenanceDigest, SignaturePath: signaturePath, SignatureDigest: signatureDigest}, nil
}

func FinalizeFile(options FileFinalizeOptions) (FileEvidence, error) {
	if !buildIDPattern.MatchString(options.BuildID) || !revisionPattern.MatchString(options.Revision) {
		return FileEvidence{}, errors.New("invalid build ID or source revision")
	}
	if options.PackageType != "bos" && options.PackageType != "iso" && options.PackageType != "pxe" && options.PackageType != "disk" && options.PackageType != "model" {
		return FileEvidence{}, errors.New("file package type must be bos, iso, pxe, disk, or model")
	}
	artifact := filepath.Clean(options.Artifact)
	info, err := os.Lstat(artifact)
	if err != nil {
		return FileEvidence{}, fmt.Errorf("inspect artifact: %w", err)
	}
	if !info.Mode().IsRegular() || info.Size() <= 0 {
		return FileEvidence{}, errors.New("artifact must be a non-empty regular file")
	}
	if options.Runner == nil {
		options.Runner = ExecRunner{}
	}
	if options.Now == nil {
		options.Now = time.Now
	}
	if options.SigningKey == "" {
		options.SigningKey = "/run/secrets/signing/cosign.key"
	}
	if err := os.MkdirAll(options.Artifacts, 0o750); err != nil {
		return FileEvidence{}, err
	}
	digest, err := fileDigest(artifact)
	if err != nil {
		return FileEvidence{}, err
	}
	sbomPath := filepath.Join(options.Artifacts, options.BuildID+".spdx.json")
	scanPath := filepath.Join(options.Artifacts, options.BuildID+".vulnerabilities.json")
	provenancePath := filepath.Join(options.Artifacts, options.BuildID+".provenance.json")
	signaturePath := filepath.Join(options.Artifacts, options.BuildID+".sigstore.json")
	if err := options.Runner.Run("syft", "file:"+artifact, "-o", "spdx-json="+sbomPath); err != nil {
		return FileEvidence{}, fmt.Errorf("generate file SBOM: %w", err)
	}
	if err := options.Runner.Run("grype", "sbom:"+sbomPath, "-o", "json", "--file", scanPath); err != nil {
		return FileEvidence{}, fmt.Errorf("scan file SBOM: %w", err)
	}
	provenance := map[string]any{
		"_type": "https://in-toto.io/Statement/v1", "predicateType": "https://slsa.dev/provenance/v1",
		"subject": []any{map[string]any{"name": filepath.Base(artifact), "digest": map[string]any{"sha256": strings.TrimPrefix(digest, "sha256:")}}},
		"predicate": map[string]any{
			"buildDefinition": map[string]any{"buildType": "https://kiki.io/build/" + options.PackageType + "/v1", "externalParameters": map[string]any{"source": options.Source, "revision": options.Revision}},
			"runDetails":      map[string]any{"builder": map[string]any{"id": "https://kiki.io/builders/kiki-image-factory/v1"}, "metadata": map[string]any{"invocationId": options.BuildID, "finishedOn": options.Now().UTC().Format(time.RFC3339)}},
		},
	}
	data, err := json.MarshalIndent(provenance, "", "  ")
	if err != nil {
		return FileEvidence{}, err
	}
	if err := os.WriteFile(provenancePath, data, 0o640); err != nil {
		return FileEvidence{}, err
	}
	if err := options.Runner.Run("cosign", "sign-blob", "--yes", "--key", options.SigningKey, "--bundle", signaturePath, artifact); err != nil {
		return FileEvidence{}, fmt.Errorf("sign artifact blob: %w", err)
	}
	sbomDigest, err := fileDigest(sbomPath)
	if err != nil {
		return FileEvidence{}, err
	}
	scanDigest, err := fileDigest(scanPath)
	if err != nil {
		return FileEvidence{}, err
	}
	provenanceDigest, err := fileDigest(provenancePath)
	if err != nil {
		return FileEvidence{}, err
	}
	signatureDigest, err := fileDigest(signaturePath)
	if err != nil {
		return FileEvidence{}, err
	}
	return FileEvidence{ArtifactPath: artifact, Digest: digest, SizeBytes: info.Size(), SBOMPath: sbomPath, SBOMDigest: sbomDigest, ScanPath: scanPath, ScanDigest: scanDigest, ProvenancePath: provenancePath, ProvenanceDigest: provenanceDigest, SignaturePath: signaturePath, SignatureDigest: signatureDigest}, nil
}

func readBuildKitDescriptor(path string) (string, uint64, string, error) {
	data, err := os.ReadFile(filepath.Clean(path))
	if err != nil {
		return "", 0, "", fmt.Errorf("read BuildKit metadata: %w", err)
	}
	var metadata map[string]json.RawMessage
	if err := json.Unmarshal(data, &metadata); err != nil {
		return "", 0, "", fmt.Errorf("parse BuildKit metadata: %w", err)
	}
	var digest string
	if err := json.Unmarshal(metadata["containerimage.digest"], &digest); err != nil || !shaPattern.MatchString(digest) {
		return "", 0, "", errors.New("BuildKit metadata has no valid containerimage.digest")
	}
	var descriptor struct {
		Digest    string `json:"digest"`
		Size      uint64 `json:"size"`
		MediaType string `json:"mediaType"`
	}
	if err := json.Unmarshal(metadata["containerimage.descriptor"], &descriptor); err != nil || descriptor.Digest != digest || descriptor.Size == 0 || descriptor.MediaType == "" {
		return "", 0, "", errors.New("BuildKit metadata has no matching manifest descriptor")
	}
	return digest, descriptor.Size, descriptor.MediaType, nil
}

func immutableImageRef(image, digest string) (string, error) {
	if !shaPattern.MatchString(digest) || strings.Contains(image, "@") || !strings.Contains(image, "/") {
		return "", errors.New("invalid image reference or digest")
	}
	lastSlash := strings.LastIndex(image, "/")
	if colon := strings.LastIndex(image, ":"); colon > lastSlash {
		image = image[:colon]
	}
	return image + "@" + digest, nil
}

func fileDigest(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(data)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}
