import json
from shapely.geometry import shape, mapping
from shapely.ops import transform
import pyproj

# Load GeoJSON
with open('pincode.geojson', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Simplify geometries
simplified_features = []
for feature in data['features']:
    geom = shape(feature['geometry'])
    # Simplify with tolerance (higher = more simplified)
    simplified = geom.simplify(0.001, preserve_topology=True)
    feature['geometry'] = mapping(simplified)
    simplified_features.append(feature)

data['features'] = simplified_features

# Save simplified version
with open('pincode_simplified.geojson', 'w', encoding='utf-8') as f:
    json.dump(data, f)

print("Simplified GeoJSON created!")