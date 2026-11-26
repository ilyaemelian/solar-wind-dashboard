"""Fetch and normalize the public NOAA Space Weather Prediction Center feeds."""

import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock, local

import requests

BASE_URL = "https://services.swpc.noaa.gov/"
CACHE_SECONDS = 60
RETRY_DELAY_SECONDS = 20
MAX_CACHE_AGE = timedelta(hours=24)
KP_INTERVAL = timedelta(hours=3)
LOG = logging.getLogger(__name__)
HTTP = local()
BULLETIN = re.compile(
    r"^(CANCEL[^:]*|EXTENDED WARNING|WATCH|WARNING|ALERT|SUMMARY|UPDATE):\s*.+",
    re.IGNORECASE,
)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing NOAA timestamp")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def utc_string(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def number(value):
    if type(value) in (int, float) and math.isfinite(value):
        return value
    return None


def points(rows, fields, *, telemetry=False, forecast=False):
    result = {}
    for row in rows:
        if telemetry and (row.get("active") is not True or not row.get("source")):
            continue
        if forecast and row.get("observed") != "predicted":
            continue
        try:
            observed_at = utc_string(timestamp(row["time_tag"]))
        except (KeyError, ValueError):
            continue
        values = {}
        for name, upstream in fields.items():
            value = number(row.get(upstream))
            if value is not None and name == "kp" and not 0 <= value <= 9:
                value = None
            if value is not None and name in ("speed", "density") and value < 0:
                value = None
            values[name] = value
        if not any(value is not None for value in values.values()):
            continue
        point = {"time": observed_at, **values}
        if telemetry:
            point["source"] = row["source"]
        result[observed_at] = point
    if not result:
        raise ValueError("NOAA response has no usable measurements")
    return sorted(result.values(), key=lambda point: point["time"])


def bulletins(rows):
    result = {}
    for row in rows:
        product, message = row.get("product_id"), row.get("message")
        if not isinstance(product, str) or not isinstance(message, str) or not message.strip():
            continue
        try:
            issued_at = utc_string(timestamp(row.get("issue_datetime")))
        except ValueError:
            continue
        heading = next(
            (line.strip() for line in message.splitlines() if BULLETIN.match(line.strip())),
            None,
        )
        kind, _, title = heading.partition(":") if heading else ("Bulletin", "", "")
        result[(issued_at, product)] = {
            "time": issued_at,
            "product_id": product,
            "kind": kind.title(),
            "title": title.strip() or product,
            "message": message.replace("\r\n", "\n").strip(),
        }
    if rows and not result:
        raise ValueError("NOAA response has no valid bulletins")
    return sorted(result.values(), key=lambda item: item["time"], reverse=True)


@dataclass(frozen=True)
class Feed:
    path: str
    parse: object
    max_age: timedelta | None = None


FEEDS = {
    "wind": Feed(
        "json/rtsw/rtsw_wind_1m.json",
        lambda rows: points(rows, {"speed": "proton_speed", "density": "proton_density"}, telemetry=True),
        timedelta(minutes=15),
    ),
    "magnetic": Feed(
        "json/rtsw/rtsw_mag_1m.json",
        lambda rows: points(rows, {"bz": "bz_gsm"}, telemetry=True),
        timedelta(minutes=15),
    ),
    "kp": Feed(
        "products/noaa-planetary-k-index.json",
        lambda rows: points(rows, {"kp": "Kp"}),
        timedelta(hours=7),
    ),
    "forecast": Feed(
        "products/noaa-planetary-k-index-forecast.json",
        lambda rows: points(rows, {"kp": "kp"}, forecast=True),
    ),
    "alerts": Feed("products/alerts.json", bulletins),
}


def fetch_json(url):
    if not hasattr(HTTP, "session"):
        HTTP.session = requests.Session()
        HTTP.session.headers.update({"User-Agent": "SolarWindDashboard/2.0", "Accept": "application/json"})
    for attempt in range(2):
        try:
            with HTTP.session.get(url, timeout=(4, 8)) as response:
                response.raise_for_status()
                return response.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code
            if attempt or not 500 <= status < 600:
                raise
        except (requests.ConnectionError, requests.Timeout):
            if attempt:
                raise
        time.sleep(0.25)


@dataclass
class FeedCache:
    fetched_at: datetime | None = None
    data: list | None = None
    retry_at: float = 0
    failed: bool = False


class NOAAClient:
    def __init__(self, fetch=fetch_json):
        self.fetch = fetch
        self.cache = {name: FeedCache() for name in FEEDS}
        self.locks = {name: Lock() for name in FEEDS}
        self.pool = ThreadPoolExecutor(max_workers=len(FEEDS), thread_name_prefix="noaa")

    def _read(self, name):
        feed = FEEDS[name]
        url = BASE_URL + feed.path
        entry = self.cache[name]
        with self.locks[name]:
            if time.monotonic() >= entry.retry_at:
                try:
                    rows = self.fetch(url)
                    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                        raise ValueError("Unexpected NOAA JSON format")
                    data = feed.parse(rows)
                except (OSError, ValueError) as exc:
                    LOG.warning("NOAA %s: %s", name, exc)
                    entry.failed = True
                    entry.retry_at = time.monotonic() + RETRY_DELAY_SECONDS
                else:
                    entry.data = data
                    entry.fetched_at = datetime.now(UTC)
                    entry.failed = False
                    entry.retry_at = time.monotonic() + CACHE_SECONDS
            return self._describe(name, entry, url, datetime.now(UTC))

    @staticmethod
    def _describe(name, entry, url, now):
        data = entry.data
        state = "unavailable"
        if data is not None and now - entry.fetched_at <= MAX_CACHE_AGE:
            state = "cached" if entry.failed else "live"
            if name == "forecast":
                data = [point for point in data if timestamp(point["time"]) + KP_INTERVAL > now]
                if not data:
                    state = "unavailable"
            elif FEEDS[name].max_age:
                latest = timestamp(data[-1]["time"])
                if not entry.failed and now - latest > FEEDS[name].max_age:
                    state = "delayed"
        return {
            "state": state,
            "source_url": url,
            "fetched_at": utc_string(entry.fetched_at) if entry.fetched_at else None,
            "data": data if state != "unavailable" else [],
        }

    def snapshot(self):
        feeds = dict(zip(FEEDS, self.pool.map(self._read, FEEDS)))
        return {"generated_at": utc_string(datetime.now(UTC)), "feeds": feeds}
