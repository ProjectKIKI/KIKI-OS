package bootstrap

import (
	"crypto/sha256"
	"crypto/subtle"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

//go:embed static/*
var staticFS embed.FS

type Server struct {
	store        *Store
	artifactsDir string
	requireToken bool
	adminToken   string
	maxUpload    int64
	diagnostics  DiagnosticRunner
}

type ServerOptions struct {
	RequireRegistrationToken bool
	AdminToken               string
	MaxUploadBytes           int64
	Diagnostics              DiagnosticRunner
}

func NewServer(store *Store, artifactsDir string, requireToken bool, diagnostics DiagnosticRunner) http.Handler {
	return NewServerWithOptions(store, artifactsDir, ServerOptions{RequireRegistrationToken: requireToken, Diagnostics: diagnostics})
}

func NewServerWithOptions(store *Store, artifactsDir string, options ServerOptions) http.Handler {
	maxUpload := options.MaxUploadBytes
	if maxUpload <= 0 {
		maxUpload = 128 << 20
	}
	s := &Server{
		store:        store,
		artifactsDir: artifactsDir,
		requireToken: options.RequireRegistrationToken,
		adminToken:   options.AdminToken,
		maxUpload:    maxUpload,
		diagnostics:  options.Diagnostics,
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleIndex)
	mux.HandleFunc("/api/v1/nodes", s.handleNodes)
	mux.HandleFunc("/api/v1/nodes/", s.handleNode)
	mux.HandleFunc("/api/v1/events", s.handleEvents)
	mux.HandleFunc("/api/v1/images", s.handleImages)
	mux.HandleFunc("/api/v1/tokens", s.handleTokens)
	mux.HandleFunc("/api/v1/artifacts", s.handleArtifactIndex)
	mux.HandleFunc("/artifacts/", s.handleArtifacts)
	return logMiddleware(mux)
}

func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	data, err := staticFS.ReadFile("static/index.html")
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	_, _ = w.Write(data)
}

func (s *Server) handleNodes(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	if !s.requireAdmin(w, r) {
		return
	}
	writeJSON(w, http.StatusOK, s.store.ListNodes())
}

func (s *Server) handleNode(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/v1/nodes/")
	if path == "register" && r.Method == http.MethodPost {
		payload, err := readJSON(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		result, err := s.store.RegisterNode(payload, bearerToken(r), s.requireToken)
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, result)
		return
	}
	if path == "heartbeat" && r.Method == http.MethodPost {
		payload, err := readJSON(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		name, err := s.store.Heartbeat(payload, bearerToken(r), s.requireToken)
		if err != nil {
			writeJSON(w, authenticationStatus(err), map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "node": name})
		return
	}
	if path == "logs" && r.Method == http.MethodPost {
		payload, err := readJSON(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		if err := s.store.LogEvent(payload, bearerToken(r), s.requireToken); err != nil {
			writeJSON(w, authenticationStatus(err), map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
		return
	}
	if path == "log-bundles" && r.Method == http.MethodPost {
		s.handleLogBundle(w, r)
		return
	}
	if strings.HasSuffix(path, "/diagnose") && r.Method == http.MethodPost {
		if !s.requireAdmin(w, r) {
			return
		}
		name := strings.TrimSuffix(path, "/diagnose")
		diag, err := s.store.Diagnose(name, s.diagnostics)
		if err != nil {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusCreated, diag)
		return
	}
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	if !s.requireAdmin(w, r) {
		return
	}
	node, ok := s.store.NodeDetail(path)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	writeJSON(w, http.StatusOK, node)
}

func (s *Server) handleLogBundle(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, s.maxUpload+(1<<20))
	if err := r.ParseMultipartForm(s.maxUpload); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	nodeName := firstNonEmpty(r.FormValue("nodeName"), r.FormValue("node"))
	if nodeName == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "nodeName is required"})
		return
	}
	if err := validateNodeName(nodeName); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	if s.requireToken {
		if err := s.store.ValidateNodeCredential(nodeName, bearerToken(r)); err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": err.Error()})
			return
		}
	}
	file, header, err := r.FormFile("bundle")
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bundle file is required"})
		return
	}
	defer file.Close()

	safeNode := sanitizePathName(nodeName)
	safeName := sanitizePathName(header.Filename)
	if safeName == "" {
		safeName = "bundle.tar.gz"
	}
	relative := filepath.Join("log-bundles", safeNode, time.Now().UTC().Format("20060102T150405.000000000Z")+"-"+safeName)
	target := filepath.Join(s.artifactsDir, relative)
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	size, copyErr := io.Copy(out, io.LimitReader(file, s.maxUpload+1))
	closeErr := out.Close()
	if copyErr != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": copyErr.Error()})
		return
	}
	if closeErr != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": closeErr.Error()})
		return
	}
	if size > s.maxUpload {
		_ = os.Remove(target)
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "log bundle exceeds upload limit"})
		return
	}
	payload := map[string]any{
		"nodeName":  nodeName,
		"file":      relative,
		"sizeBytes": size,
		"url":       "/artifacts/" + filepath.ToSlash(relative),
	}
	if err := s.store.RecordLogBundle(nodeName, bearerToken(r), "uploaded log bundle", payload, s.requireToken); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusCreated, payload)
}

func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	if !s.requireAdmin(w, r) {
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	writeJSON(w, http.StatusOK, s.store.Events(limit))
}

func (s *Server) handleImages(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	switch r.Method {
	case http.MethodGet:
		writeJSON(w, http.StatusOK, s.store.Images())
	case http.MethodPost:
		payload, err := readJSON(r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		id, err := s.store.CreateImagePlan(payload)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusCreated, map[string]any{"ok": true, "id": id})
	default:
		methodNotAllowed(w)
	}
}

func (s *Server) handleTokens(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	if !s.requireAdmin(w, r) {
		return
	}
	payload, err := readJSON(r)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	ttl, _ := intAt(payload, "ttlSeconds")
	if ttl == 0 {
		ttl = 3600
	}
	if ttl < 60 || ttl > 86400 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "ttlSeconds must be between 60 and 86400"})
		return
	}
	nodeName := stringAt(payload, "nodeName")
	if nodeName == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "nodeName is required"})
		return
	}
	token, err := s.store.CreateToken(nodeName, ttl)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusCreated, token)
}

func (s *Server) handleArtifactIndex(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	if !s.requireAdmin(w, r) {
		return
	}
	artifacts, err := scanArtifacts(s.artifactsDir)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, artifacts)
}

func (s *Server) handleArtifacts(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	if !s.requireAdmin(w, r) {
		return
	}
	rel := strings.TrimPrefix(r.URL.Path, "/artifacts/")
	root, err := filepath.Abs(s.artifactsDir)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	target, err := filepath.Abs(filepath.Join(root, rel))
	if err != nil || (target != root && !strings.HasPrefix(target, root+string(os.PathSeparator))) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	http.ServeFile(w, r, target)
}

func readJSON(r *http.Request) (map[string]any, error) {
	defer r.Body.Close()
	data, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if len(data) == 0 {
		return map[string]any{}, nil
	}
	var payload map[string]any
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, err
	}
	return payload, nil
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	encoder := json.NewEncoder(w)
	encoder.SetIndent("", "  ")
	_ = encoder.Encode(value)
}

func methodNotAllowed(w http.ResponseWriter) {
	writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
}

func (s *Server) requireAdmin(w http.ResponseWriter, r *http.Request) bool {
	if s.adminToken == "" {
		return true
	}
	provided := bearerToken(r)
	if len(provided) == len(s.adminToken) && subtle.ConstantTimeCompare([]byte(provided), []byte(s.adminToken)) == 1 {
		return true
	}
	writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "admin bearer token is required"})
	return false
}

func bearerToken(r *http.Request) string {
	value := r.Header.Get("Authorization")
	if !strings.HasPrefix(value, "Bearer ") {
		return ""
	}
	return strings.TrimSpace(strings.TrimPrefix(value, "Bearer "))
}

func authenticationStatus(err error) int {
	if strings.Contains(err.Error(), "token") {
		return http.StatusUnauthorized
	}
	return http.StatusBadRequest
}

func logMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(os.Stderr, "%s %s %s\n", r.RemoteAddr, r.Method, r.URL.Path)
		next.ServeHTTP(w, r)
	})
}

func intAt(input map[string]any, path ...string) (int, bool) {
	var cursor any = input
	for _, part := range path {
		mapping, ok := cursor.(map[string]any)
		if !ok {
			return 0, false
		}
		cursor = mapping[part]
	}
	switch value := cursor.(type) {
	case float64:
		return int(value), true
	case int:
		return value, true
	default:
		return 0, false
	}
}

func scanArtifacts(root string) ([]Artifact, error) {
	var artifacts []Artifact
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	err = filepath.WalkDir(absRoot, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			return nil
		}
		ext := strings.ToLower(filepath.Ext(entry.Name()))
		if ext != ".iso" && ext != ".gz" && ext != ".img" && ext != ".qcow2" {
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		sum, err := fileSHA256(path)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(absRoot, path)
		if err != nil {
			return err
		}
		artifacts = append(artifacts, Artifact{
			Name:      entry.Name(),
			Path:      filepath.ToSlash(rel),
			URL:       "/artifacts/" + filepath.ToSlash(rel),
			Kind:      artifactKind(entry.Name()),
			SizeBytes: info.Size(),
			SHA256:    sum,
			ModTime:   info.ModTime().UTC(),
		})
		return nil
	})
	return artifacts, err
}

func fileSHA256(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func artifactKind(name string) string {
	lower := strings.ToLower(name)
	switch {
	case strings.HasSuffix(lower, ".iso"):
		return "iso"
	case strings.HasSuffix(lower, ".qcow2"):
		return "disk"
	case strings.HasSuffix(lower, ".img"):
		return "image"
	case strings.HasSuffix(lower, ".tar.gz"):
		return "overlay"
	case strings.HasSuffix(lower, ".gz"):
		return "archive"
	default:
		return "file"
	}
}

func sanitizePathName(value string) string {
	value = strings.TrimSpace(value)
	value = strings.ReplaceAll(value, "\\", "-")
	value = strings.ReplaceAll(value, "/", "-")
	value = strings.ReplaceAll(value, "..", "-")
	value = strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_' || r == '.' {
			return r
		}
		return '-'
	}, value)
	return strings.Trim(value, "-")
}
