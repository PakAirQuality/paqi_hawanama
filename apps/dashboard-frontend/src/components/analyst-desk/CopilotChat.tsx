"use client"

import { useState, useRef, useEffect, useCallback } from 'react'
import { ChatMessage } from './ChatMessage'
import type { ChatMessage as ChatMessageType, CopilotAction } from './types'

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

interface CopilotChatProps {
  selectedDate: string
  onAction?: (action: CopilotAction) => void
}

export function CopilotChat({ selectedDate, onAction }: CopilotChatProps) {
  const [messages, setMessages] = useState<ChatMessageType[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId] = useState(() => crypto.randomUUID())
  const [briefingDone, setBriefingDone] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

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
        if (done) break

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
              const { clean, actions } = extractActions(accumulated)
              allActions.push(...actions)

              // Dispatch actions immediately
              for (const action of actions) {
                onAction?.(action)
              }

              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantId
                    ? { ...m, content: clean, actions: [...allActions], streaming: true }
                    : m
                )
              )
            } else if (event.type === 'action') {
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
    }
  }, [extractActions, onAction])

  // Auto-briefing on mount
  useEffect(() => {
    if (briefingDone || !selectedDate) return
    setBriefingDone(true)

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
      {/* Header */}
      <div className="px-3 py-2 border-b border-slate-100">
        <div className="flex items-center gap-1.5">
          <div className={`w-1.5 h-1.5 rounded-full ${isStreaming ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'}`} />
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Copilot</h2>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-2">
        {messages.map(msg => (
          <ChatMessage key={msg.id} message={msg} />
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
