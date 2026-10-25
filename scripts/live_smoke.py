#!/usr/bin/env python3
"""Run a real baseline lifecycle against one NEW, EMPTY participant run.
No admin access, private datasets or mocks. The config scopes every operation.
"""
import argparse
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/python"))
from static import read_account, discover, client


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--language", choices=["python", "go", "terraform"], required=True)
    p.add_argument("--terraform", default="terraform")
    args = p.parse_args()
    config = args.config.resolve()
    account = read_account(config)
    zones = discover(account)

    def rows():
        return [v for endpoint in zones.values() for v in client(account, endpoint).list_instances()["instances"]]

    if rows():
        raise SystemExit("Use a fresh, empty run; this smoke must not touch existing resources")
    run_tag = hashlib.sha256(account["endpoint"].encode()).hexdigest()[:12]
    receipt = ROOT / ".local" / ("smoke-" + args.language + "-" + run_tag + "-receipt.json")
    receipt.parent.mkdir(exist_ok=True)

    def invoke(action):
        if args.language == "python":
            command = [sys.executable, "examples/python/static.py", action, "--config", str(config), "--state", str(receipt)]
        elif args.language == "go":
            command = ["go", "run", "./examples/go-static", "-config", str(config), "-action", "destroy" if action == "destroy" else "deploy"]
        else:
            command = [args.terraform, "-chdir=examples/terraform", "destroy" if action == "destroy" else "apply", "-auto-approve",
                       "-state=" + str(ROOT / (".local/smoke-terraform-" + run_tag + ".tfstate")),
                       "-var=config_path=" + str(config), "-var=python=" + sys.executable,
                       "-var=receipt_path=" + str(receipt)]
        subprocess.run(command, cwd=ROOT, check=True, timeout=120)

    if args.language == "terraform":
        subprocess.run([args.terraform, "-chdir=examples/terraform", "init", "-backend=false"], cwd=ROOT, check=True, timeout=60)
    try:
        invoke("deploy")
        first = rows()
        profiles = {v["id"]: v for v in json.loads((ROOT / "challenge/catalog.json").read_text())["profiles"]}
        if len(first) != 2 or not any(profiles[v["instance-type"]["id"]]["gpu_count"] for v in first):
            raise AssertionError("Expected the CPU/GPU baseline")
        invoke("deploy")
        if sorted(v["id"] for v in rows()) != sorted(v["id"] for v in first):
            raise AssertionError("Repeating deployment duplicated resources")
    finally:
        if rows():
            invoke("destroy")
    if rows():
        raise AssertionError("Cleanup left allocated resources")
    print(json.dumps({"result": "PASS", "language": args.language, "verified": ["real CPU/GPU admission", "repeat preserves VM IDs", "delete and empty zone inventories"]}))


if __name__ == "__main__":
    main()
