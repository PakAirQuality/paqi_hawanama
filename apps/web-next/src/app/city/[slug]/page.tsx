import { Suspense } from 'react'
import CityClient from './CityClient'
import citySlugs from '@/static/citySlugs.json'

export function generateStaticParams() {
  return citySlugs.map((slug: string) => ({ slug }))
}

interface CityPageProps {
  params: { slug: string }
}

export default function CityPage({ params }: CityPageProps) {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-background">
        <div className="container mx-auto px-4 py-8">
          <div className="text-center">Loading city data...</div>
        </div>
      </div>
    }>
      <CityClient citySlug={params.slug} />
    </Suspense>
  )
}