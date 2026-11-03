'use client'

import { Flame, Wind, MapPin, Satellite, Users } from 'lucide-react'

/** One emission source on the map: kilns or an industry category */
export interface SourceLayer {
  key: string
  label: string
  color: string
  on: boolean
}

interface LayersPanelProps {
  showStations: boolean
  onToggleStations: () => void
  showSatellite: boolean
  onToggleSatellite: () => void
  showFires: boolean
  onToggleFires: () => void
  showWind: boolean
  onToggleWind: () => void
  showPopulation: boolean
  onTogglePopulation: () => void
  sources: SourceLayer[]
  onToggleSource: (key: string) => void
}

const LAYER_ITEMS: {
  key: keyof Pick<LayersPanelProps, 'showStations' | 'showSatellite' | 'showFires' | 'showWind' | 'showPopulation'>
  label: string
  description: string
  icon: typeof Flame
  activeColor: string
}[] = [
  { key: 'showStations', label: 'Stations', description: 'Air quality monitoring stations', icon: MapPin, activeColor: 'text-amber-600' },
  { key: 'showSatellite', label: 'PM2.5 Estimation', description: 'ML model prediction heatmap', icon: Satellite, activeColor: 'text-indigo-600' },
  { key: 'showFires', label: 'Active Fires', description: 'FIRMS VIIRS fire detections', icon: Flame, activeColor: 'text-orange-500' },
  { key: 'showWind', label: 'Wind Field', description: 'Latest surface wind speed & direction', icon: Wind, activeColor: 'text-sky-500' },
  { key: 'showPopulation', label: 'Population', description: 'WorldPop 2025 constrained 100m', icon: Users, activeColor: 'text-purple-500' },
]

function Toggle({ on }: { on: boolean }) {
  return (
    <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${on ? 'bg-slate-700 justify-end' : 'bg-slate-200 justify-start'}`}>
      <div className={`w-3 h-3 rounded-full mx-0.5 transition-colors ${on ? 'bg-white' : 'bg-slate-400'}`} />
    </div>
  )
}

const rowClass = (on: boolean) =>
  `w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${on ? 'bg-slate-50 hover:bg-slate-100' : 'bg-white hover:bg-slate-50 opacity-50'}`

export function LayersPanel({
  showStations, onToggleStations,
  showSatellite, onToggleSatellite,
  showFires, onToggleFires,
  showWind, onToggleWind,
  showPopulation, onTogglePopulation,
  sources, onToggleSource,
}: LayersPanelProps) {
  const toggles: Record<string, { value: boolean; toggle: () => void }> = {
    showStations: { value: showStations, toggle: onToggleStations },
    showSatellite: { value: showSatellite, toggle: onToggleSatellite },
    showFires: { value: showFires, toggle: onToggleFires },
    showWind: { value: showWind, toggle: onToggleWind },
    showPopulation: { value: showPopulation, toggle: onTogglePopulation },
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-slate-100">
        <h3 className="text-xs font-semibold text-slate-800 tracking-wide">
          Map Layers
        </h3>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-1">
        {LAYER_ITEMS.map((item) => {
          const { value, toggle } = toggles[item.key]
          const Icon = item.icon
          return (
            <button key={item.key} onClick={toggle} aria-pressed={value} className={rowClass(value)}>
              <div className={`shrink-0 ${value ? item.activeColor : 'text-slate-300'}`}>
                <Icon size={16} />
              </div>
              <div className="min-w-0 flex-1">
                <div className={`text-xs font-medium ${value ? 'text-slate-700' : 'text-slate-500'}`}>
                  {item.label}
                </div>
                <div className="text-[11px] text-slate-500 truncate">
                  {item.description}
                </div>
              </div>
              <Toggle on={value} />
            </button>
          )
        })}

        <h4 className="px-3 pb-1 pt-4 text-[11px] font-semibold text-slate-600">Emission sources</h4>
        {sources.map((source) => (
          <button key={source.key} onClick={() => onToggleSource(source.key)} aria-pressed={source.on} className={rowClass(source.on)}>
            <span className="flex w-4 shrink-0 justify-center" aria-hidden>
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: source.on ? source.color : '#cbd5e1' }} />
            </span>
            <span className={`min-w-0 flex-1 truncate text-xs font-medium ${source.on ? 'text-slate-700' : 'text-slate-500'}`}>
              {source.label}
            </span>
            <Toggle on={source.on} />
          </button>
        ))}
      </div>
    </div>
  )
}
