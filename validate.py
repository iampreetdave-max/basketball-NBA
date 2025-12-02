import psycopg2
import pandas as pd

# Database credentials
DB_HOST = 'winbets-predictions.postgres.database.azure.com'
DB_PORT = '5432'
DB_NAME = 'postgres'
DB_USER = 'winbets'
DB_PASSWORD = 'Constantinople@1900'
TABLE_NAME = 'agility_nba_b1'

# ============================================================================
# PNL CALCULATION FUNCTIONS (from validation engine)
# ============================================================================

def calculate_ml_correct(predicted_winner, actual_winner):
    """
    Calculate if moneyline prediction was correct.
    
    Args:
        predicted_winner: str - "HOME WIN" or "AWAY WIN" (from moneyline_predicted)
        actual_winner: str - "HOME WIN" or "AWAY WIN" (from moneyline_actual)
    
    Returns:
        int - 1 if correct, 0 if incorrect
    """
    # Normalize to handle case variations and slight format differences
    pred_normalized = str(predicted_winner).strip().upper()
    actual_normalized = str(actual_winner).strip().upper()
    
    if pred_normalized == actual_normalized:
        return 1
    else:
        return 0


def calculate_ml_pnl(ml_correct, moneyline_odds):
    """
    Calculate P/L on moneyline bet.
    
    Logic from validation engine:
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
            # Winning bet: multiply odds by 1 and subtract 1 (net profit)
            pnl = round((odds * 1) - 1, 2)
        else:
            # Losing bet: loss of 1.0 (full stake)
            pnl = -1.0
        
        return pnl
    except (ValueError, TypeError):
        return None


# ============================================================================
# DATA PUSH FUNCTION
# ============================================================================

def push_to_database(csv_file_path):
    """
    Read CSV, calculate ml_correct and ml_pnl, then update PostgreSQL database.
    
    Data flow:
    1. Read CSV with all prediction data
    2. Determine which odds to use (home_odds or away_odds based on prediction)
    3. Calculate ml_correct by comparing moneyline_predicted vs moneyline_actual
    4. Calculate ml_pnl using the PnL formula with odds and correctness
    5. Update database rows matched on game_identifier
    """
    try:
        # Read CSV
        df = pd.read_csv(csv_file_path)
        print(f"\n✓ Loaded {len(df)} rows from {csv_file_path}")
        
        # Validate required columns
        required_columns = [
            'game_identifier',
            'moneyline_predicted',
            'moneyline_actual',
            'home_odds',
            'away_odds',
            'home_actual',
            'away_actual',
            'total_actual',
            'moneyline_correct'
        ]
        
        missing_cols = [col for col in required_columns if col not in df.columns]
        if missing_cols:
            print(f"✗ Missing columns: {missing_cols}")
            return
        
        # Create working copy
        df_subset = df[[col for col in required_columns if col in df.columns]].copy()
        
        # ====================================================================
        # CALCULATE ML_CORRECT
        # ====================================================================
        print("\n[STEP 1] Calculating ml_correct...")
        df_subset['ml_correct_calc'] = df_subset.apply(
            lambda row: calculate_ml_correct(
                row.get('moneyline_predicted'),
                row.get('moneyline_actual')
            ),
            axis=1
        )
        
        # Compare with CSV values (for validation)
        matches = (df_subset['moneyline_correct'] == df_subset['ml_correct_calc']).sum()
        print(f"   ✓ Calculated {len(df_subset)} ml_correct values")
        print(f"   ✓ {matches}/{len(df_subset)} match CSV values")
        
        # ====================================================================
        # CALCULATE ML_PNL
        # ====================================================================
        print("\n[STEP 2] Calculating ml_pnl...")
        
        def get_odds_for_prediction(row):
            """Get the correct odds based on which side was predicted"""
            predicted = str(row.get('moneyline_predicted', '')).strip().upper()
            home_odds = row.get('home_odds')
            away_odds = row.get('away_odds')
            
            if predicted == 'HOME WIN':
                return home_odds
            elif predicted == 'AWAY WIN':
                return away_odds
            else:
                return None
        
        # Get odds for each prediction
        df_subset['odds_used'] = df_subset.apply(get_odds_for_prediction, axis=1)
        
        # Calculate PnL
        df_subset['ml_pnl'] = df_subset.apply(
            lambda row: calculate_ml_pnl(
                row.get('ml_correct_calc'),
                row.get('odds_used')
            ),
            axis=1
        )
        
        print(f"   ✓ Calculated {len(df_subset)} ml_pnl values")
        
        # ====================================================================
        # DISPLAY SUMMARY BEFORE PUSH
        # ====================================================================
        print("\n[PREVIEW] First 5 rows to be pushed:")
        print("=" * 100)
        
        preview_df = df_subset[['game_identifier', 'moneyline_predicted', 'moneyline_actual', 
                                 'ml_correct_calc', 'odds_used', 'ml_pnl']].head(5)
        for idx, row in preview_df.iterrows():
            print(f"  {idx+1}. {row['game_identifier']}")
            print(f"     Prediction: {row['moneyline_predicted']} | Actual: {row['moneyline_actual']}")
            print(f"     Correct: {row['ml_correct_calc']} | Odds: {row['odds_used']} | PnL: ${row['ml_pnl']}")
        
        print("=" * 100)
        
        # Overall stats
        correct_count = df_subset['ml_correct_calc'].sum()
        accuracy = (correct_count / len(df_subset) * 100) if len(df_subset) > 0 else 0
        total_pnl = df_subset['ml_pnl'].sum()
        
        print(f"\n📊 CALCULATION SUMMARY:")
        print(f"   Total predictions: {len(df_subset)}")
        print(f"   Correct: {int(correct_count)}")
        print(f"   Accuracy: {accuracy:.1f}%")
        print(f"   Total P/L: ${total_pnl:+.2f}")
        print(f"   Avg P/L per bet: ${total_pnl / len(df_subset):+.2f}")
        
        print("\n" + "=" * 100)
        print("DATA TO BE PUSHED TO DATABASE")
        print("=" * 100)
        
        # Show what will be pushed
        push_df = df_subset[[
            'game_identifier',
            'home_actual',
            'away_actual',
            'total_actual',
            'moneyline_actual',
            'ml_correct_calc',
            'ml_pnl'
        ]].copy()
        
        print(push_df.to_string(index=False))
        print("=" * 100)
        print(f"\nTotal rows to process: {len(push_df)}")
        
        # Ask for confirmation
        confirmation = input("\n⚠️  Do you want to proceed with pushing this data to the database? (yes/no): ").strip().lower()
        if confirmation not in ['yes', 'y']:
            print("✗ Operation cancelled by user")
            return
        
        # ====================================================================
        # CONNECT TO DATABASE AND PUSH
        # ====================================================================
        print("\n[STEP 3] Connecting to database...")
        
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        
        cursor = conn.cursor()
        print(f"   ✓ Connected to {TABLE_NAME}")
        
        updated = 0
        failed = 0
        
        print(f"\n[STEP 4] Pushing {len(push_df)} records...")
        
        for idx, row in push_df.iterrows():
            game_id = row['game_identifier']
            
            try:
                # Update query
                update_query = f"""
                UPDATE {TABLE_NAME}
                SET home_points_actual = %s,
                    away_points_actual = %s,
                    total_points_actual = %s,
                    ml_actual = %s,
                    ml_correct = %s,
                    ml_pnl = %s
                WHERE game_identifier = %s
                """
                
                cursor.execute(update_query, (
                    int(row['home_actual']) if pd.notna(row['home_actual']) else None,
                    int(row['away_actual']) if pd.notna(row['away_actual']) else None,
                    int(row['total_actual']) if pd.notna(row['total_actual']) else None,
                    row['moneyline_actual'],
                    bool(int(row['ml_correct_calc'])) if pd.notna(row['ml_correct_calc']) else None,
                    float(row['ml_pnl']) if pd.notna(row['ml_pnl']) else None,
                    game_id
                ))
                
                rows_affected = cursor.rowcount
                if rows_affected > 0:
                    updated += rows_affected
                    if (idx + 1) % 20 == 0:
                        print(f"   ✓ Processed {idx + 1}/{len(push_df)}")
                else:
                    print(f"   ⚠️  Row {idx + 1}: No record found for {game_id}")
            
            except Exception as e:
                print(f"   ✗ Row {idx + 1} ({game_id}): {str(e)}")
                failed += 1
        
        # Commit transaction
        conn.commit()
        
        print(f"\n{'=' * 100}")
        print("✓ PUSH COMPLETE")
        print(f"{'=' * 100}")
        print(f"✓ Successfully updated: {updated} records")
        print(f"✗ Failed: {failed} records")
        print(f"⏭️  Skipped: {len(push_df) - updated - failed} records (no match found)")
        
        cursor.close()
        conn.close()
        
    except psycopg2.Error as e:
        print(f"✗ Database error: {e}")
    except FileNotFoundError:
        print(f"✗ CSV file not found: {csv_file_path}")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    csv_file = "NBA_PREDICTIONS_ML.csv"  # Replace with your CSV filename
    push_to_database(csv_file)
