from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User
import os

# Use DATABASE_URL from environment (provided by Render Postgres)
# Fallback to local SQLite for development
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not SQLALCHEMY_DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./trading_platform.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    # check_same_thread is only needed for SQLite
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
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
    except Exception as e:
        print(f"Error seeding DB: {e}")
    finally:
        db.close()
    print(f"Database initialized with: {SQLALCHEMY_DATABASE_URL.split(':')[0]}")

if __name__ == "__main__":
    init_db()
