"use client"

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Play, RefreshCw, ExternalLink } from 'lucide-react'
import type { ExecutionsResponse } from './types'
import { ExecutionStatusBadge } from './StatusBadges'
import { getExecutionStatus, formatDate } from './utils'

interface ExecutionsTabProps {
  dailyExecs: ExecutionsResponse | undefined
  dailyExecsLoading: boolean
  retrainExecs: ExecutionsResponse | undefined
}

export function ExecutionsTab({
  dailyExecs,
  dailyExecsLoading,
  retrainExecs,
}: ExecutionsTabProps) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* Daily Executions */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold flex items-center space-x-2">
            <Play className="w-4 h-4" />
            <span>Daily Pipeline</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {dailyExecsLoading ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-12 bg-gray-100 rounded animate-pulse"></div>
              ))}
            </div>
          ) : dailyExecs?.executions?.length ? (
            <div className="space-y-1.5">
              {dailyExecs.executions.map((exec) => {
                const status = getExecutionStatus(exec)
                return (
                  <div key={exec.uid} className="p-2 bg-gray-50 rounded">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center space-x-2">
                          <ExecutionStatusBadge status={status} />
                          <span className="text-[10px] text-gray-500 font-mono truncate">
                            {exec.name.split('/').pop()}
                          </span>
                        </div>
                        <div className="text-[10px] text-gray-500 mt-0.5">
                          {formatDate(exec.createTime)}
                          {exec.completionTime && (
                            <span className="text-gray-400"> → {formatDate(exec.completionTime)}</span>
                          )}
                        </div>
                      </div>
                      {exec.logUri && (
                        <a
                          href={exec.logUri}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800 shrink-0"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-6 text-gray-500 text-sm">
              No executions found
            </div>
          )}
        </CardContent>
      </Card>

      {/* Retrain Executions */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold flex items-center space-x-2">
            <RefreshCw className="w-4 h-4" />
            <span>Model Retrain</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {retrainExecs?.executions?.length ? (
            <div className="space-y-1.5">
              {retrainExecs.executions.map((exec) => {
                const status = getExecutionStatus(exec)
                return (
                  <div key={exec.uid} className="p-2 bg-gray-50 rounded">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center space-x-2">
                          <ExecutionStatusBadge status={status} />
                          <span className="text-[10px] text-gray-500 font-mono truncate">
                            {exec.name.split('/').pop()}
                          </span>
                        </div>
                        <div className="text-[10px] text-gray-500 mt-0.5">
                          {formatDate(exec.createTime)}
                          {exec.completionTime && (
                            <span className="text-gray-400"> → {formatDate(exec.completionTime)}</span>
                          )}
                        </div>
                      </div>
                      {exec.logUri && (
                        <a
                          href={exec.logUri}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800 shrink-0"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-6 text-gray-500 text-sm">
              No retrain executions found
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
