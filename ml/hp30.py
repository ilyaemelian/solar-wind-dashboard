"""GFZ geomagnetic activity inputs for the fixed Hp30 experiment."""

import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests

GFZ = "https://kp.gfz.de/fileadmin/files_for_gfz_cms/"
ARCHIVE_URL = GFZ + "Hp30_ap30_complete_series.txt"
NOWCAST_URL = GFZ + "Hp30_ap30_nowcast.txt"
PROTOCOL_PATH = Path(__file__).with_name("hp30_protocol.json")
START = pd.Timestamp("2013-12-31", tz="UTC")
END = pd.Timestamp("2026-01-01", tz="UTC")
BIN = pd.Timedelta(minutes=30)
ISSUE_BUFFER = pd.Timedelta(minutes=30)


def parse_hpo(source):
    """Read GFZ's whitespace format, whose UTC timestamps are bin starts."""
    rows = pd.read_csv(
        source, sep=r"\s+", header=None, comment="#",
        usecols=[0, 1, 2, 3, 7, 8],
        names=["year", "month", "day", "start_hour", "hp30", "ap30"],
    )
    hours = rows.pop("start_hour")
    if rows.empty or not (hours.between(0, 23.5) & (hours * 2 % 1 == 0)).all():
        raise ValueError("Expected half-hour UTC bins in the GFZ Hp30 file")
    dates = pd.to_datetime(rows[["year", "month", "day"]], utc=True)
    starts = pd.DatetimeIndex(dates + pd.to_timedelta(hours, unit="h"))
    if not starts.is_unique or not starts.is_monotonic_increasing:
        raise ValueError("GFZ Hp30 times must be unique and chronological")
    data = rows[["hp30", "ap30"]].set_axis(starts).astype(float)
    return data.where(data.ge(0) & np.isfinite(data))


def get_archive(cache_dir):
    cache = Path(cache_dir)
    cache.mkdir(exist_ok=True, parents=True)
    path = cache / ARCHIVE_URL.rsplit("/", 1)[-1]
    if path.is_file():
        return read_archive(path)
    with NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with requests.get(ARCHIVE_URL, timeout=(12, 90), stream=True) as response:
            response.raise_for_status()
            with temporary.open("wb") as out:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    out.write(chunk)
        data, manifest = read_archive(temporary)
        temporary.replace(path)
        return data, manifest
    finally:
        temporary.unlink(missing_ok=True)


def read_archive(path):
    data = parse_hpo(path)
    data = data.loc[(data.index >= START) & (data.index < END)]
    expected = pd.date_range(START, END, inclusive="left", freq=BIN)
    if not data.index.equals(expected):
        raise ValueError("GFZ Hp30 does not contain the entire fixed archive window")
    # Hash only the input window. GFZ keeps appending newer values to this file.
    canonical = data.to_csv(header=False, date_format="%Y-%m-%dT%H:%MZ", float_format="%.3f", lineterminator="\n")
    manifest = {
        "source": ARCHIVE_URL,
        "doi": "10.5880/hpo.0003",
        "as_issued": False,
        "start": START.isoformat(),
        "end_exclusive": END.isoformat(),
        "rows": len(data),
        "parsed_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "assumed_buffer_minutes": int(ISSUE_BUFFER / pd.Timedelta(minutes=1)),
    }
    return data, manifest


def make_hp30_features(hpo, targets, *, lead_hours):
    """Use completed bins ending at least 30 minutes before model issuance."""
    ap30 = hpo["ap30"].asfreq("30min")
    last_hour = np.log1p(ap30.rolling(2, min_periods=2).mean())
    features = pd.DataFrame({
        "hp30_latest": hpo["hp30"],
        "ap30_log_mean_2h": np.log1p(ap30.rolling(4, min_periods=3).mean()),
        "ap30_log_change_1h": last_hour - last_hour.shift(2),
    })
    starts = (targets - pd.Timedelta(hours=lead_hours) - ISSUE_BUFFER - BIN).floor("30min")
    return features.reindex(starts).set_axis(targets)


def load_hp30_features(cache_dir, targets, *, lead_hours):
    locked = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    data, manifest = get_archive(cache_dir)
    if manifest != locked:
        raise ValueError("The fixed GFZ Hp30 data differs from the locked input window")
    return make_hp30_features(data, targets, lead_hours=lead_hours), manifest
