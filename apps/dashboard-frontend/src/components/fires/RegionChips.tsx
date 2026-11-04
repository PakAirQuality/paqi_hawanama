'use client'

import { Pill, PillGroup } from './Pill'
import { REGION_PRESETS, isPreset } from './regions'

interface Props {
  value: string
  onChange: (region: string) => void
  districts?: { name: string; province: string }[]
}

export function RegionChips({ value, onChange, districts }: Props) {
  const main = REGION_PRESETS.filter(p => p.group === 'main')
  const provinces = REGION_PRESETS.filter(p => p.group === 'province')
  const districtValue = isPreset(value) ? '' : value
  return (
    <div className="flex flex-wrap items-center gap-2">
      <PillGroup label="Region">
        {main.map(p => (
          <Pill key={p.id} active={value === p.id} onClick={() => onChange(p.id)} title={p.label}>
            {p.short ?? p.label}
          </Pill>
        ))}
      </PillGroup>
      <PillGroup label="Pakistan province">
        {provinces.map(p => (
          <Pill key={p.id} active={value === p.id} onClick={() => onChange(p.id)} title={p.label}>
            {p.short ?? p.label}
          </Pill>
        ))}
      </PillGroup>
      {districts && districts.length > 0 && (
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <span className="sr-only">District</span>
          <select
            value={districtValue}
            onChange={e => onChange(e.target.value || 'pakistan')}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${districtValue ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-200 bg-white text-slate-700'}`}
            aria-label="District"
          >
            <option value="">District…</option>
            {districts.map(d => (
              <option key={d.name} value={d.name}>{d.name} ({d.province})</option>
            ))}
          </select>
        </label>
      )}
    </div>
  )
}
