# Aura v13 release notes

## Changes
- Softened margins for long-input, parallel and zero-input checkpointable CPU workload classes.
- Generalized the long-output margin rule to any single-worker CPU job with output time >= 1 hour, including the EU output-heavy job.
- Kept `--score-aware-beta` default at 0.0; beta values did not improve both historical replay sets.
- Retained v12's bounded, actual-quota-checked fallback for a released zero-checkpoint restart-from-zero single-worker job.

## Verification
- 32 unit tests.
- 96 seeds in each of two synthetic grid families, no missed deliveries in the tested set.
- Seven cadence variants per historical trace: mean score 22,104.4 (task13 trace) and 22,104.8 (task14 trace). Versus v12: 22,090.8 and 22,091.3. Replay is approximate and not a live score.

## Caveat
No new live run has been executed with v13. Latest confirmed live result is task14: 22,086.827254, 15/15 delivered.
