package bootstrap

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
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
)

type Store struct {
	path string
	mu   sync.Mutex
	data StateFile
}

var nodeNamePattern = regexp.MustCompile(`^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$`)

func NewStore(path string) (*Store, error) {
	st := &Store{path: path}
	if err := st.load(); err != nil {
		return nil, err
	}
	return st, nil
}

func (s *Store) load() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	data, err := os.ReadFile(s.path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			s.data = StateFile{
				NextEventID:      1,
				NextHeartbeatID:  1,
				NextImagePlanID:  1,
				NextImageItemID:  1,
				NextDiagnosticID: 1,
			}
			return s.saveLocked()
		}
		return err
	}
	if len(data) == 0 {
		return nil
	}
	if err := json.Unmarshal(data, &s.data); err != nil {
		return err
	}
	s.ensureCounters()
	return nil
}

func (s *Store) ensureCounters() {
	if s.data.NextEventID == 0 {
		s.data.NextEventID = 1
	}
	if s.data.NextHeartbeatID == 0 {
		s.data.NextHeartbeatID = 1
	}
	if s.data.NextImagePlanID == 0 {
		s.data.NextImagePlanID = 1
	}
	if s.data.NextImageItemID == 0 {
		s.data.NextImageItemID = 1
	}
	if s.data.NextDiagnosticID == 0 {
		s.data.NextDiagnosticID = 1
	}
	if s.data.Nodes == nil {
		s.data.Nodes = []Node{}
	}
	if s.data.Events == nil {
		s.data.Events = []Event{}
	}
	if s.data.Heartbeats == nil {
		s.data.Heartbeats = []Heartbeat{}
	}
	if s.data.Tokens == nil {
		s.data.Tokens = []Token{}
	}
	if s.data.NodeCredentials == nil {
		s.data.NodeCredentials = []NodeCredential{}
	}
	for i := range s.data.Tokens {
		if s.data.Tokens[i].TokenHash == "" && s.data.Tokens[i].Token != "" {
			s.data.Tokens[i].TokenHash = tokenHash(s.data.Tokens[i].Token)
			s.data.Tokens[i].Token = ""
		}
	}
	if s.data.ImagePlans == nil {
		s.data.ImagePlans = []ImagePlan{}
	}
	if s.data.Diagnostics == nil {
		s.data.Diagnostics = []Diagnostic{}
	}
}

func (s *Store) saveLocked() error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s.data, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	if err := os.Rename(tmp, s.path); err == nil {
		return nil
	}
	_ = os.Remove(s.path)
	if err := os.Rename(tmp, s.path); err == nil {
		return nil
	}
	_ = os.Remove(tmp)
	return os.WriteFile(s.path, data, 0o600)
}

func (s *Store) RegisterNode(payload map[string]any, bearerToken string, requireToken bool) (RegistrationResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	node := nodeFromPayload(payload)
	if node.Name == "" {
		return RegistrationResult{}, errors.New("metadata.name is required")
	}
	if err := validateNodeName(node.Name); err != nil {
		return RegistrationResult{}, err
	}
	now := time.Now().UTC()
	issuedNodeToken := ""
	if bearerToken != "" {
		if err := s.authenticateNodeLocked(node.Name, bearerToken, now); err != nil {
			return RegistrationResult{}, err
		}
	} else {
		registrationToken := stringAt(payload, "spec", "registrationToken")
		if requireToken {
			if err := s.consumeActiveTokenLocked(registrationToken, node.Name, now); err != nil {
				return RegistrationResult{}, err
			}
		} else if registrationToken != "" {
			_ = s.consumeActiveTokenLocked(registrationToken, node.Name, now)
		}
		var err error
		issuedNodeToken, err = randomToken(32)
		if err != nil {
			return RegistrationResult{}, err
		}
		s.replaceNodeCredentialLocked(node.Name, issuedNodeToken, now)
	}
	deleteNested(payload, "spec", "registrationToken")
	s.upsertNodeLocked(node, "registration", payload, now)
	if err := s.saveLocked(); err != nil {
		return RegistrationResult{}, err
	}
	return RegistrationResult{OK: true, Node: node.Name, NodeToken: issuedNodeToken}, nil
}

func (s *Store) upsertNodeLocked(node Node, eventType string, payload map[string]any, now time.Time) {
	existing := -1
	for i := range s.data.Nodes {
		if s.data.Nodes[i].Name == node.Name {
			existing = i
			break
		}
	}
	if existing >= 0 {
		current := s.data.Nodes[existing]
		if phaseRank(current.Phase) > phaseRank(node.Phase) && node.Phase != "failed" {
			node.Phase = current.Phase
		}
		mergeNode(&current, node)
		current.UpdatedAt = now
		s.data.Nodes[existing] = current
	} else {
		node.CreatedAt = now
		node.UpdatedAt = now
		s.data.Nodes = append(s.data.Nodes, node)
	}
	s.addEventLocked(node.Name, eventType, node.Phase, eventType, payload, now)
}

func (s *Store) Heartbeat(payload map[string]any, bearerToken string, requireToken bool) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	node := nodeFromPayload(withPhase(payload, "booted"))
	if node.Name == "" {
		return "", errors.New("metadata.name is required")
	}
	if err := validateNodeName(node.Name); err != nil {
		return "", err
	}
	now := time.Now().UTC()
	if requireToken {
		if err := s.authenticateNodeLocked(node.Name, bearerToken, now); err != nil {
			return "", err
		}
	}
	s.upsertNodeLocked(node, "heartbeat", payload, now)
	s.data.Heartbeats = append(s.data.Heartbeats, Heartbeat{
		ID:        s.data.NextHeartbeatID,
		NodeName:  node.Name,
		Raw:       redactMap(payload),
		CreatedAt: now,
	})
	s.data.NextHeartbeatID++
	for i := range s.data.Nodes {
		if s.data.Nodes[i].Name == node.Name {
			s.data.Nodes[i].Phase = "booted"
			s.data.Nodes[i].LastHeartbeatAt = now.Format(time.RFC3339)
			s.data.Nodes[i].UpdatedAt = now
			break
		}
	}
	return node.Name, s.saveLocked()
}

func (s *Store) LogEvent(payload map[string]any, bearerToken string, requireToken bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	nodeName := firstNonEmpty(stringAt(payload, "node"), stringAt(payload, "nodeName"), stringAt(payload, "metadata", "name"))
	if nodeName == "" {
		return errors.New("nodeName is required")
	}
	now := time.Now().UTC()
	if requireToken {
		if err := s.authenticateNodeLocked(nodeName, bearerToken, now); err != nil {
			return err
		}
	}
	level := firstNonEmpty(stringAt(payload, "level"), "info")
	message := stringAt(payload, "message")
	s.addEventLocked(nodeName, "log", level, message, payload, now)
	if level == "error" && nodeName != "" {
		for i := range s.data.Nodes {
			if s.data.Nodes[i].Name == nodeName {
				s.data.Nodes[i].Phase = "failed"
				s.data.Nodes[i].LastError = message
				s.data.Nodes[i].UpdatedAt = now
				break
			}
		}
	}
	return s.saveLocked()
}

func (s *Store) RecordLogBundle(nodeName, bearerToken, message string, payload map[string]any, requireToken bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now().UTC()
	if requireToken {
		if err := s.authenticateNodeLocked(nodeName, bearerToken, now); err != nil {
			return err
		}
	}
	s.addEventLocked(nodeName, "log_bundle", "uploaded", message, payload, now)
	return s.saveLocked()
}

func (s *Store) ValidateNodeCredential(nodeName, bearerToken string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.authenticateNodeLocked(nodeName, bearerToken, time.Now().UTC())
}

func (s *Store) CreateToken(nodeName string, ttlSeconds int) (IssuedToken, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now().UTC()
	if err := validateNodeName(nodeName); err != nil {
		return IssuedToken{}, err
	}
	id, err := randomHex(8)
	if err != nil {
		return IssuedToken{}, err
	}
	tokenValue, err := randomToken(32)
	if err != nil {
		return IssuedToken{}, err
	}
	token := Token{
		ID:        id,
		NodeName:  nodeName,
		TokenHash: tokenHash(tokenValue),
		Status:    "active",
		CreatedAt: now,
	}
	if ttlSeconds > 0 {
		expires := now.Add(time.Duration(ttlSeconds) * time.Second)
		token.ExpiresAt = &expires
	}
	s.data.Tokens = append(s.data.Tokens, token)
	if err := s.saveLocked(); err != nil {
		return IssuedToken{}, err
	}
	return IssuedToken{ID: token.ID, NodeName: token.NodeName, Token: tokenValue, Status: token.Status, CreatedAt: token.CreatedAt, ExpiresAt: token.ExpiresAt}, nil
}

func (s *Store) CreateImagePlan(payload map[string]any) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now().UTC()
	name := firstNonEmpty(stringAt(payload, "metadata", "name"), "image-plan")
	destination := stringAt(payload, "spec", "destination")
	plan := ImagePlan{
		ID:          s.data.NextImagePlanID,
		Name:        name,
		Destination: destination,
		Status:      "planned",
		Raw:         redactMap(payload),
		CreatedAt:   now,
		UpdatedAt:   now,
	}
	s.data.NextImagePlanID++
	for _, image := range stringSliceAt(payload, "spec", "images") {
		item := ImageItem{
			ID:          s.data.NextImageItemID,
			PlanID:      plan.ID,
			Image:       image,
			Destination: imageDestination(destination, image),
			Status:      "planned",
			UpdatedAt:   now,
		}
		s.data.NextImageItemID++
		plan.Items = append(plan.Items, item)
	}
	s.data.ImagePlans = append(s.data.ImagePlans, plan)
	return plan.ID, s.saveLocked()
}

func (s *Store) ListNodes() []Node {
	s.mu.Lock()
	defer s.mu.Unlock()
	nodes := append([]Node(nil), s.data.Nodes...)
	if nodes == nil {
		return []Node{}
	}
	sort.Slice(nodes, func(i, j int) bool {
		return nodes[i].UpdatedAt.After(nodes[j].UpdatedAt)
	})
	return nodes
}

func (s *Store) NodeDetail(name string) (Node, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, node := range s.data.Nodes {
		if node.Name == name {
			node.Events = recentEventsForNode(s.data.Events, name, 50)
			node.Diagnostics = recentDiagnosticsForNode(s.data.Diagnostics, name, 5)
			return node, true
		}
	}
	return Node{}, false
}

func (s *Store) Events(limit int) []Event {
	s.mu.Lock()
	defer s.mu.Unlock()
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	events := append([]Event(nil), s.data.Events...)
	if events == nil {
		return []Event{}
	}
	sort.Slice(events, func(i, j int) bool {
		return events[i].ID > events[j].ID
	})
	if len(events) > limit {
		events = events[:limit]
	}
	return events
}

func (s *Store) Images() []ImagePlan {
	s.mu.Lock()
	defer s.mu.Unlock()
	plans := append([]ImagePlan(nil), s.data.ImagePlans...)
	if plans == nil {
		return []ImagePlan{}
	}
	sort.Slice(plans, func(i, j int) bool {
		return plans[i].ID > plans[j].ID
	})
	return plans
}

func (s *Store) Diagnose(name string, runner DiagnosticRunner) (Diagnostic, error) {
	s.mu.Lock()
	detail, ok := nodeDetailLocked(s.data, name)
	s.mu.Unlock()
	if !ok {
		return Diagnostic{}, fmt.Errorf("node %q not found", name)
	}

	provider, summary := runner.Diagnose(detail)
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UTC()
	diag := Diagnostic{
		ID:        s.data.NextDiagnosticID,
		NodeName:  name,
		Provider:  provider,
		Summary:   summary,
		CreatedAt: now,
	}
	s.data.NextDiagnosticID++
	s.data.Diagnostics = append(s.data.Diagnostics, diag)
	return diag, s.saveLocked()
}

func (s *Store) addEventLocked(nodeName, eventType, phase, message string, payload map[string]any, createdAt time.Time) {
	s.data.Events = append(s.data.Events, Event{
		ID:        s.data.NextEventID,
		NodeName:  nodeName,
		Type:      eventType,
		Phase:     phase,
		Message:   message,
		Raw:       redactMap(payload),
		CreatedAt: createdAt,
	})
	s.data.NextEventID++
}

func (s *Store) consumeActiveTokenLocked(token, nodeName string, usedAt time.Time) error {
	if token == "" {
		return errors.New("registration token is missing")
	}
	for i := range s.data.Tokens {
		if !tokenMatches(s.data.Tokens[i].TokenHash, token) {
			continue
		}
		if s.data.Tokens[i].Status != "active" {
			return errors.New("registration token is inactive")
		}
		if s.data.Tokens[i].ExpiresAt != nil && s.data.Tokens[i].ExpiresAt.Before(usedAt) {
			return errors.New("registration token expired")
		}
		if s.data.Tokens[i].NodeName != "" && s.data.Tokens[i].NodeName != nodeName {
			return errors.New("registration token is bound to another node")
		}
		s.data.Tokens[i].Status = "used"
		s.data.Tokens[i].UsedAt = &usedAt
		return nil
	}
	return errors.New("registration token not found")
}

func (s *Store) replaceNodeCredentialLocked(nodeName, token string, createdAt time.Time) {
	credential := NodeCredential{NodeName: nodeName, TokenHash: tokenHash(token), CreatedAt: createdAt}
	for i := range s.data.NodeCredentials {
		if s.data.NodeCredentials[i].NodeName == nodeName {
			s.data.NodeCredentials[i] = credential
			return
		}
	}
	s.data.NodeCredentials = append(s.data.NodeCredentials, credential)
}

func (s *Store) authenticateNodeLocked(nodeName, token string, usedAt time.Time) error {
	if token == "" {
		return errors.New("node bearer token is missing")
	}
	for i := range s.data.NodeCredentials {
		credential := &s.data.NodeCredentials[i]
		if credential.NodeName != nodeName || !tokenMatches(credential.TokenHash, token) {
			continue
		}
		credential.LastUsedAt = &usedAt
		return nil
	}
	return errors.New("node bearer token is invalid")
}

func tokenHash(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func tokenMatches(expectedHash, token string) bool {
	actual := tokenHash(token)
	return len(expectedHash) == len(actual) && subtle.ConstantTimeCompare([]byte(expectedHash), []byte(actual)) == 1
}

func deleteNested(input map[string]any, path ...string) {
	if len(path) == 0 {
		return
	}
	cursor := input
	for _, part := range path[:len(path)-1] {
		next, ok := cursor[part].(map[string]any)
		if !ok {
			return
		}
		cursor = next
	}
	delete(cursor, path[len(path)-1])
}

func validateNodeName(name string) error {
	if len(name) == 0 || len(name) > 253 || strings.Contains(name, "..") || !nodeNamePattern.MatchString(name) {
		return errors.New("node name must be a valid lowercase DNS name")
	}
	return nil
}

func nodeFromPayload(payload map[string]any) Node {
	name := firstNonEmpty(stringAt(payload, "metadata", "name"), stringAt(payload, "spec", "hostname"), stringAt(payload, "spec", "nodeName"))
	return Node{
		Name:           name,
		Role:           stringAt(payload, "spec", "role"),
		Phase:          firstNonEmpty(stringAt(payload, "spec", "phase"), "unknown"),
		ClusterName:    stringAt(payload, "spec", "clusterRef", "name"),
		Hostname:       firstNonEmpty(stringAt(payload, "spec", "hostname"), name),
		BootMode:       stringAt(payload, "spec", "storage", "bootMode"),
		Disk:           stringAt(payload, "spec", "storage", "disk"),
		RootFS:         stringAt(payload, "spec", "storage", "rootFs"),
		OSDistribution: stringAt(payload, "spec", "os", "distribution"),
		OSRelease:      stringAt(payload, "spec", "os", "release"),
		OSArchitecture: stringAt(payload, "spec", "os", "architecture"),
		Raw:            redactMap(payload),
	}
}

func mergeNode(dst *Node, src Node) {
	if src.Role != "" {
		dst.Role = src.Role
	}
	if src.Phase != "" {
		dst.Phase = src.Phase
	}
	if src.ClusterName != "" {
		dst.ClusterName = src.ClusterName
	}
	if src.Hostname != "" {
		dst.Hostname = src.Hostname
	}
	if src.BootMode != "" {
		dst.BootMode = src.BootMode
	}
	if src.Disk != "" {
		dst.Disk = src.Disk
	}
	if src.RootFS != "" {
		dst.RootFS = src.RootFS
	}
	if src.OSDistribution != "" {
		dst.OSDistribution = src.OSDistribution
	}
	if src.OSRelease != "" {
		dst.OSRelease = src.OSRelease
	}
	if src.OSArchitecture != "" {
		dst.OSArchitecture = src.OSArchitecture
	}
	if src.Raw != nil {
		dst.Raw = src.Raw
	}
}

func nodeDetailLocked(data StateFile, name string) (Node, bool) {
	for _, node := range data.Nodes {
		if node.Name == name {
			node.Events = recentEventsForNode(data.Events, name, 50)
			node.Diagnostics = recentDiagnosticsForNode(data.Diagnostics, name, 5)
			return node, true
		}
	}
	return Node{}, false
}

func recentEventsForNode(events []Event, name string, limit int) []Event {
	var result []Event
	for i := len(events) - 1; i >= 0 && len(result) < limit; i-- {
		if events[i].NodeName == name {
			result = append(result, events[i])
		}
	}
	return result
}

func recentDiagnosticsForNode(diagnostics []Diagnostic, name string, limit int) []Diagnostic {
	var result []Diagnostic
	for i := len(diagnostics) - 1; i >= 0 && len(result) < limit; i-- {
		if diagnostics[i].NodeName == name {
			result = append(result, diagnostics[i])
		}
	}
	return result
}

func withPhase(payload map[string]any, phase string) map[string]any {
	copyPayload := cloneMap(payload)
	spec, _ := copyPayload["spec"].(map[string]any)
	if spec == nil {
		spec = map[string]any{}
		copyPayload["spec"] = spec
	}
	spec["phase"] = phase
	return copyPayload
}

func cloneMap(input map[string]any) map[string]any {
	data, _ := json.Marshal(input)
	var output map[string]any
	_ = json.Unmarshal(data, &output)
	return output
}

func redactMap(input map[string]any) map[string]any {
	return redactAny(input).(map[string]any)
}

func redactAny(input any) any {
	switch value := input.(type) {
	case map[string]any:
		out := make(map[string]any, len(value))
		for key, item := range value {
			lower := strings.ToLower(key)
			if lower == "registrationtoken" || lower == "token" || lower == "authorization" {
				out[key] = "REDACTED"
			} else {
				out[key] = redactAny(item)
			}
		}
		return out
	case []any:
		out := make([]any, 0, len(value))
		for _, item := range value {
			out = append(out, redactAny(item))
		}
		return out
	default:
		return input
	}
}

func stringAt(input map[string]any, path ...string) string {
	var cursor any = input
	for _, part := range path {
		mapping, ok := cursor.(map[string]any)
		if !ok {
			return ""
		}
		cursor = mapping[part]
	}
	switch value := cursor.(type) {
	case string:
		return value
	case fmt.Stringer:
		return value.String()
	default:
		return ""
	}
}

func stringSliceAt(input map[string]any, path ...string) []string {
	var cursor any = input
	for _, part := range path {
		mapping, ok := cursor.(map[string]any)
		if !ok {
			return nil
		}
		cursor = mapping[part]
	}
	items, ok := cursor.([]any)
	if !ok {
		return nil
	}
	var result []string
	for _, item := range items {
		if text, ok := item.(string); ok {
			result = append(result, text)
		}
	}
	return result
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func phaseRank(phase string) int {
	switch phase {
	case "pending":
		return 0
	case "installing":
		return 10
	case "installed":
		return 20
	case "booted":
		return 30
	case "failed":
		return 100
	default:
		return 5
	}
}

func imageDestination(destination, image string) string {
	if destination == "" {
		return ""
	}
	parts := strings.SplitN(image, "/", 2)
	suffix := image
	if len(parts) == 2 {
		suffix = parts[1]
	}
	return strings.TrimRight(destination, "/") + "/" + suffix
}

func randomHex(bytes int) (string, error) {
	buf := make([]byte, bytes)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

func randomToken(bytes int) (string, error) {
	buf := make([]byte, bytes)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}
