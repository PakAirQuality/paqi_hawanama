import { Suspense } from 'react'
import CityClient from './CityClient'

interface CityPageProps {
  params: { slug: string }
}

// Generate static paths for all city slugs
export async function generateStaticParams() {
  // For static export, we'll generate these at build time
  try {
    const citySlugs = await import('@/static/citySlugs.json')
    return citySlugs.default.map((slug: string) => ({ slug }))
  } catch (error) {
    // Fallback if the static file doesn't exist yet
    return []
  }
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