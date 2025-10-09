/**
 * boundaryUtils.ts - Generate natural city boundaries from station coordinates
 * 
 * Creates smooth, organic city outlines using DBSCAN clustering, KDE heatmaps,
 * and contour extraction. Falls back to concave hull when needed.
 */

import concaveman from 'concaveman';
import { isoLines } from 'marchingsquares';
import { Station } from './api';

// Types
interface Point {
  x: number;
  y: number;
}

interface ClusteredStation extends Station {
  cluster: number;
  point: Point;
}

interface CityBoundary {
  cityKey: string;
  stations: Station[];
  polygon: number[][];
  method: 'kde_contour' | 'concave_hull' | 'buffer';
}

// Constants
const WEB_MERCATOR_A = 6378137; // Earth radius in meters
const KDE_GRID_SIZE = 250; // meters (smaller for more detail)
const KDE_BANDWIDTH = 1200; // meters (larger for bigger extents)
const CONTOUR_THRESHOLD = 0.18; // 18% of max density (lower for larger boundaries)
const SMOOTHING_ITERATIONS = 3; // More smoothing for natural curves
const MIN_STATIONS_FOR_BOUNDARY = 1; // Allow even single-station cities

/**
 * Generate city key for grouping stations
 */
export function getCityKey(station: Station): string {
  // Normalize text: lowercase, remove special chars, normalize spaces
  const normalize = (text: string) => 
    text?.toLowerCase()
        .replace(/[^\w\s]/g, '') // Remove special characters
        .replace(/\s+/g, '_')    // Replace spaces with underscores
        .trim() || 'unknown';
  
  const city = normalize(station.city);
  const state = normalize(station.state);
  const country = normalize(station.country);
  
  return `${country}_${state}_${city}`;
}

/**
 * Convert lat/lng to Web Mercator coordinates (EPSG:3857)
 */
function toWebMercator(lat: number, lng: number): Point {
  const x = lng * Math.PI / 180 * WEB_MERCATOR_A;
  const y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) * WEB_MERCATOR_A;
  return { x, y };
}

/**
 * Convert Web Mercator back to lat/lng
 */
function fromWebMercator(point: Point): [number, number] {
  const lng = point.x / WEB_MERCATOR_A * 180 / Math.PI;
  const lat = (Math.atan(Math.exp(point.y / WEB_MERCATOR_A)) * 360 / Math.PI) - 90;
  return [lng, lat];
}

/**
 * Calculate Euclidean distance between two points
 */
function distance(p1: Point, p2: Point): number {
  const dx = p1.x - p2.x;
  const dy = p1.y - p2.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Find k-nearest neighbors distances for adaptive eps calculation
 */
function findNearestNeighborDistances(points: Point[], k: number = 4): number[] {
  return points.map(point => {
    const distances = points
      .filter(p => p !== point)
      .map(p => distance(point, p))
      .sort((a, b) => a - b);
    
    return distances[Math.min(k - 1, distances.length - 1)] || 0;
  });
}

/**
 * Adaptive DBSCAN clustering
 */
function dbscan(points: Point[], factor: number = 1.5): number[] {
  const n = points.length;
  if (n < 2) return points.map(() => 0);
  
  // Calculate adaptive eps
  const nnDistances = findNearestNeighborDistances(points);
  const medianDistance = nnDistances.sort((a, b) => a - b)[Math.floor(nnDistances.length / 2)];
  const eps = Math.max(200, Math.min(2000, medianDistance * factor)); // clamp to 200-2000m
  
  // Calculate adaptive minPts
  const minPts = Math.max(4, Math.floor(Math.sqrt(n)));
  
  const clusters: number[] = new Array(n).fill(-1); // -1 = noise
  let clusterId = 0;
  
  for (let i = 0; i < n; i++) {
    if (clusters[i] !== -1) continue; // already processed
    
    const neighbors = findNeighbors(points, i, eps);
    if (neighbors.length < minPts) {
      clusters[i] = -1; // mark as noise
      continue;
    }
    
    // Start new cluster
    clusters[i] = clusterId;
    const queue = [...neighbors];
    
    while (queue.length > 0) {
      const current = queue.shift()!;
      
      if (clusters[current] === -1) {
        clusters[current] = clusterId; // change noise to border point
      }
      
      if (clusters[current] !== -1) continue; // already processed
      
      clusters[current] = clusterId;
      const currentNeighbors = findNeighbors(points, current, eps);
      
      if (currentNeighbors.length >= minPts) {
        queue.push(...currentNeighbors.filter(idx => clusters[idx] === -1));
      }
    }
    
    clusterId++;
  }
  
  return clusters;
}

/**
 * Find neighbors within eps distance
 */
function findNeighbors(points: Point[], index: number, eps: number): number[] {
  const neighbors: number[] = [];
  const point = points[index];
  
  for (let i = 0; i < points.length; i++) {
    if (i !== index && distance(point, points[i]) <= eps) {
      neighbors.push(i);
    }
  }
  
  return neighbors;
}

/**
 * Get the largest cluster
 */
function getLargestCluster(stations: ClusteredStation[]): ClusteredStation[] {
  const clusterCounts = new Map<number, number>();
  
  stations.forEach(station => {
    if (station.cluster >= 0) { // ignore noise (-1)
      clusterCounts.set(station.cluster, (clusterCounts.get(station.cluster) || 0) + 1);
    }
  });
  
  if (clusterCounts.size === 0) return stations; // no valid clusters, return all
  
  const largestCluster = Array.from(clusterCounts.entries())
    .sort((a, b) => b[1] - a[1])[0][0];
  
  return stations.filter(station => station.cluster === largestCluster);
}

/**
 * Generate KDE heatmap over a grid
 */
function generateKDE(points: Point[], bounds: { minX: number; maxX: number; minY: number; maxY: number }): {
  grid: number[][];
  gridX: number[];
  gridY: number[];
} {
  const { minX, maxX, minY, maxY } = bounds;
  
  // Create grid
  const cols = Math.ceil((maxX - minX) / KDE_GRID_SIZE);
  const rows = Math.ceil((maxY - minY) / KDE_GRID_SIZE);
  
  const gridX = Array.from({ length: cols }, (_, i) => minX + i * KDE_GRID_SIZE);
  const gridY = Array.from({ length: rows }, (_, i) => minY + i * KDE_GRID_SIZE);
  
  const grid: number[][] = Array.from({ length: rows }, () => new Array(cols).fill(0));
  
  // Apply Gaussian kernel
  const bandwidth = KDE_BANDWIDTH;
  const variance = bandwidth * bandwidth;
  
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const gridPoint = { x: gridX[j], y: gridY[i] };
      
      let density = 0;
      for (const point of points) {
        const dist2 = Math.pow(gridPoint.x - point.x, 2) + Math.pow(gridPoint.y - point.y, 2);
        density += Math.exp(-dist2 / (2 * variance));
      }
      
      grid[i][j] = density / (points.length * 2 * Math.PI * variance);
    }
  }
  
  return { grid, gridX, gridY };
}

/**
 * Apply organic smoothing to a polygon with natural variation
 */
function smoothPolygon(polygon: number[][], iterations: number = SMOOTHING_ITERATIONS): number[][] {
  let smoothed = [...polygon];
  
  for (let iter = 0; iter < iterations; iter++) {
    const newPolygon: number[][] = [];
    
    for (let i = 0; i < smoothed.length; i++) {
      const current = smoothed[i];
      const next = smoothed[(i + 1) % smoothed.length];
      
      // Add slight variation to smoothing ratios for organic feel
      const baseRatio1 = 0.25;
      const baseRatio2 = 0.75;
      const variation = (Math.random() - 0.5) * 0.08; // ±4% variation
      
      const ratio1 = Math.max(0.15, Math.min(0.35, baseRatio1 + variation));
      const ratio2 = Math.max(0.65, Math.min(0.85, baseRatio2 + variation));
      
      // Quarter point toward next (with variation)
      const quarter = [
        current[0] + ratio1 * (next[0] - current[0]),
        current[1] + ratio1 * (next[1] - current[1])
      ];
      
      // Three-quarter point toward next (with variation)
      const threeQuarter = [
        current[0] + ratio2 * (next[0] - current[0]),
        current[1] + ratio2 * (next[1] - current[1])
      ];
      
      newPolygon.push(quarter, threeQuarter);
    }
    
    smoothed = newPolygon;
  }
  
  return smoothed;
}

/**
 * Ensure polygon ring is properly closed
 */
function ensureClosedRing(polygon: number[][]): number[][] {
  if (polygon.length === 0) return polygon;
  
  const first = polygon[0];
  const last = polygon[polygon.length - 1];
  
  // Check if already closed (within small tolerance)
  const tolerance = 1e-8;
  if (Math.abs(first[0] - last[0]) < tolerance && Math.abs(first[1] - last[1]) < tolerance) {
    return polygon;
  }
  
  // Close the ring
  return [...polygon, [first[0], first[1]]];
}

/**
 * Generate natural boundary for small cities using Voronoi-inspired approach
 */
function generateBufferBoundary(stations: ClusteredStation[]): number[][] {
  // Calculate center point
  const centerLat = stations.reduce((sum, s) => sum + s.latitude, 0) / stations.length;
  const centerLng = stations.reduce((sum, s) => sum + s.longitude, 0) / stations.length;
  
  // Calculate appropriate base radius (increased for larger extents)
  let baseRadius = 0.010; // ~1000m default radius in degrees (increased from 800m)
  
  if (stations.length > 1) {
    // Use maximum distance from center as basis for radius
    const maxDist = Math.max(...stations.map(s => {
      const dlat = s.latitude - centerLat;
      const dlng = s.longitude - centerLng;
      return Math.sqrt(dlat * dlat + dlng * dlng);
    }));
    
    // Ensure minimum radius and add larger buffer
    baseRadius = Math.max(0.005, maxDist * 2.2); // At least 500m, with 2.2x buffer (increased)
  }
  
  // Create organic, irregular boundary using multiple techniques
  const numPoints = 24; // More points for smoother curves
  const polygon: number[][] = [];
  
  // Generate irregular radius variations using multiple sine waves
  const radiusVariations: number[] = [];
  for (let i = 0; i < numPoints; i++) {
    const angle = (i / numPoints) * 2 * Math.PI;
    
    // Combine multiple frequency sine waves for natural variation
    const variation1 = Math.sin(angle * 3) * 0.3;      // Primary variation
    const variation2 = Math.sin(angle * 7) * 0.15;     // Secondary bumps
    const variation3 = Math.sin(angle * 11) * 0.08;    // Fine detail
    const variation4 = Math.sin(angle * 2.3) * 0.2;    // Asymmetry
    
    // Combine variations (range roughly -0.7 to +0.7)
    const totalVariation = variation1 + variation2 + variation3 + variation4;
    
    // Apply variation to base radius (0.3 to 1.7 times base radius)
    const radiusMultiplier = 1.0 + totalVariation;
    radiusVariations.push(Math.max(0.3, radiusMultiplier));
  }
  
  // Add influence from actual station positions for even more natural look
  for (let i = 0; i < numPoints; i++) {
    const angle = (i / numPoints) * 2 * Math.PI;
    let stationInfluence = 0;
    
    // Check how close this angle is to actual stations
    for (const station of stations) {
      const stationAngle = Math.atan2(
        station.latitude - centerLat,
        station.longitude - centerLng
      );
      
      // Normalize angles to [0, 2π]
      const normalizedStationAngle = stationAngle < 0 ? stationAngle + 2 * Math.PI : stationAngle;
      const normalizedCurrentAngle = angle < 0 ? angle + 2 * Math.PI : angle;
      
      // Calculate angular distance (accounting for wrap-around)
      let angleDiff = Math.abs(normalizedCurrentAngle - normalizedStationAngle);
      angleDiff = Math.min(angleDiff, 2 * Math.PI - angleDiff);
      
      // Add influence if station is nearby (within π/2 radians)
      if (angleDiff < Math.PI / 2) {
        const influence = Math.cos(angleDiff * 2) * 0.3; // 0.3 max influence
        stationInfluence += influence;
      }
    }
    
    // Apply station influence
    radiusVariations[i] += stationInfluence;
    radiusVariations[i] = Math.max(0.2, radiusVariations[i]); // Ensure minimum
  }
  
  // Generate polygon points with varied radius
  for (let i = 0; i < numPoints; i++) {
    const angle = (i / numPoints) * 2 * Math.PI;
    const radius = baseRadius * radiusVariations[i];
    
    const lat = centerLat + radius * Math.cos(angle);
    const lng = centerLng + radius * Math.sin(angle);
    polygon.push([lng, lat]);
  }
  
  // Close the polygon
  polygon.push([polygon[0][0], polygon[0][1]]);
  
  // Apply multiple rounds of smoothing for natural curves
  let smoothed = smoothPolygon(polygon, 2); // Initial smoothing
  
  // Add slight randomness for more organic feel (very subtle)
  const finalPolygon: number[][] = [];
  for (let i = 0; i < smoothed.length - 1; i++) { // Skip last point (duplicate of first)
    const point = smoothed[i];
    
    // Add tiny random offset (max ~50m at equator)
    const randomOffset = 0.0005;
    const offsetLng = (Math.random() - 0.5) * randomOffset;
    const offsetLat = (Math.random() - 0.5) * randomOffset;
    
    finalPolygon.push([
      point[0] + offsetLng,
      point[1] + offsetLat
    ]);
  }
  
  // Close the final polygon
  finalPolygon.push([finalPolygon[0][0], finalPolygon[0][1]]);
  
  return finalPolygon;
}

/**
 * Add organic variation to a boundary polygon
 */
function addOrganicVariation(polygon: number[][], variationStrength: number = 0.15): number[][] {
  if (polygon.length === 0) return polygon;
  
  // Calculate polygon centroid
  const centroid = polygon.reduce(
    (acc, point) => [acc[0] + point[0], acc[1] + point[1]], 
    [0, 0]
  ).map(coord => coord / polygon.length);
  
  return polygon.map((point, i) => {
    const angle = (i / polygon.length) * 2 * Math.PI;
    
    // Calculate distance from centroid
    const dx = point[0] - centroid[0];
    const dy = point[1] - centroid[1];
    const distance = Math.sqrt(dx * dx + dy * dy);
    
    // Create organic variation using multiple sine waves
    const variation1 = Math.sin(angle * 3.7) * 0.4;  // Primary variation
    const variation2 = Math.sin(angle * 8.3) * 0.2;  // Secondary bumps
    const variation3 = Math.sin(angle * 12.1) * 0.1; // Fine detail
    const variation4 = Math.sin(angle * 5.7) * 0.3;  // Asymmetry
    
    const totalVariation = variation1 + variation2 + variation3 + variation4;
    const radiusMultiplier = 1.0 + (totalVariation * variationStrength);
    
    // Apply variation while maintaining general shape
    const newDistance = distance * Math.max(0.7, radiusMultiplier);
    const ratio = newDistance / distance;
    
    return [
      centroid[0] + dx * ratio,
      centroid[1] + dy * ratio
    ];
  });
}

/**
 * Generate city boundary using KDE contour method with organic enhancement
 */
function generateKDEBoundary(stations: ClusteredStation[]): number[][] | null {
  try {
    const points = stations.map(s => s.point);
    
    // Calculate bounds with larger padding for bigger extents
    const padding = KDE_BANDWIDTH * 2.5; // Increased padding
    const bounds = {
      minX: Math.min(...points.map(p => p.x)) - padding,
      maxX: Math.max(...points.map(p => p.x)) + padding,
      minY: Math.min(...points.map(p => p.y)) - padding,
      maxY: Math.max(...points.map(p => p.y)) + padding
    };
    
    // Generate KDE grid
    const { grid, gridX, gridY } = generateKDE(points, bounds);
    
    // Find maximum density
    const maxDensity = Math.max(...grid.flat());
    if (maxDensity === 0) return null;
    
    // Extract contour at threshold
    const threshold = maxDensity * CONTOUR_THRESHOLD;
    const contours = isoLines(grid, [threshold], { x: gridX, y: gridY });
    
    if (!contours || contours.length === 0) return null;
    
    // Find the largest contour
    let largestContour = contours[0];
    for (const contour of contours) {
      if (contour.coordinates && contour.coordinates.length > 0) {
        const coords = contour.coordinates[0];
        if (coords.length > (largestContour.coordinates?.[0]?.length || 0)) {
          largestContour = contour;
        }
      }
    }
    
    if (!largestContour.coordinates || largestContour.coordinates.length === 0) {
      return null;
    }
    
    // Convert Web Mercator back to lat/lng
    const webMercatorCoords = largestContour.coordinates[0];
    const latlngCoords = webMercatorCoords.map((coord: number[]) => 
      fromWebMercator({ x: coord[0], y: coord[1] })
    );
    
    // Add organic variation before smoothing
    const organicCoords = addOrganicVariation(latlngCoords, 0.12);
    
    // Smooth and close the polygon
    const smoothed = smoothPolygon(organicCoords);
    return ensureClosedRing(smoothed);
    
  } catch (error) {
    console.warn('KDE contour generation failed:', error);
    return null;
  }
}

/**
 * Expand polygon outward for larger boundary extents
 */
function expandPolygon(polygon: number[][], expansionFactor: number = 1.3): number[][] {
  if (polygon.length === 0) return polygon;
  
  // Calculate polygon centroid
  const centroid = polygon.reduce(
    (acc, point) => [acc[0] + point[0], acc[1] + point[1]], 
    [0, 0]
  ).map(coord => coord / polygon.length);
  
  // Expand each point away from centroid
  return polygon.map(point => {
    const dx = point[0] - centroid[0];
    const dy = point[1] - centroid[1];
    
    return [
      centroid[0] + dx * expansionFactor,
      centroid[1] + dy * expansionFactor
    ];
  });
}

/**
 * Generate city boundary using concave hull with organic enhancement
 */
function generateConcaveHullBoundary(stations: ClusteredStation[]): number[][] {
  const latlngPoints = stations.map(s => [s.longitude, s.latitude]);
  
  try {
    // Generate concave hull with adjusted parameters for more natural shapes
    const hull = concaveman(latlngPoints, 1.8, 0.015); // More concave, slightly longer threshold
    
    // Expand the hull for larger extents
    const expanded = expandPolygon(hull, 1.4);
    
    // Add organic variation
    const organicHull = addOrganicVariation(expanded, 0.08);
    
    // Smooth and close the polygon
    const smoothed = smoothPolygon(organicHull);
    return ensureClosedRing(smoothed);
    
  } catch (error) {
    console.warn('Concave hull generation failed, using enhanced convex hull:', error);
    
    // Enhanced fallback: convex hull with organic treatment
    const convexHull = convexHullGiftWrap(latlngPoints);
    const expanded = expandPolygon(convexHull, 1.3);
    const organic = addOrganicVariation(expanded, 0.1);
    const smoothed = smoothPolygon(organic);
    return ensureClosedRing(smoothed);
  }
}

/**
 * Simple convex hull using gift wrapping algorithm
 */
function convexHullGiftWrap(points: number[][]): number[][] {
  if (points.length < 3) return points;
  
  // Find leftmost point
  let leftmost = 0;
  for (let i = 1; i < points.length; i++) {
    if (points[i][0] < points[leftmost][0]) {
      leftmost = i;
    }
  }
  
  const hull: number[][] = [];
  let current = leftmost;
  
  do {
    hull.push([...points[current]]);
    let next = (current + 1) % points.length;
    
    for (let i = 0; i < points.length; i++) {
      const orientation = getOrientation(points[current], points[i], points[next]);
      if (orientation === 2) {
        next = i;
      }
    }
    
    current = next;
  } while (current !== leftmost);
  
  return hull;
}

/**
 * Get orientation of three points (0=collinear, 1=clockwise, 2=counterclockwise)
 */
function getOrientation(p: number[], q: number[], r: number[]): number {
  const val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1]);
  if (Math.abs(val) < 1e-10) return 0; // collinear
  return val > 0 ? 1 : 2; // clockwise or counterclockwise
}

/**
 * Main function: Generate natural city boundaries from stations
 */
export function generateCityBoundaries(stations: Station[]): GeoJSON.FeatureCollection {
  // Group stations by city
  const cityGroups = new Map<string, Station[]>();
  
  stations.forEach(station => {
    const cityKey = getCityKey(station);
    if (!cityGroups.has(cityKey)) {
      cityGroups.set(cityKey, []);
    }
    cityGroups.get(cityKey)!.push(station);
  });
  
  const boundaries: CityBoundary[] = [];
  
  // Process each city
  console.log(`🗺️ Processing ${cityGroups.size} cities:`, Array.from(cityGroups.keys()));
  
  for (const [cityKey, cityStations] of cityGroups) {
    console.log(`🏙️ Processing ${cityKey}: ${cityStations.length} stations`);
    
    if (cityStations.length < MIN_STATIONS_FOR_BOUNDARY) {
      console.warn(`Skipping ${cityKey}: insufficient stations (${cityStations.length})`);
      continue;
    }
    
    // Project to Web Mercator
    const projectedStations: ClusteredStation[] = cityStations.map(station => ({
      ...station,
      point: toWebMercator(station.latitude, station.longitude),
      cluster: -1
    }));
    
    // Run adaptive DBSCAN
    const points = projectedStations.map(s => s.point);
    const clusters = dbscan(points);
    
    // Assign cluster IDs
    projectedStations.forEach((station, i) => {
      station.cluster = clusters[i];
    });
    
    // Keep largest cluster only
    const largestClusterStations = getLargestCluster(projectedStations);
    
    if (largestClusterStations.length < MIN_STATIONS_FOR_BOUNDARY) {
      console.warn(`Skipping ${cityKey}: largest cluster too small (${largestClusterStations.length})`);
      continue;
    }
    
    let polygon: number[][] | null = null;
    let method: 'kde_contour' | 'concave_hull' | 'buffer' = 'kde_contour';
    
    // Special handling for small cities (1-2 stations)
    if (largestClusterStations.length <= 2) {
      console.log(`Using buffer method for small city ${cityKey} (${largestClusterStations.length} stations)`);
      polygon = generateBufferBoundary(largestClusterStations);
      method = 'buffer';
    } else if (largestClusterStations.length <= 5) {
      // For small cities (3-5 stations), try concave hull first
      console.log(`Using concave hull for small city ${cityKey} (${largestClusterStations.length} stations)`);
      polygon = generateConcaveHullBoundary(largestClusterStations);
      method = 'concave_hull';
    } else {
      // Try KDE contour method first for larger cities
      polygon = generateKDEBoundary(largestClusterStations);
      method = 'kde_contour';
      
      // Fallback to concave hull if KDE failed
      if (!polygon) {
        console.log(`Falling back to concave hull for ${cityKey}`);
        polygon = generateConcaveHullBoundary(largestClusterStations);
        method = 'concave_hull';
      }
    }
    
    if (polygon && polygon.length >= 3) {
      boundaries.push({
        cityKey,
        stations: largestClusterStations,
        polygon,
        method
      });
    }
  }
  
  // Convert to GeoJSON
  const features: GeoJSON.Feature[] = boundaries.map(boundary => {
    const sampleStation = boundary.stations[0];
    const cityName = sampleStation?.city || '';
    
    return {
      type: 'Feature',
      properties: {
        cityKey: boundary.cityKey,
        stationCount: boundary.stations.length,
        method: boundary.method,
        // Add sample station info
        sampleCity: cityName,
        sampleState: sampleStation?.state,
        sampleCountry: sampleStation?.country,
        // Add properties expected by click handlers
        CITY_NAME: cityName, // Expected by click handler
        UC: cityName // Fallback property expected by click handler
      },
      geometry: {
        type: 'Polygon',
        coordinates: [boundary.polygon]
      }
    };
  });
  
  return {
    type: 'FeatureCollection',
    features
  };
}

/**
 * Utility function to get boundary for a specific city
 */
export function getCityBoundary(stations: Station[], cityKey: string): GeoJSON.Feature | null {
  const boundaries = generateCityBoundaries(stations);
  return boundaries.features.find(f => f.properties?.cityKey === cityKey) || null;
}

/**
 * Legacy function for compatibility - returns 'station_only' for all cities
 */
export function getCityBoundaryType(_: string, __: number): 'station_only' {
  return 'station_only';
}

// Major cities with square airshed boundaries (center coordinates + size in km)
const MAJOR_CITIES_SQUARES = {
  'Karachi': { lat: 24.8607, lon: 67.0011, size_km: 80 },
  'Lahore': { lat: 31.5204, lon: 74.3587, size_km: 35 }, // Reduced to avoid crossing into India
  'Faisalabad': { lat: 31.4504, lon: 73.1350, size_km: 50 },
  'Rawalpindi': { lat: 33.5651, lon: 73.0169, size_km: 25 }, // Smaller to avoid overlap
  'Islamabad': { lat: 33.6844, lon: 73.0479, size_km: 25 }, // Smaller to avoid overlap  
  'Peshawar': { lat: 34.0151, lon: 71.5249, size_km: 50 },
  'Bahawalpur': { lat: 29.4010, lon: 71.6833, size_km: 45 },
  'Quetta': { lat: 30.1798, lon: 66.9750, size_km: 45 }
} as const;

/**
 * Check if a city should use square airshed boundaries
 */
function shouldUseSquareBoundary(cityName: string): { lat: number; lon: number; size_km: number } | null {
  const normalizedCity = cityName.toLowerCase().trim();
  for (const [key, config] of Object.entries(MAJOR_CITIES_SQUARES)) {
    if (normalizedCity.includes(key.toLowerCase())) {
      return config;
    }
  }
  return null;
}

/**
 * Create a square airshed boundary for a major city
 */
function createSquareBoundary(
  config: { lat: number; lon: number; size_km: number },
  stations: Station[],
  cityKey: string,
  cityName: string
): GeoJSON.Feature {
  const { lat, lon, size_km } = config;
  
  // Convert km to degrees (approximately)
  const half_size_deg = (size_km / 2) / 111.0; // 1 degree ≈ 111 km
  
  // Create square coordinates
  const square = [
    [lon - half_size_deg, lat - half_size_deg], // SW
    [lon + half_size_deg, lat - half_size_deg], // SE  
    [lon + half_size_deg, lat + half_size_deg], // NE
    [lon - half_size_deg, lat + half_size_deg], // NW
    [lon - half_size_deg, lat - half_size_deg]  // Close the polygon
  ];

  console.log(`🗺️ Created ${size_km}km square airshed for ${cityName}`);

  // Create a feature with our expected properties
  const sampleStation = stations[0];
  return {
    type: 'Feature',
    properties: {
      cityKey,
      stationCount: stations.length,
      method: 'square_airshed',
      sampleCity: sampleStation?.city || '',
      sampleState: sampleStation?.state,
      sampleCountry: sampleStation?.country,
      CITY_NAME: sampleStation?.city || '',
      UC: sampleStation?.city || '',
      center_lat: lat,
      center_lon: lon,
      size_km: size_km,
      area_km2: size_km * size_km
    },
    geometry: {
      type: 'Polygon',
      coordinates: [square]
    }
  };
}

/**
 * Enhanced boundary generation with square airsheds for major cities
 */
export async function generateCityBoundariesWithSquares(stations: Station[]): Promise<GeoJSON.FeatureCollection> {
  console.log('🗺️ generateCityBoundariesWithSquares called with', stations.length, 'stations');
  
  // Group stations by city
  const cityGroups = new Map<string, Station[]>();
  
  stations.forEach(station => {
    const cityKey = getCityKey(station);
    if (!cityGroups.has(cityKey)) {
      cityGroups.set(cityKey, []);
    }
    cityGroups.get(cityKey)!.push(station);
  });

  const features: GeoJSON.Feature[] = [];
  
  console.log(`🗺️ Processing ${cityGroups.size} cities for boundary generation`);

  for (const [cityKey, cityStations] of cityGroups) {
    const sampleStation = cityStations[0];
    const cityName = sampleStation?.city || '';
    
    console.log(`🏙️ Processing ${cityKey} (${cityName}): ${cityStations.length} stations`);
    
    if (cityStations.length < MIN_STATIONS_FOR_BOUNDARY) {
      console.log(`Skipping ${cityKey}: insufficient stations (${cityStations.length})`);
      continue;
    }

    // Check if this is a major city that should use square airsheds
    const squareConfig = shouldUseSquareBoundary(cityName);
    
    if (squareConfig) {
      console.log(`🗺️ Using square airshed for ${cityName} (${squareConfig.size_km}km)`);
      const squareFeature = createSquareBoundary(squareConfig, cityStations, cityKey, cityName);
      features.push(squareFeature);
      continue;
    }

    // Fall back to custom boundary generation for smaller cities
    console.log(`🗺️ Using custom boundary generation for ${cityName}`);
    const customBoundaries = generateCityBoundaries([...cityStations]);
    const cityFeature = customBoundaries.features.find(f => f.properties?.cityKey === cityKey);
    
    if (cityFeature) {
      features.push(cityFeature);
    }
  }
  
  console.log(`🗺️ Generated ${features.length} total boundaries`);
  
  return {
    type: 'FeatureCollection',
    features
  };
}

/**
 * Legacy function for compatibility - now uses simple square airsheds for major cities
 */
export async function getFilteredBoundaries(stations: Station[]): Promise<GeoJSON.FeatureCollection> {
  console.log('🗺️ getFilteredBoundaries called with', stations.length, 'stations');
  
  const boundaries = await generateCityBoundariesWithSquares(stations);
  
  console.log(`🗺️ Generated ${boundaries.features.length} boundaries (square airsheds + custom)`);
  
  return boundaries;
}