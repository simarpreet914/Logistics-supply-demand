import folium
import json
import webbrowser
import os

# Create map
m = folium.Map(location=[20.5937, 78.9629], zoom_start=5)

# Load simplified pincode boundaries
try:
    with open('pincode_simplified.geojson', 'r', encoding='utf-8') as f:
        pincode_geojson = json.load(f)
    
    # Add pincode boundaries layer (hidden by default)
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
        show=False  # Start hidden
    ).add_to(m)
    
    print(f"Successfully loaded {len(pincode_geojson['features'])} simplified pincode boundaries")
    
except FileNotFoundError:
    print("Simplified GeoJSON file not found. Run simplify_geojson.py first.")
except Exception as e:
    print(f"Error loading pincode boundaries: {e}")

# Add layer control
folium.LayerControl(collapsed=False).add_to(m)

# Save map
output_file = 'logistics_heatmap_v9.html'
m.save(output_file)
