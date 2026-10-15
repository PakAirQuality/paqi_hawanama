/** Format a YYYY-MM-DD date string as "May 11, 2026" without timezone surprises. */
export function formatDateLabel(date: string | null | undefined): string {
  if (!date) return ''
  return new Date(date + 'T00:00:00').toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}
