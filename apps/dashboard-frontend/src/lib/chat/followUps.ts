// Questions offered in the chat: a starting set, then follow-ups after each answer.

export const STARTING_QUESTIONS = [
  'What are the most polluted cities today?',
  'How is Lahore looking for the next 3 days?',
  'Were there any fires detected?',
  'What is driving the pollution?',
]

interface FollowUpInput {
  answer: string
  asked: string[]
  cities: Iterable<string>
  /** Questions the model suggested at the end of its answer */
  offered?: string[]
  limit?: number
}

const LABEL_RE = /follow[- ]?ups?|you (can|could|might|may) (also )?ask|next questions?|dig deeper|explore further|learn more|would you like|next steps?/i
const LIST_ITEM_RE = /^\s*(?:[-*+•]|\d{1,2}[.)])\s+(.*)$/
const MAX_LABEL_CHARS = 60
const MAX_QUESTION_CHARS = 140

const isLabel = (line: string) => line.trim().length <= MAX_LABEL_CHARS && LABEL_RE.test(line)
const plain = (line: string) => line.replace(/[*_`]/g, '').replace(/^["“]|["”]$/g, '').trim()

/**
 * The copilot ends its answers with a labelled list of suggested questions. That list is lifted
 * out so it can be offered as buttons; anything that does not match this shape stays in the answer.
 */
export function splitFollowUps(text: string): { body: string; questions: string[] } {
  const lines = text.trimEnd().split(/\r?\n/)
  let i = lines.length - 1
  const questions: string[] = []

  while (i >= 0) {
    const item = LIST_ITEM_RE.exec(lines[i])
    if (item) {
      questions.unshift(plain(item[1]))
      i--
    } else if (!lines[i].trim() && questions.length > 0) {
      i--
    } else {
      break
    }
  }

  if (i < 0 || questions.length === 0 || !isLabel(lines[i]) || questions.some(q => !q || q.length > MAX_QUESTION_CHARS)) {
    return { body: text, questions: [] }
  }
  const body = lines.slice(0, i).join('\n').trimEnd()
  return body ? { body, questions } : { body: text, questions: [] }
}

const firstCityIn = (answer: string, cities: Iterable<string>): string | null => {
  let best: { city: string; at: number } | null = null
  for (const city of cities) {
    const at = city.length > 2 ? answer.indexOf(city) : -1
    if (at >= 0 && (!best || at < best.at)) best = { city, at }
  }
  return best?.city ?? null
}

/** Up to `limit` questions not asked yet: the model's own first, then one about the answer's city. */
export function followUpQuestions({ answer, asked, cities, offered = [], limit = 3 }: FollowUpInput): string[] {
  const city = firstCityIn(answer, cities)
  const lead = city ? [`How is ${city} looking for the next 3 days?`] : []
  const used = new Set(asked.map(q => q.trim().toLowerCase()))
  return [...offered, ...lead, ...STARTING_QUESTIONS]
    .filter((q, i, all) => !used.has(q.toLowerCase()) && all.findIndex(o => o.toLowerCase() === q.toLowerCase()) === i)
    .slice(0, limit)
}
