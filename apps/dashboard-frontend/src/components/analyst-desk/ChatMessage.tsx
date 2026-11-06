"use client"

import { useEffect, useState } from 'react'
import { Check, Copy, MapPin, RotateCcw, TrendingUp } from 'lucide-react'
import { actionLabel } from '@/lib/chat/actions'
import { splitFollowUps } from '@/lib/chat/followUps'
import { useTypewriter } from '@/lib/chat/useTypewriter'
import { MarkdownContent } from './MarkdownContent'
import { TrajectoryMiniMap } from './TrajectoryMiniMap'
import type { ChatMessage as ChatMessageType, CopilotAction } from './types'

interface ChatMessageProps {
  message: ChatMessageType
  knownCities?: Set<string>
  onCityClick?: (city: string) => void
  /** Which actions can be run from this page; the rest are not shown */
  canRunAction?: (action: CopilotAction) => boolean
  onActionClick?: (action: CopilotAction) => void
  /** Only given to the newest reply when it failed in a way that retrying can fix */
  onRetry?: () => void
  /** Write the reply out word by word. Off for text that already existed, like the published brief. */
  animate?: boolean
  /** Told when a reply starts and finishes appearing, so what follows it can wait */
  onRevealChange?: (id: string, revealing: boolean) => void
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard blocked: the text can still be selected by hand */ }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? 'Copied' : 'Copy answer'}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 max-md:py-2 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-800 transition-colors"
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function Waiting() {
  return (
    <span role="status" className="inline-flex items-center gap-2 py-0.5 text-[13px] text-slate-500">
      <span className="inline-flex items-center gap-1" aria-hidden>
        {[0, 150, 300].map(delay => (
          <span key={delay} className="h-1.5 w-1.5 rounded-full bg-slate-400 motion-safe:animate-pulse" style={{ animationDelay: `${delay}ms` }} />
        ))}
      </span>
      Checking the data…
    </span>
  )
}

function AssistantMessage({ message, knownCities, onCityClick, canRunAction, onActionClick, onRetry, animate = true, onRevealChange }: ChatMessageProps) {
  const { body } = splitFollowUps(message.content)
  // A reply that arrives live is written out; a saved one appears at once
  const [arrivedLive, setArrivedLive] = useState(!!message.streaming)
  if (message.streaming && !arrivedLive) setArrivedLive(true)
  const { text, typing } = useTypewriter(body, animate && arrivedLive && message.status !== 'stopped')

  const writing = typing || !!message.streaming
  useEffect(() => { onRevealChange?.(message.id, writing) }, [message.id, writing, onRevealChange])

  // The trajectory action is drawn inside the message, never offered as a chip
  const trajectory = (message.actions ?? []).find(a => a.type === 'show_trajectory')
  const actions = (message.actions ?? []).filter(a => a.type !== 'show_trajectory' && canRunAction?.(a))

  return (
    <div className="mb-4">
      <div className="px-1 text-sm leading-6 text-slate-700 break-words">
        {text && (
          <div className={writing ? 'chat-writing' : undefined}>
            <MarkdownContent text={text} partial={writing} knownCities={knownCities} onCityClick={onCityClick} />
          </div>
        )}
        {message.streaming && !text && <Waiting />}

        {trajectory && !writing && <TrajectoryMiniMap action={trajectory} />}

        {message.notice && !typing && (
          <p role="alert" className={`text-slate-600 ${text ? 'mt-2 border-t border-slate-200 pt-2' : ''}`}>
            {message.notice}
          </p>
        )}
      </div>

      {!writing && actions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 px-1">
          {actions.map((action, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onActionClick?.(action)}
              className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-1 max-md:py-2 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
            >
              {action.type === 'show_station_trend' ? <TrendingUp size={13} /> : <MapPin size={13} />}
              {actionLabel(action)}
            </button>
          ))}
        </div>
      )}

      {!writing && (onRetry || body) && (
        <div className="mt-1 flex items-center gap-1">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 transition-colors"
            >
              <RotateCcw size={13} />
              Try again
            </button>
          )}
          {body && <CopyButton text={body} />}
        </div>
      )}
    </div>
  )
}

export function ChatMessage(props: ChatMessageProps) {
  const { message } = props
  if (message.role === 'assistant') return <AssistantMessage {...props} />

  return (
    <div className="flex justify-end mb-4">
      <div className="max-w-[88%] rounded-2xl rounded-br-md bg-slate-800 px-3.5 py-2 text-sm leading-6 text-white whitespace-pre-wrap break-words">
        {message.content}
      </div>
    </div>
  )
}
