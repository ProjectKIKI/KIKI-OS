package controller

import (
	"example.com/aos-pkg/internal/infraops"
	"example.com/aos-pkg/internal/modelruntime"
)

type ObjectMeta struct {
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
}

type ModelResource struct {
	Metadata ObjectMeta `json:"metadata"`
	Spec     struct {
		Digest             string `json:"digest"`
		Format             string `json:"format"`
		Source             string `json:"source"`
		SizeBytes          uint64 `json:"sizeBytes"`
		MinimumMemoryBytes uint64 `json:"minimumMemoryBytes"`
		MinimumVRAMBytes   uint64 `json:"minimumVRAMBytes"`
		License            struct {
			ID       string `json:"id"`
			Accepted bool   `json:"accepted"`
		} `json:"license"`
	} `json:"spec"`
}

func (resource ModelResource) Name() string { return resource.Metadata.Name }

func (resource ModelResource) InfraOpsModel() infraops.Model {
	return infraops.Model{Name: resource.Metadata.Name, Digest: resource.Spec.Digest, Format: resource.Spec.Format, Source: resource.Spec.Source, SizeBytes: resource.Spec.SizeBytes, MinimumMemoryBytes: resource.Spec.MinimumMemoryBytes, MinimumVRAMBytes: resource.Spec.MinimumVRAMBytes, LicenseID: resource.Spec.License.ID, LicenseAccepted: resource.Spec.License.Accepted}
}

type ModelDeploymentResource struct {
	Metadata ObjectMeta `json:"metadata"`
	Spec     struct {
		ModelRef struct {
			Name string `json:"name"`
		} `json:"modelRef"`
		Placement struct {
			Runtime     string `json:"runtime"`
			Accelerator string `json:"accelerator"`
			NodeName    string `json:"nodeName"`
		} `json:"placement"`
		Endpoint struct {
			Port          int `json:"port"`
			ContextLength int `json:"contextLength"`
		} `json:"endpoint"`
		Cache struct {
			PersistentVolumeClaim string `json:"persistentVolumeClaim"`
			ModelPath             string `json:"modelPath"`
		} `json:"cache"`
		Resources struct {
			CPU    string `json:"cpu"`
			Memory string `json:"memory"`
		} `json:"resources"`
	} `json:"spec"`
}

func (resource ModelDeploymentResource) Name() string      { return resource.Metadata.Name }
func (resource ModelDeploymentResource) Namespace() string { return resource.Metadata.Namespace }

func (resource ModelDeploymentResource) InfraOpsRequest() infraops.DeploymentRequest {
	modelPath := resource.Spec.Cache.ModelPath
	if modelPath == "" {
		modelPath = "/models/" + resource.Spec.ModelRef.Name
	}
	return infraops.DeploymentRequest{Name: resource.Metadata.Name, Namespace: resource.Metadata.Namespace, ModelName: resource.Spec.ModelRef.Name, NodeName: resource.Spec.Placement.NodeName, Placement: modelruntime.Placement{Runtime: resource.Spec.Placement.Runtime, Accelerator: resource.Spec.Placement.Accelerator}, ModelPath: modelPath, CachePVC: resource.Spec.Cache.PersistentVolumeClaim, Port: resource.Spec.Endpoint.Port, ContextLength: resource.Spec.Endpoint.ContextLength, CPU: resource.Spec.Resources.CPU, Memory: resource.Spec.Resources.Memory}
}
