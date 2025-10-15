import folium
import json

# ...existing code...

# Create map
m = folium.Map(location=[20.5937, 78.9629], zoom_start=5)

# ...your existing heatmap/hexagon code...

# Load and add pincode boundaries from GeoJSON
try:
    with open('pincode.geojson', 'r') as f:
        pincode_geojson = json.load(f)
    
    # Add pincode boundaries layer
    folium.GeoJson(
        pincode_geojson,
        name='Pincode Boundaries',
        style_function=lambda x: {
            'fillColor': 'transparent',
            'color': '#3388ff',
            'weight': 1.5,
            'fillOpacity': 0.05,
            'opacity': 0.6
        },
        highlight_function=lambda x: {
            'weight': 3,
            'color': '#ff0000',
            'fillOpacity': 0.15
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['Pincode', 'Office_Name', 'Division', 'Region', 'Circle'],
            aliases=['Pincode:', 'Office Name:', 'Division:', 'Region:', 'Circle:'],
            style="background-color: white; color: #333333; font-family: arial; font-size: 12px; padding: 10px;"
        )
    ).add_to(m)
    
    print(f"Successfully loaded {len(pincode_geojson['features'])} pincode boundaries")
    
except FileNotFoundError:
    print("GeoJSON file not found. Please check the file path.")
except Exception as e:
    print(f"Error loading pincode boundaries: {e}")

# Add layer control to toggle visibility
folium.LayerControl(collapsed=False).add_to(m)

# Save map
m.save('logistics_heatmap_v9.html')