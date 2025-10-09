import React from 'react';
import { pm25ToAQI } from '../config/aqiStyles';
import { STYLES } from '../config/mapConfig';

// Helper function to get the correct CSS class for AQI color
// Now works with PM2.5 values converted to AQI for color
const getAqiColorClass = (pm25: number | null | undefined): string => {
  // Handle null/undefined values (no reading)
  if (pm25 === null || pm25 === undefined) return 'bg-no-reading';
  
  // Convert PM2.5 to AQI for color determination
  const aqi = pm25ToAQI(pm25);
  
  // Handle actual AQI values
  if (aqi === 0) return 'bg-no-reading'; // Treat 0 as no reading
  if (aqi <= 50) return 'bg-good';
  if (aqi <= 100) return 'bg-moderate';
  if (aqi <= 150) return 'bg-unhealthy-sensitive';
  if (aqi <= 200) return 'bg-unhealthy';
  if (aqi <= 300) return 'bg-very-unhealthy';
  return 'bg-hazardous';
};

interface AqiMarkerProps {
  aqi?: number;
  avg_aqi?: number;
  pm25?: number;
  avg_pm25?: number;
  point_count?: number;
  isCluster: boolean;
  zoom?: number;
}

const AqiMarker: React.FC<AqiMarkerProps> = ({ aqi, avg_aqi, pm25, avg_pm25, point_count, isCluster, zoom = 5 }) => {
  // Use config values for base size - no zoom scaling
  const markerSize = isCluster ? STYLES.cluster.radius : STYLES.point.radius;
  // Debug logging
  if (!isCluster) {
    console.log('AqiMarker individual station:', { aqi, avg_aqi, pm25, avg_pm25, point_count, isCluster });
  }

  // Show PM2.5 values: 'avg_pm25' for clusters, 'pm25' for individual stations
  const pm25ValueToShow = isCluster ? avg_pm25 : pm25;
  const displayValue = pm25ValueToShow ? Math.round(pm25ValueToShow) : '-';

  // Use PM2.5 values for color determination
  const colorValue = isCluster ? avg_pm25 : pm25;
  const colorClass = getAqiColorClass(colorValue);

  // Hide text at very low zoom levels (globe view)
  const showText = zoom >= 3;
  
  // Make markers more compact at low zoom levels
  const isLowZoom = zoom < 3;
  const compactSize = isLowZoom ? Math.max(4, markerSize * 0.3) : markerSize;
  const actualSize = compactSize * 2;

  return (
    <div 
      className={`aqi-marker-container ${isCluster ? 'cluster' : 'point'} ${isLowZoom ? 'low-zoom' : ''}`}
      style={{
        width: `${actualSize}px`,
        height: `${actualSize}px`
      }}
    >
      <div 
        className={`aqi-marker ${colorClass}`}
        style={{
          width: `${actualSize}px`,
          height: `${actualSize}px`,
          fontSize: `${Math.max(8, compactSize - 2)}px`
        }}
      >
        {showText && <span>{displayValue}</span>}
      </div>
    </div>
  );
};

export default AqiMarker;