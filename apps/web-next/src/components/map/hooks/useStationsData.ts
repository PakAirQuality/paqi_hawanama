import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Station } from '@/lib/api'

export const useStationsData = (enabled: boolean = true): { stations: Station[]; loading: boolean; error: string | null } => {
  const { data, isPending, error } = useQuery({
    queryKey: ['stations'],
    queryFn: () => api.getStations(),
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchInterval: enabled ? 5 * 60 * 1000 : false,
    retry: 1,
    retryDelay: 1500,
  })

  return {
    stations: data ?? [],
    loading: enabled && isPending,
    error: error ? (error instanceof Error ? error.message : 'Failed to fetch stations') : null,
  }
}
