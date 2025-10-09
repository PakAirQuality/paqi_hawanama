'use client';

import { useEffect, useState, useMemo } from 'react';
import 'mapbox-gl/dist/mapbox-gl.css';
import Map, { Marker, Source, Layer, type ViewStateChangeEvent } from 'react-map-gl/mapbox';
import { useStationSidebar } from '@/stores/stationSidebar';

// Modular imports
import { useStationsData } from './hooks/useStationsData';
import AqiMarker from './components/AqiMarker';

interface MapProps {
  center?: [number, number];
  zoom?: number;
  className?: string;
  heatmapVisible?: boolean;
}

export default function MapRefactored({ 
  center, 
  zoom, 
  className = '', 
  heatmapVisible = true
}: MapProps) {
  const { openStation } = useStationSidebar();
  const { stations, loading, error } = useStationsData();

  const [viewport, setViewport] = useState({
    longitude: center?.[0] || 69.3451,
    latitude: center?.[1] || 30.3753,
    zoom: zoom || 5,
  });

  const [bounds, setBounds] = useState<[number, number, number, number] | undefined>();
  const [map, setMap] = useState<any>(null);

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

  const handleProvinceClick = (e: any) => {
    if (e.features?.[0]) {
      const province = e.features[0];
      console.log('Province clicked:', province.properties);
      
      // Calculate bounds for the province geometry
      if (province.geometry.type === 'Polygon' || province.geometry.type === 'MultiPolygon') {
        const coordinates = province.geometry.type === 'Polygon' 
          ? province.geometry.coordinates[0]
          : province.geometry.coordinates.flat(2);
        
        // Calculate bounding box
        let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
        
        coordinates.forEach((coord: [number, number]) => {
          const [lng, lat] = coord;
          minLng = Math.min(minLng, lng);
          minLat = Math.min(minLat, lat);
          maxLng = Math.max(maxLng, lng);
          maxLat = Math.max(maxLat, lat);
        });
        
        // Add padding to the bounds
        const padding = 0.1;
        const boundsArray: [[number, number], [number, number]] = [
          [minLng - padding, minLat - padding],
          [maxLng + padding, maxLat + padding]
        ];
        
        // Fit map to province bounds
        if (map) {
          map.fitBounds(boundsArray, {
            padding: 50,
            duration: 1000
          });
        }
      }
    }
  };

  const handleMapChange = (evt: ViewStateChangeEvent) => {
    setViewport(evt.viewState);
    setBounds(evt.target.getBounds().toArray().flat() as [number, number, number, number]);
    
    // Console log zoom level for development
    if (process.env.NODE_ENV === 'development' && evt.viewState?.zoom !== undefined) {
      console.log('🔍 Map Zoom Level:', evt.viewState.zoom.toFixed(2));
    }
    
    // Capture map instance on first load
    if (!map) {
      setMap(evt.target);
    }
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
    <div className={`w-full h-full relative ${className}`} style={{ 
      maxWidth: '100vw', 
      maxHeight: '100vh',
      overflow: 'hidden'
    }}>
      <Map
        {...viewport}
        zoom={viewport?.zoom || 5}
        mapboxAccessToken={process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN}
        mapStyle="mapbox://styles/mapbox/outdoors-v12"
        onMove={handleMapChange}
        onLoad={handleMapChange}
        style={{ 
          width: '100%', 
          height: '100%',
          maxWidth: '100vw',
          maxHeight: '100vh'
        }}
        maxPitch={60}
        attributionControl={false}
        touchZoomRotate={true}
        touchPitch={false}
        dragPan={true}
        scrollZoom={true}
        doubleClickZoom={true}
        keyboard={false}
      >
        {/* Pakistan boundary with green outline and shading */}
        <Source
          id="pakistan-boundary"
          type="geojson"
          data="/pakistan.geojson"
        >
          {/* Pakistan fill layer removed */}
          
          {/* Pakistan outline - hidden */}
          <Layer
            id="pakistan-outline"
            type="line"
            paint={{
              'line-color': 'transparent',
              'line-width': 0,
              'line-opacity': 0
            }}
          />
        </Source>

        {/* Provincial boundaries */}
        <Source
          id="pakistan-provinces"
          type="geojson"
          data="/pakistan_provinces.geojson"
        >
          {/* Province fill for hover effect - hidden */}
          <Layer
            id="provinces-fill"
            type="fill"
            paint={{
              'fill-color': 'transparent',
              'fill-opacity': 0
            }}
            onMouseEnter={(e) => {
              if (e.features?.[0] && map) {
                map.setFeatureState(
                  { source: 'pakistan-provinces', id: e.features[0].id },
                  { hover: true }
                );
                // Change cursor to pointer
                map.getCanvas().style.cursor = 'pointer';
              }
            }}
            onMouseLeave={(e) => {
              if (e.features?.[0] && map) {
                map.setFeatureState(
                  { source: 'pakistan-provinces', id: e.features[0].id },
                  { hover: false }
                );
                // Reset cursor
                map.getCanvas().style.cursor = '';
              }
            }}
            onClick={handleProvinceClick}
          />
          
          {/* Province outline - hidden */}
          <Layer
            id="provinces-outline"
            type="line"
            paint={{
              'line-color': 'transparent',
              'line-width': 0,
              'line-opacity': 0
            }}
          />
        </Source>

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
                  zoom={viewport?.zoom || 5}
                />
              </div>
            </Marker>
          );
        })}
      </Map>
    </div>
  );
}