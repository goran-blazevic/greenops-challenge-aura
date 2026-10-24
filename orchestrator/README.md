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

## Offline benchmark (synthetic grids only)

`tests/bench.py` uses invented grids and the simulator's public accounting model. Latest paired 24-seed check after horizon-aware scoring, selective parking and GPU quota reservations:

| artificial grid | mean electricity | mean lifecycle | mean total | maximum total | missed / leftover VMs |
|---|---:|---:|---:|---:|---:|
| random levels/cycles/weather | 9.62 kg | 9.38 kg | 19.00 kg | 27.67 kg | 0 / 0 |
| daily-cycle test grid | 13.55 kg | 9.40 kg | 22.96 kg | 24.59 kg | 0 / 0 |

The benchmark does **not** guarantee the live run will be below 20 kg. The worst synthetic cases exceed that target.

## Run-local learning database

The CLI creates `.local/greenops-memory-<run-hash>.sqlite3` by default; `--memory-db` overrides the location. It persists forecast points fetched from that run, published history, workload status, actions and horizon-bucket forecast residuals. It learns calibration only after the run publishes the corresponding observation. The SQLite metadata binds the DB to the exact cloud endpoint hash; using it with another run is rejected. No secret is written to SQLite. Do not transfer the DB or its forecasts between runs.
