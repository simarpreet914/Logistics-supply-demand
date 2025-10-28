import h3
from collections import defaultdict

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