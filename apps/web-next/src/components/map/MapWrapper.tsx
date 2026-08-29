'use client'

import dynamic from 'next/dynamic'
import { MAP_CONFIG } from './config/mapConfig'

// Dynamic import to avoid SSR issues with Mapbox GL JS
const MapRefactored = dynamic(() => import('./MapRefactored'), { 
  ssr: false,
  loading: () => (
    <div className="w-full h-full bg-gray-100 flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"></div>
        <p className="text-gray-600">Loading map...</p>
      </div>
    </div>
  )
})

interface MapWrapperProps {
  className?: string
  heatmapVisible?: boolean
  windVisible?: boolean
  modelVariant?: 'backbone' | 'support_aware'
  viewMode?: 'live' | 'estimated'
  selectedDate?: string | null
  availableDates?: string[]
}

export default function MapWrapper({ className, heatmapVisible = true, windVisible = false, modelVariant = 'backbone', viewMode = 'live', selectedDate = null, availableDates = [] }: MapWrapperProps) {
  return (
    <div className={`${className}`} style={{
      width: '100%',
      height: '100%',
      transform: 'translate3d(0, 0, 0)', // Force GPU acceleration
      willChange: 'transform' // Optimize for animations
    }}>
      <MapRefactored
        className="w-full h-full"
        center={MAP_CONFIG.center}
        zoom={MAP_CONFIG.zoom}
        heatmapVisible={heatmapVisible}
        windVisible={windVisible}
        modelVariant={modelVariant}
        viewMode={viewMode}
        selectedDate={selectedDate}
        availableDates={availableDates}
      />
    </div>
  )
}