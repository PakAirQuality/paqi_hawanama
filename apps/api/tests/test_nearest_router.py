"""
Tests for Nearest API Router
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.nearest import make_station_id
from app.utils.geo import haversine_km, validate_coordinates, validate_radius

client = TestClient(app)


class TestGeoUtils:
    """Test cases for geographic utilities"""
    
    def test_haversine_distance(self):
        """Test haversine distance calculation"""
        # Test known distance (Lahore to Karachi approximately)
        lahore_lat, lahore_lon = 31.5204, 74.3587
        karachi_lat, karachi_lon = 24.8607, 67.0011
        
        distance = haversine_km(lahore_lat, lahore_lon, karachi_lat, karachi_lon)
        
        # Should be approximately 1000km
        assert 950 <= distance <= 1100
        assert isinstance(distance, float)
    
    def test_haversine_same_point(self):
        """Test haversine distance for same point"""
        distance = haversine_km(31.5204, 74.3587, 31.5204, 74.3587)
        assert distance == 0.0
    
    def test_coordinate_validation(self):
        """Test coordinate validation"""
        # Valid coordinates should not raise
        validate_coordinates(31.5204, 74.3587)
        validate_coordinates(-90, -180)
        validate_coordinates(90, 180)
        
        # Invalid coordinates should raise ValueError
        with pytest.raises(ValueError, match="Latitude must be between"):
            validate_coordinates(91, 0)
        
        with pytest.raises(ValueError, match="Latitude must be between"):
            validate_coordinates(-91, 0)
        
        with pytest.raises(ValueError, match="Longitude must be between"):
            validate_coordinates(0, 181)
        
        with pytest.raises(ValueError, match="Longitude must be between"):
            validate_coordinates(0, -181)
    
    def test_radius_validation(self):
        """Test radius validation and clamping"""
        # Valid radius
        assert validate_radius(50) == 50.0
        
        # Clamping
        assert validate_radius(0.5) == 1.0  # Min clamp
        assert validate_radius(500) == 300.0  # Max clamp
        
        # Invalid radius
        with pytest.raises(ValueError):
            validate_radius(-5)
        
        with pytest.raises(ValueError):
            validate_radius("invalid")


class TestMakeStationId:
    """Test cases for station ID generation"""
    
    def test_deterministic_station_id(self):
        """Test that station ID generation is deterministic"""
        id1 = make_station_id("Pakistan", "Punjab", "Lahore", "US Consulate", 31.520400, 74.358700)
        id2 = make_station_id("Pakistan", "Punjab", "Lahore", "US Consulate", 31.520400, 74.358700)
        
        assert id1 == id2
        assert len(id1) == 16
        assert isinstance(id1, str)
    
    def test_different_stations_different_ids(self):
        """Test that different stations get different IDs"""
        id1 = make_station_id("Pakistan", "Punjab", "Lahore", "US Consulate", 31.520400, 74.358700)
        id2 = make_station_id("Pakistan", "Sindh", "Karachi", "Embassy", 24.860100, 67.001100)
        
        assert id1 != id2
    
    def test_station_id_handles_none_state(self):
        """Test station ID generation with None state"""
        id1 = make_station_id("Pakistan", None, "Lahore", "Station", 31.5204, 74.3587)
        id2 = make_station_id("Pakistan", "", "Lahore", "Station", 31.5204, 74.3587)
        
        assert id1 == id2  # None and empty string should produce same ID
        assert len(id1) == 16


class TestNearestRouter:
    """Test cases for nearest endpoints"""
    
    @pytest.mark.asyncio
    async def test_nearest_city_success(self):
        """Test successful nearest city request"""
        mock_response = {
            "source": "airvisual",
            "distance_km": 4.32,
            "entity": {
                "lat": 31.517,
                "lon": 74.360,
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore"
            },
            "current": {
                "ts_utc": "2025-09-24T14:00:00+00:00",
                "ts_local": "2025-09-24T19:00:00+05:00",
                "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                "weather": {"temp_c": 28, "humidity": 54},
                "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                "qc_state": "OK",
                "units": {"pm25": "µg/m³"}
            }
        }
        
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.return_value = type('MockResponse', (), mock_response)()
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587&radius_km=50")
            
            assert response.status_code == 200
            mock_service.get_nearest_city.assert_called_once_with(
                lat=31.5204, lon=74.3587, radius_km=50.0, aqi_filter="both", tz="Asia/Karachi"
            )
    
    @pytest.mark.asyncio 
    async def test_nearest_station_success(self):
        """Test successful nearest station request"""
        mock_response = {
            "source": "airvisual",
            "distance_km": 2.10,
            "entity": {
                "lat": 31.521,
                "lon": 74.355,
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore",
                "name": "Lahore US Consulate",
                "station_id": "9f1a0c2b8d6e3a41"
            },
            "current": {
                "ts_utc": "2025-09-24T14:00:00+00:00",
                "ts_local": "2025-09-24T19:00:00+05:00",
                "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                "weather": {"temp_c": 28, "humidity": 54},
                "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                "qc_state": "OK",
                "units": {"pm25": "µg/m³"}
            }
        }
        
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_station.return_value = type('MockResponse', (), mock_response)()
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/station?lat=31.5204&lon=74.3587&radius_km=30")
            
            assert response.status_code == 200
            mock_service.get_nearest_station.assert_called_once_with(
                lat=31.5204, lon=74.3587, radius_km=30.0, aqi_filter="both", tz="Asia/Karachi"
            )
    
    def test_invalid_coordinates(self):
        """Test endpoints with invalid coordinates"""
        # Invalid latitude
        response = client.get("/api/v1/nearest/city?lat=91&lon=74.3587")
        assert response.status_code == 422
        
        # Invalid longitude
        response = client.get("/api/v1/nearest/city?lat=31.5204&lon=181")
        assert response.status_code == 422
        
        # Missing coordinates
        response = client.get("/api/v1/nearest/city?lat=31.5204")
        assert response.status_code == 422
    
    def test_radius_parameter_validation(self):
        """Test radius parameter validation"""
        # Valid radius
        response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587&radius_km=100")
        # Should pass validation (actual service call may fail but not due to validation)
        assert response.status_code != 422
        
        # Invalid radius (too small)
        response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587&radius_km=0")
        assert response.status_code == 422
        
        # Invalid radius (too large)
        response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587&radius_km=400")
        assert response.status_code == 422
    
    def test_aqi_parameter(self):
        """Test AQI filter parameter"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.return_value = type('MockResponse', (), {
                "source": "airvisual", "distance_km": 1.0, "entity": {}, "current": {}
            })()
            mock_get_service.return_value = mock_service
            
            # Test different AQI filters
            for aqi_filter in ["us", "cn", "both"]:
                response = client.get(f"/api/v1/nearest/city?lat=31.5204&lon=74.3587&aqi={aqi_filter}")
                assert response.status_code == 200
                
                # Verify the service was called with correct parameter
                mock_service.get_nearest_city.assert_called_with(
                    lat=31.5204, lon=74.3587, radius_km=50.0, aqi_filter=aqi_filter, tz="Asia/Karachi"
                )
    
    def test_timezone_parameter(self):
        """Test timezone parameter"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.return_value = type('MockResponse', (), {
                "source": "airvisual", "distance_km": 1.0, "entity": {}, "current": {}
            })()
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587&tz=UTC")
            assert response.status_code == 200
            
            mock_service.get_nearest_city.assert_called_with(
                lat=31.5204, lon=74.3587, radius_km=50.0, aqi_filter="both", tz="UTC"
            )
    
    @pytest.mark.asyncio
    async def test_nearest_city_not_found(self):
        """Test nearest city when none found within radius"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.side_effect = RuntimeError("no_nearest_city")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587&radius_km=1")
            
            assert response.status_code == 404
            data = response.json()
            assert data["detail"] == "no_nearest_city"
    
    @pytest.mark.asyncio
    async def test_nearest_station_not_found(self):
        """Test nearest station when none found within radius"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_station.side_effect = RuntimeError("no_nearest_station")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/station?lat=31.5204&lon=74.3587&radius_km=1")
            
            assert response.status_code == 404
            data = response.json()
            assert data["detail"] == "no_nearest_station"
    
    @pytest.mark.asyncio
    async def test_nearest_station_plan_upgrade_required(self):
        """Test nearest station when plan upgrade is required"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_station.side_effect = RuntimeError("Nearest station requires plan upgrade")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/station?lat=31.5204&lon=74.3587")
            
            assert response.status_code == 501
            data = response.json()
            assert data["detail"] == "Nearest station requires plan upgrade"
            assert response.headers.get("feature_limitation") == "true"
    
    @pytest.mark.asyncio
    async def test_service_unavailable(self):
        """Test endpoints when service is unavailable"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.side_effect = RuntimeError("client not available")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587")
            
            assert response.status_code == 503
            data = response.json()
            assert "service unavailable" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_upstream_api_error(self):
        """Test handling of upstream API errors"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.side_effect = RuntimeError("Upstream API error: 500 Internal Server Error")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587")
            
            assert response.status_code == 502
            data = response.json()
            assert "Upstream API error" in data["detail"]
            assert response.headers.get("upstream_error") == "true"
    
    @pytest.mark.asyncio
    async def test_parameter_validation_error(self):
        """Test handling of parameter validation errors"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.side_effect = ValueError("Invalid coordinates")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587")
            
            assert response.status_code == 400
            data = response.json()
            assert "Invalid coordinates" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_unexpected_error(self):
        """Test handling of unexpected errors"""
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.side_effect = Exception("Unexpected error")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587")
            
            assert response.status_code == 500
            data = response.json()
            assert data["detail"] == "Internal server error"


class TestNormalizationUtils:
    """Test cases for data normalization utilities"""
    
    def test_timezone_conversion(self):
        """Test timezone conversion utility"""
        from app.utils.normalization import to_local
        
        # Create UTC datetime
        utc_time = datetime(2025, 9, 24, 14, 0, 0, tzinfo=timezone.utc)
        
        # Convert to Karachi time (UTC+5)
        local_time = to_local(utc_time, "Asia/Karachi")
        
        assert local_time.hour == 19  # 14 + 5
        assert str(local_time.tzinfo) == "Asia/Karachi"
    
    def test_invalid_timezone_fallback(self):
        """Test fallback to UTC for invalid timezone"""
        from app.utils.normalization import to_local
        
        utc_time = datetime(2025, 9, 24, 14, 0, 0, tzinfo=timezone.utc)
        local_time = to_local(utc_time, "Invalid/Timezone")
        
        # Should fall back to UTC
        assert local_time.tzinfo == timezone.utc
    
    def test_heat_index_calculation(self):
        """Test heat index calculation"""
        from app.utils.normalization import calculate_heat_index
        
        # Normal temperature - should return original
        heat_index = calculate_heat_index(20.0, 50.0)
        assert heat_index == 20.0
        
        # High temperature and humidity - should calculate heat index
        heat_index = calculate_heat_index(35.0, 80.0)
        assert heat_index is not None
        assert heat_index > 35.0  # Should be higher than actual temperature
        
        # Invalid inputs
        heat_index = calculate_heat_index(None, 50.0)
        assert heat_index is None


class TestIntegrationFlow:
    """Integration test for complete nearest flow"""
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_nearest_flow(self):
        """Test complete nearest city/station discovery flow"""
        
        # Mock complete API responses
        mock_city_response = {
            "source": "airvisual",
            "distance_km": 4.32,
            "entity": {
                "lat": 31.517,
                "lon": 74.360, 
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore"
            },
            "current": {
                "ts_utc": "2025-09-24T14:00:00+00:00",
                "ts_local": "2025-09-24T19:00:00+05:00", 
                "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                "weather": {"temp_c": 28, "humidity": 54, "pressure_hpa": 1011},
                "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                "qc_state": "OK",
                "units": {"pm25": "µg/m³"}
            }
        }
        
        with patch('app.services.airvisual_nearest.get_nearest_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_nearest_city.return_value = type('MockResponse', (), mock_city_response)()
            mock_service.get_nearest_station.return_value = type('MockResponse', (), {
                **mock_city_response,
                "entity": {
                    **mock_city_response["entity"],
                    "name": "Lahore US Consulate", 
                    "station_id": "test_station_id"
                }
            })()
            mock_get_service.return_value = mock_service
            
            # Test nearest city
            city_response = client.get("/api/v1/nearest/city?lat=31.5204&lon=74.3587&radius_km=50&aqi=both&tz=Asia/Karachi")
            assert city_response.status_code == 200
            
            # Test nearest station
            station_response = client.get("/api/v1/nearest/station?lat=31.5204&lon=74.3587&radius_km=30&aqi=us&tz=UTC")
            assert station_response.status_code == 200
            
            # Verify service calls
            mock_service.get_nearest_city.assert_called_with(
                lat=31.5204, lon=74.3587, radius_km=50.0, aqi_filter="both", tz="Asia/Karachi"
            )
            mock_service.get_nearest_station.assert_called_with(
                lat=31.5204, lon=74.3587, radius_km=30.0, aqi_filter="us", tz="UTC"
            )


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/test_nearest_router.py -v
    pytest.main([__file__, "-v"])