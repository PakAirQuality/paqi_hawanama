import { useState, useEffect } from 'react'
import { api } from '@/lib/api'
import type { Station } from '@/lib/api'

/**
 * Hook for fetching and managing stations data
 */
export const useStationsData = () => {
  const [stations, setStations] = useState<Station[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    
    const fetchStations = async () => {
      try {
        console.log('🔍 useStationsData: Fetching stations...')
        const data = await api.getStations()
        console.log('🔍 useStationsData: Received', data?.length || 0, 'stations')
        if (mounted) { 
          setStations(data)
          setError(null)
        }
      } catch (err) {
        console.error('🔍 useStationsData: Error fetching stations:', err)
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to fetch stations')
        }
      } finally {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    fetchStations()
    
    return () => { 
      mounted = false 
    }
  }, [])

  return { stations, loading, error }
}