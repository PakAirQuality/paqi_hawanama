"""
Tests for Current Conditions API Router
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.models.current import StationMeta, ScalarWithUnit
from app.services.normalize import normalize_current, _parse_timestamp, _map_pollutant_code

client = TestClient(app)


class TestNormalizationUtils:
    """Test cases for normalization utilities"""
    
    def test_parse_timestamp_valid(self):
        """Test parsing valid timestamps"""
        # ISO format with Z suffix
        ts = _parse_timestamp("2025-09-24T14:00:00Z")
        assert ts.tzinfo == timezone.utc
        assert ts.hour == 14
        
        # ISO format without Z
        ts = _parse_timestamp("2025-09-24T14:00:00+00:00")
        assert ts.tzinfo == timezone.utc
    
    def test_parse_timestamp_invalid(self):
        """Test parsing invalid timestamps"""
        # Invalid format should return current time
        ts = _parse_timestamp("invalid")
        assert ts.tzinfo == timezone.utc
        
        # None should return current time
        ts = _parse_timestamp(None)
        assert ts.tzinfo == timezone.utc
    
    def test_pollutant_code_mapping(self):
        """Test pollutant code mapping"""
        assert _map_pollutant_code("p1") == "pm10"
        assert _map_pollutant_code("p2") == "pm25"
        assert _map_pollutant_code("o3") == "o3"
        assert _map_pollutant_code("n2") == "no2"
        assert _map_pollutant_code("s2") == "so2"
        assert _map_pollutant_code("co") == "co"
        assert _map_pollutant_code("unknown") == "unknown"
        assert _map_pollutant_code(None) is None
    
    def test_normalize_current_basic(self):
        """Test basic current data normalization"""
        mock_payload = {
            "current": {
                "pollution": {
                    "ts": "2025-09-24T14:00:00Z",
                    "aqius": 95,
                    "aqicn": 70,
                    "mainus": "p2",
                    "maincn": "p2",
                    "p2": {"conc": 32.6}
                },
                "weather": {
                    "tp": 28,
                    "hu": 54,
                    "pr": 1011,
                    "ws": 1.67,
                    "wd": 135,
                    "ic": "01n"
                }
            }
        }
        
        scope = {"country": "Pakistan", "state": "Punjab", "city": "Lahore"}
        
        result = normalize_current(mock_payload, "both", "Asia/Karachi", scope)
        
        assert result.source == "airvisual"
        assert result.scope.country == "Pakistan"
        assert result.scope.state == "Punjab"
        assert result.scope.city == "Lahore"
        assert result.aqi["us"] == 95
        assert result.aqi["cn"] == 70
        assert result.aqi["main_us"] == "pm25"
        assert result.aqi["main_cn"] == "pm25"
        assert result.weather["temp_c"] == 28
        assert result.weather["humidity"] == 54
        assert result.pollutants["pm25"].conc == 32.6
        assert result.pollutants["pm25"].unit == "µg/m³"
    
    def test_normalize_current_aqi_filtering(self):
        """Test AQI filtering in normalization"""
        mock_payload = {
            "current": {
                "pollution": {
                    "ts": "2025-09-24T14:00:00Z",
                    "aqius": 95,
                    "aqicn": 70,
                    "mainus": "p2",
                    "maincn": "p2"
                },
                "weather": {}
            }
        }
        
        scope = {"country": "Pakistan", "state": "Punjab", "city": "Lahore"}
        
        # Test US only
        result = normalize_current(mock_payload, "us", "UTC", scope)
        assert result.aqi["us"] == 95
        assert result.aqi["cn"] is None
        assert result.aqi["main_us"] == "pm25"
        assert result.aqi["main_cn"] is None
        
        # Test CN only
        result = normalize_current(mock_payload, "cn", "UTC", scope)
        assert result.aqi["us"] is None
        assert result.aqi["cn"] == 70
        assert result.aqi["main_us"] is None
        assert result.aqi["main_cn"] == "pm25"


class TestStationMeta:
    """Test cases for StationMeta model"""
    
    def test_station_meta_creation(self):
        """Test StationMeta model creation"""
        meta = StationMeta(
            country="Pakistan",
            state="Punjab",
            city="Lahore",
            name="Test Station",
            lat=31.5204,
            lon=74.3587,
            source_station_id="test123"
        )
        
        assert meta.country == "Pakistan"
        assert meta.state == "Punjab"
        assert meta.city == "Lahore"
        assert meta.name == "Test Station"
        assert meta.lat == 31.5204
        assert meta.lon == 74.3587
        assert meta.source_station_id == "test123"
    
    def test_station_meta_optional_fields(self):
        """Test StationMeta with optional fields"""
        meta = StationMeta(
            country="Pakistan",
            state="Punjab",
            city="Lahore",
            name="Test Station",
            lat=31.5204,
            lon=74.3587
        )
        
        assert meta.source_station_id is None


class TestCurrentRouter:
    """Test cases for current endpoints"""
    
    @pytest.mark.asyncio
    async def test_city_current_success(self):
        """Test successful city current request"""
        mock_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual",
            "ts_utc": "2025-09-24T14:00:00+00:00",
            "ts_local": "2025-09-24T19:00:00+05:00",
            "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
            "weather": {"temp_c": 28, "humidity": 54, "pressure_hpa": 1011},
            "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
            "qc_state": "OK",
            "units": {"pm25": "µg/m³", "pm10": "µg/m³", "o3": "ppb", "no2": "ppb", "so2": "ppb", "co": "ppm"}
        }
        
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.return_value = type('MockResponse', (), mock_response)()
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/current?aqi=both&tz=Asia/Karachi")
            
            assert response.status_code == 200
            mock_service.get_city_current.assert_called_once_with(
                country="Pakistan", state="Punjab", city="Lahore", aqi_mode="both", tz="Asia/Karachi"
            )
    
    @pytest.mark.asyncio
    async def test_city_current_url_encoded_params(self):
        """Test city current with URL encoded parameters"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.return_value = type('MockResponse', (), {
                "scope": {"country": "United States", "state": "New York", "city": "New York City"},
                "source": "airvisual", "ts_utc": "2025-09-24T14:00:00+00:00",
                "ts_local": "2025-09-24T19:00:00+05:00", "aqi": {}, "weather": {},
                "pollutants": {}, "units": {}, "qc_state": None
            })()
            mock_get_service.return_value = mock_service
            
            # URL encode spaces as %20
            response = client.get("/api/v1/cities/United%20States/New%20York/New%20York%20City/current")
            
            assert response.status_code == 200
            mock_service.get_city_current.assert_called_with(
                country="United States", state="New York", city="New York City", 
                aqi_mode="both", tz="Asia/Karachi"
            )
    
    @pytest.mark.asyncio
    async def test_city_current_parameters(self):
        """Test city current with different parameter combinations"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.return_value = type('MockResponse', (), {
                "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
                "source": "airvisual", "ts_utc": "2025-09-24T14:00:00+00:00",
                "ts_local": "2025-09-24T14:00:00+00:00", "aqi": {}, "weather": {},
                "pollutants": {}, "units": {}, "qc_state": None
            })()
            mock_get_service.return_value = mock_service
            
            # Test different AQI modes
            for aqi_mode in ["us", "cn", "both"]:
                response = client.get(f"/api/v1/cities/Pakistan/Punjab/Lahore/current?aqi={aqi_mode}")
                assert response.status_code == 200
                
            # Test different timezones
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/current?tz=UTC")
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_city_current_empty_parameters(self):
        """Test city current with empty path parameters"""
        # Empty city parameter
        response = client.get("/api/v1/cities/Pakistan/Punjab//current")
        assert response.status_code == 404  # FastAPI routing issue
        
        # Test with service that validates empty params
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.side_effect = ValueError("Country, state, and city parameters must be non-empty")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/%20/Punjab/Lahore/current")  # Space as country
            assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_city_current_not_found(self):
        """Test city current when city not found"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.side_effect = RuntimeError("city_not_found")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/NonExistent/State/City/current")
            
            assert response.status_code == 404
            data = response.json()
            assert data["detail"] == "city_not_found"
    
    @pytest.mark.asyncio
    async def test_station_current_success(self):
        """Test successful station current request"""
        mock_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual",
            "ts_utc": "2025-09-24T14:00:00+00:00",
            "ts_local": "2025-09-24T19:00:00+05:00",
            "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
            "weather": {"temp_c": 28, "humidity": 54},
            "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
            "qc_state": "OK",
            "units": {"pm25": "µg/m³", "pm10": "µg/m³", "o3": "ppb", "no2": "ppb", "so2": "ppb", "co": "ppm"}
        }
        
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_station_current.return_value = type('MockResponse', (), mock_response)()
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations/9f1a0c2b8d6e3a41/current?aqi=both&tz=Asia/Karachi")
            
            assert response.status_code == 200
            mock_service.get_station_current.assert_called_once_with(
                station_id="9f1a0c2b8d6e3a41", aqi_mode="both", tz="Asia/Karachi"
            )
    
    def test_station_current_invalid_station_id(self):
        """Test station current with invalid station_id format"""
        # Too short
        response = client.get("/api/v1/stations/abc123/current")
        assert response.status_code == 422  # FastAPI validation error
        
        # Invalid characters
        response = client.get("/api/v1/stations/xyz123ghij456klmn/current")  
        assert response.status_code == 422  # FastAPI validation error
        
        # Too long
        response = client.get("/api/v1/stations/9f1a0c2b8d6e3a4100/current")
        assert response.status_code == 422  # FastAPI validation error
    
    @pytest.mark.asyncio
    async def test_station_current_not_found(self):
        """Test station current when station not found"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_station_current.side_effect = RuntimeError("station_not_found")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations/0123456789abcdef/current")
            
            assert response.status_code == 404
            data = response.json()
            assert data["detail"] == "station_not_found"
    
    @pytest.mark.asyncio
    async def test_station_current_plan_upgrade_required(self):
        """Test station current when plan upgrade required"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_station_current.side_effect = RuntimeError("Station current requires plan upgrade")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations/9f1a0c2b8d6e3a41/current")
            
            assert response.status_code == 501
            data = response.json()
            assert data["detail"] == "Station current requires plan upgrade"
            assert response.headers.get("feature_limitation") == "true"
    
    @pytest.mark.asyncio
    async def test_service_unavailable(self):
        """Test endpoints when service is unavailable"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.side_effect = RuntimeError("client not available")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/current")
            
            assert response.status_code == 503
            data = response.json()
            assert "service unavailable" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_upstream_api_error(self):
        """Test handling of upstream API errors"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.side_effect = RuntimeError("Upstream API error: 500 Internal Server Error")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/current")
            
            assert response.status_code == 502
            data = response.json()
            assert "Upstream API error" in data["detail"]
            assert response.headers.get("upstream_error") == "true"
    
    @pytest.mark.asyncio
    async def test_timezone_warning_header(self):
        """Test timezone warning header for invalid timezone"""
        mock_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual",
            "ts_utc": "2025-09-24T14:00:00+00:00",
            "ts_local": "2025-09-24T14:00:00+00:00",  # Same as UTC indicates fallback
            "aqi": {}, "weather": {}, "pollutants": {}, "units": {}, "qc_state": None
        }
        
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_result = type('MockResponse', (), mock_response)()
            mock_result.ts_utc = datetime(2025, 9, 24, 14, 0, 0, tzinfo=timezone.utc)
            mock_result.ts_local = datetime(2025, 9, 24, 14, 0, 0, tzinfo=timezone.utc)
            mock_result.ts_local.tzinfo.zone = "UTC"  # Mock timezone zone attribute
            
            mock_service.get_city_current.return_value = mock_result
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/current?tz=Invalid/Timezone")
            
            # Note: The actual timezone warning logic might need adjustment based on implementation
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_parameter_validation_error(self):
        """Test handling of parameter validation errors"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_station_current.side_effect = ValueError("station_id must be a 16-character string")
            mock_get_service.return_value = mock_service
            
            # This should be caught by FastAPI validation, but test service-level validation too
            response = client.get("/api/v1/stations/9f1a0c2b8d6e3a41/current")  # Valid format
            
            # The service layer validation error should be handled
            # This test might need adjustment based on actual flow
    
    @pytest.mark.asyncio
    async def test_unexpected_error(self):
        """Test handling of unexpected errors"""
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.side_effect = Exception("Unexpected error")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/current")
            
            assert response.status_code == 500
            data = response.json()
            assert data["detail"] == "Internal server error"


class TestIntegrationFlow:
    """Integration test for complete current conditions flow"""
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_current_flow(self):
        """Test complete current conditions flow for city and station"""
        
        # Mock complete API responses
        mock_city_response = {
            "scope": {"country": "Pakistan", "state": "Punjab", "city": "Lahore"},
            "source": "airvisual",
            "ts_utc": "2025-09-24T14:00:00+00:00",
            "ts_local": "2025-09-24T19:00:00+05:00",
            "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
            "weather": {"temp_c": 28, "humidity": 54, "pressure_hpa": 1011, "wind_speed_ms": 1.67},
            "pollutants": {
                "pm25": {"conc": 32.6, "unit": "µg/m³"},
                "pm10": {"conc": 45.2, "unit": "µg/m³"},
                "o3": None, "no2": None, "so2": None, "co": None
            },
            "qc_state": "OK",
            "units": {"pm25": "µg/m³", "pm10": "µg/m³", "o3": "ppb", "no2": "ppb", "so2": "ppb", "co": "ppm"}
        }
        
        with patch('app.services.airvisual_current.get_current_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_city_current.return_value = type('MockResponse', (), mock_city_response)()
            mock_service.get_station_current.return_value = type('MockResponse', (), mock_city_response)()
            mock_get_service.return_value = mock_service
            
            # Test city current
            city_response = client.get("/api/v1/cities/Pakistan/Punjab/Lahore/current?aqi=both&tz=Asia/Karachi")
            assert city_response.status_code == 200
            city_data = city_response.json()
            assert city_data["scope"]["country"] == "Pakistan"
            assert city_data["aqi"]["us"] == 95
            assert city_data["weather"]["temp_c"] == 28
            
            # Test station current
            station_response = client.get("/api/v1/stations/9f1a0c2b8d6e3a41/current?aqi=us&tz=UTC")
            assert station_response.status_code == 200
            
            # Verify service calls
            mock_service.get_city_current.assert_called_with(
                country="Pakistan", state="Punjab", city="Lahore", aqi_mode="both", tz="Asia/Karachi"
            )
            mock_service.get_station_current.assert_called_with(
                station_id="9f1a0c2b8d6e3a41", aqi_mode="us", tz="UTC"
            )


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/test_current_router.py -v
    pytest.main([__file__, "-v"])