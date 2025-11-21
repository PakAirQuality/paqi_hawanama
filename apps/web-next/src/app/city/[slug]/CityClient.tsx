'use client'

import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { CitySearch } from '@/components/ui/CitySearch'
import Link from 'next/link'
import { ArrowLeft, Thermometer, Droplets, Wind } from 'lucide-react'
import AQIChart from '@/components/charts/AQIChart'
import CityMap from '@/components/city/CityMap'
import WeatherCard from '@/components/weather/WeatherCard'
import { getAQIColorByValue } from '@/components/map/config/aqiStyles'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts'

// Compact rectangular AQI box component for city page with black text - responsive sizing
const CityAQIBox: React.FC<{ value: number }> = ({ value }) => {
  return (
    <div 
      className="w-16 h-12 sm:w-24 sm:h-20 rounded-lg flex flex-col items-center justify-center text-black font-bold shadow-md border border-black/10"
      style={{ backgroundColor: getAQIColorByValue(value) }}
    >
      <div className="text-lg sm:text-2xl font-bold leading-tight">{Math.round(value) || '--'}</div>
      <div className="text-[10px] sm:text-xs font-medium -mt-0.5">AQI</div>
    </div>
  )
}

interface CityClientProps {
  citySlug: string
}

export default function CityClient({ citySlug }: CityClientProps) {
  const [chartMetric, setChartMetric] = useState<'aqi' | 'pm25'>('aqi')
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const checkIsMobile = () => {
      setIsMobile(window.innerWidth <= 768)
    }
    
    checkIsMobile()
    window.addEventListener('resize', checkIsMobile)
    return () => window.removeEventListener('resize', checkIsMobile)
  }, [])

  const { data: cityData, isLoading: cityLoading, error: cityError } = useQuery({
    queryKey: ['city', citySlug],
    queryFn: () => api.getCity(citySlug),
    refetchInterval: 60000,
  })

  const { data: historicalData, isLoading: historicalLoading } = useQuery({
    queryKey: ['city-historical', citySlug],
    queryFn: () => api.getCityHistorical(citySlug, 24),
    refetchInterval: 300000,
  })

  // Transform city-level weather data to match WeatherData interface
  const cityWeatherData = cityData?.weather ? {
    station_id: 0,
    timestamp: cityData.weather.last_update || new Date().toISOString(),
    temperature: cityData.weather.temperature,
    humidity: cityData.weather.humidity,
    pressure: cityData.weather.pressure,
    wind_speed: cityData.weather.wind_speed,
    wind_direction: cityData.weather.wind_direction,
    weather_icon: undefined,
    heat_index: cityData.weather.heat_index
  } : null
  const weatherLoading = cityLoading
  const weatherError = cityError

  if (cityLoading) {
    return (
      <div className="min-h-screen bg-background">
        <header className="border-b">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <div>
                <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
                <p className="text-sm text-muted-foreground">Pakistan Air Quality Monitoring</p>
              </div>
            </div>
          </div>
        </header>
        <div className="container mx-auto px-4 py-8">
          <div className="text-center">Loading city data...</div>
        </div>
      </div>
    )
  }

  if (cityError || !cityData) {
    return (
      <div className="min-h-screen bg-background">
        <header className="border-b">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <div>
                <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
                <p className="text-sm text-muted-foreground">Pakistan Air Quality Monitoring</p>
              </div>
            </div>
          </div>
        </header>
        <div className="container mx-auto px-4 py-8">
          <div className="text-center text-red-500">City not found or error loading data</div>
          <div className="text-center mt-4">
            <Link href="/" className="text-blue-500 hover:underline">← Back to Map</Link>
          </div>
        </div>
      </div>
    )
  }

  // Helper function to get AQI color styles using proper EPA colors
  const getAQIStyles = (aqi_category: string, aqiValue?: number) => {
    // If we have an AQI value, use the proper color system
    if (aqiValue) {
      const bgColor = getAQIColorByValue(aqiValue)
      return {
        style: { backgroundColor: bgColor, color: '#000000' }, // Black text for better contrast
        className: 'font-bold text-black'
      }
    }
    
    // Fallback to category-based colors if no AQI value
    switch (aqi_category) {
      case 'good': 
        return { style: { backgroundColor: 'rgba(110, 204, 57, 1)', color: '#000000' }, className: 'font-bold text-black' }
      case 'moderate': 
        return { style: { backgroundColor: 'rgba(240, 194, 12, 1)', color: '#000000' }, className: 'font-bold text-black' }
      case 'unhealthy_sensitive': 
        return { style: { backgroundColor: 'rgba(241, 128, 23, 1)', color: '#000000' }, className: 'font-bold text-black' }
      case 'unhealthy': 
        return { style: { backgroundColor: 'rgba(239, 120, 85, 1)', color: '#ffffff' }, className: 'font-bold text-white' }
      case 'very_unhealthy': 
        return { style: { backgroundColor: '#a070b5', color: '#ffffff' }, className: 'font-bold text-white' }
      case 'hazardous': 
        return { style: { backgroundColor: '#991b1b', color: '#ffffff' }, className: 'font-bold text-white' }
      default: 
        return { style: { backgroundColor: '#6b7280', color: '#ffffff' }, className: 'font-bold text-white' }
    }
  }

  // Prepare chart data for bar chart using Pakistan time and handling null values
  const chartData = historicalData?.readings?.map((reading: { 
    timestamp_utc: string; 
    timestamp_pk: string; 
    timestamp: string; 
    avg_aqi?: number; 
    avg_pm25?: number; 
    reporting_stations?: number 
  }, index: number) => {
    // Use Pakistan time for display
    const pkDate = new Date(reading.timestamp_pk || reading.timestamp)
    const hour = pkDate.getHours()
    const aqiValue = reading.avg_aqi
    const pm25Value = reading.avg_pm25
    
    return {
      hour: hour,
      timeLabel: pkDate.toLocaleTimeString('en-US', { hour: '2-digit', hour12: false }),
      aqi: aqiValue !== null && aqiValue !== undefined ? Math.round(aqiValue) : null,
      pm25: pm25Value !== null && pm25Value !== undefined ? Math.round(pm25Value) : null,
      color: getAQIColorByValue(aqiValue || 0),
      timestamp_pk: reading.timestamp_pk || reading.timestamp,
      timestamp_utc: reading.timestamp_utc || reading.timestamp,
      chartPosition: index
    }
  }) || []

  // Debug city data fields if needed
  if (process.env.NODE_ENV === 'development' && cityData) {
    console.log('🏙️ City data received:', {
      avg_aqi: cityData.avg_aqi,
      avg_pm25: cityData.avg_pm25
    });
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center space-x-3 min-w-0">
              <img 
                src="/logo-cropped.png" 
                alt="Hawanama Logo" 
                className="w-8 h-8 sm:w-12 sm:h-12 object-contain flex-shrink-0"
              />
              <div className="min-w-0">
                <Link href="/" className="text-lg sm:text-2xl font-bold text-foreground truncate block">Hawanama</Link>
                <p className="text-xs sm:text-sm text-muted-foreground hidden sm:block">Pakistan Air Quality Monitoring</p>
              </div>
            </div>
            <div className="flex items-center space-x-2 sm:space-x-4 min-w-0">
              <div className="relative">
                <CitySearch className="w-32 sm:w-48 md:w-64 ring-2 ring-blue-400/50 border-blue-400/50 rounded-2xl" />
              </div>
              <div className="flex items-center space-x-4">
                <Link href="/">
                  <Button variant="ghost" size="sm">
                    <ArrowLeft className="w-4 h-4 mr-2" />
                    Back to Map
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-6">
        {/* City Header */}
        <div className="mb-6">
          <div>
            <h1 className="text-2xl font-bold text-foreground">
              {cityData.city_name}
            </h1>
            <p className="text-sm text-muted-foreground">{cityData.state}, Pakistan</p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* City Info */}
          <div className="lg:col-span-1 space-y-4">
            
            {/* Compact AQI Card */}
            <div 
              className="rounded-lg p-4"
              style={{ backgroundColor: getAQIColorByValue(cityData.avg_aqi || 0) }}
            >
              {/* Upper section: PM2.5 | Category */}
              <div className="grid grid-cols-2 gap-4 items-center mb-4">
                
                {/* PM2.5 Number */}
                <div className="text-center">
                  <div className="text-xs text-gray-700 mb-1">PM2.5</div>
                  <div className="text-3xl font-bold leading-none text-gray-900">
                    {cityData.avg_pm25 ? Math.round(cityData.avg_pm25) : '--'}
                  </div>
                </div>
                
                {/* Category and US AQI */}
                <div className="text-center">
                  <div className="text-sm font-semibold text-gray-800">
                    {(() => {
                      const aqi = cityData.avg_aqi || 0
                      if (aqi <= 50) return 'Good'
                      if (aqi <= 100) return 'Moderate'
                      if (aqi <= 150) return 'Unhealthy for Sensitive Groups'
                      if (aqi <= 200) return 'Unhealthy'
                      if (aqi <= 300) return 'Very Unhealthy'
                      return 'Hazardous'
                    })()}
                  </div>
                  <div className="text-xs text-gray-700 mt-1">
                    US AQI {Math.round(cityData.avg_aqi || 0)}
                  </div>
                </div>
              </div>
              
              {/* Compact Weather Bar */}
              {cityWeatherData && (
                <div className="mt-3 bg-white rounded-md px-3 py-2 flex items-center justify-between text-sm text-gray-800">
                  <div className="flex items-center space-x-1">
                    <Thermometer className="w-4 h-4" />
                    <span>{cityWeatherData.temperature?.toFixed(1) || '--'}°C</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <Droplets className="w-4 h-4" />
                    <span>{cityWeatherData.humidity || '--'}%</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <Wind className="w-4 h-4" />
                    <span>{cityWeatherData.wind_speed?.toFixed(1) || '--'} m/s</span>
                  </div>
                </div>
              )}
            </div>

            {/* City Statistics Card */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">City Statistics</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-sm">Average AQI</span>
                  <span className="text-sm font-bold">
                    {Math.round(cityData.avg_aqi || 0)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm">Average PM2.5</span>
                  <span className="text-sm font-bold">
                    {cityData.avg_pm25 ? `${Math.round(cityData.avg_pm25)} µg/m³` : 'No data'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm">Active Stations</span>
                  <span className="text-sm text-muted-foreground">
                    {cityData?.stations?.length || 0}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm">Last Updated</span>
                  <span className="text-sm text-muted-foreground">
                    {cityWeatherData ? new Date(cityWeatherData.timestamp).toLocaleTimeString('en-US', { 
                      hour12: false, 
                      hour: '2-digit', 
                      minute: '2-digit' 
                    }) : 'Recent'}
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Charts and Historical Data */}
          <div className="lg:col-span-2 space-y-4">
            {/* Historical Chart */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="text-base sm:text-lg">24-Hour {chartMetric === 'aqi' ? 'AQI' : 'PM2.5'} Trend</CardTitle>
                    <CardDescription className="text-sm">
                      {historicalLoading ? 'Loading...' : ''}
                    </CardDescription>
                  </div>
                  <div className="flex items-center space-x-1 sm:space-x-2">
                    <button
                      onClick={() => setChartMetric('aqi')}
                      className={`px-2 py-0.5 sm:px-2 sm:py-0.5 text-xs rounded transition-colors ${
                        chartMetric === 'aqi' 
                          ? 'bg-blue-100 text-blue-700 font-medium' 
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      AQI
                    </button>
                    <button
                      onClick={() => setChartMetric('pm25')}
                      className={`px-2 py-0.5 sm:px-2 sm:py-0.5 text-xs rounded transition-colors ${
                        chartMetric === 'pm25' 
                          ? 'bg-blue-100 text-blue-700 font-medium' 
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      PM2.5
                    </button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {!historicalLoading && chartData.length > 0 ? (
                  // Mobile-optimized chart configuration for city
                  (() => {
                    const mobileConfig = {
                      height: isMobile ? 180 : 200,
                      margin: isMobile 
                        ? { top: 8, right: 8, bottom: 20, left: 5 }
                        : { top: 10, right: 15, bottom: 30, left: 10 },
                      barCategoryGap: isMobile ? "15%" : "30%",
                      maxBarSize: isMobile ? 16 : 14,
                      tickCount: isMobile ? 3 : 5,
                      yAxisWidth: isMobile ? 30 : 40,
                      fontSize: isMobile ? 9 : 10,
                      yAxisFontSize: isMobile ? 10 : 11
                    }

                    return (
                      <div className="bg-white border border-gray-100 rounded-xl p-2 sm:p-4">
                        <div className="relative [&_.recharts-active-bar]:!opacity-100 [&_.recharts-bar]:!opacity-100 [&_.recharts-rectangle:hover]:!opacity-100 [&_.recharts-active-shape]:!fill-current">
                          <ResponsiveContainer width="100%" height={mobileConfig.height}>
                            <BarChart
                              data={chartData}
                              margin={mobileConfig.margin}
                              barCategoryGap={mobileConfig.barCategoryGap}
                              onClick={() => {}} // Disable click events
                              onMouseMove={() => {}} // Disable mouse tracking
                            >
                              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" horizontal={true} vertical={false} />
                              <XAxis
                                dataKey="chartPosition"
                                type="number"
                                domain={[0, chartData.length - 1]}
                                axisLine={{ stroke: '#d1d5db' }}
                                tickLine={{ stroke: '#d1d5db' }}
                                stroke="#9ca3af"
                                tick={{ fontSize: mobileConfig.fontSize }}
                                tickCount={mobileConfig.tickCount}
                                interval={isMobile ? Math.floor(chartData.length / 3) : 0}
                                tickFormatter={(value) => {
                                  const dataPoint = chartData[Math.round(value)]
                                  if (!dataPoint) return ""
                                  const hour = dataPoint.hour
                                  if (hour === 0) return "00:00"
                                  return `${hour.toString().padStart(2, '0')}:00`
                                }}
                              />
                              
                              <YAxis
                                orientation="right"
                                axisLine={false}
                                tickLine={false}
                                stroke="#9ca3af"
                                tick={{ fontSize: mobileConfig.yAxisFontSize, dx: isMobile ? 2 : 5 }}
                                tickFormatter={(value) => Math.round(value)}
                                width={mobileConfig.yAxisWidth}
                                domain={[0, 'dataMax + 10']}
                              />
                              
                              <ReferenceLine y={0} stroke="#374151" strokeWidth={1} />

                              <Tooltip
                                contentStyle={{
                                  backgroundColor: 'white',
                                  border: '1px solid #e5e7eb',
                                  borderRadius: '8px',
                                  fontSize: isMobile ? '11px' : '12px',
                                  padding: isMobile ? '6px' : '8px'
                                }}
                                formatter={(value, name) => [
                                  chartMetric === 'aqi' ? `AQI ${value}` : `${value} µg/m³`,
                                  chartMetric === 'aqi' ? 'AQI' : 'PM2.5'
                                ]}
                                labelFormatter={(label, payload) => {
                                  if (payload && payload[0]?.payload?.timestamp_pk) {
                                    const date = new Date(payload[0].payload.timestamp_pk)
                                    return date.toLocaleString('en-US', {
                                      month: 'short',
                                      day: 'numeric',
                                      hour: '2-digit',
                                      minute: '2-digit',
                                      hour12: false,
                                      timeZone: 'Asia/Karachi'
                                    }) + ' PKT'
                                  }
                                  return label
                                }}
                              />

                              <Bar
                                dataKey={chartMetric}
                                radius={[3, 3, 0, 0]}
                                maxBarSize={mobileConfig.maxBarSize}
                                isAnimationActive={false}
                                style={{ cursor: 'default' }}
                              >
                                {chartData.map((entry, index) => (
                                  <Cell 
                                    key={`cell-${index}`} 
                                    fill={getAQIColorByValue(entry.aqi)}
                                    style={{ cursor: 'default' }}
                                  />
                                ))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    )
                  })()
                ) : (
                  <div className="h-40 sm:h-64 flex items-center justify-center text-muted-foreground">
                    {historicalLoading ? 'Loading chart data...' : 'No historical data available'}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* City Map */}
            <Card>
              <CardHeader>
                <CardTitle>Station Locations</CardTitle>
                <CardDescription>Air quality monitoring stations in {cityData.city_name}</CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <div className="h-64">
                  <CityMap
                    center={[
                      cityData.avg_longitude || 74.3587, // Fallback to Lahore coordinates
                      cityData.avg_latitude || 31.5204
                    ]}
                    zoom={11}
                    cityName={cityData.city_name}
                    stations={cityData.stations || []}
                  />
                </div>
              </CardContent>
            </Card>

            {/* Monitoring Stations */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-lg">Monitoring Stations</CardTitle>
                <CardDescription className="text-sm">{cityData?.stations?.length || 0} stations in {cityData?.city_name || 'Unknown City'}</CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <div className="max-h-80 overflow-y-auto">
                  {(cityData?.stations || []).map((station: { id: string; name: string; latest_aqi?: number; latest_pm25?: number; temp_c?: number; hours_since_update?: number; aqi_category?: string }) => (
                    <div 
                      key={station.id} 
                      className="block p-2 sm:p-3 border-b"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex-1 min-w-0">
                          <h4 className="font-medium truncate text-sm">{station.name}</h4>
                          <div className="flex items-center space-x-3 text-xs text-muted-foreground mt-1">
                            <span>PM2.5: {station.latest_pm25 ? `${station.latest_pm25}µg/m³` : 'N/A'}</span>
                            <span>Temp: {station.temp_c ? `${station.temp_c}°C` : 'N/A'}</span>
                          </div>
                        </div>
                        <div className="flex flex-col items-end">
                          {(() => {
                            const styles = getAQIStyles(station.aqi_category || '', station.latest_aqi)
                            return (
                              <div 
                                className={`px-2 py-1 rounded text-xs ${styles.className}`}
                                style={styles.style}
                              >
                                {station.latest_aqi || '--'}
                              </div>
                            )
                          })()}
                          <div className="text-[10px] text-muted-foreground mt-1">
                            {station.hours_since_update ? (
                              station.hours_since_update < 1 
                                ? `${Math.round(station.hours_since_update * 60)}m ago`
                                : `${station.hours_since_update.toFixed(1)}h ago`
                            ) : 'Recent'}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}
