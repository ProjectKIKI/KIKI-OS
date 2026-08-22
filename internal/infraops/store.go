package infraops

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"example.com/aos-pkg/internal/agent"
	"example.com/aos-pkg/internal/buildsystem"
	"example.com/aos-pkg/internal/imagefactory"
	"example.com/aos-pkg/internal/modelruntime"
)

var resourceNamePattern = regexp.MustCompile(`^[a-z0-9]([-a-z0-9.]{0,61}[a-z0-9])?$`)
var sha256Pattern = regexp.MustCompile(`^sha256:[a-f0-9]{64}$`)

type Store struct {
	mu     sync.RWMutex
	path   string
	now    func() time.Time
	images RuntimeImages
	build  buildsystem.Config
	data   stateFile
}

func NewStore(path string, images RuntimeImages, buildConfig ...buildsystem.Config) (*Store, error) {
	store := &Store{path: path, now: time.Now, images: images}
	if len(buildConfig) > 0 {
		store.build = buildConfig[0]
	}
	store.data = stateFile{NextAuditID: 1, Nodes: map[string]Node{}, Models: map[string]Model{}, Deployments: map[string]ModelDeployment{}, Builds: map[string]Build{}, Artifacts: map[string]Artifact{}, Tasks: map[string]ManagedTask{}, Audit: []AuditEvent{}}
	data, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(data, &store.data); err != nil {
			return nil, fmt.Errorf("parse InfraOps state: %w", err)
		}
		store.normalize()
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("read InfraOps state: %w", err)
	}
	return store, nil
}

func (s *Store) normalize() {
	if s.data.NextAuditID < 1 {
		s.data.NextAuditID = 1
	}
	if s.data.Nodes == nil {
		s.data.Nodes = map[string]Node{}
	}
	if s.data.Models == nil {
		s.data.Models = map[string]Model{}
	}
	if s.data.Deployments == nil {
		s.data.Deployments = map[string]ModelDeployment{}
	}
	if s.data.Builds == nil {
		s.data.Builds = map[string]Build{}
	}
	if s.data.Artifacts == nil {
		s.data.Artifacts = map[string]Artifact{}
	}
	if s.data.Audit == nil {
		s.data.Audit = []AuditEvent{}
	}
	if s.data.Tasks == nil {
		s.data.Tasks = map[string]ManagedTask{}
	}
}

func (s *Store) CreateTask(actor string, request TaskRequest) (ManagedTask, error) {
	now := s.now().UTC()
	task := agent.Task{APIVersion: "infraops.kiki.io/v1alpha1", ID: request.ID, IdempotencyKey: request.IdempotencyKey, Action: request.Action, TargetNode: request.TargetNode, Parameters: request.Parameters, Approval: request.Approval, CreatedBy: actor, CreatedAt: now, ExpiresAt: request.ExpiresAt, State: agent.TaskPending}
	if err := task.Validate(now); err != nil {
		return ManagedTask{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, existing := range s.data.Tasks {
		if existing.IdempotencyKey == task.IdempotencyKey {
			if existing.CreatedBy == task.CreatedBy && existing.Action == task.Action && existing.TargetNode == task.TargetNode && string(existing.Parameters) == string(task.Parameters) {
				return existing, nil
			}
			return ManagedTask{}, errors.New("idempotency key is already used by another task request")
		}
	}
	if _, exists := s.data.Tasks[task.ID]; exists {
		return ManagedTask{}, errors.New("task ID already exists")
	}
	managed := ManagedTask{Task: task, Approvals: []TaskApproval{}, UpdatedAt: now}
	s.data.Tasks[task.ID] = managed
	s.auditLocked(actor, "task.create", "Task", task.ID, map[string]any{"action": task.Action, "targetNode": task.TargetNode, "approval": task.Approval})
	return managed, s.saveLocked()
}

func (s *Store) ApproveTask(actor, id string) (ManagedTask, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	task, ok := s.data.Tasks[id]
	if !ok {
		return ManagedTask{}, errors.New("task not found")
	}
	if task.State != agent.TaskPending {
		return ManagedTask{}, errors.New("only Pending tasks can be approved")
	}
	if !s.now().Before(task.ExpiresAt) {
		return ManagedTask{}, errors.New("task is expired")
	}
	if actor == task.CreatedBy {
		return ManagedTask{}, errors.New("task creator cannot approve the same task")
	}
	for _, approval := range task.Approvals {
		if approval.Actor == actor {
			return ManagedTask{}, errors.New("actor already approved task")
		}
	}
	task.Approvals = append(task.Approvals, TaskApproval{Actor: actor, CreatedAt: s.now().UTC()})
	task.UpdatedAt = s.now().UTC()
	s.data.Tasks[id] = task
	s.auditLocked(actor, "task.approve", "Task", id, map[string]int{"approvalCount": len(task.Approvals)})
	return task, s.saveLocked()
}

func (s *Store) ClaimNodeTask(actor, node string, supportedActions []agent.TaskAction) (ManagedTask, error) {
	supported := make(map[agent.TaskAction]bool, len(supportedActions))
	for _, action := range supportedActions {
		supported[action] = true
	}
	if len(supported) == 0 {
		return ManagedTask{}, errors.New("at least one task action capability is required")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now().UTC()
	var selected *ManagedTask
	dirty := false
	for id, candidate := range s.data.Tasks {
		if candidate.State == agent.TaskPending && !now.Before(candidate.ExpiresAt) {
			candidate.State = agent.TaskExpired
			candidate.UpdatedAt = now
			s.data.Tasks[id] = candidate
			s.auditLocked("system", "task.expire", "Task", id, nil)
			dirty = true
			continue
		}
		if candidate.State != agent.TaskPending || candidate.TargetNode != node || !supported[candidate.Action] || len(candidate.Approvals) < requiredApprovals(candidate.Approval) {
			continue
		}
		if selected == nil || candidate.CreatedAt.Before(selected.CreatedAt) || (candidate.CreatedAt.Equal(selected.CreatedAt) && candidate.ID < selected.ID) {
			copy := candidate
			selected = &copy
		}
	}
	if selected == nil {
		if dirty {
			if err := s.saveLocked(); err != nil {
				return ManagedTask{}, err
			}
		}
		return ManagedTask{}, errors.New("no claimable task")
	}
	selected.State = agent.TaskRunning
	selected.ClaimedBy = node
	selected.UpdatedAt = now
	s.data.Tasks[selected.ID] = *selected
	s.auditLocked(actor, "task.claim", "Task", selected.ID, map[string]string{"node": node})
	return *selected, s.saveLocked()
}

func (s *Store) CompleteNodeTask(actor, node, id string, result TaskResult) (ManagedTask, error) {
	if len(result.Output) > 64<<10 || len(result.Message) > 4096 {
		return ManagedTask{}, errors.New("task result exceeds output limit")
	}
	if result.State != agent.TaskSucceeded && result.State != agent.TaskFailed && result.State != agent.TaskCancelled {
		return ManagedTask{}, errors.New("task result state must be terminal")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	task, ok := s.data.Tasks[id]
	if !ok {
		return ManagedTask{}, errors.New("task not found")
	}
	if task.TargetNode != node || task.ClaimedBy != node || !agent.CanTransitionTask(task.State, result.State) {
		return ManagedTask{}, errors.New("task is not running on the reporting node")
	}
	task.State = result.State
	task.Result = &result
	task.UpdatedAt = s.now().UTC()
	s.data.Tasks[id] = task
	s.auditLocked(actor, "task.complete", "Task", id, map[string]any{"node": node, "state": result.State, "message": result.Message})
	return task, s.saveLocked()
}

func (s *Store) ListTasks() []ManagedTask {
	s.mu.RLock()
	defer s.mu.RUnlock()
	items := make([]ManagedTask, 0, len(s.data.Tasks))
	for _, task := range s.data.Tasks {
		items = append(items, task)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].CreatedAt.Before(items[j].CreatedAt) })
	return items
}

func requiredApprovals(class agent.ApprovalClass) int {
	switch class {
	case agent.ApprovalOperator:
		return 1
	case agent.ApprovalTwoParty:
		return 2
	default:
		return 0
	}
}

func (s *Store) UpsertNode(name, actor string, inventory agent.Inventory) (Node, error) {
	if !resourceNamePattern.MatchString(name) || inventory.SchemaVersion != "kiki.io/inventory/v1alpha1" {
		return Node{}, errors.New("invalid node name or inventory schema")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	node := Node{Name: name, Inventory: inventory, UpdatedAt: s.now().UTC()}
	s.data.Nodes[name] = node
	s.auditLocked(actor, "node.inventory.update", "Node", name, nil)
	return node, s.saveLocked()
}

func (s *Store) CreateModel(actor string, model Model) (Model, error) {
	if !resourceNamePattern.MatchString(model.Name) || !sha256Pattern.MatchString(model.Digest) || !strings.HasPrefix(model.Source, "oci://") {
		return Model{}, errors.New("invalid model identity, digest, or source")
	}
	if model.Format != "gguf" && model.Format != "safetensors" {
		return Model{}, errors.New("model format must be gguf or safetensors")
	}
	if model.SizeBytes == 0 || model.MinimumMemoryBytes == 0 || model.LicenseID == "" || !model.LicenseAccepted {
		return Model{}, errors.New("model size, memory, and accepted license are required")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if existing, ok := s.data.Models[model.Name]; ok {
		if existing.Digest == model.Digest {
			return existing, nil
		}
		return Model{}, errors.New("model name is immutable and already references another digest")
	}
	model.CreatedAt = s.now().UTC()
	s.data.Models[model.Name] = model
	s.auditLocked(actor, "model.create", "Model", model.Name, map[string]string{"digest": model.Digest})
	return model, s.saveLocked()
}

func (s *Store) CreateDeployment(actor string, request DeploymentRequest) (ModelDeployment, error) {
	if !resourceNamePattern.MatchString(request.Name) || !resourceNamePattern.MatchString(request.Namespace) || (request.NodeName != "" && !resourceNamePattern.MatchString(request.NodeName)) {
		return ModelDeployment{}, errors.New("invalid deployment, namespace, or node name")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.data.Deployments[request.Namespace+"/"+request.Name]; exists {
		return ModelDeployment{}, errors.New("deployment already exists")
	}
	model, ok := s.data.Models[request.ModelName]
	if !ok {
		return ModelDeployment{}, errors.New("model not found")
	}
	runtimeModel := modelruntime.Model{
		Digest: model.Digest, Format: model.Format, SizeBytes: model.SizeBytes,
		MinimumMemoryBytes: model.MinimumMemoryBytes, MinimumVRAMBytes: model.MinimumVRAMBytes,
	}
	var plan modelruntime.Plan
	if request.NodeName != "" {
		node, ok := s.data.Nodes[request.NodeName]
		if !ok {
			return ModelDeployment{}, errors.New("node inventory not found")
		}
		plan = modelruntime.Select(runtimeModel, request.Placement, node.Inventory)
	} else {
		names := make([]string, 0, len(s.data.Nodes))
		for name := range s.data.Nodes {
			names = append(names, name)
		}
		sort.Strings(names)
		if len(names) == 0 {
			return ModelDeployment{}, errors.New("no node inventory is available for automatic placement")
		}
		for _, name := range names {
			candidate := modelruntime.Select(runtimeModel, request.Placement, s.data.Nodes[name].Inventory)
			if request.NodeName == "" {
				request.NodeName = name
				plan = candidate
			}
			if candidate.Phase == "Ready" {
				request.NodeName = name
				plan = candidate
				break
			}
		}
	}
	deployment := ModelDeployment{DeploymentRequest: request, Plan: plan, CreatedAt: s.now().UTC(), UpdatedAt: s.now().UTC(), Status: DeploymentStatus{Phase: plan.Phase}}
	if plan.Phase == "Ready" {
		template, err := modelruntime.RenderPodTemplate(modelruntime.PodSpec{
			Name: request.Name, Namespace: request.Namespace, NodeName: request.NodeName,
			ModelAlias: request.ModelName, ModelPath: request.ModelPath, ModelSource: model.Source, ModelDigest: model.Digest, CachePVC: request.CachePVC,
			Port: request.Port, ContextLength: request.ContextLength, CPU: request.CPU, Memory: request.Memory,
			LlamaImage: s.images.Llama, VLLMImage: s.images.VLLM, FetcherImage: s.images.Fetcher,
		}, plan)
		if err != nil {
			return ModelDeployment{}, err
		}
		deployment.PodTemplate = template
	}
	key := request.Namespace + "/" + request.Name
	s.data.Deployments[key] = deployment
	s.auditLocked(actor, "modeldeployment.create", "ModelDeployment", key, map[string]string{"model": request.ModelName, "phase": plan.Phase})
	return deployment, s.saveLocked()
}

func (s *Store) UpdateDeploymentStatus(actor, namespace, name string, status DeploymentStatus) (ModelDeployment, error) {
	key := namespace + "/" + name
	s.mu.Lock()
	defer s.mu.Unlock()
	deployment, ok := s.data.Deployments[key]
	if !ok {
		return ModelDeployment{}, errors.New("deployment not found")
	}
	status.ObservedAt = s.now().UTC()
	if deployment.Status.Phase == status.Phase && deployment.Status.PodPhase == status.PodPhase && deployment.Status.PodIP == status.PodIP && deployment.Status.Message == status.Message {
		return deployment, nil
	}
	deployment.Status = status
	deployment.UpdatedAt = status.ObservedAt
	s.data.Deployments[key] = deployment
	s.auditLocked(actor, "modeldeployment.status.update", "ModelDeployment", key, status)
	return deployment, s.saveLocked()
}

func (s *Store) ListNodes() []Node {
	s.mu.RLock()
	defer s.mu.RUnlock()
	items := make([]Node, 0, len(s.data.Nodes))
	for _, item := range s.data.Nodes {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Name < items[j].Name })
	return items
}
func (s *Store) ListModels() []Model {
	s.mu.RLock()
	defer s.mu.RUnlock()
	items := make([]Model, 0, len(s.data.Models))
	for _, item := range s.data.Models {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Name < items[j].Name })
	return items
}
func (s *Store) ListDeployments() []ModelDeployment {
	s.mu.RLock()
	defer s.mu.RUnlock()
	items := make([]ModelDeployment, 0, len(s.data.Deployments))
	for _, item := range s.data.Deployments {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Namespace+items[i].Name < items[j].Namespace+items[j].Name })
	return items
}
func (s *Store) ListAudit() []AuditEvent {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return append([]AuditEvent(nil), s.data.Audit...)
}

func (s *Store) CreateBuild(actor string, request BuildRequest) (Build, error) {
	if request.Type != "bos" && request.Type != "oci" && request.Type != "cpm" && request.Type != "model" && request.Type != "iso" && request.Type != "pxe" && request.Type != "disk" {
		return Build{}, errors.New("build type must be bos, oci, cpm, model, iso, pxe, or disk")
	}
	if !request.Security.GenerateSBOM || !request.Security.GenerateProvenance || !request.Security.Sign {
		return Build{}, errors.New("SBOM, provenance, and signing are required")
	}
	var job map[string]any
	var networkPolicy map[string]any
	var factoryTask *imagefactory.Task
	var err error
	if request.Type == "bos" {
		var recipe *buildsystem.BOSRecipe
		if request.BOSRecipe != nil {
			arch := "amd64"
			if len(request.Platforms) == 1 && request.Platforms[0] == "linux/arm64" {
				arch = "arm64"
			}
			recipe = &buildsystem.BOSRecipe{Name: request.BOSRecipe.Name, Version: request.BOSRecipe.Version, Release: request.BOSRecipe.Release, Summary: request.BOSRecipe.Summary, Description: request.BOSRecipe.Description, License: request.BOSRecipe.License, Arch: arch, SourceURL: request.Source.URL, SourceSHA256: request.Source.Revision, BuildRequires: request.BOSRecipe.BuildRequires, Requires: request.BOSRecipe.Requires, Prepare: request.BOSRecipe.Prepare, Build: request.BOSRecipe.Build, Install: request.BOSRecipe.Install, Check: request.BOSRecipe.Check, Files: request.BOSRecipe.Files}
		}
		job, err = buildsystem.RenderBOSJob(buildsystem.BOSBuild{ID: request.ID, Source: request.Source, ContextPath: request.ContextPath, OutputName: request.OutputName, ArtifactPVC: request.ArtifactPVC, Platforms: request.Platforms, Recipe: recipe}, s.build)
		if err == nil {
			networkPolicy, err = buildsystem.RenderBuildNetworkPolicy(request.ID, s.build.EgressProxyCIDR)
		}
	} else if request.Type == "oci" || request.Type == "cpm" {
		job, err = buildsystem.RenderOCIJob(buildsystem.OCIBuild{ID: request.ID, Source: request.Source, ContextPath: request.ContextPath, DefinitionPath: request.DefinitionPath, Destination: request.Destination, ArtifactPVC: request.ArtifactPVC, Platforms: request.Platforms, PackageType: request.Type}, s.build.OCI)
		if err == nil {
			networkPolicy, err = buildsystem.RenderOCINetworkPolicy(request.ID, s.build.OCI)
		}
	} else if request.Type == "model" {
		if request.ModelBuild == nil {
			return Build{}, errors.New("model build options are required")
		}
		job, err = buildsystem.RenderModelJob(buildsystem.ModelBuild{ID: request.ID, Source: request.Source, ContextPath: request.ContextPath, InputPath: request.ModelBuild.InputPath, InputFormat: request.ModelBuild.InputFormat, OutputFormat: request.ModelBuild.OutputFormat, Quantization: request.ModelBuild.Quantization, Destination: request.Destination, ArtifactPVC: request.ArtifactPVC, LicenseID: request.ModelBuild.LicenseID}, s.build.Model)
		if err == nil {
			networkPolicy, err = buildsystem.RenderBuildNetworkPolicy(request.ID, s.build.Model.EgressProxyCIDR)
		}
	} else {
		if request.Factory == nil {
			return Build{}, errors.New("image factory options are required")
		}
		task, taskErr := imagefactory.CreateTask(imagefactory.Request{BuildID: request.ID, Type: request.Type, Source: request.Source, Release: request.Factory.Release, Arch: request.Factory.Arch, BootModes: request.Factory.BootModes, OutputName: request.OutputName}, s.build.AllowedGitHosts)
		err = taskErr
		if err == nil {
			factoryTask = &task
		}
	}
	if err != nil {
		return Build{}, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, exists := s.data.Builds[request.ID]; exists {
		return Build{}, errors.New("build ID already exists")
	}
	now := s.now().UTC()
	build := Build{BuildRequest: request, Phase: "Queued", Job: job, NetworkPolicy: networkPolicy, FactoryTask: factoryTask, CreatedAt: now, UpdatedAt: now}
	s.data.Builds[request.ID] = build
	s.auditLocked(actor, "build.create", "Build", request.ID, map[string]string{"revision": request.Source.Revision, "type": request.Type})
	return build, s.saveLocked()
}

func (s *Store) ClaimFactoryBuild(actor string, supportedTypes []string) (Build, error) {
	supported := make(map[string]bool, len(supportedTypes))
	for _, kind := range supportedTypes {
		if kind != "iso" && kind != "pxe" && kind != "disk" {
			return Build{}, fmt.Errorf("unsupported Image Factory capability %q", kind)
		}
		supported[kind] = true
	}
	if len(supported) == 0 {
		return Build{}, errors.New("at least one Image Factory capability is required")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	var selected *Build
	for _, candidate := range s.data.Builds {
		if candidate.Phase != "Queued" || candidate.FactoryTask == nil || !supported[candidate.Type] {
			continue
		}
		if selected == nil || candidate.CreatedAt.Before(selected.CreatedAt) || (candidate.CreatedAt.Equal(selected.CreatedAt) && candidate.ID < selected.ID) {
			copy := candidate
			selected = &copy
		}
	}
	if selected == nil {
		return Build{}, errors.New("no queued Image Factory build")
	}
	selected.Phase = "Fetching"
	selected.UpdatedAt = s.now().UTC()
	s.data.Builds[selected.ID] = *selected
	s.auditLocked(actor, "imagefactory.claim", "Build", selected.ID, map[string]string{"type": selected.Type})
	return *selected, s.saveLocked()
}

func (s *Store) ReportBuild(actor, id string, result BuildResult) (Build, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	build, ok := s.data.Builds[id]
	if !ok {
		return Build{}, errors.New("build not found")
	}
	if build.Phase == result.Phase {
		return build, nil
	}
	if !validBuildTransition(build.Phase, result.Phase) {
		return Build{}, fmt.Errorf("invalid build transition %s -> %s", build.Phase, result.Phase)
	}
	if result.Phase == "Succeeded" {
		if !sha256Pattern.MatchString(result.Digest) || result.SizeBytes == 0 || result.MediaType == "" || !sha256Pattern.MatchString(result.SBOMDigest) || !sha256Pattern.MatchString(result.ScanDigest) || !sha256Pattern.MatchString(result.ProvenanceDigest) || !sha256Pattern.MatchString(result.SignatureDigest) {
			return Build{}, errors.New("successful build requires artifact, SBOM, scan, provenance, and signature digests")
		}
		if _, exists := s.data.Artifacts[result.Digest]; exists {
			return Build{}, errors.New("artifact digest already exists")
		}
		artifact := Artifact{Digest: result.Digest, BuildID: id, Name: build.OutputName, MediaType: result.MediaType, SizeBytes: result.SizeBytes, SBOMDigest: result.SBOMDigest, ScanDigest: result.ScanDigest, ProvenanceDigest: result.ProvenanceDigest, SignatureDigest: result.SignatureDigest, CreatedAt: s.now().UTC()}
		s.data.Artifacts[result.Digest] = artifact
		build.Artifact = &artifact
	}
	build.Phase = result.Phase
	build.UpdatedAt = s.now().UTC()
	s.data.Builds[id] = build
	s.auditLocked(actor, "build.phase.update", "Build", id, result)
	return build, s.saveLocked()
}

func (s *Store) ListBuilds() []Build {
	s.mu.RLock()
	defer s.mu.RUnlock()
	items := make([]Build, 0, len(s.data.Builds))
	for _, item := range s.data.Builds {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].CreatedAt.Before(items[j].CreatedAt) })
	return items
}

func (s *Store) IsFactoryBuild(id string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	build, ok := s.data.Builds[id]
	return ok && build.FactoryTask != nil
}

func (s *Store) IsClusterBuild(id string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	build, ok := s.data.Builds[id]
	return ok && build.FactoryTask == nil && build.Job != nil
}
func (s *Store) ListArtifacts() []Artifact {
	s.mu.RLock()
	defer s.mu.RUnlock()
	items := make([]Artifact, 0, len(s.data.Artifacts))
	for _, item := range s.data.Artifacts {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Digest < items[j].Digest })
	return items
}

type MetricsSnapshot struct {
	Nodes       int
	Models      int
	Artifacts   int
	AuditEvents int
	Deployments map[string]int
	Builds      map[string]int
	Tasks       map[string]int
}

func (s *Store) Metrics() MetricsSnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()
	snapshot := MetricsSnapshot{Nodes: len(s.data.Nodes), Models: len(s.data.Models), Artifacts: len(s.data.Artifacts), AuditEvents: len(s.data.Audit), Deployments: map[string]int{}, Builds: map[string]int{}, Tasks: map[string]int{}}
	for _, deployment := range s.data.Deployments {
		snapshot.Deployments[deployment.Status.Phase]++
	}
	for _, build := range s.data.Builds {
		snapshot.Builds[build.Phase]++
	}
	for _, task := range s.data.Tasks {
		snapshot.Tasks[string(task.State)]++
	}
	return snapshot
}

func validBuildTransition(from, to string) bool {
	switch from {
	case "Queued":
		return to == "Fetching" || to == "Cancelled" || to == "Failed"
	case "Fetching":
		return to == "Validating" || to == "Failed" || to == "Cancelled"
	case "Validating":
		return to == "Building" || to == "Failed" || to == "Cancelled"
	case "Building":
		return to == "Testing" || to == "Failed" || to == "Cancelled"
	case "Testing":
		return to == "Scanning" || to == "Failed" || to == "Cancelled"
	case "Scanning":
		return to == "Signing" || to == "Failed" || to == "Cancelled"
	case "Signing":
		return to == "Publishing" || to == "Failed" || to == "Cancelled"
	case "Publishing":
		return to == "Succeeded" || to == "Failed" || to == "Cancelled"
	default:
		return false
	}
}

func (s *Store) auditLocked(actor, action, resource, id string, detail any) {
	encoded, _ := json.Marshal(detail)
	s.data.Audit = append(s.data.Audit, AuditEvent{ID: s.data.NextAuditID, Actor: actor, Action: action, Resource: resource, ResourceID: id, Detail: encoded, CreatedAt: s.now().UTC()})
	s.data.NextAuditID++
}

func (s *Store) saveLocked() error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o750); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s.data, "", "  ")
	if err != nil {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(s.path), ".infraops-state-*.tmp")
	if err != nil {
		return err
	}
	name := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(name)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		return err
	}
	if _, err := temporary.Write(data); err != nil {
		return err
	}
	if err := temporary.Sync(); err != nil {
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, s.path); err != nil {
		return err
	}
	committed = true
	return nil
}
