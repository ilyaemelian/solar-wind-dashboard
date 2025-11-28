"""
Create professional visualizations for SolarWind Dashboard
High-quality graphics for academic presentations
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path

# TODO: Create professional visualizations for presentation

def create_solar_wind_speed_chart():
    """Create solar wind speed time series visualization"""
    # Generate sample data (in real app, fetch from NASA API)
    dates = [datetime.now() - timedelta(hours=i) for i in range(72, 0, -1)]
    wind_speed = 300 + np.random.randn(72) * 50 + np.sin(np.linspace(0, 4*np.pi, 72)) * 30
    
    # Create matplotlib figure
    fig, ax = plt.subplots(figsize=(14, 6), facecolor='#0a0e27')
    ax.set_facecolor('#0a0e27')
    
    ax.plot(dates, wind_speed, color='#00d1ff', linewidth=2.5, label='Solar Wind Speed')
    ax.axhline(y=400, color='#ff6f61', linestyle='--', alpha=0.7, label='Alert Threshold')
    ax.fill_between(dates, wind_speed, 400, where=(wind_speed > 400), 
                    color='#ff6f61', alpha=0.3, label='High Speed Zone')
    
    ax.set_xlabel('Time (UTC)', color='#9fb3c8', fontsize=12)
    ax.set_ylabel('Speed (km/s)', color='#9fb3c8', fontsize=12)
    ax.set_title('Solar Wind Speed - Real-time Monitoring', 
                color='#00d1ff', fontsize=16, fontweight='bold', pad=20)
    ax.legend(loc='upper right', facecolor='#0e1724', edgecolor='#00d1ff', 
              labelcolor='#9fb3c8')
    ax.grid(True, alpha=0.2, color='#9fb3c8')
    ax.tick_params(colors='#9fb3c8')
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    # Save
    output_path = Path(__file__).parent.parent.parent / 'visualizations' / 'solar_wind_speed.png'
    output_path.parent.mkdir(exist_ok=True)
    plt.savefig(output_path, dpi=300, facecolor='#0a0e27', bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()
    
    return output_path


def create_kp_index_heatmap():
    """Create Kp index heatmap for geomagnetic activity"""
    # Generate sample data
    dates = [datetime.now() - timedelta(days=i) for i in range(30, 0, -1)]
    hours = list(range(24))
    kp_values = np.random.rand(30, 24) * 9  # Kp index 0-9
    
    # Create figure
    fig, ax = plt.subplots(figsize=(16, 8), facecolor='#0a0e27')
    ax.set_facecolor('#0a0e27')
    
    im = ax.imshow(kp_values, aspect='auto', cmap='RdYlGn_r', 
                   vmin=0, vmax=9, interpolation='bilinear')
    
    # Set labels
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([f'{h:02d}:00' for h in range(0, 24, 3)], color='#9fb3c8')
    ax.set_yticks(range(0, 30, 5))
    ax.set_yticklabels([(datetime.now() - timedelta(days=30-i)).strftime('%m/%d') 
                        for i in range(0, 30, 5)], color='#9fb3c8')
    
    ax.set_xlabel('Hour (UTC)', color='#9fb3c8', fontsize=12)
    ax.set_ylabel('Date', color='#9fb3c8', fontsize=12)
    ax.set_title('Kp Index Heatmap - Geomagnetic Activity (30 days)', 
                color='#00d1ff', fontsize=16, fontweight='bold', pad=20)
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Kp Index', color='#9fb3c8', fontsize=11)
    cbar.ax.tick_params(colors='#9fb3c8')
    
    plt.tight_layout()
    
    # Save
    output_path = Path(__file__).parent.parent.parent / 'visualizations' / 'kp_index_heatmap.png'
    plt.savefig(output_path, dpi=300, facecolor='#0a0e27', bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()
    
    return output_path


def create_alert_timeline():
    """Create alert timeline visualization"""
    # Sample alert data
    alert_times = [datetime.now() - timedelta(hours=i*6) for i in range(10, 0, -1)]
    severities = ['G1', 'G2', 'G3', 'G2', 'G4', 'G3', 'G2', 'G1', 'G3', 'G2']
    colors_map = {'G1': '#27ae60', 'G2': '#3498db', 'G3': '#f39c12', 
                  'G4': '#e74c3c', 'G5': '#8e44ad'}
    
    fig, ax = plt.subplots(figsize=(14, 6), facecolor='#0a0e27')
    ax.set_facecolor('#0a0e27')
    
    y_pos = np.arange(len(alert_times))
    colors = [colors_map.get(s, '#9fb3c8') for s in severities]
    
    bars = ax.barh(y_pos, [1]*len(alert_times), color=colors, alpha=0.8, height=0.6)
    
    # Add severity labels
    for i, (time, severity) in enumerate(zip(alert_times, severities)):
        ax.text(0.5, i, f'{severity} - {time.strftime("%m/%d %H:%M")}', 
               color='white', fontweight='bold', va='center', ha='center')
    
    ax.set_yticks([])
    ax.set_xlim(0, 1)
    ax.set_xlabel('Alert Timeline', color='#9fb3c8', fontsize=12)
    ax.set_title('Space Weather Alerts - Health Impact Timeline', 
                color='#00d1ff', fontsize=16, fontweight='bold', pad=20)
    ax.tick_params(colors='#9fb3c8')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    
    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=color, label=severity) 
                      for severity, color in colors_map.items()]
    ax.legend(handles=legend_elements, loc='upper right', 
              facecolor='#0e1724', edgecolor='#00d1ff', labelcolor='#9fb3c8')
    
    plt.tight_layout()
    
    # Save
    output_path = Path(__file__).parent.parent.parent / 'visualizations' / 'alert_timeline.png'
    plt.savefig(output_path, dpi=300, facecolor='#0a0e27', bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()
    
    return output_path


def create_earth_visualization():
    """Create Earth with solar wind visualization"""
    fig, ax = plt.subplots(figsize=(12, 12), facecolor='#0a0e27', subplot_kw={'projection': 'polar'})
    ax.set_facecolor('#0a0e27')
    
    # Earth
    earth = plt.Circle((0, 0), 0.3, color='#3498db', zorder=3)
    ax.add_patch(earth)
    
    # Solar wind streams
    angles = np.linspace(0, 2*np.pi, 8)
    for angle in angles:
        x = 0.5 * np.cos(angle)
        y = 0.5 * np.sin(angle)
        ax.arrow(0, 0, x, y, head_width=0.05, head_length=0.05, 
                fc='#00d1ff', ec='#00d1ff', alpha=0.7, linewidth=2)
    
    ax.set_title('Solar Wind Streams Around Earth', 
                color='#00d1ff', fontsize=16, fontweight='bold', pad=30)
    ax.set_xticklabels([])
    ax.set_yticklabels([])
    ax.grid(True, alpha=0.3, color='#9fb3c8')
    
    plt.tight_layout()
    
    # Save
    output_path = Path(__file__).parent.parent.parent / 'visualizations' / 'earth_solar_wind.png'
    plt.savefig(output_path, dpi=300, facecolor='#0a0e27', bbox_inches='tight')
    print(f"Saved: {output_path}")
    plt.close()
    
    return output_path


def create_interactive_plotly_chart():
    """Create interactive Plotly visualization"""
    dates = [datetime.now() - timedelta(hours=i) for i in range(72, 0, -1)]
    wind_speed = 300 + np.random.randn(72) * 50
    kp_index = 2 + np.random.randn(72) * 1.5
    
    fig = go.Figure()
    
    # Solar wind speed
    fig.add_trace(go.Scatter(
        x=dates,
        y=wind_speed,
        mode='lines+markers',
        name='Solar Wind Speed',
        line=dict(color='#00d1ff', width=3),
        marker=dict(size=4)
    ))
    
    # Kp index (secondary y-axis)
    fig.add_trace(go.Scatter(
        x=dates,
        y=kp_index,
        mode='lines',
        name='Kp Index',
        yaxis='y2',
        line=dict(color='#ff6f61', width=2, dash='dash')
    ))
    
    fig.update_layout(
        title='Real-time Space Weather Monitoring',
        xaxis_title='Time (UTC)',
        yaxis=dict(title='Wind Speed (km/s)', side='left', color='#00d1ff'),
        yaxis2=dict(title='Kp Index', side='right', overlaying='y', color='#ff6f61'),
        template='plotly_dark',
        plot_bgcolor='#0a0e27',
        paper_bgcolor='#0a0e27',
        font=dict(color='#9fb3c8'),
        height=500,
        hovermode='x unified'
    )
    
    # Save
    output_path = Path(__file__).parent.parent.parent / 'visualizations' / 'interactive_chart.html'
    fig.write_html(str(output_path))
    print(f"Saved: {output_path}")
    
    return output_path


def main():
    """Generate all visualizations"""
    print("=" * 60)
    print("Creating professional visualizations for SolarWind Dashboard")
    print("=" * 60)
    
    visualizations = []
    
    print("\n1. Creating solar wind speed chart...")
    visualizations.append(create_solar_wind_speed_chart())
    
    print("\n2. Creating Kp index heatmap...")
    visualizations.append(create_kp_index_heatmap())
    
    print("\n3. Creating alert timeline...")
    visualizations.append(create_alert_timeline())
    
    print("\n4. Creating Earth visualization...")
    visualizations.append(create_earth_visualization())
    
    print("\n5. Creating interactive Plotly chart...")
    visualizations.append(create_interactive_plotly_chart())
    
    print("\n" + "=" * 60)
    print("All visualizations created successfully!")
    print("=" * 60)
    print(f"\nCreated {len(visualizations)} visualizations:")
    for viz in visualizations:
        print(f"  - {viz}")


if __name__ == "__main__":
    main()

