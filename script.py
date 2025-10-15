from flask import Flask, render_template_string, jsonify, request
import h3
import requests
from shapely.geometry import Point, Polygon
import time
import pandas as pd
from collections import defaultdict
from datetime import datetime

app = Flask(__name__)

# Global data storage
logistics_data = {
    'df': None,
    'loaded': False,
    'logistics_players': [],
    'time_bins': []
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>H3 Hexagon Pincode Mapper with Logistics Data</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
        #map { height: 100vh; width: 100%; }
        
        .info-box {
            position: fixed;
            top: 10px;
            left: 50%;
            transform: translateX(-50%);
            background-color: white;
            border: 2px solid #3498db;
            border-radius: 8px;
            padding: 15px;
            z-index: 9999;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            max-width: 500px;
        }
        
        .info-box h3 {
            margin: 0 0 10px 0;
            color: #3498db;
        }
        
        .info-box p {
            margin: 5px 0;
            font-size: 14px;
        }
        
        .control-panel {
            position: fixed;
            top: 20px;
            right: 20px;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            z-index: 1000;
            max-width: 320px;
            max-height: 85vh;
            overflow-y: auto;
        }
        
        .control-panel h4 {
            margin: 0 0 15px 0;
            color: #2c3e50;
            font-size: 16px;
            border-bottom: 2px solid #3498db;
            padding-bottom: 8px;
        }
        
        .filter-section {
            margin-bottom: 18px;
            padding-bottom: 15px;
            border-bottom: 1px solid #eee;
        }
        
        .filter-section:last-child {
            border-bottom: none;
        }
        
        .filter-section label {
            display: block;
            margin-bottom: 6px;
            font-weight: bold;
            font-size: 13px;
            color: #555;
        }
        
        .filter-section select, .filter-section input[type="range"] {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
        }
        
        .filter-section button {
            width: 100%;
            padding: 10px;
            background: #3498db;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            margin-top: 8px;
        }
        
        .filter-section button:hover {
            background: #2980b9;
        }
        
        .filter-section button:disabled {
            background: #95a5a6;
            cursor: not-allowed;
        }
        
        .stats-box {
            background: #f8f9fa;
            padding: 12px;
            border-radius: 4px;
            font-size: 12px;
            margin-top: 10px;
        }
        
        .stats-box div {
            margin: 6px 0;
            display: flex;
            justify-content: space-between;
        }
        
        .stats-box strong {
            color: #2c3e50;
        }
        
        .legend {
            position: fixed;
            bottom: 20px;
            left: 20px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            z-index: 1000;
            max-width: 250px;
        }
        
        .legend h4 {
            margin: 0 0 10px 0;
            font-size: 14px;
            color: #2c3e50;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            margin: 6px 0;
            font-size: 12px;
        }
        
        .legend-color {
            width: 30px;
            height: 18px;
            margin-right: 10px;
            border: 1px solid #333;
            border-radius: 2px;
        }
        
        .loading {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: white;
            padding: 30px 40px;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            z-index: 10000;
            text-align: center;
            min-width: 250px;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #3498db;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .toggle-section {
            margin: 10px 0;
        }
        
        .toggle-section label {
            display: flex;
            align-items: center;
            font-weight: normal;
            font-size: 13px;
            cursor: pointer;
        }
        
        .toggle-section input[type="checkbox"] {
            margin-right: 8px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="info-box">
        <h3>🗺️ Logistics Supply-Demand Pincode Mapper</h3>
        <p><strong>Click anywhere</strong> on the map to load pincode area with logistics data</p>
        <p style="font-size: 12px; color: #666;">Hexagons show success rate • Green = High success • Red = Low success</p>
    </div>
    
    <div id="map"></div>
    
    <div class="control-panel">
        <h4>📊 Control Panel</h4>
        
        <div class="filter-section">
            <label>H3 Resolution (Hexagon Size)</label>
            <input type="range" id="resolution" min="7" max="10" value="8" />
            <small style="color: #666; display: block; margin-top: 5px;">
                Current: <span id="res-value">8</span> (7=Large, 10=Small)
            </small>
        </div>
        
        <div class="filter-section">
            <label>📦 Logistics Player</label>
            <select id="logistics-player">
                <option value="all">All Players</option>
            </select>
        </div>
        
        <div class="filter-section">
            <label>🕐 Time Period</label>
            <select id="time-bin">
                <option value="all">All Time</option>
            </select>
        </div>
        
        <div class="filter-section">
            <div class="toggle-section">
                <label>
                    <input type="checkbox" id="show-boundary" checked>
                    Show Pincode Boundary
                </label>
            </div>
            <div class="toggle-section">
                <label>
                    <input type="checkbox" id="show-supply" checked>
                    Show Supply Points (Restaurants)
                </label>
            </div>
        </div>
        
        <div class="filter-section">
            <button onclick="loadPincodeData()" id="load-btn">
                🔄 Reload with Filters
            </button>
            <button onclick="clearAll()" style="background: #e74c3c;">
                🗑️ Clear All
            </button>
        </div>
        
        <div class="stats-box">
            <div><strong>Current Pincode:</strong> <span id="current-pincode">-</span></div>
            <div><strong>Total Orders:</strong> <span id="total-orders">0</span></div>
            <div><strong>Success Rate:</strong> <span id="success-rate">0%</span></div>
            <div><strong>Hexagons:</strong> <span id="hex-count">0</span></div>
            <div><strong>Supply Points:</strong> <span id="supply-count">0</span></div>
        </div>
    </div>
    
    <div class="legend">
        <h4>Success Rate Legend</h4>
        <div class="legend-item">
            <div class="legend-color" style="background: #d73027;"></div>
            <span>0-20% (Critical)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #fc8d59;"></div>
            <span>20-40% (Poor)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #fee090;"></div>
            <span>40-60% (Fair)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #91cf60;"></div>
            <span>60-80% (Good)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #1a9850;"></div>
            <span>80-100% (Excellent)</span>
        </div>
        <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #ddd;">
            <div class="legend-item">
                <div class="legend-color" style="background: #2ecc71; border-color: #27ae60;"></div>
                <span>Supply Point</span>
            </div>
        </div>
    </div>
    
    <div id="loading" class="loading" style="display: none;">
        <div class="spinner"></div>
        <div id="loading-text">Processing...</div>
    </div>

    <script>
        // Initialize map
        const map = L.map('map').setView([28.7041, 77.1025], 12);
        
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(map);

        let hexagonLayers = [];
        let boundaryLayer = null;
        let supplyMarkers = [];
        let clickedLatLng = null;
        let currentPincode = null;
        let isProcessing = false;

        // Update resolution display
        document.getElementById('resolution').addEventListener('input', function(e) {
            document.getElementById('res-value').textContent = e.target.value;
        });

        // Load filters on page load
        async function loadFilters() {
            try {
                const response = await fetch('/get_filters');
                const data = await response.json();
                
                const playerSelect = document.getElementById('logistics-player');
                data.logistics_players.forEach(player => {
                    const option = document.createElement('option');
                    option.value = player;
                    option.textContent = player.split('/').pop(); // Show last part
                    playerSelect.appendChild(option);
                });
                
                const timeSelect = document.getElementById('time-bin');
                data.time_bins.forEach(bin => {
                    const option = document.createElement('option');
                    option.value = bin;
                    option.textContent = bin;
                    timeSelect.appendChild(option);
                });
            } catch (error) {
                console.error('Error loading filters:', error);
            }
        }

        // Handle map clicks
        map.on('click', async function(e) {
            if (isProcessing) {
                alert('Please wait for the current operation to complete');
                return;
            }

            clickedLatLng = e.latlng;
            await loadPincodeData();
        });

        async function loadPincodeData() {
            if (!clickedLatLng) {
                alert('Please click on the map first');
                return;
            }

            if (isProcessing) return;
            
            isProcessing = true;
            showLoading('Fetching pincode information...');
            
            const resolution = parseInt(document.getElementById('resolution').value);
            const player = document.getElementById('logistics-player').value;
            const timeBin = document.getElementById('time-bin').value;
            
            try {
                const response = await fetch('/get_pincode_logistics', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        lat: clickedLatLng.lat,
                        lng: clickedLatLng.lng,
                        resolution: resolution,
                        logistics_player: player,
                        time_bin: timeBin
                    })
                });
                
                const data = await response.json();
                
                if (data.error) {
                    alert('Error: ' + data.error);
                    hideLoading();
                    isProcessing = false;
                    return;
                }

                updateLoadingText(`Creating ${data.hexagons.length} hexagons for pincode ${data.pincode}...`);
                
                clearAll();
                currentPincode = data.pincode;
                
                // Draw boundary
                if (data.boundary && data.boundary.length > 0 && document.getElementById('show-boundary').checked) {
                    boundaryLayer = L.polygon(data.boundary, {
                        color: '#e74c3c',
                        fillColor: 'transparent',
                        weight: 3,
                        dashArray: '10, 10'
                    }).addTo(map);
                    
                    boundaryLayer.bindPopup(`<strong>Pincode Boundary:</strong> ${data.pincode}`);
                }
                
                // Draw hexagons with color based on success rate
                data.hexagons.forEach(hex => {
                    const color = getSuccessRateColor(hex.success_rate);
                    const polygon = L.polygon(hex.boundary, {
                        color: color,
                        fillColor: color,
                        fillOpacity: 0.5,
                        weight: 2
                    }).addTo(map);
                    
                    polygon.bindPopup(`
                        <strong>Hexagon Details</strong><br>
                        <strong>H3 Index:</strong> ${hex.h3_index}<br>
                        <strong>Center:</strong> ${hex.center_lat.toFixed(6)}, ${hex.center_lng.toFixed(6)}<br>
                        <strong>Total Orders:</strong> ${hex.total_orders}<br>
                        <strong>Success Orders:</strong> ${hex.success_orders}<br>
                        <strong>Failed Orders:</strong> ${hex.fail_orders}<br>
                        <strong>Success Rate:</strong> ${hex.success_rate.toFixed(1)}%<br>
                        <strong>Supply Points:</strong> ${hex.supply_count}
                    `);
                    
                    hexagonLayers.push(polygon);
                });
                
                // Draw supply points
                if (document.getElementById('show-supply').checked && data.supply_points) {
                    data.supply_points.forEach(point => {
                        const marker = L.circleMarker([point.lat, point.lng], {
                            radius: 5,
                            fillColor: '#2ecc71',
                            color: '#27ae60',
                            weight: 2,
                            fillOpacity: 0.8
                        }).addTo(map);
                        
                        marker.bindPopup(`
                            <strong>Supply Point (Restaurant)</strong><br>
                            <strong>Location:</strong> ${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}<br>
                            <strong>Total Orders:</strong> ${point.count}
                        `);
                        
                        supplyMarkers.push(marker);
                    });
                }
                
                // Update stats
                document.getElementById('current-pincode').textContent = data.pincode;
                document.getElementById('total-orders').textContent = data.stats.total_orders;
                document.getElementById('success-rate').textContent = data.stats.success_rate.toFixed(1) + '%';
                document.getElementById('hex-count').textContent = data.hexagons.length;
                document.getElementById('supply-count').textContent = data.stats.supply_points;
                
                // Fit map to bounds
                if (data.boundary && data.boundary.length > 0) {
                    const bounds = L.latLngBounds(data.boundary);
                    map.fitBounds(bounds, { padding: [50, 50] });
                }
                
                hideLoading();
                
            } catch (error) {
                console.error('Error:', error);
                alert('Error loading data. Please check console.');
                hideLoading();
            } finally {
                isProcessing = false;
            }
        }

        function getSuccessRateColor(rate) {
            if (rate >= 80) return '#1a9850';
            if (rate >= 60) return '#91cf60';
            if (rate >= 40) return '#fee090';
            if (rate >= 20) return '#fc8d59';
            return '#d73027';
        }

        function clearAll() {
            hexagonLayers.forEach(layer => map.removeLayer(layer));
            supplyMarkers.forEach(marker => map.removeLayer(marker));
            hexagonLayers = [];
            supplyMarkers = [];
            
            if (boundaryLayer) {
                map.removeLayer(boundaryLayer);
                boundaryLayer = null;
            }
            
            document.getElementById('current-pincode').textContent = '-';
            document.getElementById('total-orders').textContent = '0';
            document.getElementById('success-rate').textContent = '0%';
            document.getElementById('hex-count').textContent = '0';
            document.getElementById('supply-count').textContent = '0';
        }

        function showLoading(text) {
            document.getElementById('loading').style.display = 'block';
            document.getElementById('loading-text').textContent = text;
        }

        function updateLoadingText(text) {
            document.getElementById('loading-text').textContent = text;
        }

        function hideLoading() {
            document.getElementById('loading').style.display = 'none';
        }

        // Load filters on page load
        loadFilters();
    </script>
</body>
</html>
"""

def load_csv_data(csv_path):
    """Load logistics CSV data"""
    try:
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        
        # Parse timestamp with mixed format support
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], format='mixed', errors='coerce')
        
        # Drop rows with invalid timestamps
        invalid_count = df['Timestamp'].isna().sum()
        if invalid_count > 0:
            print(f"⚠️  Warning: {invalid_count} rows with invalid timestamps will be skipped")
            df = df.dropna(subset=['Timestamp'])
        
        # Extract hour and date
        df['Hour'] = df['Timestamp'].dt.hour
        df['Date'] = df['Timestamp'].dt.date
        
        # Create time bins
        df['Time_Bin'] = pd.cut(df['Hour'], 
                               bins=[0, 6, 12, 18, 24],
                               labels=['Night (12AM-6AM)', 'Morning (6AM-12PM)', 
                                      'Afternoon (12PM-6PM)', 'Evening (6PM-12AM)'])
        
        # Clean and validate coordinates
        df['Restaurant Latitude'] = pd.to_numeric(df['Restaurant Latitude'], errors='coerce')
        df['Restaurant Longitude'] = pd.to_numeric(df['Restaurant Longitude'], errors='coerce')
        
        # Drop rows with invalid coordinates
        invalid_coords = df[['Restaurant Latitude', 'Restaurant Longitude']].isna().any(axis=1).sum()
        if invalid_coords > 0:
            print(f"⚠️  Warning: {invalid_coords} rows with invalid coordinates will be skipped")
            df = df.dropna(subset=['Restaurant Latitude', 'Restaurant Longitude'])
        
        # Validate we have data left
        if len(df) == 0:
            print("❌ No valid data after cleaning")
            return False
        
        logistics_data['df'] = df
        logistics_data['logistics_players'] = df['Logistics Player'].unique().tolist()
        logistics_data['time_bins'] = [str(tb) for tb in df['Time_Bin'].unique() if pd.notna(tb)]
        logistics_data['loaded'] = True
        
        print(f"✅ Loaded {len(df)} valid logistics records")
        print(f"   Players: {len(logistics_data['logistics_players'])}")
        print(f"   Time Bins: {len(logistics_data['time_bins'])}")
        print(f"   Date Range: {df['Date'].min()} to {df['Date'].max()}")
        return True
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_location_info(lat, lng):
    """Get pincode using Nominatim"""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {'lat': lat, 'lon': lng, 'format': 'json', 'addressdetails': 1}
        headers = {'User-Agent': 'Logistics-Mapper/1.0'}
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        address = data.get('address', {})
        pincode = address.get('postcode', None)
        
        return {'pincode': pincode, 'address': data.get('display_name', '')}
    except Exception as e:
        print(f"Error fetching location: {e}")
        return None

def get_pincode_boundary(lat, lng, pincode):
    """Get pincode boundary using Overpass API"""
    try:
        overpass_url = "https://overpass-api.de/api/interpreter"
        query = f"""
        [out:json][timeout:25];
        (
          relation["postal_code"="{pincode}"]["boundary"="postal_code"];
          way["postal_code"="{pincode}"]["boundary"="postal_code"];
        );
        out geom;
        """
        
        response = requests.post(overpass_url, data={'data': query}, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            elements = data.get('elements', [])
            
            if elements:
                for element in elements:
                    if element.get('type') == 'way' and 'geometry' in element:
                        coords = [[node['lat'], node['lon']] for node in element['geometry']]
                        return coords
                    elif element.get('type') == 'relation' and 'members' in element:
                        for member in element['members']:
                            if member.get('role') == 'outer' and 'geometry' in member:
                                coords = [[node['lat'], node['lon']] for node in member['geometry']]
                                return coords
        
        return create_approximate_boundary(lat, lng, radius_km=2)
    except Exception as e:
        print(f"Error fetching boundary: {e}")
        return create_approximate_boundary(lat, lng, radius_km=2)

def create_approximate_boundary(lat, lng, radius_km=2):
    """Create circular boundary"""
    from math import cos, sin, radians, degrees
    points = []
    earth_radius = 6371
    
    for i in range(32):
        angle = radians(i * 360 / 32)
        dlat = (radius_km / earth_radius) * cos(angle)
        dlng = (radius_km / (earth_radius * cos(radians(lat)))) * sin(angle)
        points.append([lat + degrees(dlat), lng + degrees(dlng)])
    
    return points

def fill_polygon_with_hexagons(boundary_coords, resolution, df_filtered):
    """Fill polygon with hexagons and aggregate logistics data"""
    if not boundary_coords or len(boundary_coords) < 3:
        return []
    
    try:
        polygon_coords = [(coord[1], coord[0]) for coord in boundary_coords]
        polygon = Polygon(polygon_coords)
        
        minx, miny, maxx, maxy = polygon.bounds
        center_lng = (minx + maxx) / 2
        center_lat = (miny + maxy) / 2
        
        center_h3 = h3.latlng_to_cell(center_lat, center_lng, resolution)
        area_deg = (maxx - minx) * (maxy - miny)
        k = min(int(area_deg * 1000 / (resolution + 1)), 50)
        
        hexagons = h3.grid_disk(center_h3, k)
        
        # Aggregate data per hexagon
        hexagon_data = defaultdict(lambda: {
            'total_orders': 0,
            'success_orders': 0,
            'fail_orders': 0,
            'supply_count': 0,
            'restaurant_locs': set()
        })
        
        # Process each order
        for _, row in df_filtered.iterrows():
            try:
                lat = float(row['Restaurant Latitude'])
                lng = float(row['Restaurant Longitude'])
                
                # Validate coordinates are reasonable
                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                    continue
                
                if pd.notna(lat) and pd.notna(lng):
                    hex_id = h3.latlng_to_cell(lat, lng, resolution)
                    
                    if hex_id in hexagons:
                        hex_boundary = h3.cell_to_boundary(hex_id)
                        hex_coords = [(coord[1], coord[0]) for coord in hex_boundary]
                        hex_polygon = Polygon(hex_coords)
                        
                        if polygon.intersects(hex_polygon):
                            hexagon_data[hex_id]['total_orders'] += 1
                            hexagon_data[hex_id]['restaurant_locs'].add((lat, lng))
                            
                            order_status = str(row['Order Status']).strip().lower()
                            if order_status == 'success':
                                hexagon_data[hex_id]['success_orders'] += 1
                            else:
                                hexagon_data[hex_id]['fail_orders'] += 1
            except (ValueError, TypeError) as e:
                # Skip rows with invalid data
                continue
        
        # Create hexagon response
        valid_hexagons = []
        for hex_id, data in hexagon_data.items():
            if data['total_orders'] > 0:
                hex_boundary = h3.cell_to_boundary(hex_id)
                boundary_leaflet = [[coord[0], coord[1]] for coord in hex_boundary]
                center = h3.cell_to_latlng(hex_id)
                
                success_rate = (data['success_orders'] / data['total_orders'] * 100)
                
                valid_hexagons.append({
                    'h3_index': hex_id,
                    'boundary': boundary_leaflet,
                    'center_lat': center[0],
                    'center_lng': center[1],
                    'total_orders': data['total_orders'],
                    'success_orders': data['success_orders'],
                    'fail_orders': data['fail_orders'],
                    'success_rate': success_rate,
                    'supply_count': len(data['restaurant_locs'])
                })
        
        return valid_hexagons
    except Exception as e:
        print(f"Error filling polygon: {e}")
        import traceback
        traceback.print_exc()
        return []

@app.route('/')
def index():
    if not logistics_data['loaded']:
        return "CSV data not loaded. Please check server logs."
    return render_template_string(HTML_TEMPLATE)

@app.route('/get_filters')
def get_filters():
    return jsonify({
        'logistics_players': logistics_data.get('logistics_players', []),
        'time_bins': logistics_data.get('time_bins', [])
    })

@app.route('/get_pincode_logistics', methods=['POST'])
def get_pincode_logistics():
    try:
        data = request.json
        lat = data['lat']
        lng = data['lng']
        resolution = data['resolution']
        player = data['logistics_player']
        time_bin = data['time_bin']
        
        # Get pincode
        location_info = get_location_info(lat, lng)
        if not location_info or not location_info['pincode']:
            return jsonify({'error': 'Could not find pincode for this location'}), 400
        
        pincode = location_info['pincode']
        
        # Get boundary
        time.sleep(1)
        boundary = get_pincode_boundary(lat, lng, pincode)
        
        # Filter data
        df = logistics_data['df'].copy()
        if player != 'all':
            df = df[df['Logistics Player'] == player]
        if time_bin != 'all':
            df = df[df['Time_Bin'].astype(str) == time_bin]
        
        # Fill hexagons with data
        hexagons = fill_polygon_with_hexagons(boundary, resolution, df)
        
        # Get supply points
        supply_points = []
        try:
            supply_grouped = df.groupby(['Restaurant Latitude', 'Restaurant Longitude']).size().reset_index(name='count')
            for _, row in supply_grouped.head(100).iterrows():
                lat = float(row['Restaurant Latitude'])
                lng = float(row['Restaurant Longitude'])
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    supply_points.append({
                        'lat': lat,
                        'lng': lng,
                        'count': int(row['count'])
                    })
        except Exception as e:
            print(f"Warning: Error processing supply points: {e}")
        
        # Calculate stats
        total_orders = len(df)
        success_orders = len(df[df['Order Status'].str.strip().str.lower() == 'success'])
        success_rate = (success_orders / total_orders * 100) if total_orders > 0 else 0
        
        return jsonify({
            'pincode': pincode,
            'boundary': boundary,
            'hexagons': hexagons,
            'supply_points': supply_points,
            'stats': {
                'total_orders': total_orders,
                'success_rate': success_rate,
                'supply_points': len(supply_points)
            }
        })
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("=" * 70)
    print("🚚 Logistics Pincode Mapper with H3 Hexagons")
    print("=" * 70)
    
    csv_path = 'logistics_data.csv'  # Change to your CSV path
    print(f"\n📂 Loading CSV: {csv_path}")
    
    if load_csv_data(csv_path):
        print("\n✅ Data loaded successfully!")
        print("\n📍 Open browser: http://127.0.0.1:5000")
        print("\n✨ Features:")
        print("   1. Click anywhere to load pincode boundary")
        print("   2. H3 hexagons filled with logistics data")
        print("   3. Color-coded by success rate (Red=Low, Green=High)")
        print("   4. Filter by logistics player and time")
        print("   5. View supply points (restaurants)")
        print("   6. Hexagon properties: lat, lng, orders, success rate")
        print("\n📊 CSV Format Expected:")
        print("   - Restaurant Latitude, Restaurant Longitude")
        print("   - Order Status (Success/Fail)")
        print("   - Logistics Player")
        print("   - Timestamp")
        print("\n⚠️  Press Ctrl+C to stop")
        print("=" * 70 + "\n")
        app.run(debug=True, port=5000)
    else:
        print("\n❌ Failed to load CSV!")
        print("\n📋 Required CSV columns:")
        print("   - Restaurant Latitude")
        print("   - Restaurant Longitude")
        print("   - Order Status")
        print("   - Logistics Player")
        print("   - Timestamp")
        print("\n💡 Make sure your CSV file exists and has the correct format")
        print("=" * 70 + "\n")