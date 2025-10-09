#!/usr/bin/env python3
"""
Test script for the new health and metadata endpoints
"""

import asyncio
import httpx
import json

API_BASE_URL = "http://localhost:8000"

async def test_endpoints():
    """Test all health and metadata endpoints"""
    
    endpoints = [
        "/api/v1/health/",
        "/api/v1/health/db", 
        "/api/v1/health/metrics",
        "/api/v1/meta/aqi-scales",
        "/api/v1/meta/pollutants", 
        "/api/v1/meta/units",
        "/api/v1/meta/aqi-categories"
    ]
    
    print("🧪 Testing Health & Metadata API Endpoints")
    print("=" * 50)
    
    async with httpx.AsyncClient() as client:
        for endpoint in endpoints:
            url = f"{API_BASE_URL}{endpoint}"
            try:
                print(f"\n📍 Testing: {endpoint}")
                response = await client.get(url, timeout=10.0)
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"   ✅ Status: {response.status_code}")
                    
                    # Show key info for each endpoint
                    if "health" in endpoint:
                        if "metrics" in endpoint:
                            stations = data.get("stations", {})
                            print(f"   📊 Stations - Total: {stations.get('total')}, Active 24h: {stations.get('active_24h')}")
                        elif "db" in endpoint:
                            stats = data.get("statistics", {})
                            print(f"   💾 DB - Size: {stats.get('database_size')}, Readings 24h: {stats.get('readings_last_24h')}")
                        else:
                            db_status = data.get("database", {}).get("status", "unknown")
                            print(f"   🏥 Service: {data.get('status')}, DB: {db_status}")
                    
                    elif "meta" in endpoint:
                        if "aqi-scales" in endpoint:
                            scales = data.get("scales", [])
                            print(f"   📏 Available scales: {scales}")
                        elif "pollutants" in endpoint:
                            aliases = data.get("aliases", {})
                            print(f"   🧪 Pollutant aliases: {len(aliases)} defined")
                        elif "units" in endpoint:
                            sections = list(data.keys())
                            print(f"   📐 Unit sections: {sections}")
                        elif "aqi-categories" in endpoint:
                            categories = list(data.get("us_epa", {}).keys())
                            print(f"   🎯 AQI categories: {len(categories)} defined")
                    
                else:
                    print(f"   ❌ Status: {response.status_code}")
                    print(f"   Error: {response.text[:200]}")
                    
            except Exception as e:
                print(f"   💥 Error: {str(e)}")
    
    print("\n" + "=" * 50)
    print("✨ Health & Metadata API Testing Complete!")

if __name__ == "__main__":
    asyncio.run(test_endpoints())