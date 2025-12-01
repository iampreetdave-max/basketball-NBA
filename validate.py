"""
NBA Predictions Validation - Database Update
Updates agility_nba_b1 table with validation results
"""

import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
import sys
from datetime import datetime

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

DB_CONFIG = {
    'host': 'winbets-predictions.postgres.database.azure.com',
    'port': 5432,
    'database': 'postgres',
    'user': 'winbets',
    'password': 'Constantinople@1900'
}

TABLE_NAME = 'agility_nba_b1'
LOOKUP_COLUMN = 'game_identifier'

# Columns to update in database
UPDATE_COLUMNS = [
    'home_points_actual',
    'away_points_actual',
    'total_points_actual',
    'ml_actual',
    'ml_correct',
    'ml_pnl'
]


class NBADatabaseUpdater:
    """Handles database connection and updates"""
    
    def __init__(self, db_config):
        self.db_config = db_config
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """Connect to PostgreSQL database"""
        try:
            self.conn = psycopg2.connect(
                host=self.db_config['host'],
                port=self.db_config['port'],
                database=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                sslmode='require'
            )
            self.cursor = self.conn.cursor()
            print("✓ Connected to database")
            return True
        except Exception as e:
            print(f"❌ Connection failed: {str(e)}")
            return False
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
            print("✓ Connection closed")
    
    def check_columns_exist(self):
        """Check if update columns exist in table"""
        try:
            self.cursor.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{TABLE_NAME}' 
                AND table_schema = 'public'
            """)
            existing_cols = [row[0] for row in self.cursor.fetchall()]
            print(f"✓ Table has {len(existing_cols)} columns")
            
            missing_cols = [col for col in UPDATE_COLUMNS if col not in existing_cols]
            
            if missing_cols:
                print(f"⚠️  Missing columns: {missing_cols}")
                print("   Creating missing columns...")
                self.create_missing_columns(missing_cols)
            
            return True
        except Exception as e:
            print(f"❌ Error checking columns: {str(e)}")
            return False
    
    def create_missing_columns(self, columns):
        """Create missing columns in table"""
        try:
            for col in columns:
                if col == 'ml_correct':
                    sql = f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} INTEGER"
                elif col == 'ml_pnl':
                    sql = f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} NUMERIC(10,2)"
                else:
                    # For score and result columns
                    if 'points' in col:
                        sql = f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} INTEGER"
                    else:
                        sql = f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} VARCHAR(50)"
                
                self.cursor.execute(sql)
                self.conn.commit()
                print(f"   ✓ Created column: {col}")
        except Exception as e:
            print(f"❌ Error creating columns: {str(e)}")
            self.conn.rollback()
    
    def update_records(self, df):
        """Update records in database with batch operation"""
        try:
            if LOOKUP_COLUMN not in df.columns:
                print(f"❌ Error: '{LOOKUP_COLUMN}' column not found in CSV")
                return 0, 0
            
            updated_count = 0
            skipped_count = 0
            
            # Prepare batch update data
            update_data = []
            
            for idx, row in df.iterrows():
                game_id = row.get(LOOKUP_COLUMN)
                
                if not game_id or pd.isna(game_id):
                    skipped_count += 1
                    continue
                
                # Build update values tuple
                values = [row.get(col) for col in UPDATE_COLUMNS]
                values.append(game_id)  # Add lookup value at end
                
                update_data.append(tuple(values))
            
            # Build SQL update statement
            set_clause = ', '.join([f"{col} = %s" for col in UPDATE_COLUMNS])
            sql = f"""
                UPDATE {TABLE_NAME}
                SET {set_clause}
                WHERE {LOOKUP_COLUMN} = %s
            """
            
            # Execute batch update
            if update_data:
                execute_batch(self.cursor, sql, update_data, page_size=100)
                self.conn.commit()
                updated_count = len(update_data)
                print(f"✓ Updated {updated_count} records")
            
            return updated_count, skipped_count
        
        except Exception as e:
            print(f"❌ Error updating records: {str(e)}")
            self.conn.rollback()
            return 0, len(df)
    
    def verify_updates(self, df):
        """Verify a sample of updates"""
        try:
            if LOOKUP_COLUMN not in df.columns or len(df) == 0:
                return
            
            # Check first record
            sample_game_id = df.iloc[0].get(LOOKUP_COLUMN)
            
            self.cursor.execute(f"""
                SELECT {', '.join(UPDATE_COLUMNS)}
                FROM {TABLE_NAME}
                WHERE {LOOKUP_COLUMN} = %s
            """, (sample_game_id,))
            
            result = self.cursor.fetchone()
            
            if result:
                print(f"\n✓ Sample verification for {LOOKUP_COLUMN}={sample_game_id}:")
                for col, val in zip(UPDATE_COLUMNS, result):
                    print(f"   {col}: {val}")
            else:
                print(f"⚠️  Game ID {sample_game_id} not found in database")
        
        except Exception as e:
            print(f"❌ Error verifying updates: {str(e)}")


def read_csv(csv_file):
    """Read CSV file"""
    try:
        df = pd.read_csv(csv_file)
        print(f"✓ Loaded {len(df)} rows from {csv_file}")
        return df
    except FileNotFoundError:
        print(f"❌ File not found: {csv_file}")
        return None
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return None


def main():
    """Main execution"""
    print("\n" + "=" * 80)
    print("🏀 NBA VALIDATION - DATABASE UPDATE")
    print("=" * 80)
    print(f"⏰ Time: {datetime.now().isoformat()}\n")
    
    # Read validation results
    results_df = read_csv('NBA_Validation.csv')
    if results_df is None or len(results_df) == 0:
        print("⚠️  No validation results to update")
        sys.exit(0)
    
    print(f"   Database: {DB_CONFIG['host']}")
    print(f"   Table: {TABLE_NAME}")
    print(f"   Lookup column: {LOOKUP_COLUMN}\n")
    
    # Connect to database
    db = NBADatabaseUpdater(DB_CONFIG)
    if not db.connect():
        sys.exit(1)
    
    # Check columns
    if not db.check_columns_exist():
        db.close()
        sys.exit(1)
    
    print()
    
    # Update records
    updated, skipped = db.update_records(results_df)
    
    print(f"\n   Total records in CSV: {len(results_df)}")
    print(f"   Updated: {updated}")
    print(f"   Skipped: {skipped}")
    
    # Verify updates
    if updated > 0:
        db.verify_updates(results_df)
    
    # Close connection
    db.close()
    
    print("\n" + "=" * 80)
    print("✓ Database update complete")
    print("=" * 80 + "\n")


if __name__ == '__main__':
    main()
