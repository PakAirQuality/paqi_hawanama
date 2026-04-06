/**
 * Enriches brick_kilns.geojson with district names from pakistan_districts.geojson
 * using point-in-polygon ray-casting. Writes enriched file to public/brick_kilns.geojson.
 */
import { readFileSync, writeFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const publicDir = resolve(__dirname, '../public')

// Ray-casting point-in-polygon
function pointInPolygon(point, polygon) {
  const [x, y] = point
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i]
    const [xj, yj] = polygon[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside
    }
  }
  return inside
}

function pointInFeature(point, feature) {
  const geom = feature.geometry
  if (geom.type === 'Polygon') {
    return pointInPolygon(point, geom.coordinates[0])
  }
  if (geom.type === 'MultiPolygon') {
    return geom.coordinates.some(poly => pointInPolygon(point, poly[0]))
  }
  return false
}

// Load data
const districts = JSON.parse(readFileSync(resolve(publicDir, 'pakistan_districts.geojson'), 'utf-8'))
const kilns = JSON.parse(readFileSync(resolve(publicDir, 'brick_kilns.geojson'), 'utf-8'))

console.log(`Enriching ${kilns.features.length} kilns with ${districts.features.length} districts...`)

// Build bounding boxes for quick rejection
const districtBboxes = districts.features.map(f => {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const coords = f.geometry.type === 'MultiPolygon'
    ? f.geometry.coordinates.flat(1)
    : f.geometry.coordinates
  for (const ring of coords) {
    for (const [x, y] of ring) {
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    }
  }
  return { feature: f, minX, minY, maxX, maxY, name: f.properties.shapeName }
})

let matched = 0
for (const f of kilns.features) {
  const [lon, lat] = f.geometry.coordinates
  const point = [lon, lat]
  let found = false
  for (const d of districtBboxes) {
    if (lon < d.minX || lon > d.maxX || lat < d.minY || lat > d.maxY) continue
    if (pointInFeature(point, d.feature)) {
      f.properties.district = d.name
      matched++
      found = true
      break
    }
  }
  if (!found) {
    f.properties.district = ''
  }
}

console.log(`Matched ${matched}/${kilns.features.length} kilns to districts`)

writeFileSync(resolve(publicDir, 'brick_kilns.geojson'), JSON.stringify(kilns))
console.log('Written enriched brick_kilns.geojson')
