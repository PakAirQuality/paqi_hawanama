"use client"

import { useState, useRef, useEffect, useCallback, useMemo, type KeyboardEvent, type UIEvent } from 'react'
import { ArrowDown, ArrowUp, Square } from 'lucide-react'
import { ChatMessage } from './ChatMessage'
import dynamic from 'next/dynamic'
import type { TrayStation, StationTrendInfo } from './AnalystTray'
// Recharts (~100 KB gzip) only loads when a station trend is opened
const StationTrendPanel = dynamic(() => import('./AnalystTray').then(m => m.StationTrendPanel), { ssr: false, loading: () => <div className="p-4 text-xs text-slate-500">Loading chart…</div> })
import type { ChatMessage as ChatMessageType, CopilotAction } from './types'
import { useOptionalSelection } from '@/lib/selection'
import { useQuery } from '@tanstack/react-query'
import { fetchDailyBrief } from '@/components/ops-pipeline/api'
import { streamCopilot, type StreamOutcome } from '@/lib/chat/stream'
import { actionKey } from '@/lib/chat/actions'
import { STARTING_QUESTIONS, followUpQuestions, splitFollowUps } from '@/lib/chat/followUps'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://hawanama-152782825429.asia-south1.run.app"
const DESK_PREFIX = `${API_BASE}/api/v1/ops/analyst-desk`

// COPILOT_MAX_MESSAGE_CHARS on the API; a longer message is rejected there
const MAX_MESSAGE_CHARS = 2000
const COUNTER_FROM_CHARS = 1800
const MAX_INPUT_HEIGHT = 120
const NEAR_BOTTOM_PX = 48

const STATION_CHIPS = [
  "What's the forecast?",
  "Show 24h trend",
  "Compare with neighbors",
  "Why is it elevated?",
]

interface CopilotChatProps {
  selectedDate: string
  /** The day whose published brief opens the chat, when it differs from selectedDate */
  briefDate?: string
  /** `fromClick` is true when the person pressed the action, false when the answer triggered it */
  onAction?: (action: CopilotAction, fromClick: boolean) => void
  stations?: TrayStation[]
  onStreamingChange?: (streaming: boolean) => void
  activeTab?: 'chat' | 'analytics'
  /** Leaving a station trend the assistant opened */
  onCloseTrend?: () => void
}

interface LastRequest {
  endpoint: string
  body: object
  assistantId: string
}

export function CopilotChat({ selectedDate, briefDate = selectedDate, onAction, stations, onStreamingChange, activeTab: externalTab, onCloseTrend }: CopilotChatProps) {
  const [internalTab, setInternalTab] = useState<'chat' | 'analytics'>('chat')
  const activeTab = externalTab ?? internalTab
  // Shared selection: sent with every request so the answer describes what the map shows
  const selection = useOptionalSelection()
  const selectionParts = selection?.describeParts()
  const selectionLine = selection?.describe()
  const setActiveTab = setInternalTab
  const [messages, setMessages] = useState<ChatMessageType[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  // Set once today's allowance is used up: asking again cannot work until it resets
  const [limitReached, setLimitReached] = useState(false)
  // A fresh session per date, with a random id so no two visitors can ever share a server-side conversation
  const [_sessionId] = useState(() => crypto.randomUUID())
  const sessionId = `tracker-${selectedDate}-${_sessionId}`
  // Which date the conversation belongs to
  const [conversationDate, setConversationDate] = useState<string>('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [showStationChips, setShowStationChips] = useState(false)
  const [trendStation, setTrendStation] = useState<StationTrendInfo | null>(null)
  const [showJump, setShowJump] = useState(false)
  // The reply the last request produced: only that one can be retried
  const [retryableId, setRetryableId] = useState<string | null>(null)
  // The reply still appearing on screen; what comes after it waits until it has finished
  const [writingId, setWritingId] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const streamingRef = useRef(false) // read before state updates land, so a double press sends once
  const lastRequestRef = useRef<LastRequest | null>(null)
  const pinnedToBottomRef = useRef(true)
  const lastScrollTopRef = useRef(0)

  // Long-lived callbacks read these, so a stream always sees the latest selection and handlers
  const contextRef = useRef(selection?.toContext())
  contextRef.current = selection?.toContext()
  const onActionRef = useRef(onAction)
  onActionRef.current = onAction
  const onStreamingRef = useRef(onStreamingChange)
  onStreamingRef.current = onStreamingChange

  // Extract unique city names for clickable city detection in chat messages
  const knownCities = useMemo(() => {
    const cities = new Set<string>()
    for (const s of (stations ?? [])) {
      if (s.city) cities.add(s.city)
    }
    return cities
  }, [stations])

  const handleCityClick = useCallback((city: string) => {
    setInput(`@${city} `)
    setShowStationChips(true)
    inputRef.current?.focus()
  }, [])

  // Follow new text, unless the reader has scrolled up to read something earlier
  useEffect(() => {
    if (scrollRef.current && pinnedToBottomRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, activeTab])

  // Text keeps growing after the message state settles, as a reply is written out
  useEffect(() => {
    const el = contentRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      if (scrollRef.current && pinnedToBottomRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [activeTab])

  const handleRevealChange = useCallback((id: string, revealing: boolean) => {
    setWritingId(current => (revealing ? id : current === id ? null : current))
  }, [])

  const handleScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    // Only scrolling up lets go of the bottom: content growing below also leaves a gap for a moment
    const scrolledUp = el.scrollTop < lastScrollTopRef.current
    lastScrollTopRef.current = el.scrollTop
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
    if (nearBottom) pinnedToBottomRef.current = true
    else if (scrolledUp) pinnedToBottomRef.current = false
    setShowJump(!pinnedToBottomRef.current)
  }

  const jumpToLatest = () => {
    pinnedToBottomRef.current = true
    setShowJump(false)
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }

  // Grow the box with what is typed, up to a limit
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_HEIGHT)}px`
  }, [input])

  const applyAction = useCallback((action: CopilotAction, fromClick: boolean) => {
    if (action.type === 'show_station_trend' && action.station_id) {
      setTrendStation({ station_id: action.station_id, station_name: action.station_name || '', hours: action.hours ?? 24 })
      setActiveTab('analytics')
    }
    onActionRef.current?.(action, fromClick)
  }, [setActiveTab])

  const canRunAction = useCallback(() => !!onAction, [onAction])

  const setStreaming = useCallback((streaming: boolean) => {
    streamingRef.current = streaming
    setIsStreaming(streaming)
    onStreamingRef.current?.(streaming)
  }, [])

  const cancelStream = useCallback(() => {
    if (!abortRef.current) return
    abortRef.current.abort()
    abortRef.current = null
    setStreaming(false)
  }, [setStreaming])

  const updateMessage = useCallback((id: string, patch: Partial<ChatMessageType>) => {
    setMessages(prev => prev.map(m => (m.id === id ? { ...m, ...patch } : m)))
  }, [])

  const runRequest = useCallback(async (request: LastRequest) => {
    const { endpoint, body, assistantId } = request
    const controller = new AbortController()
    abortRef.current?.abort()
    abortRef.current = controller
    lastRequestRef.current = request
    setRetryableId(assistantId)
    setStreaming(true)

    const outcome: StreamOutcome = await streamCopilot({
      url: `${DESK_PREFIX}${endpoint}`,
      body,
      signal: controller.signal,
      onText: content => updateMessage(assistantId, { content }),
      onAction: action => {
        applyAction(action, false)
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m
          const actions = m.actions ?? []
          return actions.some(a => actionKey(a) === actionKey(action)) ? m : { ...m, actions: [...actions, action] }
        }))
      },
    })

    // A newer request or a date change took over: this one no longer owns the chat's state
    if (abortRef.current !== controller) return
    abortRef.current = null

    if (outcome.status === 'limit') setLimitReached(true)
    updateMessage(assistantId, {
      streaming: false,
      status: outcome.status,
      notice: outcome.status === 'ok' ? undefined : outcome.status === 'stopped' ? 'Stopped.' : outcome.message,
    })
    setStreaming(false)
  }, [applyAction, setStreaming, updateMessage])

  // Leaving the page ends any answer still arriving, so it stops using the visitor's allowance
  useEffect(() => () => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  // A new conversation per date; it opens with the published brief (filled in below)
  useEffect(() => {
    if (!selectedDate || conversationDate === selectedDate) return
    setConversationDate(selectedDate)
    cancelStream()
    lastRequestRef.current = null
    setRetryableId(null)
    pinnedToBottomRef.current = true
    setMessages([{ id: `brief-${selectedDate}`, role: 'assistant', content: '', streaming: true }])
  }, [selectedDate, conversationDate, cancelStream])

  // The day's cached brief (same query as the summary card), not a live model run; the model
  // only runs when someone asks a question.
  const { data: dailyBrief, isError: dailyBriefError } = useQuery({
    queryKey: ['ops-brief', briefDate],
    queryFn: () => fetchDailyBrief(briefDate),
    enabled: !!briefDate,
    staleTime: Infinity,
    retry: 1,
  })
  useEffect(() => {
    if (!dailyBrief && !dailyBriefError) return
    const content = dailyBrief?.narrative || `No daily brief has been published for ${briefDate} yet. Ask a question below.`
    setMessages(prev => prev.map(m => (m.id === `brief-${selectedDate}` ? { ...m, content, streaming: false } : m)))
  }, [dailyBrief, dailyBriefError, briefDate, selectedDate])

  // Send a message
  const sendMessage = useCallback((text: string) => {
    const message = text.trim()
    if (!message || message.length > MAX_MESSAGE_CHARS || streamingRef.current || limitReached) return

    const assistantId = crypto.randomUUID()
    setMessages(prev => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', content: message },
      { id: assistantId, role: 'assistant', content: '', streaming: true },
    ])
    setInput('')
    setShowStationChips(false)
    setActiveTab('chat')
    pinnedToBottomRef.current = true
    setShowJump(false)

    runRequest({
      endpoint: '/copilot/chat',
      body: { session_id: sessionId, message, date: selectedDate, context: contextRef.current },
      assistantId,
    })
  }, [limitReached, runRequest, selectedDate, sessionId, setActiveTab])

  const retryLast = useCallback(() => {
    const request = lastRequestRef.current
    if (!request || streamingRef.current || limitReached) return
    updateMessage(request.assistantId, { content: '', actions: undefined, notice: undefined, status: undefined, streaming: true })
    pinnedToBottomRef.current = true
    runRequest(request)
  }, [limitReached, runRequest, updateMessage])

  const stopAnswer = () => abortRef.current?.abort()

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
    e.preventDefault()
    sendMessage(input)
  }

  const lastMessage = messages[messages.length - 1]
  const asked = messages.filter(m => m.role === 'user').map(m => m.content)
  const settled = !isStreaming && !writingId && !limitReached && lastMessage?.role === 'assistant' && !lastMessage.streaming
  const answered = settled && (lastMessage.status === undefined || lastMessage.status === 'ok')

  // Opening questions under the brief, then follow-ups after each answer
  const suggestions = !answered ? [] : asked.length === 0
    ? STARTING_QUESTIONS
    : followUpQuestions({ answer: lastMessage.content, asked, cities: knownCities, offered: splitFollowUps(lastMessage.content).questions })

  const canRetry = settled && retryableId === lastMessage?.id &&
    (lastMessage.status === 'error' || lastMessage.status === 'busy' || lastMessage.status === 'unavailable' || lastMessage.status === 'stopped')

  const showingTrend = activeTab === 'analytics' && !!trendStation

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Content area */}
      {!showingTrend ? (
        <div className="relative flex-1 min-h-0">
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            role="log"
            aria-label="Conversation with the assistant"
            aria-busy={isStreaming}
            className="h-full overflow-y-auto px-3 py-3"
          >
            <div ref={contentRef} className="min-h-full">
            {messages.map(msg => (
              <ChatMessage
                key={msg.id}
                message={msg}
                knownCities={knownCities}
                onCityClick={handleCityClick}
                canRunAction={canRunAction}
                onActionClick={action => applyAction(action, true)}
                onRetry={canRetry && msg.id === lastMessage?.id ? retryLast : undefined}
                animate={!msg.id.startsWith('brief-')}
                onRevealChange={handleRevealChange}
              />
            ))}

            {/* Suggested questions */}
            {suggestions.length > 0 && (
              <div className="mt-1 space-y-1.5">
                <p className="text-xs font-medium text-slate-500">
                  {asked.length === 0 ? 'Try asking' : 'Ask next'}
                </p>
                {suggestions.map(q => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => sendMessage(q)}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-[13px] text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            {/* Empty state */}
            {messages.length === 0 && (
              <div className="flex items-center justify-center h-full text-slate-500 text-sm">
                Loading…
              </div>
            )}
            </div>
          </div>

          {showJump && (
            <button
              type="button"
              onClick={jumpToLatest}
              aria-label="Jump to latest message"
              className="absolute bottom-3 left-1/2 -translate-x-1/2 flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-700 shadow-md hover:bg-slate-50 transition-colors"
            >
              <ArrowDown size={15} />
            </button>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-hidden">
          {trendStation && (
            <StationTrendPanel
              station={trendStation}
              onBack={() => { setTrendStation(null); onCloseTrend?.() }}
            />
          )}
        </div>
      )}

      {/* Station suggestion chips */}
      {showStationChips && input.startsWith('@') && !isStreaming && !limitReached && (
        <div className="px-3 py-1.5 border-slate-100 flex flex-wrap gap-1.5">
          {STATION_CHIPS.map(chip => (
            <button
              key={chip}
              type="button"
              onClick={() => sendMessage(input + chip)}
              className="px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      {!showingTrend && (
        <div className="px-3 pb-2 pt-1">
          {selectionParts && !limitReached && (
            <p className="mb-1.5 truncate text-xs text-slate-500" title={`The assistant answers about: ${selectionLine}`}>
              About {selectionParts[0]} · {selectionParts[2].replace(/ PKT$/, '')}
            </p>
          )}
          <form onSubmit={e => { e.preventDefault(); sendMessage(input) }}>
            <div className="flex items-end gap-1.5 rounded-xl border border-slate-300 bg-white p-1.5 focus-within:border-slate-800 focus-within:ring-1 focus-within:ring-slate-800 transition-colors">
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                maxLength={MAX_MESSAGE_CHARS}
                disabled={limitReached}
                aria-label="Message the assistant"
                style={{ outline: 'none' }} // the box around it shows focus; globals.css would add a second ring
                placeholder={limitReached ? 'Daily limit reached' : 'Ask about air quality, forecasts, cities…'}
                className="min-h-8 flex-1 resize-none bg-transparent px-2 py-1 text-base leading-6 text-slate-800 placeholder:text-slate-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 md:text-sm"
              />
              {isStreaming ? (
                // Keyed so React swaps the element: reused, it would turn into the submit button
                // during this click, and the browser would then send whatever is in the box.
                <button
                  key="stop"
                  type="button"
                  onClick={stopAnswer}
                  aria-label="Stop the answer"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-800 text-white hover:bg-slate-700 transition-colors"
                >
                  <Square size={12} fill="currentColor" />
                </button>
              ) : (
                <button
                  key="send"
                  type="submit"
                  disabled={!input.trim() || limitReached}
                  aria-label="Send message"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-800 text-white hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ArrowUp size={16} />
                </button>
              )}
            </div>
          </form>
          <div className="mt-1 flex items-start justify-between gap-2 text-[11px] leading-4 text-slate-500">
            <span>AI-generated. Check key figures against station data.</span>
            {input.length >= COUNTER_FROM_CHARS && (
              <span className="shrink-0 tabular-nums">{input.length}/{MAX_MESSAGE_CHARS}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
