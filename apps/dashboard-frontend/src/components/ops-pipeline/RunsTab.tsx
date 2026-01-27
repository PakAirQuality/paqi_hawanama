"use client"

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { RunsResponse, RunReport } from './types'
import { StatusBadge } from './StatusBadges'
import { formatDuration, formatDate } from './utils'

interface RunsTabProps {
  runs: RunsResponse | undefined
  runsLoading: boolean
  selectedRunDate: string | null
  setSelectedRunDate: (date: string | null) => void
  selectedRun: RunReport | null | undefined
  selectedRunLoading: boolean
}

export function RunsTab({
  runs,
  runsLoading,
  selectedRunDate,
  setSelectedRunDate,
  selectedRun,
  selectedRunLoading,
}: RunsTabProps) {
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      {/* Runs List */}
      <Card className="lg:col-span-1">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">Run History</CardTitle>
        </CardHeader>
        <CardContent>
          {runsLoading ? (
            <div className="space-y-2">
              {[...Array(10)].map((_, i) => (
                <div key={i} className="h-10 bg-gray-200 rounded animate-pulse"></div>
              ))}
            </div>
          ) : (
            <div className="space-y-1 max-h-[500px] overflow-y-auto">
              {runs?.dates?.slice().reverse().map((date) => (
                <button
                  key={date}
                  onClick={() => setSelectedRunDate(date)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                    selectedRunDate === date
                      ? 'bg-blue-100 text-blue-700'
                      : 'hover:bg-gray-100 text-gray-700'
                  }`}
                >
                  {date}
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Selected Run Details */}
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle className="text-lg font-semibold">
            {selectedRunDate ? `Run: ${selectedRunDate}` : 'Select a run'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!selectedRunDate ? (
            <div className="text-center py-12 text-gray-500">
              Select a run from the list to view details
            </div>
          ) : selectedRunLoading ? (
            <div className="space-y-4">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="h-6 bg-gray-200 rounded animate-pulse"></div>
              ))}
            </div>
          ) : selectedRun ? (
            <div className="space-y-4">
              <div className="flex items-center space-x-4">
                <StatusBadge success={selectedRun.success} />
                <span className="text-sm text-gray-500">
                  {formatDate(selectedRun.run_at)}
                </span>
                <Badge variant="outline" className="text-xs">
                  {selectedRun.git_commit}
                </Badge>
              </div>

              <div className="grid gap-4 md:grid-cols-2 mt-4">
                <div className="p-4 bg-gray-50 rounded-lg">
                  <h4 className="font-medium text-gray-700 mb-2">Station Data</h4>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600">Stations</span>
                      <span>{selectedRun.details?.station_data?.n_stations}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600">Observations</span>
                      <span>{selectedRun.details?.station_data?.n_obs}</span>
                    </div>
                  </div>
                </div>

                <div className="p-4 bg-gray-50 rounded-lg">
                  <h4 className="font-medium text-gray-700 mb-2">Feature Partitions</h4>
                  <div className="space-y-1 text-sm">
                    {['met', 'aod', 'tropomi'].map((feature) => {
                      const data = selectedRun.details?.feature_partitions?.[feature as keyof typeof selectedRun.details.feature_partitions]
                      return (
                        <div key={feature} className="flex justify-between">
                          <span className="text-gray-600 uppercase">{feature}</span>
                          <Badge variant="outline" className={`text-xs ${
                            data?.status === 'exists' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                          }`}>
                            {data?.status ?? 'N/A'}
                          </Badge>
                        </div>
                      )
                    })}
                  </div>
                </div>

                <div className="p-4 bg-gray-50 rounded-lg">
                  <h4 className="font-medium text-gray-700 mb-2">Master Partition</h4>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600">Rows</span>
                      <span>{selectedRun.details?.master_partition?.master_rows?.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600">Features</span>
                      <span>{selectedRun.details?.master_partition?.n_features}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600">Missing Rate</span>
                      <span>{((selectedRun.details?.master_partition?.total_missing_rate ?? 0) * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                </div>

                <div className="p-4 bg-gray-50 rounded-lg">
                  <h4 className="font-medium text-gray-700 mb-2">Inference</h4>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600">Status</span>
                      <span>{String(selectedRun.details?.inference?.status)}</span>
                    </div>
                    {selectedRun.details?.inference?.error && (
                      <div className="text-red-600 text-xs mt-2">
                        {selectedRun.details.inference.error}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-gray-200">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Runtime</span>
                  <span className="font-medium">{formatDuration(selectedRun.details?.runtime_seconds ?? 0)}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-12 text-gray-500">
              Failed to load run details
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
