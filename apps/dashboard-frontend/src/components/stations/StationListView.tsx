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

interface StationListViewProps {
  stations?: Station[]
  selectedStation: string | null
  onStationSelect: (stationId: string) => void
}

export function StationListView({ stations, selectedStation, onStationSelect }: StationListViewProps) {
  return (
    <Card className="h-[600px]">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold flex items-center space-x-2">
            <span>📋</span>
            <span>Station List</span>
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            {stations?.length || 0} stations
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="h-[500px] overflow-y-auto">
          {!stations ? (
            <div className="p-6 text-center text-gray-500">
              Loading stations...
            </div>
          ) : stations.length === 0 ? (
            <div className="p-6 text-center text-gray-500">
              No stations found
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {stations.map((station) => (
                <div
                  key={station.station_id}
                  onClick={() => onStationSelect(station.station_id)}
                  className={`p-4 cursor-pointer transition-colors hover:bg-gray-50 ${
                    selectedStation === station.station_id
                      ? 'bg-blue-50 border-r-4 border-blue-500'
                      : ''
                  }`}
                >
                  <div className="space-y-2">
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-sm truncate">
                          {station.name}
                        </div>
                        <div className="text-xs text-gray-600 mt-1">
                          {station.city || 'Unknown'} • {station.provider || 'Unknown'}
                        </div>
                      </div>
                      <div className="flex flex-col items-end space-y-1">
                        <Badge 
                          className={`text-xs ${
                            station.active
                              ? 'bg-green-100 text-green-700 border-green-200'
                              : 'bg-red-100 text-red-700 border-red-200'
                          }`}
                        >
                          {station.active ? 'Online' : 'Offline'}
                        </Badge>
                        {station.pm25_latest && (
                          <div className="text-xs font-medium">
                            {station.pm25_latest.toFixed(1)} μg/m³
                          </div>
                        )}
                      </div>
                    </div>
                    
                    {/* Progress bars for uptime */}
                    {station.uptime_30d !== undefined && (
                      <div className="flex items-center space-x-2">
                        <div className="flex-1 bg-gray-200 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full transition-all ${
                              station.uptime_30d > 0.9
                                ? 'bg-green-500'
                                : station.uptime_30d > 0.7
                                ? 'bg-yellow-500'
                                : 'bg-red-500'
                            }`}
                            style={{ width: `${station.uptime_30d * 100}%` }}
                          ></div>
                        </div>
                        <div className="text-xs text-gray-500 w-12 text-right">
                          {(station.uptime_30d * 100).toFixed(0)}%
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}