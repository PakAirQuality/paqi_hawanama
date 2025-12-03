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

interface StationDetailPanelProps {
  stationId: string | null
  stations?: Station[]
}

export function StationDetailPanel({ stationId, stations }: StationDetailPanelProps) {
  const station = stations?.find(s => s.station_id === stationId)
  
  if (!stationId || !station) {
    return (
      <Card className="h-[600px]">
        <CardContent className="flex items-center justify-center h-full">
          <div className="text-center">
            <div className="text-4xl mb-3">🎯</div>
            <h3 className="text-lg font-medium text-gray-700 mb-2">
              Select a Station
            </h3>
            <p className="text-gray-500 text-sm">
              Choose a station from the list or map to view detailed information and analysis.
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }
  
  const getAqiLevel = (pm25?: number) => {
    if (!pm25) return { level: 'Unknown', color: 'bg-gray-500' }
    if (pm25 <= 12) return { level: 'Good', color: 'bg-green-500' }
    if (pm25 <= 35) return { level: 'Moderate', color: 'bg-yellow-500' }
    if (pm25 <= 55) return { level: 'Unhealthy for Sensitive', color: 'bg-orange-500' }
    if (pm25 <= 150) return { level: 'Unhealthy', color: 'bg-red-500' }
    return { level: 'Hazardous', color: 'bg-purple-900' }
  }
  
  const aqiInfo = getAqiLevel(station.pm25_latest)
  
  return (
    <Card className="h-[600px]">
      <CardHeader>
        <CardTitle className="text-lg font-semibold flex items-center space-x-2">
          <span>📊</span>
          <span>Station Details</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Station Identity */}
        <div className="space-y-3">
          <div>
            <h3 className="font-semibold text-gray-900 truncate">
              {station.name}
            </h3>
            <p className="text-sm text-gray-600">
              {station.city || 'Unknown City'}
            </p>
          </div>
          
          <div className="flex items-center space-x-2">
            <Badge 
              className={`text-xs ${
                station.active
                  ? 'bg-green-100 text-green-700 border-green-200'
                  : 'bg-red-100 text-red-700 border-red-200'
              }`}
            >
              {station.active ? 'Online' : 'Offline'}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {station.provider || 'Unknown'}
            </Badge>
          </div>
        </div>
        
        {/* Current Reading */}
        <div className="bg-gray-50 rounded-lg p-4 space-y-3">
          <h4 className="font-medium text-gray-800">Current Reading</h4>
          
          {station.pm25_latest ? (
            <div className="space-y-2">
              <div className="flex items-center space-x-3">
                <div className={`w-4 h-4 rounded-full ${aqiInfo.color}`}></div>
                <div>
                  <div className="text-lg font-bold">
                    {station.pm25_latest.toFixed(1)} μg/m³
                  </div>
                  <div className="text-sm text-gray-600">{aqiInfo.level}</div>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-gray-500 text-sm">
              No recent data available
            </div>
          )}
        </div>
        
        {/* Uptime Status */}
        {station.uptime_30d !== undefined && (
          <div className="space-y-3">
            <h4 className="font-medium text-gray-800">30-Day Uptime</h4>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Availability</span>
                <span className="font-medium">
                  {(station.uptime_30d * 100).toFixed(1)}%
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all ${
                    station.uptime_30d > 0.95
                      ? 'bg-green-500'
                      : station.uptime_30d > 0.85
                      ? 'bg-yellow-500'
                      : 'bg-red-500'
                  }`}
                  style={{ width: `${station.uptime_30d * 100}%` }}
                ></div>
              </div>
              <div className="text-xs text-gray-500">
                {station.uptime_30d > 0.95
                  ? 'Excellent uptime'
                  : station.uptime_30d > 0.85
                  ? 'Good uptime'
                  : 'Poor uptime - needs attention'}
              </div>
            </div>
          </div>
        )}
        
        {/* Quick Actions */}
        <div className="space-y-2">
          <h4 className="font-medium text-gray-800">Quick Actions</h4>
          <div className="space-y-2">
            <button className="w-full text-left p-2 text-sm text-gray-600 hover:bg-gray-100 rounded transition-colors">
              📈 View Historical Data
            </button>
            <button className="w-full text-left p-2 text-sm text-gray-600 hover:bg-gray-100 rounded transition-colors">
              🔧 Quality Control Report
            </button>
            <button className="w-full text-left p-2 text-sm text-gray-600 hover:bg-gray-100 rounded transition-colors">
              📊 Export Data
            </button>
            <button className="w-full text-left p-2 text-sm text-gray-600 hover:bg-gray-100 rounded transition-colors">
              ⚙️ Station Settings
            </button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}