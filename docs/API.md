# Participant API reference

The simulator implements a bounded Exoscale-compatible cloud API and an Electricity Maps v4-shaped electricity API. Upstream documentation explains the general format; the subset below defines this challenge's support. Use challenge credentials and URLs from **API credentials** for the selected run. Reopening that page retrieves the same saved cloud and grid keys for any current teammate; explicit rotation replaces them.

## Cloud

Official references: [Exoscale API](https://community.exoscale.com/reference/api/), [compute operations](https://community.exoscale.com/reference/api/compute/), [Go binding](https://pkg.go.dev/github.com/exoscale/egoscale/v3), [Python binding](https://github.com/exoscale/python-exoscale). Full product/provider compatibility is not implied.

`GREENOPS_CLOUD_ENDPOINT` is the discovery URL, including `/runs/{run_id}/cloud/v2`. `GET {GREENOPS_CLOUD_ENDPOINT}/zone` returns `zones` with `name` and `api-endpoint`. Use the returned endpoint for that zone, e.g. `/runs/{run_id}/cloud/de-fra-1/v2`. Never synthesize production hostnames or strip the run prefix. Discovery is public read-only; all resource/catalog/operation calls require EXO2 HMAC with the selected run's cloud key and secret. Sign the complete original prefixed request path.

| Method | Path relative to a discovered zone endpoint | Purpose |
|---|---|---|
| GET | `/zone` | Run-local zone discovery |
| GET | `/instance-type`, `/instance-type/{id}` | Available synthetic profiles |
| GET | `/template`, `/template/{id}` | Template inventory |
| GET / POST | `/instance` | List / create VMs |
| GET / DELETE | `/instance/{id}` | Inspect / delete VM |
| PUT | `/instance/{id}:start`, `/instance/{id}:stop` | Resume / stop VM |
| GET | `/operation/{id}` | Poll an admitted lifecycle operation |

The adapter also has an empty deploy-target inventory and basic SSH-key metadata routes; the baseline needs neither SSH keys nor networking/security groups. `GET {cloud discovery endpoint}/instance-type/{id}` is a supported read alias for CLI type resolution. Unsupported products/routes return errors.

VM create returns an operation, not completed work. Supply `name`, `instance-type:{id}`, `template:{id}`, and base64-encoded user-data containing:

```json
{"greenops":{"schema_version":"1.0","workload_id":"COPY_PUBLIC_WORKLOAD_ID"}}
```

The simulator interprets this binding; it never executes cloud-init. First accepted VM creation starts the run clock. VMs can be allocated before their workload release and wait until release. An empty binding is idle infrastructure. Quotas count allocated VMs including stopped ones, GPU-associated vCPUs and cards by GPU family. Residency-invalid attempts permanently disqualify the run.

Stopping preserves all local work, including progress since the last checkpoint,
and staged input. Resuming the same VM continues without repeating completed boot
or input staging. Deletion discards uncheckpointed work; `restart_from_zero` jobs
lose that deleted worker's unfinished local contribution. Stopped instances still
reserve workload worker slots as well as their resource quotas. In the production
game, stopped time incurs no electricity or lifecycle allocation.

Use exo **1.95.6**, the pinned tested CLI. The downloaded `greenops-exo-<run-id>.json` contains the account endpoint. Rename it to `greenops-exo.json` in your starter folder for these commands. After checking `/path/to/exo version`, run:

```sh
/path/to/exo -C greenops-exo.json -O json zone
/path/to/exo -C greenops-exo.json -O json compute instance-template list --zone at-vie-1
```

Version 1.76.1 ignores the downloaded endpoint override and reaches the real cloud. Other CLI versions require verification. Current starter bindings are egoscale v3.1.40 and Python `exoscale` 0.16.3. Operation receipts are memory-only; blindly retrying a create after an ambiguous network error can duplicate resources. Inspect existing VMs before retrying.

## Electricity

Upstream [Electricity Maps v4 documentation](https://app.electricitymaps.com/docs) and [carbon forecast](https://app.electricitymaps.com/docs/reference/carbon-intensity/forecast) are useful format references. **Call your run's grid URL, not the live Electricity Maps service.** Our subset has a shorter horizon and explicit publication rules.

`GREENOPS_GRID_ENDPOINT` includes `/runs/{run_id}/grid/v4`. Send the distinct grid secret as `auth-token`. Cloud credentials and the portal session do not authorize this API. Every route below is GET; responses are JSON and `Cache-Control: no-store`.

| Path relative to grid endpoint | Response envelope | Required extra query |
|---|---|---|
| `/carbon-intensity/forecast` | `zone, forecast:[{datetime,carbonIntensity}], updatedAt` | — |
| `/carbon-intensity/latest` | `zone, datetime, carbonIntensity, updatedAt` | — |
| `/carbon-intensity/history` | `zone, history:[{datetime,carbonIntensity,...}], temporalGranularity` | — |
| `/carbon-intensity/past` | One carbon point | `datetime` |
| `/carbon-intensity/past-range` | `zone, data:[carbon points], temporalGranularity` | `start`, `end` (exclusive) |
| `/electricity-mix/forecast` | `zone, data:[{datetime,updatedAt,breakdownType,mix,...}], unit:"MW"` | — |
| `/electricity-mix/latest` | Same `data` envelope, one point | — |
| `/electricity-mix/history` | `zone, history:[mix points], unit:"MW"` | — |
| `/renewable-percentage-level/forecast` | `zone, forecast:[{datetime,level}]` | — |
| `/renewable-percentage-level/latest` | `zone, data:[{datetime,level}]` | — |
| `/renewable-percentage-level/past` | Same `data` envelope | `datetime` |

All requests require `zone`, an electricity area code from the public catalog: AT, BG, CH, DE, ES, FR, HR, IT in the current candidate. These differ from cloud zone slugs. `temporalGranularity=hourly` is the only supported granularity. Forecasts allow `horizonHours=6|24`, default 24; 48/72 are rejected. Past/range times are UTC hour boundaries (e.g. `2025-09-30T00:00:00Z`), with a maximum seven-day range. The caller cannot select `now` or a future forecast issuance time.

Observations appear only after an hourly interval ends plus the publication delay (one hour in the candidate). At run start, latest can therefore be two hours before the start timestamp. History returns the most recent 24 published hours. A future or partly future historical range is rejected in full. Forecasts select only an issued and available vintage as of the run clock. Pausing freezes that information boundary; polling does not advance time.

```sh
curl --fail-with-body --get "$GREENOPS_GRID_ENDPOINT/carbon-intensity/forecast" \
  -H "auth-token: $GREENOPS_GRID_SECRET" \
  --data-urlencode zone=DE --data-urlencode horizonHours=24
```

**FICTIONAL, abbreviated response; these numbers are invented for documentation:**

```json
{
  "zone":"DE",
  "forecast":[{"datetime":"2025-09-30T00:00:00Z","carbonIntensity":180.0}],
  "updatedAt":"2025-09-30T00:00:00Z",
  "temporalGranularity":"hourly",
  "flowTraced":false,
  "provenance":"fictional",
  "accountingBasis":"synthetic_approximate_consumption_mix",
  "emissionFactorType":"lifecycle"
}
```

Carbon intensity is gCO₂e/kWh; mix values are MW, with separate storage charge/discharge and import/export totals. Renewable `level` is `low`, `moderate` or `high`, not a percentage. Carbon metadata states synthetic/estimated lifecycle factors; no measured flow tracing is claimed. Carbon permits only `flowTraced=false` and `emissionFactorType=lifecycle`. Mix permits `breakdownType=normal`; deprecated `flowTraced` is accepted without enabling tracing. `disableCallerLookup` is accepted with an explicit zone; latitude/longitude and IP lookup are unsupported. `disableEstimations=true` and mix `estimationFallback=false` produce no data because these are synthetic inputs.

Errors: 401 missing/wrong/conflicting credentials; 404 unknown route or unavailable/unpublished data; 422 invalid area, unsupported/duplicate query parameter, horizon, granularity or future historical request. Errors use `error.code` and `error.message`. Unsupported families and endpoints (including prices/flows/full renewable percentages) are not implemented. See [participant rules](RULES.md): no cross-run collection or external actuals to build a perfect view of the future.

## Batched work status and explicit cleanup

`GREENOPS_WORK_ENDPOINT` is `/runs/{id}/work/v1`; GET `/status` uses your cloud
EXO2 HMAC key/secret and signs this complete path. It is read-only: no query
parameters or caller-controlled time. The Go and Python `run` examples sign it.
One request returns authoritative virtual time, speed, run state, qualification,
and every workload's surviving progress, output delivery, active VM IDs/zones.
It contains no carbon ledger or future electricity values.

Poll once per wall second; back off on 429 (`Retry-After: 1`). The default work
budget is 5 requests/second, burst 10 per run. Cloud and grid share 20/second,
burst 40. Completion means `final_output_delivered: true`, not compute at 100%.
VMs remain idle and incur carbon until you delete them. Stop retains quota.

```sh
greenops-static -action run -config /path/greenops-exo.json
python3 examples/python/static.py run --config /path/greenops-exo.json
```

These remain static placement demos, now with poll-and-cleanup loops. They delete
only VMs they own, and never change the simulation clock. `deploy` still returns
immediately for manual exploration. The sample plan covers two workloads, not all
15; a full competition controller must schedule the entire public workload pack.

**Fictional abbreviated response:**
```json
{"run_id":"example","virtual_time":"2025-09-29T12:00:00Z","speed_multiplier":720,"state":"RUNNING","qualification":"QUALIFIED","workloads":[{"id":"example-work","state":"succeeded","required_work":"100","completed_work":"100.000000","work_unit":"vcpu_hour","lost_work":"0.000000","final_output_delivered":true,"assignments":[{"vm_id":"example-vm","zone":"at-vie-1","state":"running"}]}]}
```

For organizer reruns the Go/Python examples also accept `EXOSCALE_API_KEY`,
`EXOSCALE_API_SECRET` and `GREENOPS_CLOUD_ENDPOINT` when the default CLI config is
absent. No operator token is needed. A derived participant image can start with:

```dockerfile
FROM ghcr.io/exogmi/greenops-challenge-starter-kit:latest
# Pin the reviewed immutable base digest when submitting your image.
ENTRYPOINT ["greenops-static", "-action", "run", "-plan", "/opt/greenops-starter/examples/static-plan.json", "-catalog", "/opt/greenops-starter/challenge/catalog.json"]
```

This sample still only covers two workloads. Replace it with your full controller.
For Python set any receipt/state path under writable `/tmp` during judging.

## Datacenter metadata and PUE

Read the portal's public `GET /api/catalog` or `challenge/catalog.json` before
planning. Zone records expose `slug`, `name`, `country`, `electricity_area`,
`eu_member`, `location:{city,latitude,longitude,precision:"city"}`, `pue`,
`pue_provenance:"fictional_game_value"` and `fictional`. Coordinates approximate
a city centre, not the facility. All PUE values are fictional game inputs,
including zones whose location is real.

Join a zone slug with `profiles[].zones` for offerings. Profiles include
`gpu_model`, family, cards/VM, per-card VRAM, CPU cores, RAM, throughput and watts.
A CPU-only zone has no matching GPU profile; France has no GPU offering.
RTX PRO 6000 uses family `gpurtx6000pro`, currently available in Frankfurt,
Zagreb and Zurich, further restricted by each workload's residency.

Fictional PUE: Frankfurt 1.20; Munich 1.40; Geneva 1.35; Zurich 1.29; Paris 1.52;
Madrid 1.40; Milan 1.22; Sofia 1.47; Zagreb 1.38; Vienna 1 1.28; Vienna 2 1.23.
Estimate emissions as IT kWh × PUE × forecast gCO2e/kWh. Reported energy already
includes PUE; do not multiply it again. Final scoring uses realized intensity.

Limits remain run-wide: 20 VMs, 320 vCPUs, 4 RTX PRO 6000 cards, 8 cards per other
supported GPU family. Stopped and multi-card VMs retain quota; GPU cores also
count toward the vCPU cap. No separate zone capacity pool is simulated. Schemas
for the catalog, zones and profiles are included under `challenge/schemas/`.
Scoring reference-energy weights remain frozen at their original PUE 1.20
benchmark; actual costs use the new datacenter values. Check the scenario/cohort
in the manifest and run configuration. No electricity time series is distributed.

## Electricity-only scoring

Current public `rules.json` advertises `greenops-score-v2` and
`impact_basis: electricity_usage`. Scores expose `scored_gco2e` for the usage cost
used in points and tie-breaking. `total_gco2e` still includes usage plus lifecycle;
the two component fields retain their meaning. Legacy v1 run/rules responses
remain supported. Use the scenario and cohort matching your run.

The catalog's `scenario_id` is a short opaque workload pack reference (`pack-…`),
matching the website and the exported rules, manifest and example plan. Treat it
as a label, not a description of the workloads or a scoring/content hash. Workload
IDs used to bind VMs remain unchanged.
