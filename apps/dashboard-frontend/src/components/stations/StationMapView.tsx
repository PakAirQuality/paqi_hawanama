'use client'

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface Station {
  station_id: string
  name: string
  city?: string | null
  provider?: string | null
  active?: boolean
  uptime_30d?: number
  pm25_latest?: number
  aqi_latest?: number
}

interface StationMapViewProps {
  stations?: Station[]
  selectedStation: string | null
  onStationSelect: (stationId: string) => void
}

export function StationMapView({ stations, selectedStation, onStationSelect }: StationMapViewProps) {
  return (
    <Card className="h-[600px]">
      <CardHeader>
        <CardTitle className="text-lg font-semibold flex items-center space-x-2">
          <span>🗺️</span>
          <span>Interactive Station Map</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[500px] bg-gradient-to-br from-blue-50 to-green-50 rounded-lg border-2 border-dashed border-gray-300 flex items-center justify-center">
          <div className="text-center max-w-md">
            <div className="text-4xl mb-4">🗺️</div>
            <h3 className="text-xl font-semibold text-gray-700 mb-2">
              Interactive Station Map
            </h3>
            <p className="text-gray-600 mb-4">
              This will show a Mapbox GL JS map with all monitoring stations plotted by location, colored by their current status and AQI levels.
            </p>
            
            <div className="grid grid-cols-2 gap-3 text-sm text-left bg-white p-4 rounded-lg shadow-sm">
              <div className="flex items-center space-x-2">
                <div className="w-3 h-3 bg-green-500 rounded-full"></div>
                <span>Active (Good)</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-3 h-3 bg-yellow-500 rounded-full"></div>
                <span>Active (Moderate)</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-3 h-3 bg-orange-500 rounded-full"></div>
                <span>Active (Unhealthy)</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="w-3 h-3 bg-red-500 rounded-full"></div>
                <span>Offline/Critical</span>
              </div>
            </div>
            
            <div className="mt-4">
              <Badge variant="outline" className="text-xs">
                Map Integration: Phase 2
              </Badge>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}