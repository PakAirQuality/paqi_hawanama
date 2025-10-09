'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import MapWrapper from '@/components/map/MapWrapper'
import { StationCard } from '@/components/station/StationCard'
import { CitySearch } from '@/components/ui/CitySearch'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import Link from 'next/link'
import { usePersistentState } from '@/hooks/usePersistentState'

export default function Home() {

  // Debug database state
  const { data: debugInfo } = useQuery({
    queryKey: ['debug-info'],
    queryFn: async () => {
      console.log('🔍 DEBUG: Fetching debug info...')
      const result = await api.getDebugInfo()
      console.log('🔍 DEBUG: Database debug info:', result)
      return result
    },
  })

  // Fetch dashboard statistics
  const { data: dashboardStats, isLoading } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: () => api.getDashboardStats(),
    refetchInterval: 60000, // Refresh every minute
  })
  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Header */}
      <header className="flex-shrink-0 border-b">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center space-x-3 min-w-0">
              <img 
                src="/logo-cropped.png" 
                alt="Hawanama Logo" 
                className="w-8 h-8 sm:w-12 sm:h-12 object-contain flex-shrink-0"
              />
              <div className="min-w-0">
                <h1 className="text-lg sm:text-2xl font-bold text-foreground truncate">Hawanama</h1>
                <p className="text-xs sm:text-sm text-muted-foreground hidden sm:block">Pakistan Air Quality Monitoring</p>
              </div>
            </div>
            <div className="flex items-center space-x-2 sm:space-x-4 min-w-0">
              <CitySearch className="w-32 sm:w-48 md:w-64" />
              <nav className="hidden md:flex items-center space-x-4">
                <span className="text-sm text-muted-foreground">Cities</span>
              </nav>
              <div className="hidden sm:flex items-center space-x-2">
                <span className="text-sm text-muted-foreground">Live Data</span>
                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content - Full Width Map */}
      <div className="relative flex-1 w-full h-[calc(100vh-140px)]">
        {/* Full Width Map */}
        <MapWrapper 
          className="w-full h-full"
        />
        
        {/* Floating Overview Card - Temporarily commented out */}
        {/* <div className="absolute top-4 left-4 z-10">
          <Card className="w-80 bg-white shadow-lg">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Overview</CardTitle>
              <CardDescription className="text-xs">Real-time air quality across Pakistan</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <div>
                <div className="flex justify-between items-center">
                  <span className="text-xs font-medium">Active Stations</span>
                  <span className="text-xl font-bold">
                    {isLoading ? '...' : dashboardStats?.active_stations || 0}
                  </span>
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {isLoading ? 'Loading...' : `${dashboardStats?.total_stations || 0} total stations`}
                </div>
              </div>
              <div>
                <div className="flex justify-between items-center">
                  <span className="text-xs font-medium">Avg PM 2.5</span>
                  <span className={`text-xl font-bold ${
                    dashboardStats?.aqi_color === 'green' ? 'text-green-600' :
                    dashboardStats?.aqi_color === 'yellow' ? 'text-yellow-600' :
                    dashboardStats?.aqi_color === 'orange' ? 'text-orange-600' :
                    dashboardStats?.aqi_color === 'red' ? 'text-red-600' :
                    dashboardStats?.aqi_color === 'purple' ? 'text-purple-600' :
                    'text-gray-600'
                  }`}>
                    {isLoading ? '...' : dashboardStats?.avg_pm25 || '--'}
                  </span>
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {isLoading ? 'Loading...' : 'μg/m³'}
                </div>
              </div>
              <div>
                <div className="flex justify-between items-center">
                  <span className="text-xs font-medium">Last Update</span>
                  <span className="text-xs">
                    {isLoading ? '...' : dashboardStats?.last_update || 'No data'}
                  </span>
                </div>
              </div>
              {dashboardStats?.top_cities && dashboardStats.top_cities.length > 0 && (
                <div>
                  <div className="text-xs font-medium mb-1">Highest AQI Cities</div>
                  <div className="space-y-0.5">
                    {dashboardStats.top_cities.slice(0, 3).map((city: { name: string; aqi: number }, index: number) => (
                      <div key={index} className="flex justify-between text-[10px]">
                        <span className="truncate">{city.name.split(',')[0]}</span>
                        <span className="font-medium">{Math.round(city.aqi)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div> */}
        
      </div>
      
      {/* Station Card Popup */}
      <StationCard />
    </div>
  )
}