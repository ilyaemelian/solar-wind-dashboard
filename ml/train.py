"""Train and evaluate a calibrated next-interval geomagnetic storm classifier."""

import argparse
import hashlib
import json
import platform
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from ml.data import COUPLING_PREFIX, KP_FEATURE, STORM_KP, load_archive, make_examples
from ml.history import append_benchmark
from src.hybrid_store import DEFAULT_DB, read_runs
from src.noaa import timestamp, utc_string

SPLITS = {
    "train": (2014, 2021),
    "calibration": (2022, 2022),
    "validation": (2023, 2023),
    "test": (2024, 2025),
}
LEAD_HOURS = 1
ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = ROOT / "benchmark_protocol.json"
HISTORY_PATH = ROOT / "MODEL_HISTORY.md"
HYBRID_ARTIFACT = DEFAULT_DB.with_name("hybrid_ridge.joblib")


def fit_threshold(y, probabilities):
    precision, recall, thresholds = precision_recall_curve(y, probabilities)
    precision, recall = precision[:-1], recall[:-1]
    divisor = 4 * precision + recall
    f2 = np.divide(5 * precision * recall, divisor, out=np.zeros_like(divisor), where=divisor > 0)
    # Among equally good F2 thresholds, keep the more selective threshold.
    return float(thresholds[np.flatnonzero(f2 == f2.max())[-1]])


def fit_budget_threshold(y, probabilities, false_positive_budget):
    """Maximize detected validation intervals within the previous model's false-alarm count."""
    order = np.argsort(-probabilities)
    ordered_scores = probabilities[order]
    ordered_labels = np.asarray(y)[order]
    ends = np.r_[np.flatnonzero(np.diff(ordered_scores) != 0), len(order) - 1]
    true_positives = np.cumsum(ordered_labels)[ends]
    within_budget = ends + 1 - true_positives <= false_positive_budget
    eligible = np.flatnonzero(within_budget)
    if not len(eligible):
        return float(np.nextafter(ordered_scores[0], np.inf))
    # Scores are descending, so argmax breaks ties in favor of fewer alerts.
    return float(ordered_scores[ends[eligible[np.argmax(true_positives[eligible])]]])


def evaluate(rows, probabilities, threshold):
    y = rows["storm"]
    prediction = probabilities >= threshold
    tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
    onset = y.eq(1) & rows["previous_kp"].lt(STORM_KP)
    return {
        "average_precision": float(average_precision_score(y, probabilities)),
        "brier": float(brier_score_loss(y, probabilities)),
        "roc_auc": float(roc_auc_score(y, probabilities)),
        "threshold": threshold,
        "precision": float(tp / max(1, tp + fp)),
        "recall": float(tp / (tp + fn)),
        "f1": float(2 * tp / (2 * tp + fp + fn)),
        "onset_recall": float(prediction[onset].mean()) if onset.any() else None,
        "onsets": int(onset.sum()),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def block_bootstrap(rows, model, reference, draws=300):
    """Paired resampling in seven-day blocks to keep nearby Kp intervals together."""
    y = rows["storm"].to_numpy()
    week = (rows.index - rows.index[0]).days // 7
    blocks = [np.flatnonzero(week == value) for value in np.unique(week)]
    rng = np.random.default_rng(42)
    deltas = []
    for _ in range(draws):
        selection = np.concatenate([blocks[i] for i in rng.integers(0, len(blocks), len(blocks))])
        if np.unique(y[selection]).size != 2:
            continue
        ap = average_precision_score(y[selection], model[selection])
        baseline_ap = average_precision_score(y[selection], reference[selection])
        deltas.append(ap - baseline_ap)
    return {
        "successful_draws": len(deltas),
        "block_days": 7,
        "average_precision_delta_95pct": [float(x) for x in np.quantile(deltas, [0.025, 0.975])],
    }


def scaled_linear_pipeline(estimator):
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        estimator,
    )


def predict_storm_probability(artifact, rows):
    score = getattr(artifact["model"], artifact.get("score_method", "decision_function"))
    raw = score(rows[artifact["features"]]).reshape(-1, 1)
    return artifact["calibrator"].predict_proba(raw)[:, 1]


def row_id_sha256(rows):
    records = "\n".join(f"{t.isoformat()} {kp:.2f}" for t, kp in rows["target_kp"].items())
    return hashlib.sha256(records.encode()).hexdigest()


def check_protocol(manifest, splits):
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    files = {str(row["year"]): row["sha256"] for row in manifest}
    row_digests = {name: row_id_sha256(rows) for name, rows in splits.items()}
    if (
        protocol["lead_hours"] != LEAD_HOURS
        or protocol["splits"] != {name: list(years) for name, years in SPLITS.items()}
        or protocol["archive_sha256"] != files
        or protocol["row_id_sha256"] != row_digests
    ):
        raise ValueError("Frozen benchmark changed. Restore the pinned OMNI files and protocol before comparing models.")
    return protocol["id"], row_digests


def gfz_coverage(db_path, test):
    """Count only forecasts available by the frozen one-hour cutoff."""
    starts = {utc_string(t): t for t in test.index}
    paired = {}
    for item in read_runs(db_path):
        start = starts.get(item["target_start"])
        if start is None or item.get("gfz") is None:
            continue
        issued = timestamp(item["issued_at"])
        received = item.get("sources", {}).get("gfz", {}).get("received_at")
        if received and timestamp(received) <= issued <= start - pd.Timedelta(hours=LEAD_HOURS):
            paired.setdefault(item["target_start"], item["gfz"]["storm_fraction"])
    return paired


def run(
    cache_dir, output_dir, *, hybrid_artifact=HYBRID_ARTIFACT, hybrid_db=DEFAULT_DB,
    with_goes=False, with_hp30=False, with_hht=False,
):
    hourly, manifest = load_archive(SPLITS["train"][0], SPLITS["test"][1], cache_dir)
    frame, features = make_examples(hourly, include_coupling=True, lead_hours=LEAD_HOURS)
    extra_inputs = {}
    if with_goes:
        from ml.goes import load_goes_features

        extra_inputs["goes"] = load_goes_features(cache_dir, frame.index, lead_hours=LEAD_HOURS)
    if with_hp30 or with_hht:
        from ml.hp30 import load_hp30_features

        extra_inputs["hp30"] = load_hp30_features(cache_dir, frame.index, lead_hours=LEAD_HOURS)
    for extra, _ in extra_inputs.values():
        frame = frame.join(extra, validate="one_to_one")
    if with_hht:
        from ml.hht import STATS_COLUMNS, load_hht_features

        hro, hht_manifest = load_hht_features(cache_dir, frame.index, lead_hours=LEAD_HOURS)
        frame = frame.join(hro, validate="one_to_one")
    splits = {
        name: frame.loc[(frame.index.year >= first) & (frame.index.year <= last)]
        for name, (first, last) in SPLITS.items()
    }
    for name, rows in splits.items():
        if rows["storm"].nunique() != 2:
            raise ValueError(f"{name} must contain storm and non-storm intervals")
    protocol_id, row_digests = check_protocol(manifest, splits)
    train, calibration, validation, test = (splits[name] for name in SPLITS)
    fill_kp = float(train[KP_FEATURE].median())
    base_features = [name for name in features if not name.startswith(COUPLING_PREFIX)]
    newell_features = [name for name in features if name.startswith(f"{COUPLING_PREFIX}newell_")]
    models = {
        "logistic": (scaled_linear_pipeline(LogisticRegression(max_iter=1000, random_state=42)), base_features, "storm"),
        "logistic_newell": (
            scaled_linear_pipeline(LogisticRegression(max_iter=1000, random_state=42)),
            base_features + newell_features, "storm",
        ),
        "logistic_coupling": (scaled_linear_pipeline(LogisticRegression(max_iter=1000, random_state=42)), features, "storm"),
        "ridge": (scaled_linear_pipeline(Ridge(alpha=10)), base_features, "target_kp"),
        "ridge_coupling": (scaled_linear_pipeline(Ridge(alpha=10)), features, "target_kp"),
        "gradient_boosting": (
            HistGradientBoostingClassifier(
                learning_rate=0.06, max_iter=220, max_leaf_nodes=15,
                min_samples_leaf=35, l2_regularization=1.0, early_stopping=False, random_state=42,
            ),
            base_features, "storm",
        ),
    }
    for key, (extra, _) in extra_inputs.items():
        columns = extra.columns.to_list()
        if not train[columns].notna().any().all():
            raise ValueError(f"No {key} training measurements for at least one feature")
        models[f"ridge_{key}"] = (scaled_linear_pipeline(Ridge(alpha=10)), features + columns, "target_kp")
    hht_names = []
    if with_hht:
        if not train[hro.columns].notna().any().all():
            raise ValueError("No HRO training observations for at least one feature")
        hp30_columns = models["ridge_hp30"][1]
        for suffix, columns in (("hro", STATS_COLUMNS), ("hht", hro.columns.to_list())):
            estimators = {
                "ridge": Ridge(alpha=10),
                "ann": MLPRegressor(
                    hidden_layer_sizes=(10,), activation="relu", solver="adam", batch_size=64,
                    max_iter=50, n_iter_no_change=6, random_state=42,
                ),
            }
            for architecture, estimator in estimators.items():
                name = f"{architecture}_hp30_{suffix}"
                models[name] = (scaled_linear_pipeline(estimator), hp30_columns + columns, "target_kp")
                hht_names.append(name)
    # The persistence score ranks by the last available Kp. A one-variable sigmoid
    # on the calibration period lets it compete on probability metrics as well.
    candidates = {"persistence": (None, [KP_FEATURE], "storm"), **models}
    calibrators, thresholds, validation_scores = {}, {}, {}
    val_probabilities, test_probabilities = {}, {}
    for name, (model, columns, target) in candidates.items():
        score_method = "predict" if target == "target_kp" else "decision_function"
        if model is not None:
            model.fit(train[columns], train[target])

        def raw_scores(rows):
            if model is None:
                return rows[KP_FEATURE].fillna(fill_kp).to_numpy().reshape(-1, 1)
            return getattr(model, score_method)(rows[columns]).reshape(-1, 1)

        calibrator = LogisticRegression(max_iter=1000).fit(raw_scores(calibration), calibration["storm"])
        val_probability = calibrator.predict_proba(raw_scores(validation))[:, 1]
        threshold = fit_threshold(validation["storm"], val_probability)
        calibrators[name] = calibrator
        thresholds[name] = threshold
        val_probabilities[name] = val_probability
        validation_scores[name] = float(average_precision_score(validation["storm"], val_probability))
        test_probabilities[name] = calibrator.predict_proba(raw_scores(test))[:, 1]

    selected = max(models, key=validation_scores.__getitem__)
    _, selected_features, _ = models[selected]
    previous = "logistic"
    budget = int(((val_probabilities[previous] >= thresholds[previous]) & validation["storm"].eq(0)).sum())
    budget_thresholds = {
        name: fit_budget_threshold(validation["storm"], val_probabilities[name], budget)
        for name in models
    }
    current_artifact_hash = None
    if hybrid_artifact.is_file():
        current = joblib.load(hybrid_artifact)
        expected_inputs = [row for row in manifest if row["year"] <= SPLITS["calibration"][1]]
        if current["sources"] != expected_inputs:
            raise ValueError("The live Ridge artifact was trained on different OMNI files")
        horizon = current["horizons"][LEAD_HOURS]
        name = "ridge_live_component"
        val_probabilities[name] = predict_storm_probability(horizon, validation)
        test_probabilities[name] = predict_storm_probability(horizon, test)
        validation_scores[name] = float(average_precision_score(validation["storm"], val_probabilities[name]))
        thresholds[name] = fit_threshold(validation["storm"], val_probabilities[name])
        budget_thresholds[name] = fit_budget_threshold(validation["storm"], val_probabilities[name], budget)
        current_artifact_hash = hashlib.sha256(hybrid_artifact.read_bytes()).hexdigest()
    gfz = gfz_coverage(hybrid_db, test)
    hybrid_metrics = None
    if len(gfz) == len(test) and "ridge_live_component" in test_probabilities:
        gfz_scores = np.array([gfz[utc_string(t)] for t in test.index])
        hybrid_scores = (test_probabilities["ridge_live_component"] + gfz_scores) / 2
        hybrid_metrics = {
            "average_precision": float(average_precision_score(test["storm"], hybrid_scores)),
            "brier": float(brier_score_loss(test["storm"], hybrid_scores)),
        }
    report = {
        "benchmark_id": protocol_id,
        "lead_hours": LEAD_HOURS,
        "target": "Kp >= 5 in the target 3-hour UTC interval",
        "row_id_sha256": row_digests,
        "selected_model": selected,
        "validation_average_precision": validation_scores,
        "test_metrics": {
            name: evaluate(test, probabilities, thresholds[name])
            for name, probabilities in test_probabilities.items()
        },
        "paired_bootstrap_vs_persistence": block_bootstrap(
            test, test_probabilities[selected], test_probabilities["persistence"],
        ),
        "paired_bootstrap_vs_previous_logistic": block_bootstrap(
            test, test_probabilities[selected], test_probabilities["logistic"],
        ),
        "false_positive_budget_on_validation": budget,
        "test_at_validation_budget": {
            name: evaluate(test, test_probabilities[name], threshold)
            for name, threshold in budget_thresholds.items()
        },
        "splits": {
            name: {
                "years": list(SPLITS[name]),
                "rows": len(rows),
                "storms": int(rows["storm"].sum()),
            }
            for name, rows in splits.items()
        },
        "features": selected_features,
        "feature_counts": {name: len(columns) for name, (_, columns, _) in candidates.items()},
        "current_ridge_artifact_sha256": current_artifact_hash,
        "hybrid_evaluation": {
            "gfz_forecasts_on_fixed_test": len(gfz), "test_rows": len(test),
            "metrics": hybrid_metrics,
            "reason": "No comparable as-issued GFZ archive for the full frozen test" if len(gfz) < len(test)
            else "No live Ridge artifact" if hybrid_metrics is None else None,
        },
        "data": manifest,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    for key, (extra, extra_manifest) in extra_inputs.items():
        baseline, candidate = "ridge_coupling", f"ridge_{key}"
        ridge_budget = int(((val_probabilities[baseline] >= thresholds[baseline]) & validation["storm"].eq(0)).sum())
        matched_thresholds = {
            name: fit_budget_threshold(validation["storm"], val_probabilities[name], ridge_budget)
            for name in (baseline, candidate)
        }
        report[f"{key}_comparison"] = {
            "data": extra_manifest,
            "feature_coverage": {
                split: {column: int(count) for column, count in rows[extra.columns].notna().sum().items()}
                for split, rows in splits.items()
            },
            "false_positive_budget_on_validation": ridge_budget,
            "test_at_ridge_validation_budget": {
                name: evaluate(test, test_probabilities[name], threshold)
                for name, threshold in matched_thresholds.items()
            },
            "paired_average_precision_gain": (
                report["test_metrics"][candidate]["average_precision"] - report["test_metrics"][baseline]["average_precision"]
            ),
            "paired_bootstrap": block_bootstrap(test, test_probabilities[candidate], test_probabilities[baseline]),
        }
        if key == "hp30":
            first_poststorm = test["storm"].eq(0) & test["previous_kp"].ge(STORM_KP)
            report["hp30_comparison"]["first_poststorm_test"] = {
                "intervals": int(first_poststorm.sum()),
                "false_alerts": {
                    name: int((first_poststorm & (test_probabilities[name] >= threshold)).sum())
                    for name, threshold in matched_thresholds.items()
                },
            }
    if with_hht:
        reference = "ridge_hp30"
        best_hht = max(hht_names, key=validation_scores.__getitem__)
        hht_budget = int(((val_probabilities[reference] >= thresholds[reference]) & validation["storm"].eq(0)).sum())
        hht_thresholds = {
            name: fit_budget_threshold(validation["storm"], val_probabilities[name], hht_budget)
            for name in (reference, *hht_names)
        }
        report["hht_comparison"] = {
            "source": hht_manifest,
            "covered_rows": {
                split: {
                    "with_statistics": int(rows[STATS_COLUMNS].notna().all(axis=1).sum()),
                    "with_all_hht_features": int(rows[hro.columns.difference(STATS_COLUMNS)].notna().all(axis=1).sum()),
                } for split, rows in splits.items()
            },
            "best_challenger_on_validation": best_hht,
            "false_positive_budget_on_validation": hht_budget,
            "test_at_hp30_validation_budget": {
                name: evaluate(test, test_probabilities[name], threshold)
                for name, threshold in hht_thresholds.items()
            },
            "paired_bootstrap_vs_hp30": {
                name: block_bootstrap(test, test_probabilities[name], test_probabilities[reference])
                for name in hht_names
            },
        }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    exports = {"model.joblib": selected}
    exports.update({f"ridge_{key}.joblib": f"ridge_{key}" for key in extra_inputs})
    exports.update({f"{name}.joblib": name for name in hht_names})
    for filename, name in exports.items():
        model, columns, target = models[name]
        artifact = {
            "model": model,
            "calibrator": calibrators[name],
            "threshold": thresholds[name],
            "validation_budget_threshold": budget_thresholds[name],
            "features": columns,
            "include_coupling": any(column.startswith(COUPLING_PREFIX) for column in columns),
            "score_method": "predict" if target == "target_kp" else "decision_function",
            "lead_hours": LEAD_HOURS,
            "research_only": True,
        }
        key = name.removeprefix("ridge_")
        if key in extra_inputs:
            artifact[f"{key}_sources"] = extra_inputs[key][1]
        if name in hht_names:
            artifact["hp30_sources"] = extra_inputs["hp30"][1]
            artifact["hro_sources"] = hht_manifest
        joblib.dump(artifact, output_dir / filename, compress=3)
    (output_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path(".ml-cache"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ml-output/fixed-benchmark"))
    parser.add_argument("--hybrid-artifact", type=Path, default=HYBRID_ARTIFACT)
    parser.add_argument("--hybrid-db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--goes", action="store_true", help="Include the matched GOES XRS experiment")
    parser.add_argument("--hp30", action="store_true", help="Include the retrospective GFZ Hp30 experiment")
    parser.add_argument("--hht", action="store_true", help="Evaluate HHT–ANN and its Ridge controls on the fixed benchmark")
    args = parser.parse_args()
    with threadpool_limits(limits=2):
        report = run(
            args.cache_dir, args.output_dir, hybrid_artifact=args.hybrid_artifact, hybrid_db=args.hybrid_db,
            with_goes=args.goes, with_hp30=args.hp30, with_hht=args.hht,
        )
    append_benchmark(report, HISTORY_PATH)
    summary = {
        "selected_model": report["selected_model"],
        "benchmark_id": report["benchmark_id"],
        "test_metrics": report["test_metrics"],
        "paired_bootstrap_vs_persistence": report["paired_bootstrap_vs_persistence"],
        "paired_bootstrap_vs_previous_logistic": report["paired_bootstrap_vs_previous_logistic"],
        "hybrid_evaluation": report["hybrid_evaluation"],
    }
    if args.goes:
        summary["goes_comparison"] = {key: value for key, value in report["goes_comparison"].items() if key != "data"}
    if args.hp30:
        summary["hp30_comparison"] = report["hp30_comparison"]
    if args.hht:
        summary["hht_comparison"] = {key: value for key, value in report["hht_comparison"].items() if key != "source"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
