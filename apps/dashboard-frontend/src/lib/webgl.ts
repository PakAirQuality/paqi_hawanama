/** Can this browser render a Mapbox GL map? Checked before constructing one, so an
 * unsupported or disabled WebGL never becomes an uncaught constructor error. */
export function canRenderMap(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    const gl = (canvas.getContext('webgl2') || canvas.getContext('webgl') || canvas.getContext('experimental-webgl')) as WebGLRenderingContext | null
    if (!gl) return false
    // Release the probe at once: browsers cap live WebGL contexts (about 16), and every check
    // (each map mount, each hot reload in development) would otherwise hold one more.
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return true
  } catch {
    return false
  }
}

/** The fields our Mapbox 'error' handlers read; tile and source errors carry sourceId/tile. */
export type MapErrorEvent = {
  error?: { message?: string; status?: number; statusCode?: number }
  sourceId?: string
  tile?: unknown
}

export type MapUnavailableReason = 'no-webgl' | 'init-failed' | 'layers-failed' | 'context-lost' | 'runtime-error'

export const MAP_UNAVAILABLE_TEXT: Record<MapUnavailableReason, string> = {
  'no-webgl': 'This browser cannot render the interactive map (WebGL is unavailable or disabled).',
  'init-failed': 'The interactive map could not start.',
  'layers-failed': 'The map started, but its data layers could not be loaded.',
  'context-lost': 'The graphics context was lost (often memory pressure or a driver reset).',
  'runtime-error': 'The map hit an error while rendering.',
}
