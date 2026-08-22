package bootstrap

import "time"

type Node struct {
	Name            string         `json:"name"`
	Role            string         `json:"role,omitempty"`
	Phase           string         `json:"phase"`
	ClusterName     string         `json:"cluster_name,omitempty"`
	Hostname        string         `json:"hostname,omitempty"`
	BootMode        string         `json:"boot_mode,omitempty"`
	Disk            string         `json:"disk,omitempty"`
	RootFS          string         `json:"root_fs,omitempty"`
	OSDistribution  string         `json:"os_distribution,omitempty"`
	OSRelease       string         `json:"os_release,omitempty"`
	OSArchitecture  string         `json:"os_architecture,omitempty"`
	LastHeartbeatAt string         `json:"last_heartbeat_at,omitempty"`
	LastError       string         `json:"last_error,omitempty"`
	Raw             map[string]any `json:"raw,omitempty"`
	CreatedAt       time.Time      `json:"created_at"`
	UpdatedAt       time.Time      `json:"updated_at"`
	Events          []Event        `json:"events,omitempty"`
	Diagnostics     []Diagnostic   `json:"diagnostics,omitempty"`
}

type Event struct {
	ID        int64          `json:"id"`
	NodeName  string         `json:"node_name,omitempty"`
	Type      string         `json:"type"`
	Phase     string         `json:"phase,omitempty"`
	Message   string         `json:"message,omitempty"`
	Raw       map[string]any `json:"raw,omitempty"`
	CreatedAt time.Time      `json:"created_at"`
}

type Heartbeat struct {
	ID        int64          `json:"id"`
	NodeName  string         `json:"node_name"`
	Raw       map[string]any `json:"raw,omitempty"`
	CreatedAt time.Time      `json:"created_at"`
}

type Token struct {
	ID        string     `json:"id"`
	NodeName  string     `json:"node_name,omitempty"`
	Token     string     `json:"token,omitempty"` // legacy plaintext; migrated to TokenHash on load
	TokenHash string     `json:"token_hash,omitempty"`
	Status    string     `json:"status"`
	CreatedAt time.Time  `json:"created_at"`
	UsedAt    *time.Time `json:"used_at,omitempty"`
	ExpiresAt *time.Time `json:"expires_at,omitempty"`
}

type IssuedToken struct {
	ID        string     `json:"id"`
	NodeName  string     `json:"node_name,omitempty"`
	Token     string     `json:"token"`
	Status    string     `json:"status"`
	CreatedAt time.Time  `json:"created_at"`
	ExpiresAt *time.Time `json:"expires_at,omitempty"`
}

type NodeCredential struct {
	NodeName   string     `json:"node_name"`
	TokenHash  string     `json:"token_hash"`
	CreatedAt  time.Time  `json:"created_at"`
	LastUsedAt *time.Time `json:"last_used_at,omitempty"`
}

type RegistrationResult struct {
	OK        bool   `json:"ok"`
	Node      string `json:"node"`
	NodeToken string `json:"nodeToken,omitempty"`
}

type ImagePlan struct {
	ID          int64          `json:"id"`
	Name        string         `json:"name"`
	Destination string         `json:"destination,omitempty"`
	Status      string         `json:"status"`
	Raw         map[string]any `json:"raw,omitempty"`
	CreatedAt   time.Time      `json:"created_at"`
	UpdatedAt   time.Time      `json:"updated_at"`
	Items       []ImageItem    `json:"items"`
}

type ImageItem struct {
	ID          int64     `json:"id"`
	PlanID      int64     `json:"plan_id"`
	Image       string    `json:"image"`
	Destination string    `json:"destination,omitempty"`
	Status      string    `json:"status"`
	Message     string    `json:"message,omitempty"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type Diagnostic struct {
	ID        int64     `json:"id"`
	NodeName  string    `json:"node_name"`
	Provider  string    `json:"provider"`
	Summary   string    `json:"summary"`
	CreatedAt time.Time `json:"created_at"`
}

type Artifact struct {
	Name      string    `json:"name"`
	Path      string    `json:"path"`
	URL       string    `json:"url"`
	Kind      string    `json:"kind"`
	SizeBytes int64     `json:"size_bytes"`
	SHA256    string    `json:"sha256"`
	ModTime   time.Time `json:"mod_time"`
}

type StateFile struct {
	NextEventID      int64            `json:"next_event_id"`
	NextHeartbeatID  int64            `json:"next_heartbeat_id"`
	NextImagePlanID  int64            `json:"next_image_plan_id"`
	NextImageItemID  int64            `json:"next_image_item_id"`
	NextDiagnosticID int64            `json:"next_diagnostic_id"`
	Nodes            []Node           `json:"nodes"`
	Events           []Event          `json:"events"`
	Heartbeats       []Heartbeat      `json:"heartbeats"`
	Tokens           []Token          `json:"tokens"`
	NodeCredentials  []NodeCredential `json:"node_credentials"`
	ImagePlans       []ImagePlan      `json:"image_plans"`
	Diagnostics      []Diagnostic     `json:"diagnostics"`
}
