from sqlalchemy import text
from database import engine

def run_migrations():
    """Manually add missing columns to the database."""
    print("MIGRATE: Running Database Migrations...")
    with engine.connect() as conn:
        # Helper to execute with safe rollback
        def safe_execute(sql, name):
            try:
                # Use a specific transaction for each change
                with conn.begin():
                    conn.execute(text(sql))
                print(f" MIGRATE: Change applied: {name}")
            except Exception as e:
                # Most common is 'already exists', so we silence but log if it's something else
                if "already exists" not in str(e).lower():
                    print(f" MIGRATE: Skip {name} (detail: {str(e)[:100]}...)")
                else:
                    print(f" MIGRATE: {name} already exists.")

        # 1. Update 'users' table
        safe_execute("ALTER TABLE users ADD COLUMN discord_id VARCHAR", "discord_id in users")
        safe_execute("ALTER TABLE users ADD COLUMN avatar VARCHAR", "avatar in users")

        # 2. Update 'api_keys' table
        safe_execute("ALTER TABLE api_keys ADD COLUMN extra_config VARCHAR", "extra_config in api_keys")

        # 3. Update 'trades' table
        safe_execute("ALTER TABLE trades ADD COLUMN asset_type VARCHAR DEFAULT 'CRYPTO'", "asset_type in trades")
        
        # 4. Update 'whale_wallets' table
        safe_execute("ALTER TABLE whale_wallets ADD COLUMN last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP", "last_active in whale_wallets")
        
        # 5. Update 'dex_positions' table
        safe_execute("ALTER TABLE dex_positions ADD COLUMN highest_pnl FLOAT DEFAULT 0.0", "highest_pnl in dex_positions")
        safe_execute("ALTER TABLE dex_positions ADD COLUMN trade_count INTEGER DEFAULT 1", "trade_count in dex_positions")
    print("MIGRATE: Migrations Complete.")

if __name__ == "__main__":
    run_migrations()
