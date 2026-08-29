"use client"

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { ChatMessage } from './ChatMessage'
import { AnalystPanel, StationTrendPanel, type TrayStation, type StationTrendInfo } from './AnalystTray'
import type { ChatMessage as ChatMessageType, CopilotAction, StationMention } from './types'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://hawanama-152782825429.asia-south1.run.app"
const API_TOKEN = process.env.NEXT_PUBLIC_TASKS_API_SECRET || ""
const DESK_PREFIX = `${API_BASE}/api/v1/ops/analyst-desk`

const ACTION_RE = /\{\{ACTION:(\{.*?\})\}\}/g

const SUGGESTED_QUESTIONS = [
  "What are the most polluted cities today?",
  "Show me all ramp events",
  "How is Lahore looking for the next 3 days?",
  "Which stations should I prioritize?",
]

const STATION_CHIPS = [
  "What's the forecast?",
  "Show 24h trend",
  "Compare with neighbors",
  "Why is it elevated?",
]

interface CopilotChatProps {
  selectedDate: string
  onAction?: (action: CopilotAction) => void
  stationMention?: StationMention | null
  cityMention?: string | null
  onMentionConsumed?: () => void
  stations?: TrayStation[]
  onStreamingChange?: (streaming: boolean) => void
  activeTab?: 'chat' | 'analytics'
}

export function CopilotChat({ selectedDate, onAction, stationMention, cityMention, onMentionConsumed, stations, onStreamingChange, activeTab: externalTab }: CopilotChatProps) {
  const [internalTab, setInternalTab] = useState<'chat' | 'analytics'>('chat')
  const activeTab = externalTab ?? internalTab
  const setActiveTab = setInternalTab
  const [messages, setMessages] = useState<ChatMessageType[]>(() => {
    // Restore cached briefing from today if available
    if (typeof window !== 'undefined') {
      const lastBriefDate = localStorage.getItem('analyst_briefing_date')
      const today = new Date().toISOString().slice(0, 10)
      if (lastBriefDate === today) {
        try {
          const cached = localStorage.getItem('analyst_briefing_messages')
          if (cached) return JSON.parse(cached)
        } catch { /* ignore parse errors */ }
      }
    }
    return []
  })
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId] = useState(() => crypto.randomUUID())
  const [briefingDone, setBriefingDone] = useState(() => {
    // Only brief once per calendar day — show cached brief on reload
    if (typeof window !== 'undefined') {
      const lastBriefDate = localStorage.getItem('analyst_briefing_date')
      const today = new Date().toISOString().slice(0, 10)
      if (lastBriefDate === today) return true
    }
    return false
  })
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [showStationChips, setShowStationChips] = useState(false)
  const [trendStation, setTrendStation] = useState<StationTrendInfo | null>(null)

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

  // Pre-fill input when a station is mentioned (only if chat panel is open)
  useEffect(() => {
    if (!stationMention) return
    if (externalTab === 'chat') {
      setInput(`@${stationMention.stationName} `)
      setShowStationChips(true)
      inputRef.current?.focus()
    }
    onMentionConsumed?.()
  }, [stationMention, onMentionConsumed, externalTab])

  // Pre-fill input when a district/city is clicked on the map
  useEffect(() => {
    if (!cityMention) return
    if (externalTab === 'chat') {
      setInput(`@${cityMention} `)
      setShowStationChips(true)
      inputRef.current?.focus()
    }
    onMentionConsumed?.()
  }, [cityMention, onMentionConsumed, externalTab])

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // Parse action tags from streamed text
  const extractActions = useCallback((text: string): { clean: string; actions: CopilotAction[] } => {
    const actions: CopilotAction[] = []
    const clean = text.replace(ACTION_RE, (_, json) => {
      try {
        actions.push(JSON.parse(json))
      } catch { /* ignore malformed */ }
      return ''
    })
    return { clean, actions }
  }, [])

  // SSE stream reader
  const streamResponse = useCallback(async (
    endpoint: string,
    body: object,
    assistantId: string,
  ) => {
    setIsStreaming(true)
    onStreamingChange?.(true)

    try {
      const res = await fetch(`${DESK_PREFIX}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
        },
        body: JSON.stringify(body),
      })

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''
      const allActions: CopilotAction[] = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          // Stream ended — mark message as not streaming
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantId ? { ...m, streaming: false } : m
            )
          )
          break
        }

        const text = decoder.decode(value, { stream: true })
        const lines = text.split('\n')

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          try {
            const event = JSON.parse(raw)

            if (event.type === 'text') {
              accumulated += event.content
              const { clean, actions: extractedActions } = extractActions(accumulated)

              // Only dispatch newly found actions (avoid duplicates)
              const newActions = extractedActions.slice(allActions.length)
              for (const action of newActions) {
                if (action.type === 'show_station_trend' && action.station_id) {
                  setTrendStation({ station_id: action.station_id, station_name: action.station_name || '', hours: action.hours ?? 24 })
                }
                onAction?.(action)
              }
              allActions.push(...newActions)

              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantId
                    ? { ...m, content: clean, actions: [...allActions], streaming: true }
                    : m
                )
              )
            } else if (event.type === 'action') {
              if (event.action.type === 'show_station_trend' && event.action.station_id) {
                setTrendStation({ station_id: event.action.station_id, station_name: event.action.station_name || '', hours: event.action.hours ?? 24 })
                setActiveTab('analytics')
              }
              allActions.push(event.action)
              onAction?.(event.action)
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantId
                    ? { ...m, actions: [...allActions] }
                    : m
                )
              )
            } else if (event.type === 'error') {
              accumulated += `\n\n_Error: ${event.content}_`
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantId
                    ? { ...m, content: accumulated, streaming: false }
                    : m
                )
              )
            } else if (event.type === 'done') {
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantId ? { ...m, streaming: false } : m
                )
              )
            }
          } catch { /* ignore parse errors on partial chunks */ }
        }
      }
    } catch (err) {
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantId
            ? { ...m, content: 'Failed to connect to copilot.', streaming: false }
            : m
        )
      )
    } finally {
      setIsStreaming(false)
      onStreamingChange?.(false)
    }
  }, [extractActions, onAction, onStreamingChange])

  // Cache briefing messages whenever they change (after streaming ends)
  useEffect(() => {
    if (briefingDone && messages.length > 0 && !messages.some(m => m.streaming)) {
      try {
        const today = new Date().toISOString().slice(0, 10)
        localStorage.setItem('analyst_briefing_date', today)
        localStorage.setItem('analyst_briefing_messages', JSON.stringify(messages))
      } catch { /* quota exceeded — ignore */ }
    }
  }, [briefingDone, messages])

  // Auto-briefing on mount (once per calendar day)
  useEffect(() => {
    if (briefingDone || !selectedDate) return
    setBriefingDone(true)
    if (typeof window !== 'undefined') {
      localStorage.setItem('analyst_briefing_date', new Date().toISOString().slice(0, 10))
    }

    const assistantId = crypto.randomUUID()
    setMessages([{
      id: assistantId,
      role: 'assistant',
      content: '',
      streaming: true,
    }])

    streamResponse('/copilot/briefing', {
      session_id: sessionId,
      date: selectedDate,
    }, assistantId)
  }, [selectedDate, briefingDone, sessionId, streamResponse])

  // Send a message
  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isStreaming) return

    const userMsg: ChatMessageType = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text.trim(),
    }

    const assistantId = crypto.randomUUID()
    const assistantMsg: ChatMessageType = {
      id: assistantId,
      role: 'assistant',
      content: '',
      streaming: true,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setInput('')
    setShowStationChips(false)
    setActiveTab('chat')

    await streamResponse('/copilot/chat', {
      session_id: sessionId,
      message: text.trim(),
      date: selectedDate,
    }, assistantId)

    inputRef.current?.focus()
  }, [isStreaming, sessionId, selectedDate, streamResponse])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
  }

  const handleSuggestion = (q: string) => {
    sendMessage(q)
  }

  // Show suggestions after briefing is done
  const showSuggestions = messages.length > 0 &&
    !isStreaming &&
    messages.every(m => m.role === 'assistant')

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Tab header — only shown when not externally controlled */}
      {!externalTab && (
        <div className="flex border-b border-slate-100">
          <button
            onClick={() => setActiveTab('chat')}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors ${
              activeTab === 'chat'
                ? 'text-slate-800 font-semibold border-b-2 border-slate-800'
                : 'text-slate-400 hover:text-slate-600'
            }`}
          >
            <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${isStreaming ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'}`} />
            Chat
          </button>
          <button
            onClick={() => setActiveTab('analytics')}
            className={`relative flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors ${
              activeTab === 'analytics'
                ? 'text-slate-800 font-semibold border-b-2 border-slate-800'
                : trendStation && activeTab !== 'analytics'
                  ? 'text-blue-600 border-b-2 border-blue-400 animate-pulse'
                  : 'text-slate-400 hover:text-slate-600'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 13h4v8H3zM10 9h4v12h-4zM17 5h4v16h-4z" />
            </svg>
            Analytics
            {trendStation && activeTab !== 'analytics' && (
              <span className="absolute top-1.5 right-4 flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
              </span>
            )}
          </button>
        </div>
      )}

      {/* Content area */}
      {activeTab === 'chat' ? (
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-2">
          {messages.map(msg => (
            <ChatMessage key={msg.id} message={msg} knownCities={knownCities} onCityClick={handleCityClick} />
          ))}

          {/* Suggested questions */}
          {showSuggestions && (
            <div className="mt-3 space-y-1">
              <p className="text-[10px] text-slate-400 font-medium uppercase tracking-wide mb-1.5">
                Ask about...
              </p>
              {SUGGESTED_QUESTIONS.map((q, i) => (
                <button
                  key={i}
                  onClick={() => handleSuggestion(q)}
                  className="w-full text-left px-2.5 py-1.5 rounded-md text-[11px] text-slate-500 hover:bg-slate-50 hover:text-slate-800 transition-colors border border-slate-100"
                >
                  {q}
                </button>
              ))}
            </div>
          )}

          {/* Empty state */}
          {messages.length === 0 && !isStreaming && (
            <div className="flex items-center justify-center h-full text-slate-400 text-xs">
              Loading briefing...
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-hidden">
          {trendStation ? (
            <StationTrendPanel
              station={trendStation}
              onBack={() => setTrendStation(null)}
            />
          ) : (
            <AnalystPanel stations={stations ?? []} />
          )}
        </div>
      )}

      {/* Station suggestion chips */}
      {showStationChips && input.startsWith('@') && (
        <div className="px-3 py-1.5 border-t border-slate-100 flex flex-wrap gap-1">
          {STATION_CHIPS.map((chip, i) => (
            <button
              key={i}
              onClick={() => sendMessage(input + chip)}
              className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-600 hover:bg-slate-200 transition-colors"
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="px-3 py-2 border-t border-slate-100">
        <div className="flex items-center gap-1.5">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about forecasts, cities, watchlists..."
            disabled={isStreaming}
            className="flex-1 px-3 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-300 focus:border-transparent disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={isStreaming || !input.trim()}
            className="p-1.5 rounded-lg bg-slate-800 text-white hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </form>
    </div>
  )
}
