from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User
import os

# Use DATABASE_URL from environment (provided by Render Postgres)
# Fallback to local SQLite for development
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or None

if SQLALCHEMY_DATABASE_URL:
    # DEBUG: Masked connection string (Safe for logs)
    db_host = SQLALCHEMY_DATABASE_URL.split('@')[-1] if '@' in SQLALCHEMY_DATABASE_URL else "internal"
    print(f"🗄️ Connecting to Database: {db_host}")
    
    if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not SQLALCHEMY_DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./trading_platform.db"
    print("⚠️ DATABASE_URL not found. Falling back to SQLite.")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    # check_same_thread is only needed for SQLite
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    print("🛠️ Initializing Database Connection...")
    try:
        from migrate import run_migrations
        run_migrations()
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            # Check if Demo User exists
            demo_user = db.query(User).filter(User.id == 1).first()
            if not demo_user:
                user = User(id=1, username="demo_trader", hashed_password="not_needed_for_now")
                db.add(user)
                db.commit()
                print("👤 Demo User created.")
            print("✅ Database Connection: STABLE")
        except Exception as e:
            print(f"⚠️ Error seeding DB: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"❌ CRITICAL DATABASE ERROR: {e}")
        print("💡 TIP: Verify your DATABASE_URL in Render. If you recently reset the DB password, you must update the environment variable.")
        # We don't raise here so the bot can at least keep the Webhook Listener alive for health checks
        # But most functions will fail.

if __name__ == "__main__":
    init_db()
