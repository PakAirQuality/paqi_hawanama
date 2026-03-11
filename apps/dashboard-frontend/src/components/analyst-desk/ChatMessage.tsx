"use client"

import type { ChatMessage as ChatMessageType } from './types'

interface ChatMessageProps {
  message: ChatMessageType
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed ${
          isUser
            ? 'bg-slate-800 text-white rounded-br-md'
            : 'bg-slate-100 text-slate-800 rounded-bl-md'
        }`}
      >
        {message.content.split('\n').map((line, i) => {
          if (!line.trim()) return <br key={i} />

          // Render bold text (**text**)
          const parts = line.split(/(\*\*[^*]+\*\*)/)
          return (
            <p key={i} className={i > 0 ? 'mt-1.5' : ''}>
              {parts.map((part, j) => {
                if (part.startsWith('**') && part.endsWith('**')) {
                  return (
                    <span key={j} className="font-semibold">
                      {part.slice(2, -2)}
                    </span>
                  )
                }
                return <span key={j}>{part}</span>
              })}
            </p>
          )
        })}

        {/* Action badges */}
        {message.actions && message.actions.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {message.actions.map((action, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-[10px] font-medium"
              >
                {action.type === 'zoom_to_city' && (
                  <>{'\u{1F4CD}'} {action.city}</>
                )}
                {action.type === 'zoom_to_station' && (
                  <>{'\u{1F4CD}'} Station {action.sensor_id}</>
                )}
                {action.type === 'set_horizon' && (
                  <>D+{action.horizon}</>
                )}
              </span>
            ))}
          </div>
        )}

        {/* Streaming indicator */}
        {message.streaming && (
          <span className="inline-flex gap-1 ml-1">
            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
          </span>
        )}
      </div>
    </div>
  )
}
