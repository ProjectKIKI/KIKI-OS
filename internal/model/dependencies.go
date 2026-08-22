package model

import "strings"

// PackageDependencies describes package relationships.
type PackageDependencies struct {
	Build   []string `json:"build,omitempty" yaml:"build,omitempty"`
	Runtime []string `json:"runtime,omitempty" yaml:"runtime,omitempty"`
}

// Normalize removes empty entries and duplicate names while preserving order.
func (d *PackageDependencies) Normalize() {
	d.Build = normalizeDependencyList(d.Build)
	d.Runtime = normalizeDependencyList(d.Runtime)
}

func normalizeDependencyList(items []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(items))
	for _, item := range items {
		item = strings.TrimSpace(item)
		if item == "" || seen[item] {
			continue
		}
		seen[item] = true
		out = append(out, item)
	}
	return out
}
