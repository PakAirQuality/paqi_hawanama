'use client'

import { useEffect } from 'react'
import { X } from 'lucide-react'
import { useStationSidebar } from '@/stores/stationSidebar'
import { useStationCurrent, useStationHistory, useAQICategories, useAbortOnStationChange } from '@/hooks/useStation'
import { AQICard } from './AQICard'
import { HistoryMiniChart } from './HistoryMiniChart'
import { MetricRow } from './MetricRow'
import { formatPollutant, getWindDirection } from '@/lib/aqi'

export function StationSidebar() {
  const { isOpen, stationId, close } = useStationSidebar()
  const abortQueries = useAbortOnStationChange(stationId)
  
  const { data: current, isLoading: currentLoading } = useStationCurrent(stationId)
  const { data: history, isLoading: historyLoading } = useStationHistory(stationId)
  const { data: categories } = useAQICategories()

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

  return (
    <>
      {/* Mobile backdrop */}
      <div 
        className="fixed inset-0 bg-black/50 lg:hidden z-40"
        onClick={handleBackdropClick}
      />
      
      {/* Sidebar */}
      <div className={`
        fixed right-0 top-0 h-full bg-white shadow-2xl z-50
        transform transition-transform duration-300 ease-out
        ${isOpen ? 'translate-x-0' : 'translate-x-full'}
        w-full lg:w-96
      `}>
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Station Details</h2>
            <button
              onClick={close}
              className="p-1 rounded-lg hover:bg-gray-100 transition-colors"
            >
              <X size={20} className="text-gray-500" />
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-6">
            {currentLoading ? (
              <div className="animate-pulse space-y-4">
                <div className="h-32 bg-gray-200 rounded-2xl" />
                <div className="h-20 bg-gray-200 rounded-2xl" />
                <div className="h-40 bg-gray-200 rounded-2xl" />
              </div>
            ) : current && categories ? (
              <>
                {/* Station Name */}
                <div>
                  <h3 className="text-xl font-semibold text-gray-900 mb-1">
                    {current.name}
                  </h3>
                  <p className="text-sm text-gray-500">
                    Updated {new Date(current.last_update).toLocaleString()}
                  </p>
                </div>

                {/* AQI Card */}
                <AQICard 
                  aqi={current.aqi_us} 
                  categories={categories}
                  mainPollutant={formatPollutant(current.main_pollutant)}
                  mainValue={current.main_value}
                  mainUnits={current.main_units}
                />

                {/* Weather Metrics */}
                <div className="bg-gray-50 rounded-2xl p-4 space-y-3">
                  <h4 className="font-medium text-gray-900 mb-3">Weather</h4>
                  
                  <MetricRow 
                    label="Temperature" 
                    value={`${current.temp_c}°C`}
                  />
                  <MetricRow 
                    label="Humidity" 
                    value={`${current.humidity}%`}
                  />
                  <MetricRow 
                    label="Wind" 
                    value={`${current.wind_speed_kmh?.toFixed(1)} km/h ${getWindDirection(current.wind_direction)}`}
                  />
                  <MetricRow 
                    label="Pressure" 
                    value={`${current.pressure_mbar} mbar`}
                  />
                </div>

                {/* History Chart */}
                <div className="bg-gray-50 rounded-2xl p-4">
                  <h4 className="font-medium text-gray-900 mb-3">24h AQI Trend</h4>
                  {historyLoading ? (
                    <div className="h-32 bg-gray-200 rounded-lg animate-pulse" />
                  ) : history ? (
                    <HistoryMiniChart data={history} categories={categories} />
                  ) : (
                    <div className="h-32 flex items-center justify-center text-gray-500">
                      No history data available
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex items-center justify-center h-32 text-gray-500">
                Failed to load station data
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}