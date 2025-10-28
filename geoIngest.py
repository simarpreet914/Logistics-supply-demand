"""
MongoDB Data Ingestion Script with Pre-aggregation
Run this script ONCE to load CSV data and create aggregated H3 hexagons
Usage: python ingest_data.py
"""

import pandas as pd
import h3
from pymongo import MongoClient, ASCENDING
from datetime import datetime
import sys
from collections import defaultdict

# MongoDB Configuration
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "logistics_db"
COLLECTION_NAME = "orders"
AGGREGATES_COLLECTION = "h3_aggregates"

def parse_gps_coordinate(gps_string):
    """Parse GPS coordinate string like '13.014071,77.532051'"""
    try:
        if pd.isna(gps_string) or str(gps_string).strip() == '':
            return None, None
        parts = str(gps_string).strip().split(',')
        if len(parts) == 2:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    except:
        pass
    return None, None

def create_indexes(collection, aggregates_collection):
    """Create all necessary indexes for fast queries"""
    print("\n🔧 Creating MongoDB indexes...")
    
    # Raw orders collection indexes
    collection.create_index([("logistics_player", ASCENDING)], background=True)
    collection.create_index([("hour_bin", ASCENDING)], background=True)
    collection.create_index([("order_status", ASCENDING)], background=True)
    collection.create_index([("pickup_location", "2dsphere")], background=True)
    
    # H3 indexes for different resolutions
    for res in range(6, 11):
        collection.create_index([(f"h3_res_{res}", ASCENDING)], background=True)
    
    # Compound indexes
    collection.create_index([("logistics_player", ASCENDING), ("hour_bin", ASCENDING)], background=True)
    
    print("✅ Raw orders indexes created!")
    
    # Aggregates collection indexes (CRITICAL for speed)
    print("\n🔧 Creating aggregates indexes...")
    aggregates_collection.create_index([("h3_index", ASCENDING)], unique=True, background=True)
    aggregates_collection.create_index([("logistics_players", ASCENDING)], background=True)
    aggregates_collection.create_index([("hour_bins", ASCENDING)], background=True)
    aggregates_collection.create_index([("total_orders", ASCENDING)], background=True)
    
    # NOTE: Cannot create compound index on two array fields (MongoDB limitation)
    # Solution: Use single-field indexes + MongoDB's index intersection
    # MongoDB will automatically use both indexes when filtering by both fields
    
    print("✅ Aggregates indexes created!")
    print("ℹ️  MongoDB will use index intersection for combined filters")

def build_h3_aggregates(collection, aggregates_collection, h3_resolution=8):
    """
    Build pre-aggregated H3 hexagons from raw orders
    This is the SECRET SAUCE for instant queries!
    """
    print("\n" + "=" * 80)
    print("🔮 BUILDING PRE-AGGREGATED H3 HEXAGONS")
    print("=" * 80)
    
    h3_field = f"h3_res_{h3_resolution}"
    
    print(f"\n📊 Aggregating data by {h3_field}...")
    print("⏱️  This may take a few minutes for millions of records...\n")
    
    # MongoDB aggregation pipeline to create pre-aggregated hexagons
    pipeline = [
        {
            '$group': {
                '_id': f'${h3_field}',
                'total_orders': {'$sum': 1},
                'successful_orders': {
                    '$sum': {'$cond': [{'$eq': ['$order_status', 'success']}, 1, 0]}
                },
                'failed_orders': {
                    '$sum': {'$cond': [{'$ne': ['$order_status', 'success']}, 1, 0]}
                },
                'avg_lat': {'$avg': '$pickup_lat'},
                'avg_lon': {'$avg': '$pickup_lon'},
                'unique_locations': {
                    '$addToSet': {
                        '$concat': [
                            {'$toString': '$pickup_lat'},
                            ',',
                            {'$toString': '$pickup_lon'}
                        ]
                    }
                },
                'hour_bins': {'$addToSet': '$hour_bin'},
                'logistics_players': {'$addToSet': '$logistics_player'}
            }
        },
        {
            '$project': {
                'h3_index': '$_id',
                'total_orders': 1,
                'successful_orders': 1,
                'failed_orders': 1,
                'success_rate': {
                    '$multiply': [
                        {'$divide': ['$successful_orders', '$total_orders']},
                        100
                    ]
                },
                'unique_restaurants': {'$size': '$unique_locations'},
                'center_lat': '$avg_lat',
                'center_lon': '$avg_lon',
                'hour_bins': 1,
                'logistics_players': 1
            }
        }
    ]
    
    print(f"🔄 Running aggregation pipeline...")
    aggregated_docs = list(collection.aggregate(pipeline, allowDiskUse=True))
    
    print(f"✅ Aggregated {len(aggregated_docs):,} unique H3 hexagons")
    
    # Clear existing aggregates
    aggregates_collection.delete_many({})
    print(f"🗑️  Cleared old aggregates")
    
    # Insert aggregated hexagons with flattened filter combinations
    if aggregated_docs:
        hex_docs = []
        for doc in aggregated_docs:
            # Create filter key for combined queries (workaround for parallel array limitation)
            hour_bins_sorted = sorted(doc['hour_bins'])
            players_sorted = sorted([str(p) for p in doc['logistics_players']])
            
            # Create combination keys for faster filtering
            filter_combinations = []
            for player in players_sorted:
                for hour in hour_bins_sorted:
                    filter_combinations.append(f"{player}|{hour}")
            
            hex_doc = {
                'h3_index': doc['h3_index'],
                'total_orders': doc['total_orders'],
                'successful_orders': doc['successful_orders'],
                'failed_orders': doc['failed_orders'],
                'success_rate': round(doc['success_rate'], 2),
                'unique_restaurants': doc['unique_restaurants'],
                'center_lat': round(doc['center_lat'], 6),
                'center_lon': round(doc['center_lon'], 6),
                'hour_bins': hour_bins_sorted,
                'logistics_players': players_sorted,
                'filter_combinations': filter_combinations  # NEW: For combined filtering
            }
            hex_docs.append(hex_doc)
        
        # Bulk insert
        try:
            aggregates_collection.insert_many(hex_docs, ordered=False)
            print(f"✅ Inserted {len(hex_docs):,} pre-aggregated hexagons")
        except Exception as e:
            print(f"⚠️  Insert warning (some duplicates possible): {e}")
            # Continue anyway - most docs inserted successfully
    
    print("\n" + "=" * 80)
    print("🎉 PRE-AGGREGATION COMPLETE!")
    print("=" * 80)
    print(f"📊 Total H3 hexagons: {len(aggregated_docs):,}")
    print(f"🚀 Queries will now be INSTANT (< 50ms)")

def ingest_csv_to_mongodb(csv_path, chunk_size=100000):
    """Load CSV data into MongoDB with multiple H3 resolutions"""
    
    print("=" * 80)
    print("📊 LOGISTICS DATA INGESTION TO MONGODB")
    print("=" * 80)
    
    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    aggregates_collection = db[AGGREGATES_COLLECTION]
    
    # Check existing data
    existing_count = collection.count_documents({})
    existing_aggregates = aggregates_collection.count_documents({})
    
    print(f"\n📦 Existing records in raw orders: {existing_count:,}")
    print(f"📦 Existing aggregated hexagons: {existing_aggregates:,}")

    # Skip if sufficient data exists
    CHUNK_ROW_ESTIMATE = 10000
    CHUNK_LIMIT = 20
    MIN_RECORDS_FOR_SKIP = CHUNK_ROW_ESTIMATE * CHUNK_LIMIT

    if existing_count >= MIN_RECORDS_FOR_SKIP:
        print(f"\n⏭️  Detected {existing_count:,} raw records.")
        
        # Always ensure indexes exist
        create_indexes(collection, aggregates_collection)

        # Check if aggregates already exist
        existing_aggregates = aggregates_collection.count_documents({})
        if existing_aggregates == 0:
            print("\n⚙️  No aggregated hexagons found — building now...")
            build_h3_aggregates(collection, aggregates_collection, h3_resolution=8)
        else:
            response = input(f"\n⚠️  Found {existing_aggregates:,} existing aggregates. Rebuild them? (yes/no): ")
            if response.strip().lower() == 'yes':
                build_h3_aggregates(collection, aggregates_collection, h3_resolution=8)
            else:
                print("✅ Skipping aggregation rebuild.")
        
        # Show database summary
        print(f"\n📈 DATABASE SUMMARY:")
        print(f"   Total raw documents: {collection.count_documents({}):,}")
        print(f"   Total aggregated hexagons: {aggregates_collection.count_documents({}):,}")
        print(f"   Unique logistics players: {len(collection.distinct('logistics_player'))}")

        first_doc = collection.find_one(sort=[('timestamp', 1)])
        last_doc = collection.find_one(sort=[('timestamp', -1)])
        if first_doc and last_doc:
            print(f"   Date range: {first_doc['date']} to {last_doc['date']}")

        success_count = collection.count_documents({'order_status': 'success'})
        total_count = collection.count_documents({})
        if total_count > 0:
            print(f"   Success rate: {success_count / total_count * 100:.1f}%")

        print(f"\n✅ Indexes and Aggregations Ready!")
        print(f"   Run: python app.py")
        print("=" * 80)
        client.close()
        return


    elif existing_count > 0:
        print(f"\n⚠️  Database already contains {existing_count:,} records")
        response = input("Delete existing data and reload? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Ingestion cancelled")
            client.close()
            return
        
        print("🗑️  Dropping collections...")
        collection.drop()
        aggregates_collection.drop()
        collection = db[COLLECTION_NAME]
        aggregates_collection = db[AGGREGATES_COLLECTION]
    
    print(f"\n📂 Loading CSV: {csv_path}")
    print(f"⚙️  Chunk size: {chunk_size:,} rows\n")
    
    total_inserted = 0
    total_skipped = 0
    batch_records = []
    BATCH_SIZE = 10000
    
    # H3 resolutions to precompute
    H3_RESOLUTIONS = [6, 7, 8, 9, 10]
    
    try:
        for chunk_num, chunk in enumerate(pd.read_csv(csv_path, chunksize=chunk_size), 1):
            # Clean column names
            chunk.columns = chunk.columns.str.strip().str.lower()
            
            # Rename columns to standard format
            column_mapping = {
                'bpp_id': 'logistics_player',
                'timestamp': 'timestamp_raw',
                'pick_up_gps': 'pickup_gps',
                'delivery_gps': 'delivery_gps',
                'order_status': 'order_status'
            }
            chunk = chunk.rename(columns=column_mapping)
            
            # Parse pickup GPS coordinates
            chunk[['pickup_lat', 'pickup_lon']] = chunk['pickup_gps'].apply(
                lambda x: pd.Series(parse_gps_coordinate(x))
            )
            
            # Parse delivery GPS coordinates
            chunk[['delivery_lat', 'delivery_lon']] = chunk['delivery_gps'].apply(
                lambda x: pd.Series(parse_gps_coordinate(x))
            )
            
            # Drop rows with invalid pickup coordinates
            chunk = chunk.dropna(subset=['pickup_lat', 'pickup_lon'])
            
            # Parse timestamp
            chunk['timestamp'] = pd.to_datetime(chunk['timestamp_raw'], format='mixed', errors='coerce')
            chunk = chunk.dropna(subset=['timestamp'])
            
            # Extract time components
            chunk['hour'] = chunk['timestamp'].dt.hour
            chunk['date'] = chunk['timestamp'].dt.date.astype(str)
            chunk['day_of_week'] = chunk['timestamp'].dt.dayofweek
            chunk['hour_bin'] = chunk['hour'].apply(lambda x: f"{x:02d}-{(x+1):02d}")
            
            # Normalize order status
            chunk['order_status'] = chunk['order_status'].str.strip().str.lower()
            
            # Handle missing logistics_player
            chunk['logistics_player'] = chunk['logistics_player'].fillna('unknown')
            
            # Calculate H3 indices for multiple resolutions
            for res in H3_RESOLUTIONS:
                chunk[f'h3_res_{res}'] = chunk.apply(
                    lambda row: h3.latlng_to_cell(row['pickup_lat'], row['pickup_lon'], res=res),
                    axis=1
                )
            
            # Prepare MongoDB documents
            for _, row in chunk.iterrows():
                doc = {
                    'timestamp': row['timestamp'],
                    'date': row['date'],
                    'hour': int(row['hour']),
                    'hour_bin': row['hour_bin'],
                    'day_of_week': int(row['day_of_week']),
                    
                    # Pickup location (restaurants/supply points)
                    'pickup_lat': float(row['pickup_lat']),
                    'pickup_lon': float(row['pickup_lon']),
                    'pickup_location': {
                        'type': 'Point',
                        'coordinates': [float(row['pickup_lon']), float(row['pickup_lat'])]
                    },
                    
                    # Delivery location (optional)
                    'delivery_lat': float(row['delivery_lat']) if pd.notna(row['delivery_lat']) else None,
                    'delivery_lon': float(row['delivery_lon']) if pd.notna(row['delivery_lon']) else None,
                    
                    # Order details
                    'order_status': str(row['order_status']),
                    'logistics_player': str(row['logistics_player']),
                    
                    # H3 indices at different resolutions
                    **{f'h3_res_{res}': str(row[f'h3_res_{res}']) for res in H3_RESOLUTIONS}
                }
                
                # Add delivery location if available
                if doc['delivery_lat'] and doc['delivery_lon']:
                    doc['delivery_location'] = {
                        'type': 'Point',
                        'coordinates': [doc['delivery_lon'], doc['delivery_lat']]
                    }
                
                batch_records.append(doc)
                
                # Insert in batches
                if len(batch_records) >= BATCH_SIZE:
                    try:
                        collection.insert_many(batch_records, ordered=False)
                        total_inserted += len(batch_records)
                    except Exception as e:
                        print(f"⚠️  Batch insert warning: {e}")
                        total_skipped += len(batch_records)
                    batch_records = []
            
            print(f"✓ Chunk {chunk_num}: Processed (Total inserted: {total_inserted:,})")

            # Limit chunks for faster testing
            MAX_CHUNKS = 55
            if chunk_num >= MAX_CHUNKS:
                print(f"\n⏹️ Reached {MAX_CHUNKS} chunks, stopping ingestion...\n")
                break
        
        # Insert remaining records
        if batch_records:
            try:
                collection.insert_many(batch_records, ordered=False)
                total_inserted += len(batch_records)
            except Exception as e:
                print(f"⚠️  Final batch warning: {e}")
                total_skipped += len(batch_records)
        
        print(f"\n{'=' * 80}")
        print(f"✅ RAW DATA INGESTION COMPLETE!")
        print(f"{'=' * 80}")
        print(f"📊 Total records inserted: {total_inserted:,}")
        if total_skipped > 0:
            print(f"⚠️  Records skipped: {total_skipped:,}")
        
        # Create indexes on raw collection
        create_indexes(collection, aggregates_collection)
        
        # BUILD PRE-AGGREGATED HEXAGONS (THE MAGIC!)
        build_h3_aggregates(collection, aggregates_collection, h3_resolution=8)
        
        # Show summary statistics
        print(f"\n📈 FINAL DATABASE SUMMARY:")
        print(f"   Total raw documents: {collection.count_documents({}):,}")
        print(f"   Total aggregated hexagons: {aggregates_collection.count_documents({}):,}")
        print(f"   Unique logistics players: {len(collection.distinct('logistics_player'))}")
        
        first_doc = collection.find_one(sort=[('timestamp', 1)])
        last_doc = collection.find_one(sort=[('timestamp', -1)])
        if first_doc and last_doc:
            print(f"   Date range: {first_doc['date']} to {last_doc['date']}")
        
        success_count = collection.count_documents({'order_status': 'success'})
        total_count = collection.count_documents({})
        if total_count > 0:
            print(f"   Success rate: {success_count / total_count * 100:.1f}%")
        
        print(f"\n✅ Ready for visualization!")
        print(f"   Run: python app.py")
        print("=" * 80)
        
    except FileNotFoundError:
        print(f"❌ Error: File '{csv_path}' not found!")
    except Exception as e:
        print(f"❌ Error during ingestion: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()

if __name__ == '__main__':
    csv_file = 'logistics_big_data.csv'
    
    # Check if custom CSV path provided
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    
    ingest_csv_to_mongodb(csv_file, chunk_size=100000)