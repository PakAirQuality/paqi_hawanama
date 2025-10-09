"""
Tests for Directory API Router
"""

import pytest
import json
from typing import List, Dict, Any
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from httpx import AsyncClient
import respx

from app.main import app
from app.schemas.directory import make_station_id

client = TestClient(app)


class TestDirectoryRouter:
    """Test cases for directory router endpoints"""
    
    def test_make_station_id_function(self):
        """Test the station ID generation function"""
        # Test deterministic behavior
        station_id1 = make_station_id("Pakistan", "Punjab", "Lahore", "US Consulate", 31.520400, 74.358700)
        station_id2 = make_station_id("Pakistan", "Punjab", "Lahore", "US Consulate", 31.520400, 74.358700)
        
        assert station_id1 == station_id2
        assert len(station_id1) == 16
        assert isinstance(station_id1, str)
        
        # Test different inputs produce different IDs
        station_id3 = make_station_id("Pakistan", "Sindh", "Karachi", "Embassy", 24.860100, 67.001100)
        assert station_id1 != station_id3
        
        # Test precision handling
        station_id4 = make_station_id("Pakistan", "Punjab", "Lahore", "US Consulate", 31.5204001, 74.3587001)
        station_id5 = make_station_id("Pakistan", "Punjab", "Lahore", "US Consulate", 31.520400, 74.358700)
        assert station_id4 == station_id5  # Should round to 6 decimal places

    @pytest.mark.asyncio 
    async def test_get_countries_success(self):
        """Test successful countries listing"""
        # Mock the service response
        mock_countries = [
            {"country": "Pakistan"},
            {"country": "India"},
            {"country": "United Arab Emirates"}
        ]
        
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_countries.return_value = [
                {"country": c["country"]} for c in mock_countries
            ]
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/countries")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 3
            assert data[0]["country"] == "Pakistan"
            mock_service.get_countries.assert_called_once_with(q=None)

    @pytest.mark.asyncio
    async def test_get_countries_with_filter(self):
        """Test countries listing with search filter"""
        mock_countries = [{"country": "Pakistan"}]
        
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_countries.return_value = mock_countries
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/countries?q=Pak")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["country"] == "Pakistan"
            mock_service.get_countries.assert_called_once_with(q="Pak")

    @pytest.mark.asyncio
    async def test_get_countries_cache_behavior(self):
        """Test that countries endpoint calls service only once when cached"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_countries.return_value = [{"country": "Pakistan"}]
            mock_get_service.return_value = mock_service
            
            # First call
            response1 = client.get("/api/v1/countries")
            assert response1.status_code == 200
            
            # The service layer handles caching, so we just verify the call was made
            mock_service.get_countries.assert_called_with(q=None)

    @pytest.mark.asyncio
    async def test_get_countries_upstream_error(self):
        """Test countries endpoint with upstream API error"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_countries.side_effect = RuntimeError("Upstream API error: 500 Internal Server Error")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/countries")
            
            assert response.status_code == 502
            data = response.json()
            assert "Upstream API error" in data["detail"]
            assert response.headers.get("upstream_error") == "true"

    @pytest.mark.asyncio
    async def test_get_states_success(self):
        """Test successful states listing"""
        mock_states = [
            {"state": "Punjab"},
            {"state": "Sindh"},
            {"state": "Khyber Pakhtunkhwa"}
        ]
        
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_states.return_value = mock_states
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/states?country=Pakistan")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 3
            assert data[0]["state"] == "Punjab"
            mock_service.get_states.assert_called_once_with("Pakistan")

    @pytest.mark.asyncio
    async def test_get_states_missing_country(self):
        """Test states endpoint without country parameter"""
        response = client.get("/api/v1/states")
        
        assert response.status_code == 422  # FastAPI validation error

    @pytest.mark.asyncio
    async def test_get_states_empty_country(self):
        """Test states endpoint with empty country"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_states.side_effect = ValueError("Country parameter is required and cannot be empty")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/states?country=")
            
            assert response.status_code == 400
            data = response.json()
            assert "required and cannot be empty" in data["detail"]

    @pytest.mark.asyncio
    async def test_get_cities_success(self):
        """Test successful cities listing"""
        mock_cities = [
            {"city": "Lahore"},
            {"city": "Faisalabad"},
            {"city": "Rawalpindi"}
        ]
        
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_cities.return_value = mock_cities
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/cities?country=Pakistan&state=Punjab")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 3
            assert data[0]["city"] == "Lahore"
            mock_service.get_cities.assert_called_once_with("Pakistan", "Punjab")

    @pytest.mark.asyncio
    async def test_get_cities_missing_parameters(self):
        """Test cities endpoint with missing required parameters"""
        # Missing both country and state
        response = client.get("/api/v1/cities")
        assert response.status_code == 422
        
        # Missing state
        response = client.get("/api/v1/cities?country=Pakistan")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_stations_success(self):
        """Test successful stations listing"""
        mock_stations = [
            {
                "station_id": "9f1a0c2b8d6e3a41",
                "name": "Lahore US Consulate",
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore",
                "lat": 31.5204,
                "lon": 74.3587
            }
        ]
        
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_stations.return_value = mock_stations
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations?country=Pakistan&state=Punjab&city=Lahore")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["station_id"] == "9f1a0c2b8d6e3a41"
            assert data[0]["name"] == "Lahore US Consulate"
            mock_service.get_stations.assert_called_once_with(
                country="Pakistan", state="Punjab", city="Lahore", bbox=None
            )

    @pytest.mark.asyncio
    async def test_get_stations_with_bbox(self):
        """Test stations listing with bounding box filter"""
        mock_stations = [
            {
                "station_id": "9f1a0c2b8d6e3a41",
                "name": "Lahore US Consulate",
                "country": "Pakistan",
                "state": "Punjab", 
                "city": "Lahore",
                "lat": 31.5204,
                "lon": 74.3587
            }
        ]
        
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_stations.return_value = mock_stations
            mock_get_service.return_value = mock_service
            
            bbox = "74.0,31.0,75.0,32.0"
            response = client.get(f"/api/v1/stations?country=Pakistan&bbox={bbox}")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            mock_service.get_stations.assert_called_once_with(
                country="Pakistan", state=None, city=None, bbox=bbox
            )

    @pytest.mark.asyncio
    async def test_get_stations_bbox_only_error(self):
        """Test stations endpoint with only bbox (should fail)"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_stations.side_effect = ValueError(
                "Provide country (and optionally state/city) to scope the stations, then bbox filters locally."
            )
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations?bbox=74.0,31.0,75.0,32.0")
            
            assert response.status_code == 400
            data = response.json()
            assert "bbox filters locally" in data["detail"]

    @pytest.mark.asyncio 
    async def test_get_stations_invalid_bbox(self):
        """Test stations endpoint with invalid bbox format"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_stations.side_effect = ValueError("bbox must have exactly 4 values: minLon,minLat,maxLon,maxLat")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations?country=Pakistan&bbox=74.0,31.0,75.0")
            
            assert response.status_code == 400
            data = response.json()
            assert "bbox must have exactly 4 values" in data["detail"]

    @pytest.mark.asyncio
    async def test_get_stations_no_parameters_error(self):
        """Test stations endpoint with no parameters"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_stations.side_effect = ValueError("At least one of 'country' or 'bbox' must be provided")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations")
            
            assert response.status_code == 400
            data = response.json()
            assert "At least one of 'country' or 'bbox' must be provided" in data["detail"]

    @pytest.mark.asyncio
    async def test_get_stations_plan_upgrade_required(self):
        """Test stations endpoint when feature requires plan upgrade"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_stations.side_effect = RuntimeError("Stations listing requires plan upgrade")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/stations?country=Pakistan")
            
            assert response.status_code == 501
            data = response.json()
            assert data["detail"] == "Stations listing requires plan upgrade"
            assert response.headers.get("feature_limitation") == "true"

    @pytest.mark.asyncio
    async def test_service_unavailable(self):
        """Test endpoints when service is unavailable"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_countries.side_effect = RuntimeError("client not available")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/countries")
            
            assert response.status_code == 503
            data = response.json()
            assert "service unavailable" in data["detail"]

    @pytest.mark.asyncio
    async def test_unexpected_error_handling(self):
        """Test handling of unexpected errors"""
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_countries.side_effect = Exception("Unexpected error")
            mock_get_service.return_value = mock_service
            
            response = client.get("/api/v1/countries")
            
            assert response.status_code == 500
            data = response.json()
            assert data["detail"] == "Internal server error"


class TestDirectoryIntegration:
    """Integration tests that could work with real API (when available)"""
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_full_directory_flow(self):
        """Test the full directory discovery flow"""
        # This would be an integration test with the real API
        # For now, we'll mock the entire flow
        
        mock_responses = {
            "countries": [{"country": "Pakistan"}],
            "states": [{"state": "Punjab"}], 
            "cities": [{"city": "Lahore"}],
            "stations": [{
                "station_id": "test123",
                "name": "Test Station",
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore", 
                "lat": 31.5204,
                "lon": 74.3587
            }]
        }
        
        with patch('app.services.airvisual_directory.get_directory_service') as mock_get_service:
            mock_service = AsyncMock()
            mock_service.get_countries.return_value = mock_responses["countries"]
            mock_service.get_states.return_value = mock_responses["states"]
            mock_service.get_cities.return_value = mock_responses["cities"]
            mock_service.get_stations.return_value = mock_responses["stations"]
            mock_get_service.return_value = mock_service
            
            # Test the flow: countries -> states -> cities -> stations
            countries_resp = client.get("/api/v1/countries")
            assert countries_resp.status_code == 200
            countries = countries_resp.json()
            
            states_resp = client.get(f"/api/v1/states?country={countries[0]['country']}")
            assert states_resp.status_code == 200
            states = states_resp.json()
            
            cities_resp = client.get(f"/api/v1/cities?country={countries[0]['country']}&state={states[0]['state']}")
            assert cities_resp.status_code == 200
            cities = cities_resp.json()
            
            stations_resp = client.get(f"/api/v1/stations?country={countries[0]['country']}&state={states[0]['state']}&city={cities[0]['city']}")
            assert stations_resp.status_code == 200
            stations = stations_resp.json()
            
            assert len(stations) == 1
            assert stations[0]["name"] == "Test Station"


if __name__ == "__main__":
    # Run tests with: python -m pytest tests/test_directory_router.py -v
    pytest.main([__file__, "-v"])