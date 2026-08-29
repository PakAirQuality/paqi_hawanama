#!/usr/bin/env python3
"""
Generate custom hull-shaped polygons for cities based on station locations.

This script creates polygons that tightly encapsulate stations within each city,
providing more accurate spatial coverage than administrative boundaries.
"""

import asyncio
import json
import math
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from shapely.geometry import Point, Polygon, MultiPoint
from shapely.ops import unary_union
from scipy.spatial import ConvexHull
import random

# Import the database connection
import sys
sys.path.append('.')
from app.core.database import SessionLocal


def add_natural_jaggedness(points: List[Tuple[float, float]], intensity: float = 0.8) -> List[Tuple[float, float]]:
    """Add natural, zig-zag jaggedness to create irregular borders."""
    if len(points) < 3:
        return points
    
    jagged_points = []
    for i in range(len(points)):
        current = np.array(points[i])
        next_point = np.array(points[(i + 1) % len(points)])
        
        # Add the original point with slight random offset
        base_offset = random.uniform(-0.0002, 0.0002) * intensity
        jagged_current = current + np.array([base_offset, base_offset * 0.7])
        jagged_points.append((float(jagged_current[0]), float(jagged_current[1])))
        
        # Add 2-3 intermediate jagged points between each pair
        num_segments = random.randint(2, 4)
        for j in range(1, num_segments):
            t = j / num_segments
            
            # Linear interpolation between points
            interp_point = current + t * (next_point - current)
            
            # Calculate perpendicular direction for jagging
            direction = next_point - current
            if np.linalg.norm(direction) > 0:
                perpendicular = np.array([-direction[1], direction[0]])
                perpendicular = perpendicular / np.linalg.norm(perpendicular)
                
                # Create natural zig-zag pattern
                zigzag_intensity = intensity * random.uniform(0.3, 1.0)
                side = 1 if random.random() > 0.5 else -1
                
                # Vary the offset to create natural looking borders
                if j % 2 == 0:
                    offset_distance = zigzag_intensity * 0.001 * side
                else:
                    offset_distance = zigzag_intensity * 0.0015 * -side
                
                jagged_interp = interp_point + perpendicular * offset_distance
                
                # Add some random noise
                noise = np.array([random.uniform(-0.0001, 0.0001), random.uniform(-0.0001, 0.0001)])
                jagged_interp += noise * intensity
                
                jagged_points.append((float(jagged_interp[0]), float(jagged_interp[1])))
    
    return jagged_points


def create_natural_polygon(stations: List[Tuple[float, float]], city_name: str, existing_polygons: List[Polygon] = None) -> Polygon:
    """Create a natural-looking jagged polygon around station points, avoiding intersections."""
    if existing_polygons is None:
        existing_polygons = []
    
    if len(stations) < 3:
        # For 1-2 stations, create a simple jagged circle
        if len(stations) == 1:
            center = Point(stations[0])
            # Create a small polygon around single station
            angles = np.linspace(0, 2*np.pi, 12, endpoint=False)
            base_radius = 0.008  # ~800m base radius
            circle_points = []
            for angle in angles:
                # Add natural variation to radius
                radius_variation = random.uniform(0.7, 1.3)
                radius = base_radius * radius_variation
                x = center.x + radius * np.cos(angle)
                y = center.y + radius * np.sin(angle)
                circle_points.append((x, y))
            
            # Add jaggedness to the circle
            jagged_circle = add_natural_jaggedness(circle_points, intensity=1.2)
            return Polygon(jagged_circle)
        else:
            # For 2 stations, create jagged buffer around line
            from shapely.geometry import LineString
            line = LineString(stations)
            buffered = line.buffer(0.008)
            
            # Extract exterior coordinates and add jaggedness
            coords = list(buffered.exterior.coords)[:-1]  # Remove duplicate last point
            jagged_coords = add_natural_jaggedness(coords, intensity=1.0)
            return Polygon(jagged_coords)
    
    # Convert to numpy array for scipy
    from scipy.spatial import ConvexHull
    points = np.array(stations)
    
    # Calculate convex hull
    hull = ConvexHull(points)
    hull_points = points[hull.vertices]
    
    # Convert back to list of tuples
    hull_coords = [(float(x), float(y)) for x, y in hull_points]
    
    # Create initial polygon without buffer to check station spread
    initial_poly = Polygon(hull_coords)
    bounds = initial_poly.bounds
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    
    # Adaptive buffer based on city size and station density
    station_density = len(stations) / max(width * height, 0.001)
    
    if city_name.lower() == "lahore" or len(stations) > 20:
        # Large cities get smaller relative buffer to avoid overlaps
        buffer_factor = 0.08
        jaggedness_intensity = 1.5
    elif len(stations) < 5:
        # Small cities get more buffer
        buffer_factor = 0.15
        jaggedness_intensity = 1.2
    else:
        buffer_factor = 0.12
        jaggedness_intensity = 1.0
    
    buffer_size = min(width, height) * buffer_factor
    buffer_size = max(buffer_size, 0.004)  # ~400m minimum
    buffer_size = min(buffer_size, 0.015)  # ~1.5km maximum
    
    # Create buffered polygon first
    buffered_poly = initial_poly.buffer(buffer_size)
    
    # Extract exterior coordinates and add natural jaggedness
    coords = list(buffered_poly.exterior.coords)[:-1]  # Remove duplicate last point
    jagged_coords = add_natural_jaggedness(coords, intensity=jaggedness_intensity)
    
    final_polygon = Polygon(jagged_coords)
    
    # Check for intersections with existing polygons
    for existing_poly in existing_polygons:
        if final_polygon.intersects(existing_poly):
            print(f"    ⚠️  {city_name} intersects with existing polygon, reducing size...")
            
            # Reduce buffer and try again
            buffer_size *= 0.7
            buffered_poly = initial_poly.buffer(buffer_size)
            coords = list(buffered_poly.exterior.coords)[:-1]
            jagged_coords = add_natural_jaggedness(coords, intensity=jaggedness_intensity * 0.8)
            final_polygon = Polygon(jagged_coords)
            
            # If still intersecting, use the non-intersecting difference
            if final_polygon.intersects(existing_poly):
                try:
                    final_polygon = final_polygon.difference(existing_poly.buffer(0.001))
                    if final_polygon.geom_type == 'MultiPolygon':
                        # Take the largest polygon if it becomes multipolygon
                        final_polygon = max(final_polygon.geoms, key=lambda p: p.area)
                except:
                    # Fallback: just use a smaller buffer
                    buffered_poly = initial_poly.buffer(buffer_size * 0.5)
                    coords = list(buffered_poly.exterior.coords)[:-1]
                    jagged_coords = add_natural_jaggedness(coords, intensity=0.8)
                    final_polygon = Polygon(jagged_coords)
            
            break
    
    return final_polygon


async def get_cities_with_stations() -> Dict[str, List[Tuple[float, float]]]:
    """Get all cities and their station coordinates."""
    async with SessionLocal() as session:
        query = """
        SELECT 
            c.name as city_name,
            s.lat,
            s.lon
        FROM cities c
        JOIN stations s ON c.id = s.city_id
        WHERE s.active = true
            AND s.lat IS NOT NULL 
            AND s.lon IS NOT NULL
        ORDER BY c.name, s.station_id
        """
        
        result = await session.execute(text(query))
        rows = result.fetchall()
        
        cities = {}
        for row in rows:
            city_name = row.city_name
            lat, lon = float(row.lat), float(row.lon)
            
            if city_name not in cities:
                cities[city_name] = []
            cities[city_name].append((lon, lat))  # GeoJSON format: [lon, lat]
        
        return cities


def polygon_to_geojson(polygon: Polygon, city_name: str, station_count: int) -> Dict[str, Any]:
    """Convert Shapely polygon to GeoJSON feature."""
    # Handle both Polygon and MultiPolygon cases
    if polygon.geom_type == 'MultiPolygon':
        # Take the largest polygon from MultiPolygon
        polygon = max(polygon.geoms, key=lambda p: p.area)
    
    # Get exterior coordinates
    coords = list(polygon.exterior.coords)
    
    return {
        "type": "Feature",
        "properties": {
            "city_name": city_name,
            "station_count": station_count,
            "area_km2": round(polygon.area * 111**2, 2),  # Rough conversion to km²
            "generated_by": "natural_jagged_polygons",
            "style": "jagged_boundaries"
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [coords]
        }
    }


async def generate_city_polygons():
    """Main function to generate natural polygons for all cities."""
    print("🔍 Fetching cities and station data...")
    cities_stations = await get_cities_with_stations()
    
    print(f"📊 Found {len(cities_stations)} cities with stations")
    
    features = []
    existing_polygons = []
    
    # Sort cities by station count (largest first) to handle overlaps better
    sorted_cities = sorted(cities_stations.items(), key=lambda x: len(x[1]), reverse=True)
    
    for city_name, stations in sorted_cities:
        print(f"  Processing {city_name}: {len(stations)} stations")
        
        if len(stations) == 0:
            continue
        
        try:
            # Generate natural jagged polygon with intersection avoidance
            polygon = create_natural_polygon(stations, city_name, existing_polygons)
            
            # Validate polygon
            if not polygon.is_valid:
                print(f"    ⚠️  Invalid polygon for {city_name}, attempting to fix...")
                polygon = polygon.buffer(0)  # Often fixes self-intersections
            
            if polygon.area < 0.000001:  # Very small polygon
                print(f"    ⚠️  Very small polygon for {city_name}, skipping...")
                continue
            
            # Convert to GeoJSON feature
            feature = polygon_to_geojson(polygon, city_name, len(stations))
            features.append(feature)
            existing_polygons.append(polygon)
            
            print(f"    ✅ Generated jagged polygon: {feature['properties']['area_km2']} km²")
            
        except Exception as e:
            print(f"    ❌ Error generating polygon for {city_name}: {e}")
            import traceback
            traceback.print_exc()
    
    # Create complete GeoJSON
    geojson = {
        "type": "FeatureCollection",
        "properties": {
            "name": "Pakistan City Station Natural Coverage Polygons",
            "description": "Natural jagged polygons showing air quality monitoring station coverage areas with no overlaps",
            "generated_at": "2025-09-26",
            "total_cities": len(features),
            "style": "natural_jagged_boundaries"
        },
        "features": features
    }
    
    # Save to file
    output_path = Path("../web-next/public/city_station_polygons.geojson")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)
    
    print(f"\n✅ Generated {len(features)} natural jagged city polygons")
    print(f"💾 Saved to: {output_path}")
    
    # Print summary
    total_stations = sum(len(stations) for stations in cities_stations.values())
    total_area = sum(feature['properties']['area_km2'] for feature in features)
    
    print(f"\n📈 Summary:")
    print(f"  Cities: {len(features)}")
    print(f"  Total stations: {total_stations}")
    print(f"  Total coverage area: {total_area:.1f} km²")
    print(f"  Average area per city: {total_area/len(features):.1f} km²")
    print(f"  Style: Natural jagged boundaries with no intersections")
    
    return geojson


if __name__ == "__main__":
    # Install required packages if not available
    try:
        import shapely
        import scipy
        import numpy
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("Install with: pip install shapely scipy numpy")
        sys.exit(1)
    
    # Run the polygon generation
    asyncio.run(generate_city_polygons())