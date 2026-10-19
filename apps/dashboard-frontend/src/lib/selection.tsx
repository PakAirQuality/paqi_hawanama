'use client'

/**
 * The shared selection: what the map, cards, charts, downloads and the assistant are all
 * describing. One object, one provider; components read it instead of keeping their own
 * copies, and every request that the API can scope (model, date) is keyed by it.
 */

import { createContext, useCallback, useContext, useMemo, useState } from 'react'

export type ModelKey = 'backbone' | 'support_aware'

export const MODEL_LABELS: Record<ModelKey, string> = {
  backbone: 'Satellite backbone',
  support_aware: 'Enhanced (support-aware)',
}

export const MODEL_HELP: Record<ModelKey, string> = {
  backbone: 'Daily 1 km PM2.5 estimated from satellite aerosol, weather and land features; independent of ground stations.',
  support_aware: 'Same model, nudged toward nearby ground observations where they exist; closer to stations, less independent of them.',
}

export interface SelectionLocation {
  type: 'national' | 'city' | 'station'
  id?: string
  name?: string
}

export interface Selection {
  /** Pakistan calendar day (YYYY-MM-DD) the view describes */
  date: string | null
  tz: 'Asia/Karachi'
  model: ModelKey
  pollutant: 'pm25'
  units: 'µg/m³'
  location: SelectionLocation
  layers: { fires: boolean; kilns: boolean; industry: boolean; population: boolean }
  /** true when `date` is the newest available day (live-ish), false for historical browsing */
  isLatest: boolean
}

export interface SelectionApi extends Selection {
  setDate: (d: string | null, isLatest?: boolean) => void
  setModel: (m: ModelKey) => void
  setLocation: (l: SelectionLocation) => void
  setLayer: (k: keyof Selection['layers'], on: boolean) => void
  /** Payload sent to the copilot so its answer matches the view. */
  toContext: () => {
    model: ModelKey
    pollutant: string
    units: string
    tz: string
    location: { type: string; id: string; name: string }
    layers: string[]
  }
  /** One-line human description: "Lahore · PM2.5 µg/m³ · 17 Oct 2026 PKT · Enhanced model" */
  describe: () => string
}

const DEFAULT: Selection = {
  date: null,
  tz: 'Asia/Karachi',
  model: 'backbone',
  pollutant: 'pm25',
  units: 'µg/m³',
  location: { type: 'national', name: 'Pakistan' },
  layers: { fires: false, kilns: true, industry: true, population: false },
  isLatest: true,
}

const SelectionContext = createContext<SelectionApi | null>(null)

export function SelectionProvider({ children, initial }: { children: React.ReactNode; initial?: Partial<Selection> }) {
  const [state, setState] = useState<Selection>({ ...DEFAULT, ...initial })

  const setDate = useCallback((date: string | null, isLatest = false) => setState((s) => ({ ...s, date, isLatest })), [])
  const setModel = useCallback((model: ModelKey) => setState((s) => ({ ...s, model })), [])
  const setLocation = useCallback((location: SelectionLocation) => setState((s) => ({ ...s, location })), [])
  const setLayer = useCallback(
    (k: keyof Selection['layers'], on: boolean) => setState((s) => ({ ...s, layers: { ...s.layers, [k]: on } })),
    [],
  )

  const api = useMemo<SelectionApi>(() => {
    const toContext = () => ({
      model: state.model,
      pollutant: state.pollutant,
      units: state.units,
      tz: state.tz,
      location: { type: state.location.type, id: state.location.id ?? '', name: state.location.name ?? '' },
      layers: (Object.keys(state.layers) as Array<keyof Selection['layers']>).filter((k) => state.layers[k]),
    })
    const describe = () => {
      const where = state.location.name || 'Pakistan'
      const when = state.date ? `${formatShort(state.date)} PKT` : 'latest'
      const model = state.model === 'support_aware' ? 'Enhanced model' : 'Satellite model'
      return `${where} · PM2.5 ${state.units} · ${when} · ${model}`
    }
    return { ...state, setDate, setModel, setLocation, setLayer, toContext, describe }
  }, [state, setDate, setModel, setLocation, setLayer])

  return <SelectionContext.Provider value={api}>{children}</SelectionContext.Provider>
}

function formatShort(dateStr: string): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  return new Date(y, m - 1, d, 12).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function useSelection(): SelectionApi {
  const ctx = useContext(SelectionContext)
  if (!ctx) throw new Error('useSelection must be used inside <SelectionProvider>')
  return ctx
}

/** Same as useSelection but tolerant of being rendered outside the provider (returns null). */
export function useOptionalSelection(): SelectionApi | null {
  return useContext(SelectionContext)
}
