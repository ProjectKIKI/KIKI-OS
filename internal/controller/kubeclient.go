package controller

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type KubernetesClient struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

func NewInClusterClient() (*KubernetesClient, error) {
	host := os.Getenv("KUBERNETES_SERVICE_HOST")
	port := os.Getenv("KUBERNETES_SERVICE_PORT_HTTPS")
	if host == "" || port == "" {
		return nil, errors.New("Kubernetes service environment is unavailable")
	}
	token, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/token")
	if err != nil {
		return nil, fmt.Errorf("read service-account token: %w", err)
	}
	caData, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
	if err != nil {
		return nil, fmt.Errorf("read Kubernetes CA: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caData) {
		return nil, errors.New("Kubernetes CA contains no certificate")
	}
	transport := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: pool}}
	return &KubernetesClient{BaseURL: "https://" + host + ":" + port, Token: strings.TrimSpace(string(token)), HTTP: &http.Client{Transport: transport, Timeout: 30 * time.Second}}, nil
}

func (client *KubernetesClient) ApplyPod(ctx context.Context, pod map[string]any) (PodObservation, error) {
	metadata, ok := pod["metadata"].(map[string]any)
	if !ok {
		return PodObservation{}, errors.New("Pod metadata is missing")
	}
	name, _ := metadata["name"].(string)
	namespace, _ := metadata["namespace"].(string)
	if name == "" || namespace == "" {
		return PodObservation{}, errors.New("Pod name and namespace are required")
	}
	data, err := json.Marshal(pod)
	if err != nil {
		return PodObservation{}, err
	}
	path := "/api/v1/namespaces/" + url.PathEscape(namespace) + "/pods/" + url.PathEscape(name) + "?fieldManager=kiki-controller&force=true"
	request, err := http.NewRequestWithContext(ctx, http.MethodPatch, client.BaseURL+path, bytes.NewReader(data))
	if err != nil {
		return PodObservation{}, err
	}
	request.Header.Set("Authorization", "Bearer "+client.Token)
	request.Header.Set("Content-Type", "application/apply-patch+yaml")
	response, err := client.HTTP.Do(request)
	if err != nil {
		return PodObservation{}, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 2<<20))
	if err != nil {
		return PodObservation{}, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return PodObservation{}, fmt.Errorf("Kubernetes apply Pod returned %s: %s", response.Status, strings.TrimSpace(string(body)))
	}
	var applied struct {
		Status struct {
			Phase   string `json:"phase"`
			PodIP   string `json:"podIP"`
			Message string `json:"message"`
		} `json:"status"`
	}
	if err := json.Unmarshal(body, &applied); err != nil {
		return PodObservation{}, fmt.Errorf("decode applied Pod: %w", err)
	}
	return PodObservation{Phase: applied.Status.Phase, PodIP: applied.Status.PodIP, Message: applied.Status.Message}, nil
}

func (client *KubernetesClient) ListModels(ctx context.Context, namespace string) ([]ModelResource, error) {
	var list struct {
		Items []ModelResource `json:"items"`
	}
	path := "/apis/kiki.io/v1alpha1/namespaces/" + url.PathEscape(namespace) + "/kikimodels"
	if err := client.getJSON(ctx, path, &list); err != nil {
		return nil, err
	}
	return list.Items, nil
}

func (client *KubernetesClient) ListModelDeployments(ctx context.Context, namespace string) ([]ModelDeploymentResource, error) {
	var list struct {
		Items []ModelDeploymentResource `json:"items"`
	}
	path := "/apis/kiki.io/v1alpha1/namespaces/" + url.PathEscape(namespace) + "/kikimodeldeployments"
	if err := client.getJSON(ctx, path, &list); err != nil {
		return nil, err
	}
	return list.Items, nil
}

func (client *KubernetesClient) getJSON(ctx context.Context, path string, output any) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, client.BaseURL+path, nil)
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+client.Token)
	response, err := client.HTTP.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 4<<20))
	if err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("Kubernetes GET %s returned %s: %s", path, response.Status, strings.TrimSpace(string(body)))
	}
	if err := json.Unmarshal(body, output); err != nil {
		return fmt.Errorf("decode Kubernetes GET %s: %w", path, err)
	}
	return nil
}

func (client *KubernetesClient) UpdateModelDeploymentStatus(ctx context.Context, namespace, name string, status map[string]any) error {
	data, err := json.Marshal(map[string]any{"status": status})
	if err != nil {
		return err
	}
	path := "/apis/kiki.io/v1alpha1/namespaces/" + url.PathEscape(namespace) + "/kikimodeldeployments/" + url.PathEscape(name) + "/status"
	request, err := http.NewRequestWithContext(ctx, http.MethodPatch, client.BaseURL+path, bytes.NewReader(data))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+client.Token)
	request.Header.Set("Content-Type", "application/merge-patch+json")
	response, err := client.HTTP.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 2<<20))
	if err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("Kubernetes update ModelDeployment status returned %s: %s", response.Status, strings.TrimSpace(string(body)))
	}
	return nil
}

func (client *KubernetesClient) ApplyBuild(ctx context.Context, policy, job map[string]any) error {
	if err := client.applyObject(ctx, policy, "networking.k8s.io", "v1", "networkpolicies"); err != nil {
		return err
	}
	return client.applyObject(ctx, job, "batch", "v1", "jobs")
}

func (client *KubernetesClient) applyObject(ctx context.Context, object map[string]any, group, version, resource string) error {
	metadata, ok := object["metadata"].(map[string]any)
	if !ok {
		return errors.New("Kubernetes object metadata is missing")
	}
	name, _ := metadata["name"].(string)
	namespace, _ := metadata["namespace"].(string)
	if name == "" || namespace == "" {
		return errors.New("Kubernetes object name and namespace are required")
	}
	data, err := json.Marshal(object)
	if err != nil {
		return err
	}
	path := "/apis/" + group + "/" + version + "/namespaces/" + url.PathEscape(namespace) + "/" + resource + "/" + url.PathEscape(name) + "?fieldManager=kiki-controller&force=true"
	request, err := http.NewRequestWithContext(ctx, http.MethodPatch, client.BaseURL+path, bytes.NewReader(data))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+client.Token)
	request.Header.Set("Content-Type", "application/apply-patch+yaml")
	response, err := client.HTTP.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 2<<20))
	if err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("Kubernetes apply %s returned %s: %s", resource, response.Status, strings.TrimSpace(string(body)))
	}
	return nil
}
