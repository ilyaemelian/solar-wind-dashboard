"""
Alert processor for weather-sensitive people
Filters and processes alerts for cardiovascular patients, elderly, etc.
"""

from typing import List, Dict
from .alert_models import Alert, AlertSeverity
try:
    from ..translation.translator import translate_alert_data
except ImportError:
    # Fallback if translation module not available
    def translate_alert_data(data):
        return data


class AlertProcessor:
    """Processes alerts for weather-sensitive people"""
    
    def __init__(self):
        self.health_threshold = AlertSeverity.STRONG  # G3 and above
    
    def filter_health_relevant(self, alerts: List[Alert]) -> List[Alert]:
        """Filter alerts that are relevant for health-sensitive people"""
        return [alert for alert in alerts if alert.is_dangerous_for_health()]
    
    def process_alerts(self, alerts: List[Alert], translate: bool = True) -> List[Dict]:
        """Process alerts and return formatted data"""
        processed = []
        
        for alert in alerts:
            alert_dict = alert.to_dict()
            
            # Add health-specific information
            alert_dict['health_impact'] = alert.get_health_impact()
            alert_dict['is_dangerous'] = alert.is_dangerous_for_health()
            
            # Translate if needed
            if translate:
                alert_dict = translate_alert_data(alert_dict)
            
            processed.append(alert_dict)
        
        return processed
    
    def get_critical_alerts(self, alerts: List[Alert]) -> List[Alert]:
        """Get only critical alerts (G4, G5)"""
        return [
            alert for alert in alerts 
            if alert.get_severity().value >= AlertSeverity.SEVERE.value
        ]
    
    def format_for_notification(self, alert: Alert) -> str:
        """Format alert for notification (Telegram/Email)"""
        severity = alert.get_severity()
        health_impact = alert.get_health_impact()
        
        message = f"⚠️ Space Weather Alert\n\n"
        message += f"Type: {alert.warning_type}\n"
        message += f"Severity: {severity.name}\n"
        message += f"Time: {alert.issue_time.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        message += f"Health Impact: {health_impact}\n\n"
        message += f"Details: {alert.full_message[:200]}..."
        
        return message

