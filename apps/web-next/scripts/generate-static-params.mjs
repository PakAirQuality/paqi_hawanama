// Build-time data for static routes and SEO metadata.
//
// Writes, under src/static/:
//   citySlugs.json  - unique city slugs (generateStaticParams for /city/[slug])
//   stationIds.json - station hash ids (generateStaticParams for /station/[id]);
//                     the union of the live map list and the previously committed list,
//                     so existing station URLs never disappear
//   cities.json     - slug, name, state, country, station_count, lat, lon (centroid of its stations)
//   stations.json   - id, name, city, state, country, lat, lon
//
// Runs as `prebuild`. If the API cannot be reached the committed files are kept and the
// build continues (exit 0), so an API outage never breaks a deploy.

import fs from 'fs/promises'
import path from 'path'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://hawanama-152782825429.asia-south1.run.app'
const STATIC_DIR = path.join(process.cwd(), 'src', 'static')

async function getJson(url) {
  const res = await fetch(url, { signal: AbortSignal.timeout(60_000) })
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`)
  return res.json()
}

async function readExisting(file) {
  try {
    return JSON.parse(await fs.readFile(path.join(STATIC_DIR, file), 'utf8'))
  } catch {
    return null
  }
}

function round(n) {
  return typeof n === 'number' && Number.isFinite(n) ? Math.round(n * 1e5) / 1e5 : null
}

async function main() {
  await fs.mkdir(STATIC_DIR, { recursive: true })
  const existingIds = (await readExisting('stationIds.json')) || []

  let citiesRaw, stationsRaw
  try {
    ;[citiesRaw, stationsRaw] = await Promise.all([
      getJson(`${API_BASE}/api/v1/cities`),
      getJson(`${API_BASE}/api/v1/dashboard/stations`),
    ])
  } catch (err) {
    const haveFiles = (await readExisting('cities.json')) && (await readExisting('stations.json'))
    console.warn(`⚠️  generate-static-params: API unavailable (${err.message}).`)
    if (haveFiles) {
      console.warn('   Keeping the committed src/static/*.json files.')
      return
    }
    console.error('   No committed static data to fall back on.')
    process.exit(1)
  }

  const cityList = citiesRaw.cities || citiesRaw || []
  const stationList = stationsRaw.stations || stationsRaw || []
  if (cityList.length < 50 || stationList.length < 100) {
    console.warn(`⚠️  Suspiciously small API response (cities=${cityList.length}, stations=${stationList.length}); keeping committed files.`)
    return
  }

  // Stations first, so city centroids can be derived from them.
  const stations = []
  const seenStation = new Set()
  for (const s of stationList) {
    if (!s.id || seenStation.has(s.id)) continue
    seenStation.add(s.id)
    stations.push({
      id: s.id,
      name: s.name || `Station ${s.id}`,
      city: s.city || null,
      lat: round(s.latitude),
      lon: round(s.longitude),
    })
  }

  const byCityName = new Map()
  for (const s of stations) {
    if (!s.city || s.lat == null || s.lon == null) continue
    const acc = byCityName.get(s.city) || { lat: 0, lon: 0, n: 0 }
    acc.lat += s.lat
    acc.lon += s.lon
    acc.n += 1
    byCityName.set(s.city, acc)
  }

  const cities = []
  const seenSlug = new Set()
  let duplicates = 0
  for (const c of cityList) {
    if (!c.slug || !c.name) continue
    if (seenSlug.has(c.slug)) {
      duplicates += 1
      continue
    }
    seenSlug.add(c.slug)
    const cen = byCityName.get(c.name)
    cities.push({
      slug: c.slug,
      name: c.name,
      state: c.state || null,
      country: c.country || null,
      station_count: c.station_count ?? 0,
      lat: cen ? round(cen.lat / cen.n) : null,
      lon: cen ? round(cen.lon / cen.n) : null,
    })
  }
  cities.sort((a, b) => (a.country || '').localeCompare(b.country || '') || (a.state || '').localeCompare(b.state || '') || a.name.localeCompare(b.name))

  // Attach state/country to stations through the city name (first match wins).
  const cityByName = new Map()
  for (const c of cities) if (!cityByName.has(c.name)) cityByName.set(c.name, c)
  for (const s of stations) {
    const c = s.city ? cityByName.get(s.city) : null
    s.state = c?.state ?? null
    s.country = c?.country ?? null
    s.city_slug = c?.slug ?? null
  }
  stations.sort((a, b) => a.name.localeCompare(b.name))

  // Keep metadata for stations that are not in this hour's live feed (they may have dropped
  // out temporarily); only brand-new ids are appended, and nothing is ever removed here.
  const existingStations = (await readExisting('stations.json')) || []
  const freshIds = new Set(stations.map((s) => s.id))
  for (const s of existingStations) {
    if (!freshIds.has(s.id)) stations.push(s)
  }
  stations.sort((a, b) => a.name.localeCompare(b.name))
  const stationIds = Array.from(new Set([...stations.map((s) => s.id), ...existingIds])).sort()
  const citySlugs = cities.map((c) => c.slug)

  const write = async (file, data) => {
    await fs.writeFile(path.join(STATIC_DIR, file), JSON.stringify(data, null, 2) + '\n')
    console.log(`✅ ${file}: ${Array.isArray(data) ? data.length : 'ok'}`)
  }
  await write('citySlugs.json', citySlugs)
  await write('stationIds.json', stationIds)
  await write('cities.json', cities)
  await write('stations.json', stations)

  console.log(`ℹ️  ${duplicates} duplicate city slug(s) skipped; ${stationIds.length - stations.length} station id(s) kept from the previous list.`)
}

main().catch((err) => {
  console.error('❌ generate-static-params failed:', err)
  process.exit(1)
})
