# Carbon-aware orchestrator

Controls all 15 workloads of the GreenOps challenge.  Code: `core.py` (pure decisions),
`controller.py` (loop, quota handling, VM lifecycle), `cloud.py` (Exoscale binding + grid API),
`run.py` (CLI).  Tests: `tests/test_orchestrator.py` with an offline stand-in simulator
(`tests/fake_env.py`, synthetic electricity - never real or run data).
Policy benchmark: `python tests/bench.py` (many random synthetic grids, see below).

## Run

Credentials for one run (key, secret, cloud and grid endpoints) come from a file that
`run.py` finds by itself: the nearest `greenops.env`, `greenops-*.env` or `.env`, searched
for in the working directory and in every parent.  Drop the portal's download in the
repository root once and it serves the main checkout and every git worktree beneath it, and
a mounted checkout serves a container with no `-e` plumbing at all.  Real environment
variables still win over the file, so an organizer rerun that injects credentials properly
is unaffected, and `.dockerignore` drops every env file so none is ever baked into an image.

```sh
cp ~/Downloads/greenops-<run id>.env .   # or into any parent directory
make env                                 # which file is in use; secrets shown as a length only
make run                                 # live run
make cleanup                             # delete leftovers after a crash
make test                                # Go + Python gate

make docker-build                        # submission image
make docker-run                          # that image, env file mounted read-only
make docker-cleanup
make docker-dev                          # this checkout mounted: no rebuild between edits
```

Inside one directory the most recently written file wins, so next run's download simply
takes over and nothing has to be cleaned up; `make env` lists the files it passed over.
`--env-file PATH` names one explicitly, `--no-env-file` ignores files entirely and
`GREENOPS_ENV_FILE` sets the default.  `DOCKER=docker` overrides the `sudo docker` default
and `ARGS='…'` passes flags through to the orchestrator.

Levers for comparing two runs:

```sh
make run ARGS="--no-carbon"        # baseline: never pause, ignore forecasts
make run ARGS="--no-park"          # stop instead of delete-and-restart
make run ARGS="--no-duty"          # rank on the flat forecast mean (policy 2)
make run ARGS="--no-scale"         # add workers only to save a deadline (policy 3)
make run ARGS="--no-prestage"      # do not stage ahead of the next clean stretch (policy 8)
make run ARGS="--no-reserve-best"  # reserve only the minimum VM for single-family GPU jobs
python -m orchestrator.run plan    # offline: legal options per workload
```

## Policy

1. **Legality first**: every placement is checked against country allow/deny lists, EU/CH/DACH
   residency, allowed profiles/families and GPU memory, twice (ranking and right before `create`),
   also for every restart after parking.
2. **Placement**: cheapest legal (zone, profile) = PUE x intensity x energy of the remaining work
   (active watts) plus boot/staging/output (idle watts); prefers plans that use <=55 % of the
   window (room to pause), smallest VM only on true ties (<=0.5 %): the mega CPU VM is the most
   efficient per vCPU-hour. The compute phase is priced at the mean of the *cleanest hours a plan
   with that duty cycle can occupy*, not at the flat 24 h mean, because timing (3) keeps the VM off
   during the dirty ones. A volatile grid and a faster VM are therefore valued for what they really
   buy, the freedom to skip dirty hours, instead of needing a blind tie-break. `--no-duty` reverts
   to the flat mean.
3. **Timing**: a VM runs in the cleanest `q` share of the next 24 h, `q` = needed time / time left
   x 1.25. Little slack => run non-stop, scale out to more workers if behind schedule. Where a
   workload allows several workers, workers are also added purely for carbon: `n` workers cost
   `1 + sync_overhead x (n - 1)` times the energy but finish in roughly `1/n` of the time, which
   pays whenever the forecast spread is wider than that penalty (4 % minimum gain, never while
   quota is short). `--no-scale` restricts scaling to deadline rescue.
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
6. **Quota reservation**: workloads with less slack that release soon keep room reserved. A
   workload whose every legal option draws on one GPU family (w-08, w-09) has no fallback if those
   cards are taken, so the plan it actually wants is reserved rather than the bare minimum: GPU
   jobs are the energy-dense ones and lose the most when squeezed onto a single card and forced
   through the dirty hours. `--no-reserve-best` reserves the minimum for them too.
7. **Cleanup**: VMs are deleted when `final_output_delivered` is true (failed deletes are retried);
   a tiny unbound VM starts the clock and is deleted immediately so real workloads can wait for a
   clean hour. The loop polls every 0.5 s wall time (~6 virtual minutes at 720x).
8. **Staging**: boot and input staging draw only idle watts but consume wall clock, so letting them
   eat the first clean hours pushes the compute phase into dirtier ones. The VM is created one
   staging length before the next clean stretch and is never paused until staging is done (held off
   while quota is short, where an early VM would block someone else). `--no-prestage` disables it.

Only this run's published forecast is used; nothing is cached across runs or embedded.

### Duty-cycle pricing: measure it before trusting it

An earlier form of policy 2 was already tried live on this scenario and **lost**: 27.83 kg
CO2e / 21467 points against 23.87 kg / 21907 for the same orchestrator without it, while the
offline sim had predicted -3.1 % over 20 paired seeds (branch `reliability-on-epsilon`,
commit `dc4349d`, reverted in `a297c87`). Two flaws were named:

1. it priced the cheapest `ceil(work_h)` *hours* of a 24 h forecast, so any plan needing 24 h
   or more fell back to the flat mean with no selectivity at all, while a shorter plan in the
   same family still got a discount, even though the long plan is also paused through dirty
   hours across its 70 to 100 h window;
2. it priced the **best case**, so it favoured whichever option had the widest gap between
   the optimistic estimate and what policy 3's conservative gate actually captures, and paid
   a worse PUE to chase a dip it then only partly caught.

The form here prices a *share* of the window (`duty = work_h / usable_h x 1.25`) rather than an
absolute hour count, which removes flaw 1, and the 1.25 factor is a first correction for flaw 2.
Neither is a measurement. Compare `make run` against `make run ARGS="--no-duty"` on a real run
before treating it as an improvement, and prefer the live number over `tests/bench.py`:
the synthetic sinusoids demonstrably disagreed with the real series on exactly this change.

## Offline benchmark (synthetic grids only)

`tests/bench.py` replays the controller against many randomly generated electricity curves
(levels, daily cycles, multi-day swings, noise, forecast error) and the documented accounting:
idle watts for boot/staging/output, active watts for compute, nothing while stopped, lifecycle
kg/h for every non-stopped hour, uncheckpointed work lost on delete. Result vs. the previous
version (48 seeds each, no deadline missed in any run):

| synthetic grid family            | usage CO2 v1 | usage CO2 v2 | change |
|----------------------------------|-------------:|-------------:|-------:|
| daily cycle (`fake_env.py`)      | 15.26 kg     | 13.81 kg     | -9.5 % |
| random levels/cycles/weather     | 10.61 kg     | 10.12 kg     | -4.4 % |

Lifecycle (not scored) rises by ~1 % because parked jobs boot and stage again.
These numbers come from invented grids and only show the direction of the change; the real
result depends on the run's electricity.

## Archived: run setup before the credentials file

Superseded by **Run** above; kept because the flags and the `--config` path still work.
Every run handed out a fresh key, secret and pair of endpoints, and these had to be pasted
into the shell one `export` at a time, which mixes runs together sooner or later and only
fails once the clock is already going.

```sh
export GREENOPS_GRID_ENDPOINT='…/runs/<id>/grid/v4'   # from "API credentials" of THIS run
export GREENOPS_GRID_SECRET='…'
python -m orchestrator.run run --config greenops-exo.json
python -m orchestrator.run cleanup --config greenops-exo.json   # delete leftovers after a crash
python -m orchestrator.run plan                                  # offline: legal options per workload
python -m orchestrator.run run --no-carbon                       # baseline for your comparison
python -m orchestrator.run run --no-park                         # v1 behaviour: stop instead of park
```

A `greenops-exo.json` that exists still supplies the cloud credentials, and the env file then
only contributes the grid endpoint and secret. Exported variables always beat the file, so this
form keeps working unchanged next to the new one.
