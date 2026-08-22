package controller

import (
	"context"
	"encoding/json"
	"errors"
	"path/filepath"
	"testing"

	"example.com/aos-pkg/internal/agent"
	"example.com/aos-pkg/internal/infraops"
	"example.com/aos-pkg/internal/modelruntime"
)

type fakeDeploymentStore struct {
	deployments  []infraops.ModelDeployment
	statuses     []infraops.DeploymentStatus
	builds       []infraops.Build
	buildReports []infraops.BuildResult
}

func (store *fakeDeploymentStore) ListBuilds() []infraops.Build { return store.builds }
func (store *fakeDeploymentStore) ReportBuild(_ string, _ string, result infraops.BuildResult) (infraops.Build, error) {
	store.buildReports = append(store.buildReports, result)
	return infraops.Build{Phase: result.Phase}, nil
}

type fakeResources struct {
	models      []ModelResource
	deployments []ModelDeploymentResource
	statuses    []map[string]any
}

func (source fakeResources) ListModels(context.Context, string) ([]ModelResource, error) {
	return source.models, nil
}
func (source fakeResources) ListModelDeployments(context.Context, string) ([]ModelDeploymentResource, error) {
	return source.deployments, nil
}
func (source *fakeResources) UpdateModelDeploymentStatus(_ context.Context, _, _ string, status map[string]any) error {
	source.statuses = append(source.statuses, status)
	return nil
}

func (store *fakeDeploymentStore) CreateModel(_ string, model infraops.Model) (infraops.Model, error) {
	return model, nil
}
func (store *fakeDeploymentStore) CreateDeployment(_ string, request infraops.DeploymentRequest) (infraops.ModelDeployment, error) {
	return infraops.ModelDeployment{DeploymentRequest: request}, nil
}

func (store *fakeDeploymentStore) ListDeployments() []infraops.ModelDeployment {
	return store.deployments
}

func (store *fakeDeploymentStore) UpdateDeploymentStatus(_ string, _, _ string, status infraops.DeploymentStatus) (infraops.ModelDeployment, error) {
	store.statuses = append(store.statuses, status)
	return infraops.ModelDeployment{}, nil
}

type fakePodClient struct {
	observation PodObservation
	err         error
}

type fakeBuildClient struct{ applied int }

func (client *fakeBuildClient) ApplyBuild(context.Context, map[string]any, map[string]any) error {
	client.applied++
	return nil
}

func (client fakePodClient) ApplyPod(context.Context, map[string]any) (PodObservation, error) {
	return client.observation, client.err
}

func TestReconcileAppliesReadyModelPodAndRecordsObservation(t *testing.T) {
	store := &fakeDeploymentStore{deployments: []infraops.ModelDeployment{{DeploymentRequest: infraops.DeploymentRequest{Name: "model", Namespace: "project"}, Plan: modelruntime.Plan{Phase: "Ready"}, PodTemplate: map[string]any{"kind": "Pod"}}}}
	reconciler := Reconciler{Store: store, Pods: fakePodClient{observation: PodObservation{Phase: "Running", PodIP: "10.0.0.8"}}, Actor: "controller"}
	if err := reconciler.Reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(store.statuses) != 1 || store.statuses[0].Phase != "Ready" || store.statuses[0].PodIP != "10.0.0.8" {
		t.Fatalf("unexpected status: %#v", store.statuses)
	}
}

func TestReconcileRecordsApplyFailure(t *testing.T) {
	store := &fakeDeploymentStore{deployments: []infraops.ModelDeployment{{DeploymentRequest: infraops.DeploymentRequest{Name: "model", Namespace: "project"}, Plan: modelruntime.Plan{Phase: "Ready"}, PodTemplate: map[string]any{"kind": "Pod"}}}}
	err := Reconciler{Store: store, Pods: fakePodClient{err: errors.New("denied")}}.Reconcile(context.Background())
	if err == nil || len(store.statuses) != 1 || store.statuses[0].Phase != "Failed" {
		t.Fatalf("failure was not observed: err=%v statuses=%#v", err, store.statuses)
	}
}

func TestCRDResourcesSynchronizeThroughPodReconciliation(t *testing.T) {
	const image = "registry.local/runtime@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	store, err := infraops.NewStore(filepath.Join(t.TempDir(), "state.json"), infraops.RuntimeImages{Llama: image, VLLM: image, Fetcher: image})
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.UpsertNode("node-01", "agent", agent.Inventory{SchemaVersion: "kiki.io/inventory/v1alpha1", Hostname: "node-01", Memory: agent.Memory{TotalBytes: 16 << 30, AvailableBytes: 12 << 30}, CPU: agent.CPUInventory{Architecture: "amd64", LogicalCores: 8}})
	if err != nil {
		t.Fatal(err)
	}
	var model ModelResource
	if err := json.Unmarshal([]byte(`{"metadata":{"name":"ops","namespace":"kiki-models"},"spec":{"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","format":"gguf","source":"oci://registry.local/models/ops","sizeBytes":1024,"minimumMemoryBytes":1024,"license":{"id":"apache-2.0","accepted":true}}}`), &model); err != nil {
		t.Fatal(err)
	}
	var deployment ModelDeploymentResource
	if err := json.Unmarshal([]byte(`{"metadata":{"name":"ops","namespace":"kiki-models"},"spec":{"modelRef":{"name":"ops"},"placement":{"runtime":"auto","accelerator":"auto"},"endpoint":{"port":8000,"contextLength":4096},"cache":{"persistentVolumeClaim":"model-cache","modelPath":"/models/ops/model.gguf"},"resources":{"cpu":"2","memory":"4Gi"}}}`), &deployment); err != nil {
		t.Fatal(err)
	}
	resources := &fakeResources{models: []ModelResource{model}, deployments: []ModelDeploymentResource{deployment}}
	reconciler := Reconciler{Store: store, Pods: fakePodClient{observation: PodObservation{Phase: "Running", PodIP: "10.2.0.5"}}, Resources: resources, Namespace: "kiki-models", Actor: "controller"}
	if err := reconciler.Reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	items := store.ListDeployments()
	if len(items) != 1 || items[0].NodeName != "node-01" || items[0].Status.Phase != "Ready" || items[0].PodTemplate["kind"] != "Pod" {
		t.Fatalf("CRD did not converge: %#v", items)
	}
	if len(resources.statuses) != 1 || resources.statuses[0]["phase"] != "Ready" || resources.statuses[0]["endpoint"] != "http://10.2.0.5:8000" {
		t.Fatalf("CRD status was not updated: %#v", resources.statuses)
	}
}

func TestQueuedBuildIsAppliedBeforeFetchingTransition(t *testing.T) {
	store := &fakeDeploymentStore{builds: []infraops.Build{{BuildRequest: infraops.BuildRequest{ID: "build-0001"}, Phase: "Queued", Job: map[string]any{"kind": "Job"}, NetworkPolicy: map[string]any{"kind": "NetworkPolicy"}}}}
	builds := &fakeBuildClient{}
	reconciler := Reconciler{Store: store, Pods: fakePodClient{}, Builds: builds, Actor: "controller"}
	if err := reconciler.Reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if builds.applied != 1 || len(store.buildReports) != 1 || store.buildReports[0].Phase != "Fetching" {
		t.Fatalf("build did not transition after apply: %#v %#v", builds, store.buildReports)
	}
}
