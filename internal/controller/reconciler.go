package controller

import (
	"context"
	"errors"
	"fmt"
	"time"

	"example.com/aos-pkg/internal/infraops"
)

type PodObservation struct {
	Phase   string
	PodIP   string
	Message string
}

type PodClient interface {
	ApplyPod(context.Context, map[string]any) (PodObservation, error)
}

type DeploymentStore interface {
	ListDeployments() []infraops.ModelDeployment
	CreateModel(string, infraops.Model) (infraops.Model, error)
	CreateDeployment(string, infraops.DeploymentRequest) (infraops.ModelDeployment, error)
	UpdateDeploymentStatus(string, string, string, infraops.DeploymentStatus) (infraops.ModelDeployment, error)
	ListBuilds() []infraops.Build
	ReportBuild(string, string, infraops.BuildResult) (infraops.Build, error)
}

type ResourceSource interface {
	ListModels(context.Context, string) ([]ModelResource, error)
	ListModelDeployments(context.Context, string) ([]ModelDeploymentResource, error)
	UpdateModelDeploymentStatus(context.Context, string, string, map[string]any) error
}

type BuildClient interface {
	ApplyBuild(context.Context, map[string]any, map[string]any) error
}

type Reconciler struct {
	Store     DeploymentStore
	Pods      PodClient
	Actor     string
	Interval  time.Duration
	OnError   func(error)
	Resources ResourceSource
	Namespace string
	Builds    BuildClient
}

func (reconciler Reconciler) Run(ctx context.Context) error {
	if reconciler.Store == nil || reconciler.Pods == nil {
		return errors.New("controller store and Pod client are required")
	}
	interval := reconciler.Interval
	if interval <= 0 {
		interval = 15 * time.Second
	}
	if reconciler.Actor == "" {
		reconciler.Actor = "kiki-controller"
	}
	for {
		if err := reconciler.Reconcile(ctx); err != nil && ctx.Err() == nil && reconciler.OnError != nil {
			reconciler.OnError(err)
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

func (reconciler Reconciler) Reconcile(ctx context.Context) error {
	var joined error
	if reconciler.Resources != nil {
		namespace := reconciler.Namespace
		if namespace == "" {
			namespace = "kiki-models"
		}
		if err := reconciler.syncResources(ctx, namespace); err != nil {
			joined = errors.Join(joined, err)
		}
	}
	if reconciler.Builds != nil {
		for _, build := range reconciler.Store.ListBuilds() {
			if build.Phase != "Queued" || build.Job == nil || build.NetworkPolicy == nil {
				continue
			}
			if err := reconciler.Builds.ApplyBuild(ctx, build.NetworkPolicy, build.Job); err != nil {
				joined = errors.Join(joined, fmt.Errorf("apply build %s: %w", build.ID, err))
				continue
			}
			if _, err := reconciler.Store.ReportBuild(reconciler.Actor, build.ID, infraops.BuildResult{Phase: "Fetching"}); err != nil {
				joined = errors.Join(joined, err)
			}
		}
	}
	for _, deployment := range reconciler.Store.ListDeployments() {
		if deployment.Plan.Phase != "Ready" || deployment.PodTemplate == nil {
			if reconciler.Resources != nil && deployment.Namespace == defaultNamespace(reconciler.Namespace) {
				status := map[string]any{"phase": deployment.Plan.Phase, "engine": deployment.Plan.Engine, "backend": deployment.Plan.Backend, "nodeName": deployment.NodeName, "conditions": deployment.Plan.Conditions}
				if statusErr := reconciler.Resources.UpdateModelDeploymentStatus(ctx, deployment.Namespace, deployment.Name, status); statusErr != nil {
					joined = errors.Join(joined, statusErr)
				}
			}
			continue
		}
		observation, err := reconciler.Pods.ApplyPod(ctx, deployment.PodTemplate)
		status := infraops.DeploymentStatus{Phase: runtimePhase(observation.Phase), PodPhase: observation.Phase, PodIP: observation.PodIP, Message: observation.Message}
		if err != nil {
			status = infraops.DeploymentStatus{Phase: "Failed", Message: err.Error()}
		}
		updated, updateErr := reconciler.Store.UpdateDeploymentStatus(reconciler.Actor, deployment.Namespace, deployment.Name, status)
		if updateErr != nil {
			err = errors.Join(err, updateErr)
		} else if reconciler.Resources != nil && deployment.Namespace == defaultNamespace(reconciler.Namespace) {
			resourceStatus := map[string]any{"phase": updated.Status.Phase, "engine": updated.Plan.Engine, "backend": updated.Plan.Backend, "nodeName": updated.NodeName}
			if updated.Status.PodIP != "" {
				resourceStatus["endpoint"] = fmt.Sprintf("http://%s:%d", updated.Status.PodIP, updated.Port)
			}
			if statusErr := reconciler.Resources.UpdateModelDeploymentStatus(ctx, deployment.Namespace, deployment.Name, resourceStatus); statusErr != nil {
				err = errors.Join(err, statusErr)
			}
		}
		if err != nil {
			joined = errors.Join(joined, fmt.Errorf("reconcile %s/%s: %w", deployment.Namespace, deployment.Name, err))
		}
	}
	return joined
}

func defaultNamespace(value string) string {
	if value == "" {
		return "kiki-models"
	}
	return value
}

func (reconciler Reconciler) syncResources(ctx context.Context, namespace string) error {
	models, err := reconciler.Resources.ListModels(ctx, namespace)
	if err != nil {
		return fmt.Errorf("list KikiModels: %w", err)
	}
	for _, resource := range models {
		_, createErr := reconciler.Store.CreateModel(reconciler.Actor, resource.InfraOpsModel())
		if createErr != nil {
			err = errors.Join(err, fmt.Errorf("sync KikiModel %s: %w", resource.Name(), createErr))
		}
	}
	existing := map[string]bool{}
	for _, deployment := range reconciler.Store.ListDeployments() {
		existing[deployment.Namespace+"/"+deployment.Name] = true
	}
	deployments, listErr := reconciler.Resources.ListModelDeployments(ctx, namespace)
	if listErr != nil {
		return errors.Join(err, fmt.Errorf("list KikiModelDeployments: %w", listErr))
	}
	for _, resource := range deployments {
		if existing[resource.Namespace()+"/"+resource.Name()] {
			continue
		}
		_, createErr := reconciler.Store.CreateDeployment(reconciler.Actor, resource.InfraOpsRequest())
		if createErr != nil {
			err = errors.Join(err, fmt.Errorf("sync KikiModelDeployment %s: %w", resource.Name(), createErr))
		}
	}
	return err
}

func runtimePhase(podPhase string) string {
	switch podPhase {
	case "Running":
		return "Ready"
	case "Failed":
		return "Failed"
	case "Succeeded":
		return "Stopped"
	default:
		return "Starting"
	}
}
