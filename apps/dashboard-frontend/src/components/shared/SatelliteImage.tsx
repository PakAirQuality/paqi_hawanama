"use client"

import { useState } from 'react'

function MarkerPin({ size = 14, color = '#f18017' }: { size?: number; color?: string }) {
  return (
    <div
      className="rounded-full"
      style={{
        width: size,
        height: size,
        background: color,
        border: `2px solid rgba(255,255,255,0.9)`,
        boxShadow: `0 0 0 3px ${color}40, 0 0 12px ${color}50`,
      }}
    />
  )
}

function AqiBadge({ size = 24, color = '#f18017', value }: { size?: number; color?: string; value: number }) {
  return (
    <div
      className="rounded-full flex items-center justify-center font-semibold text-white"
      style={{
        width: size,
        height: size,
        background: color,
        fontSize: size * 0.42,
        border: `1.5px solid rgba(255,255,255,0.9)`,
        boxShadow: `0 1px 4px rgba(0,0,0,0.35)`,
        lineHeight: 1,
        letterSpacing: '-0.02em',
      }}
    >
      {Math.round(value)}
    </div>
  )
}

function ChimneyPin({ size = 24 }: { size?: number }) {
  return (
    <div style={{ filter: 'drop-shadow(0 1px 3px rgba(0,0,0,0.5))' }}>
      <svg xmlns="http://www.w3.org/2000/svg" width={size} height={Math.round(size * 28 / 24)} viewBox="0 0 24 28">
        <rect x="8" y="6" width="8" height="16" rx="1" fill="#b45309" stroke="#92400e" strokeWidth="0.8"/>
        <rect x="6.5" y="4" width="11" height="3" rx="1" fill="#d97706" stroke="#92400e" strokeWidth="0.6"/>
        <rect x="5" y="22" width="14" height="4" rx="1" fill="#78716c" stroke="#57534e" strokeWidth="0.6"/>
        <circle cx="12" cy="2.5" r="2" fill="#d97706" opacity="0.5"/>
        <circle cx="15" cy="1.5" r="1.5" fill="#d97706" opacity="0.35"/>
        <circle cx="9.5" cy="1" r="1.2" fill="#d97706" opacity="0.25"/>
      </svg>
    </div>
  )
}

function renderMarker(markerType: 'circle' | 'chimney' | 'aqi', size: number, color: string, aqiValue?: number) {
  if (markerType === 'chimney') return <ChimneyPin size={size} />
  if (markerType === 'aqi' && aqiValue != null) return <AqiBadge size={size} color={color} value={aqiValue} />
  return <MarkerPin size={size} color={color} />
}

export function SatelliteImage({ lat, lon, name, markerColor, zoom = 'normal', label = 'Station location', markerType = 'circle', aqiValue }: {
  lat: number
  lon: number
  name: string
  markerColor?: string
  zoom?: 'normal' | 'close'
  label?: string
  markerType?: 'circle' | 'chimney' | 'aqi'
  aqiValue?: number
}) {
  const [showModal, setShowModal] = useState(false)
  const mColor = markerColor || '#f18017'

  const t = zoom === 'close' ? { dx: 0.0008, dy: 0.0006 } : { dx: 0.003, dy: 0.002 }
  const l = zoom === 'close' ? { dx: 0.003, dy: 0.002 } : { dx: 0.008, dy: 0.006 }
  const thumbUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox=${lon - t.dx},${lat - t.dy},${lon + t.dx},${lat + t.dy}&bboxSR=4326&size=370,204&imageSR=4326&format=png&f=image`
  const largeUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox=${lon - l.dx},${lat - l.dy},${lon + l.dx},${lat + l.dy}&bboxSR=4326&size=900,640&imageSR=4326&format=png&f=image`

  return (
    <>
      <div
        className="relative overflow-hidden rounded-xl cursor-zoom-in group"
        onClick={() => setShowModal(true)}
      >
        <img
          src={thumbUrl}
          alt={`Satellite view of ${name}`}
          className="w-full h-auto object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          style={{ minHeight: 120 }}
          loading="eager"
        />
        {/* Top-left label */}
        <div className="absolute top-1.5 left-1.5">
          <span className="text-[10px] font-medium text-white/90 bg-black/40 backdrop-blur-sm px-2 py-0.5 rounded">
            {label}
          </span>
        </div>
        {/* Top-right maximize icon */}
        <div className="absolute top-1.5 right-1.5">
          <span className="flex items-center justify-center w-6 h-6 bg-black/40 backdrop-blur-sm rounded text-white/90 group-hover:bg-black/60 transition-colors">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 3 21 3 21 9" />
              <polyline points="9 21 3 21 3 15" />
              <line x1="21" y1="3" x2="14" y2="10" />
              <line x1="3" y1="21" x2="10" y2="14" />
            </svg>
          </span>
        </div>
        {/* Center marker */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
          {renderMarker(markerType, markerType === 'aqi' ? 24 : markerType === 'chimney' ? 20 : 14, mColor, aqiValue)}
        </div>
        {/* Bottom attribution */}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/50 to-transparent px-3 py-2">
          <div className="text-[9px] text-white/60 font-medium">Esri World Imagery — Click to expand</div>
        </div>
      </div>

      {/* Lightbox modal */}
      {showModal && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/85"
          onClick={() => setShowModal(false)}
        >
          <div
            className="relative max-w-[92vw] max-h-[88vh] rounded-xl overflow-hidden shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-4 py-2.5 bg-gradient-to-b from-black/70 to-transparent">
              <div>
                <div className="text-sm font-semibold text-white">{name}</div>
                <div className="text-[10px] text-white/60">{lat.toFixed(5)}, {lon.toFixed(5)}</div>
              </div>
              <button
                onClick={() => setShowModal(false)}
                className="w-8 h-8 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 transition-colors"
              >
                <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <img
              src={largeUrl}
              alt={`Satellite view of ${name}`}
              className="block max-w-full max-h-[88vh] object-contain"
            />
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none">
              {renderMarker(markerType, markerType === 'aqi' ? 32 : markerType === 'chimney' ? 28 : 18, mColor, aqiValue)}
            </div>
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/50 to-transparent px-4 py-2">
              <div className="text-[10px] text-white/50">Esri World Imagery</div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
