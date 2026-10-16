'use client'

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import Link from 'next/link'
import { formatPktDateTime } from '@/lib/dateLabel'

// /api/v1/cities returns aqi_category ('good' … 'hazardous'), not a colour name.
const getAQIColorClass = (category: string | null | undefined) => {
  switch (category) {
    case 'good': return 'text-green-600'
    case 'moderate': return 'text-yellow-600'
    case 'unhealthy_sensitive': return 'text-orange-600'
    case 'unhealthy': return 'text-red-600'
    case 'very_unhealthy': return 'text-purple-600'
    case 'hazardous': return 'text-red-900'
    default: return 'text-gray-600'
  }
}

const getAQIBgClass = (category: string | null | undefined) => {
  switch (category) {
    case 'good': return 'bg-green-100'
    case 'moderate': return 'bg-yellow-100'
    case 'unhealthy_sensitive': return 'bg-orange-100'
    case 'unhealthy': return 'bg-red-100'
    case 'very_unhealthy': return 'bg-purple-100'
    case 'hazardous': return 'bg-red-200'
    default: return 'bg-gray-100'
  }
}

const categoryLabel = (category: string | null | undefined) =>
  category
    ? category
        .replace('unhealthy_sensitive', 'Unhealthy for Sensitive Groups')
        .replace(/_/g, ' ')
        .replace(/^\w/, (c) => c.toUpperCase())
    : 'No recent data'

interface LiveCity {
  slug: string
  name: string
  state: string
  aqi_category: string | null
  avg_aqi: number | null
  station_count: number
  last_update: string | null
}

/** Live grid of the busiest cities; the crawlable full list lives in the server page around it. */
export default function CityIndexClient() {
  const { data: citiesData, isLoading, error } = useQuery({
    queryKey: ['cities'],
    queryFn: () => api.getCities(50),
    refetchInterval: 300000, // Refresh every 5 minutes
  })

  if (isLoading) {
    return <div className="text-center text-muted-foreground py-8">Loading live city data...</div>
  }
  if (error) {
    return <div className="text-center text-red-500 py-8">Error loading live city data</div>
  }

  const cities: LiveCity[] = citiesData?.cities || []
  if (cities.length === 0) {
    return <div className="text-center text-muted-foreground py-8">No live city data available</div>
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
      {cities.map((city) => (
        <Link key={city.slug} href={`/city/${city.slug}/`}>
          <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg">{city.name}</CardTitle>
                <div className={`px-2 py-1 rounded text-sm font-bold ${getAQIColorClass(city.aqi_category)} ${getAQIBgClass(city.aqi_category)}`}>
                  {city.avg_aqi != null ? Math.round(city.avg_aqi) : '--'}
                </div>
              </div>
              <CardDescription>{city.state}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="text-sm">
                <div className={`font-medium ${getAQIColorClass(city.aqi_category)}`}>
                  {categoryLabel(city.aqi_category)}
                </div>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Stations:</span>
                <span className="font-medium">{city.station_count}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Updated:</span>
                <span className="font-medium">{formatPktDateTime(city.last_update)}</span>
              </div>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  )
}
