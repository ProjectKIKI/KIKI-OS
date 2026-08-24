package stage3

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const DefaultRemotePlanLimit int64 = 4 << 20
const defaultRemoteSignatureLimit int64 = 16 << 10

type RemotePlanOptions struct {
	URL             string
	SHA256          string
	Signature       string
	PublicKeyPath   string
	DownloadedPath  string
	VerifiedPath    string
	AllowUnverified bool
	MaxBytes        int64
	Client          *http.Client
}

type RemotePlanResult struct {
	URL                string
	SHA256             string
	Size               int64
	DownloadedPath     string
	VerifiedPath       string
	Verified           bool
	SignatureVerified  bool
	VerificationMethod string
}

func FetchRemotePlan(ctx context.Context, options RemotePlanOptions) (RemotePlanResult, error) {
	parsed, err := url.Parse(strings.TrimSpace(options.URL))
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		return RemotePlanResult{}, errors.New("remote plan URL must use http or https")
	}
	expected, err := normalizeDigest(options.SHA256)
	if err != nil {
		return RemotePlanResult{}, err
	}
	hasSignature := strings.TrimSpace(options.Signature) != ""
	if expected == "" && !hasSignature && !options.AllowUnverified {
		return RemotePlanResult{}, errors.New("remote plan requires sha256 or Ed25519 signature verification")
	}
	if hasSignature && strings.TrimSpace(options.PublicKeyPath) == "" {
		return RemotePlanResult{}, errors.New("remote plan Ed25519 signature requires a public key")
	}
	if options.DownloadedPath == "" || options.VerifiedPath == "" {
		return RemotePlanResult{}, errors.New("remote plan downloaded and verified paths are required")
	}
	if options.MaxBytes <= 0 {
		options.MaxBytes = DefaultRemotePlanLimit
	}
	if options.Client == nil {
		options.Client = &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(request *http.Request, via []*http.Request) error {
			if request.URL.Scheme != "http" && request.URL.Scheme != "https" {
				return errors.New("remote plan redirect must use http or https")
			}
			if len(via) >= 5 {
				return errors.New("too many remote plan redirects")
			}
			if len(via) > 0 && via[0].URL.Scheme == "https" && request.URL.Scheme != "https" {
				return errors.New("remote plan redirect cannot downgrade https")
			}
			return nil
		}}
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
	if err != nil {
		return RemotePlanResult{}, err
	}
	request.Header.Set("User-Agent", "kiki-agent-stage3/0.1")
	response, err := options.Client.Do(request)
	if err != nil {
		return RemotePlanResult{}, fmt.Errorf("download remote plan: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return RemotePlanResult{}, fmt.Errorf("download remote plan: HTTP %d", response.StatusCode)
	}
	limited := io.LimitReader(response.Body, options.MaxBytes+1)
	data, err := io.ReadAll(limited)
	if err != nil {
		return RemotePlanResult{}, fmt.Errorf("read remote plan: %w", err)
	}
	if int64(len(data)) > options.MaxBytes {
		return RemotePlanResult{}, fmt.Errorf("remote plan exceeds %d bytes", options.MaxBytes)
	}
	if err := writeProtected(options.DownloadedPath, data); err != nil {
		return RemotePlanResult{}, err
	}
	digestBytes := sha256.Sum256(data)
	digest := hex.EncodeToString(digestBytes[:])
	if expected != "" && digest != expected {
		return RemotePlanResult{URL: parsed.String(), SHA256: digest, Size: int64(len(data)), DownloadedPath: options.DownloadedPath}, errors.New("remote plan SHA-256 verification failed")
	}
	signatureVerified := false
	if hasSignature {
		signature, err := loadPlanSignature(ctx, options.Signature, options.Client)
		if err != nil {
			return RemotePlanResult{URL: parsed.String(), SHA256: digest, Size: int64(len(data)), DownloadedPath: options.DownloadedPath}, err
		}
		publicKey, err := loadEd25519PublicKey(options.PublicKeyPath)
		if err != nil {
			return RemotePlanResult{URL: parsed.String(), SHA256: digest, Size: int64(len(data)), DownloadedPath: options.DownloadedPath}, err
		}
		if !ed25519.Verify(publicKey, data, signature) {
			return RemotePlanResult{URL: parsed.String(), SHA256: digest, Size: int64(len(data)), DownloadedPath: options.DownloadedPath}, errors.New("remote plan Ed25519 signature verification failed")
		}
		signatureVerified = true
	}
	if err := writeProtected(options.VerifiedPath, data); err != nil {
		return RemotePlanResult{}, err
	}
	methods := make([]string, 0, 2)
	if expected != "" {
		methods = append(methods, "sha256")
	}
	if signatureVerified {
		methods = append(methods, "ed25519")
	}
	return RemotePlanResult{URL: parsed.String(), SHA256: digest, Size: int64(len(data)), DownloadedPath: options.DownloadedPath, VerifiedPath: options.VerifiedPath, Verified: len(methods) > 0, SignatureVerified: signatureVerified, VerificationMethod: strings.Join(methods, "+")}, nil
}

func ParsePlanKernelParameters(commandLine string) map[string]string {
	result := map[string]string{}
	for _, field := range strings.Fields(commandLine) {
		key, value, ok := strings.Cut(field, "=")
		if !ok {
			continue
		}
		switch key {
		case "kiki.plan.url", "kiki.plan.sha256", "kiki.plan.signature":
			result[key] = value
		}
	}
	return result
}

func normalizeDigest(value string) (string, error) {
	value = strings.TrimSpace(strings.TrimPrefix(value, "sha256:"))
	if value == "" {
		return "", nil
	}
	if len(value) != 64 {
		return "", errors.New("remote plan SHA-256 must contain 64 hexadecimal characters")
	}
	decoded, err := hex.DecodeString(value)
	if err != nil || len(decoded) != sha256.Size {
		return "", errors.New("remote plan SHA-256 is invalid")
	}
	return strings.ToLower(value), nil
}

func loadPlanSignature(ctx context.Context, reference string, client *http.Client) ([]byte, error) {
	reference = strings.TrimSpace(reference)
	var data []byte
	var err error
	switch {
	case strings.HasPrefix(reference, "base64:"):
		return decodePlanSignature(strings.TrimPrefix(reference, "base64:"))
	case strings.HasPrefix(reference, "@"):
		data, err = os.ReadFile(strings.TrimPrefix(reference, "@"))
	case strings.HasPrefix(reference, "file://"):
		parsed, parseErr := url.Parse(reference)
		if parseErr != nil || (parsed.Host != "" && parsed.Host != "localhost") || parsed.Path == "" {
			return nil, errors.New("remote plan signature file URL is invalid")
		}
		data, err = os.ReadFile(parsed.Path)
	case strings.HasPrefix(reference, "http://"), strings.HasPrefix(reference, "https://"):
		request, requestErr := http.NewRequestWithContext(ctx, http.MethodGet, reference, nil)
		if requestErr != nil {
			return nil, fmt.Errorf("create remote plan signature request: %w", requestErr)
		}
		request.Header.Set("User-Agent", "kiki-agent-stage3/0.1")
		response, requestErr := client.Do(request)
		if requestErr != nil {
			return nil, fmt.Errorf("download remote plan signature: %w", requestErr)
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("download remote plan signature: HTTP %d", response.StatusCode)
		}
		data, err = io.ReadAll(io.LimitReader(response.Body, defaultRemoteSignatureLimit+1))
		if int64(len(data)) > defaultRemoteSignatureLimit {
			return nil, fmt.Errorf("remote plan signature exceeds %d bytes", defaultRemoteSignatureLimit)
		}
	default:
		return decodePlanSignature(reference)
	}
	if err != nil {
		return nil, fmt.Errorf("read remote plan signature: %w", err)
	}
	return decodePlanSignatureBytes(data)
}

func decodePlanSignatureBytes(data []byte) ([]byte, error) {
	if len(data) == ed25519.SignatureSize {
		return data, nil
	}
	return decodePlanSignature(strings.TrimSpace(string(data)))
}

func decodePlanSignature(value string) ([]byte, error) {
	for _, encoding := range []*base64.Encoding{base64.StdEncoding, base64.RawStdEncoding, base64.URLEncoding, base64.RawURLEncoding} {
		decoded, err := encoding.DecodeString(strings.TrimSpace(value))
		if err == nil && len(decoded) == ed25519.SignatureSize {
			return decoded, nil
		}
	}
	return nil, errors.New("remote plan Ed25519 signature must be 64 raw bytes or base64")
}

func loadEd25519PublicKey(path string) (ed25519.PublicKey, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read remote plan public key: %w", err)
	}
	if block, _ := pem.Decode(data); block != nil {
		parsed, parseErr := x509.ParsePKIXPublicKey(block.Bytes)
		if parseErr != nil {
			return nil, fmt.Errorf("parse remote plan public key: %w", parseErr)
		}
		key, ok := parsed.(ed25519.PublicKey)
		if !ok {
			return nil, errors.New("remote plan public key is not Ed25519")
		}
		return key, nil
	}
	decoded, decodeErr := base64.StdEncoding.DecodeString(strings.TrimSpace(string(data)))
	if decodeErr == nil && len(decoded) == ed25519.PublicKeySize {
		return ed25519.PublicKey(decoded), nil
	}
	if len(data) == ed25519.PublicKeySize {
		return ed25519.PublicKey(data), nil
	}
	return nil, errors.New("remote plan public key must be Ed25519 PEM, 32 raw bytes, or base64")
}

func writeProtected(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create remote plan directory: %w", err)
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".remote-plan-*.tmp")
	if err != nil {
		return fmt.Errorf("create remote plan file: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(data); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return fmt.Errorf("publish remote plan: %w", err)
	}
	return nil
}
