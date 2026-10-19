import { Suspense } from 'react'
import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import CityClient from './CityClient'
import SiteFooter from '@/components/layout/SiteFooter'
import citySlugs from '@/static/citySlugs.json'
import { SITE, stationPath, cityPath, placeLabel, absoluteUrl, jsonLd, breadcrumbJsonLd } from '@/lib/site'
import { findCity, stationsInCity } from '@/lib/siteData'

export function generateStaticParams() {
  return citySlugs.map((slug: string) => ({ slug }))
}

interface CityPageProps {
  params: { slug: string }
}

export function generateMetadata({ params }: CityPageProps): Metadata {
  const city = findCity(params.slug)
  if (!city) return { title: 'City not found', robots: { index: false } }
  const where = placeLabel([city.state, city.country])
  const title = `${city.name} Air Quality Index (AQI) and PM2.5 Today`
  const description = `Live air quality in ${city.name}${where ? `, ${where}` : ''}: hourly PM2.5, US AQI and a 24-hour trend from ${city.station_count || 'local'} monitoring station${city.station_count === 1 ? '' : 's'}. Open data by the Pakistan Air Quality Initiative.`
  return {
    title,
    description,
    alternates: { canonical: cityPath(city.slug) },
    openGraph: {
      title: `${title} | Hawanama`,
      description,
      url: cityPath(city.slug),
      type: 'website',
      images: [{ url: SITE.ogImage, width: 1200, height: 630 }],
    },
    twitter: { card: 'summary_large_image', title: `${title} | Hawanama`, description, images: [SITE.ogImage] },
  }
}

export default function CityPage({ params }: CityPageProps) {
  const city = findCity(params.slug)
  if (!city) notFound()

  const stations = stationsInCity(city.name)
  const where = placeLabel([city.state, city.country])
  const breadcrumbs = breadcrumbJsonLd([
    { name: 'Home', path: '/' },
    { name: 'Cities', path: '/city/' },
    { name: city.name, path: cityPath(city.slug) },
  ])
  const place = {
    '@context': 'https://schema.org',
    '@type': 'City',
    name: city.name,
    url: absoluteUrl(cityPath(city.slug)),
    ...(city.state ? { containedInPlace: { '@type': 'AdministrativeArea', name: city.state } } : {}),
    ...(city.lat != null && city.lon != null
      ? { geo: { '@type': 'GeoCoordinates', latitude: city.lat, longitude: city.lon } }
      : {}),
  }

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbs) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(place) }} />
      <Suspense
        fallback={
          <div className="min-h-screen bg-background">
            <div className="container mx-auto px-4 py-8">
              <h1 className="text-xl sm:text-2xl font-bold text-foreground">{city.name} air quality</h1>
              <p className="text-muted-foreground mt-2">Loading live data…</p>
            </div>
          </div>
        }
      >
        <CityClient citySlug={params.slug} city={{ name: city.name, state: city.state, country: city.country }} />
      </Suspense>

      <section className="container mx-auto px-4 py-8 border-t text-sm leading-relaxed">
        <nav aria-label="Breadcrumb" className="text-muted-foreground mb-4">
          <Link href="/" className="hover:underline">Home</Link>
          <span aria-hidden="true"> › </span>
          <Link href="/city/" className="hover:underline">Cities</Link>
          <span aria-hidden="true"> › </span>
          <span className="text-foreground">{city.name}</span>
        </nav>
        <h2 className="text-lg font-semibold text-foreground mb-2">About air quality monitoring in {city.name}</h2>
        <p className="text-muted-foreground max-w-3xl">
          This page shows live fine particulate matter (PM2.5) and the US Air Quality Index (AQI) for {city.name}
          {where ? `, ${where}` : ''}, averaged across {city.station_count || 'its'} monitoring station
          {city.station_count === 1 ? '' : 's'} and updated every hour. Readings come from the Pakistan Air Quality
          Initiative’s monitoring network and partner monitors published through IQAir. Each hourly value is the
          average of the hour that just ended. Data on Hawanama is open: see the{' '}
          <Link href="/about/" className="underline hover:text-foreground">About page</Link> for downloads, the
          API and how to cite it.
        </p>
        {stations.length > 0 && (
          <div className="mt-6">
            <h3 className="font-semibold text-foreground mb-2">Monitoring stations in {city.name}</h3>
            <ul className="columns-1 sm:columns-2 lg:columns-3 gap-6 text-muted-foreground">
              {stations.map((s) => (
                <li key={s.id} className="break-inside-avoid">
                  <Link href={stationPath(s.id)} className="hover:underline">{s.name}</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
      <SiteFooter />
    </>
  )
}
