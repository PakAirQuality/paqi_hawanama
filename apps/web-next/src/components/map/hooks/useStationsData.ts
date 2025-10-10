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
    let refreshInterval: NodeJS.Timeout
    
    const fetchStations = async (isRefresh = false) => {
      try {
        if (!isRefresh) {
          console.log('🔍 useStationsData: Initial fetch...')
        } else {
          console.log('🔍 useStationsData: Refreshing stations data...')
        }
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
        if (mounted && !isRefresh) {
          setLoading(false)
        }
      }
    }

    // Initial fetch
    fetchStations()
    
    // Set up refresh interval (5 minutes to match station popup)
    refreshInterval = setInterval(() => {
      if (mounted) {
        fetchStations(true)
      }
    }, 5 * 60 * 1000) // 5 minutes
    
    return () => { 
      mounted = false
      if (refreshInterval) {
        clearInterval(refreshInterval)
      }
    }
  }, [])

  return { stations, loading, error }
}