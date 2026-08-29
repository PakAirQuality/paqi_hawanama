"use client"

import { useEffect, useMemo } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  ChevronLeft,
  ChevronRight,
  Calendar,
  Cloud,
  Sun,
  Satellite,
} from 'lucide-react'
import type { FeaturesListResponse, FeatureDatesResponse, FeatureInfo } from './types'
import { FeatureMap } from './FeatureMap'

interface FeaturesTabProps {
  featuresList: FeaturesListResponse | undefined
  featuresListLoading: boolean
  selectedFeature: string | null
  setSelectedFeature: (feature: string | null) => void
  featureDates: FeatureDatesResponse | undefined
  featureDatesLoading: boolean
  selectedFeatureDate: string | null
  setSelectedFeatureDate: (date: string | null) => void
}

const STREAM_CONFIG = {
  met: { label: 'MET', icon: Cloud, color: 'blue' },
  aod: { label: 'AOD', icon: Sun, color: 'orange' },
  tropomi: { label: 'TROPOMI', icon: Satellite, color: 'purple' },
}

export function FeaturesTab({
  featuresList,
  featuresListLoading,
  selectedFeature,
  setSelectedFeature,
  featureDates,
  featureDatesLoading,
  selectedFeatureDate,
  setSelectedFeatureDate,
}: FeaturesTabProps) {
  const features = featuresList?.features || []
  const dates = featureDates?.dates || []
  const currentIndex = selectedFeatureDate ? dates.indexOf(selectedFeatureDate) : -1

  const grouped = useMemo(() => {
    const groups: Record<string, FeatureInfo[]> = {}
    for (const f of features) {
      const stage = f.stage.toLowerCase()
      if (!groups[stage]) groups[stage] = []
      groups[stage].push(f)
    }
    return groups
  }, [features])

  const currentFeatureInfo = useMemo(() => {
    return features.find(f => f.name === selectedFeature) || null
  }, [features, selectedFeature])

  const currentStream = currentFeatureInfo?.stage.toLowerCase() || null

  useEffect(() => {
    if (features.length > 0 && !selectedFeature) {
      setSelectedFeature(features[0].name)
    }
  }, [features, selectedFeature, setSelectedFeature])

  useEffect(() => {
    if (dates.length > 0 && !selectedFeatureDate) {
      setSelectedFeatureDate(dates[dates.length - 1])
    }
  }, [dates, selectedFeatureDate, setSelectedFeatureDate])

  useEffect(() => {
    setSelectedFeatureDate(null)
  }, [selectedFeature, setSelectedFeatureDate])

  const formatDisplayDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  return (
    <div className="space-y-3">
      {/* Stream Selectors - Compact Inline */}
      <Card>
        <CardContent className="p-3">
          {featuresListLoading ? (
            <div className="h-8 bg-gray-100 rounded animate-pulse"></div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              {Object.entries(STREAM_CONFIG).map(([stream, config]) => {
                const streamFeatures = grouped[stream] || []
                const isActive = currentStream === stream
                const Icon = config.icon
                const selectedInStream = streamFeatures.find(f => f.name === selectedFeature)

                return (
                  <div
                    key={stream}
                    className={`flex items-center gap-2 px-2 py-1 rounded-md border transition-all ${
                      isActive
                        ? stream === 'met' ? 'border-blue-400 bg-blue-50' :
                          stream === 'aod' ? 'border-orange-400 bg-orange-50' :
                          'border-purple-400 bg-purple-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <Icon className={`w-3.5 h-3.5 ${
                      isActive
                        ? stream === 'met' ? 'text-blue-600' :
                          stream === 'aod' ? 'text-orange-600' :
                          'text-purple-600'
                        : 'text-gray-400'
                    }`} />
                    <span className={`text-xs font-medium ${isActive ? 'text-gray-900' : 'text-gray-500'}`}>
                      {config.label}
                    </span>
                    <Select
                      value={selectedInStream?.name || ''}
                      onValueChange={(value) => setSelectedFeature(value)}
                    >
                      <SelectTrigger className="h-6 w-28 text-[11px] border-0 bg-transparent p-0 pl-1 focus:ring-0">
                        <SelectValue placeholder="Select..." />
                      </SelectTrigger>
                      <SelectContent>
                        {streamFeatures.map(f => (
                          <SelectItem key={f.name} value={f.name} className="text-xs">
                            {f.name} ({f.unit})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )
              })}

              {currentFeatureInfo && (
                <div className="text-[10px] text-gray-500 ml-auto">
                  Range: {currentFeatureInfo.vmin}–{currentFeatureInfo.vmax} {currentFeatureInfo.unit}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Date Scrubber - Compact */}
      {selectedFeature && (
        <Card>
          <CardContent className="p-2">
            {featureDatesLoading ? (
              <div className="h-8 bg-gray-100 rounded animate-pulse"></div>
            ) : dates.length === 0 ? (
              <div className="text-center py-2 text-gray-500">
                <Calendar className="w-4 h-4 mx-auto mb-1 opacity-50" />
                <p className="text-[10px]">No COGs available</p>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <button
                  onClick={() => { if (currentIndex > 0) setSelectedFeatureDate(dates[currentIndex - 1]) }}
                  disabled={currentIndex <= 0}
                  className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30 transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <div className="text-center min-w-[90px]">
                  <div className="text-sm font-semibold text-gray-900">
                    {selectedFeatureDate ? formatDisplayDate(selectedFeatureDate) : 'Select'}
                  </div>
                </div>
                <button
                  onClick={() => { if (currentIndex < dates.length - 1) setSelectedFeatureDate(dates[currentIndex + 1]) }}
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
                      if (dates[idx]) setSelectedFeatureDate(dates[idx])
                    }}
                    className="w-full h-1 bg-gradient-to-r from-blue-200 via-blue-400 to-blue-600 rounded-full appearance-none cursor-pointer
                      [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
                      [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2
                      [&::-webkit-slider-thumb]:border-blue-600 [&::-webkit-slider-thumb]:shadow [&::-webkit-slider-thumb]:cursor-grab"
                  />
                </div>
                <div className="text-[10px] text-gray-500 min-w-[60px] text-right">
                  {currentIndex + 1}/{dates.length}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Map - Full screen like main dashboard */}
      {selectedFeatureDate && currentFeatureInfo && (
        <div className="relative bg-slate-50 rounded-lg overflow-hidden" style={{ height: 'calc(100vh - 280px)', minHeight: '400px' }}>
          <FeatureMap selectedDate={selectedFeatureDate} feature={currentFeatureInfo} />
        </div>
      )}

      {!selectedFeatureDate && !featureDatesLoading && selectedFeature && dates.length > 0 && (
        <div className="py-8 text-center text-gray-500">
          <p className="text-sm">Select a date above to view the map</p>
        </div>
      )}
    </div>
  )
}
