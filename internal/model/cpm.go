package model

// CpmPackage represents a container package entry in the local DB.
type CpmPackage struct {
    Name    string `json:"name"`
    Version string `json:"version"`
    Image   string `json:"image"`
    Summary string `json:"summary"`
}

func (p CpmPackage) GetName() string {
    return p.Name
}
