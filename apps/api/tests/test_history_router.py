"""
Tests for History API Router
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.utils.history_params import (
    parse_iso_timestamp, validate_time_range, validate_pollutants,
    get_default_time_range, generate_hourly_timeline
)

client = TestClient(app)


class TestHistoryParams:
    """Test cases for history parameter utilities"""
    
    def test_parse_iso_timestamp_valid(self):
        """Test parsing valid ISO timestamps"""
        # With Z suffix
        ts = parse_iso_timestamp("2025-09-24T14:00:00Z")
        assert ts.tzinfo == timezone.utc
        assert ts.hour == 14
        
        # With timezone offset
        ts = parse_iso_timestamp("2025-09-24T19:00:00+05:00")
        assert ts.tzinfo.utcoffset(None).total_seconds() == 5 * 3600
    
    def test_parse_iso_timestamp_invalid(self):
        """Test parsing invalid ISO timestamps"""
        with pytest.raises(ValueError):
            parse_iso_timestamp("invalid-timestamp")
        
        with pytest.raises(ValueError):
            parse_iso_timestamp("2025-09-24")  # No time component
    
    def test_validate_time_range(self):
        """Test time range validation"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=24)
        future = now + timedelta(hours=24)
        
        # Valid range
        validate_time_range(past, now)
        
        # Invalid range (from > to)
        with pytest.raises(ValueError, match="before or equal"):
            validate_time_range(now, past)
        
        # Too large span
        far_past = now - timedelta(days=200)
        with pytest.raises(ValueError, match="cannot exceed"):
            validate_time_range(far_past, now)
    
    def test_validate_pollutants(self):
        """Test pollutant validation"""
        # Valid pollutants
        result = validate_pollutants("pm25,pm10")
        assert result == ["pm25", "pm10"]
        
        # Default pollutants
        result = validate_pollutants(None)
        assert "pm25" in result and "pm10" in result
        
        # Invalid pollutant
        with pytest.raises(ValueError, match="Invalid pollutants"):
            validate_pollutants("pm25,invalid")
        
        # Whitespace handling
        result = validate_pollutants(" pm25 , pm10 ")
        assert result == ["pm25", "pm10"]
    
    def test_get_default_time_range(self):
        """Test default time range generation"""
        from_time, to_time = get_default_time_range()
        
        # Should be 48 hours apart
        diff = to_time - from_time
        assert abs(diff.total_seconds() - 48 * 3600) < 60  # Within 1 minute
        
        # Should be rounded to hour
        assert from_time.minute == 0
        assert from_time.second == 0
        assert to_time.minute == 0
        assert to_time.second == 0
    
    def test_generate_hourly_timeline(self):
        """Test hourly timeline generation"""
        start = datetime(2025, 9, 24, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 9, 24, 13, 0, 0, tzinfo=timezone.utc)
        
        timeline = generate_hourly_timeline(start, end)
        
        assert len(timeline) == 4  # 10, 11, 12, 13
        assert timeline[0] == start
        assert timeline[-1] == end
        
        # Check hourly increments
        for i in range(1, len(timeline)):
            diff = timeline[i] - timeline[i-1]
            assert diff.total_seconds() == 3600  # 1 hour


class TestHistoryRouter:
    """Test cases for history endpoints"""
    
    @pytest.mark.asyncio
    async def test_city_history_success(self):
        """Test successful city history request"""
        mock_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual",
            "granularity": "hour",
            "units": {"pm25": "µg/m³", "pm10": "µg/m³", "o3": "ppb", "no2": "ppb", "so2": "ppb", "co": "ppm"},
            "rows": [
                {
                    "ts_utc": "2025-09-24T14:00:00+00:00",
                    "ts_local": "2025-09-24T19:00:00+05:00",
                    "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                    "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                    "weather": {"temp_c": 28, "humidity": 54},
                    "qc_state": "OK"
                }
            ],
            "rollups": None
        }
        
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.return_value = type('MockResponse', (), mock_response)()
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            response = client.get(
                "/api/v1/cities/Pakistan/Punjab/Lahore/history"
                "?from=2025-09-24T10:00:00Z&to=2025-09-24T16:00:00Z"
                "&pollutants=pm25&granularity=hour&aqi=both"
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["scope"]["country"] == "Pakistan"
            assert len(data["rows"]) == 1
    
    @pytest.mark.asyncio
    async def test_city_history_url_encoded(self):
        """Test city history with URL encoded parameters"""
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.return_value = type('MockResponse', (), {
                "scope": {"country": "United States", "state": "New York", "city": "New York City"},
                "source": "airvisual", "granularity": "hour", "units": {}, "rows": [], "rollups": None
            })()
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/United%20States/New%20York/New%20York%20City/history")
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_city_history_default_parameters(self):
        """Test city history with default parameters"""
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.return_value = type('MockResponse', (), {
                "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
                "source": "airvisual", "granularity": "hour", "units": {}, "rows": [], "rollups": None
            })()
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history")
            assert response.status_code == 200
            
            # Service should be called with defaults
            args, kwargs = mock_service.get_city_history.call_args
            query = args[3]  # HistoryQuery parameter
            assert query.granularity == "hour"
            assert query.aqi_mode == "both"
            assert query.tz == "Asia/Karachi"
    
    def test_city_history_invalid_parameters(self):
        """Test city history with invalid parameters"""
        # Invalid granularity
        response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history?granularity=day")
        assert response.status_code == 400
        
        # Invalid AQI mode
        response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history?aqi=invalid")
        assert response.status_code == 400
        
        # Invalid pollutants
        response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history?pollutants=invalid")
        assert response.status_code == 400
        
        # Invalid time range (from > to)
        response = client.get(
            "/api/v1/cities/Pakistan/Punjab/Lahore/history"
            "?from=2025-09-26T10:00:00Z&to=2025-09-24T10:00:00Z"
        )
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_city_history_with_rollups(self):
        """Test city history with rollups enabled"""
        mock_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual", "granularity": "hour", "units": {}, "rows": [],
            "rollups": {
                "window": {
                    "from": "2025-09-24T10:00:00Z",
                    "to": "2025-09-24T16:00:00Z",
                    "count_hours": 5,
                    "missing_hours": 1
                },
                "pm25": {"mean": 35.2, "median": 32.0, "p90": 45.0, "max": 50.0},
                "aqi_us": {"mean": 85, "max": 120}
            }
        }
        
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.return_value = type('MockResponse', (), mock_response)()
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history?include_rollups=true")
            assert response.status_code == 200
            
            data = response.json()
            assert data["rollups"] is not None
            assert data["rollups"]["window"]["count_hours"] == 5
            assert data["rollups"]["pm25"]["mean"] == 35.2
    
    @pytest.mark.asyncio
    async def test_station_history_success(self):
        """Test successful station history request"""
        mock_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual", "granularity": "hour", "units": {}, "rows": [
                {
                    "ts_utc": "2025-09-24T14:00:00+00:00",
                    "ts_local": "2025-09-24T19:00:00+05:00",
                    "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                    "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                    "weather": {"temp_c": 28},
                    "qc_state": "OK"
                }
            ],
            "rollups": None
        }
        
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_station_history.return_value = type('MockResponse', (), mock_response)()
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations/9f1a0c2b8d6e3a41/history")
            assert response.status_code == 200
            
            data = response.json()
            assert data["scope"]["country"] == "Pakistan"
            assert len(data["rows"]) == 1
    
    def test_station_history_invalid_station_id(self):
        """Test station history with invalid station_id format"""
        # Too short
        response = client.get("/api/v1/stations/abc123/history")
        assert response.status_code == 422
        
        # Invalid characters
        response = client.get("/api/v1/stations/xyz123ghij456klmn/history")
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_station_history_not_found(self):
        """Test station history when station not found"""
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_station_history.side_effect = RuntimeError("station_not_found")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations/0123456789abcdef/history")
            assert response.status_code == 404
            assert response.json()["detail"] == "station_not_found"
    
    @pytest.mark.asyncio
    async def test_station_history_plan_limitation(self):
        """Test station history with plan limitation note"""
        mock_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual", "granularity": "hour", "units": {}, "rows": [],
            "rollups": None
        }
        mock_result = type('MockResponse', (), mock_response)()
        mock_result.upstream_note = "station_history_unavailable_on_plan"
        
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_station_history.return_value = mock_result
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations/9f1a0c2b8d6e3a41/history")
            assert response.status_code == 200
            assert response.headers.get("X-Upstream-Note") == "station_history_unavailable_on_plan"
    
    @pytest.mark.asyncio
    async def test_timezone_warning_header(self):
        """Test timezone warning header for invalid timezone"""
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.return_value = type('MockResponse', (), {
                "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
                "source": "airvisual", "granularity": "hour", "units": {}, "rows": [], "rollups": None
            })()
            mock_service.check_timezone_fallback.return_value = True  # Indicate fallback occurred
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history?tz=Invalid/Timezone")
            assert response.status_code == 200
            assert response.headers.get("X-TZ-Warning") == "invalid_tz_fallback_utc"
    
    @pytest.mark.asyncio
    async def test_fill_parameter(self):
        """Test fill parameter functionality"""
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.return_value = type('MockResponse', (), {
                "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
                "source": "airvisual", "granularity": "hour", "units": {}, "rows": [], "rollups": None
            })()
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history?fill=true")
            assert response.status_code == 200
            
            # Check that fill parameter was passed correctly
            args, kwargs = mock_service.get_city_history.call_args
            query = args[3]  # HistoryQuery parameter
            assert query.fill is True
    
    @pytest.mark.asyncio
    async def test_upstream_error_handling(self):
        """Test handling of upstream errors"""
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.side_effect = RuntimeError("Upstream API error")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/history")
            assert response.status_code == 502
            assert "Failed to retrieve city history" in response.json()["detail"]
            assert response.headers.get("upstream_error") == "true"
    
    @pytest.mark.asyncio
    async def test_city_not_found(self):
        """Test city not found error"""
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.side_effect = RuntimeError("city_not_found")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/NonExistent/State/City/history")
            assert response.status_code == 404
            assert response.json()["detail"] == "city_not_found"


class TestHistoryIntegration:
    """Integration tests for complete history flow"""
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_history_flow(self):
        """Test complete history flow for city and station"""
        
        # Mock complete history responses
        mock_city_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual",
            "granularity": "hour",
            "units": {"pm25": "µg/m³", "pm10": "µg/m³", "o3": "ppb", "no2": "ppb", "so2": "ppb", "co": "ppm"},
            "rows": [
                {
                    "ts_utc": "2025-09-24T14:00:00+00:00",
                    "ts_local": "2025-09-24T19:00:00+05:00",
                    "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                    "pollutants": {
                        "pm25": {"conc": 32.6, "unit": "µg/m³"},
                        "pm10": {"conc": 45.2, "unit": "µg/m³"},
                        "o3": None, "no2": None, "so2": None, "co": None
                    },
                    "weather": {"temp_c": 28, "humidity": 54, "pressure_hpa": 1011},
                    "qc_state": "OK"
                }
            ],
            "rollups": {
                "window": {"from": "2025-09-24T10:00:00Z", "to": "2025-09-24T16:00:00Z", 
                          "count_hours": 6, "missing_hours": 0},
                "pm25": {"mean": 35.2, "median": 32.6, "p90": 40.0, "max": 45.0},
                "aqi_us": {"mean": 88, "max": 105}
            }
        }
        
        with patch('app.services.airvisual_history.get_history_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_history.return_value = type('MockResponse', (), mock_city_response)()
            mock_service.get_station_history.return_value = type('MockResponse', (), mock_city_response)()
            mock_service.check_timezone_fallback.return_value = False
            mock_get_service.return_value = mock_service
            
            # Test city history
            city_response = client.get(
                "/api/v1/cities/Pakistan/Punjab/Lahore/history"
                "?from=2025-09-24T10:00:00Z&to=2025-09-24T16:00:00Z"
                "&pollutants=pm25,pm10&include_rollups=true"
            )
            assert city_response.status_code == 200
            city_data = city_response.json()
            assert len(city_data["rows"]) == 1
            assert city_data["rollups"]["pm25"]["mean"] == 35.2
            
            # Test station history
            station_response = client.get(
                "/api/v1/stations/9f1a0c2b8d6e3a41/history"
                "?from=2025-09-24T10:00:00Z&to=2025-09-24T16:00:00Z"
                "&aqi=us&fill=true"
            )
            assert station_response.status_code == 200


class TestHistoryRollups:
    """Test cases for rollups computation"""
    
    def test_rollups_service_basic(self):
        """Test basic rollups computation"""
        from app.services.history_rollups import get_history_rollups_service
        from app.models.history import HistoryRow, HistoryQuery
        from app.models.current import ScalarWithUnit
        
        service = get_history_rollups_service()
        
        # Create mock rows
        rows = []
        for i in range(5):
            row = HistoryRow(
                ts_utc=datetime(2025, 9, 24, 10 + i, 0, 0, tzinfo=timezone.utc),
                ts_local=datetime(2025, 9, 24, 15 + i, 0, 0, tzinfo=timezone.utc),
                aqi={"us": 80 + i * 5, "cn": 60 + i * 3},
                pollutants={"pm25": ScalarWithUnit(conc=30.0 + i * 2, unit="µg/m³")},
                weather={"temp_c": 25 + i},
                qc_state="OK"
            )
            rows.append(row)
        
        # Create mock query
        query = HistoryQuery(
            from_time=datetime(2025, 9, 24, 10, 0, 0, tzinfo=timezone.utc),
            to_time=datetime(2025, 9, 24, 14, 0, 0, tzinfo=timezone.utc),
            pollutants=["pm25"],
            granularity="hour",
            aqi_mode="both",
            tz="UTC",
            fill=False,
            include_rollups=True
        )
        
        rollups = service.compute_rollups(rows, query)
        
        assert rollups is not None
        assert rollups.window.count_hours == 5
        assert rollups.pm25 is not None
        assert rollups.pm25.mean == 34.0  # (30+32+34+36+38)/5
        assert rollups.aqi_us is not None
        assert rollups.aqi_us.mean == 90  # (80+85+90+95+100)/5


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/test_history_router.py -v
    pytest.main([__file__, "-v"])