# SolarWind model architecture

The dashboard uses Ridge + Hp30 + five-minute solar-wind statistics and Hilbert–Huang features. The model produces a numeric estimate of the final planetary Kp and a probability that it reaches 5 in a standard three-hour UTC interval. The published artifact is `ridge-hp30-hht-v1`.

## Time and inputs

Let T be the start of the target interval. Its outcome is the final Kp for [T, T + 3 h). The benchmark prediction cutoff is T − 1 h. The collector attempts a release every 30 seconds in the 15 minutes leading up to that cutoff.

| Input group | Benchmark source | Runtime source and cutoff |
| --- | --- | --- |
| Hourly solar wind and coupling | NASA hourly OMNI | NOAA RTSW, propagated from L1 and aggregated. The most recent hour is [T − 3 h, T − 2 h). |
| Last Kp and three-hour change | Kp in hourly OMNI | NOAA observed Kp. The latest input bin begins at T − 9 h and ends at T − 6 h. |
| Hp30 and ap30 | GFZ Hpo v3.0 archive | GFZ Hp30 nowcast. The latest half-hour bin ends at T − 1 h 30 min. |
| Five-minute statistics and HHT | NASA five-minute OMNI | Propagated NOAA RTSW in the window [T − 5 h, T − 2 h). |

NOAA plasma and magnetometer records must have the primary flag and a good quality flag. The collector pairs them by completed measurement minute and spacecraft. It estimates the transit time from L1 as 1.5 million km divided by the absolute earthward GSE velocity, using the scalar speed when the vector component is unavailable. Each five-minute bin uses one spacecraft and needs three distinct minutes. Hourly aggregates require six five-minute bins. Snapshot receipt timestamps and the actual issue timestamp must precede the deadline.

OMNI is an archive with its own propagation and quality procedures. Applying the live adapter changes the input distribution. The release records preserve the raw NOAA and GFZ responses so the live path can be scored prospectively. [NOAA solar wind](https://www.spaceweather.gov/products/solar-wind) · [NASA OMNI](https://omniweb.gsfc.nasa.gov/ow_min.html) · [GFZ Hp30 v3.0](https://doi.org/10.5880/hpo.0003)

## Features and model

The feature vector has 70 values before preprocessing.

| Count | Features |
| ---: | --- |
| 44 | Hourly plasma and magnetic readings, southward Bz and its electric-field proxy, dynamic pressure proxy, features over 3, 6 and 12 hours, two lagged Kp features, and Newell and viscous coupling terms |
| 3 | Latest Hp30, log of one plus the two-hour mean ap30, and the difference of log-transformed means over consecutive hours |
| 15 | Minimum, maximum and mean of Bt, GSM Bz, flow speed, density and dynamic pressure in the three-hour five-minute window |
| 8 | For both GSM Bz and Newell coupling, the number of intrinsic mode functions, log energy, log peak amplitude and instantaneous frequency at the peak |

Five-minute statistics need 27 of 36 bins for the variable. HHT decomposes each window independently using empirical mode decomposition. It preserves the oscillatory modes and applies the Hilbert transform to obtain amplitudes and phases. An isolated internal missing sample can be interpolated using its two neighbors within the same window. If gaps remain, the HHT features for that series are missing. A complete signal with no oscillatory modes produces zeros. [Yang et al.](https://doi.org/10.1029/2026SW005086)

The training pipeline fills missing values with training medians, appends 65 learned missing-value indicators, and standardizes the resulting 135 inputs. Ridge regression with α = 10 minimizes squared error on the numeric Kp. On a separate year, a logistic model maps the raw Ridge estimate to the probability of Kp ≥ 5. The display clips the numeric estimate to [0, 9]. Calibration uses the raw estimate. The runtime evaluates the exact same transformations from the bundled JSON parameters.

## Evaluation and release threshold

The frozen protocol fits on 2014–2021, calibrates on 2022, and chooses thresholds on 2023. The 2024–2025 test has 5,848 intervals, 253 with Kp ≥ 5 and 103 onsets. The selected model scored 0.5487 AP, 0.0279 Brier, and 0.436 F1 at its independent F2-selected threshold. V4 scored 0.5380 AP and won on 2023 validation. The app explicitly ships the HHT-feature Ridge as the project's selected architecture.

The app uses a separate development-only probability threshold of approximately 0.07430. The threshold maximized detected validation storm intervals with no more than 133 false alerts, the V4 validation budget. Applied to the test it gives F1 0.4493, 197 of 253 storm intervals detected, and 427 false alerts. It detects 56 of 103 onsets. At the equivalent validation budget, V4 found 60 onsets and gave 452 false alerts. [Model history](MODEL_HISTORY.md)

## Application lifecycle

- `train.py --hht` recreates the benchmark model from the pinned source files. `export_final.py` exports the chosen candidate as `ridge_hp30_hht.json`.
- `final_live.py` fetches observations, checks timing and input availability, and builds the same feature layout. Missing optional features use the fitted imputer. An unavailable required input can delay or prevent a release.
- `final_model.py` performs inference from the packaged JSON. It requires neither the training estimator nor the historical archives.
- SQLite stores the first eligible forecast for each target, the parameter file hash, and the timestamp and content hash of each captured source. The source responses are compressed and deduplicated. The endpoint serves the latest forecast through the end of its target interval.
- Flask exposes `GET /api/model-forecast`. The dashboard labels it experimental and displays it alongside the official NOAA outlook. The model's elevated-risk badge is a local classification output.

The live collector and the Flask app run in the same process when launched with `python main.py`. A deployment can run one collector with `python -m ml.final_live watch` beside the WSGI server and use a shared writable `.ml-output/` directory. The retrospective metrics describe the locked archive benchmark. Prospective measurement needs saved forecasts and final Kp labels.
