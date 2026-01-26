from sqlalchemy import text
from database import engine

def run_migrations():
    """Manually add missing columns to the database."""
    print("MIGRATE: Running Database Migrations...")
    with engine.connect() as conn:
        # Helper to execute with safe rollback and explicit existence check
        def safe_execute(table, column, sql, name):
            try:
                # Check if column exists first (Postgres specific check)
                check_sql = f"""
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='{table}' AND column_name='{column}'
                """
                with conn.begin():
                    exists = conn.execute(text(check_sql)).fetchone()
                
                if not exists:
                    with conn.begin():
                        conn.execute(text(sql))
                    print(f" MIGRATE: Change applied: {name}")
                else:
                    print(f" MIGRATE: {name} already exists.")
            except Exception as e:
                # Fallback: Try with sub-transaction if check fails
                try:
                    with conn.begin():
                        conn.execute(text(sql))
                    print(f" MIGRATE: Change applied via fallback: {name}")
                except Exception as inner_e:
                    if "already exists" not in str(inner_e).lower():
                        print(f" MIGRATE: Skip {name} (detail: {str(inner_e)[:80]}...)")
                    else:
                        print(f" MIGRATE: {name} already exists.")

        # 1. Update 'users' table
        safe_execute("users", "discord_id", "ALTER TABLE users ADD COLUMN discord_id VARCHAR", "discord_id in users")
        safe_execute("users", "avatar", "ALTER TABLE users ADD COLUMN avatar VARCHAR", "avatar in users")

        # 2. Update 'api_keys' table
        safe_execute("api_keys", "extra_config", "ALTER TABLE api_keys ADD COLUMN extra_config VARCHAR", "extra_config in api_keys")

        # 3. Update 'trades' table
        safe_execute("trades", "asset_type", "ALTER TABLE trades ADD COLUMN asset_type VARCHAR DEFAULT 'CRYPTO'", "asset_type in trades")
        
        # 4. Update 'whale_wallets' table
        safe_execute("whale_wallets", "last_active", "ALTER TABLE whale_wallets ADD COLUMN last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "last_active in whale_wallets")
        
        # 5. Update 'dex_positions' table
        safe_execute("dex_positions", "highest_pnl", "ALTER TABLE dex_positions ADD COLUMN highest_pnl FLOAT DEFAULT 0.0", "highest_pnl in dex_positions")
        safe_execute("dex_positions", "trade_count", "ALTER TABLE dex_positions ADD COLUMN trade_count INTEGER DEFAULT 1", "trade_count in dex_positions")

        # 6. Update 'launched_keywords' table
        safe_execute("launched_keywords", "name", "ALTER TABLE launched_keywords ADD COLUMN name VARCHAR", "name in launched_keywords")
        safe_execute("launched_keywords", "symbol", "ALTER TABLE launched_keywords ADD COLUMN symbol VARCHAR", "symbol in launched_keywords")

        # 7. One-time Score Bump (Ultimate Bot Consensus Fix)
        # Brings existing whales (10.0) up to the new Alpha Hunter baseline (12.5)
        try:
            with conn.begin():
                result = conn.execute(text("UPDATE whale_wallets SET score = 12.5 WHERE score = 10.0"))
                # Use rowcount if available
                if hasattr(result, 'rowcount') and result.rowcount > 0:
                    print(f" MIGRATE: Bumped {result.rowcount} whales to 12.5 score.")
        except Exception as e:
            # Table might not exist yet if this is a fresh install
            print(f" MIGRATE: Score bump skipped ({str(e)[:50]}...)")

    print("MIGRATE: Migrations Complete.")

if __name__ == "__main__":
    run_migrations()
