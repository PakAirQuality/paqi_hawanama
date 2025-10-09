'use client';

import { useEffect, useState, useMemo } from 'react';
import 'mapbox-gl/dist/mapbox-gl.css';
import Map, { Marker, Source, Layer, type ViewStateChangeEvent } from 'react-map-gl/mapbox';
import { useStationSidebar } from '@/stores/stationSidebar';

// Modular imports
import { useStationsData } from './hooks/useStationsData';
import { useSupercluster } from './hooks/useSupercluster';
import AqiMarker from './components/AqiMarker';

interface MapProps {
  center?: [number, number];
  zoom?: number;
  className?: string;
  heatmapVisible?: boolean;
  clusteringEnabled?: boolean;
}

export default function MapRefactored({ 
  center, 
  zoom, 
  className = '', 
  heatmapVisible = true,
  clusteringEnabled = true 
}: MapProps) {
  const { openStation } = useStationSidebar();
  const { stations, loading, error } = useStationsData();
  const supercluster = useSupercluster(stations);

  const [viewport, setViewport] = useState({
    longitude: center?.[0] || 69.3451,
    latitude: center?.[1] || 30.3753,
    zoom: zoom || 5,
  });

  const [bounds, setBounds] = useState<[number, number, number, number] | undefined>();
  const [map, setMap] = useState<any>(null);

  const features = useMemo(() => {
    if (!bounds || !viewport) return [];

    // If clustering is disabled, return all individual stations
    if (!clusteringEnabled || !supercluster) {
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
    }

    const clusters = supercluster.getClusters(bounds, Math.floor(viewport.zoom));

    // Calculate the average PM2.5 for each cluster and preserve AQI for individual stations
    const result = clusters.map(cluster => {
      if (cluster.properties.cluster) {
        // For clusters, avg_pm25 is already calculated in reduce function
        // cluster.properties.avg_pm25 should be available
      } else {
        // For individual stations, ensure we have both AQI and PM2.5 data
        cluster.properties.aqi = cluster.properties.aqi_raw || cluster.properties.aqi;
        cluster.properties.pm25 = cluster.properties.pm25; // PM2.5 value for individual stations
      }
      return cluster;
    });

    return result;
  }, [supercluster, bounds, viewport, stations, clusteringEnabled]);

  const handleMarkerClick = async (feature: any) => {
    const { geometry, properties } = feature;
    const [longitude, latitude] = geometry.coordinates;

    if (!supercluster) return;

    if (properties.cluster) {
      try {
        const zoom = await supercluster.getClusterExpansionZoom(properties.cluster_id);
        setViewport({ longitude, latitude, zoom });
      } catch (err) {
        console.error("Error getting cluster expansion zoom:", err);
      }
    } else {
      // For individual stations, open the sidebar
      openStation(String(properties.id));
    }
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
    <div className={`w-full relative ${className}`} style={{ height: 'calc(100vh - 120px)' }}>
      <Map
        {...viewport}
        mapboxAccessToken={process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN}
        mapStyle="mapbox://styles/mapbox/outdoors-v12"
        onMove={handleMapChange}
        onLoad={handleMapChange}
        style={{ width: '100%', height: '100%' }}
        maxPitch={60}
        attributionControl={false}
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
          const isCluster = feature.properties.cluster;
          const pointId = isCluster ? feature.properties.cluster_id : feature.properties.id;
          const key = `marker-${pointId}`;

          return (
            <Marker
              key={key}
              longitude={feature.geometry.coordinates[0]}
              latitude={feature.geometry.coordinates[1]}
            >
              <div onClick={() => handleMarkerClick(feature)}>
                <AqiMarker
                  isCluster={!!isCluster}
                  aqi={feature.properties.aqi}
                  avg_aqi={feature.properties.avg_aqi}
                  pm25={feature.properties.pm25}
                  avg_pm25={feature.properties.avg_pm25}
                  point_count={feature.properties.point_count}
                  zoom={viewport.zoom}
                />
              </div>
            </Marker>
          );
        })}
      </Map>
    </div>
  );
}