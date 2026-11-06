/**
 * Canvas-based wind particle renderer — IQAir-style flowing streamlines.
 *
 * Clears trails on map pan/zoom so particles always align with the map.
 * Ported from web-next/src/components/map/layers/WindParticleLayer.ts
 */

import type mapboxgl from 'mapbox-gl'

export interface WindMetadata {
  width: number
  height: number
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
  u_min: number
  u_max: number
  v_min: number
  v_max: number
  generated_at: string
  attribution: string
}

// Particle counts scale with zoom: base at overview, max at city level
const BASE_PARTICLES_DESKTOP = 2000
const MAX_PARTICLES_DESKTOP = 800
const BASE_PARTICLES_MOBILE = 800
const MAX_PARTICLES_MOBILE = 400
const TRAIL_FADE = 0.985
const SPEED_FACTOR = 0.006
const PARTICLE_RESET_RATE = 0.001
const LINE_WIDTH = 1.4
const LINE_OPACITY = 0.45
// Particles are coloured by wind speed (m/s) on a blue-to-red ramp (matplotlib RdBu_r without its near-white
// middle, which would vanish on the light basemap): blue for calm air, red for strong wind.
const SPEED_BREAKS = [1, 2, 3.5, 5, 7]
const SPEED_COLORS = ['#2166ac', '#4393c3', '#92c5de', '#f4a582', '#d6604d', '#b2182b']
// Zoom range over which particle count scales
const ZOOM_MIN = 3
const ZOOM_MAX = 10

/** Areas where no particles are drawn, as lon/lat polygons (rings), rasterised once to a lookup grid. */
const MASK_DEG = 0.02

class AreaMask {
  private grid: Uint8Array
  constructor(private w: number, private s: number, private cols: number, private rows: number, polys: number[][][][]) {
    const c = document.createElement('canvas')
    c.width = cols; c.height = rows
    const ctx = c.getContext('2d', { willReadFrequently: true })!
    ctx.beginPath()
    for (const poly of polys) for (const ring of poly) {
      ring.forEach(([lon, lat], i) => {
        const x = (lon - w) / MASK_DEG, y = rows - (lat - s) / MASK_DEG
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y)
      })
      ctx.closePath()
    }
    ctx.fillStyle = '#000'
    ctx.fill('evenodd')
    const px = ctx.getImageData(0, 0, cols, rows).data
    this.grid = new Uint8Array(cols * rows)
    for (let i = 0; i < this.grid.length; i++) this.grid[i] = px[i * 4 + 3] > 127 ? 1 : 0
  }

  static from(polys: number[][][][]): AreaMask | null {
    let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity
    for (const poly of polys) for (const [x, y] of poly[0]) { if (x < w) w = x; if (x > e) e = x; if (y < s) s = y; if (y > n) n = y }
    if (!Number.isFinite(w)) return null
    return new AreaMask(w, s, Math.ceil((e - w) / MASK_DEG) + 1, Math.ceil((n - s) / MASK_DEG) + 1, polys)
  }

  has(lon: number, lat: number): boolean {
    const x = Math.floor((lon - this.w) / MASK_DEG), y = this.rows - 1 - Math.floor((lat - this.s) / MASK_DEG)
    return x >= 0 && y >= 0 && x < this.cols && y < this.rows && this.grid[y * this.cols + x] === 1
  }
}

export class WindParticleRenderer {
  private canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private map: mapboxgl.Map
  private meta: WindMetadata
  private maxParticles: number
  private baseParticles: number
  private activeParticles: number

  private uGrid: Float32Array
  private vGrid: Float32Array

  // [currentX, currentY, prevX, prevY] per particle
  private particles: Float32Array
  // Wind speed at each particle's last step, for its colour
  private speeds: Float32Array

  // Visible bounds in normalized grid coords (0–1), updated on move
  private visBounds = { nxMin: 0, nxMax: 1, nyMin: 0, nyMax: 1 }

  private animFrame = 0
  private running = false
  // Where particles are not drawn (Pakistan on the Tracker, which has its own smoke plumes there)
  private mask: AreaMask | null
  private mapMoving = false
  private speedScale = 1

  constructor(map: mapboxgl.Map, windImage: HTMLImageElement, meta: WindMetadata, opts: { excludePolygons?: number[][][][] } = {}) {
    this.map = map
    this.meta = meta
    this.mask = opts.excludePolygons?.length ? AreaMask.from(opts.excludePolygons) : null

    const isMobile = window.innerWidth < 768
    this.baseParticles = isMobile ? BASE_PARTICLES_MOBILE : BASE_PARTICLES_DESKTOP
    this.maxParticles = isMobile ? MAX_PARTICLES_MOBILE : MAX_PARTICLES_DESKTOP
    this.activeParticles = this.baseParticles

    this.canvas = document.createElement('canvas')
    this.canvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;'
    this._resizeCanvas()
    // Insert right after the Mapbox WebGL canvas inside its container.
    // Marker elements are added later in the same container, so they
    // naturally stack on top of this wind canvas in DOM order.
    const mapboxCanvas = map.getCanvas()
    if (mapboxCanvas && mapboxCanvas.parentNode) {
      mapboxCanvas.parentNode.insertBefore(this.canvas, mapboxCanvas.nextSibling)
    } else {
      map.getContainer().prepend(this.canvas)
    }

    this.ctx = this.canvas.getContext('2d')!

    const { u, v } = this._decodeWindImage(windImage, meta)
    this.uGrid = u
    this.vGrid = v

    // Allocate for max particles; activeParticles controls how many we use
    // Room for the most particles any zoom asks for (the overview count can be the larger one)
    const capacity = Math.max(this.maxParticles, this.baseParticles)
    this.particles = new Float32Array(capacity * 4)
    this.speeds = new Float32Array(capacity)
    this._updateVisibleBounds()
    this._updateActiveParticles()
    this._resetAllParticles()

    this._onResize = this._onResize.bind(this)
    this._onMoveStart = this._onMoveStart.bind(this)
    this._onMoveEnd = this._onMoveEnd.bind(this)
    map.on('resize', this._onResize)
    map.on('movestart', this._onMoveStart)
    map.on('moveend', this._onMoveEnd)
  }

  /** Scale active particle count and speed based on current zoom */
  private _updateActiveParticles() {
    const zoom = this.map.getZoom()
    const t = Math.min(Math.max((zoom - ZOOM_MIN) / (ZOOM_MAX - ZOOM_MIN), 0), 1)
    this.activeParticles = Math.round(this.baseParticles + t * (this.maxParticles - this.baseParticles))
    // Scale speed down as zoom increases so particles don't fly at close zoom
    this.speedScale = Math.pow(2, (ZOOM_MIN - zoom) * 0.7)
  }

  /** Cache visible viewport bounds as normalised grid coords (0–1) */
  private _updateVisibleBounds() {
    const bounds = this.map.getBounds()
    if (!bounds) return  // map not sized yet; keep the previous viewport
    const { lon_min, lon_max, lat_min, lat_max } = this.meta
    const lonRange = lon_max - lon_min
    const latRange = lat_max - lat_min

    this.visBounds = {
      nxMin: Math.max((bounds.getWest() - lon_min) / lonRange, 0),
      nxMax: Math.min((bounds.getEast() - lon_min) / lonRange, 1),
      nyMin: Math.max((lat_max - bounds.getNorth()) / latRange, 0),
      nyMax: Math.min((lat_max - bounds.getSouth()) / latRange, 1),
    }
  }

  /** Spawn a particle within the visible viewport bounds, outside the masked area when there is one */
  private _randomVisiblePos(): [number, number] {
    const { nxMin, nxMax, nyMin, nyMax } = this.visBounds
    let pos: [number, number] = [0, 0]
    for (let tries = 0; tries < 6; tries++) {
      pos = [nxMin + Math.random() * (nxMax - nxMin), nyMin + Math.random() * (nyMax - nyMin)]
      if (!this._masked(pos[0], pos[1])) break
    }
    return pos
  }

  /** Is a normalised grid position inside the masked area? */
  private _masked(nx: number, ny: number): boolean {
    if (!this.mask) return false
    const { lon_min, lon_max, lat_min, lat_max } = this.meta
    return this.mask.has(lon_min + nx * (lon_max - lon_min), lat_max - ny * (lat_max - lat_min))
  }

  private _resetAllParticles() {
    for (let i = 0; i < this.particles.length / 4; i++) {
      const [x, y] = this._randomVisiblePos()
      this.particles[i * 4] = x
      this.particles[i * 4 + 1] = y
      this.particles[i * 4 + 2] = x
      this.particles[i * 4 + 3] = y
    }
  }

  private _decodeWindImage(
    img: HTMLImageElement,
    meta: WindMetadata,
  ): { u: Float32Array; v: Float32Array } {
    const c = document.createElement('canvas')
    c.width = meta.width
    c.height = meta.height
    const ctx = c.getContext('2d')!
    ctx.drawImage(img, 0, 0)
    const data = ctx.getImageData(0, 0, meta.width, meta.height).data

    const len = meta.width * meta.height
    const u = new Float32Array(len)
    const v = new Float32Array(len)
    const uRange = meta.u_max - meta.u_min
    const vRange = meta.v_max - meta.v_min

    for (let i = 0; i < len; i++) {
      u[i] = (data[i * 4] / 255) * uRange + meta.u_min
      v[i] = (data[i * 4 + 1] / 255) * vRange + meta.v_min
    }
    return { u, v }
  }

  private _resizeCanvas() {
    const container = this.map.getContainer()
    this.canvas.width = container.offsetWidth
    this.canvas.height = container.offsetHeight
  }

  private _onResize() {
    this._resizeCanvas()
    // Clear stale trails after resize
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
  }

  private _onMoveStart() {
    this.mapMoving = true
    this.canvas.style.opacity = '0'
  }

  private _onMoveEnd() {
    this.mapMoving = false
    this._updateVisibleBounds()
    this._updateActiveParticles()
    // Clear stale trails, reset all particles into visible area
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
    this._resetAllParticles()
    this.canvas.style.opacity = '1'
  }

  private _sampleWind(nx: number, ny: number): [number, number] {
    const { width, height } = this.meta
    const gx = Math.min(Math.max(nx * width, 0), width - 1.001)
    const gy = Math.min(Math.max(ny * height, 0), height - 1.001)

    const x0 = Math.floor(gx)
    const y0 = Math.floor(gy)
    const x1 = Math.min(x0 + 1, width - 1)
    const y1 = Math.min(y0 + 1, height - 1)
    const fx = gx - x0
    const fy = gy - y0

    const i00 = y0 * width + x0
    const i10 = y0 * width + x1
    const i01 = y1 * width + x0
    const i11 = y1 * width + x1

    const w00 = (1 - fx) * (1 - fy)
    const w10 = fx * (1 - fy)
    const w01 = (1 - fx) * fy
    const w11 = fx * fy

    return [
      this.uGrid[i00] * w00 + this.uGrid[i10] * w10 + this.uGrid[i01] * w01 + this.uGrid[i11] * w11,
      this.vGrid[i00] * w00 + this.vGrid[i10] * w10 + this.vGrid[i01] * w01 + this.vGrid[i11] * w11,
    ]
  }

  start() {
    this.running = true
    this._animate()
  }

  stop() {
    this.running = false
    if (this.animFrame) {
      cancelAnimationFrame(this.animFrame)
      this.animFrame = 0
    }
  }

  destroy() {
    this.stop()
    this.map.off('resize', this._onResize)
    this.map.off('movestart', this._onMoveStart)
    this.map.off('moveend', this._onMoveEnd)
    this.canvas.remove()
  }

  private _animate = () => {
    if (!this.running) return
    this._update()
    this._draw()
    this.animFrame = requestAnimationFrame(this._animate)
  }

  private _update() {
    const { lon_min, lon_max, lat_min, lat_max } = this.meta
    const lonRange = lon_max - lon_min
    const latRange = lat_max - lat_min
    const count = this.activeParticles

    for (let i = 0; i < count; i++) {
      const idx = i * 4
      let cx = this.particles[idx]
      let cy = this.particles[idx + 1]

      this.particles[idx + 2] = cx
      this.particles[idx + 3] = cy

      const [u, v] = this._sampleWind(cx, cy)
      this.speeds[i] = Math.hypot(u, v)
      const speed = SPEED_FACTOR * this.speedScale
      cx += (u / lonRange) * speed
      cy -= (v / latRange) * speed

      if (cx < 0 || cx > 1 || cy < 0 || cy > 1 || Math.random() < PARTICLE_RESET_RATE) {
        const [rx, ry] = this._randomVisiblePos()
        this.particles[idx] = rx
        this.particles[idx + 1] = ry
        this.particles[idx + 2] = rx
        this.particles[idx + 3] = ry
      } else {
        this.particles[idx] = cx
        this.particles[idx + 1] = cy
      }
    }
  }

  private _draw() {
    const ctx = this.ctx
    const w = this.canvas.width
    const h = this.canvas.height
    const { lon_min, lon_max, lat_min, lat_max } = this.meta
    const lonRange = lon_max - lon_min
    const latRange = lat_max - lat_min
    const map = this.map

    // Fade previous frame for trails
    ctx.globalCompositeOperation = 'destination-in'
    ctx.globalAlpha = TRAIL_FADE
    ctx.fillStyle = 'black'
    ctx.fillRect(0, 0, w, h)

    // Draw line segments, one path per speed class
    ctx.globalCompositeOperation = 'source-over'
    ctx.globalAlpha = LINE_OPACITY
    ctx.lineWidth = LINE_WIDTH
    ctx.lineCap = 'round'

    const paths = SPEED_COLORS.map(() => new Path2D())
    for (let i = 0; i < this.activeParticles; i++) {
      const idx = i * 4
      const cx = this.particles[idx]
      const cy = this.particles[idx + 1]
      const px = this.particles[idx + 2]
      const py = this.particles[idx + 3]

      if (cx === px && cy === py) continue
      if (this._masked(cx, cy)) continue

      const cLon = lon_min + cx * lonRange
      const cLat = lat_max - cy * latRange
      const pLon = lon_min + px * lonRange
      const pLat = lat_max - py * latRange

      const cp = map.project([cLon, cLat])
      const pp = map.project([pLon, pLat])

      if (
        (cp.x < -20 || cp.x > w + 20 || cp.y < -20 || cp.y > h + 20) &&
        (pp.x < -20 || pp.x > w + 20 || pp.y < -20 || pp.y > h + 20)
      ) continue

      let k = 0
      while (k < SPEED_BREAKS.length && this.speeds[i] >= SPEED_BREAKS[k]) k++
      paths[k].moveTo(pp.x, pp.y)
      paths[k].lineTo(cp.x, cp.y)
    }
    paths.forEach((path, k) => {
      ctx.strokeStyle = SPEED_COLORS[k]
      ctx.stroke(path)
    })
  }
}
