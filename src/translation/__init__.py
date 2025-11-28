"""
Translation module for space weather alerts
Supports English and Russian
"""

from .translator import AlertTranslator, translate_text, translate_alert_data

__all__ = ['AlertTranslator', 'translate_text', 'translate_alert_data']

