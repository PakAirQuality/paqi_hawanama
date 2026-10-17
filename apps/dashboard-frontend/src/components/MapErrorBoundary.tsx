'use client'

import React from 'react'
import { MAP_UNAVAILABLE_TEXT, type MapUnavailableReason } from '@/lib/webgl'

interface Props {
  children: React.ReactNode
  /** Rendered instead of the map when it fails; receives a retry callback. */
  fallback: (ctx: { reason: MapUnavailableReason; message: string; retry: () => void }) => React.ReactNode
  /** Set by the map component itself for failures that are not React render errors. */
  unavailable?: MapUnavailableReason | null
  onRetry?: () => void
}

interface State { error: Error | null }

/**
 * Keeps a map failure inside the map area: header, navigation, panels and reports stay
 * usable, the user sees why the map is missing and can retry just the map.
 */
export class MapErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.warn('[map] render error contained by MapErrorBoundary:', error.message, info.componentStack)
  }

  retry = () => {
    this.setState({ error: null })
    this.props.onRetry?.()
  }

  render() {
    const reason: MapUnavailableReason | null = this.state.error ? 'runtime-error' : (this.props.unavailable ?? null)
    if (reason) {
      const message = this.state.error?.message?.includes('WebGL') ? MAP_UNAVAILABLE_TEXT['no-webgl'] : MAP_UNAVAILABLE_TEXT[reason]
      return <>{this.props.fallback({ reason, message, retry: this.retry })}</>
    }
    return this.props.children
  }
}

export function MapUnavailableNotice({ message, retry, children }: { message: string; retry: () => void; children?: React.ReactNode }) {
  return (
    <div className="flex-1 min-h-0 flex flex-col bg-slate-50">
      <div className="m-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 flex flex-wrap items-center gap-3">
        <span className="font-medium">Interactive map unavailable.</span>
        <span className="text-amber-800">{message}</span>
        <button type="button" onClick={retry} className="ml-auto rounded-lg border border-amber-300 bg-white px-3 py-1 text-xs font-medium hover:bg-amber-100">
          Retry map
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden px-4 pb-4">{children}</div>
    </div>
  )
}
