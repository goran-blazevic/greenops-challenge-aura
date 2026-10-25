"""Terraform local-exec interpreter: pass paths as environment, never shell text."""
import os
import sys
from pathlib import Path
from static import deploy, destroy, read_account
import json

action = sys.argv[1]
account = read_account(os.environ["GREENOPS_CONFIG"])
state = Path(os.environ["GREENOPS_RECEIPT"])
if action == "deploy":
    deploy(account, json.loads(Path(os.environ["GREENOPS_PLAN"]).read_text()), state)
elif action == "destroy":
    destroy(account, state)
else:
    raise SystemExit("Unknown Terraform lifecycle action")
