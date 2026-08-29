import { Suspense } from 'react'
import StationClient from './StationClient'
import stationIds from '@/static/stationIds.json'

export function generateStaticParams() {
  return stationIds.map((id: string) => ({ id }))
}

interface StationPageProps {
  params: { id: string }
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