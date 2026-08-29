'use client'

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import Link from 'next/link'

export default function CitiesPage() {
  const { data: citiesData, isLoading, error } = useQuery({
    queryKey: ['cities'],
    queryFn: () => api.getCities(50),
    refetchInterval: 300000, // Refresh every 5 minutes
  })

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background">
        <header className="border-b">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <div>
                <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
                <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
              </div>
            </div>
          </div>
        </header>
        <div className="container mx-auto px-4 py-8">
          <div className="text-center">Loading cities...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-background">
        <header className="border-b">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <div>
                <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
                <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
              </div>
            </div>
          </div>
        </header>
        <div className="container mx-auto px-4 py-8">
          <div className="text-center text-red-500">Error loading cities data</div>
        </div>
      </div>
    )
  }

  const cities = citiesData?.cities || []

  const getAQIColorClass = (aqi_color: string) => {
    switch (aqi_color) {
      case 'green': return 'text-green-600'
      case 'yellow': return 'text-yellow-600'
      case 'orange': return 'text-orange-600'
      case 'red': return 'text-red-600'
      case 'purple': return 'text-purple-600'
      case 'maroon': return 'text-red-900'
      default: return 'text-gray-600'
    }
  }

  const getAQIBgClass = (aqi_color: string) => {
    switch (aqi_color) {
      case 'green': return 'bg-green-100'
      case 'yellow': return 'bg-yellow-100'
      case 'orange': return 'bg-orange-100'
      case 'red': return 'bg-red-100'
      case 'purple': return 'bg-purple-100'
      case 'maroon': return 'bg-red-200'
      default: return 'bg-gray-100'
    }
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
              <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
            </div>
            <nav className="flex items-center space-x-4">
              <Link href="/" className="text-sm hover:underline">Dashboard</Link>
              <Link href="/city" className="text-sm font-medium">Cities</Link>
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-foreground mb-2">Air Quality by City</h1>
          <p className="text-muted-foreground">
            Monitor air quality across major cities in South Asia. Click on any city to view detailed information and station data.
          </p>
        </div>

        {/* Cities Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {cities.map((city: { slug: string; city_name: string; aqi_color: string; avg_aqi: number; station_count: number; last_update: string }) => (
            <Link key={city.slug} href={`/city/${city.slug}`}>
              <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">{city.city_name}</CardTitle>
                    <div className={`px-2 py-1 rounded text-sm font-bold ${getAQIColorClass(city.aqi_color)} ${getAQIBgClass(city.aqi_color)}`}>
                      {city.avg_aqi || '--'}
                    </div>
                  </div>
                  <CardDescription>{city.state}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="text-sm">
                    <div className={`font-medium ${getAQIColorClass(city.aqi_color)}`}>
                      {city.aqi_category}
                    </div>
                  </div>
                  
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Stations:</span>
                    <span className="font-medium">{city.active_stations}/{city.station_count}</span>
                  </div>
                  
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Updated:</span>
                    <span className="font-medium">{city.last_update}</span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>

        {cities.length === 0 && (
          <div className="text-center py-12">
            <p className="text-muted-foreground">No cities data available</p>
          </div>
        )}
      </div>
    </div>
  )
}