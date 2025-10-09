'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { WeatherData } from '@/lib/api'

interface WeatherCardProps {
  weatherData?: WeatherData
  title?: string
  description?: string
}

export default function WeatherCard({ 
  weatherData, 
  title = "Weather Conditions",
  description = "Current meteorological data"
}: WeatherCardProps) {
  if (!weatherData) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-gray-500">No weather data available</p>
        </CardContent>
      </Card>
    )
  }

  const getWindDirection = (degrees?: number) => {
    if (degrees === undefined) return 'N/A'
    const directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    const index = Math.round(degrees / 22.5) % 16
    return directions[index]
  }

  const formatValue = (value?: number, unit: string = '', decimals: number = 1) => {
    if (value === undefined || value === null) return 'N/A'
    return `${value.toFixed(decimals)}${unit}`
  }

  const getWeatherIcon = (iconCode?: string) => {
    // Map IQAir weather icon codes to descriptive text or icons
    const iconMap: Record<string, string> = {
      '01d': '☀️', '01n': '🌙', // clear sky
      '02d': '⛅', '02n': '☁️', // few clouds
      '03d': '☁️', '03n': '☁️', // scattered clouds
      '04d': '☁️', '04n': '☁️', // broken clouds
      '09d': '🌧️', '09n': '🌧️', // shower rain
      '10d': '🌦️', '10n': '🌧️', // rain
      '11d': '⛈️', '11n': '⛈️', // thunderstorm
      '13d': '❄️', '13n': '❄️', // snow
      '50d': '🌫️', '50n': '🌫️', // mist
    }
    return iconMap[iconCode || ''] || '🌤️'
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <span className="text-2xl">{getWeatherIcon(weatherData.weather_icon)}</span>
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          
          {/* Temperature */}
          <div className="space-y-1">
            <p className="text-sm font-medium text-gray-600">Temperature</p>
            <p className="text-2xl font-bold text-blue-600">
              {formatValue(weatherData.temperature, '°C', 1)}
            </p>
          </div>

          {/* Humidity */}
          <div className="space-y-1">
            <p className="text-sm font-medium text-gray-600">Humidity</p>
            <p className="text-2xl font-bold text-cyan-600">
              {formatValue(weatherData.humidity, '%', 0)}
            </p>
          </div>

          {/* Pressure */}
          <div className="space-y-1">
            <p className="text-sm font-medium text-gray-600">Pressure</p>
            <p className="text-2xl font-bold text-purple-600">
              {formatValue(weatherData.pressure, ' hPa', 0)}
            </p>
          </div>

          {/* Wind Speed */}
          <div className="space-y-1">
            <p className="text-sm font-medium text-gray-600">Wind Speed</p>
            <p className="text-2xl font-bold text-green-600">
              {formatValue(weatherData.wind_speed, ' m/s', 1)}
            </p>
          </div>

          {/* Wind Direction */}
          <div className="space-y-1">
            <p className="text-sm font-medium text-gray-600">Wind Direction</p>
            <p className="text-2xl font-bold text-emerald-600">
              {getWindDirection(weatherData.wind_direction)}
              {weatherData.wind_direction !== undefined && (
                <span className="text-sm text-gray-500 ml-1">
                  ({weatherData.wind_direction}°)
                </span>
              )}
            </p>
          </div>

          {/* Heat Index */}
          <div className="space-y-1">
            <p className="text-sm font-medium text-gray-600">Heat Index</p>
            <p className="text-2xl font-bold text-orange-600">
              {formatValue(weatherData.heat_index, '°C', 1)}
            </p>
          </div>

        </div>

        {/* Last Updated */}
        {weatherData.timestamp && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <p className="text-xs text-gray-500">
              Last updated: {new Date(weatherData.timestamp).toLocaleString()}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}