package main

import "testing"

func TestNetworkInputValidation(t *testing.T) {
	for _, tc := range []struct {
		name, mode, address, gateway, dns, device string
		blocked                                   bool
	}{
		{"dhcp", "dhcp", "", "", "", "eth0", false},
		{"manual DNS", "dhcp", "", "", "1.1.1.1 2606:4700:4700::1111", "en* eth*", false},
		{"static", "static", "192.168.1.10/24", "192.168.1.1", "1.1.1.1", "ens3", false},
		{"IPv6", "static", "2001:db8::10/64", "fe80::1", "", "eth0", false},
		{"bad prefix", "static", "192.168.1.10/33", "", "", "eth0", true},
		{"missing prefix", "static", "192.168.1.10", "", "", "eth0", true},
		{"gateway subnet", "static", "192.168.1.10/24", "192.168.2.1", "", "eth0", true},
		{"gateway family", "static", "192.168.1.10/24", "fe80::1", "", "eth0", true},
		{"bad DNS", "dhcp", "", "", "999.1.1.1", "eth0", true},
		{"unspecified DNS", "dhcp", "", "", "0.0.0.0", "eth0", true},
		{"missing device", "dhcp", "", "", "", "", true},
		{"injected device", "dhcp", "", "", "", "eth0\nDHCP=no", true},
		{"offline", "off", "", "", "", "", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			plan := NewDefaultPlan("server-core")
			plan.Network.Mode, plan.Network.Address, plan.Network.Gateway = tc.mode, tc.address, tc.gateway
			plan.Network.DNS, plan.Network.InterfaceMatch = tc.dns, tc.device
			result := checkNetwork(plan)
			if (result.State == "BLOCK") != tc.blocked {
				t.Fatalf("unexpected result: %+v", result)
			}
		})
	}
}
