'use client'

import dynamic from 'next/dynamic'

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
}

export default function MapWrapper({ className, heatmapVisible = true }: MapWrapperProps) {
  return (
    <div className={`${className}`} style={{ minHeight: '400px' }}>
      <MapRefactored 
        className="w-full h-full" 
        heatmapVisible={heatmapVisible}
      />
    </div>
  )
}