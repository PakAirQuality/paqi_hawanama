import { useState, useEffect, useRef } from 'react'

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE || 'https://hawanama-152782825429.asia-south1.run.app/api'

export interface WindMetadata {
  width: number
  height: number
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
  u_min: number
  u_max: number
  v_min: number
  v_max: number
  generated_at: string
  attribution: string
}

/**
 * Hook for fetching wind texture and metadata.
 * Only fetches when enabled (lazy loading — zero impact on initial map load).
 * Re-fetches every 30 minutes while enabled.
 */
export function useWindData(enabled: boolean) {
  const [windImage, setWindImage] = useState<HTMLImageElement | null>(null)
  const [windMetadata, setWindMetadata] = useState<WindMetadata | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!enabled) {
      // Clear interval when disabled but keep cached data
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      return
    }

    let mounted = true

    const fetchWind = async () => {
      setLoading(true)
      setError(null)

      try {
        // Fetch texture and metadata in parallel
        const [texResp, metaResp] = await Promise.all([
          fetch(`${BASE_URL}/v1/data-sources/wind/texture`),
          fetch(`${BASE_URL}/v1/data-sources/wind/metadata`),
        ])

        if (!texResp.ok) throw new Error(`Texture fetch failed: ${texResp.status}`)
        if (!metaResp.ok) throw new Error(`Metadata fetch failed: ${metaResp.status}`)

        const [blob, meta] = await Promise.all([
          texResp.blob(),
          metaResp.json(),
        ])

        // Decode PNG blob into an HTMLImageElement for WebGL upload
        const img = new Image()
        img.crossOrigin = 'anonymous'

        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve()
          img.onerror = () => reject(new Error('Failed to decode wind texture'))
          img.src = URL.createObjectURL(blob)
        })

        if (mounted) {
          setWindImage(img)
          setWindMetadata(meta)
          setError(null)
        }
      } catch (err) {
        console.error('[useWindData] Error:', err)
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to fetch wind data')
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    fetchWind()

    // Re-fetch every 30 minutes
    intervalRef.current = setInterval(fetchWind, 30 * 60 * 1000)

    return () => {
      mounted = false
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [enabled])

  return { windImage, windMetadata, loading, error }
}
