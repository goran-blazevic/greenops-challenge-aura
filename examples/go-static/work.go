package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	exo "github.com/exoscale/egoscale/v3"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type rateLimited struct{}

func (rateLimited) Error() string { return "rate limited" }

type workStatus struct {
	RunID         string `json:"run_id"`
	Qualification string `json:"qualification"`
	VirtualTime   string `json:"virtual_time"`
	State         string `json:"state"`
	Speed         int    `json:"speed_multiplier"`
	Workloads     []struct {
		ID            string `json:"id"`
		State         string `json:"state"`
		CompletedWork string `json:"completed_work"`
		RequiredWork  string `json:"required_work"`
		Delivered     bool   `json:"final_output_delivered"`
		Assignments   []struct {
			ID   string `json:"vm_id"`
			Zone string `json:"zone"`
		} `json:"assignments"`
	} `json:"workloads"`
}

func workURL(a account) string {
	return strings.TrimSuffix(a.Endpoint, "/cloud/v2") + "/work/v1/status"
}
func pollWork(ctx context.Context, a account) (workStatus, error) {
	var out workStatus
	target := workURL(a)
	u, err := url.Parse(target)
	if err != nil {
		return out, err
	}
	if err = endpoint(a.Endpoint, ""); err != nil {
		return out, err
	}
	req, err := http.NewRequestWithContext(ctx, "GET", target, nil)
	if err != nil {
		return out, err
	}
	expiry := strconv.FormatInt(time.Now().Add(time.Minute).Unix(), 10)
	mac := hmac.New(sha256.New, []byte(a.Secret))
	mac.Write([]byte(strings.Join([]string{"GET " + u.EscapedPath(), "", "", "", expiry}, "\n")))
	req.Header.Set("Authorization", "EXO2-HMAC-SHA256 credential="+a.Key+",expires="+expiry+",signature="+base64.StdEncoding.EncodeToString(mac.Sum(nil)))
	c := http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	resp, err := c.Do(req)
	if err != nil {
		return out, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 429 {
		return out, rateLimited{}
	}
	if resp.StatusCode != 200 {
		return out, fmt.Errorf("work status HTTP %d", resp.StatusCode)
	}
	return out, json.NewDecoder(resp.Body).Decode(&out)
}

// Poll all workload statuses in one call/second. Delete only this plan's VM IDs,
// after successful final output delivery, never merely 100% compute progress.
func waitAndCleanup(ctx context.Context, a account, p plan, clients map[string]*exo.Client) error {
	owned := map[string]*exo.Client{}
	wanted := map[string]bool{}
	for _, v := range p.Placements {
		wanted[v.WorkloadID] = true
		c := clients[v.Zone]
		rows, err := c.ListInstances(ctx)
		if err != nil {
			return err
		}
		for _, vm := range rows.Instances {
			if vm.Name == v.Name {
				owned[string(vm.ID)] = c
			}
		}
	}
	for {
		status, err := pollWork(ctx, a)
		if err != nil {
			if _, ok := err.(rateLimited); ok {
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(time.Second):
					continue
				}
			}
			return err
		}
		output(status)
		remaining := len(wanted)
		for _, w := range status.Workloads {
			if !wanted[w.ID] || !w.Delivered {
				continue
			}
			remaining--
			for _, vm := range w.Assignments {
				if c := owned[vm.ID]; c != nil {
					if _, err := c.DeleteInstance(ctx, exo.UUID(vm.ID)); err != nil {
						return err
					}
					delete(owned, vm.ID)
					output(map[string]string{"deleted_completed_vm": vm.ID})
				}
			}
		}
		if remaining == 0 {
			return nil
		}
		if status.State == "COMPLETED" || status.State == "INVALIDATED" || status.State == "UNAVAILABLE" {
			return fmt.Errorf("run ended before all planned final outputs were delivered")
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(time.Second):
		}
	}
}
