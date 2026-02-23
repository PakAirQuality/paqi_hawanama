"use client"

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Loader2,
  Calendar,
  BarChart3,
  Settings2,
} from 'lucide-react'
import type { ModelHistoryResponse, ModelHistoryEntry } from './types'

interface ModelHistoryTabProps {
  history: ModelHistoryResponse | undefined
  historyLoading: boolean
  selectedRefDate: string | null
  setSelectedRefDate: (date: string | null) => void
  selectedEntry: ModelHistoryEntry | null | undefined
  selectedEntryLoading: boolean
}

export function ModelHistoryTab({
  history,
  historyLoading,
  selectedRefDate,
  setSelectedRefDate,
  selectedEntry,
  selectedEntryLoading,
}: ModelHistoryTabProps) {
  const reversedDates = history?.reference_dates ? [...history.reference_dates].reverse() : []

  return (
    <div className="space-y-4">
      {/* Date Selector */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Calendar className="w-4 h-4" />
          <span>Training Date:</span>
        </div>
        {historyLoading ? (
          <div className="w-48 h-9 bg-gray-100 rounded-md animate-pulse" />
        ) : reversedDates.length > 0 ? (
          <Select
            value={selectedRefDate || undefined}
            onValueChange={(value) => setSelectedRefDate(value)}
          >
            <SelectTrigger className="w-48 text-sm">
              <SelectValue placeholder="Select a date..." />
            </SelectTrigger>
            <SelectContent>
              {reversedDates.map((date) => (
                <SelectItem key={date} value={date} className="text-sm">
                  {date}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="text-sm text-gray-400">No history available</span>
        )}
        {selectedRefDate && (
          <Badge variant="outline" className="text-xs">
            {reversedDates.findIndex(d => d === selectedRefDate) + 1} of {reversedDates.length}
          </Badge>
        )}
      </div>

      {/* Selected Entry Details */}
      {selectedRefDate ? (
        selectedEntryLoading ? (
          <Card>
            <CardContent className="py-12">
              <div className="flex items-center justify-center">
                <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
              </div>
            </CardContent>
          </Card>
        ) : selectedEntry ? (
          <div className="space-y-4">
            {/* Model Metrics */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold flex items-center space-x-2">
                  <BarChart3 className="w-4 h-4" />
                  <span>Model Metrics</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="space-y-3">
                  {/* Validation Metrics */}
                  <div>
                    <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1.5">
                      Validation ({selectedEntry.val_date_range?.[0]} → {selectedEntry.val_date_range?.[1]})
                    </div>
                    <div className="grid grid-cols-4 gap-2">
                      <div className="p-2 bg-blue-50 rounded">
                        <div className="text-[10px] text-blue-600">R²</div>
                        <div className="text-base font-bold text-blue-900">
                          {selectedEntry.val_metrics?.r2?.toFixed(3) ?? 'N/A'}
                        </div>
                      </div>
                      <div className="p-2 bg-green-50 rounded">
                        <div className="text-[10px] text-green-600">MAE</div>
                        <div className="text-base font-bold text-green-900">
                          {selectedEntry.val_metrics?.mae?.toFixed(1) ?? 'N/A'}
                        </div>
                      </div>
                      <div className="p-2 bg-purple-50 rounded">
                        <div className="text-[10px] text-purple-600">RMSE</div>
                        <div className="text-base font-bold text-purple-900">
                          {selectedEntry.val_metrics?.rmse?.toFixed(1) ?? 'N/A'}
                        </div>
                      </div>
                      <div className="p-2 bg-amber-50 rounded">
                        <div className="text-[10px] text-amber-600">Bias</div>
                        <div className="text-base font-bold text-amber-900">
                          {selectedEntry.val_metrics?.bias?.toFixed(1) ?? 'N/A'}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Skill Metrics */}
                  <div className="pt-2 border-t border-gray-100">
                    <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1.5">
                      Skill (MAE-based)
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="p-2 bg-teal-50 rounded">
                        <div className="text-[10px] text-teal-600">vs Station-Month</div>
                        <div className="text-base font-bold text-teal-900">
                          {selectedEntry.val_metrics?.skill_vs_station_month != null
                            ? `${(selectedEntry.val_metrics.skill_vs_station_month * 100).toFixed(1)}%`
                            : 'N/A'}
                        </div>
                      </div>
                      <div className="p-2 bg-indigo-50 rounded">
                        <div className="text-[10px] text-indigo-600">vs Persistence</div>
                        <div className="text-base font-bold text-indigo-900">
                          {selectedEntry.val_metrics?.skill_vs_yesterday != null
                            ? `${(selectedEntry.val_metrics.skill_vs_yesterday * 100).toFixed(1)}%`
                            : 'N/A'}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Monthly Breakdown */}
                  {selectedEntry.val_monthly && Object.keys(selectedEntry.val_monthly).length > 0 && (
                    <div className="pt-2 border-t border-gray-100">
                      <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1">
                        Monthly MAE (μg/m³)
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(selectedEntry.val_monthly).map(([month, metrics]) => {
                          const monthNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                          return (
                            <Badge
                              key={month}
                              variant="outline"
                              className="text-[10px] px-1.5 py-0 bg-gray-50"
                              title={`R²: ${metrics.r2?.toFixed(3)}, RMSE: ${metrics.rmse?.toFixed(1)}, n=${metrics.n_predictions}`}
                            >
                              {monthNames[parseInt(month)]}: {metrics.mae?.toFixed(1)}
                            </Badge>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Training Details, Model Type & Hyperparameters */}
            <div className="grid gap-4 lg:grid-cols-3">
              {/* Training Details */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base font-semibold flex items-center space-x-2">
                    <Calendar className="w-4 h-4" />
                    <span>Training Details</span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="space-y-1">
                    <div className="flex justify-between py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Reference Date</span>
                      <span className="text-xs font-medium text-gray-900">{selectedEntry.reference_date}</span>
                    </div>
                    <div className="flex justify-between py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Cutoff Days</span>
                      <span className="text-xs font-medium text-gray-900">{selectedEntry.cutoff_days}</span>
                    </div>
                    <div className="flex justify-between py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Train Range</span>
                      <span className="text-xs font-mono text-gray-900">
                        {selectedEntry.train_date_range ? `${selectedEntry.train_date_range[0]} → ${selectedEntry.train_date_range[1]}` : 'N/A'}
                      </span>
                    </div>
                    <div className="flex justify-between py-1.5">
                      <span className="text-xs text-gray-600">Val Range</span>
                      <span className="text-xs font-mono text-gray-900">
                        {selectedEntry.val_date_range ? `${selectedEntry.val_date_range[0]} → ${selectedEntry.val_date_range[1]}` : 'N/A'}
                      </span>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Model Type */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base font-semibold flex items-center space-x-2">
                    <Settings2 className="w-4 h-4" />
                    <span>Model Type</span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="space-y-1">
                    <div className="flex justify-between py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Algorithm</span>
                      <span className="text-xs font-medium text-gray-900">LightGBM</span>
                    </div>
                    <div className="flex justify-between items-center py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Training Mode</span>
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">Operational</Badge>
                    </div>
                    <div className="flex justify-between py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Features</span>
                      <span className="text-xs font-medium text-gray-900">{selectedEntry.n_features}</span>
                    </div>
                    <div className="flex justify-between py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Train Samples</span>
                      <span className="text-xs font-medium text-gray-900">{selectedEntry.train_samples?.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between py-1.5 border-b border-gray-100">
                      <span className="text-xs text-gray-600">Val Samples</span>
                      <span className="text-xs font-medium text-gray-900">{selectedEntry.val_samples?.toLocaleString()}</span>
                    </div>
                    {selectedEntry.train_years && selectedEntry.train_years.length > 0 && (
                      <div className="flex justify-between py-1.5">
                        <span className="text-xs text-gray-600">Train Years</span>
                        <span className="text-xs font-medium text-gray-900">
                          {selectedEntry.train_years[0]} - {selectedEntry.train_years[selectedEntry.train_years.length - 1]}
                        </span>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Hyperparameters */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base font-semibold flex items-center space-x-2">
                    <Settings2 className="w-4 h-4" />
                    <span>Hyperparameters</span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  {selectedEntry.lgbm_params_used ? (
                    <div className="space-y-0.5">
                      {(() => {
                        const params = selectedEntry.lgbm_params_used
                        const displayOrder = [
                          'max_depth', 'num_leaves', 'learning_rate', 'n_estimators',
                          'min_child_samples', 'subsample', 'colsample_bytree',
                          'reg_lambda', 'reg_alpha', 'min_split_gain'
                        ]
                        const entries = displayOrder
                          .filter(key => params[key] !== undefined)
                          .map(key => [key, params[key]] as [string, number | string | boolean])

                        const formatValue = (key: string, value: number | string | boolean): string => {
                          if (typeof value === 'number') {
                            if (key === 'n_estimators') return value.toLocaleString()
                            if (key === 'learning_rate') return value.toFixed(3)
                            if (Number.isInteger(value)) return value.toString()
                            return value.toFixed(2)
                          }
                          return String(value)
                        }

                        return entries.map(([key, value], idx) => (
                          <div
                            key={key}
                            className={`flex justify-between py-1 ${idx < entries.length - 1 ? 'border-b border-gray-100' : ''}`}
                          >
                            <span className="text-xs text-gray-600">{key}</span>
                            <span className="text-xs font-mono text-gray-900">{formatValue(key, value)}</span>
                          </div>
                        ))
                      })()}
                    </div>
                  ) : (
                    <div className="text-center py-4 text-gray-500 text-sm">No hyperparameters available</div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        ) : (
          <Card>
            <CardContent className="py-12">
              <div className="text-center text-gray-500 text-sm">
                Failed to load model details
              </div>
            </CardContent>
          </Card>
        )
      ) : (
        <Card>
          <CardContent className="py-12">
            <div className="text-center text-gray-500 text-sm">
              Select a training date to view model details
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
