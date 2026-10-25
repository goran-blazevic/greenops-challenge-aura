#!/usr/bin/env python3
"""Read the current run's published forecast, never a historical external feed."""
import json
import os
from urllib.parse import urlparse
import requests
from static import read_account

account = read_account(os.environ.get("GREENOPS_CONFIG", "greenops-exo.json"))
endpoint = os.environ["GREENOPS_GRID_ENDPOINT"].rstrip("/")
cloud, grid = urlparse(account["endpoint"]), urlparse(endpoint)
run_prefix = cloud.path.split("/cloud/")[0]
if (grid.scheme, grid.netloc, grid.path) != (cloud.scheme, cloud.netloc, run_prefix + "/grid/v4"):
    raise SystemExit("Electricity endpoint must belong to this cloud run")
r = requests.get(endpoint + "/carbon-intensity/forecast",
                 params={"zone": os.environ.get("GREENOPS_AREA", "DE"), "horizonHours": 24},
                 headers={"auth-token": os.environ["GREENOPS_GRID_SECRET"]}, timeout=20,
                 allow_redirects=False)
r.raise_for_status()
print(json.dumps(r.json(), indent=2))
