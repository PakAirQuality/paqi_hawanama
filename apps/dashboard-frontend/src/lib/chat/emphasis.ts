// The copilot mostly writes plain sentences. This adds the emphasis a reader needs, from the text
// itself: figures, air quality categories and city names stand out, and the opening sentence
// (the prompt tells the model to lead with the key finding) reads as the headline.

import { BAND_KEYS } from '@/lib/aqi'
import type { Block, Inline } from './markdown'

type BandKey = (typeof BAND_KEYS)[number]

const METRIC_RE = /\d[\d,]*(?:\.\d+)?\s?(?:µg\/m³|μg\/m³|ug\/m3|m\/s|km\/h|°C|%)|\b(?:US\s)?AQI\s\d+|\b\d+\sAQI\b/g
const BAND_RE = /\b(?:unhealthy for sensitive groups|very unhealthy|hazardous|unhealthy)\b|(?<=\()(?:Good|Moderate)(?=\))/gi
const SENTENCE_END_RE = /[.!?](?=\s+[A-Z0-9*])/

const BAND_BY_TEXT: Record<string, BandKey> = {
  'unhealthy for sensitive groups': 'unhealthy_sensitive',
  'very unhealthy': 'very_unhealthy',
  hazardous: 'hazardous',
  unhealthy: 'unhealthy',
  good: 'good',
  moderate: 'moderate',
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function splitText(parts: Inline[], re: RegExp, make: (match: string) => Inline | null): Inline[] {
  return parts.flatMap(part => {
    if (part.type !== 'text') return [part]
    const out: Inline[] = []
    let last = 0
    for (const m of part.text.matchAll(re)) {
      const token = make(m[0])
      if (!token) continue
      if (m.index > last) out.push({ type: 'text', text: part.text.slice(last, m.index) })
      out.push(token)
      last = m.index + m[0].length
    }
    if (last === 0) return [part]
    if (last < part.text.length) out.push({ type: 'text', text: part.text.slice(last) })
    return out
  })
}

/** Regex matching any of the known cities, longest first so "Rahim Yar Khan" beats "Rahim". */
export function cityPattern(cities: Iterable<string>): RegExp | null {
  const names = [...cities].filter(c => c.length > 2).sort((a, b) => b.length - a.length).map(escapeRe)
  return names.length ? new RegExp(`\\b(?:${names.join('|')})\\b`, 'g') : null
}

function emphasise(parts: Inline[], city: RegExp | null, seen: Set<string>): Inline[] {
  let out = splitText(parts, METRIC_RE, text => ({ type: 'metric', text }))
  out = splitText(out, BAND_RE, text => {
    const band = BAND_BY_TEXT[text.toLowerCase()]
    return band ? { type: 'band', text, band } : null
  })
  if (!city) return out
  // Link a city the first time it appears; every mention in blue would be hard to read
  return splitText(out, city, text => {
    if (seen.has(text)) return null
    seen.add(text)
    return { type: 'city', text }
  })
}

/** Splits an opening paragraph after its first sentence. Answers with their own bold are left alone. */
function splitLead(inline: Inline[]): { lead: Inline[]; rest: Inline[] } | null {
  const [first, ...others] = inline
  if (first?.type !== 'text' || inline.some(p => p.type === 'strong')) return null
  const end = SENTENCE_END_RE.exec(first.text)
  if (!end) return null
  const cut = end.index + 1
  return {
    lead: [{ type: 'text', text: first.text.slice(0, cut) }],
    rest: [{ type: 'text', text: first.text.slice(cut) }, ...others],
  }
}

export function emphasiseBlocks(blocks: Block[], cities: Iterable<string> = []): Block[] {
  const city = cityPattern(cities)
  const seen = new Set<string>()
  const apply = (parts: Inline[]) => emphasise(parts, city, seen)

  return blocks.map((block, i) => {
    switch (block.type) {
      case 'paragraph': {
        const split = i === 0 ? splitLead(block.inline) : null
        return split
          ? { ...block, lead: apply(split.lead), inline: apply(split.rest) }
          : { ...block, inline: apply(block.inline) }
      }
      case 'quote':
      case 'heading':
        return { ...block, inline: apply(block.inline) }
      case 'list':
        return { ...block, items: block.items.map(apply) }
      case 'table':
        return { ...block, header: block.header.map(apply), rows: block.rows.map(r => r.map(apply)) }
      default:
        return block
    }
  })
}
