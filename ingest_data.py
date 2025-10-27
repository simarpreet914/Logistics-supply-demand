"""
MongoDB Data Ingestion Script for Logistics Data
Run this script ONCE to load CSV data into MongoDB
Usage: python ingest_data.py
"""

import pandas as pd
import h3
from pymongo import MongoClient, ASCENDING
from datetime import datetime
import sys

# MongoDB Configuration
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "logistics_db"
COLLECTION_NAME = "orders"

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

def create_indexes(collection):
    """Create all necessary indexes for fast queries"""
    print("\n🔧 Creating MongoDB indexes...")
    
    # Single field indexes
    collection.create_index([("logistics_player", ASCENDING)], background=True)
    collection.create_index([("hour_bin", ASCENDING)], background=True)
    collection.create_index([("hour", ASCENDING)], background=True)
    collection.create_index([("date", ASCENDING)], background=True)
    collection.create_index([("order_status", ASCENDING)], background=True)
    
    # H3 indexes for different resolutions
    for res in range(6, 11):  # Support resolution 6-10
        collection.create_index([(f"h3_res_{res}", ASCENDING)], background=True)
    
    # Compound indexes for common queries
    collection.create_index([("logistics_player", ASCENDING), ("hour_bin", ASCENDING)], background=True)
    collection.create_index([("h3_res_8", ASCENDING), ("logistics_player", ASCENDING)], background=True)
    
    # Geospatial index
    collection.create_index([("pickup_location", "2dsphere")], background=True)
    
    print("✅ All indexes created!")

def ingest_csv_to_mongodb(csv_path, chunk_size=100000):
    """Load CSV data into MongoDB with multiple H3 resolutions"""
    
    print("=" * 80)
    print("📊 LOGISTICS DATA INGESTION TO MONGODB")
    print("=" * 80)
    
    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    
    # Check existing data
    existing_count = collection.count_documents({})
    print(f"\n📦 Existing records in DB: {existing_count:,}")

    # Define how many records roughly make 50 chunks
    CHUNK_ROW_ESTIMATE = 10000  # how many rows per chunk inserted
    CHUNK_LIMIT = 50
    MIN_RECORDS_FOR_SKIP = CHUNK_ROW_ESTIMATE * CHUNK_LIMIT  # 500,000 rows

    if existing_count >= MIN_RECORDS_FOR_SKIP:
        print(f"⏭️  Detected {existing_count:,} records (~{CHUNK_LIMIT} chunks). Skipping ingestion...")
        create_indexes(collection)

        print(f"\n📈 DATABASE SUMMARY:")
        print(f"   Total documents: {collection.count_documents({}):,}")
        print(f"   Unique logistics players: {len(collection.distinct('logistics_player'))}")
        print(f"   Date range: {collection.find_one(sort=[('timestamp', 1)])['date']} "
            f"to {collection.find_one(sort=[('timestamp', -1)])['date']}")
        print(f"   Success rate: {collection.count_documents({'order_status': 'success'}) / collection.count_documents({}) * 100:.1f}%")

        print(f"\n✅ Ready for visualization!")
        print(f"   Run: python app.py")
        print("=" * 80)
        return

    elif existing_count > 0:
        print(f"\n⚠️  Database already contains {existing_count:,} records")
        response = input("Delete existing data and reload? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Ingestion cancelled")
            return
        print("🗑️  Dropping collection...")
        collection.drop()
        collection = db[COLLECTION_NAME]

        
        print("🗑️  Dropping collection...")
        collection.drop()
        collection = db[COLLECTION_NAME]
    
    print(f"\n📂 Loading CSV: {csv_path}")
    print(f"⚙️  Chunk size: {chunk_size:,} rows\n")
    
    total_inserted = 0
    total_skipped = 0
    batch_records = []
    BATCH_SIZE = 10000
    
    # H3 resolutions to precompute (6=large areas, 10=small areas)
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
            
            # Parse delivery GPS coordinates (for future use)
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
                    
                    # Delivery location (customers/demand points) - optional
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

            MAX_CHUNKS = 55
            if chunk_num >= MAX_CHUNKS:
                print(f"\n⏹️ Reached {MAX_CHUNKS} chunks, stopping ingestion early...\n")
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
        print(f"✅ DATA INGESTION COMPLETE!")
        print(f"{'=' * 80}")
        print(f"📊 Total records inserted: {total_inserted:,}")
        if total_skipped > 0:
            print(f"⚠️  Records skipped: {total_skipped:,}")
        
        # Create indexes
        create_indexes(collection)
        
        # Show summary statistics
        print(f"\n📈 DATABASE SUMMARY:")
        print(f"   Total documents: {collection.count_documents({}):,}")
        print(f"   Unique logistics players: {len(collection.distinct('logistics_player'))}")
        print(f"   Date range: {collection.find_one(sort=[('timestamp', 1)])['date']} to {collection.find_one(sort=[('timestamp', -1)])['date']}")
        print(f"   Success rate: {collection.count_documents({'order_status': 'success'}) / collection.count_documents({}) * 100:.1f}%")
        
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
    csv_file = 'logistics_bigData.csv'
    
    # Check if custom CSV path provided
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    
    ingest_csv_to_mongodb(csv_file, chunk_size=100000)