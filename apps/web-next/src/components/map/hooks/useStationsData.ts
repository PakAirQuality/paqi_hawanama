import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Station } from '@/lib/api'

export const useStationsData = (): { stations: Station[]; loading: boolean; error: string | null } => {
  const { data, isPending, error } = useQuery({
    queryKey: ['stations'],
    queryFn: () => api.getStations(),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  })

  return {
    stations: data ?? [],
    loading: isPending,
    error: error ? (error instanceof Error ? error.message : 'Failed to fetch stations') : null,
  }
}
