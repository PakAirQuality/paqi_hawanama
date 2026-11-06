"use client"

// The trajectory map inside a chat answer, on the Tracker's Mapbox style with a faded (not
// monochrome) basemap so boundaries, water and place names show at the zoom of a small figure.
// Two modes: `preview` is the small picture in the chat (not interactive, no controls, no popups;
// a click on it opens the expanded view), the default is the full map in the expanded view (pan,
// zoom, +/−, hover popups). Mapbox GL needs WebGL, so the shell (TrajectoryMiniMap) only mounts
// this when the browser can draw it and the figure is on screen; otherwise it shows the SVG.

import { useEffect, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import type { TrajectoryDoc } from '@/components/fires/api'
import { useBasemapTuning } from '@/components/ops-pipeline/mapViz'
import { useTrajectoryLayers } from '@/lib/chat/trajectoryLayers'
import { allPoints, boundsOf, centralPoints } from '@/lib/chat/trajectoryMap'
import type { MapErrorEvent, MapUnavailableReason } from '@/lib/webgl'

// the deployed build reads a token restricted to this site's own addresses (.env.production.local)
mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''

const STYLE_URL = 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu'

/** Basemap settings: the faded theme keeps land, water and relief visible without competing with the coloured paths, a
 *  strong relief, our rank-2 cities from zoom 4.5. The basemap's own town names only on the expanded view: on the small
 *  preview they double up our city labels. */
const PREVIEW_BASEMAP = { theme: 'faded' as const, placeLabels: false, cityStep: 4.5, relief: 'strong' as const }
const FULL_BASEMAP = { theme: 'faded' as const, placeLabels: true, cityStep: 4.5, relief: 'strong' as const }

/** Room for the origin label, the scale bar and the expand chip in the small figure; wider all round in the expanded view */
const PREVIEW_PADDING = { top: 30, bottom: 34, left: 30, right: 58 }
const FULL_PADDING = 60

interface Props {
  doc: TrajectoryDoc
  /** level keys to draw ('1000' | '925' | '850') */
  visible: string[]
  className?: string
  /** the small picture in the chat: no interaction, no controls, no popups */
  preview?: boolean
  title: string
  /** Called when the map cannot run here; the shell then falls back to the SVG */
  onUnavailable?: (reason: MapUnavailableReason) => void
}

export function TrajectoryMapGL({ doc, visible, className, preview = false, title, onUnavailable }: Props) {
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
        // the preview is fitted to the central paths (members may run off its edge); the expanded view holds everything
        bounds: boundsOf(preview ? centralPoints(doc) : allPoints(doc)),
        fitBoundsOptions: { padding: preview ? PREVIEW_PADDING : FULL_PADDING },
        minZoom: 3,
        maxZoom: 12,
        interactive: !preview,
        cooperativeGestures: !preview,   // wheel scrolling the chat must not zoom the expanded map
        attributionControl: false,
      })
    } catch (err) {
      console.warn('[trajectory map] init failed', err)
      unavailable.current?.('init-failed')
      return
    }
    // Mapbox's own compact credit (the ⓘ in the corner) rather than a line of caption
    m.addControl(new mapboxgl.AttributionControl({ compact: true }), 'bottom-right')
    if (!preview) m.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
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
  }, [doc, preview])

  useBasemapTuning(map, loaded, preview ? PREVIEW_BASEMAP : FULL_BASEMAP)
  useTrajectoryLayers(map, loaded, doc, visible, !preview)

  return <div ref={container} className={className} role="img" aria-label={title} data-testid="trajectory-map-gl" />
}
