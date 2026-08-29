"use client"

import { useState, useEffect } from 'react'
import {
  ChevronLeft,
  ChevronRight,
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
}: ResultsTabProps) {
  const [model, setModel] = useState<'backbone' | 'support_aware'>('backbone')
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
    <div>
      {/* Map with timeline overlay at bottom */}
      {selectedPredDate ? (
        <div className="relative bg-slate-50 rounded-lg overflow-hidden" style={{ height: 'calc(100vh - 180px)', minHeight: '500px' }}>
          <PredictionMap selectedDate={selectedPredDate} smoothed={true} model={model} />

          {/* Model toggle — top right of map */}
          <div className="absolute top-4 right-4 z-10 bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-slate-200/60 p-1 flex">
            <button
              onClick={() => setModel('backbone')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                model === 'backbone'
                  ? 'bg-slate-800 text-white shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Satellite
            </button>
            <button
              onClick={() => setModel('support_aware')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                model === 'support_aware'
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              Enhanced
            </button>
          </div>

          {/* Timeline bar — slim, floating at bottom of map */}
          <div className="absolute bottom-3 left-4 right-4 z-10 flex items-center gap-3">
            <button
              onClick={() => { if (currentIndex > 0) setSelectedPredDate(dates[currentIndex - 1]) }}
              disabled={currentIndex <= 0}
              className="p-1.5 rounded-full bg-slate-800/80 hover:bg-slate-700/80 disabled:opacity-30 transition-colors"
            >
              <ChevronLeft className="w-4 h-4 text-white" />
            </button>

            <div className="text-center min-w-[110px] text-sm font-semibold text-slate-800 bg-white/90 backdrop-blur-sm rounded-full px-3 py-1 shadow-sm">
              {formatDisplayDate(selectedPredDate)}
            </div>

            <button
              onClick={() => { if (currentIndex < dates.length - 1) setSelectedPredDate(dates[currentIndex + 1]) }}
              disabled={currentIndex >= dates.length - 1}
              className="p-1.5 rounded-full bg-slate-800/80 hover:bg-slate-700/80 disabled:opacity-30 transition-colors"
            >
              <ChevronRight className="w-4 h-4 text-white" />
            </button>

            <div className="flex-1 relative flex items-center h-6">
              {/* Track background */}
              <div className="absolute left-0 right-0 h-[5px] rounded-full bg-slate-300/60" />
              {/* Track fill */}
              <div
                className="absolute left-0 h-[5px] rounded-full bg-slate-700"
                style={{ width: dates.length > 1 ? `${(currentIndex / (dates.length - 1)) * 100}%` : '0%' }}
              />
              <input
                type="range"
                min={0}
                max={dates.length - 1}
                value={currentIndex >= 0 ? currentIndex : 0}
                onChange={(e) => {
                  const idx = parseInt(e.target.value, 10)
                  if (dates[idx]) setSelectedPredDate(dates[idx])
                }}
                className="relative z-10 w-full h-[5px] appearance-none cursor-pointer bg-transparent
                  [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5
                  [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-400
                  [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:cursor-grab
                  [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white"
              />
            </div>
          </div>
        </div>
      ) : tileDatesLoading ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <div className="h-8 w-8 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
        </div>
      ) : dates.length === 0 ? (
        <div className="text-center py-20 text-gray-500">
          <Calendar className="w-6 h-6 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No predictions available</p>
        </div>
      ) : null}
    </div>
  )
}
