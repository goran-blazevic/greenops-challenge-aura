#!/usr/bin/env python3
"""Static CPU/GPU deployment using the official Python Exoscale binding.
No carbon optimization, clock mutation, or stored electricity dataset.
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from exoscale.api.v2 import Client

ROOT = Path(__file__).resolve().parents[2]


def check_endpoint(value, reference=None):
    u = urlparse(value)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("Expected a challenge run URL")
    parts = u.path.strip("/").split("/")
    if len(parts) not in {4, 5} or parts[0] != "runs" or parts[2] != "cloud" or parts[-1] != "v2":
        raise ValueError("Cloud endpoint must be /runs/{id}/cloud[/zone]/v2")
    if u.hostname == "exoscale.com" or u.hostname.endswith(".exoscale.com"):
        raise ValueError("Use challenge endpoints only")
    if reference:
        r = urlparse(reference)
        if (u.scheme, u.netloc) != (r.scheme, r.netloc) or parts[1] != r.path.strip("/").split("/")[1]:
            raise ValueError("Discovered endpoint escaped the configured run")
    return value


def read_account(path):
    if not Path(path).exists() and str(path) == "greenops-exo.json":
        account = {"key": os.environ["EXOSCALE_API_KEY"], "secret": os.environ["EXOSCALE_API_SECRET"], "endpoint": os.environ["GREENOPS_CLOUD_ENDPOINT"]}
        check_endpoint(account["endpoint"])
        return account
    config = json.loads(Path(path).read_text())
    account = next(a for a in config["accounts"] if a["name"] == config["defaultaccount"])
    check_endpoint(account["endpoint"])
    return account


class RunOnlyAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, root):
        self.root = urlparse(root)
        super().__init__()

    def send(self, request, **kwargs):
        target = urlparse(request.url)
        prefix = self.root.path.rsplit("/v2", 1)[0] + "/"
        if ((target.scheme, target.netloc) != (self.root.scheme, self.root.netloc)
                or not target.path.startswith(prefix)):
            raise ValueError("Request escaped the configured cloud run")
        return super().send(request, **kwargs)


def client(account, endpoint=None):
    c = Client(account["key"], account["secret"], url=check_endpoint(endpoint or account["endpoint"], account["endpoint"]))
    guard = RunOnlyAdapter(account["endpoint"])
    c.http_client.mount("http://", guard)
    c.http_client.mount("https://", guard)
    c.http_client.max_redirects = 0
    return c


def discover(account):
    return {z["name"]: check_endpoint(z["api-endpoint"], account["endpoint"])
            for z in client(account).list_zones()["zones"]}


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with open(temp, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    temp.replace(path)


def deploy(account, plan, state_path):
    catalog = json.loads((ROOT / "challenge/catalog.json").read_text())
    if plan["scenario_id"] != catalog["scenario_id"]:
        raise ValueError("Plan and exported catalog scenario differ")
    zones = discover(account)
    state = json.loads(state_path.read_text()) if state_path.exists() else {"endpoint": account["endpoint"], "instances": []}
    if state["endpoint"] != account["endpoint"]:
        raise ValueError("Receipt belongs to another run; use a separate --state path")
    for placement in plan["placements"]:
        c = client(account, zones[placement["zone"]])
        # A deterministic name lets a rerun recover an accepted create after a lost response.
        existing = [v for v in c.list_instances()["instances"] if v["name"] == placement["name"]]
        if len(existing) > 1:
            raise ValueError("Ambiguous duplicate VM name; inspect this run before retrying")
        if existing:
            vm_id = existing[0]["id"]
        else:
            profile = next(p for p in c.list_instance_types()["instance-types"]
                           if p["family"] == placement["family"] and p["size"] == placement["size"])
            template = c.list_templates(visibility="public")["templates"][0]
            binding = {"greenops": {"schema_version": "1.0", "workload_id": placement["workload_id"]}}
            operation = c.create_instance(
                name=placement["name"], instance_type={"id": profile["id"]},
                template={"id": template["id"]}, disk_size=10,
                user_data=base64.b64encode(json.dumps(binding).encode()).decode(),
            )
            vm_id = operation["reference"]["id"]
            # Admission is enough: simulator boot/work progresses independently.
        row = {"id": vm_id, "zone": placement["zone"], "name": placement["name"]}
        if row not in state["instances"]:
            state["instances"].append(row)
        save(state_path, state)
        print(json.dumps(row))


def destroy(account, state_path):
    if not state_path.exists():
        raise ValueError("Receipt missing: list VMs and clean up explicitly; no successful destroy is claimed")
    state = json.loads(state_path.read_text())
    if state["endpoint"] != account["endpoint"]:
        raise ValueError("Receipt belongs to another run")
    zones = discover(account)
    for row in list(state["instances"]):
        c = client(account, zones[row["zone"]])
        if any(v["id"] == row["id"] for v in c.list_instances()["instances"]):
            c.delete_instance(id=row["id"])
        state["instances"].remove(row)
        save(state_path, state)
        print(json.dumps({"deleted": row["id"]}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["deploy", "run", "destroy", "list"])
    p.add_argument("--config", default=os.environ.get("GREENOPS_CONFIG", "greenops-exo.json"))
    p.add_argument("--plan", type=Path, default=ROOT / "examples/static-plan.json")
    p.add_argument("--state", type=Path, default=ROOT / ".local/python-receipt.json")
    args = p.parse_args()
    account = read_account(args.config)
    if args.action in {"deploy", "run"}:
        deploy(account, json.loads(args.plan.read_text()), args.state)
        if args.action == "run":
            from work import wait_and_cleanup
            wait_and_cleanup(account, json.loads(args.plan.read_text()), args.state)
    elif args.action == "destroy":
        destroy(account, args.state)
    else:
        for zone, endpoint in discover(account).items():
            print(json.dumps({"zone": zone, **client(account, endpoint).list_instances()}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, StopIteration, requests.RequestException) as e:
        sys.exit(f"Baseline failed: {e}")
