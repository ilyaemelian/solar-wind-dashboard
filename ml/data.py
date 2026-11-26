"""Load NASA's hourly OMNI archive and build time-aligned forecast examples."""

import calendar
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests

ARCHIVE = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/"
# Zero-based positions in NASA's 56-word hourly ASCII record.
COLUMNS = {0: "year", 1: "day", 2: "hour", 8: "bt", 15: "by", 16: "bz", 23: "density", 24: "speed", 38: "kp"}
FILL = {"bt": 999.9, "by": 999.9, "bz": 999.9, "density": 999.9, "speed": 9999.0, "kp": 99}
STORM_KP = 5.0
KP_FEATURE = "kp_last_available"
COUPLING_PREFIX = "coupling_"


def read_year(path, year, *, through=None):
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    expected = (365 + calendar.isleap(year)) * 24
    if through is not None:
        expected = int((pd.Timestamp(through, tz="UTC") - start) / pd.Timedelta(hours=1))
    data = pd.read_csv(
        path, sep=r"\s+", header=None, usecols=list(COLUMNS), dtype=float,
        nrows=expected if through is not None else None,
    ).rename(columns=COLUMNS)
    if len(data) != expected or not data["year"].eq(year).all():
        raise ValueError(f"{path.name} does not contain the requested {expected} hours")
    offsets = (data.pop("day") - 1) * 24 + data.pop("hour")
    if not np.array_equal(offsets.to_numpy(), np.arange(expected)):
        raise ValueError(f"{path.name} does not contain consecutive hourly records")
    data = data.drop(columns="year")
    data.index = pd.date_range(start, periods=expected, freq="h")
    for name, fill in FILL.items():
        data[name] = data[name].mask(data[name].eq(fill))
    data["kp"] = data["kp"].where(data["kp"].between(0, 90)) / 10
    return data


def load_year(year, cache, *, through=None):
    name = f"omni2_{year}.dat"
    path = cache / name
    if path.is_file():
        data = read_year(path, year, through=through)
    else:
        for attempt in range(3):
            try:
                data = download_year(path, year, through=through)
                break
            except requests.RequestException as exc:
                status = exc.response.status_code if exc.response is not None else None
                if attempt == 2 or (status is not None and status < 500 and status != 429):
                    raise
                time.sleep(2 ** attempt)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return data, {"year": year, "source": ARCHIVE + name, "sha256": digest}


def download_year(path, year, *, through=None):
    with NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with requests.get(ARCHIVE + path.name, timeout=(15, 60), stream=True) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=65_536):
                    handle.write(chunk)
        data = read_year(temporary, year, through=through)
        temporary.replace(path)
        return data
    finally:
        temporary.unlink(missing_ok=True)


def load_archive(start, end, cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda year: load_year(year, cache), range(start, end + 1)))
    return pd.concat([data for data, _ in results]), [entry for _, entry in results]


def coupling_terms(speed, density, by, bz):
    """Newell magnetic merging and viscous terms, with the magnetic field in GSM."""
    speed = speed.where(speed >= 0)
    density = density.where(density >= 0)
    transverse = np.hypot(by, bz)
    clock_angle = np.arctan2(by.abs(), bz)
    newell = speed.pow(4 / 3) * transverse.pow(2 / 3) * np.sin(clock_angle / 2).pow(8 / 3)
    return pd.DataFrame({"newell": newell, "viscous": density.pow(0.5) * speed.pow(2)})


def feature_frame(hourly, *, include_coupling=False, lead_hours=0):
    """Build target-indexed features using only data available at target minus lead."""
    # OMNI row h represents [h, h+1). Require one additional hour before use.
    solar_lag = 2 + lead_hours
    solar = hourly[["speed", "density", "bt", "bz"]].shift(solar_lag)
    solar["southward_bz"] = (-solar["bz"]).clip(lower=0)
    solar["southward_e"] = solar["speed"] * solar["southward_bz"] * 1e-3
    solar["pressure_proxy"] = 1.6726e-6 * solar["density"] * solar["speed"].pow(2)

    features = {"solar_" + name + "_latest": solar[name] for name in solar}
    for window in (3, 6, 12):
        rolling = solar.rolling(window, min_periods=(window + 1) // 2)
        features.update({f"solar_{name}_mean_{window}h": series for name, series in rolling.mean().items()})
        features[f"solar_bz_min_{window}h"] = rolling["bz"].min()
        features[f"solar_southward_e_max_{window}h"] = rolling["southward_e"].max()
    # Use completed three-hour bins with an extra three-hour reporting buffer.
    kp_lag = 6 + 3 * ((lead_hours + 2) // 3)
    features[KP_FEATURE] = hourly["kp"].shift(kp_lag)
    features["kp_change_3h"] = hourly["kp"].shift(kp_lag) - hourly["kp"].shift(kp_lag + 3)

    if include_coupling:
        coupling = coupling_terms(solar["speed"], solar["density"], hourly["by"].shift(solar_lag), solar["bz"])
        features.update({f"{COUPLING_PREFIX}{name}_latest": series for name, series in coupling.items()})
        for window in (3, 6, 12):
            rolling = coupling.rolling(window, min_periods=(window + 1) // 2)
            features.update({f"{COUPLING_PREFIX}{name}_mean_{window}h": series for name, series in rolling.mean().items()})

    return pd.DataFrame(features, index=hourly.index)


def make_examples(hourly, *, include_coupling=False, lead_hours=0):
    """Label target bins with their final Kp using an explicit issuance lead."""
    frame = feature_frame(hourly, include_coupling=include_coupling, lead_hours=lead_hours)
    features = frame.columns.to_list()
    frame["target_kp"] = hourly["kp"]
    frame["previous_kp"] = hourly["kp"].shift(3)  # Evaluation-only onset flag.
    frame = frame.loc[(frame.index.hour % 3 == 0) & frame["target_kp"].notna()].copy()
    frame = frame.loc[frame.index >= hourly.index[0] + pd.Timedelta(hours=13 + lead_hours)].copy()
    frame["storm"] = (frame["target_kp"] >= STORM_KP).astype(int)
    return frame, features
