# Development and troubleshooting

[Start with the two-workload demo](../README.md) before using these options.
Your code controls the hosted simulator through its APIs; it runs on your computer
or in your own container.

## Files to edit

- `examples/python/static.py`: Python allocation logic.
- `examples/python/work.py`: work polling and completed-VM cleanup.
- `examples/go-static/`: equivalent Go implementation.
- `examples/static-plan.json`: the demo’s two fixed placements.
- `challenge/catalog.json` and `challenge/workloads.json`: all available resources
  and all 15 workload requirements.

The Docker command in the README mounts your checkout at `/workspace`. Edit those
files on your computer and run them inside the container. The container also
includes an independent copy at `/opt/greenops-starter`; use the mounted checkout
while developing so your edits take effect.

## Start another attempt

Create a fresh simulation run and replace `greenops-exo.json` with its credentials.
Python and Terraform receipts belong to one run. Keep old state/receipts for
cleanup; use a new checkout for the next demo, or select a different Python receipt:

```sh
python examples/python/static.py run --config greenops-exo.json --state .local/second-run-receipt.json
```

For Terraform, use a fresh checkout or separate Terraform state and receipt paths.
The Go example has no local receipt file. Do not run multiple examples against the
same run at the same time; they share deterministic VM names.

## Local simulator addresses

The hosted challenge works with its downloaded URLs. Only organizers running a
local simulator need to consider container networking: `127.0.0.1` inside a
container refers to that container. Use native clients or configure a public
origin reachable from the container before creating local runs. Discovery URLs
and discovered zone endpoints must retain the same origin and run prefix.

Run commands below from the starter repository root.

## Native Go or Python

Go 1.25+ is required by the pinned Go binding. From this checkout:

```sh
go run ./examples/go-static -config greenops-exo.json -action deploy
```

Python 3.10+:

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/python examples/python/static.py deploy --config greenops-exo.json
.venv/bin/python examples/python/static.py list --config greenops-exo.json
.venv/bin/python examples/python/static.py destroy --config greenops-exo.json
```

These clients discover zone URLs, look up type/template IDs, send the workload binding and stop after admission. They do not wait for work completion or automatically remove idle VMs. Inspect progress/impact in the portal; destroy later to stop idle costs. The Python receipt is written after each admitted/recovered VM, including partial deployments. If a response is lost, inspect the run before retrying; the cloud API does not promise durable idempotent create receipts.

The Python grid example requires the matching run's grid URL and secret (download/copy them from the portal):

```sh
export GREENOPS_CONFIG="$PWD/greenops-exo.json"
export GREENOPS_GRID_ENDPOINT='COPY_RUN_GRID_ENDPOINT'
export GREENOPS_GRID_SECRET='COPY_RUN_GRID_SECRET'
.venv/bin/python examples/python/grid.py
```

For a container, pass those exported values with `-e GREENOPS_GRID_ENDPOINT -e GREENOPS_GRID_SECRET`, and set the config path inside the mount. Grid reads do not advance the run clock. Use only this run's currently published data when extending the orchestrator.

## Terraform details

In the container, Terraform and the Python binding are already installed:

```sh
terraform -chdir=examples/terraform init
terraform -chdir=examples/terraform apply -var="config_path=$PWD/greenops-exo.json"
terraform -chdir=examples/terraform destroy -var="config_path=$PWD/greenops-exo.json"
```

For native use, install Terraform **1.13.4**, then include `-var="python=$PWD/.venv/bin/python"` in apply/destroy. The config path is a path, never a secret value in HCL. Keep state and `.local/terraform-receipt.json` until destroy succeeds.

This example uses **`terraform_data` plus the official Python SDK**. It does not use or claim support for the Exoscale Terraform provider, whose simulator endpoint routing remains unverified. It has create/destroy hooks, not full native provider refresh/import/drift reconciliation. If its receipt is lost, cleanup fails visibly: list and remove the VMs explicitly. Changing credentials in the same config file is sufficient after a deliberate rotation; use a separate config/state/receipt for another run.

## Development and publication

```sh
PATH="$PWD/.venv/bin:$PATH" make test
```

For a live lifecycle check, create a fresh empty run and use:

```sh
.venv/bin/python scripts/live_smoke.py --config greenops-exo.json --language python
```

Choose `--language go` or `terraform` on a different fresh run; `--terraform` can point to a pinned binary. The check creates the two VMs, verifies repeat deployment preserves their IDs, then destroys them and checks empty inventories. It intentionally does not claim workload completion.

CI runs Go/Python tests and builds the container for Linux amd64 and arm64. CLI and Terraform archives are checksum pinned; Python dependencies are hash locked; Go dependencies use `go.sum`; base image manifests are digest pinned. Upstream tools keep their licenses; see [third-party notes](THIRD_PARTY.md).

The workflow targets `exogmi/greenops-challenge-starter-kit`. The workflow uses `GITHUB_TOKEN` with package-write permission and publishes `latest` on the default branch, commit tags and release tags. Make the GHCR package public if anonymous participant pulls are required. Run the `Verify anonymous image pull` workflow to pull with an empty Docker credential config and execute CLI, Terraform, Go and Python checks. Verify this workflow before announcing anonymous image availability. Anonymous pull and tool checks passed for the initial image; exact evidence and digest are in the verification document. Rebuild or edit the examples by deriving an image or mounting the checkout; do not bake run credentials or electricity histories into it.

Public assets come from the same platform public projection, with hashes in `challenge/manifest.json`. Organizer refresh:

```sh
python3 scripts/export_public.py --portal https://YOUR_CHALLENGE_ORIGIN
```

The origin above is a placeholder. This exports only public workload/resource metadata. Never add the platform's private `runtime.json`, actuals, complete forecast vintages or balancing/oracle reports.

To deploy, poll for successful final outputs and delete this example's completed
VMs, use `greenops-static -action run` or `python3 examples/python/static.py run`.
See [work telemetry](API.md#batched-work-status-and-explicit-cleanup) and
[frozen ranking and official judging](RULES.md#frozen-v1-ranking-and-official-judging).
