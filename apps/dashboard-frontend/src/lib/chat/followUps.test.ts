import { describe, expect, it } from 'vitest'
import { STARTING_QUESTIONS, followUpQuestions, splitFollowUps } from './followUps'

const base = { answer: 'Nothing notable.', asked: [] as string[], cities: [] as string[] }

describe('splitFollowUps', () => {
  it('lifts the list the copilot ends its answers with', () => {
    const text = 'Eminabad was worst.\n\n**Suggested Follow-ups:**\n\n- Tell me more about Eminabad.\n- What needs attention today?'
    expect(splitFollowUps(text)).toEqual({
      body: 'Eminabad was worst.',
      questions: ['Tell me more about Eminabad.', 'What needs attention today?'],
    })
  })

  it.each([
    ['a heading', '### Follow-up questions\n1. One?\n2. Two?'],
    ['plain text', 'You could also ask:\n* One?\n* Two?'],
    ['no gap before the list', 'Follow-ups:\n- One?\n- Two?'],
    ['the wording the live model used', 'Here are a few ways we can dig deeper:\n\n- One?\n- Two?'],
    ['the other wording it used', '*Suggested follow-up questions:*\n- One?\n- Two?'],
  ])('recognises %s', (_, tail) => {
    expect(splitFollowUps(`Answer.\n\n${tail}`)).toEqual({ body: 'Answer.', questions: ['One?', 'Two?'] })
  })

  it('keeps a real list that is the answer itself', () => {
    const text = 'Worst cities:\n\n- Lahore: 270\n- Kasur: 247'
    expect(splitFollowUps(text)).toEqual({ body: text, questions: [] })
  })

  it('keeps text after the list, which means it was not the closing list', () => {
    const text = 'Follow-ups:\n- One?\n\nThat is all for today.'
    expect(splitFollowUps(text)).toEqual({ body: text, questions: [] })
  })

  it('keeps an answer that is nothing but the list rather than showing an empty reply', () => {
    const text = 'Follow-ups:\n- One?'
    expect(splitFollowUps(text)).toEqual({ body: text, questions: [] })
  })

  it('does not treat a long sentence mentioning follow-ups as a label', () => {
    const text = `${'The inspectors scheduled several follow-up visits to every kiln '.repeat(2)}:\n- Kasur\n- Lahore`
    expect(splitFollowUps(text).questions).toEqual([])
  })

  it('leaves text with no list alone', () => {
    expect(splitFollowUps('Just an answer.')).toEqual({ body: 'Just an answer.', questions: [] })
  })
})

describe('followUpQuestions', () => {
  it('prefers the questions the model suggested', () => {
    const out = followUpQuestions({ ...base, offered: ['Model one?', 'Model two?'], answer: 'Lahore', cities: ['Lahore'] })
    expect(out.slice(0, 2)).toEqual(['Model one?', 'Model two?'])
    expect(out).toHaveLength(3)
  })

  it('does not repeat one the person already asked, whatever its case', () => {
    expect(followUpQuestions({ ...base, offered: ['Model one?'], asked: ['MODEL ONE?'] })).not.toContain('Model one?')
  })

  it('falls back to the standard questions', () => {
    expect(followUpQuestions(base)).toEqual(STARTING_QUESTIONS.slice(0, 3))
  })

  it('leads with the first city named in the answer', () => {
    const out = followUpQuestions({ ...base, answer: 'Kasur then Lahore were worst.', cities: ['Lahore', 'Kasur'] })
    expect(out[0]).toBe('How is Kasur looking for the next 3 days?')
  })

  it('never offers a question already asked, whatever its case', () => {
    const asked = [STARTING_QUESTIONS[0].toUpperCase()]
    expect(followUpQuestions({ ...base, asked })).not.toContain(STARTING_QUESTIONS[0])
  })

  it('does not repeat a city question that was already asked', () => {
    const out = followUpQuestions({ ...base, answer: 'Lahore.', cities: ['Lahore'], asked: ['How is Lahore looking for the next 3 days?'] })
    expect(out).not.toContain('How is Lahore looking for the next 3 days?')
  })

  it('returns nothing once everything has been asked', () => {
    expect(followUpQuestions({ ...base, asked: STARTING_QUESTIONS })).toEqual([])
  })

  it('respects the limit', () => {
    expect(followUpQuestions({ ...base, limit: 1 })).toHaveLength(1)
  })
})
