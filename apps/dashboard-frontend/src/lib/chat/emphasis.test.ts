import { describe, expect, it } from 'vitest'
import { cityPattern, emphasiseBlocks } from './emphasis'
import { parseMarkdown, type Block, type Inline } from './markdown'

const run = (text: string, cities: string[] = []) => emphasiseBlocks(parseMarkdown(text), cities)
const inlineOf = (block: Block): Inline[] => (block.type === 'paragraph' ? [...(block.lead ?? []), ...block.inline] : [])
const ofType = (blocks: Block[], type: Inline['type']) => blocks.flatMap(inlineOf).filter(p => p.type === type).map(p => ('text' in p ? p.text : ''))

describe('emphasiseBlocks', () => {
  it('picks out figures with units', () => {
    const blocks = run('PM2.5 reached 492 µg/m³ with winds of 0.8 m/s, up 34%. AQI 270 today, or 1,204 μg/m³ at worst.')
    expect(ofType(blocks, 'metric')).toEqual(['492 µg/m³', '0.8 m/s', '34%', 'AQI 270', '1,204 μg/m³'])
  })

  it('leaves bare numbers and dates alone', () => {
    expect(ofType(run('On 2026-10-31, 213 stations reported across 53 cities.'), 'metric')).toEqual([])
  })

  it('marks air quality categories and keeps the wording as written', () => {
    const blocks = run('Hazardous here, very unhealthy there, and Unhealthy for Sensitive Groups elsewhere.')
    const bands = blocks.flatMap(inlineOf).filter((p): p is Extract<Inline, { type: 'band' }> => p.type === 'band')
    expect(bands.map(b => [b.text, b.band])).toEqual([
      ['Hazardous', 'hazardous'],
      ['very unhealthy', 'very_unhealthy'],
      ['Unhealthy for Sensitive Groups', 'unhealthy_sensitive'],
    ])
  })

  it('treats Good and Moderate as categories only when labelled, not as ordinary words', () => {
    expect(ofType(run('Good news: a Moderate rise.'), 'band')).toEqual([])
    expect(ofType(run('Quetta: 30 µg/m³ (Moderate)'), 'band')).toEqual(['Moderate'])
  })

  it('links each city once and matches whole names', () => {
    const blocks = run('Lahore was worse than Lahorewala, and Lahore stayed high.', ['Lahore'])
    expect(ofType(blocks, 'city')).toEqual(['Lahore'])
  })

  it('prefers the longest city name', () => {
    expect(ofType(run('Rahim Yar Khan was high.', ['Rahim', 'Rahim Yar Khan']), 'city')).toEqual(['Rahim Yar Khan'])
  })

  it('copes with city names that contain regex characters', () => {
    expect(() => cityPattern(['Chak (Jhumra)', 'A+B'])).not.toThrow()
    expect(cityPattern(['Ab'])).toBeNull()
  })

  it('makes the opening sentence the lead, without tripping on decimals', () => {
    const [block] = run('Winds of 0.8 m/s trapped smoke. It stayed all day.')
    if (block.type !== 'paragraph') throw new Error('expected a paragraph')
    expect(block.lead?.map(p => ('text' in p ? p.text : '')).join('')).toBe('Winds of 0.8 m/s trapped smoke.')
  })

  it('adds no lead to a one-sentence answer or one with its own bold', () => {
    expect(run('Just one sentence here.')[0]).not.toHaveProperty('lead')
    expect(run('**Key point.** Then detail. And more.')[0]).not.toHaveProperty('lead')
  })

  it('does not touch code', () => {
    expect(run('```\n34% of Lahore\n```', ['Lahore'])).toEqual([{ type: 'code', text: '34% of Lahore' }])
  })

  it('reaches lists and tables', () => {
    const [list, table] = run('- Lahore: 221 µg/m³\n\n| City |\n|---|\n| Kasur |', ['Lahore', 'Kasur'])
    expect(JSON.stringify(list)).toContain('"metric"')
    expect(JSON.stringify(table)).toContain('"city"')
  })
})
