const HOUR = 3_600_000;
const states = { live: "Live", delayed: "Delayed", cached: "Cached", unavailable: "Unavailable" };
const kpLevels = {
  low: "Low",
  elevated: "Elevated",
  storm: "Storm",
};
const style = getComputedStyle(document.documentElement);
const kpColors = Object.fromEntries(Object.keys(kpLevels).map((level) => [level, style.getPropertyValue("--" + level).trim()]));
const kpLevel = (value) => value >= 5 ? "storm" : value >= 4 ? "elevated" : "low";
const metrics = {
  speed: { feed: "wind", precision: 1, unit: "km/s", maxAge: 15 * 60_000 },
  density: { feed: "wind", precision: 2, unit: "cm⁻³", maxAge: 15 * 60_000 },
  bz: { feed: "magnetic", precision: 2, unit: "nT", maxAge: 15 * 60_000 },
  kp: { feed: "kp", precision: 2, unit: "Kp", maxAge: 7 * HOUR },
};
const chartOptions = {
  speed: { ...metrics.speed, color: "#92afff", gap: 5 * 60_000 },
  bz: { ...metrics.bz, color: "#c4a0ff", gap: 5 * 60_000 },
  kp: { ...metrics.kp, color: "#a2a6d1", gap: 3 * HOUR, kpScale: true },
  forecast: { ...metrics.kp, feed: "forecast", kpScale: true, bars: true },
};

const select = (query) => document.querySelector(query);
const timezone = select("#timezone");
const filter = select("#bulletin-filter");
const more = select("#more-bulletins");
const refresh = select("#refresh");
const chartViews = new Map();
const dateFormat = (options) => new Intl.DateTimeFormat("en-GB", {
  timeZone: timezone.value, hourCycle: "h23", ...options,
});
const zoneName = () => timezone.value === "UTC" ? "UTC" : "SGT";
const fullTime = (ms) => dateFormat({
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
}).format(ms) + " " + zoneName();

let snapshot = null;
let requestFailed = false;
let loading = false;
let hours = 24;
let bulletinLimit = 8;

function setStatus(element, state, label = states[state]) {
  if (element.dataset.state !== state) element.dataset.state = state;
  if (element.textContent !== label) element.textContent = label;
}

function recentPoints(feed, key, end = Infinity, start = -Infinity) {
  return (feed?.data ?? [])
    .filter((row) => Number.isFinite(row[key]))
    .map((row) => ({ t: Date.parse(row.time), value: row[key], source: row.source }))
    .filter((point) => point.t >= start && point.t <= end);
}

function displayState(feed, latest, age) {
  if (!snapshot || !feed) return requestFailed ? "unavailable" : "loading";
  if (feed.state === "unavailable") return "unavailable";
  if (requestFailed) return "cached";
  if (latest && Date.parse(snapshot.generated_at) - latest.t > age) return "delayed";
  return feed.state;
}

function renderMetrics() {
  const now = Date.parse(snapshot?.generated_at);
  for (const [key, config] of Object.entries(metrics)) {
    const node = select('[data-metric="' + key + '"]');
    const feed = snapshot?.feeds[config.feed];
    const point = recentPoints(feed, key, now).at(-1);
    const state = displayState(feed, point, config.maxAge);
    node.querySelector("strong").textContent = point ? point.value.toFixed(config.precision) : "—";
    const parts = point ? [point.source, fullTime(point.t)] : [];
    if (state !== "live") parts.push(states[state] || "Waiting for NOAA");
    else if (!point) parts.push("No measurement");
    node.querySelector(".measurement").textContent = parts.filter(Boolean).join(" · ");
    if (key === "kp") {
      const badge = select("#kp-level");
      badge.hidden = !point;
      if (point) {
        node.dataset.level = kpLevel(point.value);
        badge.textContent = kpLevels[node.dataset.level];
      } else {
        delete node.dataset.level;
      }
    }
  }
}

function niceStep(span) {
  const rough = span / 4;
  const base = 10 ** Math.floor(Math.log10(rough));
  return ([1, 2, 2.5, 5, 10].find((n) => n * base >= rough) ?? 10) * base;
}

function drawChart(panel, key, cursor = null) {
  const config = chartOptions[key];
  const feed = snapshot?.feeds[config.feed];
  const now = Date.parse(snapshot?.generated_at);
  const windowHours = config.kpScale ? 24 : hours;
  const points = config.bars
    ? recentPoints(feed, "kp").filter((point) => point.t + 3 * HOUR > now)
    : recentPoints(feed, key, now, now - windowHours * HOUR);
  const latest = points.at(-1);
  const status = displayState(feed, latest, config.maxAge);
  const canDraw = points.length > 0;
  const empty = panel.querySelector(".chart-empty");
  const canvas = panel.querySelector("canvas");
  const inspect = panel.querySelector(".inspect");
  setStatus(panel.querySelector(".chart-status"), status, states[status] ?? "Loading");
  empty.hidden = canDraw;
  canvas.setAttribute("aria-hidden", String(!canDraw));
  const ctx = canvas.getContext("2d");
  if (!canDraw) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    empty.textContent = status === "loading" ? "Waiting for NOAA…"
      : status === "unavailable" ? "NOAA data is unavailable." : "No readings in this time range.";
    inspect.textContent = "";
    return;
  }

  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width < 80 || height < 80) return;
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  ctx.scale(scale, scale);
  const left = 37, right = width - 12, top = 10, bottom = height - 27;
  const from = config.bars ? points[0].t : now - windowHours * HOUR;
  const to = config.bars ? latest.t + 3 * HOUR : now;
  const values = points.map((point) => point.value);
  const rawLow = Math.min(...values, ...(key === "bz" ? [0] : []));
  const rawHigh = Math.max(...values, ...(key === "bz" ? [0] : []));
  const step = config.kpScale ? 3 : niceStep(Math.max(rawHigh - rawLow, key === "bz" ? 4 : 20));
  const low = config.kpScale ? 0 : Math.floor(rawLow / step) * step - step;
  const high = config.kpScale ? 9 : Math.ceil(rawHigh / step) * step + step;
  const x = (t) => left + (t - from) / (to - from) * (right - left);
  const y = (value) => bottom - (value - low) / (high - low) * (bottom - top);
  ctx.font = "11px Segoe UI, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  ctx.fillStyle = "#a8afd0";

  for (let value = low; value <= high + step / 1000; value += step) {
    const py = y(value);
    ctx.strokeStyle = value === 0 && key === "bz" ? "#656b91" : "#303553";
    ctx.beginPath();
    ctx.moveTo(left, py);
    ctx.lineTo(right, py);
    ctx.stroke();
    ctx.fillText(String(Number(value.toFixed(2))), left - 7, py);
  }

  if (config.kpScale) {
    ctx.strokeStyle = "#a26079";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(left, y(5));
    ctx.lineTo(right, y(5));
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const count = width < 400 ? (config.bars ? 2 : 3) : 4;
  const axisFormat = config.bars
    ? dateFormat({ day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : dateFormat({ hour: "2-digit", minute: "2-digit" });
  for (let index = 0; index <= count; index++) {
    const fraction = index / count;
    const formatted = axisFormat.format(from + fraction * (to - from));
    ctx.textAlign = index === 0 ? "left" : index === count ? "right" : "center";
    ctx.fillText(formatted, left + fraction * (right - left), bottom + 15);
  }

  ctx.lineWidth = 1.6;
  if (config.bars) {
    const barWidth = Math.max(2, x(from + 3 * HOUR) - left - 3);
    for (const point of points) {
      ctx.fillStyle = kpColors[kpLevel(point.value)];
      ctx.fillRect(x(point.t) + 1, y(point.value), barWidth, Math.max(1, bottom - y(point.value)));
    }
  } else {
    ctx.strokeStyle = config.color;
    const connected = (first, second) => first && second
      && second.t - first.t <= config.gap && first.source === second.source;
    ctx.beginPath();
    let previous = null;
    for (const point of points) {
      if (connected(previous, point)) {
        ctx.lineTo(x(point.t), y(point.value));
      } else {
        ctx.moveTo(x(point.t), y(point.value));
      }
      previous = point;
    }
    ctx.stroke();
    for (const [index, point] of points.entries()) {
      if (config.kpScale || (!connected(points[index - 1], point) && !connected(point, points[index + 1]))) {
        ctx.fillStyle = config.kpScale ? kpColors[kpLevel(point.value)] : config.color;
        ctx.beginPath();
        ctx.arc(x(point.t), y(point.value), 2.7, 0, 2 * Math.PI);
        ctx.fill();
      }
    }
  }

  let focus = cursor === null && !config.bars ? latest : null;
  if (cursor !== null && cursor >= left && cursor <= right) {
    const target = from + (cursor - left) / (right - left) * (to - from);
    if (config.bars) {
      focus = points.find((point) => point.t <= target && target < point.t + 3 * HOUR);
    } else {
      focus = points.reduce((best, point) =>
        Math.abs(point.t - target) < Math.abs(best.t - target) ? point : best,
      latest);
      if (Math.abs(focus.t - target) > config.gap) focus = null;
    }
  }
  if (focus) {
    const px = x(focus.t + (config.bars ? 1.5 * HOUR : 0));
    ctx.fillStyle = config.kpScale ? kpColors[kpLevel(focus.value)] : config.color;
    ctx.beginPath();
    ctx.arc(px, y(focus.value), 3.3, 0, 2 * Math.PI);
    ctx.fill();
    inspect.textContent = [
      fullTime(focus.t), focus.value.toFixed(config.precision) + " " + config.unit,
      config.kpScale ? kpLevels[kpLevel(focus.value)] : focus.source,
    ].filter(Boolean).join(" · ");
  } else {
    inspect.textContent = cursor === null ? "3-hour intervals · " + zoneName() : "No reading at this time";
  }
}

function renderBulletins() {
  const feed = snapshot?.feeds.alerts;
  const rows = feed?.data ?? [];
  const state = displayState(feed);
  setStatus(select("#bulletin-state"), state, states[state] ?? "Loading");
  const previous = filter.value;
  const kinds = [...new Set(rows.map((row) => row.kind))].sort();
  if (Array.from(filter.options).slice(1).map((option) => option.value).join("|") !== kinds.join("|")) {
    filter.replaceChildren(new Option("All types", ""), ...kinds.map((kind) => new Option(kind, kind)));
    filter.value = kinds.includes(previous) ? previous : "";
  }
  const filtered = rows.filter((row) => !filter.value || row.kind === filter.value);
  const list = select("#bulletin-list");
  const existing = new Map(Array.from(list.children, (item) => [item.dataset.key, item]));
  const next = filtered.slice(0, bulletinLimit).map((row) => {
    const key = row.time + "|" + row.product_id;
    let detail = existing.get(key);
    if (!detail) {
      detail = document.createElement("details");
      detail.dataset.key = key;
      detail.innerHTML = '<summary><span class="kind"></span><span class="bulletin-title"></span><time></time></summary><pre class="bulletin-message"></pre>';
    }
    detail.querySelector(".kind").textContent = row.kind;
    detail.querySelector(".bulletin-title").textContent = row.title;
    const time = detail.querySelector("time");
    time.dateTime = row.time;
    time.textContent = fullTime(Date.parse(row.time));
    detail.querySelector("pre").textContent = row.message;
    return detail;
  });
  const keep = new Set(next);
  for (const item of existing.values()) {
    if (!keep.has(item)) item.remove();
  }
  next.forEach((detail, index) => {
    if (list.children[index] !== detail) list.insertBefore(detail, list.children[index] ?? null);
  });
  const empty = select("#bulletin-empty");
  empty.hidden = Boolean(filtered.length);
  empty.textContent = state === "loading" ? "Waiting for NOAA…"
    : state === "unavailable" ? "The NOAA bulletin feed is unavailable."
      : "No bulletins to display for this selection.";
  more.hidden = filtered.length <= bulletinLimit;
}

function renderConnection() {
  const connection = select("#connection");
  const check = select("#last-check");
  if (requestFailed) {
    setStatus(connection, snapshot ? "cached" : "unavailable",
      snapshot ? "Dashboard offline · last response" : "Dashboard API unreachable");
    check.textContent = snapshot ? "Last response " + fullTime(Date.parse(snapshot.generated_at)) : "Refresh to try again.";
    return;
  }
  if (!snapshot) return;
  const statuses = Object.values(snapshot.feeds).map((feed) => feed.state);
  if (statuses.every((state) => state === "live")) setStatus(connection, "live", "NOAA live");
  else if (statuses.every((state) => state === "unavailable")) setStatus(connection, "unavailable", "NOAA data unavailable");
  else setStatus(connection, "partial", "Some feeds degraded");
  check.textContent = "Checked " + fullTime(Date.parse(snapshot.generated_at));
}

let modelForecast = null;
let modelLoading = false;

function renderModelForecast() {
  const state = modelForecast?.state;
  const start = Date.parse(modelForecast?.target_start);
  const end = Date.parse(modelForecast?.target_end);
  const status = select("#model-status");
  const values = select("#model-values");
  const times = select("#model-time");
  values.hidden = true;
  times.hidden = true;
  if (!state) return;
  if (state !== "ready" || end <= Date.now()) {
    const label = {
      scheduled: "Next release scheduled",
      collecting: "Checking inputs",
      missed: "No forecast issued",
      ready: "Forecast expired",
    }[state] ?? "Forecast unavailable";
    setStatus(status, state === "unavailable" || state === "missed" ? "unavailable" : "partial", label);
    if (state === "scheduled" || state === "collecting") {
      const windowStart = Date.parse(modelForecast.issue_window_start);
      times.textContent = "Target " + fullTime(start) + " · Release window opens " + fullTime(windowStart);
      times.hidden = false;
    }
    return;
  }
  const risk = modelForecast.elevated_risk;
  setStatus(status, risk ? "partial" : "live", risk ? "Experimental · elevated risk" : "Experimental");
  const issued = Date.parse(modelForecast.issued_at);
  times.textContent = fullTime(start) + " – " + fullTime(end) + " · Issued " + fullTime(issued);
  const probability = modelForecast.storm_probability;
  const kp = modelForecast.estimated_kp;
  select("#model-probability").textContent = Number.isFinite(probability) ? (100 * probability).toFixed(1) + "%" : "—";
  select("#model-kp").textContent = Number.isFinite(kp) ? kp.toFixed(2) : "—";
  values.hidden = false;
  times.hidden = false;
}

async function loadModelForecast() {
  if (modelLoading) return;
  modelLoading = true;
  try {
    const response = await fetch("/api/model-forecast", { cache: "no-store", signal: AbortSignal.timeout(5_000) });
    modelForecast = response.ok ? await response.json() : { state: "unavailable" };
  } catch {
    modelForecast = { state: "unavailable" };
  } finally {
    modelLoading = false;
    renderModelForecast();
  }
}

function render() {
  renderConnection();
  renderMetrics();
  for (const [key, panel] of chartViews) drawChart(panel, key);
  renderBulletins();
  renderModelForecast();
}

async function load() {
  if (loading) return;
  loading = true;
  refresh.disabled = true;
  void loadModelForecast();
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store", signal: AbortSignal.timeout(32_000) });
    if (!response.ok && response.status !== 503) throw new Error("Dashboard API request failed");
    const payload = await response.json();
    if (!payload.feeds || !payload.generated_at) throw new Error("Unexpected dashboard response");
    snapshot = payload;
    requestFailed = false;
  } catch {
    requestFailed = true;
  } finally {
    loading = false;
    refresh.disabled = false;
    render();
  }
}

for (const panel of document.querySelectorAll("[data-chart]")) {
  const key = panel.dataset.chart;
  const canvas = panel.querySelector("canvas");
  chartViews.set(key, panel);
  const resize = new ResizeObserver(() => drawChart(panel, key));
  resize.observe(canvas);
  canvas.addEventListener("pointermove", (event) => drawChart(panel, key, event.offsetX));
  canvas.addEventListener("pointerleave", () => drawChart(panel, key));
}
for (const button of document.querySelectorAll("[data-hours]")) {
  button.addEventListener("click", () => {
    hours = Number(button.dataset.hours);
    for (const choice of document.querySelectorAll("[data-hours]")) {
      choice.setAttribute("aria-pressed", String(choice === button));
    }
    for (const key of ["speed", "bz"]) drawChart(chartViews.get(key), key);
  });
}
timezone.addEventListener("change", render);
filter.addEventListener("change", () => {
  bulletinLimit = 8;
  renderBulletins();
});
more.addEventListener("click", () => {
  bulletinLimit += 12;
  renderBulletins();
});
refresh.addEventListener("click", load);
load();
setInterval(load, 60_000);
