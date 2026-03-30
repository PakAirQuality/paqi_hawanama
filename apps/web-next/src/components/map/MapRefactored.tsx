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

interface MapProps {
  center?: [number, number];
  zoom?: number;
  className?: string;
  heatmapVisible?: boolean;
  windVisible?: boolean;
  modelVariant?: 'backbone' | 'support_aware';
}

export default function MapRefactored({
  center,
  zoom,
  className = '',
  heatmapVisible = true,
  windVisible = true,
  modelVariant = 'backbone',
}: MapProps) {
  const { openStation } = useStationSidebar();
  const { stations, loading, error } = useStationsData();

  const [viewport, setViewport] = useState({
    longitude: center?.[0] || 78,
    latitude: center?.[1] || 22,
    zoom: zoom ?? 3.6,
  });

  const [bounds, setBounds] = useState<[number, number, number, number] | undefined>();
  const [map, setMap] = useState<any>(null);

  // Prediction tile URL — uses the latest available date
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://hawanama-152782825429.asia-south1.run.app/api';
  const predDate = '2026-03-14'; // TODO: fetch latest from API
  const modelParam = modelVariant === 'support_aware' ? '&model=support_aware' : '';
  const tileUrl = `${API_BASE}/v1/ops/pipeline/tiles/${predDate}/{z}/{x}/{y}.png?smoothed=true${modelParam}`;

  // Wind layer (lazy — only fetches data when toggled on)
  const { windImage, windMetadata } = useWindData(windVisible);
  useWindLayer(map, windImage, windMetadata, windVisible);

  const features = useMemo(() => {
    // Return all individual stations
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

  const handleMarkerClick = (feature: any) => {
    const { properties } = feature;
    // Open the station sidebar for all markers (individual stations only)
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

  // Loading state
  if (loading) {
    return (
      <div className={`flex items-center justify-center bg-gray-100 ${className}`}>
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"></div>
          <p className="text-gray-600">Loading stations...</p>
        </div>
      </div>
    );
  }

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
        mapboxAccessToken={process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || '***REMOVED***'}
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
        maxTileCacheSize={200}
        renderWorldCopies={false}
        optimizeForTerrain={false}
        antialias={false}
        // Smooth transitions
        transitionDuration={300}
        pitchWithRotate={false}
      >
        {/* PM2.5 prediction layer removed from public site */}

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