import { Suspense } from 'react'
import type { Metadata } from 'next'
import Link from 'next/link'
import StationClient from './StationClient'
import SiteFooter from '@/components/layout/SiteFooter'
import stationIds from '@/static/stationIds.json'
import { SITE, stationPath, cityPath, placeLabel, absoluteUrl, jsonLd, breadcrumbJsonLd } from '@/lib/site'
import { findStation } from '@/lib/siteData'

export function generateStaticParams() {
  return stationIds.map((id: string) => ({ id }))
}

interface StationPageProps {
  params: { id: string }
}

export function generateMetadata({ params }: StationPageProps): Metadata {
  const station = findStation(params.id)
  if (!station) {
    // Older station id without a current reading: keep the URL alive, keep it out of the index.
    return { title: `Station ${params.id}`, robots: { index: false, follow: true } }
  }
  const where = placeLabel([station.city, station.state, station.country])
  const title = `${station.name} Air Quality Monitor${station.city ? `, ${station.city}` : ''}`
  const description = `Live PM2.5 and US AQI at the ${station.name} air quality monitoring station${where ? ` in ${where}` : ''}, with a 24-hour history. Hourly open data from the Pakistan Air Quality Initiative.`
  return {
    title,
    description,
    alternates: { canonical: stationPath(station.id) },
    openGraph: {
      title: `${title} | Hawanama`,
      description,
      url: stationPath(station.id),
      type: 'website',
      images: [{ url: SITE.ogImage, width: 1200, height: 630 }],
    },
    twitter: { card: 'summary_large_image', title: `${title} | Hawanama`, description, images: [SITE.ogImage] },
  }
}

export default function StationPage({ params }: StationPageProps) {
  const station = findStation(params.id)
  const name = station?.name ?? `Station ${params.id}`
  const where = station ? placeLabel([station.city, station.state, station.country]) : ''
  const crumbs = [{ name: 'Home', path: '/' }, { name: 'Cities', path: '/city/' }]
  if (station?.city && station.city_slug) crumbs.push({ name: station.city, path: cityPath(station.city_slug) })
  crumbs.push({ name, path: stationPath(params.id) })

  const place = station
    ? {
        '@context': 'https://schema.org',
        '@type': 'Place',
        name: station.name,
        url: absoluteUrl(stationPath(station.id)),
        ...(station.city ? { containedInPlace: { '@type': 'City', name: station.city } } : {}),
        ...(station.lat != null && station.lon != null
          ? { geo: { '@type': 'GeoCoordinates', latitude: station.lat, longitude: station.lon } }
          : {}),
      }
    : null

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd(crumbs)) }} />
      {place && <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(place) }} />}
      <Suspense
        fallback={
          <div className="min-h-screen bg-background">
            <div className="container mx-auto px-4 py-6">
              <h1 className="text-2xl font-bold text-foreground">{name}</h1>
              <p className="text-muted-foreground mt-2">Loading live data…</p>
            </div>
          </div>
        }
      >
        <StationClient stationId={params.id} station={station ? { name: station.name, city: station.city } : undefined} />
      </Suspense>

      <section className="container mx-auto px-4 py-8 border-t text-sm leading-relaxed">
        <nav aria-label="Breadcrumb" className="text-muted-foreground mb-4">
          {crumbs.map((c, i) => (
            <span key={c.path}>
              {i > 0 && <span aria-hidden="true"> › </span>}
              {i < crumbs.length - 1 ? (
                <Link href={c.path} className="hover:underline">{c.name}</Link>
              ) : (
                <span className="text-foreground">{c.name}</span>
              )}
            </span>
          ))}
        </nav>
        <h2 className="text-lg font-semibold text-foreground mb-2">About this monitor</h2>
        <p className="text-muted-foreground max-w-3xl">
          {name} is an air quality monitoring station{where ? ` in ${where}` : ''}
          {station?.lat != null && station?.lon != null ? ` (${station.lat.toFixed(4)}°, ${station.lon.toFixed(4)}°)` : ''}
          . Hawanama shows its hourly fine particulate matter (PM2.5) concentration in µg/m³ and the matching US Air
          Quality Index, plus the last 24 hours. Each hourly value is the average of the hour that just ended.
          {station?.city && station.city_slug ? (
            <>
              {' '}See all monitors and the city average on the{' '}
              <Link href={cityPath(station.city_slug)} className="underline hover:text-foreground">
                {station.city} air quality page
              </Link>
              .
            </>
          ) : null}{' '}
          Data is open; see <Link href="/about/" className="underline hover:text-foreground">About</Link> for
          downloads, the API and how to cite it.
        </p>
      </section>
      <SiteFooter />
    </>
  )
}
