"""
NOAA Space Weather API data ingestion
Fetches real-time space weather data for alert system
"""

import requests
import re
from datetime import datetime
from typing import List, Dict, Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..alerts.alert_models import GeomagneticAlert, ForecastAlert, Alert
else:
    # Runtime import
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from src.alerts.alert_models import GeomagneticAlert, ForecastAlert, Alert


class NOAADataFetcher:
    """Fetches data from NOAA Space Weather Prediction Center"""
    
    def __init__(self):
        self.base_url = "https://services.swpc.noaa.gov/text"
        self.alerts_url = f"{self.base_url}/wwv.txt"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SolarWind-Dashboard/1.0'
        })
    
    def fetch_alerts(self) -> str:
        """Fetch space weather alerts from NOAA"""
        try:
            response = self.session.get(self.alerts_url, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error fetching NOAA alerts: {e}")
            return ""
    
    def parse_alert_message(self, message: str) -> Optional[Dict]:
        """Parse alert message into structured data"""
        if not message or len(message.strip()) < 10:
            return None
        
        # Extract message code and serial number
        code_match = re.search(r'^([A-Z]{1,3})\s+(\d{4})', message)
        if not code_match:
            return None
        
        message_code = code_match.group(1)
        serial_number = code_match.group(2)
        
        # Extract issue time
        time_match = re.search(r'Issue Time:\s*(\d{4}\s+\w{3}\s+\d{2}\s+\d{4}\s+UTC)', message)
        issue_time = None
        if time_match:
            try:
                time_str = time_match.group(1)
                issue_time = datetime.strptime(time_str, "%Y %b %d %H%M UTC")
            except:
                pass
        
        if not issue_time:
            issue_time = datetime.now()
        
        # Extract warning type
        alert_match = re.search(r'ALERT:\s*([^\r\n]+)', message)
        warning_type = alert_match.group(1).strip() if alert_match else "Unknown Alert"
        
        return {
            'message_code': message_code,
            'serial_number': serial_number,
            'issue_time': issue_time,
            'warning_type': warning_type,
            'full_message': message
        }
    
    def parse_geomagnetic_alert(self, message: str, base_data: Dict) -> Optional[GeomagneticAlert]:
        """Parse geomagnetic alert (K-index events)"""
        if base_data['message_code'].startswith('K'):
            # Extract K-index specific data
            valid_from_match = re.search(r'Valid From:\s*([^\r\n]+)', message)
            valid_to_match = re.search(r'Valid To:\s*([^\r\n]+)', message)
            begin_match = re.search(r'Begin Time:\s*([^\r\n]+)', message)
            condition_match = re.search(r'Warning Condition:\s*([^\r\n]+)', message)
            scale_match = re.search(r'NOAA Scale:\s*([^\r\n]+)', message)
            impacts_match = re.search(r'Potential Impacts:\s*([^\r\n]+)', message, re.DOTALL)
            
            return GeomagneticAlert(
                message_code=base_data['message_code'],
                serial_number=base_data['serial_number'],
                issue_time=base_data['issue_time'],
                warning_type=base_data['warning_type'],
                full_message=base_data['full_message'],
                noaa_scale=scale_match.group(1).strip() if scale_match else None,
                potential_impacts=impacts_match.group(1).strip() if impacts_match else None,
                warning_condition=condition_match.group(1).strip() if condition_match else None
            )
        
        return None
    
    def get_alerts(self) -> List[Alert]:
        """Get all alerts from NOAA"""
        alerts_text = self.fetch_alerts()
        if not alerts_text:
            return []
        
        # Split into individual messages
        messages = re.split(r'\n\n+', alerts_text)
        alerts = []
        
        for message in messages:
            base_data = self.parse_alert_message(message)
            if not base_data:
                continue
            
            # Try to parse as geomagnetic alert
            geomagnetic = self.parse_geomagnetic_alert(message, base_data)
            if geomagnetic:
                alerts.append(geomagnetic)
            else:
                # Create generic alert
                alerts.append(Alert(
                    message_code=base_data['message_code'],
                    serial_number=base_data['serial_number'],
                    issue_time=base_data['issue_time'],
                    warning_type=base_data['warning_type'],
                    full_message=base_data['full_message']
                ))
        
        return alerts


def fetch_noaa_alerts() -> List[Alert]:
    """Quick function to fetch NOAA alerts"""
    fetcher = NOAADataFetcher()
    return fetcher.get_alerts()

