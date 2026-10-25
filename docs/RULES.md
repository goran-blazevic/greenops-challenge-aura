# Current scoring: electricity usage

Current runs use **greenops-score-v2**: points and carbon tie-breaks count electricity
usage emissions only, including boot, staging, idle, unbound and lost-work usage.
Infrastructure & lifecycle emissions remain in the displayed total footprint and
do not affect points. Work progress, delivery bonus, reference weights and quality
formula are retained. Older runs retain their original policy/cohort unless an
organizer explicitly rescores them. Compare scores within the same cohort.

# Participant rules: reactive orchestration

These are the sponsor's competition rules, revised 20 October 2026. The scoring coefficients remain a separate rules-freeze item; these information-access rules apply regardless of the final formula.

## Attempts and submission

You may create as many simulation runs as you want during the challenge. Each run has its own 120-hour simulated window, clock, resource budget, URLs and credentials. Runs are independent attempts, not a way to collect future information for another attempt. There is no total-attempt cap. At most two unfinished runs per team may exist at a time; READY, RUNNING and PAUSED runs count, and completion releases a slot. Operators may configure a retained-run service-capacity limit; it defaults to unlimited and is not a competition attempt allowance.

To claim a winning run, submit the orchestrator source as a GitHub repository. Identify the exact commit SHA, team and run ID, entrypoint, dependency/toolchain versions, configuration format and command to reproduce it. Include all scheduling logic and any input files/models used to make decisions. Make the source accessible to the judges. Do not commit credentials. The organizer must be able to run the code with fresh run-scoped configuration and inspect its data sources. Submission collection and code audit are manual for now; an automated submission/re-execution service is not implemented.

## Allowed information

The orchestrator may read the public workload/resource/residency specifications and its own run's current resource/workload state. **All electricity information used for decisions must come from the run-specific electricity endpoints for the run being controlled.** Use only observations already published and forecasts currently available at that run's simulated time. The server chooses that time; request parameters cannot advance it.

Planning ahead using the current 6- or 24-hour forecast is encouraged. A solver or optimization library is allowed when its inputs obey this rule. You may retain observations and forecasts genuinely obtained earlier in the same run, and react to revised forecasts as time advances.

## Prohibited future knowledge

Do not obtain, embed, reconstruct or use a perfect future electricity table for the scenario. In particular:

- Do not advance another run to harvest observations or later-issued forecasts, then reuse them in an earlier run.
- Do not transfer electricity histories, future schedules derived from those histories, forecast caches, trained scenario-specific lookup tables or run-specific future knowledge between runs or teams.
- Do not preload actuals from public historical datasets, real Electricity Maps/ENTSO-E feeds, organizer files, private runtime JSON, complete forecast collections, balance/oracle outputs or inferred seeds used to generate electricity data.
- Do not replay or hard-code a successful allocation timeline learned from the scenario's future values. General algorithm improvements between attempts are allowed; scenario-specific future-data memorization is not.
- Do not query a different run's electricity endpoint or use a caller-controlled time to bypass publication boundaries.

The reusable image and public starter intentionally contain no electricity time series. Fictional response examples in documentation are illustrative, not decision inputs. Historical dates in the challenge do not grant permission to look up that period's actual emissions.

The platform enforces authenticated run scope and publication-time filtering. It cannot prove what arbitrary participant code remembers or reads elsewhere. Source review and reproducible execution determine compliance; a run that violates these information-access rules cannot win. No automated cheat-detection claim is made.

## Residency and resource rules

A residency-invalid workload placement permanently disqualifies that run, including a rejected wrong-country attempt. Switzerland is outside EU residency. Each workload's country allow/deny lists and profile restrictions also apply. The server rejects VM, vCPU, per-family GPU, worker, memory and availability violations; stopped VMs keep quota until deleted.

All useful compute and final output must meet their deadlines. Idle/setup/lost work can still incur impact. The simulator owns work, time, emissions and score; creating a real VM or executing user-data is unnecessary. All challenge electricity, power, PUE and performance values are fictional or synthetic game inputs, not measured Exoscale footprints.

## Frozen v1 ranking and official judging

Work/carbon policy v1 is frozen: 20,000 base points, 5,000 all-output delivery
bonus, fixed useful-energy weights, 200 gCO₂e/kWh reference, 75% local/25% shared
cost quality. GET public `/api/rules` for exact coefficients/reference energies
and cohort identity. Finalized partial runs may rank; clean partial work can
beat dirtier complete work. Scores finalize at 120 hours. VMs do not stop when
work finishes: poll work status and delete them to avoid idle cost.

The preliminary leaderboard takes each team's best finalized non-disqualified
practice run in one cohort. The official score comes from a fresh organizer
rerun at fixed 720×, after manual source review. Wall-time reactive controllers
need not reproduce the exact practice score. Fixed-placement/heuristic strategies
are legal without querying grid data; forbidden future data remains prohibited.

Submit a GitHub HTTPS repository URL, full immutable commit SHA, claimed practice
run and reproducible Docker build/run instructions through the portal. Keep it
private if desired and grant judges access manually. Revisions are retained;
the organizer announces the deadline. Judging containers receive only their own
cloud/grid/work credentials, run with 2 CPUs/1 GiB RAM and a 15-minute wall limit,
and must support unprivileged execution with `/tmp` writable. Build outside the
timed attempt. Infrastructure retries are recorded and invalidated; no arbitrary
scores are entered. The confirmed prize is €1,000 in Exoscale service credits.

API emulation is powered by [Feint](https://github.com/stephrobert/feint).
The GreenOps simulator owns work, time, quotas, carbon and score.
