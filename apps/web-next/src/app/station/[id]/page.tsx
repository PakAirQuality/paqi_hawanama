import { Suspense } from 'react'
import StationClient from './StationClient'

interface StationPageProps {
  params: { id: string }
}

// Generate static paths for all station IDs
export async function generateStaticParams() {
  // For static export, we'll generate these at build time
  try {
    const stationIds = await import('@/static/stationIds.json')
    return stationIds.default.map((id: string) => ({ id }))
  } catch (error) {
    // Fallback if the static file doesn't exist yet
    return []
  }
}

export default function StationPage({ params }: StationPageProps) {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-background">
        <div className="container mx-auto px-4 py-6">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-gray-200 rounded w-1/4"></div>
            <div className="h-64 bg-gray-200 rounded"></div>
          </div>
        </div>
      </div>
    }>
      <StationClient stationId={params.id} />
    </Suspense>
  )
}