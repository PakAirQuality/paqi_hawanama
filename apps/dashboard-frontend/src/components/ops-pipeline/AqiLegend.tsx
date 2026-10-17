'use client'

import { AQI_BANDS, BAND_SCALE_LABEL, UNKNOWN_BAND } from '@/lib/aqi'
import { MODEL_LABELS, type ModelKey } from '@/lib/selection'

/** Always-visible legend for the PM2.5 categories plus the no-data treatment. */
export function AqiLegend({ model, compact = false }: { model?: ModelKey; compact?: boolean }) {
  return (
    <div className="rounded-lg bg-white/92 backdrop-blur-sm shadow-md border border-slate-200 px-2.5 py-2 text-[10px] text-slate-600" aria-label="PM2.5 legend">
      <div className="font-semibold text-slate-700 mb-1">PM2.5 µg/m³ {model ? `· ${MODEL_LABELS[model]}` : ''}</div>
      <div className={`flex ${compact ? 'flex-wrap gap-x-2 gap-y-0.5' : 'flex-col gap-0.5'}`}>
        {AQI_BANDS.map((b, i) => (
          <div key={b.key} className="flex items-center gap-1.5" title={b.label}>
            <span className="inline-block w-3 h-3 rounded-sm" style={{ background: b.color }} />
            <span>{b.pm25Max == null ? `> ${AQI_BANDS[i - 1].pm25Max}` : `${i === 0 ? 0 : AQI_BANDS[i - 1].pm25Max}–${b.pm25Max}`} {compact ? b.shortLabel : b.label}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5" title="No reading or outside model coverage">
          <span className="inline-block w-3 h-3 rounded-sm border border-slate-300" style={{ background: UNKNOWN_BAND.color, opacity: 0.5 }} />
          <span>No data</span>
        </div>
      </div>
      <div className="mt-1 text-[9px] text-slate-400">{BAND_SCALE_LABEL}</div>
    </div>
  )
}
