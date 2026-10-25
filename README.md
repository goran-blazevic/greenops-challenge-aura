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

### Score-aware scheduling (v13)

v13 keeps score-aware beta opt-in (default `0.0`) and softens workload-class run margins: large-input two-worker CPU jobs `0.80`; portable parallel CPU jobs `1.30` / `1.20`; single-worker jobs with long output phases `1.50`; zero-input checkpointable CPU jobs `1.00`. Restart-from-zero jobs retain the existing deadline-safety floor. The long-output rule now covers any single-worker CPU workload with an output phase of at least one hour, rather than only Swiss-residency jobs.

Why: task14 delivered 15/15 but scored 22,086.827, 0.647 points below task13. Electricity emissions rose 13.208 g while lifecycle emissions fell 19.067 g. The largest point losses were w-14 (−8.28), w-09 (−3.18), w-15 (−2.41), and w-11 (−1.83). The task14 memory recorded 218 pause/resume pairs versus 100 in task13; this is a churn signal, not proof that churn caused the score change.

In approximate task13 and task14 replay comparisons, the v13 margin candidate averaged 22,104.4 and 22,104.8 respectively, about 13.5 points above the corresponding v12 replay results. It completed all 15 workloads in the seven cadence variants per run and in 96 seeds for each of two synthetic grid families. These replays are not live leaderboard results. The task14 live result remains the latest confirmed run; v13 has not been tested on a fresh live run and does not guarantee a win.

All 32 unit tests pass. Use fresh run credentials and a new run-scoped SQLite database for each attempt.
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
