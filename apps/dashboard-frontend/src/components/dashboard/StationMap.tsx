'use client'

import { ChartWidget } from '@/components/charts/ChartWidget'
import { Badge } from '@/components/ui/badge'

interface Station {
  station_id: string
  name: string
  city?: string
  provider?: string
  active?: boolean
  pm25_latest?: number
}

interface StationMapProps {
  stations?: Station[]
}

export function StationMap({ stations }: StationMapProps) {
  const getStatusColor = (station: Station) => {
    if (!station.active) return 'bg-red-500'
    if (station.pm25_latest === undefined) return 'bg-gray-500'
    if (station.pm25_latest <= 50) return 'bg-green-500'
    if (station.pm25_latest <= 100) return 'bg-yellow-500'
    if (station.pm25_latest <= 150) return 'bg-orange-500'
    return 'bg-red-500'
  }
  
  const headerActions = (
    <div className="flex items-center space-x-2">
      <button className="px-3 py-1 text-xs bg-gray-100 text-gray-700 rounded-full hover:bg-gray-200 transition-colors">
        Hourly
      </button>
      <button className="px-3 py-1 text-xs text-gray-600 hover:text-gray-800 transition-colors">
        📍
      </button>
    </div>
  )
  
  return (
    <ChartWidget 
      title="Station Network Overview"
      subtitle="Real-time status of monitoring stations"
      headerActions={headerActions}
      minHeight="400px"
    >
      <div className="mb-4">
        {/* Station Status Legend */}
        <div className="flex flex-wrap gap-3 text-xs">
          <div className="flex items-center space-x-1">
            <div className="w-3 h-3 bg-green-500 rounded-full"></div>
            <span>Active</span>
          </div>
          <div className="flex items-center space-x-1">
            <div className="w-3 h-3 bg-yellow-500 rounded-full"></div>
            <span>Warning</span>
          </div>
          <div className="flex items-center space-x-1">
            <div className="w-3 h-3 bg-red-500 rounded-full"></div>
            <span>Offline</span>
          </div>
          <div className="flex items-center space-x-1">
            <div className="w-3 h-3 bg-gray-500 rounded-full"></div>
            <span>Unknown</span>
          </div>
        </div>
      </div>
      
      <div className="flex items-center justify-center h-64 bg-slate-50 rounded-lg border-2 border-dashed border-slate-300">
        <div className="text-center">
          <div className="text-4xl mb-2">🗺️</div>
          <h4 className="font-medium text-gray-700">Station Map</h4>
          <p className="text-sm text-gray-500 mt-2">
            Interactive station map coming soon
          </p>
        </div>
      </div>
    </ChartWidget>
  )
}