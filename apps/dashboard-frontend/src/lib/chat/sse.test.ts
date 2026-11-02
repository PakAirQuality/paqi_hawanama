import { describe, expect, it } from 'vitest'
import { createSseParser } from './sse'

describe('createSseParser', () => {
  it('reads complete events', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"type":"text","content":"Hi"}\n\ndata: {"type":"done"}\n\n')).toEqual([
      { type: 'text', content: 'Hi' },
      { type: 'done' },
    ])
  })

  it('holds an event split across two network chunks', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"type":"text","con')).toEqual([])
    expect(parser.push('tent":"Lahore"}\n\n')).toEqual([{ type: 'text', content: 'Lahore' }])
  })

  it('survives being fed one character at a time', () => {
    const parser = createSseParser()
    const wire = 'data: {"type":"text","content":"a\\nb"}\n\ndata: {"type":"done"}\n\n'
    const events = [...wire].flatMap(c => parser.push(c))
    expect(events).toEqual([{ type: 'text', content: 'a\nb' }, { type: 'done' }])
  })

  it('handles CRLF line endings', () => {
    expect(createSseParser().push('data: {"type":"done"}\r\n\r\n')).toEqual([{ type: 'done' }])
  })

  it('reads a final event with no trailing newline on flush', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"type":"done"}')).toEqual([])
    expect(parser.flush()).toEqual([{ type: 'done' }])
  })

  it.each([
    ['not JSON', 'data: {oops}\n\n'],
    ['JSON that is not an object', 'data: 42\n\n'],
    ['null', 'data: null\n\n'],
    ['an unknown event type', 'data: {"type":"mystery"}\n\n'],
    ['text with no content', 'data: {"type":"text"}\n\n'],
    ['text with non-string content', 'data: {"type":"text","content":{"a":1}}\n\n'],
    ['a comment line', ': keep-alive\n\n'],
    ['an empty data line', 'data: \n\n'],
  ])('ignores %s', (_, wire) => {
    expect(createSseParser().push(wire)).toEqual([])
  })

  it('keeps going after a bad line', () => {
    expect(createSseParser().push('data: {bad}\n\ndata: {"type":"done"}\n\n')).toEqual([{ type: 'done' }])
  })
})
