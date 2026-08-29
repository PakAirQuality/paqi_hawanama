"""
Base models for the new TimescaleDB schema
"""

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, TIMESTAMP, SmallInteger, ARRAY
from sqlalchemy.dialects.postgresql import JSONB, CHAR
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator, Enum
from geoalchemy2 import Geography
import enum

Base = declarative_base()

# Enums matching the database
class ScopeType(str, enum.Enum):
    city = "city"
    station = "station"

class ForecastKind(str, enum.Enum):
    hourly = "hourly"
    daily = "daily"

class PollutantCode(str, enum.Enum):
    pm25 = "pm25"
    pm10 = "pm10"
    o3 = "o3"
    no2 = "no2"
    so2 = "so2"
    co = "co"

# Custom enum types for SQLAlchemy
ScopeTypeEnum = Enum(ScopeType, name="scope_type")
ForecastKindEnum = Enum(ForecastKind, name="forecast_kind")
PollutantCodeEnum = Enum(PollutantCode, name="pollutant_code")