#!/usr/bin/env node
// Pre-build script: fetch all Pakistan station IDs for static page generation

import { writeFileSync, mkdirSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"
const TOKEN = process.env.NEXT_PUBLIC_TASKS_API_SECRET || ""
const OUT_PATH = join(__dirname, '..', 'src', 'data', 'station-ids.json')

async function main() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/stations?country=Pakistan`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    const stations = data.stations || data
    const ids = stations.map((s) => s.id || s.station_id)
    mkdirSync(dirname(OUT_PATH), { recursive: true })
    writeFileSync(OUT_PATH, JSON.stringify(ids))
    console.log(`Wrote ${ids.length} station IDs to ${OUT_PATH}`)
  } catch (e) {
    console.warn(`Failed to fetch stations: ${e.message}. Writing empty array.`)
    mkdirSync(dirname(OUT_PATH), { recursive: true })
    writeFileSync(OUT_PATH, '[]')
  }
}

main()
