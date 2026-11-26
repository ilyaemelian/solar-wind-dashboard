"""Issue and store live forecasts from the selected model."""

import argparse
import io
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from sqlite3 import OperationalError

import numpy as np
import pandas as pd
import requests

from ml.data import KP_FEATURE, coupling_terms, feature_frame
from ml.final_model import MODEL_ID, MODEL_PATH, FinalModel
from ml.hht import HHT_COLUMNS, REPORTING_BUFFER_HOURS, STATS_COLUMNS, make_hht_features
from ml.hp30 import NOWCAST_URL, make_hp30_features, parse_hpo
from src.hybrid_store import DEFAULT_DB, read_runs, save_run
from src.noaa import BASE_URL, FEEDS, number, timestamp, utc_string

FORECAST_DB = DEFAULT_DB.with_name("model-forecasts.sqlite3")
LEAD_HOURS = 1
RELEASE_WINDOW = timedelta(minutes=15)
INTERVAL = timedelta(hours=3)
L1_DISTANCE_KM = 1_500_000
URLS = {**{name: BASE_URL + FEEDS[name].path for name in ("wind", "magnetic", "kp")}, "hp30": NOWCAST_URL}
LOG = logging.getLogger(__name__)
FIELDS = ["speed", "density", "bt", "by", "bz"]


def next_start(now):
    return now.replace(hour=now.hour // 3 * 3, minute=0, second=0, microsecond=0) + INTERVAL


def release_cutoff(target):
    return target - timedelta(hours=LEAD_HOURS)


def read_forecast(db, now):
    runs = read_runs(db, latest_only=True)
    if runs and timestamp(runs[0]["target_end"]) > now:
        return runs[0]
    start = next_start(now)
    cutoff = release_cutoff(start)
    if now > cutoff:
        state = "missed"
    elif now >= cutoff - RELEASE_WINDOW:
        state = "collecting"
    else:
        state = "scheduled"
    return {
        "state": state, "model_id": MODEL_ID, "target_start": utc_string(start),
        "target_end": utc_string(start + INTERVAL), "issue_deadline": utc_string(cutoff),
        "issue_window_start": utc_string(cutoff - RELEASE_WINDOW),
    }


def capture(item):
    source, url = item
    with requests.get(url, timeout=(4, 8), headers={"User-Agent": "SolarWindDashboard/3.0"}) as response:
        response.raise_for_status()
        received_at = datetime.now(UTC)
        payload = response.text if source == "hp30" else response.json(parse_constant=lambda _: None)
        if source != "hp30" and (not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload)):
            raise ValueError(f"Unexpected NOAA payload for {source}")
        return source, {
            "data": payload,
            "metadata": {"url": url, "received_at": utc_string(received_at), "last_modified": response.headers.get("Last-Modified")},
        }


def capture_inputs():
    with ThreadPoolExecutor(max_workers=len(URLS)) as pool:
        return dict(pool.map(capture, URLS.items()))


def primary_rows(captured, fields, start):
    samples = {}
    received = timestamp(captured["metadata"]["received_at"])
    for row in captured["data"]:
        if row.get("active") is not True or row.get("overall_quality") != 0 or not row.get("source"):
            continue
        try:
            observed = timestamp(row["time_tag"]).replace(second=0, microsecond=0)
        except (KeyError, ValueError):
            continue
        if start <= observed and observed + timedelta(minutes=1) <= received:
            key = (observed, row["source"])
            samples[key] = {name: number(row.get(field)) for name, field in fields.items()}
    index = pd.MultiIndex.from_tuples(samples.keys(), names=["observed", "source"])
    return pd.DataFrame(list(samples.values()), index=index, columns=list(fields), dtype=float)


def solar_wind_grid(captures, target):
    """Map L1 samples toward Earth, then bin one spacecraft per interval."""
    start = target - timedelta(hours=16)
    solar_end = target - timedelta(hours=LEAD_HOURS + REPORTING_BUFFER_HOURS)
    plasma = primary_rows(captures["wind"], {
        "speed": "proton_speed", "density": "proton_density", "vx": "proton_vx_gse",
    }, start - timedelta(hours=2))
    magnetic = primary_rows(captures["magnetic"], {"bt": "bt", "by": "by_gsm", "bz": "bz_gsm"}, start - timedelta(hours=2))
    paired = plasma.join(magnetic, how="inner").dropna(subset=FIELDS).reset_index()
    paired = paired.loc[paired["speed"].gt(0) & paired["density"].ge(0) & paired["bt"].ge(0)].copy()
    propagation_speed = paired["vx"].where(paired["vx"].lt(0)).abs().fillna(paired["speed"])
    delay = (L1_DISTANCE_KM / propagation_speed).where(propagation_speed >= 150)
    paired["arrival"] = (pd.to_datetime(paired["observed"], utc=True) + pd.to_timedelta(delay, unit="s")).dt.floor("min")
    paired = paired.loc[paired["arrival"].ge(start) & paired["arrival"].lt(solar_end)]
    minute = paired.groupby(["arrival", "source"], as_index=False)[FIELDS].mean()
    minute["bin"] = minute["arrival"].dt.floor("5min")
    grouped = minute.groupby(["bin", "source"], sort=True)
    ranked = grouped[FIELDS].mean().join(grouped.size().rename("minutes")).reset_index()
    ranked = ranked.loc[ranked["minutes"].ge(3)].sort_values(["bin", "minutes", "source"], ascending=[True, False, True])
    index = pd.date_range(start, solar_end, freq="5min", inclusive="left")
    hro = ranked.drop_duplicates("bin").set_index("bin")[FIELDS].reindex(index)
    hro["pressure"] = 1.6726e-6 * hro["density"] * hro["speed"].pow(2)
    hro["newell"] = coupling_terms(hro["speed"], hro["density"], hro["by"], hro["bz"])["newell"]
    return hro


def feature_row(captures, target):
    hro = solar_wind_grid(captures, target)
    hourly_bins = hro[FIELDS].resample("h")
    hourly = hourly_bins.mean().where(hourly_bins.count() >= 6)
    hourly = hourly.reindex(pd.date_range(target - timedelta(hours=16), target, freq="h"))
    kp = {}
    observed_by = timestamp(captures["kp"]["metadata"]["received_at"])
    for row in captures["kp"]["data"]:
        value = number(row.get("Kp"))
        try:
            start = timestamp(row["time_tag"])
        except (KeyError, ValueError):
            continue
        if value is not None and 0 <= value <= 9 and start + INTERVAL <= observed_by:
            kp[start] = value
    hourly["kp"] = pd.Series(kp, dtype=float).reindex(hourly.index)
    base = feature_frame(hourly, include_coupling=True, lead_hours=LEAD_HOURS).iloc[[-1]]
    hp_data = parse_hpo(io.StringIO(captures["hp30"]["data"]))
    hp = make_hp30_features(hp_data, base.index, lead_hours=LEAD_HOURS)
    wind = make_hht_features(hro, base.index, lead_hours=LEAD_HOURS)
    return base.join(hp).join(wind)


def collect_once(model, db=FORECAST_DB, *, clock=None, fetch=capture_inputs):
    clock = clock or (lambda: datetime.now(UTC))
    now = clock()
    target = next_start(now)
    cutoff = release_cutoff(target)
    if not cutoff - RELEASE_WINDOW <= now <= cutoff:
        return None
    latest = read_runs(db, latest_only=True)
    if latest and latest[0]["target_start"] == utc_string(target):
        return latest[0]
    captures = fetch()
    received = [timestamp(item["metadata"]["received_at"]) for item in captures.values()]
    if max(received) > cutoff:
        return None
    row = feature_row(captures, target)
    required = [
        "solar_speed_latest", "solar_density_latest", "solar_bt_latest", "solar_bz_latest",
        KP_FEATURE, "hp30_latest", "ap30_log_mean_2h", "hro_bz_mean", "hro_speed_mean",
    ]
    unavailable = [name for name in required if row[name].isna().any()]
    if unavailable:
        LOG.info("Forecast for %s is waiting for %s", target, ", ".join(unavailable))
        return None
    raw, probability = model.predict(row)
    issued = clock()
    if not max(received) <= issued <= cutoff:
        return None
    score = float(probability[0])
    coverage = row[STATS_COLUMNS + HHT_COLUMNS].notna().sum()
    return save_run(db, {
        "state": "ready", "model_id": MODEL_ID, "model_sha256": model.sha256,
        "issued_at": utc_string(issued), "issue_deadline": utc_string(cutoff),
        "target_start": utc_string(target), "target_end": utc_string(target + INTERVAL),
        "lead_minutes": (target - issued).total_seconds() / 60,
        "estimated_kp": float(np.clip(raw[0], 0, 9)), "storm_probability": score,
        "probability_threshold": model.threshold, "elevated_risk": score >= model.threshold,
        "high_resolution_features_present": int(coverage.sum()),
        "high_resolution_features_total": len(coverage),
        "evaluation": "live_unvalidated",
    }, captures, unique_target=True)


def watch(db=FORECAST_DB, model_path=MODEL_PATH):
    model = FinalModel(model_path)
    while True:
        try:
            collect_once(model, db)
        except (OSError, ValueError, OperationalError) as error:
            LOG.warning("Forecast inputs unavailable: %s", error)
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "watch"))
    parser.add_argument("--db", type=Path, default=FORECAST_DB)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "watch":
        watch(args.db, args.model)
    else:
        print(json.dumps(collect_once(FinalModel(args.model), args.db), indent=2))


if __name__ == "__main__":
    main()
