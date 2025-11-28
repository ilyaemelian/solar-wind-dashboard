# Visualizations

This directory contains professional visualizations for the SolarWind Dashboard project.

## Generated Visualizations

### Static PNG Files (1920×1080)

1. **solar_wind_speed.png** - Real-time solar wind speed time series
2. **kp_index_heatmap.png** - 30-day Kp index heatmap showing geomagnetic activity
3. **alert_timeline.png** - Timeline of space weather alerts with severity levels
4. **earth_solar_wind.png** - Visualization of solar wind streams around Earth

### Interactive HTML Files

1. **interactive_chart.html** - Interactive Plotly dashboard with real-time data

## Generating Visualizations

To create/update visualizations:

```bash
cd solar-wind-dashboard
python src/visualization/create_visualizations.py
```

Or if you're using Python 3 specifically:

```bash
python3 src/visualization/create_visualizations.py
```

## Requirements

- matplotlib >= 3.7.0
- plotly >= 5.14.0
- numpy >= 1.24.0

## Usage

- **For presentations:** Use PNG files (1920×1080) in slides or PDF
- **For web:** Use HTML files for interactive exploration
- **For publications:** High-resolution PNG files suitable for academic papers

## Notes

- All visualizations use dark theme matching the project design
- Colors: #00d1ff (accent), #9fb3c8 (muted), #0a0e27 (background)
- Format optimized for academic presentations

