'use client'

type ViewMode = 'live' | 'estimated'

interface Props {
  mode: ViewMode
  onChange: (mode: ViewMode) => void
}

export default function ViewModeToggle({ mode, onChange }: Props) {
  const isLive = mode === 'live'

  return (
    <div className="relative flex items-center rounded-full bg-[#6f7a68]/45 backdrop-blur-xl border border-white/20 shadow-[0_10px_30px_rgba(0,0,0,0.18)] p-1">
      {/* Sliding selected pill */}
      <span
        aria-hidden
        className="absolute top-1 bottom-1 left-1 rounded-full bg-white/14 shadow-[inset_0_1px_0_rgba(255,255,255,0.22),0_4px_14px_rgba(0,0,0,0.12)] transition-all duration-300 ease-out"
        style={{
          width: isLive ? '88px' : '124px',
          transform: isLive ? 'translateX(0)' : 'translateX(88px)',
        }}
      />

      <button
        type="button"
        onClick={() => onChange('live')}
        className={`relative z-10 flex w-[88px] items-center justify-center gap-2 py-1.5 rounded-full text-xs font-medium tracking-wide transition-colors duration-200 ${
          isLive ? 'text-white' : 'text-white/50'
        }`}
      >
        <span
          className={`h-2 w-2 rounded-full flex-shrink-0 transition-all duration-200 ${
            isLive
              ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.65)] animate-pulse'
              : 'bg-white/30'
          }`}
        />
        LIVE
      </button>

      <button
        type="button"
        onClick={() => onChange('estimated')}
        className={`relative z-10 flex w-[124px] items-center justify-center gap-2.5 py-1.5 rounded-full text-xs font-medium tracking-wide transition-colors duration-200 ${
          !isLive ? 'text-white' : 'text-white/50'
        }`}
      >
        <span
          className={`h-2 w-2 rounded-full flex-shrink-0 transition-all duration-200 ${
            !isLive
              ? 'bg-amber-300 shadow-[0_0_8px_rgba(252,211,77,0.55)]'
              : 'bg-white/30'
          }`}
        />
        ESTIMATED
      </button>
    </div>
  )
}
