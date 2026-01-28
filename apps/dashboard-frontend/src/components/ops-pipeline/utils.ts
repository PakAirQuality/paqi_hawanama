// Utility functions for Ops Pipeline

import type { Execution } from './types'

export function getExecutionStatus(execution: Execution): 'running' | 'succeeded' | 'failed' {
  const completedCondition = execution.conditions?.find(c => c.type === 'Completed')
  if (!completedCondition || completedCondition.state === 'CONDITION_PENDING') {
    return 'running'
  }
  if (completedCondition.state === 'CONDITION_SUCCEEDED') {
    return 'succeeded'
  }
  return 'failed'
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}m ${secs}s`
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// Turbo colormap functions
export function turboRGB(t: number): [number, number, number] {
  t = Math.max(0, Math.min(1, t))
  const r = Math.round(34.61 + t * (1172.33 - t * (10793.56 - t * (33300.12 - t * (38394.49 - t * 14825.05)))))
  const g = Math.round(23.31 + t * (557.33 + t * (1225.33 - t * (3574.96 - t * (1073.77 + t * 707.56)))))
  const b = Math.round(27.2 + t * (3211.1 - t * (15327.97 - t * (27814 - t * (22569.18 - t * 6838.66)))))
  return [
    Math.max(0, Math.min(255, r)),
    Math.max(0, Math.min(255, g)),
    Math.max(0, Math.min(255, b)),
  ]
}

export function turboToRGBA(t: number): [number, number, number, number] {
  const [r, g, b] = turboRGB(t)
  return [r, g, b, 255]
}

// Fixed colorscale range
export const VMIN = 20
export const VMAX = 180

// Turbo colormap gradient (matches backend tile rendering)
export const TURBO_GRADIENT = 'linear-gradient(to right, #30123b, #4662d7, #36aaf9, #1be5b5, #afea3b, #fbc424, #e45a31, #7a0403)'
