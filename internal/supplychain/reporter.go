package supplychain

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

type BuildReport struct {
	Phase            string `json:"phase"`
	Digest           string `json:"digest,omitempty"`
	SizeBytes        uint64 `json:"size_bytes,omitempty"`
	MediaType        string `json:"media_type,omitempty"`
	SBOMDigest       string `json:"sbom_digest,omitempty"`
	ScanDigest       string `json:"scan_digest,omitempty"`
	ProvenanceDigest string `json:"provenance_digest,omitempty"`
	SignatureDigest  string `json:"signature_digest,omitempty"`
	Message          string `json:"message,omitempty"`
}

type Reporter struct {
	BaseURL string
	Token   string
	Actor   string
	HTTP    *http.Client
}

func (reporter Reporter) Report(ctx context.Context, buildID string, report BuildReport) error {
	base, err := url.Parse(reporter.BaseURL)
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" || base.User != nil {
		return errors.New("InfraOps URL must be an absolute HTTP(S) URL without credentials")
	}
	if reporter.Token == "" || reporter.Actor == "" || buildID == "" {
		return errors.New("reporter token, actor, and build ID are required")
	}
	body, err := json.Marshal(report)
	if err != nil {
		return err
	}
	endpoint := *base
	endpoint.Path = strings.TrimRight(base.Path, "/") + "/api/v1/builds/" + url.PathEscape(buildID) + "/result"
	request, err := http.NewRequestWithContext(ctx, http.MethodPut, endpoint.String(), bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+reporter.Token)
	request.Header.Set("X-Kiki-Actor", reporter.Actor)
	request.Header.Set("Content-Type", "application/json")
	client := reporter.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		data, _ := io.ReadAll(io.LimitReader(response.Body, 8192))
		return fmt.Errorf("InfraOps build report returned %s: %s", response.Status, strings.TrimSpace(string(data)))
	}
	_, err = io.Copy(io.Discard, response.Body)
	return err
}

func (reporter Reporter) Advance(ctx context.Context, buildID string, phases ...string) error {
	for _, phase := range phases {
		if err := reporter.Report(ctx, buildID, BuildReport{Phase: phase}); err != nil {
			return err
		}
	}
	return nil
}
