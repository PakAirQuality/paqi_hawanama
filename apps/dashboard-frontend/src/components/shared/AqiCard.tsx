'use client'

import { Droplets, Navigation, Thermometer } from 'lucide-react'
import { classifyPm25, pm25ToAqi, type BandKey } from '@/lib/aqi'
import { AnimatedNumber } from './AnimatedNumber'

interface Weather {
  tempC?: number | null
  windKmh?: number | null
  humidity?: number | null
}

interface AqiCardProps {
  pm25: number
  /** station / place name shown above the card body */
  title?: string
  subtitle?: string
  /** what the PM2.5 value represents, e.g. "Daily mean" */
  caption?: string
  weather?: Weather
  className?: string
}

const GAUGE_ORDER: BandKey[] = ['good', 'moderate', 'unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous']

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180
  return [cx + r * Math.cos(a), cy - r * Math.sin(a)]
}

/** Six-segment dial: the current band is solid, the others are faint, and the needle points into the current band. */
function GaugeIcon({ band, aqi, color }: { band: BandKey; aqi: number | null; color: string }) {
  const idx = Math.max(0, GAUGE_ORDER.indexOf(band))
  const cx = 32, cy = 36, r = 24
  const seg = 180 / GAUGE_ORDER.length
  const gap = 3
  const bandMin = [0, 51, 101, 151, 201, 301][idx]
  const bandMax = [50, 100, 150, 200, 300, 500][idx]
  const within = aqi == null ? 0.5 : Math.min(1, Math.max(0, (aqi - bandMin) / (bandMax - bandMin)))
  const needleDeg = 180 - (idx + 0.15 + within * 0.7) * seg
  const [nx, ny] = polar(cx, cy, r - 7, needleDeg)

  return (
    <svg viewBox="0 0 64 44" width="64" height="44" fill="none" aria-hidden>
      {GAUGE_ORDER.map((k, i) => {
        const a0 = 180 - i * seg - gap / 2
        const a1 = 180 - (i + 1) * seg + gap / 2
        const [x0, y0] = polar(cx, cy, r, a0)
        const [x1, y1] = polar(cx, cy, r, a1)
        return (
          <path
            key={k}
            d={`M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`}
            stroke={color}
            strokeWidth={i === idx ? 6 : 4}
            strokeOpacity={i === idx ? 1 : 0.3}
            strokeLinecap="round"
          />
        )
      })}
      <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx={cx} cy={cy} r="3.5" fill={color} />
    </svg>
  )
}

/** Large AQI card: coloured by band, US AQI tile, category, main pollutant and an optional weather row. */
export function AqiCard({ pm25, title, subtitle, caption = 'Main pollutant: PM2.5', weather, className = '' }: AqiCardProps) {
  const band = classifyPm25(pm25)
  const aqi = pm25ToAqi(pm25)
  const fg = band.textColor
  const hasWeather = weather && (weather.tempC != null || weather.windKmh != null || weather.humidity != null)

  return (
    <div className={`overflow-hidden rounded-2xl shadow-lg ${className}`} style={{ background: band.color, color: fg }}>
      {(title || subtitle) && (
        <div className="px-4 pt-3">
          {title && <div className="text-sm font-semibold leading-tight">{title}</div>}
          {subtitle && <div className="text-xs opacity-80">{subtitle}</div>}
        </div>
      )}
      <div className="flex items-center gap-4 px-4 pt-3 pb-3">
        <div
          className="shrink-0 rounded-xl px-3 py-2 text-center"
          style={{ background: fg === '#ffffff' ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.62)' }}
        >
          <div className="text-3xl font-semibold leading-none tabular-nums">{aqi != null ? <AnimatedNumber value={aqi} /> : '–'}</div>
          <div className="mt-1 text-xs font-medium">US AQI</div>
        </div>
        <div className="min-w-0 flex-1 text-lg font-medium leading-tight">{band.label}</div>
        <GaugeIcon band={band.key} aqi={aqi} color="#ffffff" />
      </div>
      <div className="flex items-baseline justify-between gap-3 px-4 py-3 text-sm">
        <span>{caption}</span>
        <span className="font-semibold tabular-nums"><AnimatedNumber value={Math.round(pm25)} /> µg/m³</span>
      </div>
      {hasWeather && (
        <div className="flex items-center justify-between bg-white px-4 py-2.5 text-sm text-slate-900 tabular-nums">
          {weather!.tempC != null && (
            <span className="inline-flex items-center gap-1.5"><Thermometer size={16} className="text-slate-500" aria-hidden />{Math.round(weather!.tempC)}°</span>
          )}
          {weather!.windKmh != null && (
            <span className="inline-flex items-center gap-1.5"><Navigation size={16} className="text-slate-500" aria-hidden />{Math.round(weather!.windKmh)} km/h</span>
          )}
          {weather!.humidity != null && (
            <span className="inline-flex items-center gap-1.5"><Droplets size={16} className="text-sky-500" aria-hidden />{Math.round(weather!.humidity)} %</span>
          )}
        </div>
      )}
    </div>
  )
}
