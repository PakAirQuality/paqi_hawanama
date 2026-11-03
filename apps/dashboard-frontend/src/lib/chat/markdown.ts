// A small Markdown reader for copilot answers. It produces plain data that React renders as text,
// so HTML in an answer is shown literally and can never run. Answers stream in, so half-finished
// syntax simply stays as text until the rest arrives.

import type { BAND_KEYS } from '@/lib/aqi'

type BandKey = (typeof BAND_KEYS)[number]

export type Inline =
  | { type: 'text'; text: string }
  | { type: 'strong'; text: string }
  | { type: 'em'; text: string }
  | { type: 'code'; text: string }
  | { type: 'link'; text: string; href: string }
  // Added by emphasis.ts, never parsed from the text
  | { type: 'metric'; text: string }
  | { type: 'band'; text: string; band: BandKey }
  | { type: 'city'; text: string }

export type Block =
  | { type: 'paragraph'; inline: Inline[]; lead?: Inline[] }
  | { type: 'heading'; level: 1 | 2 | 3; inline: Inline[] }
  | { type: 'list'; ordered: boolean; items: Inline[][]; depths: number[] }
  | { type: 'quote'; inline: Inline[] }
  | { type: 'table'; header: Inline[][]; rows: Inline[][][] }
  | { type: 'code'; text: string }
  | { type: 'rule' }

const MAX_INPUT = 20_000 // a reply is capped at 1024 tokens, so this only guards against garbage

const INLINE_RE = /\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]{1,300})\]\(([^)\s]{1,2000})\)|(?<![*\w])\*([^*\n]+)\*(?!\*)|(?<![\w_])_([^_\n]+)_(?![\w_])/g
const HEADING_RE = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/
const BULLET_RE = /^\s*[-*+•]\s+(.*)$/
const NUMBERED_RE = /^\s*\d{1,3}[.)]\s+(.*)$/
const QUOTE_RE = /^\s{0,3}>\s?(.*)$/
const BARE_MARKER_RE = /^\s*(?:#{1,6}|[-*+•>]|\d{1,3}[.)])\s*$/
const RULE_RE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/
const FENCE_RE = /^\s*```/
const TABLE_DIVIDER_RE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/

/** Only web links are allowed: javascript:, data: and the like stay as plain text. */
export function safeHref(href: string): string | null {
  try {
    const url = new URL(href)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

export function parseInline(line: string): Inline[] {
  const out: Inline[] = []
  let last = 0
  for (const m of line.matchAll(INLINE_RE)) {
    const start = m.index
    if (start > last) out.push({ type: 'text', text: line.slice(last, start) })
    last = start + m[0].length
    if (m[1] !== undefined) out.push({ type: 'strong', text: m[1] })
    else if (m[2] !== undefined) out.push({ type: 'code', text: m[2] })
    else if (m[3] !== undefined) {
      const href = safeHref(m[4])
      out.push(href ? { type: 'link', text: m[3], href } : { type: 'text', text: m[3] })
    } else out.push({ type: 'em', text: (m[5] ?? m[6]) as string })
  }
  if (last < line.length) out.push({ type: 'text', text: line.slice(last) })
  return out
}

function splitRow(line: string): string[] {
  const cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|')
  return cells.map(c => c.trim())
}

const isRow = (line: string | undefined) => line !== undefined && line.includes('|') && line.trim().length > 0

const count = (text: string, re: RegExp) => text.match(re)?.length ?? 0

/** A lone table row has no divider yet, so it would show as text full of pipes. */
function dropOpenTable(text: string): string {
  const lines = text.split('\n')
  const last = lines.length - 1
  const isRow = (line: string | undefined) => line?.trimStart().startsWith('|') ?? false
  return isRow(lines[last]) && !isRow(lines[last - 1]) ? lines.slice(0, last).join('\n').trimEnd() : text
}

/** Makes text cut off mid-write presentable: closes open bold and code, and holds back a line
 * that is only the start of a list item, heading or table row until the rest of it exists. */
export function closePartial(source: string): string {
  const cut = source.lastIndexOf('\n') + 1
  const head = source.slice(0, cut)
  let line = source.slice(cut)
  if (!line || BARE_MARKER_RE.test(line) || line.trimStart().startsWith('|') || /^\s*```/.test(line)) return dropOpenTable(head.trimEnd())

  line = line.replace(/(\*{1,2}|`|\[[^\]]*\]?\(?[^)]*)$/, match => (match.startsWith('[') || /^\*+$/.test(match) ? '' : match))
  if (line.endsWith('`') && count(line, /`/g) % 2) line = line.slice(0, -1) // an opening mark with nothing after it yet
  if (count(line, /\*\*/g) % 2) line += '**'
  if (count(line.replace(/\*\*/g, ''), /\*/g) % 2) line += '*'
  if (count(line, /`/g) % 2) line += '`'
  return head + line
}

export function parseMarkdown(text: string, { partial = false }: { partial?: boolean } = {}): Block[] {
  const source = partial ? closePartial(text) : text
  const lines = source.slice(0, MAX_INPUT).split(/\r?\n/)
  const blocks: Block[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }

    if (FENCE_RE.test(line)) {
      const body: string[] = []
      i++
      while (i < lines.length && !FENCE_RE.test(lines[i])) body.push(lines[i++])
      i++
      blocks.push({ type: 'code', text: body.join('\n') })
      continue
    }

    if (isRow(line) && TABLE_DIVIDER_RE.test(lines[i + 1] ?? '') && (lines[i + 1] ?? '').includes('-')) {
      const header = splitRow(line)
      i += 2
      const rows: Inline[][][] = []
      while (isRow(lines[i])) {
        const cells = splitRow(lines[i])
        rows.push(header.map((_, c) => parseInline(cells[c] ?? '')))
        i++
      }
      blocks.push({ type: 'table', header: header.map(parseInline), rows })
      continue
    }

    const heading = HEADING_RE.exec(line)
    if (heading) {
      blocks.push({ type: 'heading', level: Math.min(heading[1].length, 3) as 1 | 2 | 3, inline: parseInline(heading[2]) })
      i++
      continue
    }

    if (RULE_RE.test(line)) {
      blocks.push({ type: 'rule' })
      i++
      continue
    }

    const ordered = NUMBERED_RE.test(line)
    if (ordered || BULLET_RE.test(line)) {
      const re = ordered ? NUMBERED_RE : BULLET_RE
      const items: Inline[][] = []
      const depths: number[] = []
      while (i < lines.length) {
        const indent = /^\s*/.exec(lines[i])?.[0].length ?? 0
        const item = re.exec(lines[i]) ?? (indent >= 2 ? BULLET_RE.exec(lines[i]) ?? NUMBERED_RE.exec(lines[i]) : null)
        if (!item) break
        items.push(parseInline(item[1]))
        depths.push(Math.min(Math.floor(indent / 2), 2))
        i++
      }
      blocks.push({ type: 'list', ordered, items, depths })
      continue
    }

    if (QUOTE_RE.test(line)) {
      const quoted: string[] = []
      while (i < lines.length) {
        const q = QUOTE_RE.exec(lines[i])
        if (!q) break
        quoted.push(q[1].trim())
        i++
      }
      blocks.push({ type: 'quote', inline: parseInline(quoted.join(' ')) })
      continue
    }

    const para: string[] = []
    while (
      i < lines.length && lines[i].trim() &&
      !FENCE_RE.test(lines[i]) && !HEADING_RE.test(lines[i]) && !RULE_RE.test(lines[i]) &&
      !BULLET_RE.test(lines[i]) && !NUMBERED_RE.test(lines[i]) && !QUOTE_RE.test(lines[i])
    ) para.push(lines[i++].trim())
    blocks.push({ type: 'paragraph', inline: parseInline(para.join(' ')) })
  }

  return blocks
}
