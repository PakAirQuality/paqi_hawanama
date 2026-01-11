'use client'

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'

interface Station {
  station_id: string
  name: string
  city?: string
  provider?: string
  active?: boolean
  uptime_30d?: number
  pm25_latest?: number
  last_seen?: string
}

interface AlertsPanelProps {
  stationsNeedingAttention: Station[]
  getStationStatus: (station: Station) => { label: string; color: string }
}

export function AlertsPanel({ stationsNeedingAttention, getStationStatus }: AlertsPanelProps) {
  return (
    <Card className="h-96">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold flex items-center space-x-2">
            <span>🚨</span>
            <span>System Alerts</span>
          </CardTitle>
          <Link href="/stations" className="text-sm text-blue-600 hover:text-blue-800">
            View All →
          </Link>
        </div>
        <p className="text-sm text-gray-600">
          Stations requiring immediate attention
        </p>
      </CardHeader>
      <CardContent>
        <div className="space-y-3 max-h-64 overflow-y-auto">
          {stationsNeedingAttention.length === 0 ? (
            <div className="text-center py-8">
              <div className="text-3xl mb-2">✅</div>
              <h4 className="font-medium text-gray-700">All Systems Normal</h4>
              <p className="text-sm text-gray-500 mt-1">
                No stations require attention at this time
              </p>
            </div>
          ) : (
            stationsNeedingAttention.map((station) => {
              const status = getStationStatus(station)
              return (
                <div
                  key={station.station_id}
                  className="p-3 bg-gray-50 rounded-lg hover:bg-gray-100 cursor-pointer transition-colors"
                  onClick={() => {
                    window.location.href = '/stations'
                  }}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center space-x-2">
                        <div className="font-medium text-sm truncate">
                          {station.name}
                        </div>
                        <Badge className={`text-xs ${status.color} border-0`}>
                          {status.label}
                        </Badge>
                      </div>
                      <div className="text-xs text-gray-600 mt-1">
                        {station.city} • {station.provider}
                      </div>
                      {station.uptime_30d !== undefined && (
                        <div className="text-xs text-gray-500 mt-1">
                          Uptime: {(station.uptime_30d * 100).toFixed(1)}%
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
        
        {stationsNeedingAttention.length > 0 && (
          <div className="mt-4 pt-3 border-t border-gray-200">
            <div className="text-xs text-gray-500 text-center">
              Showing {stationsNeedingAttention.length} critical alerts
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}