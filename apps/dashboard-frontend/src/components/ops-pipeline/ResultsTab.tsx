"use client"

import { useState, useEffect, useMemo } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import {
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
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
  const [smoothed, setSmoothed] = useState(false)
  const dates = tileDates?.dates || []
  const currentIndex = selectedPredDate ? dates.indexOf(selectedPredDate) : -1

  useEffect(() => {
    if (dates.length > 0 && !selectedPredDate) {
      setSelectedPredDate(dates[dates.length - 1])
    }
  }, [dates, selectedPredDate, setSelectedPredDate])

  const formatDisplayDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  return (
    <div className="space-y-3">
      {/* Timeline Scrubber - Compact */}
      <Card>
        <CardContent className="p-2">
          {tileDatesLoading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse"></div>
          ) : dates.length === 0 ? (
            <div className="text-center py-2 text-gray-500">
              <Calendar className="w-4 h-4 mx-auto mb-1 opacity-50" />
              <p className="text-[10px]">No predictions available</p>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <button
                onClick={() => { if (currentIndex > 0) setSelectedPredDate(dates[currentIndex - 1]) }}
                disabled={currentIndex <= 0}
                className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <div className="text-center min-w-[90px]">
                <div className="text-sm font-semibold text-gray-900">
                  {selectedPredDate ? formatDisplayDate(selectedPredDate) : 'Select'}
                </div>
              </div>
              <button
                onClick={() => { if (currentIndex < dates.length - 1) setSelectedPredDate(dates[currentIndex + 1]) }}
                disabled={currentIndex >= dates.length - 1}
                className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <div className="flex-1 px-1">
                <input
                  type="range"
                  min={0}
                  max={dates.length - 1}
                  value={currentIndex >= 0 ? currentIndex : 0}
                  onChange={(e) => {
                    const idx = parseInt(e.target.value, 10)
                    if (dates[idx]) setSelectedPredDate(dates[idx])
                  }}
                  className="w-full h-1 bg-gradient-to-r from-blue-200 via-blue-400 to-blue-600 rounded-full appearance-none cursor-pointer
                    [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                    [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2
                    [&::-webkit-slider-thumb]:border-blue-600 [&::-webkit-slider-thumb]:shadow [&::-webkit-slider-thumb]:cursor-grab"
                />
              </div>
              <button
                onClick={() => setSmoothed(s => !s)}
                className={`px-2 py-0.5 rounded-full text-[10px] font-medium transition-colors ${
                  smoothed
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-gray-100 text-gray-500'
                }`}
              >
                {smoothed ? 'Smoothed' : 'Raw'}
              </button>
              <div className="text-[10px] text-gray-500 min-w-[60px] text-right">
                {currentIndex + 1}/{dates.length}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Map - Full screen like main dashboard */}
      {selectedPredDate && (
        <div className="relative bg-slate-50 rounded-lg overflow-hidden" style={{ height: 'calc(100vh - 280px)', minHeight: '400px' }}>
          <PredictionMap selectedDate={selectedPredDate} smoothed={smoothed} />
        </div>
      )}

      {/* Statistics Panel - Compact */}
      {selectedPredDate && (
        <Card>
          <CardContent className="p-3">
            {predictionDataLoading ? (
              <div className="grid grid-cols-7 gap-2">
                {[...Array(7)].map((_, i) => (
                  <div key={i} className="h-12 bg-gray-100 rounded animate-pulse"></div>
                ))}
              </div>
            ) : predictionError ? (
              <div className="flex items-center justify-center py-3 text-amber-600">
                <AlertTriangle className="w-4 h-4 mr-2" />
                <span className="text-xs">Statistics unavailable</span>
              </div>
            ) : predictionData ? (
              <div className="grid grid-cols-4 md:grid-cols-7 gap-2">
                <div className="p-2 bg-blue-50 rounded text-center">
                  <div className="text-[10px] text-blue-600 font-medium uppercase">Mean</div>
                  <div className="text-base font-bold text-blue-900">
                    {predictionData.stats.mean?.toFixed(1) ?? '-'}
                  </div>
                </div>
                <div className="p-2 bg-green-50 rounded text-center">
                  <div className="text-[10px] text-green-600 font-medium uppercase">Median</div>
                  <div className="text-base font-bold text-green-900">
                    {predictionData.stats.median?.toFixed(1) ?? '-'}
                  </div>
                </div>
                <div className="p-2 bg-gray-50 rounded text-center">
                  <div className="text-[10px] text-gray-600 font-medium uppercase">Min</div>
                  <div className="text-base font-bold text-gray-900">
                    {predictionData.stats.min?.toFixed(1) ?? '-'}
                  </div>
                </div>
                <div className="p-2 bg-gray-50 rounded text-center">
                  <div className="text-[10px] text-gray-600 font-medium uppercase">Max</div>
                  <div className="text-base font-bold text-gray-900">
                    {predictionData.stats.max?.toFixed(1) ?? '-'}
                  </div>
                </div>
                <div className="p-2 bg-purple-50 rounded text-center">
                  <div className="text-[10px] text-purple-600 font-medium uppercase">P5</div>
                  <div className="text-base font-bold text-purple-900">
                    {predictionData.stats.p05?.toFixed(1) ?? '-'}
                  </div>
                </div>
                <div className="p-2 bg-purple-50 rounded text-center">
                  <div className="text-[10px] text-purple-600 font-medium uppercase">P95</div>
                  <div className="text-base font-bold text-purple-900">
                    {predictionData.stats.p95?.toFixed(1) ?? '-'}
                  </div>
                </div>
                <div className="p-2 bg-slate-100 rounded text-center">
                  <div className="text-[10px] text-slate-600 font-medium uppercase">Cells</div>
                  <div className="text-base font-bold text-slate-900">
                    {predictionData.stats.n_valid ? (predictionData.stats.n_valid / 1000).toFixed(0) + 'k' : '-'}
                  </div>
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {!selectedPredDate && !tileDatesLoading && dates.length > 0 && (
        <div className="py-8 text-center text-gray-500">
          <p className="text-sm">Select a date above to view the map</p>
        </div>
      )}
    </div>
  )
}
