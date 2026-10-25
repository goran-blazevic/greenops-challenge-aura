# Aura v12 release notes

## Changes
- Added class-based run margins for long-input, parallel, checkpointable, and restart-sensitive workloads.
- Added a constrained quota-reservation fallback for a released, single-worker, restart-from-zero workload with no checkpoints. The fallback runs only when advisory reservations block all options, the best option fits the controller’s currently observed quota budget, and estimated slack is at most 60 hours.
- Improved the score sensitivity estimate to include the local-workload and run-wide electricity score terms.
- Set `--score-aware-beta` default to 0.0 based on controlled task13 replay comparisons; users can opt into a nonzero value.

## Verification
- 32 unit tests.
- 96 seeds in each of two synthetic grid families, 192 offline simulations total; no missed deliveries in the tested set.
- Seven task13 replay-cadence cases: mean score 22,090.8, versus 22,081.8 for v11 with beta 0. The replay is approximate and is not a live leaderboard result.

## Caveat
The v12 source has not yet been run on a new live simulation. The best confirmed live Aura result remains task13 v11: score 22,087.474608, 15/15 delivered. No rank or score is guaranteed.
