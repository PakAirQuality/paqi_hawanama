"use client"

import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Calendar } from 'lucide-react'

import { fetchTileDates } from '@/components/ops-pipeline'
import { PredictionMap } from '@/components/ops-pipeline/PredictionMap'
import { IconRail, type RailTab } from '@/components/analyst-desk/IconRail'
import { CopilotChat } from '@/components/analyst-desk/CopilotChat'

export default function OpsPipelinePage() {
  const [selectedPredDate, setSelectedPredDate] = useState<string | null>(null)
  const [model, setModel] = useState<'backbone' | 'support_aware'>('backbone')

  // Side channel state
  const [railTab, setRailTab] = useState<RailTab | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)

  // Force map resize when panel opens/closes
  const mapWrapperRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Dispatch a resize event so mapbox-gl picks up the container change
    let raf: number
    const tick = () => {
      window.dispatchEvent(new Event('resize'))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const stop = setTimeout(() => cancelAnimationFrame(raf), 350)
    return () => { cancelAnimationFrame(raf); clearTimeout(stop) }
  }, [railTab])

  const { data: tileDates, isLoading: tileDatesLoading } = useQuery({
    queryKey: ["ops-pipeline-tile-dates"],
    queryFn: () => fetchTileDates(365),
  })

  const dates = tileDates?.dates || []
  const currentIndex = selectedPredDate ? dates.indexOf(selectedPredDate) : -1

  useEffect(() => {
    if (dates.length > 0 && !selectedPredDate) {
      setSelectedPredDate(dates[dates.length - 1])
    }
  }, [dates, selectedPredDate])

  const formatDisplayDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  if (tileDatesLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-slate-50">
        <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-slate-800/90 text-white text-sm font-medium shadow-lg">
          <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          Loading predictions...
        </div>
      </div>
    )
  }

  if (dates.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center bg-slate-50">
        <div className="text-center text-gray-500">
          <Calendar className="w-6 h-6 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No predictions available</p>
        </div>
      </div>
    )
  }

  if (!selectedPredDate) return null

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* Icon rail */}
      <IconRail
        activeTab={railTab}
        onTabChange={setRailTab}
        isStreaming={isStreaming}
      />

      {/* Sliding panel */}
      <div
        style={{
          width: railTab ? 370 : 0,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          background: '#fff',
          borderRight: railTab ? '1px solid #e2e8f0' : 'none',
          overflow: 'hidden',
          transition: 'width 250ms cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        {/* Chat / Analytics panel */}
        <div style={{
          display: railTab === 'chat' || railTab === 'analytics' ? 'flex' : 'none',
          flexDirection: 'column',
          height: '100%',
        }}>
          <CopilotChat
            selectedDate={selectedPredDate}
            onStreamingChange={setIsStreaming}
            activeTab={railTab === 'analytics' ? 'analytics' : 'chat'}
          />
        </div>

        {/* Layers panel — model selector for prediction map */}
        <div style={{ display: railTab === 'layers' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <div className="flex flex-col h-full">
            <div className="px-4 py-3 border-b border-slate-100">
              <h3 className="text-xs font-semibold text-slate-800 uppercase tracking-wide">
                Model Layers
              </h3>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-1">
              <button
                onClick={() => setModel('backbone')}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${
                  model === 'backbone'
                    ? 'bg-slate-50 hover:bg-slate-100'
                    : 'bg-white hover:bg-slate-50 opacity-50'
                }`}
              >
                <div className={`shrink-0 ${model === 'backbone' ? 'text-slate-700' : 'text-slate-300'}`}>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m8.66-13.66l-.71.71M4.05 19.95l-.71.71M21 12h-1M4 12H3m16.66 7.66l-.71-.71M4.05 4.05l-.71-.71" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <div className={`text-xs font-medium ${model === 'backbone' ? 'text-slate-700' : 'text-slate-400'}`}>
                    Satellite
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">
                    Backbone model (AOD + meteorology)
                  </div>
                </div>
                <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${
                  model === 'backbone' ? 'bg-slate-700 justify-end' : 'bg-slate-200 justify-start'
                }`}>
                  <div className={`w-3 h-3 rounded-full mx-0.5 transition-colors ${
                    model === 'backbone' ? 'bg-white' : 'bg-slate-400'
                  }`} />
                </div>
              </button>

              <button
                onClick={() => setModel('support_aware')}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${
                  model === 'support_aware'
                    ? 'bg-slate-50 hover:bg-slate-100'
                    : 'bg-white hover:bg-slate-50 opacity-50'
                }`}
              >
                <div className={`shrink-0 ${model === 'support_aware' ? 'text-emerald-600' : 'text-slate-300'}`}>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <div className={`text-xs font-medium ${model === 'support_aware' ? 'text-slate-700' : 'text-slate-400'}`}>
                    Enhanced
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">
                    Station-aware with ground truth blending
                  </div>
                </div>
                <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${
                  model === 'support_aware' ? 'bg-emerald-600 justify-end' : 'bg-slate-200 justify-start'
                }`}>
                  <div className={`w-3 h-3 rounded-full mx-0.5 transition-colors ${
                    model === 'support_aware' ? 'bg-white' : 'bg-slate-400'
                  }`} />
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Map — fills remaining space */}
      <div ref={mapWrapperRef} className="flex-1 relative min-h-0">
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
            <div className="absolute left-0 right-0 h-[5px] rounded-full bg-slate-300/60" />
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
    </div>
  )
}
