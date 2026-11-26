"""Export the selected benchmark estimator as portable JSON."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

import joblib

from ml.final_model import MODEL_ID, MODEL_PATH
from ml.train import PROTOCOL_PATH

CANDIDATE = "ridge_hp30_hht"


def export_final(output_dir, destination):
    benchmark = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    report = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    if (report["benchmark_id"] != benchmark["id"] or report["row_id_sha256"] != benchmark["row_id_sha256"]
            or CANDIDATE not in report["test_metrics"]):
        raise ValueError("Run the locked HHT benchmark before exporting")
    snapshot = (output_dir / f"{CANDIDATE}.joblib").read_bytes()
    model = joblib.load(io.BytesIO(snapshot))
    experiment = report["hht_comparison"]
    if model["hro_sources"] != experiment["source"] or model["hp30_sources"] != report["hp30_comparison"]["data"]:
        raise ValueError("The saved estimator and benchmark inputs disagree")
    imputer, scaler, ridge = model["model"]
    calibration = model["calibrator"]
    score = experiment["test_at_hp30_validation_budget"][CANDIDATE]
    data = {
        "model_id": MODEL_ID,
        "training_artifact_sha256": hashlib.sha256(snapshot).hexdigest(),
        "benchmark_id": benchmark["id"],
        "test_row_sha256": benchmark["row_id_sha256"]["test"],
        "lead_hours": model["lead_hours"],
        "features": model["features"],
        "medians": imputer.statistics_.tolist(),
        "missing_indicator_indices": imputer.indicator_.features_.tolist(),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "ridge_coefficients": ridge.coef_.tolist(),
        "ridge_intercept": float(ridge.intercept_),
        "calibrator_coefficient": float(calibration.coef_[0][0]),
        "calibrator_intercept": float(calibration.intercept_[0]),
        "probability_threshold": score["threshold"],
        "threshold_policy": "Ridge + Hp30 F2 false-positive budget on 2023 validation",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False, mode="w", encoding="utf-8") as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-output", type=Path, default=Path(".ml-output/fixed-benchmark"))
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    export_final(args.benchmark_output, args.model)
    print(args.model)


if __name__ == "__main__":
    main()
