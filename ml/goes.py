"""Build causal GOES XRS features from NOAA's yearly L2 science archives."""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests

NOAA = "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/"
LEGACY = "https://www.ncei.noaa.gov/data/goes-space-environment-monitor/access/science/xrs/"
GOES_LOCK = Path(__file__).with_name("goes_protocol.json")
FEATURES = ("goes_soft_background_log", "goes_hard_soft_ratio_log")
LAG_HOURS = 48
HOUR_MINUTES = 30
BACKGROUND_MINUTES = 720
SWITCH_TO_19 = pd.Timestamp("2025-04-07", tz="UTC")


def archive_plan():
    """Fix instruments and versions before looking at any model result."""
    for year in range(2013, 2026):
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        if year <= 2017:
            yield 15, year, start, end
        elif year < 2025:
            yield 16, year, start, end
        else:
            yield 16, year, start, SWITCH_TO_19
            yield 19, year, SWITCH_TO_19, end


def archive_url(satellite, year):
    directory = f"goes{satellite}/xrsf-l2-avg1m_science/" if satellite == 15 else f"goes{satellite}/l2/data/xrsf-l2-avg1m_science/"
    version = "2-2-1" if satellite == 15 else "2-2-2"
    return (LEGACY if satellite == 15 else NOAA) + directory + f"sci_xrsf-l2-avg1m_g{satellite}_y{year}_v{version}.nc"


def fetch_source(cache, item):
    satellite, year, start, end = item
    url = archive_url(satellite, year)
    path = cache / url.rsplit("/", 1)[-1]
    if not path.is_file():
        for attempt in range(3):
            with NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as handle:
                temporary = Path(handle.name)
            try:
                with requests.get(url, timeout=(15, 60), stream=True) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as destination:
                        for chunk in response.iter_content(chunk_size=256 * 1024):
                            destination.write(chunk)
                with temporary.open("rb") as downloaded:
                    if downloaded.read(8) != b"\x89HDF\r\n\x1a\n":
                        raise ValueError(f"Expected a NetCDF4 file from {url}")
                temporary.replace(path)
                break
            except requests.RequestException as exc:
                if attempt == 2 or (exc.response is not None and exc.response.status_code == 404):
                    raise
                time.sleep(2 ** attempt)
            finally:
                temporary.unlink(missing_ok=True)
    with path.open("rb") as source:
        sha = hashlib.file_digest(source, "sha256").hexdigest()
    return path, start, end, {"source": url, "sha256": sha, "start": start.isoformat(), "end": end.isoformat()}


def load_sources(cache_dir):
    expected = json.loads(GOES_LOCK.read_text(encoding="utf-8"))
    cache = Path(cache_dir) / "goes"
    cache.mkdir(exist_ok=True, parents=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda item: fetch_source(cache, item), archive_plan()))
    manifest = [record[3] for record in records]
    if expected != manifest:
        raise ValueError("The GOES input archive differs from the locked version")
    return records, manifest


def flux_values(dataset, channel):
    values = np.ma.asarray(dataset[f"xrs{channel}_flux"][:], dtype=np.float32).filled(np.nan)
    quality = np.ma.asarray(dataset[f"xrs{channel}_flag"][:], dtype=np.int64).filled(-1)
    values[(quality != 0) | (values <= 0) | ~np.isfinite(values)] = np.nan
    return values


def read_minutes(path, start, end):
    from netCDF4 import Dataset

    with closing(Dataset(path)) as dataset:
        time_var = dataset["time"]
        units = time_var.units
        unit, epoch = units.split(" since ", 1)
        if unit.lower() not in {"seconds", "second"}:
            raise ValueError(f"Unexpected time units in {path.name}: {units}")
        offset = np.ma.asarray(time_var[:], dtype=float).filled(np.nan)
        offsets = pd.to_timedelta(offset, unit="s")
        index = (pd.Timestamp(epoch).as_unit("ns") + offsets)
        index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
        mask = (index >= start) & (index < end)
        values = {channel: flux_values(dataset, channel)[mask] for channel in ("a", "b")}
    # Some products time-tag the minute near its center.
    frame = pd.DataFrame(values, index=index[mask].floor("min"))
    return frame[~frame.index.duplicated(keep="first")].sort_index()


def make_goes_features(minutes, targets, *, lead_hours):
    """Align completed GOES hours to issuance minus 48h on the frozen rows."""
    logged_soft = np.log10(minutes["b"])
    background = logged_soft.rolling("24h", min_periods=BACKGROUND_MINUTES).min()
    ratio = np.log10(minutes["a"]) - logged_soft
    rolling = pd.DataFrame({FEATURES[0]: background, FEATURES[1]: ratio}, index=minutes.index)
    bins = rolling.resample("h", label="right", closed="left")
    hourly = pd.DataFrame({
        FEATURES[0]: bins[FEATURES[0]].mean(),
        FEATURES[1]: bins[FEATURES[1]].median(),
    }).where(bins.count() >= HOUR_MINUTES)
    lagged_ends = targets - pd.Timedelta(hours=lead_hours + LAG_HOURS)
    return hourly.reindex(lagged_ends).set_axis(targets)


def load_goes_features(cache_dir, targets, *, lead_hours):
    records, manifest = load_sources(cache_dir)
    minutes = pd.concat([read_minutes(path, start, end) for path, start, end, _ in records])
    if not minutes.index.is_unique or not minutes.index.is_monotonic_increasing:
        raise ValueError("GOES source ranges must be unique and chronological")
    return make_goes_features(minutes, targets, lead_hours=lead_hours), manifest
