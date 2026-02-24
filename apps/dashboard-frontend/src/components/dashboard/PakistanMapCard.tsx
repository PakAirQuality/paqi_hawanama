'use client'

import React, { useMemo, useState, useEffect } from 'react'
import { geoMercator, geoPath } from 'd3-geo'

const CARD_WIDTH = 600
const CARD_HEIGHT = 280

// Mock station data for demonstration
const mockStations = [
  { id: 1, lat: 31.5804, lng: 74.3587, status: 'healthy' }, // Lahore
  { id: 2, lat: 24.8607, lng: 67.0011, status: 'failed' },  // Karachi
  { id: 3, lat: 33.7294, lng: 73.0931, status: 'noisy' },   // Islamabad
  { id: 4, lat: 30.1575, lng: 71.5249, status: 'healthy' }, // Multan
  { id: 5, lat: 31.1704, lng: 72.7097, status: 'noisy' },   // Faisalabad
  { id: 6, lat: 25.3960, lng: 68.3578, status: 'failed' },  // Hyderabad
  { id: 7, lat: 32.0836, lng: 72.6711, status: 'healthy' }, // Sargodha
  { id: 8, lat: 34.0151, lng: 71.5249, status: 'noisy' },   // Peshawar
]

const statusColor: Record<string, string> = {
  healthy: '#16A34A', // green-600
  noisy: '#EAB308',   // yellow-500
  failed: '#DC2626',  // red-600
}

interface PakistanMapCardProps {
  networkPm25: number
  bandLabel: string
  worstCity: string
  worstValue: number
  bestCity: string
  bestValue: number
  aboveGuidelinePct: number
}

export const RegionalMapCard: React.FC<PakistanMapCardProps> = ({
  networkPm25,
  bandLabel,
  worstCity,
  worstValue,
  bestCity,
  bestValue,
  aboveGuidelinePct,
}) => {
  const [pakistanGeo, setPakistanGeo] = useState<any>(null)

  useEffect(() => {
    // Load Pakistan boundary data
    fetch('/pakistan_country.geojson')
      .then(res => res.json())
      .then(data => {
        console.log('Loaded Pakistan boundary data:', data)
        setPakistanGeo(data)
      })
      .catch(err => console.error('Failed to load Pakistan boundary:', err))
  }, [])

  const { projection, pathGenerator } = useMemo(() => {
    if (!pakistanGeo) return { projection: null, pathGenerator: null }

    // Fit the entire FeatureCollection, not just the first feature
    const geoObject =
      pakistanGeo.type === 'FeatureCollection'
        ? pakistanGeo
        : { type: 'FeatureCollection', features: [pakistanGeo] }

    const proj = geoMercator().fitSize([CARD_WIDTH, CARD_HEIGHT], geoObject)
    const path = geoPath().projection(proj)
    const bounds = path.bounds(geoObject)
    console.log('Calculated bounds:', bounds)
    console.log('Projection params:', { scale: proj.scale(), translate: proj.translate() })

    return { projection: proj, pathGenerator: path }
  }, [pakistanGeo])

  return (
    <div className="flex rounded-2xl bg-white border border-slate-200 shadow-sm p-6 gap-6">
      {/* Left side: text */}
      <div className="flex-1 flex flex-col justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">
            Air Quality Across South Asia
          </h3>

          <div className="mt-3 inline-flex items-center rounded-full bg-red-100 px-3 py-1 text-[11px] font-semibold text-red-700 uppercase tracking-wide">
            {bandLabel}
          </div>

          <div className="mt-4 text-4xl md:text-5xl font-bold text-slate-900">
            {networkPm25.toFixed(1)}{' '}
            <span className="text-2xl align-super text-slate-700">µg/m³</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Network PM₂.₅ (1 h)
          </p>
        </div>

        <div className="mt-4 space-y-1 text-xs text-slate-700">
          <p>
            Worst city:{' '}
            <span className="font-semibold">{worstCity}</span>{' '}
            {worstValue.toFixed(0)} µg/m³
          </p>
          <p>
            Cleanest:{' '}
            <span className="font-semibold">{bestCity}</span>{' '}
            {bestValue.toFixed(0)} µg/m³
          </p>
          <p className="text-slate-500">
            Above WHO 24h guideline: {aboveGuidelinePct.toFixed(0)}% of stations
          </p>
        </div>
      </div>

      {/* Right side: SVG map */}
      <div className="w-[260px] h-[240px] flex flex-col items-center">
        {pakistanGeo && pathGenerator && projection ? (
          <svg
            width={CARD_WIDTH}
            height={CARD_HEIGHT}
            viewBox={`0 0 ${CARD_WIDTH} ${CARD_HEIGHT}`}
            className="w-full h-full"
          >
            {/* Pakistan outline */}
            {pakistanGeo.features?.map((feature: any, index: number) => {
              const pathString = pathGenerator(feature)
              console.log(`Feature ${index} path:`, pathString?.substring(0, 100) + '...')
              
              if (!pathString) {
                console.log(`Skipping null path ${index}`)
                return null
              }
              
              return (
                <path
                  key={index}
                  d={pathString}
                  fill="#F9FAFB"         // light gray background
                  stroke="#CBD5E1"       // slate-300 border
                  strokeWidth={1}
                />
              )
            })}

            {/* Stations */}
            {mockStations.map((station) => {
              const projected = projection([station.lng, station.lat])
              if (!projected) return null
              const [x, y] = projected
              
              return (
                <circle
                  key={station.id}
                  cx={x}
                  cy={y}
                  r={4}
                  fill={statusColor[station.status]}
                  stroke="#FFFFFF"
                  strokeWidth={1}
                  opacity={0.9}
                />
              )
            })}
          </svg>
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-gray-50 rounded">
            <span className="text-gray-400 text-sm">Loading map...</span>
          </div>
        )}

        {/* Legend */}
        <div className="mt-3 flex gap-4 text-[11px] text-slate-600">
          <LegendDot color={statusColor.healthy} label="Healthy" />
          <LegendDot color={statusColor.noisy} label="Noisy" />
          <LegendDot color={statusColor.failed} label="Failed" />
        </div>
      </div>
    </div>
  )
}

const LegendDot: React.FC<{ color: string; label: string }> = ({ color, label }) => (
  <div className="flex items-center gap-1">
    <span
      className="inline-block h-2 w-2 rounded-full"
      style={{ backgroundColor: color }}
    />
    <span>{label}</span>
  </div>
)
