from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    discord_id = Column(String, unique=True, index=True)
    avatar = Column(String)
    hashed_password = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    
    api_keys = relationship("ApiKey", back_populates="owner")
    trades = relationship("Trade", back_populates="owner")

class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String)  # 'kraken', 'alpaca', etc.
    api_key = Column(String)   # Encrypted
    api_secret = Column(String) # Encrypted
    extra_config = Column(String, nullable=True) # JSON or simple string
    user_id = Column(Integer, ForeignKey("users.id"))
    
    owner = relationship("User", back_populates="api_keys")

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String)
    side = Column(String)   # 'BUY', 'SELL'
    asset_type = Column(String, default="CRYPTO") # 'CRYPTO' or 'STOCK'
    amount = Column(Float)
    price = Column(Float)
    cost = Column(Float)    # amount * price
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    owner = relationship("User", back_populates="trades")

class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String)
    entry_price = Column(Float)
    amount = Column(Float)
    user_id = Column(Integer, ForeignKey("users.id"))

class DexPosition(Base):
    """Persisted DEX positions to preserve entry prices across restarts."""
    __tablename__ = "dex_positions"
    id = Column(Integer, primary_key=True, index=True)
    token_address = Column(String, index=True)  # Solana Mint Address
    wallet_address = Column(String, index=True) # Owner wallet
    symbol = Column(String)
    entry_price_usd = Column(Float)  # ACTUAL entry price (not current)
    amount = Column(Float)
    highest_pnl = Column(Float, default=0.0) # For Trailing Stop
    trade_count = Column(Integer, default=1) # For Churn Prevention
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class WhaleWallet(Base):
    """Qualified whale wallets for copy-trading (persisted)."""
    __tablename__ = "whale_wallets"
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String, unique=True, index=True)
    score = Column(Float, default=10.0)
    discovered_on = Column(String)  # Symbol or source
    discovered_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)  # Last trade seen
    stats = Column(JSON, nullable=True) # Full analysis data

class ActiveSwarm(Base):
    """Persisted swarm mappings (token -> [wallets]) for copy-trading exits."""
    __tablename__ = "active_swarms"
    id = Column(Integer, primary_key=True, index=True)
    token_address = Column(String, index=True)
    whale_address = Column(String, index=True)

class LaunchedKeyword(Base):
    """Tracks auto-launched keywords to prevent duplicates."""
    __tablename__ = "launched_keywords"
    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String, index=True)          # The trending keyword used
    mint_address = Column(String, index=True)     # Created token mint
    launched_at = Column(DateTime, default=datetime.datetime.utcnow)
