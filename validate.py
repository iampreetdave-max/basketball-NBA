for idx, row in push_df.iterrows():
        game_id = row['game_identifier']
        
        try:
            update_query = f"""
            UPDATE {TABLE_NAME}
            SET home_points_actual = %s,
                away_points_actual = %s,
                total_points_actual = %s,
                ml_actual = %s,
                ml_correct = %s::boolean,
                ml_pnl = %s,
                ou_correct = %s,
                status = %s
            WHERE game_identifier = %s
            """
            
            cursor.execute(update_query, (
                int(row['home_points_actual']) if pd.notna(row['home_points_actual']) else None,
                int(row['away_points_actual']) if pd.notna(row['away_points_actual']) else None,
                int(row['total_points_actual']) if pd.notna(row['total_points_actual']) else None,
                row['ml_actual'],
                int(row['ml_correct']) if pd.notna(row['ml_correct']) else None,
                float(row['ml_pnl']) if pd.notna(row['ml_pnl']) else None,
                row['ou_correct'],  # String: OVER, UNDER, or None
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
