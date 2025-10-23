from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
import pandas as pd
import h3
from collections import defaultdict
import json

app = Flask(__name__)
CORS(app)

# Global variable to store processed data
logistics_df = None
pincode_geojson = None
supply_points = []

def load_logistics_data(csv_path):
    """Load and process logistics data"""
    try:
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], format='mixed', errors='coerce')
        df = df.dropna(subset=['Timestamp'])
        
        df['Hour'] = df['Timestamp'].dt.hour
        df['Date'] = df['Timestamp'].dt.date
        
        df['Time_Bin'] = pd.cut(df['Hour'], 
                               bins=[0, 6, 12, 18, 24],
                               labels=['Night (12AM-6AM)', 'Morning (6AM-12PM)', 
                                      'Afternoon (12PM-6PM)', 'Evening (6PM-12AM)'])
        
        df['Restaurant Latitude'] = pd.to_numeric(df['Restaurant Latitude'], errors='coerce')
        df['Restaurant Longitude'] = pd.to_numeric(df['Restaurant Longitude'], errors='coerce')
        df = df.dropna(subset=['Restaurant Latitude', 'Restaurant Longitude'])
        
        df['h3_index_id'] = df.apply(
            lambda row: h3.latlng_to_cell(
                row['Restaurant Latitude'], 
                row['Restaurant Longitude'],
                res=8
            ),
            axis=1
        )
        df.to_csv("data_with_h3.csv", index=False)
        
        print(f"✅ Loaded {len(df)} valid logistics records")
        return df
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")
        return None

def create_h3_hexagons(df):
    """Create H3 hexagons from filtered data"""
    hexagon_data = defaultdict(lambda: {
        'total_orders': 0,
        'success_orders': 0,
        'fail_orders': 0,
        'coords': set(),
        'time_bins': set()
    })
    
    for _, row in df.iterrows():
        try:
            lat = float(row['Restaurant Latitude'])
            lng = float(row['Restaurant Longitude'])
            
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            
            hex_id = row['h3_index_id']
            
            hexagon_data[hex_id]['total_orders'] += 1
            hexagon_data[hex_id]['coords'].add((lat, lng))
            hexagon_data[hex_id]['time_bins'].add(str(row['Time_Bin']))
            
            order_status = str(row['Order Status']).strip().lower()
            if order_status == 'success':
                hexagon_data[hex_id]['success_orders'] += 1
            else:
                hexagon_data[hex_id]['fail_orders'] += 1
                
        except (ValueError, TypeError):
            continue
    
    hexagons = []
    for hex_id, data in hexagon_data.items():
        if data['total_orders'] > 0:
            boundary = h3.cell_to_boundary(hex_id)
            boundary_coords = [[coord[1], coord[0]] for coord in boundary]
            
            success_rate = (data['success_orders'] / data['total_orders'] * 100)
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
                    'center_lng': round(center[1], 6),
                    'unique_restaurants': len(data['coords']),
                    'time_bins': ','.join(data['time_bins'])
                }
            })
    
    return {
        'type': 'FeatureCollection',
        'features': hexagons
    }

@app.route('/')
def index():
    """Render the main map page"""
    
    # Calculate statistics
    total_orders = len(logistics_df)
    success_orders = len(logistics_df[logistics_df['Order Status'].str.strip().str.lower() == 'success'])
    success_rate = (success_orders / total_orders * 100) if total_orders > 0 else 0
    total_restaurants = logistics_df[['Restaurant Latitude', 'Restaurant Longitude']].drop_duplicates().shape[0]
    
    # Initial hexagons (all data)
    initial_hexagons = create_h3_hexagons(logistics_df)
    
    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Logistics Supply-Demand Visualization</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
        <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
        <style>
            body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
            #map { position: absolute; top: 0; bottom: 0; width: 100%; }
            
            .filter-panel {
                position: fixed;
                top: 80px;
                right: 20px;
                width: 320px;
                background-color: white;
                border: 2px solid #3498db;
                z-index: 9999;
                font-size: 13px;
                padding: 15px;
                border-radius: 8px;
                box-shadow: 0 0 15px rgba(0,0,0,0.2);
                max-height: 80vh;
                overflow-y: auto;
            }
            
            .filter-title {
                margin: 0 0 15px 0;
                color: #3498db;
                font-size: 16px;
            }
            
            .filter-section {
                margin-bottom: 15px;
            }
            
            .filter-label {
                font-weight: bold;
                display: block;
                margin-bottom: 5px;
            }
            
            .time-bin-checkbox {
                display: block;
                margin: 5px 0;
                cursor: pointer;
            }
            
            .apply-btn {
                width: 100%;
                padding: 10px;
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
                font-size: 14px;
            }
            
            .apply-btn:hover {
                background-color: #2980b9;
            }
            
            .apply-btn:disabled {
                background-color: #95a5a6;
                cursor: not-allowed;
            }
            
            .filter-status {
                margin-top: 10px;
                padding: 8px;
                background-color: #ecf0f1;
                border-radius: 4px;
                font-size: 11px;
                display: none;
            }
            
            .legend {
                position: fixed;
                bottom: 50px;
                left: 50px;
                width: 280px;
                background-color: white;
                border: 2px solid grey;
                z-index: 9999;
                font-size: 14px;
                padding: 15px;
                border-radius: 5px;
                box-shadow: 0 0 15px rgba(0,0,0,0.2);
            }
            
            .title-banner {
                position: fixed;
                top: 10px;
                left: 50%;
                transform: translateX(-50%);
                width: 500px;
                background-color: white;
                border: 2px solid #3498db;
                z-index: 9999;
                font-size: 16px;
                padding: 15px;
                border-radius: 8px;
                box-shadow: 0 0 15px rgba(0,0,0,0.2);
                text-align: center;
            }
            
            .loading {
                display: inline-block;
                width: 12px;
                height: 12px;
                border: 2px solid #3498db;
                border-top-color: transparent;
                border-radius: 50%;
                animation: spin 0.6s linear infinite;
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            
            /* Ensure Leaflet controls are visible */
            .leaflet-control-layers,
            .leaflet-control-zoom {
                z-index: 1000 !important;
            }
        </style>
    </head>
    <body>
        <div id="map"></div>
        
        <div class="title-banner">
            <h3 style="margin: 0; color: #3498db;">🗺️ Logistics Supply-Demand Visualization</h3>
            <p style="margin: 5px 0; font-size: 12px; color: #666;">
                H3 Hexagons • Real-Time Filtering • Success Rate Heatmap
            </p>
        </div>
        
        <div class="filter-panel">
            <h3 class="filter-title">🔍 Time Period Filter</h3>
            
            <div class="filter-section">
                <label class="filter-label">Select Time Periods:</label>
                <label class="time-bin-checkbox">
                    <input type="checkbox" value="Night (12AM-6AM)" checked> Night (12AM-6AM)
                </label>
                <label class="time-bin-checkbox">
                    <input type="checkbox" value="Morning (6AM-12PM)" checked> Morning (6AM-12PM)
                </label>
                <label class="time-bin-checkbox">
                    <input type="checkbox" value="Afternoon (12PM-6PM)" checked> Afternoon (12PM-6PM)
                </label>
                <label class="time-bin-checkbox">
                    <input type="checkbox" value="Evening (6PM-12AM)" checked> Evening (6PM-12AM)
                </label>
            </div>
            
            <button id="apply-filter" class="apply-btn">Apply Filter</button>
            
            <div id="filter-status" class="filter-status"></div>
        </div>
        
        <div class="legend">
            <p style="margin: 0; font-weight: bold; font-size: 16px; margin-bottom: 10px;">
                🚚 Logistics Heatmap Legend
            </p>
            <p style="margin: 5px 0;"><strong>Total Orders:</strong> {{ total_orders }}</p>
            <p style="margin: 5px 0;"><strong>Total Restaurants:</strong> {{ total_restaurants }}</p>
            <p style="margin: 5px 0;"><strong>Overall Success Rate:</strong> {{ success_rate }}%</p>
            <p style="margin: 5px 0;"><strong>Active Hexagons:</strong> <span id="hexagon-count">{{ hexagon_count }}</span></p>
            <hr style="margin: 10px 0;">
            <p style="margin: 5px 0; font-weight: bold;">Success Rate Colors:</p>
            <p style="margin: 3px 0;"><span style="color: #1a9850;">█</span> 80-100% (Excellent)</p>
            <p style="margin: 3px 0;"><span style="color: #91cf60;">█</span> 60-80% (Good)</p>
            <p style="margin: 3px 0;"><span style="color: #fee090;">█</span> 40-60% (Fair)</p>
            <p style="margin: 3px 0;"><span style="color: #fc8d59;">█</span> 20-40% (Poor)</p>
            <p style="margin: 3px 0;"><span style="color: #d73027;">█</span> 0-20% (Critical)</p>
        </div>
        
        <script>
            // Initialize map
            var map = L.map('map').setView([20.5937, 78.9629], 5);
            
            // Add base layer
            L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
                subdomains: 'abcd',
                maxZoom: 20
            }).addTo(map);
            
            // Create layer groups for proper z-index control
            var pincodeLayer = null;
            var hexagonLayer = null;
            var markerClusterGroup = null;
            
            // Add pincode boundaries FIRST (bottom layer)
            var pincodeData = {{ pincode_data | tojson }};
            if (pincodeData && pincodeData.features && pincodeData.features.length > 0) {
                pincodeLayer = L.geoJSON(pincodeData, {
                    style: {
                        fillColor: 'transparent',
                        color: '#3388ff',
                        weight: 1,
                        fillOpacity: 0,
                        opacity: 0.4
                    },
                    onEachFeature: function(feature, layer) {
                        if (feature.properties.Pincode) {
                            layer.bindTooltip(
                                '<b>Pincode:</b> ' + feature.properties.Pincode + '<br>' +
                                '<b>Office:</b> ' + (feature.properties.Office_Name || 'N/A'),
                                {
                                    style: "background-color: white; color: #333333; font-family: arial; font-size: 11px; padding: 8px;"
                                }
                            );
                        }
                    },
                    pane: 'tilePane' // Put pincode boundaries below everything
                }).addTo(map);
            }
            
            // Initial hexagon data
            var initialData = {{ initial_hexagons | tojson }};
            renderHexagons(initialData);
            
            // Add supply points (restaurant locations) with MarkerCluster
            var supplyPoints = {{ supply_points | tojson }};
            markerClusterGroup = L.markerClusterGroup({
                maxClusterRadius: 20,
                spiderfyOnMaxZoom: true,
                showCoverageOnHover: false,
                zoomToBoundsOnClick: true
            });
            
            supplyPoints.forEach(function(point) {
                var marker = L.circleMarker([point[0], point[1]], {
                    radius: 3,
                    color: '#27ae60',
                    fillColor: '#2ecc71',
                    fillOpacity: 0.7,
                    weight: 1,
                    pane: 'markerPane' // Ensure markers are on top
                });
                marker.bindPopup('Restaurant: ' + point[0].toFixed(6) + ', ' + point[1].toFixed(6));
                markerClusterGroup.addLayer(marker);
            });
            
            map.addLayer(markerClusterGroup);
            
            // Layer control - will be updated dynamically
            var baseMaps = {};
            var overlayMaps = {};
            var layerControl = null;
            
            // Initialize layer control
            function initLayerControl() {
                // Remove old control if it exists
                if (layerControl) {
                    map.removeControl(layerControl);
                }
                
                // Rebuild overlay maps with current layers
                overlayMaps = {
                    "H3 Hexagons (Success Rate)": hexagonLayer,
                    "Supply Points (Restaurants)": markerClusterGroup
                };
                
                if (pincodeLayer) {
                    overlayMaps["Pincode Boundaries"] = pincodeLayer;
                }
                
                // Create new control
                layerControl = L.control.layers(baseMaps, overlayMaps, {
                    collapsed: false,
                    position: 'topright'
                });
                
                layerControl.addTo(map);
            }
            
            // Initialize the layer control
            initLayerControl();
            
            // Filter functionality
            document.getElementById('apply-filter').addEventListener('click', applyFilter);
            
            function applyFilter() {
                var btn = document.getElementById('apply-filter');
                var statusDiv = document.getElementById('filter-status');
                
                // Get selected time bins
                var checkboxes = document.querySelectorAll('.time-bin-checkbox input[type="checkbox"]:checked');
                var selectedTimeBins = Array.from(checkboxes).map(cb => cb.value);
                
                if (selectedTimeBins.length === 0) {
                    statusDiv.style.display = 'block';
                    statusDiv.innerHTML = '⚠️ Please select at least one time period';
                    statusDiv.style.backgroundColor = '#ffe6e6';
                    return;
                }
                
                // Disable button and show loading
                btn.disabled = true;
                btn.innerHTML = '<span class="loading"></span> Filtering...';
                
                // Make API call
                fetch('/filter_hexagons', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        time_bins: selectedTimeBins
                    })
                })
                .then(response => response.json())
                .then(data => {
                    renderHexagons(data.hexagons);
                    
                    // Update status
                    statusDiv.style.display = 'block';
                    statusDiv.style.backgroundColor = '#d4edda';
                    statusDiv.innerHTML = '✅ Showing ' + data.hexagons.features.length + ' hexagons<br>' +
                                        'Total Orders: ' + data.stats.total_orders + '<br>' +
                                        'Success Rate: ' + data.stats.success_rate + '%';
                    
                    // Update hexagon count
                    document.getElementById('hexagon-count').textContent = data.hexagons.features.length;
                    
                    // Reinitialize layer control with new hexagon layer reference
                    initLayerControl();
                    
                    // Re-enable button
                    btn.disabled = false;
                    btn.innerHTML = 'Apply Filter';
                })
                .catch(error => {
                    console.error('Error:', error);
                    statusDiv.style.display = 'block';
                    statusDiv.style.backgroundColor = '#ffe6e6';
                    statusDiv.innerHTML = '❌ Error applying filter';
                    
                    btn.disabled = false;
                    btn.innerHTML = 'Apply Filter';
                });
            }
            
            function renderHexagons(geojson) {
                // Remove existing hexagon layer
                if (hexagonLayer) {
                    map.removeLayer(hexagonLayer);
                }
                
                // Add new hexagon layer on overlayPane (above pincode boundaries)
                hexagonLayer = L.geoJSON(geojson, {
                    style: function(feature) {
                        return {
                            fillColor: getColor(feature.properties.success_rate),
                            color: '#333333',
                            weight: 0.3,
                            fillOpacity: 0.6,
                            opacity: 0.8
                        };
                    },
                    onEachFeature: function(feature, layer) {
                        var props = feature.properties;
                        layer.bindTooltip(
                            '<b>H3 Index:</b> ' + props.h3_index + '<br>' +
                            '<b>Total Orders:</b> ' + props.total_orders + '<br>' +
                            '<b>Success:</b> ' + props.success_orders + '<br>' +
                            '<b>Failed:</b> ' + props.fail_orders + '<br>' +
                            '<b>Success Rate:</b> ' + props.success_rate + '%<br>' +
                            '<b>Restaurants:</b> ' + props.unique_restaurants,
                            {
                                style: "background-color: white; color: #333333; font-family: arial; font-size: 12px; padding: 10px;"
                            }
                        );
                    },
                    pane: 'overlayPane' // Put hexagons above pincode boundaries
                }).addTo(map);
            }
            
            function getColor(success_rate) {
                if (success_rate >= 80) return '#1a9850';
                else if (success_rate >= 60) return '#91cf60';
                else if (success_rate >= 40) return '#fee090';
                else if (success_rate >= 20) return '#fc8d59';
                else return '#d73027';
            }
        </script>
    </body>
    </html>
    '''
    
    return render_template_string(
        html_template,
        initial_hexagons=initial_hexagons,
        total_orders=f"{total_orders:,}",
        total_restaurants=f"{total_restaurants:,}",
        success_rate=f"{success_rate:.1f}",
        hexagon_count=f"{len(initial_hexagons['features']):,}",
        pincode_data=pincode_geojson if pincode_geojson else {},
        supply_points=supply_points
    )

@app.route('/filter_hexagons', methods=['POST'])
def filter_hexagons():
    """API endpoint to filter hexagons by time bins"""
    try:
        data = request.get_json()
        selected_time_bins = data.get('time_bins', [])
        
        if not selected_time_bins:
            return jsonify({'error': 'No time bins selected'}), 400
        
        # Filter dataframe by time bins
        filtered_df = logistics_df[logistics_df['Time_Bin'].isin(selected_time_bins)]
        
        # Create hexagons from filtered data
        hexagons = create_h3_hexagons(filtered_df)
        
        # Calculate stats
        total_orders = len(filtered_df)
        success_orders = len(filtered_df[filtered_df['Order Status'].str.strip().str.lower() == 'success'])
        success_rate = (success_orders / total_orders * 100) if total_orders > 0 else 0
        
        return jsonify({
            'hexagons': hexagons,
            'stats': {
                'total_orders': total_orders,
                'success_orders': success_orders,
                'success_rate': round(success_rate, 1)
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("=" * 70)
    print("🚀 Starting Flask Server for Dynamic Logistics Visualization")
    print("=" * 70)
    
    # Load data
    print("\n📊 Loading logistics data...")
    logistics_df = load_logistics_data('logistics_data.csv')
    
    if logistics_df is None:
        print("❌ Failed to load logistics data. Exiting.")
        exit(1)
    
    # Extract supply points (restaurant locations)
    print("📍 Extracting supply points...")
    supply_points = logistics_df[['Restaurant Latitude', 'Restaurant Longitude']].drop_duplicates().values.tolist()
    print(f"   Found {len(supply_points)} unique supply points")
    
    # Load pincode GeoJSON
    print("📍 Loading pincode boundaries...")
    try:
        with open('pincode_simplified.geojson', 'r', encoding='utf-8') as f:
            pincode_geojson = json.load(f)
        print(f"   Loaded {len(pincode_geojson['features'])} pincode boundaries")
    except FileNotFoundError:
        print("⚠️  Pincode GeoJSON not found, skipping")
        pincode_geojson = None
    except Exception as e:
        print(f"⚠️  Error loading pincode boundaries: {e}")
        pincode_geojson = None
    
    print("\n" + "=" * 70)
    print("✅ Server ready!")
    print("🌐 Open your browser and go to: http://127.0.0.1:5000")
    print("=" * 70)
    print("\n🔥 Features:")
    print("   ✓ Real-time time bin filtering (no page reload)")
    print("   ✓ Dynamic hexagon updates via API")
    print("   ✓ Supply points with marker clustering")
    print("   ✓ Proper layer ordering (Pincode → Hexagons → Markers)")
    print("   ✓ Layer control panel with proper hide/unhide")
    print("   ✓ Live statistics updates")
    print("\n💡 Press Ctrl+C to stop the server")
    print("=" * 70 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)