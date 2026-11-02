import { describe, expect, it } from 'vitest'
import { closePartial, parseInline, parseMarkdown, safeHref } from './markdown'

describe('safeHref', () => {
  it('allows web links', () => {
    expect(safeHref('https://hawanama.org/about')).toBe('https://hawanama.org/about')
  })

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    '//evil.example/x',
    '/relative/path',
  ])('refuses %s', href => {
    expect(safeHref(href)).toBeNull()
  })
})

describe('parseInline', () => {
  it('reads bold, italics, code and links', () => {
    expect(parseInline('**Lahore** is *bad*, see `pm25` and [map](https://hawanama.org)')).toEqual([
      { type: 'strong', text: 'Lahore' },
      { type: 'text', text: ' is ' },
      { type: 'em', text: 'bad' },
      { type: 'text', text: ', see ' },
      { type: 'code', text: 'pm25' },
      { type: 'text', text: ' and ' },
      { type: 'link', text: 'map', href: 'https://hawanama.org/' },
    ])
  })

  it('turns an unsafe link into plain text', () => {
    expect(parseInline('[click](javascript:alert(1))').every(p => p.type !== 'link')).toBe(true)
  })

  it('leaves underscores inside identifiers alone', () => {
    expect(parseInline('sensor_id_42 and pm2_5')).toEqual([{ type: 'text', text: 'sensor_id_42 and pm2_5' }])
  })

  it('leaves half-finished bold as text while it streams in', () => {
    expect(parseInline('**Lah')).toEqual([{ type: 'text', text: '**Lah' }])
  })

  it('does not hang on pathological input', () => {
    const started = Date.now()
    parseInline('*'.repeat(20_000) + '_'.repeat(20_000) + '['.repeat(20_000))
    expect(Date.now() - started).toBeLessThan(1000)
  })
})

describe('closePartial', () => {
  it.each([
    ['open bold', 'The worst was **Lah', 'The worst was **Lah**'],
    ['open italics', 'Note *this', 'Note *this*'],
    ['open code', 'See `pm2', 'See `pm2`'],
    ['stray stars at the end', 'Worst was **', 'Worst was '],
    ['a link still arriving', 'See [the map](https://haw', 'See '],
    ['finished bold', 'Done **now** ok', 'Done **now** ok'],
  ])('tidies %s', (_, input, expected) => {
    expect(closePartial(input)).toBe(expected)
  })

  it.each([
    ['a bare bullet', 'Intro\n- '],
    ['a bare number', 'Intro\n2. '],
    ['a bare heading', 'Intro\n## '],
    ['a table row still arriving', 'Intro\n| Lahore | 2'],
    ['a code fence opening', 'Intro\n```'],
  ])('holds back %s', (_, input) => {
    expect(closePartial(input)).toBe('Intro')
  })

  it('never shows raw markers at any point while an answer is written', () => {
    const answer = '**Punjab** is worst.\n\n### Cities\n\n- **Lahore**: 270\n\n| City | PM2.5 |\n|---|---|\n| Lahore | 221 |\n\nDone `now`.'
    const raw = (i: number) => JSON.stringify(parseMarkdown(answer.slice(0, i), { partial: true }))
    for (let i = 1; i <= answer.length; i++) expect(raw(i), `at ${i}`).not.toMatch(/\*\*|###|\|---|`/)
  })
})

describe('parseMarkdown', () => {
  it('reads block quotes', () => {
    expect(parseMarkdown('> Stay indoors\n> today')).toEqual([{ type: 'quote', inline: [{ type: 'text', text: 'Stay indoors today' }] }])
  })

  it('keeps sub-points under their list item', () => {
    const [list] = parseMarkdown('1. Lahore\n   - Very high\n2. Kasur')
    expect(list).toMatchObject({ type: 'list', ordered: true, depths: [0, 1, 0] })
  })

  it('reads the mix of blocks the assistant writes', () => {
    const blocks = parseMarkdown('### Worst cities\n\n- **Lahore**: 270\n- Kasur: 247\n\n1. First\n2. Second\n\nDone.')
    expect(blocks.map(b => b.type)).toEqual(['heading', 'list', 'list', 'paragraph'])
    expect(blocks[0]).toMatchObject({ level: 3 })
    expect(blocks[1]).toMatchObject({ ordered: false })
    expect(blocks[2]).toMatchObject({ ordered: true })
  })

  it('reads a table and evens out short rows', () => {
    const [table] = parseMarkdown('| City | PM2.5 |\n|---|---|\n| Lahore | 221 |\n| Kasur |')
    expect(table).toMatchObject({ type: 'table' })
    if (table.type !== 'table') throw new Error('expected a table')
    expect(table.header).toHaveLength(2)
    expect(table.rows).toHaveLength(2)
    expect(table.rows[1]).toHaveLength(2)
    expect(table.rows[1][1]).toEqual([])
  })

  it('does not mistake a line with a pipe for a table', () => {
    expect(parseMarkdown('Lahore | Kasur\nnext line').map(b => b.type)).toEqual(['paragraph'])
  })

  it('joins wrapped lines into one paragraph', () => {
    expect(parseMarkdown('one\ntwo')).toEqual([{ type: 'paragraph', inline: [{ type: 'text', text: 'one two' }] }])
  })

  it('keeps fenced code exactly as written', () => {
    expect(parseMarkdown('```\n**not bold**\n```')).toEqual([{ type: 'code', text: '**not bold**' }])
  })

  it('copes with a fence that has not closed yet', () => {
    expect(parseMarkdown('```\nstill coming')).toEqual([{ type: 'code', text: 'still coming' }])
  })

  it('caps very long input', () => {
    expect(() => parseMarkdown('word '.repeat(200_000))).not.toThrow()
  })

  it('returns nothing for blank text', () => {
    expect(parseMarkdown('  \n \n')).toEqual([])
  })
})
