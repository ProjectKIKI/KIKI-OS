package agent

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
	"time"
)

type Reporter struct {
	BaseURL  string
	Token    string
	Actor    string
	NodeName string
	HTTP     *http.Client
	Collect  func() (Inventory, error)
	Interval time.Duration
	OnError  func(error)
}

func (reporter Reporter) Run(ctx context.Context) error {
	if reporter.Collect == nil || reporter.NodeName == "" || reporter.Token == "" {
		return errors.New("reporter collector, node name, and token are required")
	}
	if reporter.Actor == "" {
		reporter.Actor = "kiki-agent/" + reporter.NodeName
	}
	interval := reporter.Interval
	if interval <= 0 {
		interval = 60 * time.Second
	}
	for {
		if err := reporter.Report(ctx); err != nil {
			if ctx.Err() == nil && reporter.OnError != nil {
				reporter.OnError(err)
			}
		} else if err := reporter.ProcessTask(ctx); err != nil && ctx.Err() == nil && reporter.OnError != nil {
			reporter.OnError(err)
		}
		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil
		case <-timer.C:
		}
	}
}

type claimedTask struct{ Task }

func (reporter Reporter) ProcessTask(ctx context.Context) error {
	var claimed claimedTask
	status, err := reporter.requestJSON(ctx, http.MethodPost, "/api/v1/nodes/"+url.PathEscape(reporter.NodeName)+"/tasks/claim", map[string][]TaskAction{"actions": []TaskAction{ActionDiagnosticCollect}}, &claimed)
	if err != nil {
		if status == http.StatusNotFound {
			return nil
		}
		return err
	}
	result := struct {
		State   TaskState       `json:"state"`
		Message string          `json:"message,omitempty"`
		Output  json.RawMessage `json:"output,omitempty"`
	}{State: TaskSucceeded}
	if claimed.Action != ActionDiagnosticCollect {
		result.State = TaskFailed
		result.Message = "agent does not implement claimed action"
	} else {
		inventory, collectErr := reporter.Collect()
		if collectErr != nil {
			result.State = TaskFailed
			result.Message = collectErr.Error()
		} else {
			output, encodeErr := json.Marshal(map[string]any{"scope": "node", "inventory": inventory})
			if encodeErr != nil || len(output) > 64<<10 {
				result.State = TaskFailed
				result.Message = "diagnostic output exceeded safe limit"
			} else {
				result.Output = output
			}
		}
	}
	path := "/api/v1/nodes/" + url.PathEscape(reporter.NodeName) + "/tasks/" + url.PathEscape(claimed.ID) + "/result"
	_, err = reporter.requestJSON(ctx, http.MethodPut, path, result, nil)
	return err
}

func (reporter Reporter) requestJSON(ctx context.Context, method, path string, input, output any) (int, error) {
	base, err := url.Parse(reporter.BaseURL)
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" || base.User != nil {
		return 0, errors.New("InfraOps URL must be an absolute HTTP(S) URL without credentials")
	}
	data, err := json.Marshal(input)
	if err != nil {
		return 0, err
	}
	endpoint := *base
	endpoint.Path = strings.TrimRight(base.Path, "/") + path
	request, err := http.NewRequestWithContext(ctx, method, endpoint.String(), bytes.NewReader(data))
	if err != nil {
		return 0, err
	}
	actor := reporter.Actor
	if actor == "" {
		actor = "kiki-agent/" + reporter.NodeName
	}
	request.Header.Set("Authorization", "Bearer "+reporter.Token)
	request.Header.Set("X-Kiki-Actor", actor)
	request.Header.Set("Content-Type", "application/json")
	client := reporter.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	response, err := client.Do(request)
	if err != nil {
		return 0, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(response.Body, 8192))
		return response.StatusCode, fmt.Errorf("InfraOps %s returned %s: %s", path, response.Status, strings.TrimSpace(string(body)))
	}
	if output == nil {
		_, err = io.Copy(io.Discard, response.Body)
		return response.StatusCode, err
	}
	if err := json.NewDecoder(io.LimitReader(response.Body, 2<<20)).Decode(output); err != nil {
		return response.StatusCode, err
	}
	return response.StatusCode, nil
}

func (reporter Reporter) Report(ctx context.Context) error {
	base, err := url.Parse(reporter.BaseURL)
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" || base.User != nil {
		return errors.New("InfraOps URL must be an absolute HTTP(S) URL without credentials")
	}
	inventory, err := reporter.Collect()
	if err != nil {
		return err
	}
	body, err := json.Marshal(inventory)
	if err != nil {
		return err
	}
	endpoint := *base
	endpoint.Path = strings.TrimRight(base.Path, "/") + "/api/v1/nodes/" + url.PathEscape(reporter.NodeName) + "/inventory"
	request, err := http.NewRequestWithContext(ctx, http.MethodPut, endpoint.String(), bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+reporter.Token)
	actor := reporter.Actor
	if actor == "" {
		actor = "kiki-agent/" + reporter.NodeName
	}
	request.Header.Set("X-Kiki-Actor", actor)
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
		return fmt.Errorf("InfraOps inventory update returned %s: %s", response.Status, strings.TrimSpace(string(data)))
	}
	_, err = io.Copy(io.Discard, response.Body)
	return err
}
