'use client';

import { memo, useEffect, useState, useMemo, useRef, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import 'mapbox-gl/dist/mapbox-gl.css';
import Map, { Marker, Source, Layer, type ViewStateChangeEvent, type MapRef } from 'react-map-gl/mapbox';
import { useStationSidebar } from '@/stores/stationSidebar';

// Modular imports
import { useStationsData } from './hooks/useStationsData';
import { useWindData } from './hooks/useWindData';
import { useWindLayer } from './hooks/useWindLayer';
import AqiMarker from './components/AqiMarker';
import { fetchDailyStations, type DailyStation } from '@/lib/api';
import { formatDateLabel } from '@/lib/dateLabel';

const EMPTY_DAILY: DailyStation[] = [];

// Memoized marker list: re-renders only when the station set, the zoom band or the click
// handler changes — not on every camera move (which re-renders MapRefactored itself).
const StationMarkers = memo(function StationMarkers({ features, zoomBand, onMarkerClick }: {
  features: any[];
  zoomBand: number;
  onMarkerClick: (feature: any) => void;
}) {
  return (
    <>
      {features.map(feature => (
        <Marker
          key={`marker-${feature.properties.id}`}
          longitude={feature.geometry.coordinates[0]}
          latitude={feature.geometry.coordinates[1]}
        >
          <div onClick={() => onMarkerClick(feature)}>
            <AqiMarker
              aqi={feature.properties.aqi}
              pm25={feature.properties.pm25}
              isCluster={false}
              zoom={zoomBand}
            />
          </div>
        </Marker>
      ))}
    </>
  );
});

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
  viewMode?: 'live' | 'history';
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
  const { stations, error } = useStationsData(viewMode === 'live');

  const [viewport, setViewport] = useState({
    longitude: center?.[0] || 78,
    latitude: center?.[1] || 22,
    zoom: zoom ?? 3.6,
  });

  const [map, setMap] = useState<any>(null);

  // Same-origin URL so Firebase Hosting CDN (Fastly) caches tiles for all users.
  // firebase.json rewrites /api/** → Cloud Run; in dev, next.config.ts mirrors this.
  const tileUrl = selectedDate
    ? `/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png?smoothed=true&model=support_aware`
    : null;

  // Daily station observations in ESTIMATED mode. Same query key as EstimatedContextPanel,
  // so the map and the panel share one cached request per date instead of fetching twice.
  const { data: dailyStationsData } = useQuery({
    queryKey: ['daily-stations', selectedDate],
    queryFn: () => fetchDailyStations(selectedDate as string),
    enabled: viewMode === 'history' && !!selectedDate,
    staleTime: Infinity,
    retry: 1,
    retryDelay: 1500,
  });
  const dailyStations: DailyStation[] = (viewMode === 'history' && dailyStationsData) ? dailyStationsData : EMPTY_DAILY;

  // Fly between modes: zoom into Pakistan for ESTIMATED, back to the South Asia
  // overview for LIVE. Skip the initial mount (when viewMode is still its default
  // 'live') so we don't animate from the user's already-correct starting view.
  const flownOnce = useRef(false);
  useEffect(() => {
    if (!map) return;
    if (viewMode === 'history') {
      map.flyTo({ center: [69.35, 30.0], zoom: 5, duration: 1200, essential: true })
      flownOnce.current = true
    } else if (flownOnce.current) {
      map.flyTo({
        center: [center?.[0] ?? 78, center?.[1] ?? 22],
        zoom: zoom ?? 3.6,
        duration: 1200,
        essential: true,
      })
    }
  }, [viewMode, map, center, zoom]);

  // Prefetch center tile for adjacent dates so going back is instant.
  // Uses same-origin /api/... path so the browser HTTP cache absorbs repeats.
  useEffect(() => {
    if (viewMode !== 'history' || !selectedDate || !map || availableDates.length === 0) return;
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

  // Wind layer: start only once the map has loaded and the station markers are usable
  // (or the station request has failed), so the ~186 KB texture and the particle
  // animation never compete with the first usable map.
  const stationsReady = viewMode !== 'live' || stations.length > 0 || !!error;
  const { windImage, windMetadata } = useWindData(windVisible && !!map && stationsReady);
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
        id: stn.station_id ?? `daily-${i}`,
        name: stn.name,
        city: stn.city,
        aqi: pm25ToSyntheticAqi(stn.pm25),
        pm25: stn.pm25,
        cluster: false
      }
    }));
  }, [dailyStations]);

  const features = viewMode === 'history' ? estimatedFeatures : liveFeatures;

  const handleMarkerClick = useCallback((feature: any) => {
    const { properties } = feature;
    const id = String(properties.id);
    // Synthetic IDs from estimated markers without a real station_id — skip.
    if (id.startsWith('daily-')) return;
    const isEstimated = viewMode === 'history';
    const snapshot = isEstimated
      ? dailyStations.find(s => s.station_id === id)
      : undefined;
    openStation(
      id,
      isEstimated ? selectedDate ?? undefined : undefined,
      isEstimated && snapshot
        ? { pm25: snapshot.pm25, name: snapshot.name, city: snapshot.city }
        : undefined,
    );
  }, [viewMode, dailyStations, selectedDate, openStation]);

  const handleMapChange = (evt: ViewStateChangeEvent) => {
    setViewport(evt.viewState);
  };

  // AqiMarker only changes appearance at zoom 3 and zoom 8, so markers re-render on those
  // crossings only; panning and small zooms leave the memoized marker list untouched
  // (react-map-gl repositions Marker elements itself on every map move).
  const zoomBand = (viewport?.zoom ?? 3.6) < 3 ? 2 : (viewport?.zoom ?? 3.6) < 8 ? 5 : 9;

  const handleMapLoad = (evt: any) => {
    const mapInstance = evt.target;
    setMap(mapInstance);
    handleMapChange(evt);
  };

  // ── History-mode hover tooltip on the estimated grid ─────────────────────
  // Shows the model-estimated PM2.5 for the cell under the cursor.
  // Live mode = no-op; in History mode we debounce a fetch to /tiles/{date}/point
  // and cache results in a Map so micro-movements don't refetch.
  const [hoverInfo, setHoverInfo] = useState<
    { x: number; y: number; lat: number; lon: number; pm25: number | null } | null
  >(null);
  const hoverCache = useRef<Record<string, number>>({});
  const hoverFetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleMapMouseMove = useCallback((e: any) => {
    if (viewMode !== 'history' || !selectedDate) return;
    const lng = e?.lngLat?.lng;
    const lat = e?.lngLat?.lat;
    const x = e?.point?.x;
    const y = e?.point?.y;
    if (lng == null || lat == null || x == null || y == null) return;
    // /tiles/{date}/point expects 20 ≤ lat ≤ 40 and 60 ≤ lon ≤ 80
    if (lat < 20 || lat > 40 || lng < 60 || lng > 80) {
      setHoverInfo(null);
      return;
    }
    setHoverInfo(prev => ({
      x, y, lat, lon: lng,
      pm25: prev?.pm25 ?? null,
    }));
  }, [viewMode, selectedDate]);

  const handleMapMouseLeave = useCallback(() => setHoverInfo(null), []);

  // Clear the tooltip whenever the user switches modes or date.
  useEffect(() => {
    if (viewMode !== 'history') setHoverInfo(null);
  }, [viewMode, selectedDate]);

  // Debounced fetch keyed on the rounded coords + date — same cell uses cached value.
  const hoverKey = hoverInfo
    ? `${selectedDate}|${hoverInfo.lat.toFixed(3)}|${hoverInfo.lon.toFixed(3)}`
    : null;
  useEffect(() => {
    if (!hoverInfo || !selectedDate || !hoverKey) return;
    const cached = hoverCache.current[hoverKey];
    if (cached !== undefined) {
      setHoverInfo(prev => (prev ? { ...prev, pm25: cached } : prev));
      return;
    }
    if (hoverFetchTimer.current) clearTimeout(hoverFetchTimer.current);
    hoverFetchTimer.current = setTimeout(async () => {
      try {
        const url = `/api/v1/ops/pipeline/tiles/${selectedDate}/point?lat=${hoverInfo.lat.toFixed(4)}&lon=${hoverInfo.lon.toFixed(4)}&smoothed=true&model=support_aware`;
        const res = await fetch(url, { credentials: 'omit' });
        if (!res.ok) return;
        const data = await res.json();
        const v = typeof data?.pm25 === 'number' ? data.pm25 : null;
        if (v != null) hoverCache.current[hoverKey] = v;
        setHoverInfo(prev => (prev ? { ...prev, pm25: v } : prev));
      } catch { /* swallow — transient network/edge case */ }
    }, 180);
    return () => { if (hoverFetchTimer.current) clearTimeout(hoverFetchTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hoverKey]);

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
        onMouseMove={handleMapMouseMove}
        onMouseLeave={handleMapMouseLeave}
        interactiveLayerIds={[]}
        transformRequest={(url: string, resourceType?: string) =>
          resourceType === 'Tile' && url.startsWith('/api/')
            ? { url, credentials: 'omit' as const }
            : { url }
        }
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
                'raster-opacity': viewMode === 'history'
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

        <StationMarkers features={features} zoomBand={zoomBand} onMarkerClick={handleMarkerClick} />
      </Map>

      {/* History-mode grid hover tooltip */}
      {viewMode === 'history' && selectedDate && hoverInfo && hoverInfo.pm25 != null && (
        <div
          className="pointer-events-none absolute z-40 rounded-md shadow-lg px-2.5 py-1.5"
          style={{
            left: hoverInfo.x + 14,
            top: hoverInfo.y + 14,
            background: 'rgba(15, 23, 42, 0.95)',
            border: '1px solid rgba(255,255,255,0.12)',
            color: 'white',
            minWidth: 140,
          }}
        >
          <div className="text-[9px] uppercase tracking-wider" style={{ color: 'rgba(255,255,255,0.5)' }}>
            Estimated PM2.5
          </div>
          <div className="text-sm font-semibold leading-tight">
            {hoverInfo.pm25.toFixed(1)}
            <span className="text-[10px] font-normal ml-1" style={{ color: 'rgba(255,255,255,0.55)' }}>µg/m³</span>
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: 'rgba(255,255,255,0.7)' }}>
            {formatDateLabel(selectedDate)} · Grid cell daily mean
          </div>
          <div className="text-[9px] mt-0.5" style={{ color: 'rgba(255,255,255,0.45)' }}>
            Estimated for this grid cell
          </div>
        </div>
      )}
    </div>
  );
}