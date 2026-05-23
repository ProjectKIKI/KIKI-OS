package model

// BosPackage represents a BaseOS package entry in the local DB.
type BosPackage struct {
	Name         string              `json:"name" yaml:"name"`
	Version      string              `json:"version" yaml:"version"`
	Arch         string              `json:"arch" yaml:"arch"`
	Summary      string              `json:"summary" yaml:"summary"`
	Release      string              `json:"release" yaml:"release"`
	Dependencies PackageDependencies `json:"dependencies,omitempty" yaml:"dependencies,omitempty"`
}

func (p BosPackage) GetName() string {
	return p.Name
}

func (p BosPackage) GetRuntimeDependencies() []string {
	deps := p.Dependencies
	deps.Normalize()
	return deps.Runtime
}
