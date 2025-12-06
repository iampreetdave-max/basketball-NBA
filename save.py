import psycopg2
import pandas as pd
from psycopg2 import sql

# Database configuration
DB_CONFIG = {
    'host': 'winbets-predictions.postgres.database.azure.com',
    'port': 5432,
    'database': 'postgres',
    'user': 'winbets',
    'password': 'Constantinople@1900'
}

TABLE_NAME = 'agility_NBA_b1'
CSV_FILE = 'NBA_PREDICTIONS_ML.csv'

# Columns from CSV to extract
CSV_COLUMNS = [
    'date',
    'league',
    'game_identifier',
    'home_id',
    'home_team',
    'away_id',
    'away_team',
    'home_points_predicted',
    'away_points_predicted',
    'total_points_predicted',
    'ml_prediction',
    'ml_probability',
    'home_win_odds',
    'away_win_odds',
    'ml_confidence',
    'status',
    'grade',
    'total_line_o',
    'ou_correct'
]

# Column mapping: CSV column -> Database column (use same name if not mapped)
COLUMN_MAPPING = {
    'total_line_o': 'market_total_line',
    'ou_correct': 'ou_correct'
}

def push_data():
    """Read CSV and push selected columns to database"""
    try:
        # Read CSV
        print(f"Reading {CSV_FILE}...")
        df = pd.read_csv(CSV_FILE)
        print(f"✓ Loaded {len(df)} rows from CSV")
        
        # Select only required columns
        df = df[CSV_COLUMNS]
        print(f"✓ Selected {len(CSV_COLUMNS)} columns")
        
        # Connect to database
        print("Connecting to PostgreSQL...")
        connection = psycopg2.connect(**DB_CONFIG)
        print("✓ Connected to database")
        
        # Insert data
        with connection.cursor() as cursor:
            for index, row in df.iterrows():
                # Map CSV column names to database column names
                db_columns = [COLUMN_MAPPING.get(col, col) for col in CSV_COLUMNS]
                
                # Build dynamic INSERT query with mapped column names
                columns = ', '.join(db_columns)
                placeholders = ', '.join(['%s'] * len(CSV_COLUMNS))
                
                insert_query = f"""
                INSERT INTO {TABLE_NAME} ({columns})
                VALUES ({placeholders})
                """
                
                # Handle NaN values as None for NULL insertion, preserving CSV column order
                values = tuple(
                    None if pd.isna(row[col]) else row[col]
                    for col in CSV_COLUMNS
                )
                
                cursor.execute(insert_query, values)
        
        connection.commit()
        print(f"✓ Inserted {len(df)} rows into '{TABLE_NAME}'")
        
        # Verify
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME};")
            count = cursor.fetchone()[0]
            print(f"✓ Verification: {count} total rows in {TABLE_NAME}")
        
        connection.close()
        print("✓ Database connection closed")
        print(f"\n✓ Success! Data pushed to {TABLE_NAME}")
        
    except FileNotFoundError:
        print(f"✗ Error: {CSV_FILE} not found")
        raise
    except KeyError as e:
        print(f"✗ Error: Column {e} not found in CSV")
        raise
    except psycopg2.Error as e:
        print(f"✗ Database error: {e}")
        raise
    except Exception as e:
        print(f"✗ Fatal error: {e}")
        raise

if __name__ == "__main__":
    push_data()
