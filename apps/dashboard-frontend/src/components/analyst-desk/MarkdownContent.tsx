"use client"

import { Fragment, useMemo } from 'react'
import { bandColor } from '@/lib/aqi'
import { emphasiseBlocks } from '@/lib/chat/emphasis'
import { parseMarkdown, type Block, type Inline } from '@/lib/chat/markdown'

interface MarkdownContentProps {
  text: string
  /** The text is still being written: unfinished syntax is tidied so it never shows raw */
  partial?: boolean
  knownCities?: Set<string>
  onCityClick?: (city: string) => void
}

type SpanProps = Pick<MarkdownContentProps, 'knownCities' | 'onCityClick'>

function CityLink({ city, onCityClick }: { city: string; onCityClick: (city: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onCityClick(city)}
      className="font-semibold text-blue-700 hover:underline focus-visible:underline focus-visible:outline-none"
    >
      {city}
    </button>
  )
}

function Spans({ inline, knownCities, onCityClick }: { inline: Inline[] } & SpanProps) {
  return (
    <>
      {inline.map((part, i) => {
        switch (part.type) {
          case 'strong':
            return knownCities?.has(part.text) && onCityClick
              ? <CityLink key={i} city={part.text} onCityClick={onCityClick} />
              : <strong key={i} className="font-semibold text-slate-900">{part.text}</strong>
          case 'city':
            return onCityClick
              ? <CityLink key={i} city={part.text} onCityClick={onCityClick} />
              : <Fragment key={i}>{part.text}</Fragment>
          case 'metric':
            return <strong key={i} className="font-semibold tabular-nums text-slate-900">{part.text}</strong>
          case 'band':
            return (
              <span key={i} className="whitespace-nowrap font-semibold text-slate-900">
                <span aria-hidden className="mr-1 inline-block h-2 w-2 rounded-full align-[0.05em]" style={{ background: bandColor(part.band) }} />
                {part.text}
              </span>
            )
          case 'em':
            return <em key={i} className="italic">{part.text}</em>
          case 'code':
            return <code key={i} className="rounded bg-slate-100 px-1 py-px text-[0.9em] text-slate-800">{part.text}</code>
          case 'link':
            return (
              <a key={i} href={part.href} target="_blank" rel="noopener noreferrer nofollow" className="text-blue-700 underline underline-offset-2 break-words">
                {part.text}
              </a>
            )
          default:
            return <Fragment key={i}>{part.text}</Fragment>
        }
      })}
    </>
  )
}

const HEADING_SIZE = { 1: 'text-base', 2: 'text-[15px]', 3: 'text-sm' }

function BlockView({ block, ...spans }: { block: Block } & SpanProps) {
  switch (block.type) {
    case 'heading':
      return (
        <p role="heading" aria-level={block.level + 3} className={`mt-1 font-semibold tracking-tight text-slate-900 ${HEADING_SIZE[block.level]}`}>
          <Spans inline={block.inline} {...spans} />
        </p>
      )
    case 'list': {
      const Tag = block.ordered ? 'ol' : 'ul'
      return (
        <Tag className={`space-y-1.5 pl-5 marker:text-slate-400 ${block.ordered ? 'list-decimal' : 'list-disc'}`}>
          {block.items.map((item, i) => (
            <li key={i} className={block.depths[i] ? 'list-[circle]' : undefined} style={block.depths[i] ? { marginLeft: block.depths[i] * 16 } : undefined}>
              <Spans inline={item} {...spans} />
            </li>
          ))}
        </Tag>
      )
    }
    case 'quote':
      return (
        <blockquote className="border-l-2 border-slate-300 pl-3 text-slate-600">
          <Spans inline={block.inline} {...spans} />
        </blockquote>
      )
    case 'table':
      return (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white" tabIndex={0} role="region" aria-label="Table">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                {block.header.map((cell, i) => (
                  <th key={i} scope="col" className="whitespace-nowrap border-b border-slate-200 bg-slate-50 px-2.5 py-1.5 text-left font-semibold text-slate-700">
                    <Spans inline={cell} {...spans} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r} className="border-b border-slate-100 last:border-0">
                  {row.map((cell, c) => (
                    <td key={c} className="px-2.5 py-1.5 tabular-nums text-slate-700">
                      <Spans inline={cell} {...spans} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    case 'code':
      return <pre className="overflow-x-auto rounded-lg bg-slate-100 p-2.5 text-[12px] text-slate-800"><code>{block.text}</code></pre>
    case 'rule':
      return <hr className="border-slate-200" />
    default:
      return (
        <p>
          {block.lead && <span className="font-medium text-slate-900"><Spans inline={block.lead} {...spans} /></span>}
          <Spans inline={block.inline} {...spans} />
        </p>
      )
  }
}

export function MarkdownContent({ text, partial = false, ...spans }: MarkdownContentProps) {
  const { knownCities } = spans
  const blocks = useMemo(
    () => emphasiseBlocks(parseMarkdown(text, { partial }), knownCities),
    [text, partial, knownCities],
  )
  return (
    <div className="chat-prose space-y-3">
      {blocks.map((block, i) => <BlockView key={i} block={block} {...spans} />)}
    </div>
  )
}
