/** Can this browser render a Mapbox GL map? Checked before constructing one, so an
 * unsupported or disabled WebGL never becomes an uncaught constructor error. */
export function canRenderMap(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    return !!gl
  } catch {
    return false
  }
}

export type MapUnavailableReason = 'no-webgl' | 'init-failed' | 'layers-failed' | 'context-lost' | 'runtime-error'

export const MAP_UNAVAILABLE_TEXT: Record<MapUnavailableReason, string> = {
  'no-webgl': 'This browser cannot render the interactive map (WebGL is unavailable or disabled).',
  'init-failed': 'The interactive map could not start.',
  'layers-failed': 'The map started, but its data layers could not be loaded.',
  'context-lost': 'The graphics context was lost (often memory pressure or a driver reset).',
  'runtime-error': 'The map hit an error while rendering.',
}
