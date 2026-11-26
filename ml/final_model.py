"""Portable runtime for the selected Ridge + Hp30 + HHT model."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np

MODEL_PATH = Path(__file__).with_name("ridge_hp30_hht.json")
MODEL_ID = "ridge-hp30-hht-v1"


class FinalModel:
    def __init__(self, path=MODEL_PATH):
        snapshot = Path(path).read_bytes()
        data = json.loads(snapshot)
        if data["model_id"] != MODEL_ID or data["lead_hours"] != 1:
            raise ValueError("Unsupported final model")
        self.sha256 = hashlib.sha256(snapshot).hexdigest()
        self.features = tuple(data["features"])
        self.medians = np.asarray(data["medians"], dtype=float)
        self.indicators = np.asarray(data["missing_indicator_indices"], dtype=int)
        self.centers = np.asarray(data["scaler_mean"], dtype=float)
        self.scales = np.asarray(data["scaler_scale"], dtype=float)
        self.weights = np.asarray(data["ridge_coefficients"], dtype=float)
        self.intercept = float(data["ridge_intercept"])
        self.slope = float(data["calibrator_coefficient"])
        self.bias = float(data["calibrator_intercept"])
        self.threshold = float(data["probability_threshold"])
        width = len(self.features) + self.indicators.size
        if (len(set(self.features)) != len(self.features)
                or len(self.medians) != len(self.features)
                or self.centers.shape != self.scales.shape or self.centers.shape != (width,)
                or self.weights.shape != (width,)
                or not np.all(self.scales > 0)
                or not np.all((0 <= self.indicators) & (self.indicators < len(self.features)))
                or not 0 < self.threshold < 1):
            raise ValueError("Invalid final model parameters")

    def predict(self, features):
        source = features.loc[:, list(self.features)].to_numpy(dtype=float)
        missing = np.isnan(source)
        function_input = np.column_stack((np.where(missing, self.medians, source), missing[:, self.indicators]))
        kp = ((function_input - self.centers) / self.scales) @ self.weights + self.intercept
        logit = self.slope * kp + self.bias
        exp = np.exp(-np.abs(logit))
        probability = np.where(logit >= 0, 1 / (1 + exp), exp / (1 + exp))
        if not np.isfinite(kp).all() or not np.isfinite(probability).all() or not math.isfinite(self.intercept):
            raise ValueError("Final model produced a non-finite prediction")
        return kp, probability
