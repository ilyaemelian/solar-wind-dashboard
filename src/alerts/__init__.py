"""
Alert system for weather-sensitive people
Designed for cardiovascular patients, elderly, and other weather-sensitive individuals
"""

from .alert_models import Alert, GeomagneticAlert, ForecastAlert
from .alert_processor import AlertProcessor

__all__ = ['Alert', 'GeomagneticAlert', 'ForecastAlert', 'AlertProcessor']

