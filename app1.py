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
        
        # Create hour bins (00-01, 01-02, etc.)
        df['Hour_Bin'] = df['Hour'].apply(lambda x: f"{x:02d}-{(x+1):02d}")
        
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
        'hour_bins': set(),
        'logistics_players': set()
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
            hexagon_data[hex_id]['hour_bins'].add(str(row['Hour_Bin']))
            hexagon_data[hex_id]['logistics_players'].add(str(row['Logistics Player']))
            
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
                    'hour_bins': ','.join(sorted(data['hour_bins'])),
                    'logistics_players': ','.join(data['logistics_players'])
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
    
    # Get unique logistics players
    logistics_players = sorted(
        logistics_df['Logistics Player']
        .dropna()                           # remove NaN values
        .astype(str)                        # ensure all are strings
        .loc[lambda x: (x.str.strip() != '') & (x.str.lower() != 'unknown')]  # remove empty or 'unknown'
        .unique()
        .tolist()
    )
    
    # Get unique hour bins
    hour_bins = sorted(logistics_df['Hour_Bin'].unique().tolist())
    
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
            * { box-sizing: border-box; }
            body { margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            #map { position: absolute; top: 45px; bottom: 0; width: 100%; }
            
            /* Top Filter Bar */
            .top-filter-bar {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                height: 45px; /* thinner */
                background: #f7f7f7; /* light gray-white */
                border-bottom: 1px solid #ddd; /* subtle separator */
                box-shadow: none; /* remove heavy shadow */
                z-index: 10000;
                display: flex;
                align-items: center;
                padding: 0 15px;
                gap: 15px;
            }

            
            .filter-group {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .filter-label {
                color: #333;
                font-weight: 500;
            }
            
            .filter-select {
                padding: 8px 12px;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                background: white;
                cursor: pointer;
                min-width: 150px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                transition: all 0.3s;
            }
            
            .filter-select:hover {
                box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            }
            
            .filter-select:focus {
                outline: 2px solid #ffd700;
            }
            
            .gps-input {
                padding: 8px 12px;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                width: 200px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            
            .gps-input::placeholder {
                color: #999;
            }
            
            .apply-btn {
                padding: 6px 16px;
                background: #e0e0e0;
                color: #333;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-weight: 500;
                font-size: 13px;
                cursor: pointer;
                transition: all 0.2s ease;
            }
            
            .apply-btn:hover {
                background: #d5d5d5;
            }
            
            .apply-btn:disabled {
                background: #f0f0f0;
                color: #888;
                cursor: not-allowed;
            }
            
            .loading {
                display: inline-block;
                width: 12px;
                height: 12px;
                border: 2px solid #333;
                border-top-color: transparent;
                border-radius: 50%;
                animation: spin 0.6s linear infinite;
                margin-right: 5px;
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            
            /* Legend */
            .legend {
                position: fixed;
                bottom: 10px;
                left: 10px;
                width: 150px;
                background-color: white;
                border: none;
                z-index: 9999;
                font-size: 11px;
                padding: 5px;
                border-radius: 5px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            
            .legend-title {
                font-weight: bold;
                font-size: 12px;
                margin-bottom: 5px;
            }
            
            .legend p {
                margin: 5px 0;
            }
            
            /* Leaflet controls adjustment */
            .leaflet-control-layers,
            .leaflet-control-zoom {
                z-index: 1000 !important;
                margin-top: 10px !important;
            }
            
            /* Status message */
            .status-message {
                position: fixed;
                top: 70px;
                right: 20px;
                background: white;
                padding: 12px 20px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                z-index: 9999;
                display: none;
                font-size: 13px;
                max-width: 300px;
            }
            
            .status-message.success {
                border-left: 4px solid #10b981;
            }
            
            .status-message.error {
                border-left: 4px solid #ef4444;
            }
        </style>
    </head>
    <body>
        <!-- Top Filter Bar -->
        <div class="top-filter-bar">
            <div class="filter-group">
                <label class="filter-label">Filter by Logistics Player:</label>
                <select id="logistics-player-filter" class="filter-select">
                    <option value="All">All</option>
                    {% for player in logistics_players %}
                    <option value="{{ player }}">{{ player.split('/')[-1] }}</option>
                    {% endfor %}
                </select>
            </div>
            
            <div class="filter-group">
                <label class="filter-label">Filter by Hour Bin:</label>
                <select id="hour-bin-filter" class="filter-select">
                    <option value="All">All</option>
                    {% for bin in hour_bins %}
                    <option value="{{ bin }}">{{ bin }}</option>
                    {% endfor %}
                </select>
            </div>
            
            <div class="filter-group">
                <label class="filter-label">Enter your GPS:</label>
                <input type="text" id="gps-input" class="gps-input" placeholder="Lat, Lon">
            </div>
            
            <button id="apply-filter" class="apply-btn">Apply Filters</button>
        </div>
        
        <!-- Status Message -->
        <div id="status-message" class="status-message"></div>
        
        <!-- Map -->
        <div id="map"></div>
        
        <!-- Legend -->
        <div class="legend">
            <p class="legend-title">🚚 Logistics Heatmap</p>
            <p><strong>Total Orders:</strong> {{ total_orders }}</p>
            <p><strong>Total Restaurants:</strong> {{ total_restaurants }}</p>
            <p><strong>Success Rate:</strong> {{ success_rate }}%</p>
            <p><strong>Active Hexagons:</strong> <span id="hexagon-count">{{ hexagon_count }}</span></p>
            <hr style="margin: 10px 0; border: none; border-top: 1px solid #e5e7eb;">
            <p style="font-weight: bold; margin-bottom: 5px;">Success Rate Colors:</p>
            <p style="margin: 3px 0;"><span style="color: #1a9850;">█</span> 80-100% (Excellent)</p>
            <p style="margin: 3px 0;"><span style="color: #91cf60;">█</span> 60-80% (Good)</p>
            <p style="margin: 3px 0;"><span style="color: #fee090;">█</span> 40-60% (Fair)</p>
            <p style="margin: 3px 0;"><span style="color: #fc8d59;">█</span> 20-40% (Poor)</p>
            <p style="margin: 3px 0;"><span style="color: #d73027;">█</span> 0-20% (Critical)</p>
        </div>
        
        <script>
            // Initialize map
            var map = L.map('map').setView([28.5355, 77.2200], 12);
            
            // Add base layer
            L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
                subdomains: 'abcd',
                maxZoom: 20
            }).addTo(map);
            
            // Create layer groups
            var pincodeLayer = null;
            var hexagonLayer = null;
            var markerClusterGroup = null;
            var gpsMarker = null;
            
            // Add pincode boundaries
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
                                { className: 'custom-tooltip' }
                            );
                        }
                    },
                    pane: 'tilePane'
                }).addTo(map);
            }
            
            // Initial hexagon data
            var initialData = {{ initial_hexagons | tojson }};
            renderHexagons(initialData);
            
            // Add supply points with MarkerCluster
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
                    pane: 'markerPane'
                });
                marker.bindPopup('Restaurant: ' + point[0].toFixed(6) + ', ' + point[1].toFixed(6));
                markerClusterGroup.addLayer(marker);
            });
            
            map.addLayer(markerClusterGroup);
            
            // Layer control
            var baseMaps = {};
            var overlayMaps = {};
            var layerControl = null;
            
            function initLayerControl() {
                if (layerControl) {
                    map.removeControl(layerControl);
                }
                
                overlayMaps = {
                    "H3 Hexagons (Success Rate)": hexagonLayer,
                    "Supply Points (Restaurants)": markerClusterGroup
                };
                
                if (pincodeLayer) {
                    overlayMaps["Pincode Boundaries"] = pincodeLayer;
                }
                
                layerControl = L.control.layers(baseMaps, overlayMaps, {
                    collapsed: false,
                    position: 'topright'
                });
                
                layerControl.addTo(map);
            }
            
            initLayerControl();
            
            // Filter functionality
            document.getElementById('apply-filter').addEventListener('click', applyFilter);
            
            function applyFilter() {
                var btn = document.getElementById('apply-filter');
                var statusDiv = document.getElementById('status-message');
                
                var logisticsPlayer = document.getElementById('logistics-player-filter').value;
                var hourBin = document.getElementById('hour-bin-filter').value;
                var gpsInput = document.getElementById('gps-input').value.trim();
                
                // Handle GPS input
                if (gpsInput) {
                    var coords = gpsInput.split(',').map(c => parseFloat(c.trim()));
                    if (coords.length === 2 && !isNaN(coords[0]) && !isNaN(coords[1])) {
                        if (gpsMarker) {
                            map.removeLayer(gpsMarker);
                        }
                        gpsMarker = L.marker(coords, {
                            icon: L.icon({
                                iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
                                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41],
                                popupAnchor: [1, -34],
                                shadowSize: [41, 41]
                            })
                        }).addTo(map);
                        gpsMarker.bindPopup('Your Location: ' + coords[0].toFixed(6) + ', ' + coords[1].toFixed(6)).openPopup();
                        map.setView(coords, 14);
                    }
                }
                
                // Disable button and show loading
                btn.disabled = true;
                btn.innerHTML = '<span class="loading"></span>Filtering...';
                
                // Make API call
                fetch('/filter_hexagons', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        logistics_player: logisticsPlayer,
                        hour_bin: hourBin
                    })
                })
                .then(response => response.json())
                .then(data => {
                    renderHexagons(data.hexagons);
                    
                    // Show status
                    statusDiv.className = 'status-message success';
                    statusDiv.style.display = 'block';
                    statusDiv.innerHTML = '✅ Showing ' + data.hexagons.features.length + ' hexagons<br>' +
                                        'Orders: ' + data.stats.total_orders + ' | Success Rate: ' + data.stats.success_rate + '%';
                    
                    setTimeout(() => {
                        statusDiv.style.display = 'none';
                    }, 3000);
                    
                    // Update hexagon count
                    document.getElementById('hexagon-count').textContent = data.hexagons.features.length;
                    
                    // Reinitialize layer control
                    initLayerControl();
                    
                    // Re-enable button
                    btn.disabled = false;
                    btn.innerHTML = 'Apply Filters';
                })
                .catch(error => {
                    console.error('Error:', error);
                    statusDiv.className = 'status-message error';
                    statusDiv.style.display = 'block';
                    statusDiv.innerHTML = '❌ Error applying filters';
                    
                    setTimeout(() => {
                        statusDiv.style.display = 'none';
                    }, 3000);
                    
                    btn.disabled = false;
                    btn.innerHTML = 'Apply Filters';
                });
            }
            
            function renderHexagons(geojson) {
                if (hexagonLayer) {
                    map.removeLayer(hexagonLayer);
                }
                
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
                            { className: 'custom-tooltip' }
                        );
                    },
                    pane: 'overlayPane'
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
        supply_points=supply_points,
        logistics_players=logistics_players,
        hour_bins=hour_bins
    )

@app.route('/filter_hexagons', methods=['POST'])
def filter_hexagons():
    """API endpoint to filter hexagons by hour bin and logistics player"""
    try:
        data = request.get_json()
        logistics_player = data.get('logistics_player', 'All')
        hour_bin = data.get('hour_bin', 'All')
        
        # Start with full dataframe
        filtered_df = logistics_df.copy()
        
        # Apply logistics player filter
        if logistics_player != 'All':
            filtered_df = filtered_df[filtered_df['Logistics Player'] == logistics_player]
        
        # Apply hour bin filter
        if hour_bin != 'All':
            filtered_df = filtered_df[filtered_df['Hour_Bin'] == hour_bin]
        
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
    print("🚀 Starting Flask Server for Logistics Visualization")
    print("=" * 70)
    
    # Load data
    print("\n📊 Loading logistics data...")
    logistics_df = load_logistics_data('logistics_data.csv')
    
    if logistics_df is None:
        print("❌ Failed to load logistics data. Exiting.")
        exit(1)
    
    # Extract supply points
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
    print("🌐 Open: http://127.0.0.1:5000")
    print("=" * 70)
    print("\n🔥 Features:")
    print("   ✓ Hour bin filtering (00-01, 01-02, etc.)")
    print("   ✓ Logistics player filtering")
    print("   ✓ GPS location marker")
    print("   ✓ Real-time hexagon updates")
    print("   ✓ Layer control with hide/unhide")
    print("\n💡 Press Ctrl+C to stop")
    print("=" * 70 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)