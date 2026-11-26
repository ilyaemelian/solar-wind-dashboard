"""Build trailing solar-wind statistics and Hilbert–Huang features."""

import calendar
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd
import requests

from ml.data import coupling_terms

PROTOCOL_PATH = Path(__file__).with_name("hht_protocol.json")
STEP = pd.Timedelta(minutes=5)
WINDOW = 36
REPORTING_BUFFER_HOURS = 1
# Zero-based columns in NASA OMNI's common high-resolution text format.
COLUMNS = {
    0: "year", 1: "day", 2: "hour", 3: "minute",
    13: "bt", 17: "by", 18: "bz", 21: "speed", 25: "density", 27: "pressure",
}
FILL = {"bt": 9999.99, "by": 9999.99, "bz": 9999.99,
        "speed": 99999.9, "density": 999.99, "pressure": 99.99}
STATS_FIELDS = ("bt", "bz", "speed", "density", "pressure")
HHT_FIELDS = ("bz", "newell")
STATS_COLUMNS = [f"hro_{name}_{stat}" for name in STATS_FIELDS for stat in ("min", "max", "mean")]
HHT_COLUMNS = [
    f"hht_{name}_{stat}" for name in HHT_FIELDS
    for stat in ("count", "log_energy", "log_peak_amplitude", "peak_frequency")
]


def source_file(cache, source):
    url = source["source"]
    path = cache / url.rsplit("/", 1)[-1]
    if path.is_file():
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != source["sha256"]:
                raise ValueError(f"Pinned OMNI HRO input changed: {path.name}")
        return path
    for attempt in range(3):
        with NamedTemporaryFile(dir=cache, suffix=".part", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            digest = hashlib.sha256()
            with requests.get(url, timeout=(15, 90), stream=True) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        digest.update(chunk)
                        handle.write(chunk)
            if digest.hexdigest() != source["sha256"]:
                raise ValueError(f"Pinned OMNI HRO input changed: {path.name}")
            temporary.replace(path)
            return path
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        finally:
            temporary.unlink(missing_ok=True)


def read_year(path, year):
    expected = (365 + calendar.isleap(year)) * 288
    rows = pd.read_csv(path, sep=r"\s+", header=None, usecols=list(COLUMNS), dtype=float).rename(columns=COLUMNS)
    offsets = ((rows["day"] - 1) * 24 + rows["hour"]) * 60 + rows["minute"]
    if (len(rows) != expected or not rows["year"].eq(year).all()
            or not np.array_equal(offsets.to_numpy(), np.arange(expected) * 5)):
        raise ValueError(f"{path.name} must contain every consecutive five-minute bin")
    fields = rows[list(FILL)].mask(rows[list(FILL)].eq(pd.Series(FILL)))
    fields.index = pd.date_range(f"{year}-01-01", periods=expected, freq=STEP, tz="UTC")
    fields["newell"] = coupling_terms(fields["speed"], fields["density"], fields["by"], fields["bz"])["newell"]
    return fields


def hht_chunk(windows):
    from PyEMD import EMD
    from scipy.signal import hilbert

    features = np.full((len(windows), len(HHT_FIELDS) * 4), np.nan)
    emd = EMD()
    for row, channels in enumerate(windows):
        for col, original in enumerate(channels):
            signal = original.copy()
            missing = ~np.isfinite(signal)
            isolated = missing[1:-1] & ~missing[:-2] & ~missing[2:]
            signal[1:-1][isolated] = (signal[:-2][isolated] + signal[2:][isolated]) / 2
            if not np.isfinite(signal).all():
                continue
            emd.emd(signal)
            imfs, _ = emd.get_imfs_and_residue()
            output = features[row, col * 4:(col + 1) * 4]
            if len(imfs) == 0:
                output[:] = 0
                continue
            analytic = hilbert(imfs, axis=1)
            amplitudes = np.abs(analytic)
            peak = np.unravel_index(amplitudes.argmax(), amplitudes.shape)
            phase = np.unwrap(np.angle(analytic[peak[0]]))
            frequency_per_hour = np.gradient(phase) * (12 / (2 * np.pi))
            output[:] = (
                len(imfs), np.log1p(np.square(amplitudes).sum()),
                np.log1p(amplitudes[peak]), frequency_per_hour[peak[1]],
            )
    return features


def make_hht_features(hro, targets, *, lead_hours, workers=1):
    """Decompose each completed three-hour window independently."""
    cutoff = targets - pd.Timedelta(hours=lead_hours + REPORTING_BUFFER_HOURS)
    starts = hro.index.get_indexer(cutoff - STEP * WINDOW)
    if (starts < 0).any() or (starts + WINDOW > len(hro)).any():
        raise ValueError("HRO archive does not cover the requested trailing windows")
    indices = starts[:, None] + np.arange(WINDOW)
    values = hro[list(STATS_FIELDS)].to_numpy()[indices]
    available = np.isfinite(values)
    missing = available.sum(axis=1) < 27
    minimum = np.min(values, axis=1, where=available, initial=np.inf)
    maximum = np.max(values, axis=1, where=available, initial=-np.inf)
    count = available.sum(axis=1)
    mean = np.divide(np.nansum(values, axis=1), count, where=count > 0, out=np.full_like(minimum, np.nan))
    stats = np.stack([np.where(missing, np.nan, x) for x in (minimum, maximum, mean)], axis=-1)
    windows = hro[list(HHT_FIELDS)].to_numpy()[indices].transpose(0, 2, 1)
    if workers == 1:
        decomposed = hht_chunk(windows)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            chunks = np.array_split(windows, workers * 4)
            decomposed = np.concatenate(list(pool.map(hht_chunk, chunks)))
    return pd.DataFrame(np.column_stack((stats.reshape(len(targets), -1), decomposed)),
                        index=targets, columns=STATS_COLUMNS + HHT_COLUMNS)


def load_hht_features(cache_dir, targets, *, lead_hours, workers=4):
    cache = Path(cache_dir) / "hro5"
    cache.mkdir(exist_ok=True, parents=True)
    manifest = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    dependencies = {name: version(name) for name in ("EMD-signal", "numpy", "scipy", "pandas")}
    key = hashlib.sha256()
    key.update(Path(__file__).read_bytes())
    key.update(json.dumps([manifest, dependencies, lead_hours], sort_keys=True).encode())
    key.update(targets.asi8.tobytes())
    dest = cache / f"features-{key.hexdigest()[:16]}.npz"
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda source: source_file(cache, source), manifest))
    if dest.is_file():
        with np.load(dest, allow_pickle=False) as saved:
            features = pd.DataFrame(saved["values"], index=targets, columns=STATS_COLUMNS + HHT_COLUMNS)
    else:
        hro = pd.concat([read_year(path, source["year"]) for path, source in zip(paths, manifest)])
        features = make_hht_features(hro, targets, lead_hours=lead_hours, workers=workers)
        with NamedTemporaryFile(dir=cache, suffix=".npz", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            np.savez_compressed(temporary, values=features.to_numpy())
            temporary.replace(dest)
        finally:
            temporary.unlink(missing_ok=True)
    return features, {"data": manifest, "dependencies": dependencies, "as_issued": False}
