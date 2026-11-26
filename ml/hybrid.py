"""Train the live-lead Ridge candidates and collect paired NOAA/GFZ shadow forecasts."""

import argparse
import hashlib
import io
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import joblib
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import average_precision_score, brier_score_loss
from threadpoolctl import threadpool_limits

from ml.data import KP_FEATURE, STORM_KP, feature_frame, load_archive, make_examples
from ml.hp30 import BIN as HP30_BIN, NOWCAST_URL as HP30_URL, parse_hpo
from ml.train import PROTOCOL_PATH, SPLITS, predict_storm_probability, scaled_linear_pipeline
from src.hybrid_store import DEFAULT_DB, read_runs, save_run
from src.noaa import BASE_URL, FEEDS, number, timestamp, utc_string

GFZ_URL = "https://spaceweather.gfz.de/fileadmin/Kp-Forecast/CSV/kp_product_file_FORECAST_PAGER_SWIFT_LAST.json"
GFZ_LABELS = "https://kp.gfz.de/app/json/"
URLS = {"gfz": GFZ_URL, **{name: BASE_URL + FEEDS[name].path for name in ("wind", "magnetic", "kp")}}
DEFAULT_MODEL = DEFAULT_DB.with_name("hybrid_ridge.joblib")
LEADS = (1, 2, 3)
MIN_HOURLY_MINUTES = 30
GFZ_MAX_AGE = timedelta(hours=3)
POLICY = "equal_weight_shadow_v1"
LOG = logging.getLogger(__name__)


def invalid_json_constant(value):
    raise ValueError(f"Non-finite upstream JSON value: {value}")


def train_ridge(cache_dir, model_path):
    hourly, inputs = load_archive(SPLITS["train"][0], SPLITS["calibration"][1], cache_dir)
    locked = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))["archive_sha256"]
    if any(item["sha256"] != locked[str(item["year"])] for item in inputs):
        raise ValueError("Live Ridge must be trained with the pinned OMNI files")
    horizons = {}
    for lead in LEADS:
        rows, features = make_examples(hourly, include_coupling=True, lead_hours=lead)
        train = rows.loc[rows.index.year <= SPLITS["train"][1]]
        calibration = rows.loc[rows.index.year == SPLITS["calibration"][1]]
        model = scaled_linear_pipeline(Ridge(alpha=10)).fit(train[features], train["target_kp"])
        scores = model.predict(calibration[features]).reshape(-1, 1)
        calibrator = LogisticRegression(max_iter=1000).fit(scores, calibration["storm"])
        horizons[lead] = {
            "model": model, "calibrator": calibrator, "features": features,
            "score_method": "predict",
        }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = model_path.with_suffix(".tmp")
    joblib.dump({"horizons": horizons, "sources": inputs, "training_domain": "NASA OMNI"}, temporary, compress=3)
    temporary.replace(model_path)


def fetch_capture(item):
    name, url = item
    try:
        for attempt in range(2):
            try:
                with requests.get(url, timeout=(4, 10), headers={"User-Agent": "SolarWindDashboard/2.0"}) as response:
                    response.raise_for_status()
                    data = response.text if name == "hp30" else response.json(parse_constant=invalid_json_constant)
                    modified = response.headers.get("Last-Modified")
                    received_at = datetime.now(UTC)
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise
        if name == "gfz" and not isinstance(data, dict):
            raise ValueError("Expected GFZ columns")
        if name not in {"gfz", "hp30"} and (not isinstance(data, list) or not all(isinstance(row, dict) for row in data)):
            raise ValueError("Expected NOAA records")
        metadata = {"url": url, "received_at": utc_string(received_at), "last_modified": modified}
        if name == "hp30":
            observations = parse_hpo(io.StringIO(data)).dropna()
            completed = observations.index[observations.index + HP30_BIN <= received_at]
            if completed.empty:
                raise ValueError("No completed Hp30 interval")
            metadata["latest_completed_end"] = utc_string(completed[-1] + HP30_BIN)
        return name, {"data": data, "metadata": metadata}
    except (requests.RequestException, ValueError) as exc:
        LOG.warning("%s unavailable: %s", name, exc)
        return name, {"data": None, "metadata": {"url": url, "checked_at": utc_string(datetime.now(UTC)), "error": str(exc)}}


def forecast_window(issued_at):
    anchor = issued_at.replace(minute=0, second=0, microsecond=0)
    lead = 3 - anchor.hour % 3
    return anchor, anchor + timedelta(hours=lead), lead


def gfz_signal(capture, target, issued_at):
    payload = capture["data"]
    if payload is None:
        return None, "source_unavailable"
    try:
        modified = parsedate_to_datetime(capture["metadata"]["last_modified"] or "").astimezone(UTC)
        if not timedelta(0) <= issued_at - modified <= GFZ_MAX_AGE:
            return None, "stale_or_future_file"
        times = payload["Time (UTC)"]
        if not isinstance(times, dict):
            return None, "invalid_time_column"
        key = next((key for key, value in times.items()
                    if datetime.strptime(value, "%d-%m-%Y %H:%M").replace(tzinfo=UTC) == target), None)
        if key is None:
            return None, "no_exact_target_interval"
        members = [number(columns.get(key)) for name, columns in payload.items()
                   if re.fullmatch(r"kp_\d+", name) and isinstance(columns, dict)]
        members = [value for value in members if value is not None and 0 <= value <= 9]
        if len(members) < 3:
            return None, "too_few_valid_members"
    except (KeyError, ValueError, TypeError, OverflowError):
        return None, "invalid_forecast"
    return {
        "storm_fraction": sum(value >= STORM_KP for value in members) / len(members),
        "member_count": len(members),
        "median_kp": float(pd.Series(members).median()),
    }, None


def hourly_measurements(rows, fields):
    columns = list(fields)
    samples = []
    for row in rows:
        if row.get("active") is not True or row.get("overall_quality") != 0 or not row.get("source"):
            continue
        try:
            measured_at = pd.Timestamp(timestamp(row["time_tag"])).floor("min")
        except (ValueError, KeyError):
            continue
        samples.append({
            "time": measured_at, "source": row["source"],
            **{name: number(row.get(key)) for name, key in fields.items()},
        })
    if not samples:
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], tz="UTC"))
    seen = pd.DataFrame(samples).drop_duplicates(subset=["time", "source"])
    seen[columns] = seen[columns].astype(float)
    seen["hour"] = seen["time"].dt.floor("h")
    groups = seen.groupby(["hour", "source"])
    counts = groups[columns].count()
    hourly = groups[columns].mean().where(counts >= MIN_HOURLY_MINUTES)
    # Pick one primary spacecraft per hour. A switch that leaves neither side
    # with sufficient coverage is handled as missing, not stitched together.
    ranked = groups.size().rename("samples").to_frame().join(hourly).reset_index()
    ranked = ranked.sort_values(["hour", "samples", "source"], ascending=[True, False, True])
    return ranked.drop_duplicates("hour").set_index("hour")[columns]


def ridge_signal(captures, target, lead, artifact):
    if artifact is None:
        return None, "ridge_artifact_unavailable"
    if any(captures[name]["data"] is None for name in ("wind", "magnetic", "kp")):
        return None, "noaa_source_unavailable"
    index = pd.date_range(end=target, periods=16 + lead, freq="h", tz="UTC")
    wind = hourly_measurements(captures["wind"]["data"], {"speed": "proton_speed", "density": "proton_density"})
    magnetic = hourly_measurements(captures["magnetic"]["data"], {"bt": "bt", "by": "by_gsm", "bz": "bz_gsm"})
    hourly = pd.DataFrame(index=index).join(wind).join(magnetic)
    kp = {}
    for row in captures["kp"]["data"]:
        value = number(row.get("Kp"))
        if value is None or not 0 <= value <= 9:
            continue
        try:
            measured_at = timestamp(row["time_tag"])
        except (KeyError, ValueError):
            continue
        kp[measured_at] = value
    hourly["kp"] = pd.Series(kp, dtype=float).reindex(index)
    features = feature_frame(hourly, include_coupling=True, lead_hours=lead).iloc[[-1]]
    required = ["solar_speed_latest", "solar_density_latest", "solar_bt_latest",
                "solar_bz_latest", "coupling_newell_latest", KP_FEATURE]
    if features[required].isna().any(axis=None):
        return None, "insufficient_telemetry_or_recent_kp"
    model = artifact["horizons"][lead]
    raw = float(model["model"].predict(features[model["features"]])[0])
    probability = float(predict_storm_probability(model, features)[0])
    return {"estimated_kp": min(9.0, max(0.0, raw)), "storm_probability": probability}, None


def collect_once(db_path, model_path, *, capture_hp30=False):
    artifact, model_hash = None, None
    if model_path.is_file():
        blob = model_path.read_bytes()
        artifact = joblib.load(io.BytesIO(blob))
        model_hash = hashlib.sha256(blob).hexdigest()
    urls = {**URLS, "hp30": HP30_URL} if capture_hp30 else URLS
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        captures = dict(pool.map(fetch_capture, urls.items()))
    issued_at = datetime.now(UTC)
    anchor, target, lead = forecast_window(issued_at)
    gfz, gfz_error = gfz_signal(captures["gfz"], target, issued_at)
    ridge, ridge_error = ridge_signal(captures, target, lead, artifact)
    score = (gfz["storm_fraction"] + ridge["storm_probability"]) / 2 if gfz and ridge else None
    return save_run(db_path, {
        "policy": POLICY, "mode": "shadow", "issued_at": utc_string(issued_at),
        "feature_anchor": utc_string(anchor), "model_lead_hours": lead,
        "target_start": utc_string(target), "target_end": utc_string(target + timedelta(hours=3)),
        "ridge_model_sha256": model_hash, "ridge_input_domain": "NOAA RTSW L1",
        "ridge_training_domain": "NASA OMNI", "ridge": ridge, "gfz": gfz, "hybrid_score": score,
        "state": "paired" if score is not None else "component_only" if ridge or gfz else "unavailable",
        "unavailable_reasons": {name: error for name, error in (("gfz", gfz_error), ("ridge", ridge_error)) if error},
    }, captures)


def evaluate_runs(db_path, min_lead_minutes, max_lead_minutes=None, *, label_mode="definitive", now=None):
    # Keep the last paired forecast at or before the requested lead for each target.
    now = now if now is not None else datetime.now(UTC)
    matched = {}
    model_hash = None
    for row in read_runs(db_path):
        lead = (timestamp(row["target_start"]) - timestamp(row["issued_at"])).total_seconds() / 60
        if row["policy"] != POLICY or row["state"] != "paired":
            continue
        if model_hash is None:
            model_hash = row["ridge_model_sha256"]
        if row["ridge_model_sha256"] != model_hash or lead < min_lead_minutes:
            continue
        if max_lead_minutes is None or lead <= max_lead_minutes:
            matched.setdefault(row["target_start"], row)
    completed = {key: row for key, row in matched.items() if timestamp(key) + timedelta(hours=3) <= now}
    known = []
    preliminary_count = 0
    if completed:
        params = {
            "start": timestamp(min(completed)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": timestamp(max(completed)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "index": "Kp",
        }
        if label_mode == "definitive":
            params["status"] = "def"
        response = requests.get(GFZ_LABELS, params=params, timeout=(4, 15))
        response.raise_for_status()
        payload = response.json()
        allowed = {"def"} if label_mode == "definitive" else {"def", "pre"}
        labels = {
            utc_string(timestamp(t)): (kp, status)
            for t, kp, status in zip(payload["datetime"], payload["Kp"], payload["status"], strict=True)
            if status in allowed and number(kp) is not None and 0 <= kp <= 9
        }
        known = [(row, int(labels[key][0] >= STORM_KP)) for key, row in completed.items() if key in labels]
        preliminary_count = sum(labels[key][1] == "pre" for key in completed.keys() & labels.keys())
    y = [value for _, value in known]
    result = {
        "scored_at": utc_string(now), "label_mode": label_mode, "label_source": GFZ_LABELS,
        "paired_forecasts": len(matched), "completed_intervals": len(completed),
        "labeled_intervals": len(known), "preliminary_labels": preliminary_count, "storm_intervals": sum(y),
        "minimum_actual_lead_minutes": min_lead_minutes, "maximum_actual_lead_minutes": max_lead_minutes,
        "ridge_model_sha256": model_hash, "metrics": None,
    }
    if y:
        scores = {
            "ridge": [row["ridge"]["storm_probability"] for row, _ in known],
            "gfz": [row["gfz"]["storm_fraction"] for row, _ in known],
            "hybrid": [row["hybrid_score"] for row, _ in known],
        }
        result["metrics"] = {
            name: {
                "average_precision": float(average_precision_score(y, score)) if len(set(y)) == 2 else None,
                "brier": float(brier_score_loss(y, score)),
            } for name, score in scores.items()
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--cache-dir", type=Path, default=Path(".ml-cache"))
    collect = commands.add_parser("collect")
    watch = commands.add_parser("watch")
    watch.add_argument("--minutes", type=int, default=15)
    for collector in (collect, watch):
        collector.add_argument("--capture-hp30", action="store_true", help="Save a GFZ Hp30 nowcast snapshot")
    evaluation = commands.add_parser("diagnose-live", help="Inspect collected forecasts outside the fixed model benchmark")
    evaluation.add_argument("--min-lead-minutes", type=int, default=60)
    evaluation.add_argument("--max-lead-minutes", type=int)
    evaluation.add_argument("--labels", choices=("preliminary", "definitive"), default="definitive")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "train":
        with threadpool_limits(limits=2):
            train_ridge(args.cache_dir, args.model)
        print(args.model)
    elif args.command == "collect":
        print(json.dumps(collect_once(args.db, args.model, capture_hp30=args.capture_hp30), indent=2))
    elif args.command == "diagnose-live":
        if args.min_lead_minutes < 1:
            parser.error("--min-lead-minutes must be positive")
        if args.max_lead_minutes is not None and args.max_lead_minutes < args.min_lead_minutes:
            parser.error("--max-lead-minutes must be at least --min-lead-minutes")
        print(json.dumps(evaluate_runs(args.db, args.min_lead_minutes, args.max_lead_minutes, label_mode=args.labels), indent=2))
    else:
        if args.minutes < 1:
            parser.error("--minutes must be positive")
        try:
            while True:
                print(json.dumps(collect_once(args.db, args.model, capture_hp30=args.capture_hp30)), flush=True)
                time.sleep(args.minutes * 60)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
