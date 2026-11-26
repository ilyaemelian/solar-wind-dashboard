# SolarWind model history

The app ships Ridge + Hp30 + five-minute statistics and HHT. The retrospective V4 remained the validation winner. The [architecture](ARCHITECTURE.md) documents the release threshold and live-data limitations.

The [fixed protocol](benchmark_protocol.json) uses 2014–2023 for development and 2024–2025 for testing. The target is final Kp ≥ 5 in a three-hour UTC interval, forecast one hour before it starts. The test has 5848 intervals including 253 storm intervals. The benchmark checks archive hashes and the exact row identities before scoring.

| Development split | Intervals | Storm intervals |
| --- | ---: | ---: |
| Fit, 2014–2021 | 23371 | 379 |
| Calibration, 2022 | 2920 | 54 |
| Model and threshold selection, 2023 | 2920 | 81 |

Run `python -m ml.train` to reproduce the benchmark. The history deduplicates runs with identical results.

## 2026-11-25 19:49 UTC

<!-- run:d1383439f8af867d -->

Validation winner **V2 · Ridge + physical features**.

| Model | Validation AP | Test AP ↑ | Brier ↓ | F1 ↑ | Storm intervals detected ↑ | Onsets detected ↑ | False alerts ↓ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Last available Kp | 0.232 | 0.290 | 0.0378 | 0.318 | 121/253 | 32/103 | 388 |
| V1 · Logistic regression | 0.405 | 0.507 | 0.0296 | 0.419 | 185/253 | 50/103 | 446 |
| Logistic regression + Newell | 0.404 | 0.503 | 0.0298 | 0.437 | 180/253 | 47/103 | 391 |
| Logistic regression + physical features | 0.426 | 0.500 | 0.0297 | 0.350 | 211/253 | 71/103 | 740 |
| Ridge without added coupling features | 0.425 | 0.514 | 0.0295 | 0.421 | 193/253 | 58/103 | 470 |
| V2 · Ridge + physical features | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Histogram gradient boosting | 0.347 | 0.458 | 0.0315 | 0.370 | 186/253 | 52/103 | 567 |
| Ridge from the live comparison artifact | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Ridge + GFZ/PAGER | — | — | — | — | — | — | — |

As-issued GFZ forecasts matched 0/5848 test intervals. A dash indicates an unavailable score.

SHA-256 of the Ridge comparison artifact `bd4f5a729358ea1d50fd7e3de90be7f6b815e02c9cf0ca8f1ea14750155c47d0`.

## 2026-11-25 22:31 UTC

<!-- run:573f3f5bd9d974ea -->

Validation winner **V3 · Ridge + GOES XRS**.

| Model | Validation AP | Test AP ↑ | Brier ↓ | F1 ↑ | Storm intervals detected ↑ | Onsets detected ↑ | False alerts ↓ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Last available Kp | 0.232 | 0.290 | 0.0378 | 0.318 | 121/253 | 32/103 | 388 |
| V1 · Logistic regression | 0.405 | 0.507 | 0.0296 | 0.419 | 185/253 | 50/103 | 446 |
| Logistic regression + Newell | 0.404 | 0.503 | 0.0298 | 0.437 | 180/253 | 47/103 | 391 |
| Logistic regression + physical features | 0.426 | 0.500 | 0.0297 | 0.350 | 211/253 | 71/103 | 740 |
| Ridge without added coupling features | 0.425 | 0.514 | 0.0295 | 0.421 | 193/253 | 58/103 | 470 |
| V2 · Ridge + physical features | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Histogram gradient boosting | 0.347 | 0.458 | 0.0315 | 0.370 | 186/253 | 52/103 | 567 |
| V3 · Ridge + GOES XRS | 0.446 | 0.504 | 0.0296 | 0.425 | 197/253 | 60/103 | 476 |
| Ridge from the live comparison artifact | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Ridge + GFZ/PAGER | — | — | — | — | — | — | — |

As-issued GFZ forecasts matched 0/5848 test intervals. A dash indicates an unavailable score.

**GOES experiment.** The same Ridge model added the soft X-ray background and channel ratio with a 48-hour lag.
Test coverage was 5824/5848 for the background and 5672/5848 for the ratio. Missing readings used training-set statistics.
AP change -0.0010. The paired 95% interval from weekly blocks was [-0.0030, 0.0008].

The thresholds used a shared budget of 112 false alerts on 2023 validation.

| Model | Test onsets ↑ | Test false alerts ↓ |
| --- | ---: | ---: |
| V2 · Ridge + physical features | 56/103 | 420 |
| V3 · Ridge + GOES XRS | 55/103 | 417 |

SHA-256 of the Ridge comparison artifact `bd4f5a729358ea1d50fd7e3de90be7f6b815e02c9cf0ca8f1ea14750155c47d0`.

## 2026-11-25 23:04 UTC

<!-- run:be35a34c85fb1ef8 -->

Validation winner **V4 · Ridge + Hp30 and ap30**.

| Model | Validation AP | Test AP ↑ | Brier ↓ | F1 ↑ | Storm intervals detected ↑ | Onsets detected ↑ | False alerts ↓ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Last available Kp | 0.232 | 0.290 | 0.0378 | 0.318 | 121/253 | 32/103 | 388 |
| V1 · Logistic regression | 0.405 | 0.507 | 0.0296 | 0.419 | 185/253 | 50/103 | 446 |
| Logistic regression + Newell | 0.404 | 0.503 | 0.0298 | 0.437 | 180/253 | 47/103 | 391 |
| Logistic regression + physical features | 0.426 | 0.500 | 0.0297 | 0.350 | 211/253 | 71/103 | 740 |
| Ridge without added coupling features | 0.425 | 0.514 | 0.0295 | 0.421 | 193/253 | 58/103 | 470 |
| V2 · Ridge + physical features | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Histogram gradient boosting | 0.347 | 0.458 | 0.0315 | 0.370 | 186/253 | 52/103 | 567 |
| V4 · Ridge + Hp30 and ap30 | 0.471 | 0.538 | 0.0283 | 0.445 | 202/253 | 60/103 | 452 |
| Ridge from the live comparison artifact | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Ridge + GFZ/PAGER | — | — | — | — | — | — | — |

As-issued GFZ forecasts matched 0/5848 test intervals. A dash indicates an unavailable score.

**Hp30 experiment.** Ridge added the latest Hp30, two-hour mean ap30 and one-hour ap30 change.
The most recent input bin ended at least 30 minutes before issuance.
This evaluation used the retrospective GFZ series, which can include revisions.
AP change vs. V2 was 0.0326. The paired 95% interval from weekly blocks was [0.0192, 0.0481].

The thresholds used a shared budget of 112 false alerts on 2023 validation.

| Model | Test onsets ↑ | Test false alerts ↓ | False alerts on the first interval after a storm ↓ |
| --- | ---: | ---: | ---: |
| V2 · Ridge + physical features | 56/103 | 420 | 89/103 |
| V4 · Ridge + Hp30 and ap30 | 45/103 | 327 | 94/103 |

SHA-256 of the Ridge comparison artifact `bd4f5a729358ea1d50fd7e3de90be7f6b815e02c9cf0ca8f1ea14750155c47d0`.

## 2026-11-26 10:22 UTC

<!-- run:df686ca8ef29bd95 -->

### Official NOAA SWPC forecast comparison

The latest 3-Day Forecast available at each one-hour cutoff matched 5848/5848 test intervals, including 253 storm intervals. The archived NOAA releases had a median lead of 8.1 hours.

AP ranks NOAA forecasts by their numeric Kp. NOAA and persistence use a Kp threshold of 5 for F1. Ridge thresholds were selected by F2 on the full 2023 validation set.

| Model | AP ↑ | F1 ↑ | Onsets detected ↑ | False alerts ↓ |
| --- | ---: | ---: | ---: | ---: |
| NOAA SWPC · 3-Day Forecast | 0.1945 | 0.2578 | 21/103 | 247 |
| V2 · Ridge + physical features | 0.5054 | 0.4421 | 56/103 | 420 |
| V4 · Ridge + Hp30 and ap30 | 0.5380 | 0.4454 | 60/103 | 452 |
| Last available Kp | 0.2904 | 0.3360 | 13/103 | 168 |

Constant-score AP was 0.0433.
The comparison uses the NOAA three-day bulletin and retrospective NASA OMNI and GFZ inputs for Ridge.

The [NCEI archive](https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/3day_forecast/) and the [IEM archive of NWS broadcasts](https://mesonet.agron.iastate.edu/nws/text.php) supply the releases. Run `python -m ml.noaa_benchmark` to reproduce the comparison.

SHA-256 of the matched releases and intervals `b565b14c41012c025b76e33d6481d2e5534198dad13e1efc1bc471920785a9ef`.

## 2026-11-26 10:42 UTC

<!-- run:99ee0f74cd6fa775 -->

Validation winner **V4 · Ridge + Hp30 and ap30**.

| Model | Validation AP | Test AP ↑ | Brier ↓ | F1 ↑ | Storm intervals detected ↑ | Onsets detected ↑ | False alerts ↓ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Last available Kp | 0.232 | 0.290 | 0.0378 | 0.318 | 121/253 | 32/103 | 388 |
| V1 · Logistic regression | 0.405 | 0.507 | 0.0296 | 0.419 | 185/253 | 50/103 | 446 |
| Logistic regression + Newell | 0.404 | 0.503 | 0.0298 | 0.437 | 180/253 | 47/103 | 391 |
| Logistic regression + physical features | 0.426 | 0.500 | 0.0297 | 0.350 | 211/253 | 71/103 | 740 |
| Ridge without added coupling features | 0.425 | 0.514 | 0.0295 | 0.421 | 193/253 | 58/103 | 470 |
| V2 · Ridge + physical features | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Histogram gradient boosting | 0.347 | 0.458 | 0.0315 | 0.370 | 186/253 | 52/103 | 567 |
| V4 · Ridge + Hp30 and ap30 | 0.471 | 0.538 | 0.0283 | 0.445 | 202/253 | 60/103 | 452 |
| Ridge + Hp30 + five-minute OMNI statistics | 0.470 | 0.547 | 0.0279 | 0.438 | 204/253 | 60/103 | 474 |
| ANN + Hp30 + five-minute OMNI statistics | 0.445 | 0.533 | 0.0282 | 0.448 | 184/253 | 48/103 | 384 |
| Ridge + Hp30 + five-minute statistics and HHT | 0.468 | 0.549 | 0.0279 | 0.436 | 207/253 | 63/103 | 490 |
| V5 · HHT–ANN + Hp30 | 0.436 | 0.538 | 0.0281 | 0.375 | 217/253 | 71/103 | 688 |
| Ridge from the live comparison artifact | 0.444 | 0.505 | 0.0295 | 0.442 | 191/253 | 56/103 | 420 |
| Ridge + GFZ/PAGER | — | — | — | — | — | — | — |

As-issued GFZ forecasts matched 0/5848 test intervals. A dash indicates an unavailable score.

**Hp30 experiment.** Ridge added the latest Hp30, two-hour mean ap30 and one-hour ap30 change.
The most recent input bin ended at least 30 minutes before issuance.
This evaluation used the retrospective GFZ series, which can include revisions.
AP change vs. V2 was 0.0326. The paired 95% interval from weekly blocks was [0.0192, 0.0481].

The thresholds used a shared budget of 112 false alerts on 2023 validation.

| Model | Test onsets ↑ | Test false alerts ↓ | False alerts on the first interval after a storm ↓ |
| --- | ---: | ---: | ---: |
| V2 · Ridge + physical features | 56/103 | 420 | 89/103 |
| V4 · Ridge + Hp30 and ap30 | 45/103 | 327 | 94/103 |

**HHT–ANN experiment.** Ridge and the neural network both used five-minute OMNI statistics. Each was tested with and without Hilbert–Huang features from GSM Bz and the Newell coupling function.
Full test coverage was 5395/5848 for the statistics and 3825/5848 for the HHT features. All test rows were retained.
The strongest challenger on validation was **Ridge + Hp30 + five-minute OMNI statistics**.

The thresholds used the V4 budget of 133 false alerts on 2023 validation.

| Model | Test onsets ↑ | Test false alerts ↓ | Test AP change vs. V4 | Paired 95% interval |
| --- | ---: | ---: | ---: | ---: |
| V4 · Ridge + Hp30 and ap30 | 60/103 | 452 | 0.00000 | — |
| Ridge + Hp30 + five-minute OMNI statistics | 57/103 | 449 | 0.00941 | [-0.0009, 0.0184] |
| ANN + Hp30 + five-minute OMNI statistics | 54/103 | 463 | -0.00469 | [-0.0239, 0.0150] |
| Ridge + Hp30 + five-minute statistics and HHT | 56/103 | 427 | 0.01071 | [0.0011, 0.0194] |
| V5 · HHT–ANN + Hp30 | 54/103 | 450 | -0.00001 | [-0.0181, 0.0169] |

SHA-256 of the Ridge comparison artifact `bd4f5a729358ea1d50fd7e3de90be7f6b815e02c9cf0ca8f1ea14750155c47d0`.
