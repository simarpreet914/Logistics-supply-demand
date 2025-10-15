import folium
import json
import webbrowser
import os

# Create map
m = folium.Map(location=[20.5937, 78.9629], zoom_start=5)

# Load and filter pincode boundaries
try:
    with open('pincode.geojson', 'r', encoding='utf-8') as f:
        pincode_geojson = json.load(f)
    
    # Filter by specific pincodes or regions (adjust as needed)
    # Example: Only major cities
    major_city_circles = ['delhi', 'mumbai', 'bangalore', 'chennai', 'kolkata', 'hyderabad']
    
    filtered_features = [
        f for f in pincode_geojson['features']
        if f['properties'].get('Circle', '').strip().lower() in major_city_circles
    ]
    
    pincode_geojson['features'] = filtered_features
    
    # Add pincode boundaries
    folium.GeoJson(
        pincode_geojson,
        name='Pincode Boundaries (Major Cities)',
        style_function=lambda x: {
            'fillColor': 'transparent',
            'color': '#3388ff',
            'weight': 1,
            'fillOpacity': 0,
            'opacity': 0.5
        },
        highlight_function=lambda x: {
            'weight': 2,
            'color': '#ff0000',
            'fillOpacity': 0.1
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['Pincode', 'Office_Name'],
            aliases=['Pincode:', 'Office:']
        )
    ).add_to(m)
    
    print(f"Loaded {len(filtered_features)} pincodes (filtered from {len(pincode_geojson['features'])} total)")
    
except Exception as e:
    print(f"Error: {e}")

folium.LayerControl(collapsed=False).add_to(m)

# Save map
m.save('logistics_heatmap_v9.html')
