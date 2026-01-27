"use client"

import { Badge } from '@/components/ui/badge'
import { CheckCircle2, XCircle, Loader2, AlertTriangle } from 'lucide-react'

export function StatusBadge({ success }: { success: boolean }) {
  return (
    <Badge className={`text-xs ${
      success
        ? 'bg-green-100 text-green-700 border-green-200'
        : 'bg-red-100 text-red-700 border-red-200'
    }`}>
      {success ? (
        <><CheckCircle2 className="w-3 h-3 mr-1" /> Success</>
      ) : (
        <><XCircle className="w-3 h-3 mr-1" /> Failed</>
      )}
    </Badge>
  )
}

export function ExecutionStatusBadge({ status }: { status: 'running' | 'succeeded' | 'failed' }) {
  const config = {
    running: { bg: 'bg-blue-100 text-blue-700 border-blue-200', icon: Loader2, text: 'Running' },
    succeeded: { bg: 'bg-green-100 text-green-700 border-green-200', icon: CheckCircle2, text: 'Succeeded' },
    failed: { bg: 'bg-red-100 text-red-700 border-red-200', icon: XCircle, text: 'Failed' }
  }
  const { bg, icon: Icon, text } = config[status]
  return (
    <Badge className={`text-xs ${bg}`}>
      <Icon className={`w-3 h-3 mr-1 ${status === 'running' ? 'animate-spin' : ''}`} />
      {text}
    </Badge>
  )
}

export function HealthAlert({ message }: { message: string }) {
  return (
    <div className="flex items-center space-x-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
      <AlertTriangle className="w-4 h-4 text-amber-600" />
      <span className="text-sm text-amber-800">{message}</span>
    </div>
  )
}
