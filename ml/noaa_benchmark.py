"""Compare archived NOAA SWPC forecasts on SolarWind's frozen intervals."""

import argparse
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import local
from zipfile import ZipFile

import joblib
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ml.data import KP_FEATURE, STORM_KP, load_archive, make_examples
from ml.history import append_noaa_comparison
from ml.hp30 import load_hp30_features
from ml.train import (
    HISTORY_PATH, HYBRID_ARTIFACT, LEAD_HOURS, SPLITS, block_bootstrap, check_protocol, evaluate,
    fit_budget_threshold, fit_threshold, predict_storm_probability, row_id_sha256,
)

NCEI = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/3day_forecast/"
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py"
IEM_PARAMS = {
    "pil": "DAYTDF", "center": "KWNP", "ttaaii": "FXXX10",
    "sdate": "2022-12-29", "edate": "2026-01-01", "fmt": "zip", "limit": 9999,
}
ISSUED = re.compile(r"^:?Issued:\s+(\d{4}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{4})\s+UTC", re.M)
ROWS = re.compile(r"^[ \t]*(\d{2})-(\d{2})\s*UT[ \t]+(.+)$", re.M)
HTTP = local()


def read_bulletin(text):
    text = text.replace("\r", "")
    issued = pd.Timestamp(datetime.strptime(ISSUED.search(text)[1], "%Y %b %d %H%M"), tz="UTC")
    _, table = text.split("NOAA Kp index breakdown", maxsplit=1)
    date_line = next(line for line in table.splitlines()[1:] if line.strip())
    dates_in_table = re.findall(r"([A-Z][a-z]{2})\s+(\d{1,2})", date_line)
    labels = [(month, int(day)) for month, day in dates_in_table]
    # Updates can carry forward the original table across midnight or start the next day.
    for first_day in (issued.normalize(), issued.normalize() - pd.Timedelta(days=1), issued.normalize() + pd.Timedelta(days=1)):
        dates = pd.date_range(first_day, periods=3)
        if [(ts.strftime("%b"), ts.day) for ts in dates] == labels:
            break
    else:
        raise ValueError("Dates in NOAA's Kp column headers disagree with the forecast window")
    forecasts = {}
    for start, end, values in ROWS.findall(table):
        hour = int(start)
        if hour % 3 or int(end) != (hour + 3) % 24:
            raise ValueError("Unexpected NOAA target interval")
        kp = [float(value) for value in re.sub(r"\(G[1-5]\)", "", values).split()]
        if len(kp) != 3 or not all(0 <= value <= 9 for value in kp):
            raise ValueError("Expected three planetary Kp forecasts from NOAA")
        forecasts.update({date + pd.Timedelta(hours=hour): value for date, value in zip(dates, kp)})
    if len(forecasts) != 24:
        raise ValueError("Expected 24 distinct forecast intervals")
    return issued, forecasts


def get(url, **kwargs):
    if not hasattr(HTTP, "session"):
        HTTP.session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
        HTTP.session.mount("https://", HTTPAdapter(max_retries=retry))
    response = HTTP.session.get(url, timeout=(8, 35), **kwargs)
    response.raise_for_status()
    return response.content


def iem_files(cache):
    path = cache / "iem-daytdf-20221229-20260101.zip"
    if not path.is_file():
        payload = get(IEM, params=IEM_PARAMS)
        with ZipFile(io.BytesIO(payload)) as archive:
            if not archive.namelist():
                raise ValueError("No SWPC bulletins found in the IEM ZIP")
        path.write_bytes(payload)
    with ZipFile(path) as archive:
        for name in archive.namelist():
            published = pd.to_datetime(name.removeprefix("DAYTDF_").removesuffix(".txt"), format="%Y%m%d%H%M", utc=True)
            yield "iem", name, published, archive.read(name)


def ncei_files(cache):
    """Use NCEI for validation-month coverage and to fill test archive gaps."""
    directory = cache / "ncei"
    directory.mkdir(exist_ok=True)
    months = pd.date_range("2022-12-01", "2025-12-01", freq="MS")

    def list_month(month):
        prefix = NCEI + month.strftime("%Y/%m/")
        try:
            body = get(prefix).decode()
        except requests.HTTPError as error:
            if error.response.status_code == 404:
                return []
            raise
        names = set(re.findall(r'href="(\d{12}three_day_forecast\.txt)"', body))
        return [(prefix + name, name) for name in sorted(names) if name[:8] >= "20221229"]

    def fetch_one(item):
        url, name = item
        path = directory / name
        if not path.is_file():
            path.write_bytes(get(url))
        available = pd.to_datetime(name[:12], format="%Y%m%d%H%M", utc=True)
        return "ncei", name, available, path.read_bytes()

    with ThreadPoolExecutor(max_workers=8) as pool:
        files = [item for month in pool.map(list_month, months) for item in month]
        yield from pool.map(fetch_one, files)


def read_forecasts(cache, targets):
    cache.mkdir(exist_ok=True, parents=True)
    cutoff = dict(zip(targets, targets - pd.Timedelta(hours=LEAD_HOURS)))
    releases = []
    rejected = []
    for reports in (iem_files(cache), ncei_files(cache)):
        for archive, name, published, body in reports:
            try:
                issued, forecasts = read_bulletin(body.decode("utf-8", errors="replace"))
            except (TypeError, ValueError, StopIteration) as error:
                rejected.append({"archive": archive, "file": name, "error": str(error)})
                continue
            releases.append((archive, name, issued, max(issued, published), forecasts, hashlib.sha256(body).hexdigest()))
    # Prefer the WMO transmission time for copies of the same bulletin.
    iem_copies = {(issued, tuple(forecasts.items())) for archive, _, issued, _, forecasts, _ in releases if archive == "iem"}
    best = {}
    for archive, name, issued, available, forecasts, digest in releases:
        if archive == "ncei" and (issued, tuple(forecasts.items())) in iem_copies:
            continue
        order = (available, issued, archive == "iem", name)
        for target, kp in forecasts.items():
            if target not in cutoff or available > cutoff[target]:
                continue
            if target not in best or best[target][0] < order:
                best[target] = (order, kp, available, issued, archive, name, digest)
    matches = pd.DataFrame(
        (entry[1:] for entry in best.values()), index=pd.DatetimeIndex(best, name="target_start"),
        columns=["forecast_kp", "available", "issued", "archive", "file", "bulletin_sha256"],
    ).sort_index()
    return matches, {"parsed_bulletins": len(releases), "rejected": rejected}


def comparison(cache_dir, output_dir, hp30_artifact):
    hourly, manifest = load_archive(SPLITS["train"][0], SPLITS["test"][1], cache_dir)
    frame, _ = make_examples(hourly, include_coupling=True, lead_hours=LEAD_HOURS)
    splits = {key: frame.loc[frame.index.year.isin(range(first, last + 1))]
              for key, (first, last) in SPLITS.items()}
    benchmark, digests = check_protocol(manifest, splits)
    hp30, hp_manifest = load_hp30_features(cache_dir, frame.index, lead_hours=LEAD_HOURS)
    ridge = joblib.load(HYBRID_ARTIFACT)
    hp30_model = joblib.load(hp30_artifact)
    if (
        ridge["sources"] != [row for row in manifest if row["year"] <= SPLITS["calibration"][1]] or
        hp30_model["hp30_sources"] != hp_manifest or hp30_model["lead_hours"] != LEAD_HOURS
    ):
        raise ValueError("Saved models do not have the expected inputs")
    validation, test = (splits[key].join(hp30) for key in ("validation", "test"))
    matched, archive = read_forecasts(cache_dir / "swpc-3day", validation.index.union(test.index))
    noaa = matched["forecast_kp"] / 9
    validation_ridge = predict_storm_probability(ridge["horizons"][LEAD_HOURS], validation)
    default_thresholds = {
        "noaa_swpc": STORM_KP / 9,
        "ridge_coupling": fit_threshold(validation["storm"], validation_ridge),
        "ridge_hp30": hp30_model["threshold"],
        "persistence": STORM_KP / 9,
    }

    def scores(rows):
        return {
            "noaa_swpc": noaa.loc[rows.index].to_numpy(),
            "ridge_coupling": predict_storm_probability(ridge["horizons"][LEAD_HOURS], rows),
            "ridge_hp30": predict_storm_probability(hp30_model, rows),
            "persistence": (rows[KP_FEATURE].fillna(splits["train"][KP_FEATURE].median()) / 9).to_numpy(),
        }

    full_count = len(test)
    full_val_count = len(validation)
    validation = validation.loc[validation.index.isin(matched.index)]
    test = test.loc[test.index.isin(matched.index)]
    test_scores, val_scores = scores(test), scores(validation)
    budget = int(((val_scores["ridge_coupling"] >= default_thresholds["ridge_coupling"]) & validation["storm"].eq(0)).sum())
    matched_thresholds = {key: fit_budget_threshold(validation["storm"], values, budget) for key, values in val_scores.items()}

    def measure(name, probabilities, thresholds):
        row = evaluate(test, probabilities, thresholds[name])
        if name in {"noaa_swpc", "persistence"}:
            row.pop("brier")
            row["threshold"] *= 9  # Kp, not a probability.
        return row

    test_matches = matched.loc[test.index]
    ages = (test.index - test_matches["available"]).dt.total_seconds() / 3600
    report = {
        "benchmark": benchmark, "lead_hours": LEAD_HOURS, "full_test_sha256": digests["test"],
        "matched_test_sha256": row_id_sha256(test),
        "validation_rows": len(validation), "full_validation_rows": full_val_count,
        "test_rows": len(test), "full_test_rows": full_count, "test_storms": int(test["storm"].sum()),
        "test_sources": test_matches["archive"].value_counts().to_dict(),
        "noaa_age_hours_before_target": {key: float(value) for key, value in
                                         zip(("min", "median", "max"), ages.quantile([0, .5, 1]))},
        "archive": archive,
        "test_metrics": {name: measure(name, values, default_thresholds) for name, values in test_scores.items()},
        "false_positive_budget_on_validation": budget,
        "test_at_validation_budget": {name: measure(name, values, matched_thresholds) for name, values in test_scores.items()},
        "paired_bootstrap_vs_noaa": {
            key: block_bootstrap(test, test_scores[key], test_scores["noaa_swpc"])
            for key in ("ridge_coupling", "ridge_hp30")
        },
        "constant_average_precision": float(test["storm"].mean()),
    }
    output_dir.mkdir(exist_ok=True, parents=True)
    csv = matched.assign(
        storm=frame["storm"], final_kp=frame["target_kp"],
        lead_hours=(matched.index - matched["available"]).dt.total_seconds() / 3600,
    ).to_csv(lineterminator="\n")
    report["matches_sha256"] = hashlib.sha256(csv.encode()).hexdigest()
    (output_dir / "noaa_matches.csv").write_bytes(csv.encode())
    (output_dir / "noaa_metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path(".ml-cache"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ml-output/fixed-benchmark"))
    args = parser.parse_args()
    result = comparison(args.cache_dir, args.output_dir, args.output_dir / "ridge_hp30.joblib")
    append_noaa_comparison(result, HISTORY_PATH)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
