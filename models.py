from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    phone = Column(String)
    referrer_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    search_history = relationship("SearchHistory", back_populates="user")
    referrals = relationship("User")

class Subscription(Base):
    __tablename__ = 'subscriptions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True)
    is_active = Column(Boolean, default=False)
    start_date = Column(DateTime)
    period = Column(String)  # 'month' or 'year'
    end_date = Column(DateTime)
    is_trial = Column(Boolean, default=False)
    
    user = relationship("User", back_populates="subscription")
    payments = relationship("Payment", back_populates="subscription")

class Payment(Base):
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey('subscriptions.id'))
    amount = Column(Float, nullable=False)
    transaction_id = Column(String, unique=True)
    status = Column(String)  # 'pending', 'completed', 'failed'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    subscription = relationship("Subscription", back_populates="payments")

class SearchHistory(Base):
    __tablename__ = 'search_history'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    query_type = Column(String)  # 'vin', 'part_number', 'car_model'
    query_text = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="search_history")
    results = relationship("SearchResult", back_populates="search")

class SearchResult(Base):
    __tablename__ = 'search_results'
    
    id = Column(Integer, primary_key=True)
    search_id = Column(Integer, ForeignKey('search_history.id'))
    source = Column(String)  # 'exist', 'avtoto', 'autodoc'
    part_name = Column(String)
    part_number = Column(String)
    price = Column(Float)
    url = Column(String)
    rating = Column(Float)
    reviews_count = Column(Integer)
    
    search = relationship("SearchHistory", back_populates="results")
