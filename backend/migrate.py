from sqlalchemy import text
from database import engine

def run_migrations():
    """Manually add missing columns to the database."""
    print("MIGRATE: Running Database Migrations...")
    with engine.connect() as conn:
        # 1. Update 'users' table
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN discord_id VARCHAR"))
            print(" MIGRATE: Added 'discord_id' to users")
        except Exception: pass # Already exists

        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN avatar VARCHAR"))
            print(" MIGRATE: Added 'avatar' to users")
        except Exception: pass

        # 2. Update 'api_keys' table
        try:
            conn.execute(text("ALTER TABLE api_keys ADD COLUMN extra_config VARCHAR"))
            print(" MIGRATE: Added 'extra_config' to api_keys")
        except Exception: pass

        # 3. Update 'trades' table
        try:
            conn.execute(text("ALTER TABLE trades ADD COLUMN asset_type VARCHAR DEFAULT 'CRYPTO'"))
            print(" MIGRATE: Added 'asset_type' to trades")
        except Exception: pass
        
        # 4. Update 'whale_wallets' table - Add last_active for pruning lazy whales
        try:
            conn.execute(text("ALTER TABLE whale_wallets ADD COLUMN last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
            print(" MIGRATE: Added 'last_active' to whale_wallets")
        except Exception: pass  # Already exists
        
        # 5. Update 'dex_positions' table - Add highest_pnl and trade_count for Ultimate Bot
        try:
            conn.execute(text("ALTER TABLE dex_positions ADD COLUMN highest_pnl FLOAT DEFAULT 0.0"))
            print(" MIGRATE: Added 'highest_pnl' to dex_positions")
        except Exception: pass

        try:
            conn.execute(text("ALTER TABLE dex_positions ADD COLUMN trade_count INTEGER DEFAULT 1"))
            print(" MIGRATE: Added 'trade_count' to dex_positions")
        except Exception: pass
        
        conn.commit()
    print("MIGRATE: Migrations Complete.")

if __name__ == "__main__":
    run_migrations()
