"use client"

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Loader2,
  Calendar,
  BarChart3,
  Settings2,
  ChevronRight,
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
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      {/* Model History List */}
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle className="text-lg font-semibold flex items-center space-x-2">
            <Calendar className="w-5 h-5" />
            <span>Model Training History</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {historyLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
            </div>
          ) : history?.reference_dates?.length ? (
            <div className="space-y-1 max-h-[600px] overflow-y-auto">
              {[...history.reference_dates].reverse().map((date) => (
                <button
                  key={date}
                  onClick={() => setSelectedRefDate(date)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-center justify-between ${
                    selectedRefDate === date
                      ? 'bg-blue-100 text-blue-900 font-medium'
                      : 'hover:bg-gray-100 text-gray-700'
                  }`}
                >
                  <span>{date}</span>
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                </button>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No model training history available
            </div>
          )}
        </CardContent>
      </Card>

      {/* Selected Entry Details */}
      <div className="lg:col-span-2 space-y-6">
        {selectedRefDate ? (
          selectedEntryLoading ? (
            <Card>
              <CardContent className="py-16">
                <div className="flex items-center justify-center">
                  <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
                </div>
              </CardContent>
            </Card>
          ) : selectedEntry ? (
            <>
              {/* Model Metrics */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                    <BarChart3 className="w-5 h-5" />
                    <span>Model Metrics</span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    {/* Validation Metrics */}
                    <div>
                      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                        Validation Window ({selectedEntry.val_date_range?.[0]} to {selectedEntry.val_date_range?.[1]})
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <div className="p-3 bg-blue-50 rounded-lg">
                          <div className="text-xs text-blue-600">R²</div>
                          <div className="text-xl font-bold text-blue-900">
                            {selectedEntry.val_metrics?.r2?.toFixed(3) ?? 'N/A'}
                          </div>
                        </div>
                        <div className="p-3 bg-green-50 rounded-lg">
                          <div className="text-xs text-green-600">MAE</div>
                          <div className="text-xl font-bold text-green-900">
                            {selectedEntry.val_metrics?.mae?.toFixed(1) ?? 'N/A'}
                          </div>
                          <div className="text-xs text-green-500">μg/m³</div>
                        </div>
                        <div className="p-3 bg-purple-50 rounded-lg">
                          <div className="text-xs text-purple-600">RMSE</div>
                          <div className="text-xl font-bold text-purple-900">
                            {selectedEntry.val_metrics?.rmse?.toFixed(1) ?? 'N/A'}
                          </div>
                          <div className="text-xs text-purple-500">μg/m³</div>
                        </div>
                        <div className="p-3 bg-amber-50 rounded-lg">
                          <div className="text-xs text-amber-600">Bias</div>
                          <div className="text-xl font-bold text-amber-900">
                            {selectedEntry.val_metrics?.bias?.toFixed(1) ?? 'N/A'}
                          </div>
                          <div className="text-xs text-amber-500">μg/m³</div>
                        </div>
                      </div>
                    </div>

                    {/* Skill Metrics */}
                    <div className="pt-2 border-t border-gray-100">
                      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                        Skill Metrics (MAE-based)
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="p-3 bg-teal-50 rounded-lg">
                          <div className="text-xs text-teal-600">vs Station-Month Baseline</div>
                          <div className="text-xl font-bold text-teal-900">
                            {selectedEntry.val_metrics?.skill_vs_station_month != null
                              ? `${(selectedEntry.val_metrics.skill_vs_station_month * 100).toFixed(1)}%`
                              : 'N/A'}
                          </div>
                          <div className="text-xs text-teal-500">skill improvement</div>
                        </div>
                        <div className="p-3 bg-indigo-50 rounded-lg">
                          <div className="text-xs text-indigo-600">vs Persistence (yesterday)</div>
                          <div className="text-xl font-bold text-indigo-900">
                            {selectedEntry.val_metrics?.skill_vs_yesterday != null
                              ? `${(selectedEntry.val_metrics.skill_vs_yesterday * 100).toFixed(1)}%`
                              : 'N/A'}
                          </div>
                          <div className="text-xs text-indigo-500">skill improvement</div>
                        </div>
                      </div>
                    </div>

                    {/* Monthly Breakdown */}
                    {selectedEntry.val_monthly && Object.keys(selectedEntry.val_monthly).length > 0 && (
                      <div className="pt-2 border-t border-gray-100">
                        <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
                          Monthly Validation (MAE μg/m³)
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(selectedEntry.val_monthly).map(([month, metrics]) => {
                            const monthNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                            return (
                              <Badge
                                key={month}
                                variant="outline"
                                className="text-xs bg-gray-50"
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
              <div className="grid gap-6 lg:grid-cols-3">
                {/* Training Details */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                      <Calendar className="w-5 h-5" />
                      <span>Training Details</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Reference Date</span>
                        <span className="text-sm font-medium text-gray-900">{selectedEntry.reference_date}</span>
                      </div>
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Cutoff Days</span>
                        <span className="text-sm font-medium text-gray-900">{selectedEntry.cutoff_days}</span>
                      </div>
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Train Range</span>
                        <span className="text-sm font-mono text-gray-900">
                          {selectedEntry.train_date_range ? `${selectedEntry.train_date_range[0]} → ${selectedEntry.train_date_range[1]}` : 'N/A'}
                        </span>
                      </div>
                      <div className="flex justify-between py-2">
                        <span className="text-sm text-gray-600">Validation Range</span>
                        <span className="text-sm font-mono text-gray-900">
                          {selectedEntry.val_date_range ? `${selectedEntry.val_date_range[0]} → ${selectedEntry.val_date_range[1]}` : 'N/A'}
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Model Type */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                      <Settings2 className="w-5 h-5" />
                      <span>Model Type</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Algorithm</span>
                        <span className="text-sm font-medium text-gray-900">LightGBM</span>
                      </div>
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Training Mode</span>
                        <Badge variant="outline" className="text-xs">Operational Waterline</Badge>
                      </div>
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Features</span>
                        <span className="text-sm font-medium text-gray-900">{selectedEntry.n_features}</span>
                      </div>
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Training Samples</span>
                        <span className="text-sm font-medium text-gray-900">{selectedEntry.train_samples?.toLocaleString()}</span>
                      </div>
                      <div className="flex justify-between py-2 border-b border-gray-100">
                        <span className="text-sm text-gray-600">Validation Samples</span>
                        <span className="text-sm font-medium text-gray-900">{selectedEntry.val_samples?.toLocaleString()}</span>
                      </div>
                      {selectedEntry.train_years && selectedEntry.train_years.length > 0 && (
                        <div className="flex justify-between py-2">
                          <span className="text-sm text-gray-600">Training Years</span>
                          <span className="text-sm font-medium text-gray-900">
                            {selectedEntry.train_years[0]} - {selectedEntry.train_years[selectedEntry.train_years.length - 1]}
                          </span>
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>

                {/* Hyperparameters */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                      <Settings2 className="w-5 h-5" />
                      <span>Hyperparameters</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {selectedEntry.lgbm_params_used ? (
                      <div className="space-y-2">
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
                              <span className="text-sm text-gray-600">{key}</span>
                              <span className="text-sm font-mono text-gray-900">{formatValue(key, value)}</span>
                            </div>
                          ))
                        })()}
                      </div>
                    ) : (
                      <div className="text-center py-8 text-gray-500">No hyperparameters available</div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          ) : (
            <Card>
              <CardContent className="py-16">
                <div className="text-center text-gray-500">
                  Failed to load model details
                </div>
              </CardContent>
            </Card>
          )
        ) : (
          <Card>
            <CardContent className="py-16">
              <div className="text-center text-gray-500">
                Select a reference date to view model training details
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
