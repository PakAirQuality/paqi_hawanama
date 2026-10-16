import type { Metadata } from 'next'
import Link from 'next/link'
import CityIndexClient from './CityIndexClient'
import SiteFooter from '@/components/layout/SiteFooter'
import { SITE, cityPath, jsonLd, breadcrumbJsonLd } from '@/lib/site'
import { allCities } from '@/lib/siteData'

const title = 'Air Quality by City: Pakistan, India, Bangladesh, Nepal and Sri Lanka'
const description =
  'Live AQI and PM2.5 for every monitored city in Pakistan and South Asia, from Lahore, Karachi and Islamabad to Delhi, Dhaka, Kathmandu and Colombo. Hourly open data by the Pakistan Air Quality Initiative.'

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: '/city/' },
  openGraph: { title: `${title} | Hawanama`, description, url: '/city/', type: 'website', images: [{ url: SITE.ogImage, width: 1200, height: 630 }] },
  twitter: { card: 'summary_large_image', title: `${title} | Hawanama`, description, images: [SITE.ogImage] },
}

const COUNTRY_ORDER = ['Pakistan', 'India', 'Bangladesh', 'Nepal', 'Sri Lanka']

function groupCities() {
  const byCountry = new Map<string, Map<string, typeof allCities>>()
  for (const c of allCities) {
    const country = c.country || 'Other'
    const state = c.state || 'Other'
    if (!byCountry.has(country)) byCountry.set(country, new Map())
    const states = byCountry.get(country)!
    if (!states.has(state)) states.set(state, [])
    states.get(state)!.push(c)
  }
  const countries = Array.from(byCountry.keys()).sort(
    (a, b) => (COUNTRY_ORDER.indexOf(a) + 1 || 99) - (COUNTRY_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b),
  )
  return countries.map((country) => ({
    country,
    states: Array.from(byCountry.get(country)!.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([state, cities]) => ({ state, cities: cities.slice().sort((a, b) => a.name.localeCompare(b.name)) })),
  }))
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
          <div className="flex items-center justify-between">
            <div>
              <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
              <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
            </div>
            <nav className="flex items-center space-x-4">
              <Link href="/" className="text-sm hover:underline">Dashboard</Link>
              <Link href="/city/" className="text-sm font-medium">Cities</Link>
              <Link href="/about/" className="text-sm hover:underline">About</Link>
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-foreground mb-2">Air Quality by City</h1>
          <p className="text-muted-foreground max-w-3xl">
            Hourly PM2.5 and US AQI for {allCities.length} monitored cities across Pakistan, India, Bangladesh, Nepal
            and Sri Lanka. The cards show the cities with the most recent data; every monitored city is listed below.
            Click a city for its live reading, 24-hour trend and the stations behind it.
          </p>
        </div>

        <CityIndexClient />

        <section className="mt-12">
          <h2 className="text-2xl font-bold text-foreground mb-4">All monitored cities</h2>
          {groups.map((g) => (
            <div key={g.country} className="mb-8">
              <h3 className="text-xl font-semibold text-foreground mb-3">{g.country}</h3>
              {g.states.map((s) => (
                <div key={s.state} className="mb-4">
                  <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-1">{s.state}</h4>
                  <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                    {s.cities.map((c) => (
                      <li key={c.slug}>
                        <Link href={cityPath(c.slug)} className="hover:underline text-foreground">
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
            </div>
          ))}
        </section>
      </div>
      <SiteFooter />
    </div>
  )
}
