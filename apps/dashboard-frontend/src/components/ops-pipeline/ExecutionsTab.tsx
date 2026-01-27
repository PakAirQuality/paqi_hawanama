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
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Daily Executions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg font-semibold flex items-center space-x-2">
            <Play className="w-5 h-5" />
            <span>Daily Pipeline Executions</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {dailyExecsLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-16 bg-gray-200 rounded animate-pulse"></div>
              ))}
            </div>
          ) : dailyExecs?.executions?.length ? (
            <div className="space-y-3">
              {dailyExecs.executions.map((exec) => {
                const status = getExecutionStatus(exec)
                return (
                  <div key={exec.uid} className="p-3 bg-gray-50 rounded-lg">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center space-x-2">
                          <ExecutionStatusBadge status={status} />
                          <span className="text-xs text-gray-500 font-mono">
                            {exec.name.split('/').pop()}
                          </span>
                        </div>
                        <div className="text-xs text-gray-600">
                          Started: {formatDate(exec.createTime)}
                          {exec.completionTime && (
                            <> | Completed: {formatDate(exec.completionTime)}</>
                          )}
                        </div>
                      </div>
                      {exec.logUri && (
                        <a
                          href={exec.logUri}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800"
                        >
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No executions found
            </div>
          )}
        </CardContent>
      </Card>

      {/* Retrain Executions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg font-semibold flex items-center space-x-2">
            <RefreshCw className="w-5 h-5" />
            <span>Model Retrain Executions</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {retrainExecs?.executions?.length ? (
            <div className="space-y-3">
              {retrainExecs.executions.map((exec) => {
                const status = getExecutionStatus(exec)
                return (
                  <div key={exec.uid} className="p-3 bg-gray-50 rounded-lg">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center space-x-2">
                          <ExecutionStatusBadge status={status} />
                          <span className="text-xs text-gray-500 font-mono">
                            {exec.name.split('/').pop()}
                          </span>
                        </div>
                        <div className="text-xs text-gray-600">
                          Started: {formatDate(exec.createTime)}
                          {exec.completionTime && (
                            <> | Completed: {formatDate(exec.completionTime)}</>
                          )}
                        </div>
                      </div>
                      {exec.logUri && (
                        <a
                          href={exec.logUri}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:text-blue-800"
                        >
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No retrain executions found
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
