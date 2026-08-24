package stage3

import "testing"

func TestSetPathPreservesDocumentChildren(t *testing.T) {
	document := Document{
		"kubernetes": Document{
			"role":    "compute",
			"kubeadm": Document{"action": "join"},
		},
	}
	if err := SetPath(document, "kubernetes.cluster.control_plane_endpoint", "10.0.0.10:6443"); err != nil {
		t.Fatal(err)
	}
	config, err := Decode(document)
	if err != nil {
		t.Fatal(err)
	}
	if config.Kubernetes.Role != "compute" || config.Kubernetes.Kubeadm.Action != "join" || config.Kubernetes.Cluster.ControlPlaneEndpoint != "10.0.0.10:6443" {
		t.Fatalf("path update discarded siblings: %+v", config.Kubernetes)
	}
}
