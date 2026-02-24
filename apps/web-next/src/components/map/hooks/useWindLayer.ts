import { useEffect, useRef } from 'react'
import { WindParticleRenderer } from '../layers/WindParticleLayer'
import type { WindMetadata } from './useWindData'

/**
 * Manages the WindParticleRenderer lifecycle on a Mapbox map instance.
 * Creates/destroys the canvas overlay in response to visibility and data changes.
 */
export function useWindLayer(
  map: any | null,
  windImage: HTMLImageElement | null,
  windMetadata: WindMetadata | null,
  visible: boolean,
) {
  const rendererRef = useRef<WindParticleRenderer | null>(null)

  useEffect(() => {
    // Clean up any existing renderer
    if (rendererRef.current) {
      rendererRef.current.destroy()
      rendererRef.current = null
    }

    if (!map || !windImage || !windMetadata || !visible) return

    try {
      const renderer = new WindParticleRenderer(map, windImage, windMetadata)
      renderer.start()
      rendererRef.current = renderer
    } catch (err) {
      console.error('[useWindLayer] Failed to create wind renderer:', err)
    }

    return () => {
      if (rendererRef.current) {
        rendererRef.current.destroy()
        rendererRef.current = null
      }
    }
  }, [map, windImage, windMetadata, visible])
}
