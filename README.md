# GreenOps Challenge starter

Build a program that chooses when and where cloud workloads run, and reduce their
electricity emissions. **Your code runs on your computer and controls our simulator through
APIs. The website shows its progress and results.**

Start with this demo: it schedules one CPU workload and one GPU workload. Then
extend it to schedule all 15 workloads within 120 simulated hours.


## Carbon-aware all-workload controller

The recommended entrypoint is `python -m orchestrator.run run --config greenops-exo.json`. It controls all 15 workloads: legal profile/zone selection, run-scoped forecast scheduling, deadline-aware quota reservation and scale-out, selective parking for checkpointable jobs, and deletion after final delivery. This replaces the older single-plan Python script.

### Run it

Use a **fresh simulation run** and matching cloud and grid credentials. In PowerShell from the extracted project root:

```powershell
$env:GREENOPS_GRID_ENDPOINT = Read-Host "Grid endpoint from this run"
$secure = Read-Host "Grid secret from this run" -AsSecureString
$env:GREENOPS_GRID_SECRET = (New-Object System.Net.NetworkCredential("", $secure)).Password
docker run --rm -it -e GREENOPS_GRID_ENDPOINT -e GREENOPS_GRID_SECRET -v "${PWD}:/workspace" ghcr.io/exogmi/greenops-challenge-starter-kit:latest
```

Inside the container:

```sh
python -m orchestrator.run plan
python -m orchestrator.run run --config greenops-exo.json
```

### Per-run SQLite memory

On launch, the controller creates `.local/greenops-memory-<run-hash>.sqlite3` (override with `--memory-db`). It records forecasts fetched from this run, observations only after this run publishes them, workload status, controller actions, and forecast errors by horizon bucket. It adjusts later forecasts only from this run’s own observed forecast errors. It stores no credentials and refuses to open if the endpoint hash belongs to another run. **Never copy the database to a different run**; competition rules prohibit transferring run-specific forecast data or learned schedules. The project’s `.local` folder is Git-ignored. Reuse the same DB for restarts of that run; a new run automatically gets a new DB filename.

Keep the process open until it reports all workloads delivered and VMs cleaned up. The run receipt is also endpoint-scoped. After a crash, resume with the same run credentials. For orchestrator-owned VM cleanup after an interruption: `python -m orchestrator.run cleanup --config greenops-exo.json`. Do not use old credentials that were exposed in chat.

### Score-aware scheduling (v11)

v11 keeps the score-v2 scheduler and sets `--score-aware-beta 0.05` as the default, matching the command used for Aura's task13 run. It reads public per-workload reference energies from `challenge/rules.json` and the workload's current estimated electricity emissions from this run's currently published forecast, then computes the score's marginal value per gram. The beta adjusts each workload's run margin so cleaner forecast hours are preferentially offered to work where they are worth more leaderboard points. It does not read or store future data. Pass `--score-aware-beta 0` to restore v9 scheduling exactly.

Aura's task13 run, using beta 0.05, scored 22,087.47 with all 15 workloads delivered, 12.796445 kg electricity emissions and 21.902045 kg total impact. That's the best reported Aura score so far. **It does not prove beta 0.05 caused the gain:** replaying the same task13 data does not reproduce a consistent score advantage over beta 0, and the grid/polling variation between real attempts is material. The setting is retained as a measured candidate, not a win guarantee.

All 32 tests pass. Replay comparisons are approximate, depend on the polling cadence, and are not a live score. A fresh run is required to test it; do not reuse another run's SQLite memory.

## 1. Download your credentials

Sign in at [greenops.containerstack.net](https://greenops.containerstack.net),
create or join a team, then click **New simulation run**.

Open that run’s **API credentials → Download CLI config** to download
`greenops-exo-<run-id>.json`. The ID is the first 10 characters of your run.
Python, Go and Terraform examples all use this file.
Keep it private; it contains your run’s access keys.

## 2. Get the starter

You need Git and Docker installed on your computer.

```sh
git clone https://github.com/exogmi/greenops-challenge-starter-kit.git
cd greenops-challenge-starter-kit
```

Move the downloaded JSON file into this folder and rename it to
`greenops-exo.json`. It is ignored by Git.

## 3. Open the development environment

Run this in the starter folder:

```sh
docker run --rm -it -v "$PWD:/workspace" \
  ghcr.io/exogmi/greenops-challenge-starter-kit:latest
```

This opens a terminal inside a container with Python, Go and Terraform ready to use.
Your checkout is mounted at `/workspace`; edits on your computer appear there.

## 4. Run the demo

Inside the container, run:

```sh
python examples/python/static.py run --config greenops-exo.json
```

Keep that terminal open and open your run’s dashboard in the website. You should
see one CPU VM and one GPU VM, followed by workload progress. The clock starts
when the first VM is created. The example deletes its VMs after their outputs
are delivered. It schedules **two of the 15 workloads**.

Prefer another tool? Use the same setup and choose the
[Go or Terraform example](docs/EXAMPLES.md) on a fresh run.

## 5. Build your solution

Start by editing `examples/python/static.py` or `examples/go-static/`. The demo’s
fixed placements are in `examples/static-plan.json`; all 15 workload requirements
are in `challenge/workloads.json`.

First schedule all workloads and meet their deadlines. Then use electricity
forecasts to improve when and where they run. Read the
[cloud, work-status and electricity API reference](docs/API.md) as you need it.

For each new attempt, create a fresh run and download its credentials. Python and
Terraform state belongs to one run: use a fresh checkout or
[separate receipt/state files](docs/DEVELOPMENT.md#start-another-attempt).

Use only observations and forecasts published by the run you control, and respect
each workload’s allowed locations. Read the [competition rules](docs/RULES.md)
before building your optimizer. Submit your GitHub repository and reproducible
run instructions through the website when you have a result to submit.

[Native installation and troubleshooting](docs/DEVELOPMENT.md) ·
[Verification](docs/VERIFICATION.md) · [Third-party software](docs/THIRD_PARTY.md)

Platform trouble? [Report a technical problem](mailto:greenops.challenge@exoscale.ch).
