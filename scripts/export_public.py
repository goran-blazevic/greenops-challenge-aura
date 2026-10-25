#!/usr/bin/env python3
"""Organizer export: fetch only the public catalog, never a private runtime file."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"scenario_id", "provenance", "impact_model", "zones", "profiles", "workloads", "max_vms", "max_vcpus", "max_gpus", "gpu_family_quotas"}


def export(catalog, destination, rules=None):
    if set(catalog) - FIELDS or catalog.get("impact_model", "exoscale-lca-v1") != "exoscale-lca-v1":
        raise ValueError("Unexpected catalog fields or impact model; inspect before public export")
    if rules is not None:
        if (set(rules) != {"rules", "cohort", "enabled", "scenario_id"}
            or set(rules["rules"]) != ({"version", "hash", "reference_energy_kwh", "base_points", "completion_bonus", "reference_gco2e_per_kwh", "local_weight", "shared_weight"} | ({"impact_basis"} if rules["rules"].get("version") == "greenops-score-v2" else set()))
            or rules["rules"]["version"] not in {"greenops-score-v1", "greenops-score-v2"}
            or (rules["rules"]["version"] == "greenops-score-v2" and rules["rules"].get("impact_basis") != "electricity_usage")
            or rules["scenario_id"] != catalog["scenario_id"]):
            raise ValueError("Unexpected scoring rules; inspect before public export")
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "rules.json").write_text(json.dumps(rules, indent=2) + "\n")
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in [("catalog.json", catalog), ("workloads.json", catalog["workloads"])]:
        (destination / name).write_text(json.dumps(data, indent=2) + "\n")
    assets = sorted(p for p in destination.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {
        "schema_version": "1.0", "scenario_id": catalog["scenario_id"],
        "provenance": catalog["provenance"], "score_policy": "frozen " + (rules["rules"]["version"] if rules else "greenops-score-v1") + "; see rules.json",
        "source": "public /api/catalog projection; no electricity series exported",
        "sha256": {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest() for p in assets},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portal", required=True)
    args = parser.parse_args()
    with urlopen(args.portal.rstrip("/") + "/api/catalog", timeout=20) as response:
        catalog = json.load(response)
    with urlopen(args.portal.rstrip("/") + "/api/rules", timeout=20) as response:
        rules = json.load(response)
    export(catalog, ROOT / "challenge", rules)

    # Placements stay static; only the public scenario identity follows exports.
    plan_path = ROOT / "examples/static-plan.json"
    plan = json.loads(plan_path.read_text())
    plan["scenario_id"] = catalog["scenario_id"]
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
