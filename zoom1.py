import folium
from folium import plugins
import json
import pandas as pd
import h3
from collections import defaultdict
from datetime import datetime

# Load logistics CSV data
def load_logistics_data(csv_path):
    """Load and process logistics data"""
    try:
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        
        # Parse timestamp with mixed format support
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], format='mixed', errors='coerce')
        df = df.dropna(subset=['Timestamp'])
        
        # Extract hour and date
        df['Hour'] = df['Timestamp'].dt.hour
        df['Date'] = df['Timestamp'].dt.date
        
        # Create time bins
        df['Time_Bin'] = pd.cut(df['Hour'], 
                               bins=[0, 6, 12, 18, 24],
                               labels=['Night (12AM-6AM)', 'Morning (6AM-12PM)', 
                                      'Afternoon (12PM-6PM)', 'Evening (6PM-12AM)'])
        
        # Clean coordinates
        df['Restaurant Latitude'] = pd.to_numeric(df['Restaurant Latitude'], errors='coerce')
        df['Restaurant Longitude'] = pd.to_numeric(df['Restaurant Longitude'], errors='coerce')
        df = df.dropna(subset=['Restaurant Latitude', 'Restaurant Longitude'])
        
        print(f"✅ Loaded {len(df)} valid logistics records")
        return df
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")
        return None

def create_h3_hexagons(df, resolution=8):
    """Create H3 hexagons from GPS coordinates with aggregated data"""
    hexagon_data = defaultdict(lambda: {
        'total_orders': 0,
        'success_orders': 0,
        'fail_orders': 0,
        'coords': []
    })
    
    for _, row in df.iterrows():
        try:
            lat = float(row['Restaurant Latitude'])
            lng = float(row['Restaurant Longitude'])
            
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            
            # Get H3 index for this coordinate
            hex_id = h3.latlng_to_cell(lat, lng, resolution)
            
            hexagon_data[hex_id]['total_orders'] += 1
            hexagon_data[hex_id]['coords'].append((lat, lng))
            
            order_status = str(row['Order Status']).strip().lower()
            if order_status == 'success':
                hexagon_data[hex_id]['success_orders'] += 1
            else:
                hexagon_data[hex_id]['fail_orders'] += 1
                
        except (ValueError, TypeError):
            continue
    
    # Create hexagon features
    hexagons = []
    for hex_id, data in hexagon_data.items():
        if data['total_orders'] > 0:
            # Get hexagon boundary
            boundary = h3.cell_to_boundary(hex_id)
            boundary_coords = [[coord[1], coord[0]] for coord in boundary]  # [lng, lat] for GeoJSON
            
            # Calculate success rate
            success_rate = (data['success_orders'] / data['total_orders'] * 100)
            
            # Get center
            center = h3.cell_to_latlng(hex_id)
            
            hexagons.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [boundary_coords]
                },
                'properties': {
                    'h3_index': hex_id,
                    'total_orders': data['total_orders'],
                    'success_orders': data['success_orders'],
                    'fail_orders': data['fail_orders'],
                    'success_rate': round(success_rate, 2),
                    'center_lat': round(center[0], 6),
                    'center_lng': round(center[1], 6)
                }
            })
    
    return {
        'type': 'FeatureCollection',
        'features': hexagons
    }

def get_color_from_success_rate(success_rate):
    """Get color based on success rate"""
    if success_rate >= 80:
        return '#1a9850'  # Dark green
    elif success_rate >= 60:
        return '#91cf60'  # Light green
    elif success_rate >= 40:
        return '#fee090'  # Yellow
    elif success_rate >= 20:
        return '#fc8d59'  # Orange
    else:
        return '#d73027'  # Red

def create_map_with_h3_and_pincodes(logistics_csv, pincode_geojson_path, resolution=8):
    """Create interactive map with H3 hexagons and pincode boundaries"""
    
    # Load logistics data
    print("📊 Loading logistics data...")
    df = load_logistics_data(logistics_csv)
    if df is None:
        return None
    
    # Create H3 hexagons
    print(f"🔷 Creating H3 hexagons at resolution {resolution}...")
    h3_geojson = create_h3_hexagons(df, resolution)
    print(f"   Created {len(h3_geojson['features'])} hexagons")
    
    # Calculate overall statistics
    total_orders = len(df)
    success_orders = len(df[df['Order Status'].str.strip().str.lower() == 'success'])
    success_rate = (success_orders / total_orders * 100) if total_orders > 0 else 0
    
    # Create base map
    print("🗺️  Creating map...")
    m = folium.Map(
        location=[20.5937, 78.9629],  # India center
        zoom_start=5,
        tiles='CartoDB positron'
    )
    
    # Add pincode boundaries layer
    print("📍 Loading pincode boundaries...")
    try:
        with open(pincode_geojson_path, 'r', encoding='utf-8') as f:
            pincode_geojson = json.load(f)
        
        folium.GeoJson(
            pincode_geojson,
            name='Pincode Boundaries',
            style_function=lambda x: {
                'fillColor': 'transparent',
                'color': '#3388ff',
                'weight': 1,
                'fillOpacity': 0,
                'opacity': 0.4
            },
            highlight_function=lambda x: {
                'weight': 2,
                'color': '#ff0000',
                'fillOpacity': 0.1
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['Pincode', 'Office_Name'],
                aliases=['Pincode:', 'Office:'],
                style="background-color: white; color: #333333; font-family: arial; font-size: 11px; padding: 8px;"
            ),
            show=True
        ).add_to(m)
        
        print(f"   Loaded {len(pincode_geojson['features'])} pincode boundaries")
    except FileNotFoundError:
        print("⚠️  Pincode GeoJSON not found, skipping pincode boundaries")
    except Exception as e:
        print(f"⚠️  Error loading pincode boundaries: {e}")
    
    # Add H3 hexagons layer with heatmap colors
    print("🔷 Adding H3 hexagons layer...")
    folium.GeoJson(
        h3_geojson,
        name='H3 Hexagons (Success Rate)',
        style_function=lambda feature: {
            'fillColor': get_color_from_success_rate(feature['properties']['success_rate']),
            'color': '#333333',
            'weight': 1,
            'fillOpacity': 0.6,
            'opacity': 0.8
        },
        highlight_function=lambda x: {
            'weight': 3,
            'color': '#000000',
            'fillOpacity': 0.8
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['h3_index', 'total_orders', 'success_orders', 'fail_orders', 'success_rate'],
            aliases=['H3 Index:', 'Total Orders:', 'Success:', 'Failed:', 'Success Rate:'],
            style="background-color: white; color: #333333; font-family: arial; font-size: 12px; padding: 10px;"
        ),
        show=True
    ).add_to(m)
    
    # Add supply points layer (restaurant locations)
    print("📍 Adding supply points...")
    supply_points = []
    for _, row in df.iterrows():
        supply_points.append([
            row['Restaurant Latitude'],
            row['Restaurant Longitude']
        ])
    
    # Add marker cluster for supply points
    marker_cluster = plugins.MarkerCluster(
        name='Supply Points (Restaurants)',
        show=False,
        options={
            'maxClusterRadius': 20   # smaller = split earlier; try 20–40
        }
    ).add_to(m)
    
    for lat, lng in supply_points:  # Limit to 500 for performance
        folium.CircleMarker(
            location=[lat, lng],
            radius=3,
            color='#27ae60',
            fill=True,
            fillColor='#2ecc71',
            fillOpacity=0.7,
            popup=f'Restaurant: {lat:.6f}, {lng:.6f}'
        ).add_to(marker_cluster)
    
    # Add legend
    legend_html = f'''
    <div style="position: fixed; 
                bottom: 50px; left: 50px; width: 280px; height: auto; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 15px; border-radius: 5px;
                box-shadow: 0 0 15px rgba(0,0,0,0.2);">
        <p style="margin: 0; font-weight: bold; font-size: 16px; margin-bottom: 10px;">
            🚚 Logistics Heatmap Legend
        </p>
        <p style="margin: 5px 0;"><strong>Total Orders:</strong> {total_orders:,}</p>
        <p style="margin: 5px 0;"><strong>Overall Success Rate:</strong> {success_rate:.1f}%</p>
        <p style="margin: 5px 0;"><strong>Active Hexagons:</strong> {len(h3_geojson['features']):,}</p>
        <hr style="margin: 10px 0;">
        <p style="margin: 5px 0; font-weight: bold;">Success Rate Colors:</p>
        <p style="margin: 3px 0;"><span style="color: #1a9850;">█</span> 80-100% (Excellent)</p>
        <p style="margin: 3px 0;"><span style="color: #91cf60;">█</span> 60-80% (Good)</p>
        <p style="margin: 3px 0;"><span style="color: #fee090;">█</span> 40-60% (Fair)</p>
        <p style="margin: 3px 0;"><span style="color: #fc8d59;">█</span> 20-40% (Poor)</p>
        <p style="margin: 3px 0;"><span style="color: #d73027;">█</span> 0-20% (Critical)</p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    # Add layer control
    folium.LayerControl(collapsed=False).add_to(m)
    
    # Add title
    title_html = '''
    <div style="position: fixed; 
                top: 10px; left: 50%; transform: translateX(-50%);
                width: 500px; background-color: white; 
                border:2px solid #3498db; z-index:9999; 
                font-size:16px; padding: 15px; border-radius: 8px;
                box-shadow: 0 0 15px rgba(0,0,0,0.2);
                text-align: center;">
        <h3 style="margin: 0; color: #3498db;">
            🗺️ Logistics Supply-Demand Visualization
        </h3>
        <p style="margin: 5px 0; font-size: 12px; color: #666;">
            H3 Hexagons • Pincode Boundaries • Success Rate Heatmap
        </p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))
    
    return m

# Main execution
if __name__ == '__main__':
    print("=" * 70)
    print("🚚 Logistics H3 Hexagon Visualization with Pincode Boundaries")
    print("=" * 70)
    
    # Configuration
    logistics_csv = 'logistics_data.csv'
    pincode_geojson = 'pincode_simplified.geojson'
    h3_resolution = 8  # 8 is good for city-level, 9 for neighborhood-level
    output_file = 'logistics_h3_heatmap.html'
    
    # Create map
    m = create_map_with_h3_and_pincodes(
        logistics_csv=logistics_csv,
        pincode_geojson_path=pincode_geojson,
        resolution=h3_resolution
    )
    
    if m:
        # Save map
        m.save(output_file)
        print(f"\n✅ Map saved to: {output_file}")
        print(f"\n📊 Features:")
        print(f"   ✓ Pincode boundaries from government dataset")
        print(f"   ✓ H3 hexagons aggregating GPS coordinates")
        print(f"   ✓ Success rate heatmap (color-coded)")
        print(f"   ✓ Supply points (restaurant locations)")
        print(f"   ✓ Interactive tooltips with details")
        print(f"   ✓ Layer controls for toggling views")
        print(f"\n💡 Tip: Adjust h3_resolution (7-10) for different zoom levels")
        print("=" * 70)
        
        # Open in browser
        import webbrowser
        import os
        webbrowser.open('file://' + os.path.realpath(output_file))
    else:
        print("\n❌ Failed to create map. Check errors above.")
        print("=" * 70)