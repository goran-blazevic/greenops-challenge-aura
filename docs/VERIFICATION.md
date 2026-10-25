# Current starter verification

The public repository contains the current workload v5 pack, schemas, API/rules
documentation and static client examples. Catalog, workloads, rules and example
scenario identity were exported through an isolated simulator's public
`/api/catalog` and `/api/rules` endpoints. The manifest pins public asset hashes;
private electricity series, credentials, coupons and simulator state are excluded.

Local Go client tests and the five Python routing, telemetry and export tests
passed using the documented Python binding dependency. The checks validate
scenario/hash consistency, 15 jobs, 14,600 total CPU vCPU-hours, single-worker zero
overhead, request scoping, signed telemetry and refusal of private export fields.

The GitHub Actions source-check and multiarchitecture image workflows validate
and publish this snapshot. Consult their results for its exact commit before
using a newly built image. Participant examples cover two workloads and API
mechanics; they do not establish full-pack completion, optimized impact or
production load capacity. Native Exoscale Terraform-provider lifecycle and
automatic winning-code audits are not claimed.

Use the current API subset in [API.md](API.md), information-access policy in
[RULES.md](RULES.md), and a fresh run matching `challenge/manifest.json`.
