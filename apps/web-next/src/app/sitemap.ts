import type { MetadataRoute } from 'next'
import { SITE, cityPath, stationPath } from '@/lib/site'
import { allCities, allStations } from '@/lib/siteData'

export const dynamic = 'force-static'

export default function sitemap(): MetadataRoute.Sitemap {
  const built = new Date()
  const entries: MetadataRoute.Sitemap = [
    { url: `${SITE.url}/`, lastModified: built, changeFrequency: 'hourly', priority: 1 },
    { url: `${SITE.url}/city/`, lastModified: built, changeFrequency: 'daily', priority: 0.9 },
    { url: `${SITE.url}/about/`, lastModified: built, changeFrequency: 'monthly', priority: 0.8 },
  ]
  for (const c of allCities) {
    entries.push({
      url: `${SITE.url}${cityPath(c.slug)}`,
      lastModified: built,
      changeFrequency: 'hourly',
      priority: c.country === 'Pakistan' ? 0.8 : 0.6,
    })
  }
  for (const s of allStations) {
    entries.push({
      url: `${SITE.url}${stationPath(s.id)}`,
      lastModified: built,
      changeFrequency: 'hourly',
      priority: s.country === 'Pakistan' ? 0.6 : 0.4,
    })
  }
  return entries
}
