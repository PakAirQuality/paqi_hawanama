#!/usr/bin/env python3
"""
WorldPop K-means Clustering for City Boundaries

This script processes WorldPop population density data to create city boundaries
using k-means clustering around high-density population areas.
"""

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import from_bounds
import geopandas as gpd
from shapely.geometry import Point, Polygon
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import json
import argparse
from scipy.spatial import ConvexHull
from shapely.ops import unary_union
import warnings
warnings.filterwarnings('ignore')

# Major cities with approximate center coordinates and search radius
MAJOR_CITIES = {
    'Karachi': {'lat': 24.8607, 'lon': 67.0011, 'radius_km': 50},
    'Lahore': {'lat': 31.5204, 'lon': 74.3587, 'radius_km': 40}, 
    'Faisalabad': {'lat': 31.4504, 'lon': 73.1350, 'radius_km': 30},
    'Rawalpindi': {'lat': 33.5651, 'lon': 73.0169, 'radius_km': 25},
    'Islamabad': {'lat': 33.6844, 'lon': 73.0479, 'radius_km': 25},
    'Peshawar': {'lat': 34.0151, 'lon': 71.5249, 'radius_km': 30}
}

def load_worldpop_data(tiff_path):
    """Load WorldPop raster data"""
    print(f"📊 Loading WorldPop data from {tiff_path}")
    
    with rasterio.open(tiff_path) as src:
        # Read metadata
        transform = src.transform
        crs = src.crs
        bounds = src.bounds
        
        print(f"📏 Raster info: {src.width}x{src.height}, CRS: {crs}")
        print(f"📍 Bounds: {bounds}")
        
        # Read the data
        population = src.read(1)
        
        # Handle nodata values
        nodata = src.nodata
        if nodata is not None:
            population[population == nodata] = 0
            
        return population, transform, crs, bounds

def get_city_window(city_info, transform, bounds, buffer_km=None):
    """Get a raster window around a city center"""
    lat, lon = city_info['lat'], city_info['lon']
    radius = buffer_km or city_info['radius_km']
    
    # Convert km to degrees (approximately)
    radius_deg = radius / 111.0  # 1 degree ≈ 111 km
    
    # Calculate bounding box
    min_lon = lon - radius_deg
    max_lon = lon + radius_deg
    min_lat = lat - radius_deg
    max_lat = lat + radius_deg
    
    # Convert to pixel coordinates
    ul_col, ul_row = ~transform * (min_lon, max_lat)
    lr_col, lr_row = ~transform * (max_lon, min_lat)
    
    # Ensure coordinates are integers and within bounds
    ul_col, ul_row = max(0, int(ul_col)), max(0, int(ul_row))
    lr_col, lr_row = int(lr_col), int(lr_row)
    
    width = lr_col - ul_col
    height = lr_row - ul_row
    
    return Window(ul_col, ul_row, width, height), (min_lon, min_lat, max_lon, max_lat)

def extract_city_population(population, transform, city_name, city_info):
    """Extract population data for a specific city"""
    print(f"🏙️ Processing {city_name}")
    
    # Get window around city
    window, bbox = get_city_window(city_info, transform, None)
    
    # Extract population data for this window
    row_start, row_end = window.row_off, window.row_off + window.height
    col_start, col_end = window.col_off, window.col_off + window.width
    
    # Ensure we don't go out of bounds
    row_start = max(0, row_start)
    col_start = max(0, col_start)
    row_end = min(population.shape[0], row_end)
    col_end = min(population.shape[1], col_end)
    
    city_pop = population[row_start:row_end, col_start:col_end]
    
    print(f"📦 Extracted {city_pop.shape} window for {city_name}")
    print(f"📊 Population stats: min={city_pop.min():.1f}, max={city_pop.max():.1f}, mean={city_pop.mean():.1f}")
    
    return city_pop, window, bbox

def perform_kmeans_clustering(city_pop, window, transform, n_clusters=8, density_threshold_percentile=75):
    """Perform k-means clustering on population density data"""
    
    # Create coordinate arrays
    rows, cols = np.mgrid[0:city_pop.shape[0], 0:city_pop.shape[1]]
    
    # Only use pixels with significant population
    threshold = np.percentile(city_pop[city_pop > 0], density_threshold_percentile) if np.any(city_pop > 0) else 0
    mask = city_pop > threshold
    
    if not np.any(mask):
        print(f"⚠️ No high-density areas found above threshold {threshold}")
        return None, None
    
    # Prepare data for clustering
    high_density_coords = np.column_stack([
        rows[mask].ravel(),
        cols[mask].ravel(),
        city_pop[mask].ravel()
    ])
    
    print(f"🎯 Found {len(high_density_coords)} high-density pixels for clustering")
    
    # Normalize features
    scaler = StandardScaler()
    # Weight coordinates more heavily than population for spatial clustering
    features = np.column_stack([
        high_density_coords[:, 0] * 2,  # row coordinate
        high_density_coords[:, 1] * 2,  # col coordinate  
        high_density_coords[:, 2] / high_density_coords[:, 2].max()  # normalized population
    ])
    
    features_scaled = scaler.fit_transform(features)
    
    # Perform k-means clustering
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    cluster_labels = kmeans.fit_predict(features_scaled)
    
    return cluster_labels, high_density_coords

def create_cluster_polygons(cluster_labels, high_density_coords, window, transform, min_cluster_size=50):
    """Create polygons from clusters"""
    
    polygons = []
    cluster_info = []
    
    for cluster_id in np.unique(cluster_labels):
        cluster_mask = cluster_labels == cluster_id
        cluster_coords = high_density_coords[cluster_mask]
        
        if len(cluster_coords) < min_cluster_size:
            continue
            
        # Convert pixel coordinates to geographic coordinates
        rows = cluster_coords[:, 0] + window.row_off
        cols = cluster_coords[:, 1] + window.col_off
        
        # Convert to lon/lat
        lons, lats = rasterio.transform.xy(transform, rows, cols)
        points = np.column_stack([lons, lats])
        
        # Create convex hull
        if len(points) >= 3:
            try:
                hull = ConvexHull(points)
                hull_points = points[hull.vertices]
                polygon = Polygon(hull_points)
                
                # Calculate cluster statistics
                pop_sum = cluster_coords[:, 2].sum()
                pop_mean = cluster_coords[:, 2].mean()
                
                polygons.append(polygon)
                cluster_info.append({
                    'cluster_id': int(cluster_id),
                    'point_count': len(cluster_coords),
                    'population_sum': float(pop_sum),
                    'population_mean': float(pop_mean),
                    'area_pixels': len(cluster_coords)
                })
                
                print(f"🔷 Cluster {cluster_id}: {len(cluster_coords)} pixels, pop_sum={pop_sum:.0f}")
                
            except Exception as e:
                print(f"⚠️ Failed to create polygon for cluster {cluster_id}: {e}")
                continue
    
    return polygons, cluster_info

def merge_nearby_clusters(polygons, cluster_info, max_distance_deg=0.01):
    """Merge nearby cluster polygons"""
    if len(polygons) <= 1:
        return polygons, cluster_info
    
    # Simple approach: merge all polygons into one union
    try:
        merged_polygon = unary_union(polygons)
        
        # If result is MultiPolygon, take the largest polygon
        if hasattr(merged_polygon, 'geoms'):
            largest_poly = max(merged_polygon.geoms, key=lambda p: p.area)
            merged_polygon = largest_poly
        
        # Combine cluster info
        merged_info = {
            'cluster_id': 'merged',
            'point_count': sum(info['point_count'] for info in cluster_info),
            'population_sum': sum(info['population_sum'] for info in cluster_info),
            'population_mean': np.mean([info['population_mean'] for info in cluster_info]),
            'area_pixels': sum(info['area_pixels'] for info in cluster_info),
            'original_clusters': len(polygons)
        }
        
        return [merged_polygon], [merged_info]
        
    except Exception as e:
        print(f"⚠️ Failed to merge polygons: {e}")
        return polygons, cluster_info

def process_city_boundaries(tiff_path, output_path, target_cities=None):
    """Main function to process city boundaries"""
    
    # Load WorldPop data
    population, transform, crs, bounds = load_worldpop_data(tiff_path)
    
    # Filter cities if specified
    cities_to_process = target_cities or list(MAJOR_CITIES.keys())
    
    city_boundaries = {
        'type': 'FeatureCollection',
        'features': []
    }
    
    for city_name in cities_to_process:
        if city_name not in MAJOR_CITIES:
            print(f"⚠️ Unknown city: {city_name}")
            continue
            
        try:
            print(f"\n🏙️ Processing {city_name}")
            city_info = MAJOR_CITIES[city_name]
            
            # Extract city population data
            city_pop, window, bbox = extract_city_population(population, transform, city_name, city_info)
            
            # Perform k-means clustering
            cluster_labels, high_density_coords = perform_kmeans_clustering(city_pop, window, transform)
            
            if cluster_labels is None:
                print(f"❌ Skipping {city_name}: no clusters found")
                continue
            
            # Create cluster polygons
            polygons, cluster_info = create_cluster_polygons(cluster_labels, high_density_coords, window, transform)
            
            if not polygons:
                print(f"❌ Skipping {city_name}: no valid polygons created")
                continue
            
            # Merge nearby clusters
            merged_polygons, merged_info = merge_nearby_clusters(polygons, cluster_info)
            
            # Add to GeoJSON
            for i, (polygon, info) in enumerate(zip(merged_polygons, merged_info)):
                feature = {
                    'type': 'Feature',
                    'properties': {
                        'cityKey': f"pakistan_{city_name.lower().replace(' ', '_')}_{city_name.lower()}",
                        'sampleCity': city_name,
                        'sampleState': 'Pakistan',
                        'sampleCountry': 'Pakistan',
                        'CITY_NAME': city_name,
                        'UC': city_name,
                        'method': 'worldpop_kmeans',
                        'stationCount': 0,  # Will be updated when stations are mapped
                        **info
                    },
                    'geometry': polygon.__geo_interface__
                }
                city_boundaries['features'].append(feature)
                
            print(f"✅ {city_name}: Created {len(merged_polygons)} boundary polygon(s)")
            
        except Exception as e:
            print(f"❌ Error processing {city_name}: {e}")
            continue
    
    # Save results
    with open(output_path, 'w') as f:
        json.dump(city_boundaries, f, indent=2)
    
    print(f"\n💾 Saved {len(city_boundaries['features'])} city boundaries to {output_path}")
    return city_boundaries

def main():
    parser = argparse.ArgumentParser(description='Generate city boundaries from WorldPop data using k-means clustering')
    parser.add_argument('--input', '-i', 
                       default='pak_pop_2025_CN_100m_R2024B_v1.tif',
                       help='Input WorldPop TIFF file')
    parser.add_argument('--output', '-o',
                       default='worldpop_city_boundaries.geojson',
                       help='Output GeoJSON file')
    parser.add_argument('--cities', '-c', nargs='+',
                       help='Specific cities to process (default: all major cities)')
    
    args = parser.parse_args()
    
    print("🌍 WorldPop K-means City Boundary Generator")
    print("=" * 50)
    
    try:
        boundaries = process_city_boundaries(args.input, args.output, args.cities)
        print(f"\n✅ Successfully generated boundaries for {len(boundaries['features'])} cities")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0

if __name__ == '__main__':
    exit(main())