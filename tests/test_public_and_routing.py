"""Behavioral starter guardrails; all request fixtures are invented."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/python"))
from static import check_endpoint


class PublicAndRouting(unittest.TestCase):
    def test_discovery_cannot_escape_run_or_contact_cloud(self):
        base = "http://localhost:8080/runs/fictional-run/cloud/v2"
        check_endpoint(base)
        check_endpoint("http://localhost:8080/runs/fictional-run/cloud/ch-gva-2/v2", base)
        for url in ["https://api-at-vie-1.exoscale.com/v2", "https://example.invalid/v2",
                    "http://localhost:8080/runs/other/cloud/v2",
                    "http://elsewhere.invalid/runs/fictional-run/cloud/v2",
                    base + "?endpoint=other"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                check_endpoint(url, base)

    def test_public_exports_have_only_public_catalog_and_matching_hashes(self):
        catalog = json.loads((ROOT / "challenge/catalog.json").read_text())
        self.assertEqual(len(catalog["workloads"]), 15)
        self.assertRegex(catalog["scenario_id"], r"^pack-[a-f0-9]{10}$")
        self.assertEqual(sum(int(w["required_work"]) for w in catalog["workloads"] if w["kind"] == "cpu"), 14600)
        plan = json.loads((ROOT / "examples/static-plan.json").read_text())
        self.assertEqual(plan["scenario_id"], catalog["scenario_id"])
        research = next(w for w in catalog["workloads"] if w["id"] == "w-01-dach-research")
        self.assertEqual(research["required_work"], "1000")
        self.assertEqual(research["work_unit"], "vcpu_hour")
        self.assertNotIn("hourly_intensity", catalog)
        self.assertNotIn("electricity", catalog)
        self.assertEqual(catalog["impact_model"], "exoscale-lca-v1")
        self.assertTrue(all("lifecycle_kg_per_hour" in p for p in catalog["profiles"]))
        manifest = json.loads((ROOT / "challenge/manifest.json").read_text())
        self.assertEqual(manifest["scenario_id"], catalog["scenario_id"])
        for name, digest in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / "challenge" / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(catalog["workloads"], json.loads((ROOT / "challenge/workloads.json").read_text()))
        for workload in catalog["workloads"]:
            if workload["max_workers"] == 1:
                self.assertEqual(workload["sync_overhead"], "0", workload["id"])

    def test_export_refuses_unexpected_private_fields(self):
        spec = importlib.util.spec_from_file_location("export_public", ROOT / "scripts/export_public.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(ValueError):
            module.export({"hourly_intensity": {"fictional": [1]}}, ROOT / ".local/should-not-export")
        with self.assertRaises(ValueError):
            module.export({"impact_model": "unknown"}, ROOT / ".local/should-not-export")


if __name__ == "__main__":
    unittest.main()
