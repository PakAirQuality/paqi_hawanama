"""
Typed contracts for the OpenAQ v3 responses we consume.

Confirmed against https://docs.openaq.org (locations_get_v3_locations_get,
sensor_measurements_get_v3_sensors__sensors_id__measurements_get): camelCase
field names, `meta.found` may be an integer or a string such as ">1000".
Everything is `extra='ignore'` so new upstream fields never break parsing.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, List, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class DatetimePair(_Model):
    utc: datetime
    local: Optional[str] = None


class Parameter(_Model):
    id: Optional[int] = None
    name: str
    units: Optional[str] = None
    display_name: Optional[str] = Field(None, alias="displayName")


class Sensor(_Model):
    id: int
    name: Optional[str] = None
    parameter: Parameter


class Instrument(_Model):
    id: Optional[int] = None
    name: Optional[str] = None


class NamedRef(_Model):
    id: Optional[int] = None
    name: Optional[str] = None


class Country(_Model):
    id: Optional[int] = None
    code: Optional[str] = None
    name: Optional[str] = None


class Coordinates(_Model):
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class Attribution(_Model):
    name: Optional[str] = None
    url: Optional[str] = None


class License(_Model):
    id: Optional[int] = None
    name: Optional[str] = None
    attribution: Optional[Attribution] = None
    date_from: Optional[date] = Field(None, alias="dateFrom")
    date_to: Optional[date] = Field(None, alias="dateTo")


class Location(_Model):
    id: int
    name: Optional[str] = None
    locality: Optional[str] = None
    timezone: Optional[str] = None
    country: Optional[Country] = None
    owner: Optional[NamedRef] = None
    provider: Optional[NamedRef] = None
    is_mobile: bool = Field(False, alias="isMobile")
    is_monitor: bool = Field(False, alias="isMonitor")
    instruments: List[Instrument] = Field(default_factory=list)
    sensors: List[Sensor] = Field(default_factory=list)
    coordinates: Optional[Coordinates] = None
    licenses: Optional[List[License]] = None
    bounds: Optional[List[float]] = None
    datetime_first: Optional[DatetimePair] = Field(None, alias="datetimeFirst")
    datetime_last: Optional[DatetimePair] = Field(None, alias="datetimeLast")

    def sensors_for(self, parameter: str) -> List[Sensor]:
        return [s for s in self.sensors if (s.parameter.name or "").lower() == parameter.lower()]


class Period(_Model):
    label: Optional[str] = None
    interval: Optional[str] = None
    datetime_from: Optional[DatetimePair] = Field(None, alias="datetimeFrom")
    datetime_to: Optional[DatetimePair] = Field(None, alias="datetimeTo")


class Coverage(_Model):
    expected_count: Optional[int] = Field(None, alias="expectedCount")
    expected_interval: Optional[str] = Field(None, alias="expectedInterval")
    observed_count: Optional[int] = Field(None, alias="observedCount")
    observed_interval: Optional[str] = Field(None, alias="observedInterval")
    percent_complete: Optional[float] = Field(None, alias="percentComplete")
    percent_coverage: Optional[float] = Field(None, alias="percentCoverage")


class FlagInfo(_Model):
    has_flags: bool = Field(False, alias="hasFlags")


class Measurement(_Model):
    value: Optional[float] = None
    parameter: Parameter
    period: Optional[Period] = None
    coordinates: Optional[Coordinates] = None
    coverage: Optional[Coverage] = None
    flag_info: Optional[FlagInfo] = Field(None, alias="flagInfo")


class Meta(_Model):
    page: int = 1
    limit: int = 100
    found: Optional[Union[int, str]] = None

    def found_int(self) -> Optional[int]:
        """Integer `found` when the API gives one; strings like '>1000' are not a stop rule."""
        return self.found if isinstance(self.found, int) else None


class Page(_Model, Generic[T]):
    meta: Meta = Field(default_factory=Meta)
    results: List[T] = Field(default_factory=list)


class OpenAQRateInfo(_Model):
    limit: Optional[int] = None
    used: Optional[int] = None
    remaining: Optional[int] = None
    reset_in_s: Optional[float] = None
    reset_raw: Optional[str] = None


def parse_locations_page(payload: Any) -> Page[Location]:
    return Page[Location].model_validate(payload)


def parse_measurements_page(payload: Any) -> Page[Measurement]:
    return Page[Measurement].model_validate(payload)
