/**
 * Map configuration constants for Mapbox GL JS
 * Climate TRACE light relief style settings
 */

export const MAP_CONFIG = {
  style: 'mapbox://styles/mapbox/standard',
  center: [69.35, 30.38] as [number, number], // Pakistan center
  zoom: 3,
  projection: 'globe' as const, // Beautiful globe projection with 2D overlay
  accessToken: process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || '***REMOVED***',
  config: {
    basemap: {
      // Light canvas with relief for Climate TRACE style
      theme: 'faded',              // Softer contrast than 'default'
      lightPreset: 'day',          // Bright light; could try 'dusk' for depth
      show3dObjects: false,        // Clean and performant
      showAdminBoundaries: true,   // Geographic context
      showRoadLabels: true,        // Keep for navigation
      showPlaceLabels: true,       // Keep for context
      showTransitLabels: false     // Remove clutter
    }
  }
} as const

// Style configurations
export const STYLES = {
  cluster: { radius: 15, strokeWidth: 0, strokeColor: 'transparent', textSize: 12 },
  point: { radius: 13, strokeWidth: 0, strokeColor: 'transparent', textSize: 10, opacity: 1.0 },
  pakistan: { lineColor: '#065f46', lineWidth: 2, lineOpacity: 0.8 },
  countryFocus: {
    // Inside Pakistan - Climate TRACE style prominent green overlay
    insideFill: 'rgba(16, 185, 129, 0.25)',  // emerald-500 with 25% opacity - much more prominent
    insideStroke: '#059669',                  // emerald-600 for strong outline
    insideStrokeWidth: 2.5,
    insideStrokeOpacity: 0.8,
    // Outside Pakistan - stronger dimming for dramatic contrast  
    outsideFill: 'rgba(75, 85, 99, 0.6)',    // gray-600 with 60% opacity - much darker
    outsideOpacity: 0.6,
    // Vibrant green glow effect
    glowColor: 'rgba(16, 185, 129, 0.4)',    // emerald-500 with higher opacity
    glowWidth: 4,
    // Additional Climate TRACE-style elements
    innerGlow: 'rgba(52, 211, 153, 0.15)',   // emerald-400 for bright inner highlight
    shadowColor: 'rgba(6, 78, 59, 0.2)',     // emerald-900 for depth
    // Accent highlight for modern tech feel
    accentColor: 'rgba(167, 243, 208, 0.12)', // emerald-200 for subtle tech accent
  },
  provinces: {
    // Provincial boundary lines - enhanced visibility
    strokeColor: '#059669',          // emerald-600 for better visibility against green overlay
    strokeWidth: 2,                  // Slightly thicker for prominence
    strokeOpacity: 0.8,              // More opaque for clarity
    strokeDashArray: [4, 2],         // More pronounced dashed pattern
    // Enhanced hover effects
    hoverStrokeColor: '#047857',     // emerald-700 for strong hover contrast
    hoverStrokeWidth: 3,             // Prominent hover width
    hoverStrokeOpacity: 1,           // Full opacity on hover
    hoverStrokeDashArray: [6, 2],    // Different dash pattern for hover
    // Fill for interactive areas
    fillColor: 'transparent',
    hoverFillColor: 'rgba(16, 185, 129, 0.15)', // More visible hover fill
    // Additional glow effect for interactivity
    glowColor: 'rgba(5, 150, 105, 0.4)',        // emerald-600 glow
    glowWidth: 4,
    hoverGlowColor: 'rgba(4, 120, 87, 0.6)',    // emerald-700 hover glow
    hoverGlowWidth: 5
  },
  heatmap: {
    // Zoom levels for heatmap visibility - now covers low zoom levels
    minZoom: 2,
    maxZoom: 7,
    // AQI weight mapping (0-500 AQI -> 0-1 weight)
    weightStops: [
      [0, 0.00],     // No AQI
      [50, 0.10],    // Good
      [100, 0.25],   // Moderate
      [150, 0.45],   // Unhealthy for Sensitive
      [200, 0.65],   // Unhealthy
      [300, 0.85],   // Very Unhealthy
      [500, 1.00]    // Hazardous
    ],
    // Intensity scaling with zoom
    intensity: {
      minZoom: 3,
      minValue: 0.8,   // Lower intensity to prevent saturation
      maxZoom: 12,
      maxValue: 1.5    // Moderate max intensity for proper color mapping
    },
    // Radius scaling with zoom for natural, cloudy appearance
    radius: {
      minZoom: 3,
      minValue: 35,    // Larger radius for more dispersed, cloudy effect
      midZoom: 6,
      midValue: 55,    // Bigger mid-range for natural spread
      maxZoom: 10,
      maxValue: 80     // Large radius for organic cloud-like blobs
    },
    // Opacity fading with zoom for natural, atmospheric effect
    opacity: {
      minZoom: 3,
      minValue: 0.75,   // More transparent for subtle, cloudy appearance
      maxZoom: 10,
      maxValue: 0.45    // Fade out more gradually for natural transition
    },
    // Color stops for heatmap density
    colorStops: [
      [0.00, 'rgba(0,0,0,0)'],      // Transparent
      [0.10, '#16a34a'],            // Good (green)
      [0.25, '#ca8a04'],            // Moderate (amber)
      [0.45, '#ea580c'],            // Unhealthy Sensitive (orange)
      [0.65, '#dc2626'],            // Unhealthy (red)
      [0.85, '#a070b5'],            // Very Unhealthy (purple)
      [1.00, '#991b1b']             // Hazardous (dark red)
    ]
  },
  hexagon: {
    // Zoom levels for hexagon visibility (opposite to clusters)
    minZoom: 0,
    maxZoom: 6,  // Fade out as clusters fade in
    // Hexagon configuration - smaller, more granular
    radius: {
      minZoom: 0,
      minValue: 25000,   // 25km at low zoom for better granularity
      maxZoom: 6,
      maxValue: 8000     // 8km at high zoom for detailed coverage
    },
    // Height scaling based on AQI
    elevation: {
      scale: 2000,      // Much larger elevation multiplier
      range: [0, 20000] // Much taller hexagons - up to 20km high
    },
    // Opacity transitions (inverted - high at low zoom)
    opacity: {
      minZoom: 0,
      minValue: 0.85,   // Very solid but not completely opaque
      maxZoom: 6,
      maxValue: 0.0     // Invisible at zoom 6+
    },
    // Professional AQI color palette - vibrant and clear
    colorRange: [
      [16, 185, 129],   // Good (emerald-500) - clean, fresh green
      [245, 158, 11],   // Moderate (amber-500) - warm yellow-orange
      [251, 146, 60],   // Unhealthy for Sensitive (orange-400) - clear orange
      [239, 68, 68],    // Unhealthy (red-500) - strong red
      [160, 112, 181],   // Very Unhealthy (custom purple) - vivid purple
      [127, 29, 29]     // Hazardous (red-900) - dark maroon
    ],
    // Domain for color scaling (AQI ranges) - adjusted for typical values
    colorDomain: [0, 200],  // Most AQI values are 0-200, not 0-500
    // Enable extrusion for 3D effect
    extruded: true,
    // Coverage area - full coverage for maximum visibility
    coverage: 1.0
  }
} as const