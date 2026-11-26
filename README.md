# SolarWind — Space Weather Dashboard

SolarWind forecasts the risk of geomagnetic storms and displays live spacecraft observations, planetary Kp, the official NOAA outlook, and original NOAA bulletins. The dashboard defaults to Singapore time and can switch to UTC.

## Run locally

Use Python 3.11 or newer.

```sh
python -m venv .venv
# Windows PowerShell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
# macOS / Linux
# .venv/bin/python -m pip install -r requirements.txt
# .venv/bin/python main.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The app starts its forecast collector automatically. NOAA provides the dashboard observations and GFZ provides the Hp30 inputs for the model. A scheduled card shows when the next release window opens.

## Data flow

The browser requests `GET /api/dashboard` from Flask. The server fetches the five public NOAA SWPC feeds in parallel, normalizes their timestamps to UTC, and caches each successful response for one minute. Each feed reports its own status, source URL, and fetch time. A temporary failure can use the last successful response for up to 24 hours, marked **Cached**. An older observation is marked **Delayed** even if the upstream request succeeds. If every feed is unavailable, the endpoint returns HTTP 503 with the same response format.

| Feed | NOAA source | What the dashboard shows |
| --- | --- | --- |
| Plasma | [RTSW wind](https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json) | Speed and proton density from the primary instrument |
| Magnetic field | [RTSW magnetometer](https://services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json) | GSM Bz from the primary instrument |
| Observed geomagnetic activity | [Planetary Kp](https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json) | Reported Kp by three-hour interval |
| Forecast | [NOAA Kp outlook](https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json) | Predicted Kp for current and upcoming intervals |
| Bulletins | [NOAA alerts](https://services.swpc.noaa.gov/products/alerts.json) | Recent releases and their original message text |

Telemetry covers up to 24 hours. Charts leave gaps when readings are missing and break the line when the primary spacecraft changes. The Kp card and charts use green for values below 4, yellow for values from 4 to below 5, and red from 5 upward. The dashed line at 5 marks the [NOAA G1 threshold](https://www.swpc.noaa.gov/noaa-scales-explanation). The color bands are for the global Kp index.

## SolarWind model forecast

The selected model is **Ridge + Hp30 + five-minute solar-wind statistics and Hilbert–Huang features**. The dashboard shows its estimated Kp and calibrated probability of `Kp ≥ 5` in a standard three-hour interval. The runtime reads a bundled JSON parameter file. An app install requires neither training nor the historical data archives. [Model architecture](ml/ARCHITECTURE.md)

The collector polls during the 15-minute window ending one hour before the target interval. It saves the first qualifying prediction and its input snapshots, and skips the release if the required inputs are unavailable by the deadline. Flask serves that record through `GET /api/model-forecast`. For a hosted deployment, run the WSGI app and one `python -m ml.final_live watch` process with a shared writable `.ml-output/` directory.

On the fixed retrospective test the selected model achieved **0.5487 average precision** compared with 0.5380 for Ridge + Hp30 and 0.1945 for the latest archived NOAA 3-Day Forecast available at the cutoff. The NOAA lead was 8.1 hours at the median. The dashboard labels its forecast experimental and shows it alongside the official NOAA outlook. [Model history](ml/MODEL_HISTORY.md)

## Fixed ML benchmark

The task is to predict whether the final Kp reaches 5 in a standard three-hour UTC interval, **one hour before it starts**. All versions use the same [locked NASA OMNI inputs and rows](ml/benchmark_protocol.json). The development window is 2014–2023. It includes fitting on 2014–2021, probability calibration on 2022, and model and threshold selection on 2023. The sole test window is 2024–2025 with 5,848 intervals, including 253 storm intervals.

Run the benchmark from the project root:

```sh
python -m pip install -r requirements-ml.txt
python -m ml.train
python -m ml.train --goes
python -m ml.train --hp30
python -m ml.train --hht
```

The command updates [model history](ml/MODEL_HISTORY.md) and writes the fitted artifact and machine-readable results to `.ml-output/fixed-benchmark/`. It checks the original file hashes and the exact row fingerprints before scoring. Ridge + GFZ receives a benchmark score only when as-issued GFZ forecasts cover the same test intervals at the same lead.

The GOES experiment adds two features to the existing Ridge pipeline using the [Chakraborty and Morley study](https://arxiv.org/html/2007.02733) as a guide. It summarizes a trailing 24-hour minimum of soft X-ray flux and the hard/soft flux ratio with a 48-hour lag from issuance. The model retains all benchmark rows and handles missing readings using training-only statistics. The command downloads the [pinned NOAA Level 2 archives](ml/goes_protocol.json) on first use (about 280 MB) and saves the experimental artifact as `.ml-output/fixed-benchmark/ridge_goes.joblib`.

The Hp30 experiment uses [GFZ Hpo v3.0 observations](https://doi.org/10.5880/hpo.0003) and locks the archive slice used in the benchmark. It adds the latest Hp30, the two-hour mean of ap30 and the change in ap30 between consecutive hours. Bins must have ended at least 30 minutes before issuance. GFZ can revise archived values, so this result is retrospective. The candidate is saved as `.ml-output/fixed-benchmark/ridge_hp30.joblib`.

The HHT experiment adapts [Yang et al.'s HHT–ANN](https://doi.org/10.1029/2026SW005086) to the fixed one-hour forecast. It keeps the Hp30 inputs and compares Ridge with a ten-unit ReLU network, with and without the Hilbert–Huang features. The first run downloads about 410 MB of [pinned five-minute NASA OMNI files](ml/hht_protocol.json) and caches the features. The HHT window spans three hours and ends one hour before forecast issuance to match the hourly OMNI reporting buffer. These are retrospective models. The full HHT–ANN candidate is saved as `.ml-output/fixed-benchmark/ann_hp30_hht.joblib`.

Run `python -m ml.export_final` after `python -m ml.train --hht` to regenerate the bundled Ridge artifact. Model selection for the app is explicit. The validation winner remains recorded in the benchmark history.

To compare the fitted Ridge models against the archived NOAA SWPC 3-Day Forecast, run `python -m ml.hybrid train`, `python -m ml.train --hp30`, then `python -m ml.noaa_benchmark`. The comparison uses the latest published bulletin by the one-hour cutoff for each matching interval. The matching records and metrics are saved as `noaa_matches.csv` and `noaa_metrics.json` in the fixed benchmark output directory.

## Optional Ridge + GFZ experiment

Run these commands from the project root in a local terminal. The hybrid is implemented in [`ml/hybrid.py`](ml/hybrid.py) and runs without a notebook.

```sh
python -m pip install -r requirements-ml.txt
python -m ml.hybrid train
python -m ml.hybrid collect
python -m ml.hybrid watch --minutes 15
```

Use `collect` for a single run or `watch` to keep collecting while the process is running. Each run targets the next standard three-hour UTC Kp bin. Ridge models are trained for one, two, and three whole-hour leads. The pipeline records both the model's whole-hour feature anchor and the actual issue time. It uses the exact matching bin from the [GFZ/PAGER forecast](https://spaceweather.gfz.de/products-data/forecasts/forecast-kp-index). The hybrid score averages Ridge's storm probability and the fraction of valid GFZ ensemble members at or above Kp 5. The weights are fixed at 50/50. The output is an experimental score and does not trigger alerts. A single available component is reported on its own.

The collector saves source snapshots, reception times, model checksum and all three scores in `.ml-output/hybrid.sqlite3`. With Flask running, `/api/hybrid` serves the latest recorded run. The separately trained Ridge artifact is `.ml-output/hybrid_ridge.joblib`. The last-modified header is used as a freshness check for GFZ, and actual lead is calculated from the local issue time.

Add `--capture-hp30` to `collect` or `watch` to save GFZ's original live Hp30 response and its reception time for prospective verification of the archive experiment.

The live log is available for operational diagnosis through `python -m ml.hybrid diagnose-live --labels preliminary`. Use `python -m ml.train` for version comparisons and model history.

## Author

Ilya Emelianov · [GitHub](https://github.com/ilyaemelian)
