package imagefactory

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

type Client struct {
	BaseURL        string
	Token          string
	Actor          string
	HTTP           *http.Client
	SupportedTypes []string
}

type ClaimedBuild struct {
	ID          string `json:"id"`
	Phase       string `json:"phase"`
	FactoryTask *Task  `json:"factory_task"`
}

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

func (client Client) Claim(ctx context.Context) (ClaimedBuild, error) {
	var claimed ClaimedBuild
	types := client.SupportedTypes
	if len(types) == 0 {
		types = []string{"iso"}
	}
	if err := client.call(ctx, http.MethodPost, "/api/v1/image-factory/claim", map[string][]string{"types": types}, &claimed); err != nil {
		return ClaimedBuild{}, err
	}
	if claimed.ID == "" || claimed.Phase != "Fetching" || claimed.FactoryTask == nil || claimed.FactoryTask.Request.BuildID != claimed.ID {
		return ClaimedBuild{}, errors.New("InfraOps returned an invalid Image Factory claim")
	}
	return claimed, nil
}

func (client Client) Report(ctx context.Context, buildID, phase, message string) error {
	return client.ReportResult(ctx, buildID, BuildReport{Phase: phase, Message: message})
}

func (client Client) ReportResult(ctx context.Context, buildID string, report BuildReport) error {
	if buildID == "" {
		return errors.New("build ID is required")
	}
	return client.call(ctx, http.MethodPut, "/api/v1/builds/"+url.PathEscape(buildID)+"/result", report, nil)
}

func (client Client) call(ctx context.Context, method, path string, input, output any) error {
	base, err := url.Parse(client.BaseURL)
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" || base.User != nil {
		return errors.New("InfraOps URL must be an absolute HTTP(S) URL without credentials")
	}
	if strings.TrimSpace(client.Token) == "" || strings.TrimSpace(client.Actor) == "" {
		return errors.New("InfraOps token and worker actor are required")
	}
	body, err := json.Marshal(input)
	if err != nil {
		return err
	}
	endpoint := *base
	endpoint.Path = strings.TrimRight(base.Path, "/") + path
	request, err := http.NewRequestWithContext(ctx, method, endpoint.String(), bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+client.Token)
	request.Header.Set("X-Kiki-Actor", client.Actor)
	request.Header.Set("Content-Type", "application/json")
	httpClient := client.HTTP
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	response, err := httpClient.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		data, _ := io.ReadAll(io.LimitReader(response.Body, 8192))
		return fmt.Errorf("InfraOps %s %s returned %s: %s", method, path, response.Status, strings.TrimSpace(string(data)))
	}
	if output == nil {
		_, err = io.Copy(io.Discard, response.Body)
		return err
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, 2<<20))
	if err := decoder.Decode(output); err != nil {
		return fmt.Errorf("decode InfraOps response: %w", err)
	}
	return nil
}
