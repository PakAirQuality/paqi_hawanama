"use client"

import { useEffect, useMemo } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import {
  Map,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertTriangle,
  Play,
  Pause,
  Calendar
} from 'lucide-react'
import type { TileDatesResponse, PredictionData } from './types'
import { PredictionMap } from './PredictionMap'

interface ResultsTabProps {
  tileDates: TileDatesResponse | undefined
  tileDatesLoading: boolean
  selectedPredDate: string | null
  setSelectedPredDate: (date: string | null) => void
  predictionData: PredictionData | null | undefined
  predictionDataLoading: boolean
  predictionError: Error | null
}

export function ResultsTab({
  tileDates,
  tileDatesLoading,
  selectedPredDate,
  setSelectedPredDate,
  predictionData,
  predictionDataLoading,
  predictionError,
}: ResultsTabProps) {
  const dates = tileDates?.dates || []
  const currentIndex = selectedPredDate ? dates.indexOf(selectedPredDate) : -1

  // Auto-select latest date when dates load
  useEffect(() => {
    if (dates.length > 0 && !selectedPredDate) {
      setSelectedPredDate(dates[dates.length - 1])
    }
  }, [dates, selectedPredDate, setSelectedPredDate])

  // Format date for display
  const formatDisplayDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  // Get date range labels
  const dateRangeLabel = useMemo(() => {
    if (dates.length === 0) return ''
    return `${formatDisplayDate(dates[0])} - ${formatDisplayDate(dates[dates.length - 1])}`
  }, [dates])

  return (
    <div className="space-y-4">
      {/* Timeline Scrubber */}
      <Card>
        <CardContent className="p-4">
          {tileDatesLoading ? (
            <div className="h-16 bg-gray-100 rounded animate-pulse"></div>
          ) : dates.length === 0 ? (
            <div className="text-center py-4 text-gray-500">
              <Calendar className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No predictions available</p>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Current Date Display */}
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <button
                    onClick={() => {
                      if (currentIndex > 0) setSelectedPredDate(dates[currentIndex - 1])
                    }}
                    disabled={currentIndex <= 0}
                    className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-5 h-5" />
                  </button>
                  <div className="text-center min-w-[180px]">
                    <div className="text-2xl font-bold text-gray-900">
                      {selectedPredDate ? formatDisplayDate(selectedPredDate) : 'Select date'}
                    </div>
                    <div className="text-xs text-gray-500">{selectedPredDate}</div>
                  </div>
                  <button
                    onClick={() => {
                      if (currentIndex < dates.length - 1) setSelectedPredDate(dates[currentIndex + 1])
                    }}
                    disabled={currentIndex >= dates.length - 1}
                    className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronRight className="w-5 h-5" />
                  </button>
                </div>
                <div className="text-sm text-gray-500">
                  {currentIndex + 1} of {dates.length} days
                </div>
              </div>

              {/* Timeline Slider */}
              <div className="relative px-2">
                <input
                  type="range"
                  min={0}
                  max={dates.length - 1}
                  value={currentIndex >= 0 ? currentIndex : 0}
                  onChange={(e) => {
                    const idx = parseInt(e.target.value, 10)
                    if (dates[idx]) setSelectedPredDate(dates[idx])
                  }}
                  className="w-full h-2 bg-gradient-to-r from-blue-200 via-blue-400 to-blue-600 rounded-lg appearance-none cursor-pointer
                    [&::-webkit-slider-thumb]:appearance-none
                    [&::-webkit-slider-thumb]:w-5
                    [&::-webkit-slider-thumb]:h-5
                    [&::-webkit-slider-thumb]:rounded-full
                    [&::-webkit-slider-thumb]:bg-white
                    [&::-webkit-slider-thumb]:border-2
                    [&::-webkit-slider-thumb]:border-blue-600
                    [&::-webkit-slider-thumb]:shadow-lg
                    [&::-webkit-slider-thumb]:cursor-grab
                    [&::-webkit-slider-thumb]:active:cursor-grabbing
                    [&::-webkit-slider-thumb]:hover:scale-110
                    [&::-webkit-slider-thumb]:transition-transform
                    [&::-moz-range-thumb]:w-5
                    [&::-moz-range-thumb]:h-5
                    [&::-moz-range-thumb]:rounded-full
                    [&::-moz-range-thumb]:bg-white
                    [&::-moz-range-thumb]:border-2
                    [&::-moz-range-thumb]:border-blue-600
                    [&::-moz-range-thumb]:shadow-lg
                    [&::-moz-range-thumb]:cursor-grab"
                />
                {/* Date range labels */}
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>{dates[0]}</span>
                  <span>{dates[dates.length - 1]}</span>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Map Visualization - Now First */}
      {selectedPredDate && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-lg font-semibold flex items-center space-x-2">
              <Map className="w-5 h-5" />
              <span>PM2.5 Predictions</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="relative bg-slate-50 rounded-xl overflow-hidden shadow-inner" style={{ height: '500px' }}>
              <PredictionMap selectedDate={selectedPredDate} />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Statistics Panel - Now Below Map */}
      {selectedPredDate && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-lg font-semibold">Statistics for {selectedPredDate}</CardTitle>
          </CardHeader>
          <CardContent>
            {predictionDataLoading ? (
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
                {[...Array(7)].map((_, i) => (
                  <div key={i} className="h-20 bg-gray-100 rounded-lg animate-pulse"></div>
                ))}
              </div>
            ) : predictionError ? (
              <div className="flex items-center justify-center py-6 text-amber-600">
                <AlertTriangle className="w-5 h-5 mr-2" />
                <span className="text-sm">Statistics unavailable for this date</span>
              </div>
            ) : predictionData ? (
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
                <div className="p-4 bg-blue-50 rounded-lg text-center">
                  <div className="text-xs text-blue-600 font-medium uppercase tracking-wide">Mean</div>
                  <div className="text-2xl font-bold text-blue-900 mt-1">
                    {predictionData.stats.mean?.toFixed(1) ?? '-'}
                  </div>
                  <div className="text-xs text-blue-500">ug/m3</div>
                </div>
                <div className="p-4 bg-green-50 rounded-lg text-center">
                  <div className="text-xs text-green-600 font-medium uppercase tracking-wide">Median</div>
                  <div className="text-2xl font-bold text-green-900 mt-1">
                    {predictionData.stats.median?.toFixed(1) ?? '-'}
                  </div>
                  <div className="text-xs text-green-500">ug/m3</div>
                </div>
                <div className="p-4 bg-gray-50 rounded-lg text-center">
                  <div className="text-xs text-gray-600 font-medium uppercase tracking-wide">Min</div>
                  <div className="text-2xl font-bold text-gray-900 mt-1">
                    {predictionData.stats.min?.toFixed(1) ?? '-'}
                  </div>
                  <div className="text-xs text-gray-500">ug/m3</div>
                </div>
                <div className="p-4 bg-gray-50 rounded-lg text-center">
                  <div className="text-xs text-gray-600 font-medium uppercase tracking-wide">Max</div>
                  <div className="text-2xl font-bold text-gray-900 mt-1">
                    {predictionData.stats.max?.toFixed(1) ?? '-'}
                  </div>
                  <div className="text-xs text-gray-500">ug/m3</div>
                </div>
                <div className="p-4 bg-purple-50 rounded-lg text-center">
                  <div className="text-xs text-purple-600 font-medium uppercase tracking-wide">P5</div>
                  <div className="text-2xl font-bold text-purple-900 mt-1">
                    {predictionData.stats.p05?.toFixed(1) ?? '-'}
                  </div>
                  <div className="text-xs text-purple-500">ug/m3</div>
                </div>
                <div className="p-4 bg-purple-50 rounded-lg text-center">
                  <div className="text-xs text-purple-600 font-medium uppercase tracking-wide">P95</div>
                  <div className="text-2xl font-bold text-purple-900 mt-1">
                    {predictionData.stats.p95?.toFixed(1) ?? '-'}
                  </div>
                  <div className="text-xs text-purple-500">ug/m3</div>
                </div>
                <div className="p-4 bg-slate-100 rounded-lg text-center">
                  <div className="text-xs text-slate-600 font-medium uppercase tracking-wide">Cells</div>
                  <div className="text-2xl font-bold text-slate-900 mt-1">
                    {predictionData.stats.n_valid ? (predictionData.stats.n_valid / 1000).toFixed(1) + 'k' : '-'}
                  </div>
                  <div className="text-xs text-slate-500">valid</div>
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      )}

      {/* Empty state when no date selected */}
      {!selectedPredDate && !tileDatesLoading && dates.length > 0 && (
        <Card>
          <CardContent className="p-12 text-center text-gray-500">
            <Map className="w-16 h-16 mx-auto mb-4 opacity-30" />
            <p>Use the timeline above to select a date</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
