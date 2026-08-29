'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { ArrowLeft, MapPin, Clock, Activity, Thermometer, Droplets, Wind, Eye } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useStationCurrent, useStationHistory, useStationPM25History, useAQICategories } from '@/hooks/useStation'
import { formatPollutant, getWindDirection } from '@/lib/aqi'
import { getAQICategory } from '@/lib/aqi'
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

interface StationClientProps {
  stationId: string
}

export default function StationClient({ stationId }: StationClientProps) {
  const [chartMetric, setChartMetric] = useState<'aqi' | 'pm25'>('pm25')
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const checkIsMobile = () => {
      setIsMobile(window.innerWidth <= 768)
    }
    
    checkIsMobile()
    window.addEventListener('resize', checkIsMobile)
    return () => window.removeEventListener('resize', checkIsMobile)
  }, [])

  const { data: current, isLoading: currentLoading, error: currentError } = useStationCurrent(stationId)
  const { data: history, isLoading: historyLoading } = useStationHistory(stationId)
  const { data: pm25History, isLoading: pm25HistoryLoading } = useStationPM25History(stationId)
  const { data: categories } = useAQICategories()

  if (currentLoading) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container mx-auto px-4 py-6">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-gray-200 rounded w-1/4"></div>
            <div className="h-64 bg-gray-200 rounded"></div>
          </div>
        </div>
      </div>
    )
  }

  // Calculate statistics from history data including current reading
  const getStatistics = () => {
    if (!history || history.length === 0) {
      // If no history but we have current data, use that
      if (current && current.aqi_us != null) {
        return { min: current.aqi_us, max: current.aqi_us, avg: current.aqi_us, coverage: 100 }
      }
      return { min: null, max: null, avg: null, coverage: 0 }
    }
    
    // Combine history with current reading for statistics
    let allReadings = [...history]
    if (current && current.aqi_us != null && current.last_update) {
      const currentTime = new Date(current.last_update)
      const latestHistoryTime = history.length > 0 ? new Date(history[history.length - 1].timestamp) : new Date(0)
      
      // Add current reading if it's more recent
      if (currentTime > latestHistoryTime) {
        allReadings.push({
          timestamp: current.last_update,
          aqi_us: current.aqi_us,
          p2_conc: current.main_value
        })
      }
    }
    
    const validReadings = allReadings.filter(r => r.aqi_us != null)
    const aqiValues = validReadings.map(r => r.aqi_us)
    
    if (aqiValues.length === 0) {
      return { min: null, max: null, avg: null, coverage: 0 }
    }
    
    return {
      min: Math.min(...aqiValues),
      max: Math.max(...aqiValues),
      avg: aqiValues.reduce((a, b) => a + b, 0) / aqiValues.length,
      coverage: (validReadings.length / allReadings.length) * 100
    }
  }
  
  const stats = getStatistics()
  
  // Get current AQI category
  const category = current && categories ? getAQICategory(current.aqi_us, categories) : null
  const currentAQI = current?.aqi_us || 0
  
  // Get health advisory based on current AQI
  const getHealthAdvisory = (aqi: number | null) => {
    if (!aqi) return { level: 'Unknown', message: 'No data available', color: 'gray' }
    
    if (aqi <= 50) return { level: 'Good', message: 'Air quality is satisfactory', color: 'green' }
    if (aqi <= 100) return { level: 'Moderate', message: 'Air quality is acceptable for most people', color: 'yellow' }
    if (aqi <= 150) return { level: 'Unhealthy for Sensitive Groups', message: 'People with respiratory disease should limit outdoor activities', color: 'orange' }
    if (aqi <= 200) return { level: 'Unhealthy', message: 'Everyone may begin to experience health effects', color: 'red' }
    if (aqi <= 300) return { level: 'Very Unhealthy', message: 'Health warnings of emergency conditions', color: 'purple' }
    return { level: 'Hazardous', message: 'Emergency conditions affecting entire population', color: 'maroon' }
  }
  
  const healthAdvisory = getHealthAdvisory(currentAQI)

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <img 
                src="/logo-cropped.png" 
                alt="Hawanama Logo" 
                className="w-12 h-12 object-contain"
              />
              <div>
                <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
                <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
              </div>
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
      </header>

      {/* Station Header */}
      <div className="border-b bg-gray-50">
        <div className="container mx-auto px-4 py-4">
          <div>
            <h1 className="text-2xl font-bold text-foreground">
              {current?.name || `Station ${stationId}`}
            </h1>
            <p className="text-sm text-muted-foreground">Station Details & Historical Data</p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="container mx-auto px-4 py-6">
        {current ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Station Info */}
            <div className="lg:col-span-1 space-y-4">
              
              {/* Compact AQI Card */}
              <div 
                className="rounded-lg p-4"
                style={{ backgroundColor: getAQIColorByValue(currentAQI || 0) }}
              >
                {/* Upper section: PM2.5 | Category */}
                <div className="grid grid-cols-2 gap-4 items-center mb-4">
                  
                  {/* PM2.5 Number */}
                  <div className="text-center">
                    <div className="text-xs text-gray-700 mb-1">PM2.5</div>
                    <div className="text-3xl font-bold leading-none text-gray-900">
                      {current.main_value || '--'}
                    </div>
                  </div>
                  
                  {/* Category and US AQI */}
                  <div className="text-center">
                    <div className="text-sm font-semibold text-gray-800">
                      {healthAdvisory.level}
                    </div>
                    <div className="text-xs text-gray-700 mt-1">
                      US AQI {currentAQI || '--'}
                    </div>
                  </div>
                </div>
                
                {/* Compact Weather Bar */}
                <div className="mt-3 bg-white rounded-md px-3 py-2 flex items-center justify-between text-sm text-gray-800">
                  <div className="flex items-center space-x-1">
                    <Thermometer className="w-4 h-4" />
                    <span>{current.temp_c}°C</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <Droplets className="w-4 h-4" />
                    <span>{current.humidity}%</span>
                  </div>
                  <div className="flex items-center space-x-1">
                    <Wind className="w-4 h-4" />
                    <span>{current.wind_speed_kmh?.toFixed(1)} km/h</span>
                  </div>
                </div>
              </div>

              {/* Today's Statistics Card */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Today&apos;s Statistics</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex justify-between">
                    <span className="text-sm">Min AQI</span>
                    <span className={`text-sm font-bold ${
                      stats.min <= 50 ? 'text-green-600' :
                      stats.min <= 100 ? 'text-yellow-600' :
                      stats.min <= 150 ? 'text-orange-600' :
                      'text-red-600'
                    }`}>
                      {stats.min ? Math.round(stats.min) : 'No data'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm">Max AQI</span>
                    <span className={`text-sm font-bold ${
                      stats.max <= 50 ? 'text-green-600' :
                      stats.max <= 100 ? 'text-yellow-600' :
                      stats.max <= 150 ? 'text-orange-600' :
                      stats.max <= 200 ? 'text-red-600' :
                      'text-purple-600'
                    }`}>
                      {stats.max ? Math.round(stats.max) : 'No data'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm">Average</span>
                    <span className="text-sm font-bold">
                      {stats.avg ? Math.round(stats.avg) : 'No data'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-sm">Total Readings</span>
                    <span className="text-sm text-muted-foreground">
                      {(() => {
                        let count = history?.length || 0
                        // Add 1 if current reading is newer than latest history
                        if (current && current.last_update && history && history.length > 0) {
                          const currentTime = new Date(current.last_update)
                          const latestHistoryTime = new Date(history[history.length - 1].timestamp)
                          if (currentTime > latestHistoryTime) count += 1
                        } else if (current && (!history || history.length === 0)) {
                          count = 1
                        }
                        return count
                      })()}
                    </span>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Charts and Historical Data */}
            <div className="lg:col-span-2 space-y-4">
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="flex items-center text-lg">
                        <Clock className="w-5 h-5 mr-2" />
                        24-Hour {chartMetric === 'aqi' ? 'AQI' : 'PM2.5'} Trend
                      </CardTitle>
                      <CardDescription className="text-sm">
                        Air quality measurements over the last 24 hours
                      </CardDescription>
                    </div>
                    <div className="flex items-center space-x-2">
                      <button
                        onClick={() => setChartMetric('aqi')}
                        className={`px-3 py-1 text-sm rounded-md transition-colors ${
                          chartMetric === 'aqi' 
                            ? 'bg-blue-100 text-blue-700 font-medium' 
                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        AQI
                      </button>
                      <button
                        onClick={() => setChartMetric('pm25')}
                        className={`px-3 py-1 text-sm rounded-md transition-colors ${
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
                  {(historyLoading || pm25HistoryLoading) ? (
                    <div className="h-64 bg-gray-100 animate-pulse rounded"></div>
                  ) : (() => {
                    // Prepare combined chart data similar to city implementation
                    const aqiData = history?.map((item) => {
                      const pkDate = new Date(item.timestamp_pk || item.timestamp)
                      return {
                        timestamp_pk: item.timestamp_pk || item.timestamp,
                        timestamp_utc: item.timestamp_utc || item.timestamp,
                        hour: pkDate.getHours(),
                        timeLabel: pkDate.toLocaleTimeString('en-US', { hour: '2-digit', hour12: false }),
                        aqi: item.aqi_us,
                        pm25: null as number | null
                      }
                    }) || []
                    
                    const pm25Data = pm25History?.map((item) => {
                      const pkDate = new Date(item.timestamp_pk || item.timestamp)
                      return {
                        timestamp_pk: item.timestamp_pk || item.timestamp,
                        timestamp_utc: item.timestamp_utc || item.timestamp,
                        hour: pkDate.getHours(),
                        timeLabel: pkDate.toLocaleTimeString('en-US', { hour: '2-digit', hour12: false }),
                        aqi: null as number | null,
                        pm25: item.pm25
                      }
                    }) || []
                    
                    // Merge data by local timestamp
                    const chartDataMap = new Map()
                    
                    // Add AQI data
                    aqiData.forEach(item => {
                      chartDataMap.set(item.timestamp_pk, {
                        hour: item.hour,
                        timeLabel: item.timeLabel,
                        aqi: item.aqi,
                        pm25: item.pm25,
                        timestamp_pk: item.timestamp_pk,
                        timestamp_utc: item.timestamp_utc
                      })
                    })
                    
                    // Add PM2.5 data
                    pm25Data.forEach(item => {
                      const existing = chartDataMap.get(item.timestamp_pk)
                      if (existing) {
                        existing.pm25 = item.pm25
                      } else {
                        chartDataMap.set(item.timestamp_pk, {
                          hour: item.hour,
                          timeLabel: item.timeLabel,
                          aqi: item.aqi,
                          pm25: item.pm25,
                          timestamp_pk: item.timestamp_pk,
                          timestamp_utc: item.timestamp_utc
                        })
                      }
                    })
                    
                    const chartData = Array.from(chartDataMap.values())
                      .sort((a, b) => new Date(a.timestamp_pk).getTime() - new Date(b.timestamp_pk).getTime())
                      .map((item, index) => ({
                        ...item,
                        aqi: item.aqi || null,  // Keep null values instead of converting to 0
                        pm25: item.pm25 || null,  // Keep null values instead of converting to 0
                        color: getAQIColorByValue(item.aqi || 0),
                        chartPosition: index
                      }))
                    
                    // Mobile-optimized chart configuration
                    const mobileConfig = {
                      height: isMobile ? 250 : 320,
                      margin: isMobile 
                        ? { top: 10, right: 10, bottom: 25, left: 5 }
                        : { top: 10, right: 15, bottom: 30, left: 10 },
                      barCategoryGap: isMobile ? "15%" : "25%",
                      maxBarSize: isMobile ? 12 : 16,
                      tickCount: isMobile ? 4 : 6,
                      yAxisWidth: isMobile ? 35 : 40,
                      fontSize: isMobile ? 10 : 11
                    }

                    return chartData.length > 0 ? (
                      <div className="bg-white border border-gray-100 rounded-xl p-3 sm:p-4">
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
                                domain={['dataMin', 'dataMax']}
                                axisLine={{ stroke: '#d1d5db' }}
                                tickLine={{ stroke: '#d1d5db' }}
                                stroke="#9ca3af"
                                tick={{ fontSize: mobileConfig.fontSize }}
                                tickCount={mobileConfig.tickCount}
                                allowDataOverflow={false}
                                interval={isMobile ? Math.floor(chartData.length / 4) : 0}
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
                                tick={{ fontSize: mobileConfig.fontSize, dx: isMobile ? 2 : 5 }}
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
                                  padding: isMobile ? '8px' : '12px'
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
                                radius={[2, 2, 0, 0]}
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
                    ) : (
                      <div className="h-64 flex items-center justify-center text-muted-foreground">
                        <div className="text-center">
                          <p>No data available for chart</p>
                          <p className="text-sm mt-2">
                            No readings found for this station
                          </p>
                        </div>
                      </div>
                    )
                  })()}
                </CardContent>
              </Card>
            </div>
          </div>
        ) : (
          <div className="text-center py-12">
            <div className="space-y-4">
              <p className="text-muted-foreground">Station not found</p>
              {currentError && (
                <div className="text-sm text-red-600 space-y-2">
                  <p>Error: {currentError.message}</p>
                  <p>Station ID: {stationId}</p>
                </div>
              )}
              {!currentError && !current && (
                <div className="text-sm text-gray-500 space-y-2">
                  <p>Station ID: {stationId}</p>
                  <p>Loading: {currentLoading ? 'Yes' : 'No'}</p>
                  <p>No station data found for this ID</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}