"use client"

import type { ChatMessage as ChatMessageType } from './types'

interface ChatMessageProps {
  message: ChatMessageType
  knownCities?: Set<string>
  onCityClick?: (city: string) => void
}

function formatTrendLabel(hours?: number): string {
  if (!hours || hours <= 72) return `${hours || 24}h`
  return `${Math.round(hours / 24)}d`
}

export function ChatMessage({ message, knownCities, onCityClick }: ChatMessageProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-2`}>
      <div
        className={`max-w-[88%] rounded-xl px-3 py-1.5 text-[12px] leading-[1.5] ${
          isUser
            ? 'bg-slate-800 text-white rounded-br-sm'
            : 'bg-slate-50 text-slate-700 rounded-bl-sm'
        }`}
      >
        {message.content.split('\n').map((line, i) => {
          if (!line.trim()) return <br key={i} />

          // Render bold text (**text**)
          const parts = line.split(/(\*\*[^*]+\*\*)/)
          return (
            <p key={i} className={i > 0 ? 'mt-1' : ''}>
              {parts.map((part, j) => {
                if (part.startsWith('**') && part.endsWith('**')) {
                  const text = part.slice(2, -2)
                  const isCity = !isUser && knownCities?.has(text)
                  return (
                    <span
                      key={j}
                      className={`font-semibold${isCity ? ' text-blue-600 cursor-pointer hover:underline' : ''}`}
                      onClick={isCity ? () => onCityClick?.(text) : undefined}
                    >
                      {text}
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
          <div className="flex flex-wrap gap-1 mt-1.5">
            {message.actions.map((action, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-0.5 px-1.5 py-px rounded-full bg-blue-50 text-blue-600 text-[9px] font-medium"
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
                {action.type === 'filter_network' && (
                  <>{action.network ? `Filter: ${action.network}` : 'All networks'}</>
                )}
                {action.type === 'show_station_trend' && (
                  <>{'\u{1F4C8}'} {formatTrendLabel(action.hours)} Trend</>
                )}
              </span>
            ))}
          </div>
        )}

        {/* Streaming indicator */}
        {message.streaming && (
          <span className="inline-flex gap-0.5 ml-1">
            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
          </span>
        )}
      </div>
    </div>
  )
}
