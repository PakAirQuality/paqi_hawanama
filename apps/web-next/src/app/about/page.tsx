import type { Metadata } from 'next'
import Link from 'next/link'
import SiteFooter from '@/components/layout/SiteFooter'
import { SITE, jsonLd, breadcrumbJsonLd, absoluteUrl } from '@/lib/site'
import { allCities, allStations } from '@/lib/siteData'

const title = 'About Hawanama: Open Air Quality Data for Pakistan'
const description =
  'Hawanama is the Pakistan Air Quality Initiative’s real-time air quality platform: how the PM2.5 and AQI data is collected, where to download it, the open-source code on GitHub, and how to cite it.'

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: '/about/' },
  openGraph: { title: `${title} | Hawanama`, description, url: '/about/', type: 'website', images: [{ url: SITE.ogImage, width: 1200, height: 630 }] },
  twitter: { card: 'summary_large_image', title: `${title} | Hawanama`, description, images: [SITE.ogImage] },
}

const ext = { target: '_blank', rel: 'noopener' } as const
const A = ({ href, children }: { href: string; children: React.ReactNode }) => (
  <a href={href} className="underline hover:text-foreground" {...ext}>{children}</a>
)

export default function AboutPage() {
  const pkCities = allCities.filter((c) => c.country === 'Pakistan').length
  const pkStations = allStations.filter((s) => s.country === 'Pakistan').length
  const datasetJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Dataset',
    name: 'Hawanama hourly air quality readings for Pakistan and South Asia',
    description: `Hourly PM2.5 (µg/m³) and US AQI from ${allStations.length} monitoring stations in ${allCities.length} cities across Pakistan, India, Bangladesh, Nepal and Sri Lanka, collected by the Pakistan Air Quality Initiative and partners.`,
    url: absoluteUrl('/about/'),
    license: 'https://creativecommons.org/licenses/by/4.0/',
    isAccessibleForFree: true,
    creator: { '@id': `${SITE.url}/#organization` },
    keywords: ['air quality', 'PM2.5', 'AQI', 'Pakistan', 'South Asia', 'air pollution', 'open data'],
    spatialCoverage: { '@type': 'Place', name: 'Pakistan and South Asia' },
    temporalCoverage: '2016/..',
    distribution: [
      { '@type': 'DataDownload', encodingFormat: 'text/csv', contentUrl: `${SITE.links.apiBase}/exports/station-readings-csv` },
      { '@type': 'DataDownload', encodingFormat: 'application/json', contentUrl: `${SITE.links.apiBase}/openaq/measurements` },
    ],
  }

  return (
    <div className="min-h-screen bg-background">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumbJsonLd([{ name: 'Home', path: '/' }, { name: 'About', path: '/about/' }])) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLd(datasetJsonLd) }} />
      <header className="border-b">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <Link href="/" className="text-2xl font-bold text-foreground">Hawanama</Link>
              <p className="text-sm text-muted-foreground">South Asia Air Quality Monitoring</p>
            </div>
            <nav className="flex items-center space-x-4">
              <Link href="/" className="text-sm hover:underline">Dashboard</Link>
              <Link href="/city/" className="text-sm hover:underline">Cities</Link>
              <Link href="/about/" className="text-sm font-medium">About</Link>
            </nav>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8 max-w-3xl text-foreground leading-relaxed">
        <h1 className="text-3xl font-bold mb-4">About Hawanama</h1>
        <p className="text-muted-foreground mb-6">
          Hawanama (Urdu for “air report”) is the live air quality platform of the{' '}
          <A href={SITE.links.paqi}>Pakistan Air Quality Initiative (PAQI)</A>, a community-driven effort that has
          measured and published Pakistan’s air pollution since 2016. The map shows hourly fine particulate matter
          (PM2.5) and the US Air Quality Index (AQI) for {allStations.length} monitoring stations in {allCities.length}{' '}
          cities across Pakistan, India, Bangladesh, Nepal and Sri Lanka, including {pkStations} monitors in{' '}
          {pkCities} Pakistani cities such as Lahore, Karachi, Islamabad, Peshawar, Faisalabad and Quetta.
        </p>

        <h2 className="text-2xl font-semibold mt-10 mb-3">Where the data comes from</h2>
        <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
          <li>
            <strong className="text-foreground">PAQI monitoring network</strong>: low-cost PM2.5 sensors installed and
            maintained by PAQI and partners, published through IQAir/AirVisual. The same network is archived on{' '}
            <A href={SITE.links.nasaEarthdata}>NASA Earthdata (ASDC)</A>.
          </li>
          <li>
            <strong className="text-foreground">Government reference monitors</strong>: Punjab Environmental Protection
            Agency and Urban Unit beta-attenuation (BAM) monitors where available.
          </li>
          <li>
            <strong className="text-foreground">Regional monitors</strong> in India, Bangladesh, Nepal and Sri Lanka
            published through IQAir, for cross-border context.
          </li>
        </ul>
        <p className="text-muted-foreground mt-4">
          Every hourly value shown is the average of the hour that just ended, labelled in Pakistan Standard Time.
          Readings are ingested every hour, checked for plausibility, and revised when a provider back-fills a
          value; every revision is recorded. The methodology and all ingestion code are public in the{' '}
          <A href={SITE.links.githubRepo}>Hawanama repository</A>.
        </p>

        <h2 className="text-2xl font-semibold mt-10 mb-3">Open data and API</h2>
        <p className="text-muted-foreground">
          Hawanama data is free to use under{' '}
          <A href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</A>; please credit the Pakistan Air
          Quality Initiative. Downloads and endpoints:
        </p>
        <ul className="list-disc pl-6 space-y-2 text-muted-foreground mt-3">
          <li>
            CSV of recent station readings:{' '}
            <A href={`${SITE.links.apiBase}/exports/station-readings-csv`}>{`${SITE.links.apiBase}/exports/station-readings-csv`}</A>
          </li>
          <li>
            CSV of city averages:{' '}
            <A href={`${SITE.links.apiBase}/exports/city-readings-csv`}>{`${SITE.links.apiBase}/exports/city-readings-csv`}</A>
          </li>
          <li>
            OpenAQ-style JSON (locations and measurements):{' '}
            <A href={`${SITE.links.apiBase}/openaq/locations`}>{`${SITE.links.apiBase}/openaq/locations`}</A>
          </li>
          <li>
            Live city list used by this site: <A href={`${SITE.links.apiBase}/cities`}>{`${SITE.links.apiBase}/cities`}</A>
          </li>
        </ul>

        <h2 className="text-2xl font-semibold mt-10 mb-3">Related PAQI research and code</h2>
        <ul className="list-disc pl-6 space-y-2 text-muted-foreground">
          <li>
            <A href={SITE.links.emissions}>PakEmis: Pakistan greenhouse gas and air pollutant emissions inventory</A>{' '}
            (ten sectors, FY2015-16 to FY2023-24), with code and data on{' '}
            <A href={SITE.links.emissionsRepo}>GitHub</A>.
          </li>
          <li>
            <A href={SITE.links.estimationRepo}>Satellite-supported daily PM2.5 mapping for Pakistan</A> under sparse
            monitoring: reproducibility code and model artifacts, archived at{' '}
            <A href={SITE.links.zenodoEstimation}>doi:10.5281/zenodo.20824536</A>. The “Estimated” mode on the map
            comes from this work.
          </li>
          <li>
            <A href={SITE.links.zenodoReport}>Unveiling Pakistan’s Air Pollution</A>: a national landscape report on
            health risks, sources and solutions (2025).
          </li>
          <li>
            All code: <A href={SITE.links.github}>github.com/PakAirQuality</A>. Updates:{' '}
            <A href={SITE.links.twitter}>@pakairquality</A>.
          </li>
        </ul>

        <h2 className="text-2xl font-semibold mt-10 mb-3">How to cite</h2>
        <pre className="whitespace-pre-wrap text-sm bg-muted/40 border rounded p-4 text-muted-foreground">
{`Pakistan Air Quality Initiative (${new Date().getUTCFullYear()}). Hawanama: real-time air quality data for Pakistan and South Asia. https://hawanama.org`}
        </pre>

        <h2 className="text-2xl font-semibold mt-10 mb-3">Credits</h2>
        <p className="text-muted-foreground">
          Hawanama is designed, built and maintained by{' '}
          <A href="https://github.com/RehanAhmad13">Rehan Ahmad</A> (technical lead) for the Pakistan Air Quality
          Initiative, founded by <A href={SITE.links.paqi}>Abid Omar</A>. The satellite PM2.5 estimation behind the
          “Estimated” map mode is by Rehan Ahmad, Mahad Naveed and Abid Omar. Monitors are hosted by PAQI’s community
          of volunteers, schools, businesses and public agencies across Pakistan.
        </p>

        <h2 className="text-2xl font-semibold mt-10 mb-3">Contact</h2>
        <p className="text-muted-foreground">
          Questions, data requests or a monitor to host: reach PAQI through{' '}
          <A href={SITE.links.paqi}>pakairquality.com</A> or open an issue on{' '}
          <A href={SITE.links.githubRepo}>GitHub</A>.
        </p>
      </main>
      <SiteFooter />
    </div>
  )
}
