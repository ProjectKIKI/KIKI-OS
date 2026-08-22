package infraops

import (
	"context"
	"crypto/subtle"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"

	"example.com/aos-pkg/internal/agent"
)

//go:embed static/*
var staticFiles embed.FS

type Server struct {
	store      *Store
	principals map[string]Principal
	legacy     bool
}

type Principal struct {
	Token string
	Actor string
	Roles []string
}

type actorContextKey struct{}

func NewServer(store *Store, token string) http.Handler {
	server := &Server{store: store, principals: map[string]Principal{token: {Token: token, Roles: []string{"admin"}}}, legacy: true}
	return server.handler()
}

func NewServerWithPrincipals(store *Store, principals []Principal) (http.Handler, error) {
	server := &Server{store: store, principals: map[string]Principal{}}
	for _, principal := range principals {
		if strings.TrimSpace(principal.Token) == "" || strings.TrimSpace(principal.Actor) == "" || len(principal.Roles) == 0 {
			return nil, errors.New("principal token, actor, and roles are required")
		}
		if _, exists := server.principals[principal.Token]; exists {
			return nil, errors.New("principal token is duplicated")
		}
		server.principals[principal.Token] = principal
	}
	if len(server.principals) == 0 {
		return nil, errors.New("at least one principal is required")
	}
	return server.handler(), nil
}

func (s *Server) handler() http.Handler {
	server := s
	mux := http.NewServeMux()
	mux.HandleFunc("/", server.index)
	mux.HandleFunc("/api/v1/nodes", server.nodes)
	mux.HandleFunc("/api/v1/nodes/", server.node)
	mux.HandleFunc("/api/v1/models", server.models)
	mux.HandleFunc("/api/v1/model-deployments", server.deployments)
	mux.HandleFunc("/api/v1/audit", server.audit)
	mux.HandleFunc("/api/v1/builds", server.builds)
	mux.HandleFunc("/api/v1/builds/", server.build)
	mux.HandleFunc("/api/v1/artifacts", server.artifacts)
	mux.HandleFunc("/api/v1/image-factory/claim", server.claimFactoryBuild)
	mux.HandleFunc("/api/v1/tasks", server.tasks)
	mux.HandleFunc("/api/v1/tasks/", server.task)
	mux.HandleFunc("/metrics", server.metrics)
	return server.authenticate(mux)
}

func (s *Server) metrics(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		methodNotAllowed(response)
		return
	}
	snapshot := s.store.Metrics()
	response.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	_, _ = fmt.Fprintf(response, "# TYPE kiki_infraops_nodes gauge\nkiki_infraops_nodes %d\n# TYPE kiki_infraops_models gauge\nkiki_infraops_models %d\n# TYPE kiki_infraops_artifacts gauge\nkiki_infraops_artifacts %d\n# TYPE kiki_infraops_audit_events counter\nkiki_infraops_audit_events %d\n", snapshot.Nodes, snapshot.Models, snapshot.Artifacts, snapshot.AuditEvents)
	writePhaseMetrics(response, "kiki_infraops_deployments", snapshot.Deployments)
	writePhaseMetrics(response, "kiki_infraops_builds", snapshot.Builds)
	writePhaseMetrics(response, "kiki_infraops_tasks", snapshot.Tasks)
}

func writePhaseMetrics(response http.ResponseWriter, name string, values map[string]int) {
	_, _ = fmt.Fprintf(response, "# TYPE %s gauge\n", name)
	phases := make([]string, 0, len(values))
	for phase := range values {
		phases = append(phases, phase)
	}
	sort.Strings(phases)
	for _, phase := range phases {
		_, _ = fmt.Fprintf(response, "%s{phase=%q} %d\n", name, phase, values[phase])
	}
}

func (s *Server) claimFactoryBuild(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodPost {
		methodNotAllowed(response)
		return
	}
	var claim struct {
		Types []string `json:"types"`
	}
	if err := decodeJSON(response, request, &claim); err != nil {
		return
	}
	claimed, err := s.store.ClaimFactoryBuild(actor(request), claim.Types)
	if err != nil {
		writeJSON(response, http.StatusNotFound, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(response, http.StatusOK, claimed)
}

func (s *Server) authenticate(next http.Handler) http.Handler {
	return http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/" || strings.HasPrefix(request.URL.Path, "/static/") {
			next.ServeHTTP(response, request)
			return
		}
		provided := strings.TrimPrefix(request.Header.Get("Authorization"), "Bearer ")
		principal, ok := s.lookupPrincipal(provided)
		if !ok {
			writeJSON(response, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
			return
		}
		requestedActor := strings.TrimSpace(request.Header.Get("X-Kiki-Actor"))
		if s.legacy {
			if requestedActor == "" {
				writeJSON(response, http.StatusBadRequest, map[string]string{"error": "X-Kiki-Actor is required"})
				return
			}
			principal.Actor = requestedActor
		} else if requestedActor != "" && requestedActor != principal.Actor {
			writeJSON(response, http.StatusForbidden, map[string]string{"error": "actor does not match authenticated principal"})
			return
		}
		if !s.authorized(principal, request) {
			writeJSON(response, http.StatusForbidden, map[string]string{"error": "forbidden"})
			return
		}
		next.ServeHTTP(response, request.WithContext(context.WithValue(request.Context(), actorContextKey{}, principal.Actor)))
	})
}

func (s *Server) lookupPrincipal(token string) (Principal, bool) {
	for expected, principal := range s.principals {
		if expected != "" && len(token) == len(expected) && subtle.ConstantTimeCompare([]byte(token), []byte(expected)) == 1 {
			return principal, true
		}
	}
	return Principal{}, false
}

func (s *Server) authorized(principal Principal, request *http.Request) bool {
	if hasRole(principal, "admin") {
		return true
	}
	if request.Method == http.MethodGet && hasRole(principal, "viewer") {
		return true
	}
	if hasRole(principal, "operator") {
		return true
	}
	if hasRole(principal, "agent") && strings.HasPrefix(request.URL.Path, "/api/v1/nodes/") {
		if request.Method == http.MethodPut && strings.HasSuffix(request.URL.Path, "/inventory") {
			return true
		}
		if request.Method == http.MethodPost && strings.HasSuffix(request.URL.Path, "/tasks/claim") {
			return true
		}
		if request.Method == http.MethodPut && strings.Contains(request.URL.Path, "/tasks/") && strings.HasSuffix(request.URL.Path, "/result") {
			return true
		}
	}
	if hasRole(principal, "image-factory") {
		if request.Method == http.MethodPost && request.URL.Path == "/api/v1/image-factory/claim" {
			return true
		}
		if request.Method == http.MethodPut && strings.HasPrefix(request.URL.Path, "/api/v1/builds/") && strings.HasSuffix(request.URL.Path, "/result") {
			path := strings.TrimSuffix(strings.TrimPrefix(request.URL.Path, "/api/v1/builds/"), "/result")
			return s.store.IsFactoryBuild(path)
		}
	}
	if hasRole(principal, "build-worker") && request.Method == http.MethodPut && strings.HasPrefix(request.URL.Path, "/api/v1/builds/") && strings.HasSuffix(request.URL.Path, "/result") {
		path := strings.TrimSuffix(strings.TrimPrefix(request.URL.Path, "/api/v1/builds/"), "/result")
		return s.store.IsClusterBuild(path)
	}
	return false
}

func hasRole(principal Principal, role string) bool {
	for _, value := range principal.Roles {
		if value == role {
			return true
		}
	}
	return false
}

func (s *Server) index(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		writeJSON(response, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	path := "static/index.html"
	contentType := "text/html; charset=utf-8"
	if request.URL.Path == "/static/app.css" {
		path = "static/app.css"
		contentType = "text/css; charset=utf-8"
	} else if request.URL.Path == "/static/recipe.css" {
		path = "static/recipe.css"
		contentType = "text/css; charset=utf-8"
	} else if request.URL.Path == "/static/app.js" {
		path = "static/app.js"
		contentType = "application/javascript; charset=utf-8"
	} else if request.URL.Path != "/" {
		writeJSON(response, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	data, err := staticFiles.ReadFile(path)
	if err != nil {
		writeJSON(response, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	response.Header().Set("Content-Type", contentType)
	response.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
	response.Header().Set("X-Content-Type-Options", "nosniff")
	_, _ = response.Write(data)
}

func (s *Server) nodes(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		methodNotAllowed(response)
		return
	}
	writeJSON(response, http.StatusOK, s.store.ListNodes())
}

func (s *Server) node(response http.ResponseWriter, request *http.Request) {
	path := strings.TrimPrefix(request.URL.Path, "/api/v1/nodes/")
	parts := strings.Split(path, "/")
	if len(parts) == 2 && parts[1] == "inventory" && request.Method == http.MethodPut {
		var inventory agent.Inventory
		if err := decodeJSON(response, request, &inventory); err != nil {
			return
		}
		node, err := s.store.UpsertNode(parts[0], actor(request), inventory)
		if err != nil {
			writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(response, http.StatusOK, node)
		return
	}
	if len(parts) == 3 && parts[1] == "tasks" && parts[2] == "claim" && request.Method == http.MethodPost {
		var claim struct {
			Actions []agent.TaskAction `json:"actions"`
		}
		if err := decodeJSON(response, request, &claim); err != nil {
			return
		}
		claimed, err := s.store.ClaimNodeTask(actor(request), parts[0], claim.Actions)
		if err != nil {
			writeJSON(response, http.StatusNotFound, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(response, http.StatusOK, claimed)
		return
	}
	if len(parts) == 4 && parts[1] == "tasks" && parts[3] == "result" && request.Method == http.MethodPut {
		var result TaskResult
		if err := decodeJSON(response, request, &result); err != nil {
			return
		}
		completed, err := s.store.CompleteNodeTask(actor(request), parts[0], parts[2], result)
		if err != nil {
			writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(response, http.StatusOK, completed)
		return
	}
	writeJSON(response, http.StatusNotFound, map[string]string{"error": "not found"})
}

func (s *Server) tasks(response http.ResponseWriter, request *http.Request) {
	switch request.Method {
	case http.MethodGet:
		writeJSON(response, http.StatusOK, s.store.ListTasks())
	case http.MethodPost:
		var value TaskRequest
		if err := decodeJSON(response, request, &value); err != nil {
			return
		}
		created, err := s.store.CreateTask(actor(request), value)
		if err != nil {
			writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(response, http.StatusCreated, created)
	default:
		methodNotAllowed(response)
	}
}

func (s *Server) task(response http.ResponseWriter, request *http.Request) {
	path := strings.TrimPrefix(request.URL.Path, "/api/v1/tasks/")
	id, suffix, ok := strings.Cut(path, "/")
	if !ok || suffix != "approve" || request.Method != http.MethodPost {
		writeJSON(response, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	approved, err := s.store.ApproveTask(actor(request), id)
	if err != nil {
		writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(response, http.StatusOK, approved)
}

func (s *Server) models(response http.ResponseWriter, request *http.Request) {
	switch request.Method {
	case http.MethodGet:
		writeJSON(response, http.StatusOK, s.store.ListModels())
	case http.MethodPost:
		var model Model
		if err := decodeJSON(response, request, &model); err != nil {
			return
		}
		created, err := s.store.CreateModel(actor(request), model)
		if err != nil {
			writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(response, http.StatusCreated, created)
	default:
		methodNotAllowed(response)
	}
}

func (s *Server) deployments(response http.ResponseWriter, request *http.Request) {
	switch request.Method {
	case http.MethodGet:
		writeJSON(response, http.StatusOK, s.store.ListDeployments())
	case http.MethodPost:
		var deployment DeploymentRequest
		if err := decodeJSON(response, request, &deployment); err != nil {
			return
		}
		created, err := s.store.CreateDeployment(actor(request), deployment)
		if err != nil {
			writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(response, http.StatusCreated, created)
	default:
		methodNotAllowed(response)
	}
}

func (s *Server) audit(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		methodNotAllowed(response)
		return
	}
	writeJSON(response, http.StatusOK, s.store.ListAudit())
}

func (s *Server) builds(response http.ResponseWriter, request *http.Request) {
	switch request.Method {
	case http.MethodGet:
		writeJSON(response, http.StatusOK, s.store.ListBuilds())
	case http.MethodPost:
		var build BuildRequest
		if err := decodeJSON(response, request, &build); err != nil {
			return
		}
		created, err := s.store.CreateBuild(actor(request), build)
		if err != nil {
			writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(response, http.StatusCreated, created)
	default:
		methodNotAllowed(response)
	}
}

func (s *Server) build(response http.ResponseWriter, request *http.Request) {
	path := strings.TrimPrefix(request.URL.Path, "/api/v1/builds/")
	id, suffix, ok := strings.Cut(path, "/")
	if !ok || suffix != "result" || request.Method != http.MethodPut {
		writeJSON(response, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	var result BuildResult
	if err := decodeJSON(response, request, &result); err != nil {
		return
	}
	updated, err := s.store.ReportBuild(actor(request), id, result)
	if err != nil {
		writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(response, http.StatusOK, updated)
}

func (s *Server) artifacts(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		methodNotAllowed(response)
		return
	}
	writeJSON(response, http.StatusOK, s.store.ListArtifacts())
}

func decodeJSON(response http.ResponseWriter, request *http.Request, target any) error {
	request.Body = http.MaxBytesReader(response, request.Body, 2<<20)
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		err = errors.New("request contains trailing JSON")
		writeJSON(response, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return err
	}
	return nil
}

func actor(request *http.Request) string {
	value, _ := request.Context().Value(actorContextKey{}).(string)
	return value
}
func writeJSON(response http.ResponseWriter, status int, value any) {
	response.Header().Set("Content-Type", "application/json")
	response.WriteHeader(status)
	_ = json.NewEncoder(response).Encode(value)
}
func methodNotAllowed(response http.ResponseWriter) {
	writeJSON(response, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
}
