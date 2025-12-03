import requests
import psycopg2
import pandas as pd
import numpy as np
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List
from collections import defaultdict

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================
DB_HOST = 'winbets-predictions.postgres.database.azure.com'
DB_PORT = '5432'
DB_NAME = 'postgres'
DB_USER = 'winbets'
DB_PASSWORD = 'Constantinople@1900'
TABLE_NAME = 'agility_nba_b1'

# ============================================================================
# API CONFIGURATION (Same as PreMatchFeatureEngine)
# ============================================================================
API_KEYS = [
    "jdP3cFD34Ox128KeOzk1QO80WKPYoh8ZKzjLeL0H",
    "yaVs9ag9ZV7B011YWcbOFuszgN5bdeTai5r8eVWi",
    "7iXdsTMLsQpiFV6f1aWUak0BOoYrmuAf4YD99oVE",
    "dfgSQXX31W4efJ2Nqq71E35eVbtRBth8BYtHRYPc",
    "6vTdojNKZXdXhLLN9XgqlqqfXC87g3L3EoagQVAi"
]
BASE_URL = "https://api.sportradar.us/nba"
ACCESS_LEVEL = "trial"
VERSION = "v8"
LANGUAGE = "en"
FORMAT = "json"
REQUEST_DELAY = 1.5
RATE_LIMIT_THRESHOLD = 5


# ============================================================================
# SPORTRADAR API FETCHER (From PreMatchFeatureEngine)
# ============================================================================
class SportradarFetcher:
    """Fetch actual game data from Sportradar using match_ids"""
    
    def __init__(self, api_keys=API_KEYS):
        self.api_keys = api_keys
        self.current_key_index = 0
        self.rate_limit_count = 0
        self.base_url = f"{BASE_URL}/{ACCESS_LEVEL}/{VERSION}/{LANGUAGE}"
        self.request_count = 0
    
    def _get_current_api_key(self) -> str:
        """Get current active API key"""
        return self.api_keys[self.current_key_index]
    
    def _switch_api_key(self) -> None:
        """Switch to next API key"""
        if self.current_key_index < len(self.api_keys) - 1:
            self.current_key_index += 1
            self.rate_limit_count = 0
            print(f"    Switching to API key {self.current_key_index + 1}/{len(self.api_keys)}")
        else:
            self.rate_limit_count = 0
    
    def _make_request(self, endpoint: str, retries: int = 3) -> Optional[Dict]:
        """Make API request with retry logic and API key rotation"""
        url = f"{self.base_url}/{endpoint}?api_key={self._get_current_api_key()}"
        
        total_attempts = 0
        max_total_attempts = 50
        
        while total_attempts < max_total_attempts:
            try:
                response = requests.get(url, timeout=30)
                self.request_count += 1
                total_attempts += 1
                
                if response.status_code == 200:
                    self.rate_limit_count = 0
                    time.sleep(REQUEST_DELAY)
                    return response.json()
                elif response.status_code == 429:
                    self.rate_limit_count += 1
                    
                    if self.rate_limit_count >= RATE_LIMIT_THRESHOLD:
                        self._switch_api_key()
                        url = f"{self.base_url}/{endpoint}?api_key={self._get_current_api_key()}"
                        self.rate_limit_count = 0
                    
                    continue
                elif response.status_code == 404:
                    return None
                else:
                    time.sleep(5)
                    continue
                    
            except Exception as e:
                time.sleep(5)
                continue
        
        return None
    
    def get_game_summary(self, game_id: str) -> Optional[Dict]:
        """Get detailed game statistics by match_id"""
        endpoint = f"games/{game_id}/summary.{FORMAT}"
        return self._make_request(endpoint)


# ============================================================================
# PNL CALCULATION FUNCTIONS
# ============================================================================

def calculate_ml_correct(predicted_winner, actual_winner):
    """
    Calculate if moneyline prediction was correct.
    
    Args:
        predicted_winner: str - "HOME WIN" or "AWAY WIN"
        actual_winner: str - "HOME WIN" or "AWAY WIN"
    
    Returns:
        int - 1 if correct, 0 if incorrect
    """
    pred_normalized = str(predicted_winner).strip().upper()
    actual_normalized = str(actual_winner).strip().upper()
    
    return 1 if pred_normalized == actual_normalized else 0


def determine_ml_actual(home_points, away_points):
    """
    Determine actual moneyline winner from scores.
    
    Args:
        home_points: int - home team actual points
        away_points: int - away team actual points
    
    Returns:
        str - "HOME WIN" or "AWAY WIN"
    """
    if home_points is None or away_points is None:
        return None
    
    try:
        h_pts = int(home_points)
        a_pts = int(away_points)
        return "HOME WIN" if h_pts > a_pts else "AWAY WIN"
    except (ValueError, TypeError):
        return None


def calculate_ml_pnl(ml_correct, moneyline_odds):
    """
    Calculate P/L on moneyline bet.
    
    Logic:
    - If correct: profit = (odds * 1) - 1
    - If incorrect: loss = -1.0
    
    Args:
        ml_correct: int - 1 if prediction correct, 0 if incorrect
        moneyline_odds: float - the odds for the predicted side
    
    Returns:
        float - rounded to 2 decimal places
    """
    try:
        odds = float(moneyline_odds) if pd.notna(moneyline_odds) else None
        
        if odds is None or odds <= 0:
            return None
        
        if ml_correct == 1:
            pnl = round((odds * 1) - 1, 2)
        else:
            pnl = -1.0
        
        return pnl
    except (ValueError, TypeError):
        return None


def determine_status(home_points_actual, away_points_actual):
    """
    Determine game status based on actual points.
    
    Args:
        home_points_actual: int or None - home team actual points
        away_points_actual: int or None - away team actual points
    
    Returns:
        str - "SETTLED" if both scores exist, "PENDING" otherwise
    """
    if pd.notna(home_points_actual) and pd.notna(away_points_actual):
        return 'SETTLED'
    else:
        return 'PENDING'


# ============================================================================
# MAIN VALIDATION WORKFLOW
# ============================================================================

def validate_with_actual_data(predictions_csv, prematch_csv):
    """
    Main workflow:
    1. Read predictions CSV
    2. Read prematch features CSV to get match_ids
    3. Fetch actual game data from Sportradar
    4. Calculate ml_actual, ml_correct, ml_pnl
    5. Update status based on whether actual data exists
    6. Push to database
    """
    
    print("\n" + "="*100)
    print("NBA VALIDATION WITH ACTUAL DATA FETCH")
    print("="*100)
    
    # ========================================================================
    # STEP 1: READ PREDICTIONS CSV
    # ========================================================================
    print("\n[STEP 1] Reading predictions data...")
    try:
        df_predictions = pd.read_csv(predictions_csv)
        print(f"  ✓ Loaded {len(df_predictions)} predictions from {predictions_csv}")
    except FileNotFoundError:
        print(f"  ✗ File not found: {predictions_csv}")
        return
    
    # ========================================================================
    # STEP 2: READ PREMATCH FEATURES CSV (for match_ids)
    # ========================================================================
    print("\n[STEP 2] Reading prematch features data (for match_ids)...")
    try:
        df_prematch = pd.read_csv(prematch_csv)
        print(f"  ✓ Loaded {len(df_prematch)} prematch records from {prematch_csv}")
        
        # Create match_id lookup by game_identifier
        match_id_lookup = dict(zip(df_prematch['game_identifier'], df_prematch['match_id']))
        print(f"  ✓ Created lookup for {len(match_id_lookup)} match_ids")
    except FileNotFoundError:
        print(f"  ✗ File not found: {prematch_csv}")
        return
    
    # ========================================================================
    # STEP 3: MERGE AND PREPARE DATA
    # ========================================================================
    print("\n[STEP 3] Merging predictions with match_ids...")
    
    # Add match_id column from lookup
    df_predictions['match_id'] = df_predictions['game_identifier'].map(match_id_lookup)
    
    missing_match_ids = df_predictions['match_id'].isna().sum()
    if missing_match_ids > 0:
        print(f"  ⚠️  {missing_match_ids} records missing match_ids (game not in prematch features)")
    
    # Filter out records without match_ids
    df_valid = df_predictions[df_predictions['match_id'].notna()].copy()
    print(f"  ✓ {len(df_valid)} records have match_ids to fetch")
    
    if len(df_valid) == 0:
        print("  ✗ No valid records to process")
        return
    
    # ========================================================================
    # STEP 4: FETCH ACTUAL DATA FROM SPORTRADAR
    # ========================================================================
    print("\n[STEP 4] Fetching actual game data from Sportradar...")
    print(f"  API keys available: {len(API_KEYS)}")
    print(f"  Rate limit threshold: {RATE_LIMIT_THRESHOLD}")
    print()
    
    fetcher = SportradarFetcher()
    
    # Store fetched data
    actual_data = {}
    fetch_success = 0
    fetch_failed = 0
    
    for idx, row in df_valid.iterrows():
        game_id = row['match_id']
        game_identifier = row['game_identifier']
        
        # Fetch game summary
        game_summary = fetcher.get_game_summary(game_id)
        
        if game_summary:
            try:
                home_points = game_summary.get('home', {}).get('points')
                away_points = game_summary.get('away', {}).get('points')
                
                actual_data[game_identifier] = {
                    'home_points_actual': home_points,
                    'away_points_actual': away_points,
                    'status': game_summary.get('status'),
                    'raw_data': game_summary
                }
                fetch_success += 1
                
                if (fetch_success + fetch_failed) % 10 == 0:
                    print(f"  ✓ Fetched {fetch_success}/{len(df_valid)} games")
            except Exception as e:
                actual_data[game_identifier] = {'error': str(e)}
                fetch_failed += 1
        else:
            actual_data[game_identifier] = {'error': 'No data returned'}
            fetch_failed += 1
    
    print(f"\n  ✓ Successfully fetched: {fetch_success}")
    print(f"  ✗ Failed to fetch: {fetch_failed}")
    print(f"  API requests made: {fetcher.request_count}")
    
    # ========================================================================
    # STEP 5: CALCULATE VALIDATION METRICS
    # ========================================================================
    print("\n[STEP 5] Calculating validation metrics...")
    
    df_validation = df_valid.copy()
    
    # Add actual data columns
    df_validation['home_points_actual'] = df_validation['game_identifier'].apply(
        lambda x: actual_data.get(x, {}).get('home_points_actual')
    )
    df_validation['away_points_actual'] = df_validation['game_identifier'].apply(
        lambda x: actual_data.get(x, {}).get('away_points_actual')
    )
    
    # Calculate total actual
    df_validation['total_points_actual'] = (
        df_validation['home_points_actual'] + df_validation['away_points_actual']
    )
    
    # Determine ML actual winner
    df_validation['ml_actual'] = df_validation.apply(
        lambda row: determine_ml_actual(row['home_points_actual'], row['away_points_actual']),
        axis=1
    )
    
    # Calculate ML correctness
    df_validation['ml_correct'] = df_validation.apply(
        lambda row: calculate_ml_correct(row['ml_prediction'], row['ml_actual']),
        axis=1
    )
    
    # Get correct odds based on prediction
    def get_odds_for_prediction(row):
        """Extract odds based on which side was predicted"""
        predicted = str(row.get('ml_prediction', '')).strip().upper()
        home_odds = row.get('home_win_odds')
        away_odds = row.get('away_win_odds')
        
        if pd.notna(home_odds) and pd.notna(away_odds):
            if predicted == 'HOME WIN':
                return home_odds
            elif predicted == 'AWAY WIN':
                return away_odds
        return None
    
    df_validation['odds_used'] = df_validation.apply(get_odds_for_prediction, axis=1)
    
    # Calculate PnL
    df_validation['ml_pnl'] = df_validation.apply(
        lambda row: calculate_ml_pnl(row['ml_correct'], row['odds_used']),
        axis=1
    )
    
    # Determine status based on actual points
    df_validation['status'] = df_validation.apply(
        lambda row: determine_status(row['home_points_actual'], row['away_points_actual']),
        axis=1
    )
    
    print(f"  ✓ Calculated metrics for {len(df_validation)} records")
    
    # ========================================================================
    # STEP 6: SUMMARY STATISTICS
    # ========================================================================
    print("\n[STEP 6] Validation Summary")
    print("="*100)
    
    total_with_data = df_validation['home_points_actual'].notna().sum()
    correct_predictions = df_validation['ml_correct'].sum()
    accuracy = (correct_predictions / total_with_data * 100) if total_with_data > 0 else 0
    total_pnl = df_validation['ml_pnl'].sum()
    settled_count = (df_validation['status'] == 'SETTLED').sum()
    pending_count = (df_validation['status'] == 'PENDING').sum()
    
    print(f"  Total records: {len(df_validation)}")
    print(f"  With actual data: {total_with_data}")
    print(f"  Correct predictions: {int(correct_predictions)}")
    print(f"  Accuracy: {accuracy:.1f}%")
    print(f"  Total P/L: ${total_pnl:+.2f}")
    if total_with_data > 0:
        print(f"  Avg P/L per bet: ${total_pnl / total_with_data:+.2f}")
    print(f"  Status - SETTLED: {settled_count}")
    print(f"  Status - PENDING: {pending_count}")
    
    # Show sample records
    print(f"\n[SAMPLE DATA] First 5 records with calculations:")
    print("-"*100)
    
    sample_cols = [
        'game_identifier', 'ml_prediction', 'ml_actual', 'ml_correct',
        'home_points_actual', 'away_points_actual', 'total_points_actual', 'ml_pnl', 'status'
    ]
    available_cols = [col for col in sample_cols if col in df_validation.columns]
    
    if available_cols:
        print(df_validation[available_cols].head(5).to_string(index=False))
    
    # ========================================================================
    # STEP 7: PUSH TO DATABASE
    # ========================================================================
    print("\n[STEP 7] Database Push")
    print("="*100)
    
    push_df = df_validation[[
        'game_identifier',
        'home_points_actual',
        'away_points_actual',
        'total_points_actual',
        'ml_actual',
        'ml_correct',
        'ml_pnl',
        'status'
    ]].copy()
    
    print(f"\nRecords to push: {len(push_df)}")
    print(f"\nSample push data:")
    print("-"*100)
    print(push_df.head(10).to_string(index=False))
    print("-"*100)
    print()
    
    # Connect and push
    print("\n[CONNECTING] To database...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cursor = conn.cursor()
        print(f"  ✓ Connected to {TABLE_NAME}")
    except psycopg2.Error as e:
        print(f"  ✗ Database error: {e}")
        return
    
    updated = 0
    failed = 0
    
    print(f"\n[PUSHING] {len(push_df)} records...")
    
    for idx, row in push_df.iterrows():
        game_id = row['game_identifier']
        
        try:
            update_query = f"""
            UPDATE {TABLE_NAME}
            SET home_points_actual = %s,
                away_points_actual = %s,
                total_points_actual = %s,
                ml_actual = %s,
                ml_correct = %s,
                ml_pnl = %s,
                status = %s
            WHERE game_identifier = %s
            """
            
            cursor.execute(update_query, (
                int(row['home_points_actual']) if pd.notna(row['home_points_actual']) else None,
                int(row['away_points_actual']) if pd.notna(row['away_points_actual']) else None,
                int(row['total_points_actual']) if pd.notna(row['total_points_actual']) else None,
                row['ml_actual'],
                bool(int(row['ml_correct'])) if pd.notna(row['ml_correct']) else None,
                float(row['ml_pnl']) if pd.notna(row['ml_pnl']) else None,
                row['status'],
                game_id
            ))
            
            rows_affected = cursor.rowcount
            if rows_affected > 0:
                updated += rows_affected
                if (idx + 1) % 20 == 0:
                    print(f"  ✓ Processed {idx + 1}/{len(push_df)}")
            else:
                print(f"  ⚠️  Row {idx + 1}: No record found for {game_id}")
        
        except Exception as e:
            print(f"  ✗ Row {idx + 1} ({game_id}): {str(e)}")
            failed += 1
    
    # Commit
    conn.commit()
    
    print(f"\n{'='*100}")
    print("✓ PUSH COMPLETE")
    print(f"{'='*100}")
    print(f"✓ Successfully updated: {updated} records")
    print(f"✗ Failed: {failed} records")
    print(f"⏭️  Skipped: {len(push_df) - updated - failed} records (no match)")
    
    cursor.close()
    conn.close()
    
    print(f"\n{'='*100}")


if __name__ == "__main__":
    predictions_file = "NBA_PREDICTIONS_ML.csv"
    prematch_file = "nba_prematch_features.csv"
    
    validate_with_actual_data(predictions_file, prematch_file)
