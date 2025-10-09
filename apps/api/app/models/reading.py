"""Updated reading models for new TimescaleDB schema"""

from sqlalchemy import Column, String, Float, Integer, SmallInteger, TIMESTAMP, ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.models.base import Base, ScopeTypeEnum, PollutantCodeEnum


class Reading(Base):
    """Main readings table (TimescaleDB hypertable)"""
    __tablename__ = "readings"
    
    # Scope identification
    scope_type = Column(ScopeTypeEnum, nullable=False, primary_key=True)
    scope_key = Column(String, nullable=False, primary_key=True)
    ts_utc = Column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    
    # Air Quality Index values
    aqi_us = Column(SmallInteger)
    aqi_cn = Column(SmallInteger)
    main_us = Column(PollutantCodeEnum)
    main_cn = Column(PollutantCodeEnum)
    
    # Pollutant concentrations
    pm25 = Column(Float)
    pm10 = Column(Float)
    o3 = Column(Float)
    no2 = Column(Float)
    so2 = Column(Float)
    co = Column(Float)
    
    # Units for pollutant concentrations
    units_pm25 = Column(String, default='µg/m³')
    units_pm10 = Column(String, default='µg/m³')
    units_o3 = Column(String)
    units_no2 = Column(String)
    units_so2 = Column(String)
    units_co = Column(String)
    
    # Meteorological data
    temp_c = Column(Float)
    humidity = Column(Float)
    pressure_hpa = Column(Float)
    wind_speed_ms = Column(Float)
    wind_dir_deg = Column(Integer)
    weather_icon = Column(String)
    heatindex_c = Column(Float)
    dewpoint_c = Column(Float)
    visibility_km = Column(Float)
    uv_index = Column(Float)
    pop_pct = Column(SmallInteger)
    
    # Quality control and provenance
    qc_state = Column(String)
    qc_flags = Column(ARRAY(String))
    source = Column(String, nullable=False, default='airvisual')
    raw = Column(JSONB)
    ingested_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Forecast(Base):
    """Forecast data table (TimescaleDB hypertable)"""
    __tablename__ = "forecasts"
    
    # Scope identification
    scope_type = Column(ScopeTypeEnum, nullable=False, primary_key=True)
    scope_key = Column(String, nullable=False, primary_key=True)
    kind = Column(String, nullable=False, primary_key=True)  # 'hourly' | 'daily'
    ts_target = Column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    
    # Forecast metadata
    forecast_hour = Column(SmallInteger)
    issued_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    
    # Air quality forecasts
    aqi_us = Column(SmallInteger)
    aqi_cn = Column(SmallInteger)
    pm25 = Column(Float)
    pm10 = Column(Float)
    o3 = Column(Float)
    no2 = Column(Float)
    so2 = Column(Float)
    co = Column(Float)
    
    # Weather forecasts
    temp_c = Column(Float)
    temp_min_c = Column(Float)
    temp_max_c = Column(Float)
    humidity = Column(Float)
    pressure_hpa = Column(Float)
    wind_speed_ms = Column(Float)
    wind_dir_deg = Column(Integer)
    weather_icon = Column(String)
    weather_desc = Column(String)
    heatindex_c = Column(Float)
    uv_index = Column(Float)
    pop_pct = Column(SmallInteger)
    precip_mm = Column(Float)
    
    # Metadata
    units = Column(JSONB)
    confidence = Column(Float)
    source = Column(String, nullable=False, default='airvisual')
    raw = Column(JSONB)
    ingested_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class CacheBlob(Base):
    """Database-backed cache"""
    __tablename__ = "cache_blobs"
    
    cache_key = Column(String, primary_key=True)
    payload = Column(JSONB, nullable=False)
    content_type = Column(String, default='application/json')
    stored_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    expire_at = Column(TIMESTAMP(timezone=True), nullable=False)
    access_count = Column(Integer, default=0)
    last_accessed = Column(TIMESTAMP(timezone=True), server_default=func.now())


class UnitsCatalog(Base):
    """Pollutant unit definitions"""
    __tablename__ = "units_catalog"
    
    pollutant = Column(PollutantCodeEnum, primary_key=True)
    default_unit = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    description = Column(String)


class AqiBreakpoint(Base):
    """AQI calculation breakpoints"""
    __tablename__ = "aqi_breakpoints"
    
    scale = Column(String, nullable=False, primary_key=True)
    pollutant = Column(PollutantCodeEnum, nullable=False, primary_key=True)
    idx = Column(SmallInteger, nullable=False, primary_key=True)
    conc_lo = Column(Float, nullable=False)
    conc_hi = Column(Float, nullable=False)
    aqi_lo = Column(SmallInteger, nullable=False)
    aqi_hi = Column(SmallInteger, nullable=False)
    category = Column(String, nullable=False)
    color = Column(String)