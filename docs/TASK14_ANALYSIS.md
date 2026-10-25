# Task14 diagnostic: why the score slipped

## Verdict
Task14 was not a delivery regression: all 15 workloads finished. It scored 22,086.827254, down 0.647354 points from task13. Electricity CO2e rose by 13.208 g, while lifecycle CO2e fell by 19.067 g. Total footprint fell by 5.859 g, but leaderboard scoring is electricity-only, so that lower total footprint did not help the score.

## Workload-level movement
Compared with task13, biggest score gains were w-03 (+8.90 points; −56.220 g electricity) and w-06 (+5.14; −35.226 g). Largest losses were w-14 (−8.28; +52.405 g), w-09 (−3.18; +33.629 g), w-15 (−2.41; +13.484 g), w-05 (−1.91; +10.663 g), w-11 (−1.83; +9.357 g), and w-13 (−1.52; +8.418 g). Rounded dashboard point rows may not sum exactly to the final score delta.

## Churn signal, not causal proof
Task14's run-scoped SQLite recorded 453 controller events: 16 creates, one park, 218 pauses and 218 resumes. Task13 recorded 217: 16 creates, one park, 100 pauses and 100 resumes. Biggest pause/resume pair counts in task14: w-13 54, w-15 36, w-10 33, w-12 29, w-03 24 and w-06 15. Some high-churn jobs improved, so a blanket dwell increase is not justified; replay tests of global dwell reduced score.

The w-14 dashboard reports 6.575 units of checkpoint rollback after deleting a VM. This is a plausible contributor to its +52.405 g electricity delta, but task13 also had a rollback (7.291 units). The evidence does not isolate parking as the cause.

## Forecast record
Both run databases contain 22,464 forecast points, 1,128 observations and 3,424 forecast-error rows. Error ratios are identical by area and horizon bucket; overall mean actual/forecast ratio is 0.990628 and mean absolute ratio error is 0.081957. Thus the available memory does not show a calibration-quality change that explains the live score delta.

## v13 test result and limit
A conservative class-margin candidate, including a generic long-output rule for single-worker CPU jobs, produced replay means of 22,104.4 (task13 trace) and 22,104.8 (task14 trace), compared with v12 replay means of 22,090.8 and 22,091.3. All seven replay cadence variants per trace delivered 15/15. In 96 seeds in each of two synthetic grid families, the candidate delivered all workloads. This is a promising candidate, not evidence of a v13 live result or guaranteed leaderboard gain.

## Data boundary
Historical run data is used here only for diagnosis and replay testing. The shipped controller must continue to use only public specifications and the current run's currently published forecasts, observations and status. Never transfer these databases into a new attempt.
