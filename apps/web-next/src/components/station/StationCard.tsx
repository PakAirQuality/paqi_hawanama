'use client'

import React, { useEffect, useState } from 'react'
import { X, Thermometer, Droplets, Wind, Eye } from 'lucide-react'
import { useStationSidebar } from '@/stores/stationSidebar'
import { useStationCurrent, useStationHistory, useStationPM25History, useAQICategories, useAbortOnStationChange } from '@/hooks/useStation'
import { formatPollutant, getWindDirection } from '@/lib/aqi'
import { getAQICategory } from '@/lib/aqi'
import { getAQIColorByValue, getAQICategoryLabel } from '@/components/map/config/aqiStyles'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
  Tooltip,
} from 'recharts'

// Use centralized AQI color function

// Compact rectangular AQI box with color background and black text
const AQIBox: React.FC<{ value: number }> = ({ value }) => {
  return (
    <div 
      className="w-20 h-16 rounded-md flex flex-col items-center justify-center text-black font-bold shadow-md border border-black/10"
      style={{ backgroundColor: getAQIColorByValue(value) }}
    >
      <div className="text-xl font-bold leading-tight">{Math.round(value) || '--'}</div>
      <div className="text-[10px] font-medium -mt-0.5">AQI</div>
    </div>
  )
}

// Mini badge used inside the Hourly card (AQI number + tiny arc)
const MiniAQIBadge: React.FC<{ value: number }> = ({ value }) => {
  const r = 16
  const C = 2 * Math.PI * r
  const visible = (270 / 360) * C
  const pct = Math.min(1, Math.max(0, value / 500))
  const offset = C - visible * pct

  return (
    <div className="flex items-center gap-3">
      <div className="text-sm text-gray-600">AQI</div>
      <div className="text-xl font-semibold">{value}</div>
      <svg viewBox="0 0 48 48" className="w-10 h-10">
        <defs>
          <linearGradient id="miniArc" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#10b981" />
            <stop offset="50%" stopColor="#fbbf24" />
            <stop offset="100%" stopColor="#a855f7" />
          </linearGradient>
        </defs>
        <circle
          cx="24"
          cy="24"
          r={r}
          fill="none"
          stroke="url(#miniArc)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={`${visible} ${C}`}
          strokeDashoffset={offset}
          transform="rotate(-135 24 24)"
        />
      </svg>
    </div>
  )
}

export function StationCard() {
  const { isOpen, stationId, close } = useStationSidebar()
  const abortQueries = useAbortOnStationChange(stationId)
  const [chartMetric, setChartMetric] = React.useState<'aqi' | 'pm25'>('pm25')
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const checkIsMobile = () => {
      setIsMobile(window.innerWidth <= 768)
    }
    
    checkIsMobile()
    window.addEventListener('resize', checkIsMobile)
    return () => window.removeEventListener('resize', checkIsMobile)
  }, [])
  
  const { data: current, isLoading: currentLoading } = useStationCurrent(stationId)
  const { data: history, isLoading: historyLoading } = useStationHistory(stationId)
  const { data: pm25History, isLoading: pm25HistoryLoading } = useStationPM25History(stationId)
  const { data: categories } = useAQICategories()

  // Prepare combined chart data using local time and handling null values
  const chartData = React.useMemo(() => {
    const aqiData = history?.map((item) => {
      const pkDate = new Date(item.timestamp_pk)
      return {
        timestamp_pk: item.timestamp_pk,
        timestamp_utc: item.timestamp_utc,
        hour: pkDate.getHours(),
        timeLabel: pkDate.toLocaleTimeString('en-US', { hour: '2-digit', hour12: false }),
        aqi: item.aqi_us,
        pm25: null as number | null
      }
    }) || []
    
    const pm25Data = pm25History?.map((item) => {
      const pkDate = new Date(item.timestamp_pk)
      return {
        timestamp_pk: item.timestamp_pk,
        timestamp_utc: item.timestamp_utc,
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
    
    // Sort by time and create chart display order (most recent on right)
    const sortedData = Array.from(chartDataMap.values())
      .sort((a, b) => new Date(a.timestamp_pk).getTime() - new Date(b.timestamp_pk).getTime())
    
    // Get current local time hour to determine rightmost position
    const currentPKTime = new Date().toLocaleString('en-US', { timeZone: 'Asia/Karachi' })
    const currentHour = new Date(currentPKTime).getHours()
    
    return sortedData.map((item, index) => ({
      ...item,
      aqi: item.aqi || null,  // Keep null values instead of converting to 0
      pm25: item.pm25 || null,  // Keep null values instead of converting to 0
      color: getAQIColorByValue(item.aqi || 0),
      // Calculate position relative to current time for chart display
      chartPosition: index,
      relativeHour: item.hour
    }))
  }, [history, pm25History])

  // Handle ESC key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        close()
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isOpen, close])

  // Abort queries when closing
  useEffect(() => {
    if (!isOpen) {
      abortQueries()
    }
  }, [isOpen, abortQueries])

  if (!isOpen) return null

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      close()
    }
  }

  // Get current data
  const category = current && categories ? getAQICategory(current.aqi_us, categories) : null
  const currentAQI = current?.aqi_us || 0
  const currentHour = new Date().getHours()

  // Debug logging for data inconsistency tracking
  if (process.env.NODE_ENV === 'development' && current && stationId) {
    console.log(`🏠 Station popup data for ${stationId}:`, { 
      main_value: current.main_value, 
      aqi_us: current.aqi_us,
      last_update: current.last_update 
    });
  }

  return (
    <>
      {/* Mobile backdrop only */}
      <div 
        className="fixed inset-0 bg-black/30 lg:hidden z-40"
        onClick={handleBackdropClick}
      />
      
      {/* Card positioned on left side */}
      <div className={`
        fixed top-24 left-4 z-50 w-full max-w-xs
        transform transition-transform duration-300 ease-out
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        <div className="bg-white rounded-2xl shadow-xl p-3 max-h-[calc(100vh-2rem)] overflow-y-auto">
          {currentLoading ? (
            <div className="animate-pulse space-y-4">
              <div className="h-8 bg-gray-200 rounded w-3/4" />
              <div className="h-32 bg-gray-200 rounded-2xl" />
              <div className="h-20 bg-gray-200 rounded-2xl" />
              <div className="h-40 bg-gray-200 rounded-2xl" />
            </div>
          ) : current && categories && category ? (
            <>
              {/* Header: Station Name and Close Button */}
              <div className="flex items-start justify-between mb-1">
                <div className="flex-1 pr-2">
                  <div className="text-lg font-bold text-gray-900 leading-tight">
                    {current.name}
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5">
                    Last updated: {new Date(current.last_update).toLocaleTimeString('en-US', {
                      timeZone: 'Asia/Karachi',
                      hour12: false,
                      hour: '2-digit',
                      minute: '2-digit'
                    })} PKT
                  </div>
                </div>
                <button
                  onClick={close}
                  className="text-gray-400 hover:text-gray-600 p-1 flex-shrink-0"
                  aria-label="Close"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Compact AQI Card */}
              <div 
                className="rounded-lg p-3 mt-2"
                style={{ backgroundColor: getAQIColorByValue(currentAQI || 0) }}
              >
                {/* Upper section: US AQI | Category */}
                <div className="grid grid-cols-2 gap-4 items-center mb-3">
                  
                  {/* PM2.5 Number */}
                  <div className="text-center">
                    <div className="text-xs text-gray-700 mb-1">PM2.5</div>
                    <div className="text-3xl font-bold leading-none text-gray-900">
                      {current.main_value || '--'}
                      <span className="text-xs font-normal text-gray-600 ml-1">µg/m³</span>
                    </div>
                  </div>
                  
                  {/* Category and AQI */}
                  <div className="text-center">
                    <div className="text-sm font-semibold text-gray-800">
                      {getAQICategoryLabel(currentAQI, category.label)}
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


              {/* 24h Trend Bar Chart with Toggle */}
              {!(historyLoading && pm25HistoryLoading) && chartData.length > 0 && (
                  <div className="bg-white border border-gray-100 rounded-xl p-2">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-medium text-gray-700">
                      24h {chartMetric === 'aqi' ? 'AQI' : 'PM2.5'} Trend
                    </h3>
                    <div className="flex items-center space-x-0.5 sm:space-x-1">
                      <button
                        onClick={() => setChartMetric('aqi')}
                        className={`px-1.5 py-0.5 sm:px-2 sm:py-1 text-xs rounded transition-colors ${
                          chartMetric === 'aqi' 
                            ? 'bg-blue-100 text-blue-700 font-medium' 
                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        AQI
                      </button>
                      <button
                        onClick={() => setChartMetric('pm25')}
                        className={`px-1.5 py-0.5 sm:px-2 sm:py-1 text-xs rounded transition-colors ${
                          chartMetric === 'pm25' 
                            ? 'bg-blue-100 text-blue-700 font-medium' 
                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        PM2.5
                      </button>
                    </div>
                  </div>

                  {/* Mobile-optimized chart configuration for station card sidebar */}
                  {(() => {
                    const mobileConfig = {
                      height: isMobile ? 180 : 140,
                      margin: isMobile 
                        ? { top: 10, right: 12, bottom: 45, left: 8 }
                        : { top: 10, right: 15, bottom: 25, left: 15 },
                      barCategoryGap: isMobile ? "8%" : "8%",
                      maxBarSize: isMobile ? 10 : 16,
                      tickCount: isMobile ? 4 : 5,
                      yAxisWidth: isMobile ? 35 : 35,
                      fontSize: isMobile ? 10 : 10,
                      interval: isMobile ? Math.max(0, Math.floor(chartData.length / 4) - 1) : 0
                    }

                    return (
                      <div className="relative [&_.recharts-active-bar]:!opacity-100 [&_.recharts-bar]:!opacity-100 [&_.recharts-rectangle:hover]:!opacity-100 [&_.recharts-active-shape]:!fill-current [&_.recharts-wrapper]:!outline-none [&_.recharts-surface]:!outline-none">
                        <div style={{ width: '100%', height: `${mobileConfig.height}px`, outline: 'none' }}>
                      <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={chartData}
                            margin={mobileConfig.margin}
                            barCategoryGap={mobileConfig.barCategoryGap}
                            onClick={() => {}} // Disable click events
                            onMouseMove={() => {}} // Disable mouse tracking
                            style={{ outline: 'none' }}
                          >
                            <XAxis
                              dataKey="chartPosition"
                              type="number"
                              domain={[0, chartData.length - 1]}
                              axisLine={false}
                              tickLine={false}
                              stroke="#9ca3af"
                              tick={{ fontSize: mobileConfig.fontSize }}
                              tickCount={mobileConfig.tickCount}
                              interval={mobileConfig.interval}
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
                              tick={{ fontSize: mobileConfig.fontSize, dx: isMobile ? 1 : 0 }}
                              tickFormatter={(value) => Math.round(value)}
                              width={mobileConfig.yAxisWidth}
                            />

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
                    )
                  })()}
                </div>
              )}

              {/* View Details Button */}
              <div className="mt-2 pt-2 border-t border-gray-100">
                <a
                  href={`/station/${stationId}`}
                  className="w-full block text-center hover:bg-sky-700 text-gray-50 bg-sky-800 py-2 transition-colors text-sm font-medium rounded"
                  onClick={close}
                >
                  View Details
                </a>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-32 text-gray-500">
              Failed to load station data
            </div>
          )}
        </div>
      </div>
    </>
  )
}