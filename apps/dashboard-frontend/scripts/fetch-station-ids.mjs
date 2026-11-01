#!/usr/bin/env node
// Pre-build script: fetch all Pakistan station IDs for static page generation

import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"
// /api/v1/stations is public; no credential is needed or sent.
const TOKEN = ""
const OUT_PATH = join(__dirname, '..', 'src', 'data', 'station-ids.json')
const BOUNDARY_PATH = join(__dirname, '..', 'public', 'PAK_adm0.json')

function pointInRing(lng, lat, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

async function main() {
  try {
    const geom = JSON.parse(readFileSync(BOUNDARY_PATH, 'utf8')).features[0].geometry
    const polygons = geom.type === 'MultiPolygon' ? geom.coordinates : [geom.coordinates]
    const insidePakistan = (lng, lat) =>
      polygons.some((p) => pointInRing(lng, lat, p[0]) && !p.slice(1).some((h) => pointInRing(lng, lat, h)))

    const res = await fetch(`${API_BASE}/api/v1/stations?country=Pakistan`, {
      headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    // The API does not apply ?country=, so the boundary decides.
    const stations = (data.stations || data).filter((s) => insidePakistan(s.longitude, s.latitude))
    const ids = stations.map((s) => s.id || s.station_id)
    if (ids.length === 0) throw new Error('API returned no stations')
    mkdirSync(dirname(OUT_PATH), { recursive: true })
    writeFileSync(OUT_PATH, JSON.stringify(ids))
    console.log(`Wrote ${ids.length} station IDs to ${OUT_PATH}`)
  } catch (e) {
    // An empty list would publish a build with no station pages.
    if (existsSync(OUT_PATH) && JSON.parse(readFileSync(OUT_PATH, 'utf8')).length > 0) {
      console.warn(`Failed to fetch stations: ${e.message}. Keeping the committed list.`)
      return
    }
    console.error(`Failed to fetch stations: ${e.message}. No committed list to fall back on.`)
    process.exit(1)
  }
}

main()
