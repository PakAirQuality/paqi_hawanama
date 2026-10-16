// Site-wide constants and build-time lookups used for metadata, structured data and links.

export const SITE = {
  name: 'Hawanama',
  url: 'https://hawanama.org',
  org: 'Pakistan Air Quality Initiative',
  orgShort: 'PAQI',
  description:
    'Hawanama is the Pakistan Air Quality Initiative’s live air quality map: hourly PM2.5 and US AQI from more than 1,200 monitors across Pakistan, India, Bangladesh, Nepal and Sri Lanka, with open data downloads.',
  ogImage: '/og.v1.png',
  twitter: '@pakairquality',
  links: {
    github: 'https://github.com/PakAirQuality',
    githubRepo: 'https://github.com/PakAirQuality/paqi_hawanama',
    estimationRepo: 'https://github.com/PakAirQuality/pak_quality_estimation',
    emissionsRepo: 'https://github.com/PakAirQuality/pakistan-emissions-sectors',
    paqi: 'https://pakairquality.com',
    emissions: 'https://emissions.hawanama.org',
    twitter: 'https://twitter.com/pakairquality',
    zenodoEstimation: 'https://doi.org/10.5281/zenodo.20824536',
    zenodoReport: 'https://doi.org/10.5281/zenodo.17629179',
    nasaEarthdata: 'https://asdc.larc.nasa.gov/project/Low-Cost%20Sensor%20AQ/Low-Cost-Sensors-AQ_PakAirQuality_1',
    openaq: 'https://openaq.org',
    apiBase: 'https://hawanama-152782825429.asia-south1.run.app/api/v1',
  },
} as const

/** "Lahore, Punjab, Pakistan" with missing parts dropped. */
export function placeLabel(parts: Array<string | null | undefined>): string {
  return parts.filter(Boolean).join(', ')
}

export function cityPath(slug: string): string {
  return `/city/${slug}/`
}

export function stationPath(id: string): string {
  return `/station/${id}/`
}

export function absoluteUrl(path: string): string {
  return `${SITE.url}${path.startsWith('/') ? path : `/${path}`}`
}

/** Render a JSON-LD block. Keep it a plain object; React escapes nothing inside dangerouslySetInnerHTML. */
export function jsonLd(data: Record<string, unknown>): string {
  return JSON.stringify(data).replace(/</g, '\\u003c')
}

export const organizationJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  '@id': `${SITE.url}/#organization`,
  name: SITE.org,
  alternateName: SITE.orgShort,
  url: SITE.links.paqi,
  logo: absoluteUrl('/icon-512.png'),
  sameAs: [SITE.links.github, SITE.links.twitter, SITE.links.emissions, SITE.url],
}

export const websiteJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'WebSite',
  '@id': `${SITE.url}/#website`,
  name: SITE.name,
  url: SITE.url,
  description: SITE.description,
  inLanguage: 'en',
  publisher: { '@id': `${SITE.url}/#organization` },
}

export function breadcrumbJsonLd(items: Array<{ name: string; path: string }>) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: item.name,
      item: absoluteUrl(item.path),
    })),
  }
}
