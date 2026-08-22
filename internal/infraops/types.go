package infraops

import (
	"encoding/json"
	"time"

	"example.com/aos-pkg/internal/agent"
	"example.com/aos-pkg/internal/buildsystem"
	"example.com/aos-pkg/internal/imagefactory"
	"example.com/aos-pkg/internal/modelruntime"
)

type Node struct {
	Name      string          `json:"name"`
	Inventory agent.Inventory `json:"inventory"`
	UpdatedAt time.Time       `json:"updated_at"`
}

type Model struct {
	Name               string    `json:"name"`
	Digest             string    `json:"digest"`
	Format             string    `json:"format"`
	Source             string    `json:"source"`
	SizeBytes          uint64    `json:"size_bytes"`
	MinimumMemoryBytes uint64    `json:"minimum_memory_bytes"`
	MinimumVRAMBytes   uint64    `json:"minimum_vram_bytes,omitempty"`
	LicenseID          string    `json:"license_id"`
	LicenseAccepted    bool      `json:"license_accepted"`
	CreatedAt          time.Time `json:"created_at"`
}

type DeploymentRequest struct {
	Name          string                 `json:"name"`
	Namespace     string                 `json:"namespace"`
	ModelName     string                 `json:"model_name"`
	NodeName      string                 `json:"node_name"`
	Placement     modelruntime.Placement `json:"placement"`
	ModelPath     string                 `json:"model_path"`
	CachePVC      string                 `json:"cache_pvc"`
	Port          int                    `json:"port"`
	ContextLength int                    `json:"context_length"`
	CPU           string                 `json:"cpu"`
	Memory        string                 `json:"memory"`
}

type ModelDeployment struct {
	DeploymentRequest
	Plan        modelruntime.Plan `json:"plan"`
	PodTemplate map[string]any    `json:"pod_template,omitempty"`
	CreatedAt   time.Time         `json:"created_at"`
	UpdatedAt   time.Time         `json:"updated_at"`
	Status      DeploymentStatus  `json:"status"`
}

type DeploymentStatus struct {
	Phase      string    `json:"phase"`
	PodPhase   string    `json:"pod_phase,omitempty"`
	PodIP      string    `json:"pod_ip,omitempty"`
	Message    string    `json:"message,omitempty"`
	ObservedAt time.Time `json:"observed_at,omitempty"`
}

type AuditEvent struct {
	ID         int64           `json:"id"`
	Actor      string          `json:"actor"`
	Action     string          `json:"action"`
	Resource   string          `json:"resource"`
	ResourceID string          `json:"resource_id"`
	Detail     json.RawMessage `json:"detail,omitempty"`
	CreatedAt  time.Time       `json:"created_at"`
}

type TaskRequest struct {
	ID             string              `json:"id"`
	IdempotencyKey string              `json:"idempotency_key"`
	Action         agent.TaskAction    `json:"action"`
	TargetNode     string              `json:"target_node"`
	Parameters     json.RawMessage     `json:"parameters"`
	Approval       agent.ApprovalClass `json:"approval"`
	ExpiresAt      time.Time           `json:"expires_at"`
}

type TaskApproval struct {
	Actor     string    `json:"actor"`
	CreatedAt time.Time `json:"created_at"`
}

type TaskResult struct {
	State   agent.TaskState `json:"state"`
	Message string          `json:"message,omitempty"`
	Output  json.RawMessage `json:"output,omitempty"`
}

type ManagedTask struct {
	agent.Task
	Approvals []TaskApproval `json:"approvals"`
	ClaimedBy string         `json:"claimed_by,omitempty"`
	Result    *TaskResult    `json:"result,omitempty"`
	UpdatedAt time.Time      `json:"updated_at"`
}

type BuildRequest struct {
	ID             string             `json:"id"`
	Type           string             `json:"type"`
	Source         buildsystem.Source `json:"source"`
	ContextPath    string             `json:"context_path"`
	DefinitionPath string             `json:"definition_path,omitempty"`
	Destination    string             `json:"destination,omitempty"`
	OutputName     string             `json:"output_name"`
	ArtifactPVC    string             `json:"artifact_pvc"`
	Platforms      []string           `json:"platforms"`
	Factory        *FactoryOptions    `json:"factory,omitempty"`
	ModelBuild     *ModelBuildOptions `json:"model,omitempty"`
	BOSRecipe      *BOSRecipeOptions  `json:"bos_recipe,omitempty"`
	Security       BuildSecurity      `json:"security"`
}

type BOSRecipeOptions struct {
	Name          string   `json:"name"`
	Version       string   `json:"version"`
	Release       string   `json:"release"`
	Summary       string   `json:"summary"`
	Description   string   `json:"description,omitempty"`
	License       string   `json:"license"`
	BuildRequires []string `json:"build_requires,omitempty"`
	Requires      []string `json:"requires,omitempty"`
	Prepare       []string `json:"prepare,omitempty"`
	Build         []string `json:"build,omitempty"`
	Install       []string `json:"install"`
	Check         []string `json:"check,omitempty"`
	Files         []string `json:"files"`
}

type ModelBuildOptions struct {
	InputPath    string `json:"input_path"`
	InputFormat  string `json:"input_format"`
	OutputFormat string `json:"output_format"`
	Quantization string `json:"quantization"`
	LicenseID    string `json:"license_id"`
}

type FactoryOptions struct {
	Release   string   `json:"release"`
	Arch      string   `json:"arch"`
	BootModes []string `json:"boot_modes"`
}

type BuildSecurity struct {
	GenerateSBOM       bool `json:"generate_sbom"`
	GenerateProvenance bool `json:"generate_provenance"`
	Sign               bool `json:"sign"`
}

type Build struct {
	BuildRequest
	Phase         string             `json:"phase"`
	Job           map[string]any     `json:"job,omitempty"`
	NetworkPolicy map[string]any     `json:"network_policy,omitempty"`
	FactoryTask   *imagefactory.Task `json:"factory_task,omitempty"`
	Artifact      *Artifact          `json:"artifact,omitempty"`
	CreatedAt     time.Time          `json:"created_at"`
	UpdatedAt     time.Time          `json:"updated_at"`
}

type BuildResult struct {
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

type Artifact struct {
	Digest           string    `json:"digest"`
	BuildID          string    `json:"build_id"`
	Name             string    `json:"name"`
	MediaType        string    `json:"media_type"`
	SizeBytes        uint64    `json:"size_bytes"`
	SBOMDigest       string    `json:"sbom_digest,omitempty"`
	ScanDigest       string    `json:"scan_digest,omitempty"`
	ProvenanceDigest string    `json:"provenance_digest,omitempty"`
	SignatureDigest  string    `json:"signature_digest,omitempty"`
	CreatedAt        time.Time `json:"created_at"`
}

type stateFile struct {
	NextAuditID int64                      `json:"next_audit_id"`
	Nodes       map[string]Node            `json:"nodes"`
	Models      map[string]Model           `json:"models"`
	Deployments map[string]ModelDeployment `json:"deployments"`
	Builds      map[string]Build           `json:"builds"`
	Artifacts   map[string]Artifact        `json:"artifacts"`
	Audit       []AuditEvent               `json:"audit"`
	Tasks       map[string]ManagedTask     `json:"tasks"`
}

type RuntimeImages struct {
	Llama   string
	VLLM    string
	Fetcher string
}
