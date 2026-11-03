import type { CSSProperties } from 'react'

/** Grey placeholder with a soft moving highlight. Use in the final layout of the content it stands in for. */
export function Skeleton({ className = '', style }: { className?: string; style?: CSSProperties }) {
  return <div aria-hidden className={`skeleton rounded-lg ${className}`} style={style} />
}
