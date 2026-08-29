import React from 'react';
import { STYLES } from '../config/mapConfig';

// Helper function to get the correct CSS class for AQI color
// Always use API-provided AQI value for consistent coloring
const getAqiColorClass = (aqi: number | null | undefined): string => {
  // Handle null/undefined/negative values (no reading)
  if (aqi === null || aqi === undefined || aqi <= 0) return 'bg-no-reading';
  
  // Use API-provided AQI value directly for color determination
  if (aqi <= 50) return 'bg-good';
  if (aqi <= 100) return 'bg-moderate';
  if (aqi <= 150) return 'bg-unhealthy-sensitive';
  if (aqi <= 200) return 'bg-unhealthy';
  if (aqi <= 300) return 'bg-very-unhealthy';
  return 'bg-hazardous';
};

interface AqiMarkerProps {
  aqi?: number;
  pm25?: number;
  isCluster: boolean;
  zoom?: number;
}

const AqiMarker: React.FC<AqiMarkerProps> = ({ aqi, pm25, isCluster, zoom = 5 }) => {
  // Use config values for base size - only points since no clustering
  const markerSize = STYLES.point.radius;

  // Debug logging for data inconsistency tracking
  if (process.env.NODE_ENV === 'development' && typeof pm25 === 'number' && pm25 > 0) {
    console.log('🗺️ Map marker data:', { pm25, aqi, zoom });
  }

  // Show PM2.5 value
  const displayValue = pm25 ? Math.round(pm25) : '-';

  // Use API-provided AQI value for color determination
  const colorClass = getAqiColorClass(aqi);

  // Hide white/no-reading markers at lower zoom levels
  const isNoReadingMarker = colorClass === 'bg-no-reading';
  const shouldHideNoReading = isNoReadingMarker && zoom < 8;

  // Don't render no-reading markers at low zoom
  if (shouldHideNoReading) {
    return null;
  }

  // Hide text at very low zoom levels (globe view)
  const showText = zoom >= 3;
  
  // Make markers more compact at low zoom levels
  const isLowZoom = zoom < 3;
  const compactSize = isLowZoom ? Math.max(4, markerSize * 0.3) : markerSize;
  const actualSize = compactSize * 2;

  return (
    <div 
      className={`aqi-marker-container point ${isLowZoom ? 'low-zoom' : ''}`}
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