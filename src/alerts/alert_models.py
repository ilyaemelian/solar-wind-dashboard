"""
Alert models for weather-sensitive people
Based on NASA/NOAA space weather data
"""

from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class AlertSeverity(Enum):
    """Alert severity levels for weather-sensitive people"""
    NONE = 0
    MINOR = 1      # G1 - Minor impacts (weak power grid fluctuations)
    MODERATE = 2   # G2 - Moderate impacts (voltage corrections may be required)
    STRONG = 3     # G3 - Strong impacts (power system problems, navigation issues)
    SEVERE = 4     # G4 - Severe impacts (widespread voltage problems, transformer damage)
    EXTREME = 5    # G5 - Extreme impacts (complete power grid collapse possible)


class Alert:
    """Base alert class for space weather events"""
    
    def __init__(self, 
                 message_code: str,
                 serial_number: str,
                 issue_time: datetime,
                 warning_type: str,
                 full_message: str):
        self.message_code = message_code
        self.serial_number = serial_number
        self.issue_time = issue_time
        self.warning_type = warning_type
        self.full_message = full_message
        self.created_at = datetime.now()
        self.is_processed = False
    
    def get_severity(self) -> AlertSeverity:
        """Determine severity level from NOAA scale"""
        if not hasattr(self, 'noaa_scale') or not self.noaa_scale:
            return AlertSeverity.NONE
        
        scale = self.noaa_scale.upper()
        if 'G1' in scale or 'R1' in scale or 'S1' in scale:
            return AlertSeverity.MINOR
        elif 'G2' in scale or 'R2' in scale or 'S2' in scale:
            return AlertSeverity.MODERATE
        elif 'G3' in scale or 'R3' in scale or 'S3' in scale:
            return AlertSeverity.STRONG
        elif 'G4' in scale or 'R4' in scale or 'S4' in scale:
            return AlertSeverity.SEVERE
        elif 'G5' in scale or 'R5' in scale or 'S5' in scale:
            return AlertSeverity.EXTREME
        
        return AlertSeverity.NONE
    
    def is_dangerous_for_health(self) -> bool:
        """
        Check if alert is dangerous for weather-sensitive people
        (heart patients, elderly, etc.)
        """
        severity = self.get_severity()
        # G3 and above can affect health-sensitive people
        return severity.value >= AlertSeverity.STRONG.value
    
    def get_health_impact(self) -> str:
        """Get health impact description for weather-sensitive people"""
        severity = self.get_severity()
        
        impacts = {
            AlertSeverity.NONE: "No significant health impact expected",
            AlertSeverity.MINOR: "Minor impact - sensitive individuals may experience slight discomfort",
            AlertSeverity.MODERATE: "Moderate impact - cardiovascular patients and elderly should be cautious",
            AlertSeverity.STRONG: "Strong impact - weather-sensitive people may experience health issues",
            AlertSeverity.SEVERE: "Severe impact - high risk for heart patients and elderly",
            AlertSeverity.EXTREME: "Extreme impact - all weather-sensitive people should take precautions"
        }
        
        return impacts.get(severity, "Unknown impact level")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary"""
        return {
            'message_code': self.message_code,
            'serial_number': self.serial_number,
            'issue_time': self.issue_time.isoformat(),
            'warning_type': self.warning_type,
            'full_message': self.full_message,
            'severity': self.get_severity().name,
            'is_dangerous': self.is_dangerous_for_health(),
            'health_impact': self.get_health_impact()
        }


class GeomagneticAlert(Alert):
    """Geomagnetic alert (K-index events) - most relevant for weather-sensitive people"""
    
    def __init__(self,
                 message_code: str,
                 serial_number: str,
                 issue_time: datetime,
                 warning_type: str,
                 full_message: str,
                 valid_from: Optional[datetime] = None,
                 valid_to: Optional[datetime] = None,
                 begin_time: Optional[datetime] = None,
                 warning_condition: Optional[str] = None,
                 noaa_scale: Optional[str] = None,
                 potential_impacts: Optional[str] = None):
        super().__init__(message_code, serial_number, issue_time, warning_type, full_message)
        self.valid_from = valid_from
        self.valid_to = valid_to
        self.begin_time = begin_time
        self.warning_condition = warning_condition
        self.noaa_scale = noaa_scale
        self.potential_impacts = potential_impacts
    
    def is_active(self) -> bool:
        """Check if alert is currently active"""
        now = datetime.now()
        if self.valid_to:
            return now <= self.valid_to
        return True


class ForecastAlert(Alert):
    """Forecast alert (Storm Watch/Forecast)"""
    
    def __init__(self,
                 message_code: str,
                 serial_number: str,
                 issue_time: datetime,
                 warning_type: str,
                 full_message: str,
                 forecast_data: Optional[str] = None,
                 potential_impacts: Optional[str] = None):
        super().__init__(message_code, serial_number, issue_time, warning_type, full_message)
        self.forecast_data = forecast_data
        self.potential_impacts = potential_impacts

