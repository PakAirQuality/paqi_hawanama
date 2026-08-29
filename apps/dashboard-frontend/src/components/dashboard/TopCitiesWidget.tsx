'use client'

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

interface CityData {
  city: string
  avg_aqi: number
  station_count: number
}

interface TopCitiesWidgetProps {
  topCities?: CityData[]
  getAqiColor: (aqi: number) => string
}

export function TopCitiesWidget({ topCities, getAqiColor }: TopCitiesWidgetProps) {
  return (
    <Card className="h-96">
      <CardHeader>
        <CardTitle className="text-lg font-semibold flex items-center space-x-2">
          <span>🏙️</span>
          <span>Cities Overview</span>
        </CardTitle>
        <p className="text-sm text-gray-600">
          Current air quality by city
        </p>
      </CardHeader>
      <CardContent>
        <div className="space-y-3 max-h-64 overflow-y-auto">
          {!topCities ? (
            <div className="space-y-3">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="animate-pulse">
                  <div className="flex items-center justify-between p-3 bg-gray-50 rounded">
                    <div className="flex items-center space-x-3">
                      <div className="w-3 h-3 bg-gray-300 rounded-full"></div>
                      <div className="space-y-1">
                        <div className="h-4 bg-gray-300 rounded w-20"></div>
                        <div className="h-3 bg-gray-300 rounded w-16"></div>
                      </div>
                    </div>
                    <div className="h-4 bg-gray-300 rounded w-12"></div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            topCities.slice(0, 8).map((cityData, index) => (
              <div key={index} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
                <div className="flex items-center space-x-3">
                  <div 
                    className={`w-3 h-3 rounded-full ${getAqiColor(cityData.avg_aqi)}`}
                  ></div>
                  <div>
                    <div className="font-medium text-sm">{cityData.city}</div>
                    <div className="text-xs text-gray-600">
                      {cityData.station_count} station{cityData.station_count !== 1 ? 's' : ''}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-medium text-sm">
                    AQI {cityData.avg_aqi}
                  </div>
                  <div className="text-xs text-gray-500">24h avg</div>
                </div>
              </div>
            ))
          )}
        </div>
        
        {topCities && topCities.length > 8 && (
          <div className="mt-4 pt-3 border-t border-gray-200">
            <div className="text-xs text-gray-500 text-center">
              +{topCities.length - 8} more cities
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}