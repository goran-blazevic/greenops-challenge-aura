package main

import "testing"

func TestDiscoveredEndpointsStayWithinRun(t *testing.T) {
	root := "http://localhost:8080/runs/fictional/cloud/v2"
	if err := endpoint("http://localhost:8080/runs/fictional/cloud/de-fra-1/v2", root); err != nil {
		t.Fatal(err)
	}
	for _, target := range []string{"https://api-de-fra-1.exoscale.com/v2", "http://localhost:8080/runs/other/cloud/v2", "http://elsewhere.invalid/runs/fictional/cloud/v2"} {
		if endpoint(target, root) == nil {
			t.Fatalf("accepted escaped endpoint %s", target)
		}
	}
}
