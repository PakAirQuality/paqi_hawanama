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
                <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
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
                <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
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

  // Prepare chart data for bar chart using local time and handling null values
  const chartData = historicalData?.readings?.map((reading: { 
    timestamp_utc: string; 
    timestamp_pk: string; 
    timestamp: string; 
    avg_aqi?: number; 
    avg_pm25?: number; 
    reporting_stations?: number 
  }, index: number) => {
    // Use local time for display
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
                <p className="text-xs sm:text-sm text-muted-foreground hidden sm:block">South Asia Air Quality Monitoring</p>
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
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="min-w-0 flex-1">
                <h1 className="text-xl sm:text-2xl font-bold text-foreground truncate">{cityData.city_name}</h1>
                <p className="text-sm text-muted-foreground">{cityData.state}{cityData.country ? `, ${cityData.country}` : ''}</p>
              </div>
              {/* Mobile: AQI box next to city name */}
              <div className="sm:hidden">
                <CityAQIBox value={cityData.avg_aqi || 0} />
              </div>
            </div>
            {/* Desktop: AQI box in original position */}
            <div className="hidden sm:flex flex-col items-center sm:items-end">
              <CityAQIBox value={cityData.avg_aqi || 0} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6">
          {/* Left Column: Chart */}
          <div className="lg:col-span-2">
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
          </div>

          {/* Right Column: Weather and Station List */}
          <div className="space-y-4">
            {/* Weather Card - Large & Prominent */}
            {weatherLoading ? (
              <div className="relative w-full">
                <div className="relative w-full max-w-96 mx-auto h-78 flex flex-col items-center justify-center p-4 sm:p-6 rounded-xl backdrop-blur-md bg-white/95 border border-white/30 shadow-lg">
                  <div className="animate-pulse space-y-4 w-full">
                    <div className="h-5 bg-gray-200 rounded w-1/2 mx-auto"></div>
                    <div className="h-12 bg-gray-200 rounded w-1/3 mx-auto"></div>
                    <div className="flex gap-3 justify-center">
                      <div className="h-4 bg-gray-200 rounded w-20"></div>
                      <div className="h-4 bg-gray-200 rounded w-20"></div>
                      <div className="h-4 bg-gray-200 rounded w-20"></div>
                      <div className="h-4 bg-gray-200 rounded w-20"></div>
                    </div>
                  </div>
                </div>
              </div>
            ) : weatherError ? (
              <div className="relative w-full">
                <div className="relative w-full max-w-96 mx-auto h-78 flex items-center justify-center p-4 sm:p-6 rounded-xl backdrop-blur-md bg-white/95 border border-white/30 shadow-lg">
                  <p className="text-sm text-red-600">Weather data unavailable</p>
                </div>
              </div>
            ) : cityWeatherData ? (
              <div className="relative w-full">
                {/* Background decoration - hidden on mobile */}
                <div className="hidden sm:block absolute w-24 h-24 bg-blue-300/30 rounded-full left-48 top-18 -z-10 transition-all duration-1000 hover:translate-x-[-40px] hover:translate-y-8"></div>
                
                <div className="relative w-full max-w-96 mx-auto h-78 flex flex-col p-4 sm:p-6 rounded-xl backdrop-blur-md bg-white/95 border border-white/30 shadow-lg transition-transform duration-300 hover:-translate-y-1 cursor-pointer">
                  {/* City Header */}
                  <div className="text-center mb-4">
                    <p className="font-bold text-sm tracking-wider text-gray-700 m-0 uppercase">
                      {cityData.city_name}
                    </p>
                    <p className="font-medium text-xs tracking-wider text-gray-500 uppercase">
                      Current Weather
                    </p>
                  </div>
                  
                  {/* Center Stage - Main Temperature & Cloud */}
                  <div className="flex items-center justify-center gap-6 mb-6">
                    {/* Large Weather Cloud Icon */}
                    <svg viewBox="0 0 24 24" className="w-16 h-16 text-blue-500">
                      <path fill="currentColor" d="M6.5,20Q4.22,20 2.61,18.43Q1,16.85 1,14.58Q1,12.63 2.17,11.1Q3.35,9.57 5.25,9.15Q5.88,6.85 7.75,5.43Q9.63,4 12,4Q14.93,4 16.96,6.04Q19,8.07 19,11Q20.73,11.2 21.86,12.5Q23,13.78 23,15.5Q23,17.38 21.69,18.69Q20.38,20 18.5,20H6.5M6.5,18H18.5Q19.55,18 20.27,17.27Q21,16.55 21,15.5Q21,14.45 20.27,13.73Q19.55,13 18.5,13H17V11Q17,8.93 15.54,7.46Q14.07,6 12,6Q9.93,6 8.46,7.46Q7,8.93 7,11H6.5Q5.05,11 4.03,12.03Q3,13.05 3,14.5Q3,15.95 4.03,16.98Q5.05,18 6.5,18Z"/>
                    </svg>
                    
                    {/* Large Main Temperature */}
                    <p className="text-5xl text-gray-700 font-bold">
                      {Math.round(cityWeatherData.temperature || 0)}°C
                    </p>
                  </div>
                  
                  {/* Weather metrics grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 sm:gap-6 flex-1 items-center">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <svg viewBox="0 0 24 24" className="w-5 h-5 sm:w-6 sm:h-6 text-red-500">
                        <path fill="currentColor" d="M15 13V5A3 3 0 0 0 9 5V13A5 5 0 1 0 15 13M12 4A1 1 0 0 1 13 5V8H11V5A1 1 0 0 1 12 4Z"/>
                      </svg>
                      <div className="text-xs text-gray-500 font-medium text-center">Temperature</div>
                      <div className="text-xs sm:text-sm text-gray-700 font-semibold">
                        {cityWeatherData.temperature?.toFixed(1) || '--'}°C
                      </div>
                    </div>
                    
                    <div className="flex flex-col items-center justify-center gap-2">
                      <svg viewBox="0 0 24 24" className="w-5 h-5 sm:w-6 sm:h-6 text-blue-500">
                        <path fill="currentColor" d="M12,3.25C12,3.25 6,10 6,14C6,17.32 8.69,20 12,20A6,6 0 0,0 18,14C18,10 12,3.25 12,3.25M14.47,9.97L15.53,11.03L9.53,17.03L8.47,15.97L14.47,9.97Z"/>
                      </svg>
                      <div className="text-xs text-gray-500 font-medium text-center">Humidity</div>
                      <div className="text-xs sm:text-sm text-gray-700 font-semibold">
                        {cityWeatherData.humidity || '--'}%
                      </div>
                    </div>
                    
                    <div className="flex flex-col items-center justify-center gap-2">
                      <svg viewBox="0 0 24 24" className="w-5 h-5 sm:w-6 sm:h-6 text-gray-500">
                        <path fill="currentColor" d="M4,10A1,1 0 0,1 3,9A1,1 0 0,1 4,8H12A2,2 0 0,0 14,6A2,2 0 0,0 12,4C11.45,4 10.95,4.22 10.59,4.59C10.2,5 9.56,5 9.17,4.59C8.78,4.2 8.78,3.56 9.17,3.17C9.9,2.45 10.9,2 12,2A4,4 0 0,1 16,6A4,4 0 0,1 12,10H4M19,12A1,1 0 0,1 18,11A1,1 0 0,1 19,10H20A2,2 0 0,0 22,8A2,2 0 0,0 20,6C19.45,6 18.95,6.22 18.59,6.59C18.2,7 17.56,7 17.17,6.59C16.78,6.2 16.78,5.56 17.17,5.17C17.9,4.45 18.9,4 20,4A4,4 0 0,1 24,8A4,4 0 0,1 20,12H19M18,20A1,1 0 0,1 17,19A1,1 0 0,1 18,18H19A2,2 0 0,0 21,16A2,2 0 0,0 19,14C18.45,14 17.95,14.22 17.59,14.59C17.2,15 16.56,15 16.17,14.59C15.78,14.2 15.78,13.56 16.17,13.17C16.9,12.45 17.9,12 19,12A4,4 0 0,1 23,16A4,4 0 0,1 19,20H18M2,18A1,1 0 0,1 1,17A1,1 0 0,1 2,16H3A2,2 0 0,0 5,14A2,2 0 0,0 3,12C2.45,12 1.95,12.22 1.59,12.59C1.2,13 0.56,13 0.17,12.59C-0.22,12.2 -0.22,11.56 0.17,11.17C0.9,10.45 1.9,10 3,10A4,4 0 0,1 7,14A4,4 0 0,1 3,18H2Z"/>
                      </svg>
                      <div className="text-xs text-gray-500 font-medium text-center">Wind Speed</div>
                      <div className="text-xs sm:text-sm text-gray-700 font-semibold">
                        {cityWeatherData.wind_speed?.toFixed(1) || '--'} m/s
                      </div>
                    </div>
                    
                    <div className="flex flex-col items-center justify-center gap-2">
                      <svg viewBox="0 0 24 24" className="w-5 h-5 sm:w-6 sm:h-6 text-green-600">
                        <path fill="currentColor" d="M21 3L3 10.53v.98l6.84 2.65L12.48 21h.98L21 3z"/>
                      </svg>
                      <div className="text-xs text-gray-500 font-medium text-center">Wind Dir</div>
                      <div className="text-xs sm:text-sm text-gray-700 font-semibold">
                        {cityWeatherData.wind_direction || '--'}°
                      </div>
                    </div>
                  </div>
                  
                  {/* Last updated */}
                  <div className="text-center text-xs text-gray-400 mt-3 pt-3 border-t border-black/10">
                    Last updated: {new Date(cityWeatherData.timestamp).toLocaleDateString()}, {new Date(cityWeatherData.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            ) : null}

            {/* Monitoring Stations - Moved Down */}
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
