# Carbon-aware orchestrator

Controls all 15 workloads of the GreenOps challenge.  Code: `core.py` (pure decisions),
`controller.py` (loop, quota handling, VM lifecycle), `cloud.py` (Exoscale binding + grid API),
`run.py` (CLI).  Tests: `tests/test_orchestrator.py` with an offline stand-in simulator
(`tests/fake_env.py`, synthetic electricity - never real or run data).
Policy benchmark: `python tests/bench.py` (many random synthetic grids, see below). Rechecked in this workspace on 48 paired seeds.

## Run (inside the starter container, fresh run credentials in `greenops-exo.json`)

```sh
export GREENOPS_GRID_ENDPOINT='…/runs/<id>/grid/v4'   # from "API credentials" of THIS run
export GREENOPS_GRID_SECRET='…'
python -m orchestrator.run run --config greenops-exo.json
python -m orchestrator.run cleanup --config greenops-exo.json   # delete leftovers after a crash
python -m orchestrator.run plan                                  # offline: legal options per workload
python -m orchestrator.run run --no-carbon                       # baseline for your comparison
python -m orchestrator.run run --no-park                         # v1 behaviour: stop instead of park
```

## Policy

1. **Legality first**: every placement is checked against country allow/deny lists, EU/CH/DACH
   residency, allowed profiles/families and GPU memory, twice (ranking and right before `create`),
   also for every restart after parking.
2. **Placement**: cheapest legal (zone, profile) = PUE x mean forecast intensity x energy of the
   remaining work (active watts) plus boot/staging/output (idle watts); prefers plans that use
   <=55 % of the window (room to pause), smallest VM only on true ties (<=0.5 %): the mega CPU VM is the most efficient per vCPU-hour.
3. **Timing**: a VM runs in the cleanest `q` share of the next 24 h, `q` = needed time / time left
   x 1.25. Little slack => run non-stop, scale out to more workers if behind schedule.
4. **Quota pressure** (stopped VMs keep their quota): while held VMs plus soon-released jobs exceed
   the quotas, holders keep running - *unless* pausing saves more than 0.1 g CO2e per hour per vCPU
   of quota the VM keeps blocked (intensity above the job's own run threshold x watts x PUE / vCPUs).
   That lets energy-dense GPU VMs skip dirty hours while cheap CPU VMs keep the quota moving.
   No voluntary pause at all while a waiting job with < 20 h slack does not fit ("crunch").
5. **Parking**: jobs that checkpoint at least every 30 min, stage <= 15 min input and do not restart
   from zero (w-04, w-05, w-13, w-14) are *deleted* instead of stopped when the forecast says they
   would wait >= 4 h. They hold no quota while waiting and restart in the then-cleanest legal zone;
   at most one checkpoint interval of work is redone. Never used with < 12 h slack. A restarted VM
   runs >= 2 h before it may be parked again, a parked job is not pushed back in by quota pressure,
   and it waits for room for its efficient VM instead of falling back to a less efficient size.
6. **Quota reservation**: workloads with less slack that release soon keep room reserved.
7. **Cleanup**: VMs are deleted when `final_output_delivered` is true (failed deletes are retried);
   a tiny unbound VM starts the clock and is deleted immediately so real workloads can wait for a
   clean hour. The loop polls every 0.5 s wall time (~6 virtual minutes at 720x).

Only this run's published forecast is used; nothing is cached across runs or embedded.

## v6 changes and evidence

v6 = v2 policy plus:
* input staging is priced at active watts (the simulator charges staging as busy work; this matters for 2 h GPU staging),
* GPU profile choice prices compute at the cleanest hours of this run's current 24 h forecast,
* zone choice for long jobs uses up to 72 h of this run's already-published history (was 24 h),
* voluntary pauses are blocked when a waiting CPU job has < 14 h slack, or a waiting GPU job < 18 h slack (v2: 20 h for both).

Replay with live-matched accounting (staging at active power) over 5 polling cadences x 4 seeds = 20 runs:

| version | mean total | worst total | mean electricity | missed |
|---|---:|---:|---:|---:|
| v2 / v4 | 22.61 kg | 23.20 kg | 13.23 kg | 0 |
| v5 | 22.45 kg | 23.10 kg | 13.04 kg | 0 |
| v6 | 22.26 kg | 22.28 kg | 12.88 kg | 0 |

The replay reproduces live results (v2 live 22.41-22.51 kg; v5 live 23.13 kg vs replay worst 23.10 kg). 96 synthetic grids: no new deadline misses vs v2.
Below 20 kg is not reachable with a 24 h forecast in this scenario: the German grid is dirty for the first ~70 h and clean only afterwards, and the 320 vCPU quota limits when the large GPU job can start.

## Run-local learning database

The CLI creates `.local/greenops-memory-<run-hash>.sqlite3` by default; `--memory-db` overrides the location. It persists forecast points fetched from that run, published history, workload status, actions and horizon-bucket forecast residuals. It learns calibration only after the run publishes the corresponding observation. The SQLite metadata binds the DB to the exact cloud endpoint hash; using it with another run is rejected. No secret is written to SQLite. Do not transfer the DB or its forecasts between runs.
