import { describe, expect, it } from 'vitest'
import { AQI_BANDS } from './aqi'

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('AQI_BANDS', () => {
  it.each(AQI_BANDS.map(b => [b.label, b] as const))('%s text is readable on its colour', (_, band) => {
    expect(contrast(band.color, band.textColor)).toBeGreaterThanOrEqual(4.5)
  })

  it('gives every category its own colour', () => {
    expect(new Set(AQI_BANDS.map(b => b.color)).size).toBe(AQI_BANDS.length)
  })
})
