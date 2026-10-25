// A deliberately static baseline using the official egoscale v3 binding.
package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	exo "github.com/exoscale/egoscale/v3"
	"github.com/exoscale/egoscale/v3/credentials"
)

type account struct{ Name, Key, Secret, Endpoint string }
type config struct {
	DefaultAccount string `json:"defaultaccount"`
	Accounts       []account
}
type placement struct {
	Name               string `json:"name"`
	WorkloadID         string `json:"workload_id"`
	Zone, Family, Size string
}
type plan struct {
	ScenarioID string      `json:"scenario_id"`
	Placements []placement `json:"placements"`
}

func endpoint(raw, reference string) error {
	u, e := url.Parse(raw)
	if e != nil {
		return e
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	if u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (len(parts) != 4 && len(parts) != 5) || parts[0] != "runs" || parts[2] != "cloud" || parts[len(parts)-1] != "v2" {
		return fmt.Errorf("expected a challenge /runs/{id}/cloud[/zone]/v2 endpoint")
	}
	if u.Hostname() == "exoscale.com" || strings.HasSuffix(u.Hostname(), ".exoscale.com") {
		return fmt.Errorf("use challenge endpoints only")
	}
	if reference != "" {
		r, _ := url.Parse(reference)
		if u.Scheme != r.Scheme || u.Host != r.Host || parts[1] != strings.Split(strings.Trim(r.Path, "/"), "/")[1] {
			return fmt.Errorf("discovery escaped configured run")
		}
	}
	return nil
}

type guardedTransport struct{ root string }

func (g guardedTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	root, _ := url.Parse(g.root)
	prefix := strings.TrimSuffix(root.Path, "/v2") + "/"
	if r.URL.Scheme != root.Scheme || r.URL.Host != root.Host || !strings.HasPrefix(r.URL.Path, prefix) {
		return nil, fmt.Errorf("request escaped configured cloud run")
	}
	return http.DefaultTransport.RoundTrip(r)
}
func newClient(a account, target string) (*exo.Client, error) {
	if err := endpoint(target, a.Endpoint); err != nil {
		return nil, err
	}
	return exo.NewClient(credentials.NewStaticCredentials(a.Key, a.Secret),
		exo.ClientOptWithEndpoint(exo.Endpoint(target)),
		exo.ClientOptWithHTTPClient(&http.Client{Timeout: 20 * time.Second, Transport: guardedTransport{a.Endpoint}, CheckRedirect: func(r *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}))
}
func readJSON(path string, dst any) error {
	b, e := os.ReadFile(path)
	if e != nil {
		return e
	}
	return json.Unmarshal(b, dst)
}
func output(v any) { _ = json.NewEncoder(os.Stdout).Encode(v) }

func run() error {
	action := flag.String("action", "deploy", "deploy, run (deploy + poll + cleanup), list, or destroy")
	configPath := flag.String("config", "greenops-exo.json", "downloaded CLI account")
	planPath := flag.String("plan", "examples/static-plan.json", "fixed placements")
	catalogPath := flag.String("catalog", "challenge/catalog.json", "exported public catalog")
	flag.Parse()
	if *action != "deploy" && *action != "run" && *action != "list" && *action != "destroy" {
		return fmt.Errorf("unknown action")
	}
	var cfg config
	if e := readJSON(*configPath, &cfg); e != nil {
		if !os.IsNotExist(e) || *configPath != "greenops-exo.json" {
			return e
		}
		cfg = config{DefaultAccount: "environment", Accounts: []account{{Name: "environment", Key: os.Getenv("EXOSCALE_API_KEY"), Secret: os.Getenv("EXOSCALE_API_SECRET"), Endpoint: os.Getenv("GREENOPS_CLOUD_ENDPOINT")}}}
	}
	var a account
	for _, v := range cfg.Accounts {
		if v.Name == cfg.DefaultAccount {
			a = v
		}
	}
	if e := endpoint(a.Endpoint, ""); e != nil {
		return e
	}
	var p plan
	if e := readJSON(*planPath, &p); e != nil {
		return e
	}
	var catalog struct {
		ScenarioID string `json:"scenario_id"`
	}
	if e := readJSON(*catalogPath, &catalog); e != nil {
		return e
	}
	if p.ScenarioID != catalog.ScenarioID {
		return fmt.Errorf("plan/catalog scenario mismatch")
	}
	ctx := context.Background()
	discovery, e := newClient(a, a.Endpoint)
	if e != nil {
		return e
	}
	zones, e := discovery.ListZones(ctx)
	if e != nil {
		return e
	}
	clients := map[string]*exo.Client{}
	for _, z := range zones.Zones {
		c, e := newClient(a, string(z.APIEndpoint))
		if e != nil {
			return e
		}
		clients[string(z.Name)] = c
	}
	if *action == "list" {
		for zone, c := range clients {
			v, e := c.ListInstances(ctx)
			if e != nil {
				return e
			}
			output(map[string]any{"zone": zone, "instances": v.Instances})
		}
		return nil
	}
	for _, v := range p.Placements {
		c := clients[v.Zone]
		if c == nil {
			return fmt.Errorf("unknown zone %s", v.Zone)
		}
		existing, e := c.ListInstances(ctx)
		if e != nil {
			return e
		}
		matches := []exo.UUID{}
		for _, vm := range existing.Instances {
			if vm.Name == v.Name {
				matches = append(matches, vm.ID)
			}
		}
		if len(matches) > 1 {
			return fmt.Errorf("ambiguous duplicate VM name %s", v.Name)
		}
		if *action == "destroy" {
			for _, id := range matches {
				if _, e := c.DeleteInstance(ctx, id); e != nil {
					return e
				}
				output(map[string]any{"deleted": id})
			}
			continue
		}
		if len(matches) == 1 {
			output(map[string]any{"existing": matches[0], "zone": v.Zone})
			continue
		}
		profiles, e := c.ListInstanceTypes(ctx)
		if e != nil {
			return e
		}
		var profile *exo.InstanceType
		for _, t := range profiles.InstanceTypes {
			if string(t.Family) == v.Family && string(t.Size) == v.Size {
				copy := t
				profile = &copy
			}
		}
		if profile == nil {
			return fmt.Errorf("profile %s.%s unavailable in %s", v.Family, v.Size, v.Zone)
		}
		templates, e := c.ListTemplates(ctx, exo.ListTemplatesWithVisibility(exo.ListTemplatesVisibilityPublic))
		if e != nil {
			return e
		}
		if len(templates.Templates) == 0 {
			return fmt.Errorf("no template")
		}
		binding, _ := json.Marshal(map[string]any{"greenops": map[string]string{"schema_version": "1.0", "workload_id": v.WorkloadID}})
		operation, e := c.CreateInstance(ctx, exo.CreateInstanceRequest{Name: v.Name, InstanceType: profile, Template: &templates.Templates[0], DiskSize: 10, UserData: base64.StdEncoding.EncodeToString(binding)})
		if e != nil {
			return e
		}
		output(operation)
	}
	if *action == "run" {
		ctx, cancel := context.WithTimeout(ctx, 30*time.Minute)
		defer cancel()
		return waitAndCleanup(ctx, a, p, clients)
	}
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, "Baseline failed:", e)
		os.Exit(1)
	}
}
