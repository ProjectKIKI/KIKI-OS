package main

import "testing"

func TestAddXorgPackageGroup(t *testing.T) {
	for _, test := range []struct{ input, want string }{
		{"", "xorg-runtime"},
		{"development", "development,xorg-runtime"},
		{"development,xorg-runtime", "development,xorg-runtime"},
	} {
		if got := addPackageGroup(test.input, "xorg-runtime"); got != test.want {
			t.Errorf("addPackageGroup(%q) = %q; want %q", test.input, got, test.want)
		}
	}
}
