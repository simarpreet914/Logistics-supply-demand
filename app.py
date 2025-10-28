from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import os
from dotenv import load_dotenv
from data_processing import load_logistics_data
from hexagon_utils import create_h3_hexagons

load_dotenv()

app = Flask(__name__)
CORS(app)

# --- Data Loading ---
print("=" * 70)
print("🚀 Initializing Logistics Visualization App")
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
    with open(os.getenv('GEOJSON_FILE'), 'r', encoding='utf-8') as f:
        pincode_geojson = json.load(f)
    print(f"   Loaded {len(pincode_geojson['features'])} pincode boundaries")
except FileNotFoundError:
    print(f"⚠️  Pincode GeoJSON '{os.getenv('GEOJSON_FILE')}' not found, skipping")
    pincode_geojson = None
except Exception as e:
    print(f"⚠️  Error loading pincode boundaries: {e}")
    pincode_geojson = None

print("\n" + "=" * 70)
print("✅ App initialized successfully!")
print("=" * 70 + "\n")


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
    
    return render_template(
        'index.html',
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
    print("🚀 Starting Flask Development Server")
    print(f"🌐 Open: http://127.0.0.1:{os.getenv('FLASK_RUN_PORT')}")
    print("💡 Press Ctrl+C to stop")
    print("=" * 70 + "\n")
    app.run(debug=os.getenv('FLASK_DEBUG') == 'True', host=os.getenv('FLASK_RUN_HOST'), port=int(os.getenv('FLASK_RUN_PORT')))