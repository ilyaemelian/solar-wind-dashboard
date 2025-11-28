"""
NASA Solar Wind Health Alert System
Real-time monitoring for weather-sensitive people (cardiovascular patients, elderly)
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.data_ingestion.noaa_api import fetch_noaa_alerts
from src.alerts.alert_processor import AlertProcessor
from src.translation.translator import translator


def fetch_nasa_data():
    """Fetch NASA/NOAA space weather data"""
    print("Fetching space weather data from NOAA...")
    alerts = fetch_noaa_alerts()
    print(f"Fetched {len(alerts)} alerts")
    return alerts


def process_alerts_for_health(alerts):
    """Process alerts for weather-sensitive people"""
    processor = AlertProcessor()
    
    # Filter health-relevant alerts
    health_alerts = processor.filter_health_relevant(alerts)
    print(f"Found {len(health_alerts)} alerts relevant for weather-sensitive people")
    
    # Process and translate
    processed = processor.process_alerts(health_alerts, translate=True)
    
    return processed


def visualize_data(alerts):
    """Create visualizations of space weather data"""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
        
        if not alerts:
            print("No alerts to visualize")
            return
        
        # Create time series plot
        fig, ax = plt.subplots(figsize=(12, 6))
        
        times = [alert['issue_time'] for alert in alerts]
        severities = [alert.get('severity', 'NONE') for alert in alerts]
        
        # Convert times to datetime if needed
        if isinstance(times[0], str):
            times = [datetime.fromisoformat(t) for t in times]
        
        # Plot
        ax.plot(times, [ord(s[0]) for s in severities], marker='o', linestyle='-')
        ax.set_xlabel('Time')
        ax.set_ylabel('Alert Severity')
        ax.set_title('Space Weather Alerts for Weather-Sensitive People')
        ax.grid(True)
        
        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        plt.savefig("visualizations/alerts_timeline.png", dpi=150)
        print("Saved visualization: visualizations/alerts_timeline.png")
        
    except Exception as e:
        print(f"Visualization error: {e}")


def main():
    """Main function"""
    print("=" * 60)
    print("NASA Solar Wind Health Alert System")
    print("Monitoring for weather-sensitive people")
    print("=" * 60)
    
    # Fetch data
    alerts = fetch_nasa_data()
    
    if not alerts:
        print("No alerts received. System may be offline or no active alerts.")
        return
    
    # Process for health-sensitive people
    health_alerts = process_alerts_for_health(alerts)
    
    # Display critical alerts
    processor = AlertProcessor()
    critical = processor.get_critical_alerts(alerts)
    
    if critical:
        print(f"\n⚠️ CRITICAL ALERTS ({len(critical)}):")
        for alert in critical[:5]:  # Show first 5
            print(f"  - {alert.warning_type} ({alert.get_severity().name})")
            print(f"    Health Impact: {alert.get_health_impact()}")
    
    # Visualize
    if health_alerts:
        visualize_data(health_alerts)
    
    print("\n✅ System running successfully")
    print("Alerts are being monitored for weather-sensitive people")


if __name__ == "__main__":
    main()
