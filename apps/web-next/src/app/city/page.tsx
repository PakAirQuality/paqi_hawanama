import type { Metadata } from 'next'
import Link from 'next/link'
import CityIndexClient from './CityIndexClient'
import SiteFooter from '@/components/layout/SiteFooter'
import { SITE, cityPath, jsonLd, breadcrumbJsonLd } from '@/lib/site'
import { allCities } from '@/lib/siteData'

const title = 'Air Quality by City in Pakistan'
const description =
  'Live AQI and PM2.5 for every monitored city in Pakistan, from Lahore, Karachi and Islamabad to Peshawar, Faisalabad and Quetta. Hourly open data by the Pakistan Air Quality Initiative.'

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: '/city/' },
  openGraph: { title: `${title} | Hawanama`, description, url: '/city/', type: 'website', images: [{ url: SITE.ogImage, width: 1200, height: 630 }] },
  twitter: { card: 'summary_large_image', title: `${title} | Hawanama`, description, images: [SITE.ogImage] },
}

function groupCities() {
  const states = new Map<string, typeof allCities>()
  for (const c of allCities) {
    const state = c.state || 'Other'
    if (!states.has(state)) states.set(state, [])
    states.get(state)!.push(c)
  }
  return Array.from(states.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([state, cities]) => ({ state, cities: cities.slice().sort((a, b) => a.name.localeCompare(b.name)) }))
}

export default function CitiesPage() {
  const groups = groupCities()
  const crumbs = breadcrumbJsonLd([
    { name: 'Home', path: '/' },
    { name: 'Cities', path: '/city/' },
  ])

  return (
    <div className="min-h-screen bg-background">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(crumbs) }} />
      {/* Header */}
      <header className="border-b">
        <div className="container mx-auto px-4 py-4">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <div>
              <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
              <p className="hidden sm:block text-sm text-muted-foreground">Pakistan Air Quality Monitoring</p>
            </div>
            <nav className="flex items-center space-x-4">
              <Link href="/" className="py-1.5 text-sm hover:underline">Dashboard</Link>
              <Link href="/city/" className="py-1.5 text-sm font-medium">Cities</Link>
              <Link href="/about/" className="py-1.5 text-sm hover:underline">About</Link>
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-foreground mb-2">Air Quality by City</h1>
          <p className="text-muted-foreground max-w-3xl">
            Hourly PM2.5 and US AQI for {allCities.length} monitored cities across Pakistan. The cards show the cities
            with the most recent data; every monitored city is listed below.
            Click a city for its live reading, 24-hour trend and the stations behind it.
          </p>
        </div>

        <CityIndexClient />

        <section className="mt-12">
          <h2 className="text-2xl font-bold text-foreground mb-4">All monitored cities</h2>
          {groups.map((s) => (
            <div key={s.state} className="mb-4">
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-1">{s.state}</h3>
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                {s.cities.map((c) => (
                  <li key={c.slug}>
                    <Link href={cityPath(c.slug)} className="inline-block py-1 sm:py-0 hover:underline text-foreground">
                      {c.name}
                    </Link>
                    {c.station_count > 1 && (
                      <span className="text-muted-foreground"> ({c.station_count})</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      </div>
      <SiteFooter />
    </div>
  )
}
