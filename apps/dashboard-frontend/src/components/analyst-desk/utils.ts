// Utilities for the Analyst Desk

// ── Health band colours and labels: derived from the one classification in lib/aqi ──
// Keys are the canonical US EPA 2024 categories; legacy keys ("severe") are kept as
// aliases so older stored forecasts still render.

import { AQI_BANDS, UNKNOWN_BAND } from '@/lib/aqi'

function withAliases<T>(pick: (b: typeof AQI_BANDS[number]) => T): Record<string, T> {
  const out: Record<string, T> = {}
  for (const b of AQI_BANDS) out[b.key] = pick(b)
  out.severe = out.hazardous
  out.usg = out.unhealthy_sensitive
  out.unknown = pick(UNKNOWN_BAND as typeof AQI_BANDS[number])
  return out
}

export const BAND_COLORS: Record<string, string> = withAliases(b => b.color)
export const BAND_BG_COLORS: Record<string, string> = withAliases(b => b.badge)
export const BAND_LABELS: Record<string, string> = withAliases(b => b.label)

// ── Priority colors ─────────────────────────────────────────────────────

export const PRIORITY_STYLES: Record<string, string> = {
  monitor:  'bg-green-50 text-green-700 border-green-200',
  review:   'bg-amber-50 text-amber-700 border-amber-200',
  escalate: 'bg-red-50 text-red-700 border-red-200',
}

// ── Confidence colors ───────────────────────────────────────────────────

export const CONFIDENCE_STYLES: Record<string, string> = {
  high:   'bg-emerald-100 text-emerald-800',
  medium: 'bg-slate-100 text-slate-700',
  low:    'bg-orange-100 text-orange-800',
}

// ── Trend helpers ───────────────────────────────────────────────────────

export const TREND_ICONS: Record<string, string> = {
  worsening:         '\u2191',  // ↑
  stable:            '\u2192',  // →
  improving:         '\u2193',  // ↓
  insufficient_data: '\u2014',  // —
}

export const TREND_STYLES: Record<string, string> = {
  worsening:         'text-red-600',
  stable:            'text-slate-500',
  improving:         'text-green-600',
  insufficient_data: 'text-slate-400',
}

// ── Episode state labels ────────────────────────────────────────────────

export const EPISODE_LABELS: Record<string, string> = {
  stable:              'Stable',
  rising:              'Rising',
  ramp_likely:         'Ramp Likely',
  severe_ramp_likely:  'Severe Ramp Likely',
}

// ── Watchlist display config ────────────────────────────────────────────

export const WATCHLIST_CONFIG: Record<string, { label: string; icon: string; color: string }> = {
  severe_tomorrow:       { label: 'Severe Tomorrow',       icon: '\u26a0',  color: 'text-red-600' },
  severe_3day:           { label: 'Severe 3-Day',          icon: '\u26a0',  color: 'text-red-500' },
  rapid_deterioration:   { label: 'Rapid Deterioration',   icon: '\u2191',  color: 'text-orange-600' },
  persistent_risk:       { label: 'Persistent Risk',       icon: '\u23f1',  color: 'text-purple-600' },
  low_confidence_alert:  { label: 'Low Confidence',        icon: '?',       color: 'text-amber-600' },
  ramp_watch:            { label: 'Ramp Watch',            icon: '\u26a1',  color: 'text-yellow-600' },
  worsening_outlook:     { label: 'Worsening Outlook',     icon: '\u2197',  color: 'text-orange-500' },
  anomaly_drivers:       { label: 'Anomaly Drivers',       icon: '\ud83d\udd25', color: 'text-red-500' },
}

// ── Formatting helpers ──────────────────────────────────────────────────

export function formatPM25(val: number | null | undefined): string {
  if (val == null) return '—'
  return `${Math.round(val)}`
}

export function formatPercent(val: number | null | undefined): string {
  if (val == null) return '—'
  return `${Math.round(val * 100)}%`
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}
