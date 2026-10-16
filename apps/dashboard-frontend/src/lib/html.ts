/**
 * Escaping for the few places that build HTML strings by hand (Mapbox popups).
 *
 * Station, city and feature names come from upstream feeds and GeoJSON files; a name
 * containing markup must render as text, never as DOM. Use `esc()` for every
 * interpolated value inside `setHTML(...)`, or build nodes with `textContent` and
 * `setDOMContent` instead.
 */

const MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

/** Escape a value for use as HTML text or inside a double-quoted attribute. */
export function esc(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value).replace(/[&<>"']/g, (ch) => MAP[ch])
}

/** Format a number with fixed decimals, or a dash when missing; safe to interpolate. */
export function num(value: unknown, decimals = 0, fallback = '–'): string {
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return fallback
  return n.toFixed(decimals)
}
