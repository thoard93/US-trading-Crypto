from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
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
    user_id = Column(Integer, ForeignKey("users.id"))
    
    owner = relationship("User", back_populates="api_keys")

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String)
    side = Column(String)   # 'BUY', 'SELL'
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
