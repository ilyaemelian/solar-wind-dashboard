# 🌌 NASA Solar Wind Health Alert System

## 📋 Overview
A predictive alert system for geomagnetic disturbances using NASA/NOAA space weather data. Designed specifically for **weather-sensitive people**, including:
- **Cardiovascular patients** (heart disease, hypertension)
- **Elderly individuals** (increased sensitivity to geomagnetic storms)
- **People with weather sensitivity** (meteoropathy)

The system monitors space weather events and provides early warnings when geomagnetic disturbances may affect health-sensitive populations.

## ✨ Features

### 🔄 Core Functionality
- **Real-time data ingestion** from NOAA Space Weather Prediction Center
- **Health-focused alert system** - filters alerts relevant for weather-sensitive people
- **Multi-language support** - English and Russian translations
- **Severity classification** - G1 (Minor) to G5 (Extreme) based on NOAA scale
- **Health impact assessment** - specific warnings for cardiovascular patients and elderly

### 📊 Alert Types
- **Geomagnetic Alerts (K-index)** - Most relevant for health impacts
- **Forecast Alerts** - Storm predictions and warnings
- **Radio Emission Alerts** - Type II radio bursts
- **Electron Flux Alerts** - High-energy particle events

### ⚠️ Health Impact Levels
- **G3 (Strong)** and above: Significant impact on weather-sensitive people
- **G4 (Severe)**: High risk for heart patients and elderly
- **G5 (Extreme)**: All weather-sensitive people should take precautions

## 🛠️ Tech Stack
- **Python 3.8+**
- **Data Processing**: numpy, pandas
- **Visualization**: matplotlib, plotly
- **Translation**: deep-translator (Google Translate)
- **API**: requests for NOAA data
- **Web Framework**: Flask (optional)

## 📦 Installation

1. **Clone the repository**
```bash
git clone https://github.com/ilyaemelian/solar-wind-dashboard.git
cd solar-wind-dashboard
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Run the alert system**
```bash
python main.py
```

## 🚀 Usage

### Basic Usage
```python
from src.data_ingestion.noaa_api import fetch_noaa_alerts
from src.alerts.alert_processor import AlertProcessor

# Fetch alerts
alerts = fetch_noaa_alerts()

# Process for health-sensitive people
processor = AlertProcessor()
health_alerts = processor.filter_health_relevant(alerts)

# Get critical alerts (G4, G5)
critical = processor.get_critical_alerts(alerts)
```

### Alert Processing
The system automatically:
1. Fetches real-time data from NOAA
2. Parses different alert types
3. Filters alerts relevant for weather-sensitive people
4. Translates to Russian (if needed)
5. Generates health impact assessments

## 🏆 Project Status

✅ **Production-Ready System**: Successfully demonstrated at "33rd International Space Olympiad" and won the competition.

✅ **Current Features**:
- Real-time NOAA data ingestion
- Alert processing and filtering
- Health impact assessment
- Multi-language support
- Visualization capabilities

## 📁 Project Structure

```
solar-wind-dashboard/
├── src/
│   ├── alerts/              # Alert models and processing
│   ├── data_ingestion/      # NOAA API integration
│   ├── translation/         # Multi-language support
│   └── visualization/       # Data visualization
├── docs/                     # Documentation
├── visualizations/          # Generated visualizations
├── main.py                  # Main entry point
├── requirements.txt         # Dependencies
└── README.md               # This file
```

## 💊 Health Impact Information

### Why This Matters
Geomagnetic storms can affect:
- **Cardiovascular system** - increased risk of heart attacks and strokes
- **Blood pressure** - elevated during strong storms
- **Sleep patterns** - disturbances in sensitive individuals
- **General well-being** - discomfort and fatigue

### Alert Severity Guide
- **G1 (Minor)**: Weak power grid fluctuations, minor aurora
- **G2 (Moderate)**: Voltage corrections may be required, moderate aurora
- **G3 (Strong)**: Power system problems, navigation issues - **affects health-sensitive people**
- **G4 (Severe)**: Widespread voltage problems, transformer damage - **high risk for heart patients**
- **G5 (Extreme)**: Complete power grid collapse possible - **all weather-sensitive people at risk**

## 🎓 Academic Context

This project demonstrates:
- Scientific computing skills
- Real-world problem solving
- Social impact (helping vulnerable populations)
- Data engineering and visualization
- Software development with real satellite data

## 📄 License

MIT License

## 👤 Author

**Ilya Emelianov**
- GitHub: [@ilyaemelian](https://github.com/ilyaemelian)
- Project: [solar-wind-dashboard](https://github.com/ilyaemelian/solar-wind-dashboard)

## 🙏 Acknowledgments

- NOAA Space Weather Prediction Center for providing data
- NASA for solar wind datasets
- Deep-translator for translation services

