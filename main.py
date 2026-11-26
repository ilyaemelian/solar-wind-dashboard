"""SolarWind dashboard, NOAA data, and the selected model forecast."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import OperationalError
from threading import Thread

from flask import Flask, jsonify, send_from_directory

from ml.final_live import FORECAST_DB, read_forecast, watch
from src.hybrid_store import DEFAULT_DB, read_runs
from src.noaa import NOAAClient, timestamp

ROOT = Path(__file__).resolve().parent


def create_app(client=None, hybrid_db=DEFAULT_DB, forecast_db=FORECAST_DB):
    app = Flask(__name__)
    noaa = client if client is not None else NOAAClient()

    @app.get("/")
    def index():
        return send_from_directory(ROOT, "index.html")

    @app.get("/api/dashboard")
    def dashboard():
        payload = noaa.snapshot()
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        if all(feed["state"] == "unavailable" for feed in payload["feeds"].values()):
            response.status_code = 503
        return response

    @app.get("/api/hybrid")
    def hybrid():
        try:
            runs = read_runs(hybrid_db, latest_only=True)
        except OperationalError:
            runs = []
        if not runs:
            return jsonify(state="unavailable", mode="shadow"), 503
        result = dict(runs[0])
        if timestamp(result["target_start"]) <= datetime.now(UTC):
            result["state"] = "expired"
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/model-forecast")
    def model_forecast():
        try:
            result = read_forecast(forecast_db, datetime.now(UTC))
            response = jsonify(result)
        except OperationalError:
            response = jsonify(state="unavailable")
            response.status_code = 503
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    Thread(target=watch, name="model-forecast", daemon=True).start()
    app.run(host="127.0.0.1", port=8000)
