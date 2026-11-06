"use client"

// The interactive trajectory map inside a chat answer: the Tracker's basemap (monochrome, hillshade,
// city labels), fitted to the paths, pan and zoom, hover popups. Mapbox GL needs WebGL, so the
// shell (TrajectoryMiniMap) only mounts this when the browser can draw it and the figure is on
// screen; otherwise it shows the SVG. Wheel scrolling the chat does not zoom the map (cooperative
// gestures); pinch and two-finger drag still do.

import { useEffect, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { TrajectoryDoc } from '@/components/fires/api'
import { useBasemapTuning } from '@/components/ops-pipeline/mapViz'
import { useTrajectoryLayers } from '@/lib/chat/trajectoryLayers'
import { allPoints, boundsOf } from '@/lib/chat/trajectoryMap'
import type { MapErrorEvent, MapUnavailableReason } from '@/lib/webgl'

// the deployed build reads a token restricted to this site's own addresses (.env.production.local)
mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''

const STYLE_URL = 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu'

interface Props {
  doc: TrajectoryDoc
  /** level keys to draw ('1000' | '925' | '850') */
  visible: string[]
  className?: string
  padding?: number
  title: string
  /** Called when the map cannot run here; the shell then falls back to the SVG */
  onUnavailable?: (reason: MapUnavailableReason) => void
}

export function TrajectoryMapGL({ doc, visible, className, padding = 28, title, onUnavailable }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const unavailable = useRef(onUnavailable)
  useEffect(() => { unavailable.current = onUnavailable }, [onUnavailable])
  const [map, setMap] = useState<mapboxgl.Map | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    const el = container.current
    if (!el) return
    let m: mapboxgl.Map
    try {
      m = new mapboxgl.Map({
        container: el,
        style: STYLE_URL,
        bounds: boundsOf(allPoints(doc)),
        fitBoundsOptions: { padding },
        minZoom: 3,
        maxZoom: 12,
        attributionControl: false,       // credits are written under the map
        cooperativeGestures: true,
      })
    } catch (err) {
      console.warn('[trajectory map] init failed', err)
      unavailable.current?.('init-failed')
      return
    }
    m.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new mapboxgl.ScaleControl({ maxWidth: 80, unit: 'metric' }), 'bottom-left')
    // tile 404s are routine; anything else is worth a line in the console
    m.on('error', (ev: MapErrorEvent) => {
      const status = ev?.error?.status ?? ev?.error?.statusCode
      if (status === 404 || status === 400 || ev?.sourceId || ev?.tile) return
      console.warn('[trajectory map] error', ev?.error?.message ?? ev)
    })
    let alive = true
    m.getCanvas().addEventListener('webglcontextlost', (e) => {
      e.preventDefault()
      if (alive) unavailable.current?.('context-lost')
    })
    m.on('load', () => { if (alive) setLoaded(true) })
    // the chat panel is hidden with display:none while another tab is open: redraw when it returns
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => m.resize()) : null
    ro?.observe(el)
    setMap(m)
    return () => {
      alive = false
      ro?.disconnect()
      m.remove()
      setMap(null)
      setLoaded(false)
    }
  }, [doc, padding])

  useBasemapTuning(map, loaded)
  useTrajectoryLayers(map, loaded, doc, visible)

  return <div ref={container} className={className} role="img" aria-label={title} data-testid="trajectory-map-gl" />
}
