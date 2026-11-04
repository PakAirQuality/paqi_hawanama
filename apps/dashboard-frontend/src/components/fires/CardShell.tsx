'use client'

import type { ReactNode } from 'react'
import { ApiError } from './api'

interface Props {
  title?: string
  subtitle?: string
  id?: string
  isLoading?: boolean
  error?: unknown
  onRetry?: () => void
  skeletonHeight?: number
  children: ReactNode
  aside?: ReactNode
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return 'Too many requests, wait a minute and retry.'
    return error.message
  }
  return error instanceof Error ? error.message : 'Something went wrong.'
}

export function CardShell({ title, subtitle, id, isLoading, error, onRetry, skeletonHeight = 160, children, aside }: Props) {
  return (
    <section id={id} aria-labelledby={title && id ? `${id}-title` : undefined}
      className="rounded-2xl border border-slate-200/70 bg-white p-4 sm:p-5">
      {(title || aside) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h2 id={id ? `${id}-title` : undefined} className="text-[15px] font-semibold tracking-tight text-slate-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[12px] text-slate-500">{subtitle}</p>}
          </div>
          {aside}
        </div>
      )}
      {isLoading ? (
        <div className="skeleton rounded-lg" style={{ height: skeletonHeight }} aria-busy="true" aria-label="Loading" />
      ) : error ? (
        <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-[13px] text-slate-600">
          <span>{errorText(error)}</span>
          {onRetry && (
            <button onClick={onRetry} className="rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white">Retry</button>
          )}
        </div>
      ) : children}
    </section>
  )
}
