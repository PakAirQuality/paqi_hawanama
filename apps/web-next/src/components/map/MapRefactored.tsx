'use client';

import { useEffect, useState, useMemo } from 'react';
import 'mapbox-gl/dist/mapbox-gl.css';
import Map, { Marker, Source, Layer, type ViewStateChangeEvent, type MapRef } from 'react-map-gl/mapbox';
import { useStationSidebar } from '@/stores/stationSidebar';

// Modular imports
import { useStationsData } from './hooks/useStationsData';
import { useWindData } from './hooks/useWindData';
import { useWindLayer } from './hooks/useWindLayer';
import AqiMarker from './components/AqiMarker';
import { fetchDailyStations, type DailyStation } from '@/lib/api';

// PM2.5 µg/m³ thresholds → synthetic AQI class for AqiMarker coloring
function pm25ToSyntheticAqi(pm25: number): number {
  if (pm25 <= 35) return 30    // → bg-good
  if (pm25 <= 75) return 80    // → bg-moderate
  if (pm25 <= 150) return 160  // → bg-unhealthy
  if (pm25 <= 250) return 250  // → bg-very-unhealthy
  return 400                   // → bg-hazardous
}

interface MapProps {
  center?: [number, number];
  zoom?: number;
  className?: string;
  heatmapVisible?: boolean;
  windVisible?: boolean;
  modelVariant?: 'backbone' | 'support_aware';
  viewMode?: 'live' | 'estimated';
  selectedDate?: string | null;
  availableDates?: string[];
}

export default function MapRefactored({
  center,
  zoom,
  className = '',
  heatmapVisible = true,
  windVisible = true,
  modelVariant = 'backbone',
  viewMode = 'live',
  selectedDate = null,
  availableDates = [],
}: MapProps) {
  const { openStation } = useStationSidebar();
  const { stations, error } = useStationsData();

  const [viewport, setViewport] = useState({
    longitude: center?.[0] || 78,
    latitude: center?.[1] || 22,
    zoom: zoom ?? 3.6,
  });

  const [bounds, setBounds] = useState<[number, number, number, number] | undefined>();
  const [map, setMap] = useState<any>(null);
  const [dailyStations, setDailyStations] = useState<DailyStation[]>([]);

  // Same-origin URL so Firebase Hosting CDN (Fastly) caches tiles for all users.
  // firebase.json rewrites /api/** → Cloud Run; in dev, next.config.ts mirrors this.
  const tileUrl = selectedDate
    ? `/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png?smoothed=true&model=support_aware`
    : null;

  // Fetch daily station observations when in estimated mode
  useEffect(() => {
    if (viewMode !== 'estimated' || !selectedDate) {
      setDailyStations([])
      return
    }
    fetchDailyStations(selectedDate)
      .then(setDailyStations)
      .catch(() => setDailyStations([]))
  }, [viewMode, selectedDate]);

  // Fly to Pakistan when switching to estimated mode
  useEffect(() => {
    if (viewMode === 'estimated' && map) {
      map.flyTo({ center: [69.35, 30.0], zoom: 5, duration: 1200, essential: true })
    }
  }, [viewMode, map]);

  // Prefetch center tile for adjacent dates so going back is instant.
  // Uses same-origin /api/... path so the browser HTTP cache absorbs repeats.
  useEffect(() => {
    if (viewMode !== 'estimated' || !selectedDate || !map || availableDates.length === 0) return;
    const idx = availableDates.indexOf(selectedDate);
    const neighbors = [availableDates[idx - 1], availableDates[idx + 1]].filter(Boolean);
    if (neighbors.length === 0) return;
    const center = map.getCenter();
    const z = Math.min(Math.floor(map.getZoom()), 7);
    const n = Math.pow(2, z);
    const tx = Math.floor((center.lng + 180) / 360 * n);
    const lat = center.lat * Math.PI / 180;
    const ty = Math.floor((1 - Math.log(Math.tan(lat) + 1 / Math.cos(lat)) / Math.PI) / 2 * n);
    for (const d of neighbors) {
      fetch(`/api/v1/ops/pipeline/tiles/${d}/${z}/${tx}/${ty}.png?smoothed=true&model=support_aware`, { cache: 'force-cache' }).catch(() => {});
    }
  }, [selectedDate, viewMode, map, availableDates]);

  // Wind layer (lazy — only fetches data when toggled on)
  const { windImage, windMetadata } = useWindData(windVisible);
  useWindLayer(map, windImage, windMetadata, windVisible);

  // Live station features (LIVE mode)
  const liveFeatures = useMemo(() => {
    return stations.map(station => ({
      type: 'Feature' as const,
      geometry: {
        type: 'Point' as const,
        coordinates: [station.longitude, station.latitude]
      },
      properties: {
        id: station.id,
        name: station.name,
        city: station.city,
        aqi: station.aqi_raw,
        pm25: station.pm25,
        cluster: false
      }
    }));
  }, [stations]);

  // Daily station features for ESTIMATED mode (PM2.5-band coloring via synthetic AQI)
  const estimatedFeatures = useMemo(() => {
    return dailyStations.map((stn, i) => ({
      type: 'Feature' as const,
      geometry: {
        type: 'Point' as const,
        coordinates: [stn.lon, stn.lat]
      },
      properties: {
        id: `daily-${i}`,
        name: stn.name,
        city: stn.city,
        aqi: pm25ToSyntheticAqi(stn.pm25),
        pm25: stn.pm25,
        cluster: false
      }
    }));
  }, [dailyStations]);

  const features = viewMode === 'estimated' ? estimatedFeatures : liveFeatures;

  const handleMarkerClick = (feature: any) => {
    const { properties } = feature;
    // Only open sidebar for live station markers (estimated markers use surrogate IDs)
    if (viewMode === 'estimated') return;
    openStation(String(properties.id));
  };

  const handleMapChange = (evt: ViewStateChangeEvent) => {
    setViewport(evt.viewState);
    setBounds(evt.target.getBounds().toArray().flat() as [number, number, number, number]);
  };

  const handleMapLoad = (evt: any) => {
    const mapInstance = evt.target;
    setMap(mapInstance);
    handleMapChange(evt);
  };

  // Error state
  if (error) {
    return (
      <div className={`flex items-center justify-center bg-gray-100 ${className}`}>
        <div className="text-center">
          <p className="text-red-600 mb-2">Error loading stations</p>
          <p className="text-gray-500 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`w-full h-full relative ${className}`}>
      <Map
        {...viewport}
        zoom={viewport?.zoom ?? 3.6}
        mapboxAccessToken={process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''}
        mapStyle="mapbox://styles/mapbox/streets-v12"
        onMove={handleMapChange}
        onLoad={handleMapLoad}
        style={{ 
          width: '100%', 
          height: '100%'
        }}
        maxPitch={45}
        attributionControl={false}
        // Optimized touch settings for smooth mobile interaction
        touchZoomRotate={{
          around: 'center'
        }}
        touchPitch={false}
        dragRotate={false}
        dragPan={true}
        scrollZoom={{
          around: 'center'
        }}
        doubleClickZoom={true}
        keyboard={false}
        // Performance optimizations
        maxTileCacheSize={500}
        fadeDuration={100}
        renderWorldCopies={false}
        optimizeForTerrain={false}
        antialias={false}
        // Smooth transitions
        transitionDuration={300}
        pitchWithRotate={false}
      >
        {/* PM2.5 estimation raster — Source stays mounted to preserve Mapbox's tile cache
            across LIVE/ESTIMATED mode switches. Layer opacity goes to 0 in LIVE mode. */}
        {tileUrl && (
          <Source
            id="pm25-tiles"
            type="raster"
            tiles={[tileUrl]}
            tileSize={256}
            bounds={[60.45, 23.25, 77.95, 37.35]}
            maxzoom={12}
          >
            <Layer
              id="pm25-raster"
              type="raster"
              paint={{
                'raster-resampling': 'linear',
                'raster-opacity': viewMode === 'estimated'
                  ? [
                      'interpolate', ['linear'], ['zoom'],
                      3, 0.7,
                      7, 0.65,
                      9, 0.4,
                      12, 0.2,
                    ] as any
                  : 0,
              }}
            />
          </Source>
        )}

        {features.map(feature => {
          const key = `marker-${feature.properties.id}`;

          return (
            <Marker
              key={key}
              longitude={feature.geometry.coordinates[0]}
              latitude={feature.geometry.coordinates[1]}
            >
              <div onClick={() => handleMarkerClick(feature)}>
                <AqiMarker
                  aqi={feature.properties.aqi}
                  pm25={feature.properties.pm25}
                  isCluster={false}
                  zoom={viewport?.zoom ?? 3.6}
                />
              </div>
            </Marker>
          );
        })}
      </Map>
    </div>
  );
}