"""Record comparable runs on the fixed SolarWind benchmark."""

import hashlib
from datetime import UTC, datetime

NAMES = {
    "persistence": "Last available Kp",
    "logistic": "V1 · Logistic regression",
    "logistic_newell": "Logistic regression + Newell",
    "logistic_coupling": "Logistic regression + physical features",
    "ridge": "Ridge without added coupling features",
    "ridge_coupling": "V2 · Ridge + physical features",
    "ridge_goes": "V3 · Ridge + GOES XRS",
    "ridge_hp30": "V4 · Ridge + Hp30 and ap30",
    "ridge_hp30_hro": "Ridge + Hp30 + five-minute OMNI statistics",
    "ann_hp30_hro": "ANN + Hp30 + five-minute OMNI statistics",
    "ridge_hp30_hht": "Ridge + Hp30 + five-minute statistics and HHT",
    "ann_hp30_hht": "V5 · HHT–ANN + Hp30",
    "gradient_boosting": "Histogram gradient boosting",
    "ridge_live_component": "Ridge from the live comparison artifact",
}


def fmt(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def onset_count(row):
    if row["onset_recall"] is None:
        return "—"
    return f"{round(row['onset_recall'] * row['onsets'])}/{row['onsets']}"


def append_benchmark(report, path):
    test = report["splits"]["test"]
    coverage = report["hybrid_evaluation"]
    metrics = coverage["metrics"] or {}
    lines = [
        f"Validation winner **{NAMES[report['selected_model']]}**.",
        "",
        "| Model | Validation AP | Test AP ↑ | Brier ↓ | F1 ↑ | Storm intervals detected ↑ | Onsets detected ↑ | False alerts ↓ |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in report["test_metrics"].items():
        matrix = row["confusion_matrix"]
        lines.append(
            f"| {NAMES[name]} | {fmt(report['validation_average_precision'][name])} | {fmt(row['average_precision'])} "
            f"| {fmt(row['brier'], 4)} | {fmt(row['f1'])} | {matrix['tp']}/{test['storms']} "
            f"| {onset_count(row)} | {matrix['fp']} |"
        )
    lines.append(
        f"| Ridge + GFZ/PAGER | — | {fmt(metrics.get('average_precision'))} "
        f"| {fmt(metrics.get('brier'), 4)} | — | — | — | — |"
    )
    if not metrics:
        lines.extend(["", f"As-issued GFZ forecasts matched {coverage['gfz_forecasts_on_fixed_test']}/"
                      f"{coverage['test_rows']} test intervals. A dash indicates an unavailable score."])
    goes = report.get("goes_comparison")
    if goes:
        counts = goes["feature_coverage"]["test"]
        low, high = goes["paired_bootstrap"]["average_precision_delta_95pct"]
        lines.extend([
            "",
            "**GOES experiment.** The same Ridge model added the soft X-ray background and channel ratio with a 48-hour lag.",
            f"Test coverage was {counts['goes_soft_background_log']}/{test['rows']} for the background and "
            f"{counts['goes_hard_soft_ratio_log']}/{test['rows']} for the ratio. "
            "Missing readings used training-set statistics.",
            f"AP change {fmt(goes['paired_average_precision_gain'], 4)}. "
            f"The paired 95% interval from weekly blocks was [{fmt(low, 4)}, {fmt(high, 4)}].",
            "",
            f"The thresholds used a shared budget of {goes['false_positive_budget_on_validation']} false alerts on 2023 validation.",
            "",
            "| Model | Test onsets ↑ | Test false alerts ↓ |",
            "| --- | ---: | ---: |",
        ])
        for name, row in goes["test_at_ridge_validation_budget"].items():
            lines.append(f"| {NAMES[name]} | {onset_count(row)} | {row['confusion_matrix']['fp']} |")
    hp30 = report.get("hp30_comparison")
    if hp30:
        low, high = hp30["paired_bootstrap"]["average_precision_delta_95pct"]
        after = hp30["first_poststorm_test"]
        lines.extend([
            "",
            "**Hp30 experiment.** Ridge added the latest Hp30, two-hour mean ap30 and one-hour ap30 change.",
            f"The most recent input bin ended at least {hp30['data']['assumed_buffer_minutes']} minutes before issuance.",
            "This evaluation used the retrospective GFZ series, which can include revisions.",
            f"AP change vs. V2 was {fmt(hp30['paired_average_precision_gain'], 4)}. "
            f"The paired 95% interval from weekly blocks was [{fmt(low, 4)}, {fmt(high, 4)}].",
            "",
            f"The thresholds used a shared budget of {hp30['false_positive_budget_on_validation']} false alerts on 2023 validation.",
            "",
            "| Model | Test onsets ↑ | Test false alerts ↓ | False alerts on the first interval after a storm ↓ |",
            "| --- | ---: | ---: | ---: |",
        ])
        for name, row in hp30["test_at_ridge_validation_budget"].items():
            lines.append(
                f"| {NAMES[name]} | {onset_count(row)} | {row['confusion_matrix']['fp']} "
                f"| {after['false_alerts'][name]}/{after['intervals']} |"
            )
    hht = report.get("hht_comparison")
    if hht:
        counts = hht["covered_rows"]["test"]
        challenger = hht["best_challenger_on_validation"]
        lines.extend([
            "",
            "**HHT–ANN experiment.** Ridge and the neural network both used five-minute OMNI statistics. "
            "Each was tested with and without Hilbert–Huang features from GSM Bz and the Newell coupling function.",
            f"Full test coverage was {counts['with_statistics']}/{test['rows']} for the statistics and "
            f"{counts['with_all_hht_features']}/{test['rows']} for the HHT features. All test rows were retained.",
            f"The strongest challenger on validation was **{NAMES[challenger]}**.",
            "",
            f"The thresholds used the V4 budget of {hht['false_positive_budget_on_validation']} false alerts on 2023 validation.",
            "",
            "| Model | Test onsets ↑ | Test false alerts ↓ | Test AP change vs. V4 | Paired 95% interval |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for name, row in hht["test_at_hp30_validation_budget"].items():
            delta = row["average_precision"] - report["test_metrics"]["ridge_hp30"]["average_precision"]
            bootstrap = hht["paired_bootstrap_vs_hp30"].get(name)
            interval = "—"
            if bootstrap:
                low, high = bootstrap["average_precision_delta_95pct"]
                interval = f"[{fmt(low, 4)}, {fmt(high, 4)}]"
            lines.append(
                f"| {NAMES[name]} | {onset_count(row)} | {row['confusion_matrix']['fp']} "
                f"| {fmt(delta, 5)} | {interval} |"
            )
    saved = report["current_ridge_artifact_sha256"]
    if saved:
        lines.extend(["", f"SHA-256 of the Ridge comparison artifact `{saved}`."])
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if not existing:
        splits = report["splits"]
        existing = f"""# SolarWind model history

The [fixed protocol](benchmark_protocol.json) uses 2014–2023 for development and 2024–2025 for testing. The target is final Kp ≥ 5 in a three-hour UTC interval, forecast one hour before it starts. The test has {test['rows']} intervals including {test['storms']} storm intervals. The benchmark checks archive hashes and the exact row identities before scoring.

| Development split | Intervals | Storm intervals |
| --- | ---: | ---: |
| Fit, 2014–2021 | {splits['train']['rows']} | {splits['train']['storms']} |
| Calibration, 2022 | {splits['calibration']['rows']} | {splits['calibration']['storms']} |
| Model and threshold selection, 2023 | {splits['validation']['rows']} | {splits['validation']['storms']} |

Run `python -m ml.train` to reproduce the benchmark. The history deduplicates runs with identical results.
"""
    append_run(path, "\n".join(lines), existing)


def append_noaa_comparison(report, path):
    median = report["noaa_age_hours_before_target"]["median"]
    lines = [
        "### Official NOAA SWPC forecast comparison",
        "",
        f"The latest 3-Day Forecast available at each one-hour cutoff matched {report['test_rows']}/"
        f"{report['full_test_rows']} test intervals, including {report['test_storms']} storm intervals. "
        f"The archived NOAA releases had a median lead of {fmt(median, 1)} hours.",
        "",
        "AP ranks NOAA forecasts by their numeric Kp. NOAA and persistence use a Kp threshold of 5 for F1. "
        "Ridge thresholds were selected by F2 on the full 2023 validation set.",
        "",
        "| Model | AP ↑ | F1 ↑ | Onsets detected ↑ | False alerts ↓ |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, row in report["test_metrics"].items():
        label = NAMES.get(name, "NOAA SWPC · 3-Day Forecast")
        lines.append(
            f"| {label} | {fmt(row['average_precision'], 4)} | {fmt(row['f1'], 4)} "
            f"| {onset_count(row)} | {row['confusion_matrix']['fp']} |"
        )
    lines.extend([
        "",
        f"Constant-score AP was {fmt(report['constant_average_precision'], 4)}.",
        "The comparison uses the NOAA three-day bulletin and retrospective NASA OMNI and GFZ inputs for Ridge.",
        "",
        "The [NCEI archive](https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/3day_forecast/) "
        "and the [IEM archive of NWS broadcasts](https://mesonet.agron.iastate.edu/nws/text.php) supply the releases. "
        "Run `python -m ml.noaa_benchmark` to reproduce the comparison.",
        "",
        f"SHA-256 of the matched releases and intervals `{report['matches_sha256']}`.",
    ])
    append_run(path, "\n".join(lines), path.read_text(encoding="utf-8"))


def append_run(path, body, existing):
    signature = hashlib.sha256(body.encode()).hexdigest()[:16]
    marker = f"<!-- run:{signature} -->"
    if marker in existing:
        return
    recorded_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    text = f"{existing.rstrip()}\n\n## {recorded_at}\n\n{marker}\n\n{body}\n"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
