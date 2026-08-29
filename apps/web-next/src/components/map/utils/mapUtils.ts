import type mapboxglType from 'mapbox-gl'

/**
 * Wait for container to have valid dimensions before initializing map
 */
export function waitForContainerSize(el: HTMLElement, timeoutMs = 2000): Promise<void> {
  return new Promise((resolve) => {
    const start = performance.now()
    const check = () => {
      const { width, height } = el.getBoundingClientRect()
      if (width > 0 && height > 0) return resolve()
      if (performance.now() - start > timeoutMs) return resolve()
      requestAnimationFrame(check)
    }
    check()
  })
}

/**
 * Apply Climate TRACE visual polish to map style
 */
export const applyClimateTracePolish = (map: mapboxglType.Map) => {
  const setPaintProperty = (id: string, props: Record<string, any>) => {
    if (!map.getLayer(id)) return
    for (const [key, value] of Object.entries(props)) {
      map.setPaintProperty(id, key, value)
    }
  }

  // 1) Softer background + water
  if (map.getLayer('background')) {
    map.setPaintProperty('background', 'background-color', '#ECEFF1')   // light warm gray
  }
  ;['water', 'water-fill', 'water/1'].forEach(id =>
    setPaintProperty(id, { 'fill-color': '#DFE7EC', 'fill-opacity': 0.95 })
  )

  // 2) Roads: thin + muted so air quality circles stand out
  map.getStyle().layers
    .filter(l => l.id.startsWith('road-') && l.type === 'line')
    .forEach(l => setPaintProperty(l.id, { 'line-color': '#B9BFC6', 'line-opacity': 0.65 }))

  // 3) Admin boundaries: subtle
  ;['admin-0-boundary', 'admin-1-boundary'].forEach(id =>
    setPaintProperty(id, { 'line-color': '#A6AEB6', 'line-opacity': 0.55 })
  )

  // 4) Labels: darker text + soft halos for legibility
  map.getStyle().layers
    .filter(l => l.type === 'symbol' && /label/.test(l.id))
    .forEach(l => setPaintProperty(l.id, {
      'text-color': '#4a5562',
      'text-halo-color': '#F3F5F7',
      'text-halo-width': 1.2
    }))
}