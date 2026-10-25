package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestTelemetryUsesCloudKeyAndRunPath(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/runs/test/work/v1/status" || !strings.HasPrefix(r.Header.Get("Authorization"), "EXO2-HMAC-SHA256 credential=key,") {
			t.Error("wrong run signature")
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"state":"RUNNING","workloads":[]}`))
	}))
	defer s.Close()
	out, err := pollWork(context.Background(), account{Key: "key", Secret: "secret", Endpoint: s.URL + "/runs/test/cloud/v2"})
	if err != nil || out.State != "RUNNING" {
		t.Fatal(err, out)
	}
}
