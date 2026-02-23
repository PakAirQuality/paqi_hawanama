"use client"

import { useQuery } from '@tanstack/react-query'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  RefreshCw,
  Loader2,
  GitCommit,
  Database,
  Calendar,
  BarChart3,
  Settings2,
} from 'lucide-react'
import type { PipelineSummary, ModelDetails } from './types'
import { StatusBadge } from './StatusBadges'
import { formatDuration, formatDate } from './utils'
import { fetchModelDetails } from './api'

interface OverviewTabProps {
  summary: PipelineSummary | undefined
  summaryLoading: boolean
  triggerRetrainMutation: { mutate: () => void; isPending: boolean }
  hasRunningRetrain: boolean
}

export function OverviewTab({
  summary,
  summaryLoading,
  triggerRetrainMutation,
  hasRunningRetrain,
}: OverviewTabProps) {
  const latestRun = summary?.latest_run_report

  // Fetch model details
  const { data: modelDetails, isLoading: modelDetailsLoading } = useQuery({
    queryKey: ["ops-pipeline-model-details"],
    queryFn: fetchModelDetails,
  })

  const handleRetrainClick = () => {
    if (window.confirm('Are you sure you want to trigger model retraining? This may take several minutes.')) {
      triggerRetrainMutation.mutate()
    }
  }

  return (
    <>
      {/* Action Button */}
      <div className="flex items-center">
        <button
          onClick={handleRetrainClick}
          disabled={triggerRetrainMutation.isPending || hasRunningRetrain}
          className="flex items-center space-x-1.5 px-3 py-1.5 bg-purple-600 text-white text-xs rounded-md hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {(triggerRetrainMutation.isPending || hasRunningRetrain) ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
          <span>{hasRunningRetrain ? 'Retraining...' : 'Run Retrain'}</span>
        </button>
      </div>

      {/* Status Cards */}
      <div className="grid gap-3 md:grid-cols-4">
        {/* Last Published */}
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center space-x-2 mb-1">
              <Calendar className="w-3.5 h-3.5 text-gray-500" />
              <h3 className="text-xs font-medium text-gray-600">Last Published</h3>
            </div>
            {summaryLoading ? (
              <div className="h-6 bg-gray-200 rounded animate-pulse"></div>
            ) : (
              <div className="text-lg font-bold text-gray-900">
                {summary?.predictions_pointer?.last_published_date || 'N/A'}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Latest Run Status */}
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center space-x-2 mb-1">
              <BarChart3 className="w-3.5 h-3.5 text-gray-500" />
              <h3 className="text-xs font-medium text-gray-600">Latest Run</h3>
            </div>
            {summaryLoading ? (
              <div className="h-6 bg-gray-200 rounded animate-pulse"></div>
            ) : latestRun ? (
              <div className="space-y-0.5">
                <StatusBadge success={latestRun.success} />
                <div className="text-xs text-gray-500">
                  {latestRun.date} ({formatDuration(latestRun.details?.runtime_seconds ?? 0)})
                </div>
              </div>
            ) : (
              <div className="text-gray-400 text-sm">No runs</div>
            )}
          </CardContent>
        </Card>

        {/* Model Waterline */}
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center space-x-2 mb-1">
              <Database className="w-3.5 h-3.5 text-gray-500" />
              <h3 className="text-xs font-medium text-gray-600">Model Waterline</h3>
            </div>
            {summaryLoading ? (
              <div className="h-6 bg-gray-200 rounded animate-pulse"></div>
            ) : (
              <div className="text-lg font-bold text-gray-900">
                {summary?.model_pointer?.waterline || 'N/A'}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Git Commit */}
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center space-x-2 mb-1">
              <GitCommit className="w-3.5 h-3.5 text-gray-500" />
              <h3 className="text-xs font-medium text-gray-600">Git Commit</h3>
            </div>
            {summaryLoading ? (
              <div className="h-6 bg-gray-200 rounded animate-pulse"></div>
            ) : (
              <div className="text-base font-mono text-gray-900">
                {summary?.model_pointer?.git_commit || 'N/A'}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Model & Run Details */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Model Pointer */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold flex items-center space-x-2">
              <Database className="w-4 h-4" />
              <span>Current Model</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {summaryLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-3 bg-gray-200 rounded animate-pulse"></div>
                ))}
              </div>
            ) : summary?.model_pointer ? (
              <div className="space-y-1">
                <div className="flex justify-between items-center py-1.5 border-b border-gray-100 gap-2">
                  <span className="text-xs text-gray-600 shrink-0">Model URI</span>
                  <a
                    href={summary.model_pointer.model_uri.replace('gs://', 'https://console.cloud.google.com/storage/browser/')}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-mono text-blue-600 hover:text-blue-800 hover:underline truncate max-w-[160px]"
                    title={summary.model_pointer.model_uri}
                  >
                    {summary.model_pointer.model_uri.split('/').slice(-2).join('/')}
                  </a>
                </div>
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Waterline</span>
                  <span className="text-xs font-medium text-gray-900">{summary.model_pointer.waterline}</span>
                </div>
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Cutoff Days</span>
                  <span className="text-xs font-medium text-gray-900">{summary.model_pointer.cutoff_days}</span>
                </div>
                <div className="flex justify-between py-1.5">
                  <span className="text-xs text-gray-600">Created</span>
                  <span className="text-xs text-gray-900">{formatDate(summary.model_pointer.created_at_utc)}</span>
                </div>
              </div>
            ) : (
              <div className="text-center py-4 text-gray-500 text-sm">No model pointer found</div>
            )}
          </CardContent>
        </Card>

        {/* Model Metrics */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-semibold flex items-center space-x-2">
              <BarChart3 className="w-4 h-4" />
              <span>Model Metrics</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {modelDetailsLoading ? (
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-3 bg-gray-200 rounded animate-pulse"></div>
                ))}
              </div>
            ) : modelDetails?.training_mode === 'operational' ? (
              // Operational waterline format
              <div className="space-y-3">
                {/* Validation Metrics */}
                <div>
                  <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1.5">
                    Validation ({modelDetails.val_date_range?.[0]} → {modelDetails.val_date_range?.[1]})
                  </div>
                  <div className="grid grid-cols-4 gap-2">
                    <div className="p-2 bg-blue-50 rounded">
                      <div className="text-[10px] text-blue-600">R²</div>
                      <div className="text-base font-bold text-blue-900">
                        {modelDetails.val_metrics?.r2?.toFixed(3) ?? 'N/A'}
                      </div>
                    </div>
                    <div className="p-2 bg-green-50 rounded">
                      <div className="text-[10px] text-green-600">MAE</div>
                      <div className="text-base font-bold text-green-900">
                        {modelDetails.val_metrics?.mae?.toFixed(1) ?? 'N/A'}
                      </div>
                    </div>
                    <div className="p-2 bg-purple-50 rounded">
                      <div className="text-[10px] text-purple-600">RMSE</div>
                      <div className="text-base font-bold text-purple-900">
                        {modelDetails.val_metrics?.rmse?.toFixed(1) ?? 'N/A'}
                      </div>
                    </div>
                    <div className="p-2 bg-amber-50 rounded">
                      <div className="text-[10px] text-amber-600">Bias</div>
                      <div className="text-base font-bold text-amber-900">
                        {modelDetails.val_metrics?.bias?.toFixed(1) ?? 'N/A'}
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
                        {modelDetails.val_metrics?.skill_vs_station_month != null
                          ? `${(modelDetails.val_metrics.skill_vs_station_month * 100).toFixed(1)}%`
                          : 'N/A'}
                      </div>
                    </div>
                    <div className="p-2 bg-indigo-50 rounded">
                      <div className="text-[10px] text-indigo-600">vs Persistence</div>
                      <div className="text-base font-bold text-indigo-900">
                        {modelDetails.val_metrics?.skill_vs_yesterday != null
                          ? `${(modelDetails.val_metrics.skill_vs_yesterday * 100).toFixed(1)}%`
                          : 'N/A'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Monthly Breakdown */}
                {modelDetails.val_monthly && Object.keys(modelDetails.val_monthly).length > 0 && (
                  <div className="pt-2 border-t border-gray-100">
                    <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1">
                      Monthly MAE (μg/m³)
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(modelDetails.val_monthly).map(([month, metrics]) => {
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
            ) : modelDetails?.training_mode === 'cv' ? (
              // CV training format
              <div className="space-y-3">
                {/* CV Summary */}
                <div>
                  <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1.5">
                    Cross-Validation (expanding window)
                  </div>
                  <div className="grid grid-cols-4 gap-2">
                    <div className="p-2 bg-blue-50 rounded">
                      <div className="text-[10px] text-blue-600">R²</div>
                      <div className="text-base font-bold text-blue-900">
                        {modelDetails.cv?.summary?.r2?.mean?.toFixed(3) ?? 'N/A'}
                      </div>
                      <div className="text-[10px] text-blue-500">
                        ±{modelDetails.cv?.summary?.r2?.std?.toFixed(3) ?? '0'}
                      </div>
                    </div>
                    <div className="p-2 bg-green-50 rounded">
                      <div className="text-[10px] text-green-600">MAE</div>
                      <div className="text-base font-bold text-green-900">
                        {modelDetails.cv?.summary?.mae?.mean?.toFixed(1) ?? 'N/A'}
                      </div>
                      <div className="text-[10px] text-green-500">
                        ±{modelDetails.cv?.summary?.mae?.std?.toFixed(1) ?? '0'}
                      </div>
                    </div>
                    <div className="p-2 bg-purple-50 rounded">
                      <div className="text-[10px] text-purple-600">RMSE</div>
                      <div className="text-base font-bold text-purple-900">
                        {modelDetails.cv?.summary?.rmse?.mean?.toFixed(1) ?? 'N/A'}
                      </div>
                      <div className="text-[10px] text-purple-500">
                        ±{modelDetails.cv?.summary?.rmse?.std?.toFixed(1) ?? '0'}
                      </div>
                    </div>
                    <div className="p-2 bg-amber-50 rounded">
                      <div className="text-[10px] text-amber-600">Bias</div>
                      <div className="text-base font-bold text-amber-900">
                        {modelDetails.cv?.summary?.bias?.mean?.toFixed(1) ?? 'N/A'}
                      </div>
                      <div className="text-[10px] text-amber-500">
                        ±{modelDetails.cv?.summary?.bias?.std?.toFixed(1) ?? '0'}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Validation Folds */}
                <div>
                  <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1">
                    Validation Folds
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {modelDetails.cv?.folds && Object.entries(modelDetails.cv.folds).map(([year, fold]) => (
                      <Badge
                        key={year}
                        variant="outline"
                        className="text-[10px] px-1.5 py-0 bg-gray-50"
                        title={`Train: ${fold.train_years.join(', ')} → Val: ${year}\nR²: ${fold.val_metrics?.r2?.toFixed(3)}, MAE: ${fold.val_metrics?.mae?.toFixed(1)}`}
                      >
                        {year}: R²={fold.val_metrics?.r2?.toFixed(2)}
                      </Badge>
                    ))}
                  </div>
                </div>

                {/* Test Set Performance */}
                {modelDetails.final_model?.test_overall && (
                  <div className="pt-2 border-t border-gray-100">
                    <div className="text-[10px] font-medium text-gray-500 uppercase tracking-wide mb-1">
                      Held-out Test ({modelDetails.test_samples?.toLocaleString()} samples)
                    </div>
                    <div className="flex gap-3 text-xs">
                      <span className="text-gray-600">
                        R²: <span className="font-medium text-gray-900">{modelDetails.final_model.test_overall.r2?.toFixed(3)}</span>
                      </span>
                      <span className="text-gray-600">
                        MAE: <span className="font-medium text-gray-900">{modelDetails.final_model.test_overall.mae?.toFixed(1)}</span>
                      </span>
                      <span className="text-gray-600">
                        RMSE: <span className="font-medium text-gray-900">{modelDetails.final_model.test_overall.rmse?.toFixed(1)}</span>
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-4 text-gray-500 text-sm">No model metrics available</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Training Details, Model Type & Hyperparameters - Three Cards */}
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
            {modelDetailsLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-3 bg-gray-200 rounded animate-pulse"></div>
                ))}
              </div>
            ) : modelDetails ? (
              <div className="space-y-1">
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Reference Date</span>
                  <span className="text-xs font-medium text-gray-900">{modelDetails.reference_date || 'N/A'}</span>
                </div>
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Cutoff Days</span>
                  <span className="text-xs font-medium text-gray-900">{modelDetails.cutoff_days || 'N/A'}</span>
                </div>
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Train Range</span>
                  <span className="text-xs font-mono text-gray-900">
                    {modelDetails.train_date_range ? `${modelDetails.train_date_range[0]} → ${modelDetails.train_date_range[1]}` : 'N/A'}
                  </span>
                </div>
                <div className="flex justify-between py-1.5">
                  <span className="text-xs text-gray-600">Val Range</span>
                  <span className="text-xs font-mono text-gray-900">
                    {modelDetails.val_date_range ? `${modelDetails.val_date_range[0]} → ${modelDetails.val_date_range[1]}` : 'N/A'}
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-center py-4 text-gray-500 text-sm">No training details available</div>
            )}
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
            {modelDetailsLoading ? (
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-3 bg-gray-200 rounded animate-pulse"></div>
                ))}
              </div>
            ) : modelDetails ? (
              <div className="space-y-1">
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Algorithm</span>
                  <span className="text-xs font-medium text-gray-900">LightGBM</span>
                </div>
                <div className="flex justify-between items-center py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Training Mode</span>
                  <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                    {modelDetails.training_mode === 'operational' ? 'Operational' : 'Cross-Val'}
                  </Badge>
                </div>
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Features</span>
                  <span className="text-xs font-medium text-gray-900">{modelDetails.n_features}</span>
                </div>
                <div className="flex justify-between py-1.5 border-b border-gray-100">
                  <span className="text-xs text-gray-600">Train Samples</span>
                  <span className="text-xs font-medium text-gray-900">{modelDetails.train_samples?.toLocaleString()}</span>
                </div>
                {modelDetails.val_samples && (
                  <div className="flex justify-between py-1.5 border-b border-gray-100">
                    <span className="text-xs text-gray-600">Val Samples</span>
                    <span className="text-xs font-medium text-gray-900">{modelDetails.val_samples?.toLocaleString()}</span>
                  </div>
                )}
                {modelDetails.train_years && modelDetails.train_years.length > 0 && (
                  <div className="flex justify-between py-1.5">
                    <span className="text-xs text-gray-600">Train Years</span>
                    <span className="text-xs font-medium text-gray-900">
                      {modelDetails.train_years[0]} - {modelDetails.train_years[modelDetails.train_years.length - 1]}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-4 text-gray-500 text-sm">No model type available</div>
            )}
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
            {modelDetailsLoading ? (
              <div className="space-y-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="h-3 bg-gray-200 rounded animate-pulse"></div>
                ))}
              </div>
            ) : modelDetails?.lgbm_params_used ? (
              <div className="space-y-0.5">
                {(() => {
                  const params = modelDetails.lgbm_params_used
                  // Define display order for key hyperparameters
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
            ) : modelDetails?.best_params ? (
              // CV training format uses best_params
              <div className="space-y-0.5">
                {Object.entries(modelDetails.best_params).slice(0, 10).map(([key, value], idx, arr) => (
                  <div
                    key={key}
                    className={`flex justify-between py-1 ${idx < arr.length - 1 ? 'border-b border-gray-100' : ''}`}
                  >
                    <span className="text-xs text-gray-600">{key}</span>
                    <span className="text-xs font-mono text-gray-900">
                      {typeof value === 'number'
                        ? (key === 'n_estimators' ? value.toLocaleString() : key === 'learning_rate' ? value.toFixed(3) : Number.isInteger(value) ? value : value.toFixed(2))
                        : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-4 text-gray-500 text-sm">No hyperparameters available</div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
