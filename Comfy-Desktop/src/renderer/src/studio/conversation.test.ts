import { beforeEach, describe, expect, it } from 'vitest'
import {
  type CardAsk,
  type CardPlan,
  type CardTool,
  type QuoteRef,
  type StudioCard,
  appendUserTurn,
  blockingCards,
  composeQuotes,
  makeUserCard,
  pendingCard,
  reduceAgentEvent,
  resetCardIds,
  restoreFromHistory,
  settleTurn,
  splitQuotes
} from './conversation'

const SESSION = 'chat-1'

function quote(text: string, name = 'Book.txt', offset = 0): QuoteRef {
  return { name, offset, chars: text.length, text }
}

function kinds(cards: StudioCard[]): string[] {
  return cards.map((card) => card.kind)
}

function firstTool(cards: StudioCard[]): CardTool {
  const card = cards.find((entry): entry is CardTool => entry.kind === 'tool')
  if (!card) throw new Error('no tool card')
  return card
}

beforeEach(() => {
  resetCardIds()
})

describe('quote syntax', () => {
  it('prefixes quote blocks and keeps a blank line before the user words', () => {
    const composed = composeQuotes('把这段画出来', [quote('第一段原文')])

    expect(composed).toBe('[引用 Book.txt 0 5]\n第一段原文\n[/引用]\n\n把这段画出来')
  })

  it('returns plain text untouched when nothing is quoted', () => {
    expect(composeQuotes('一句话', [])).toBe('一句话')
  })

  it('round-trips a single quote and the trailing text', () => {
    const composed = composeQuotes('画成特写', [quote('他推开门')])
    const parsed = splitQuotes(composed)

    expect(parsed.quotes).toHaveLength(1)
    expect(parsed.quotes[0]).toMatchObject({ name: 'Book.txt', offset: 0, chars: 4 })
    expect(parsed.quotes[0].text).toBe('他推开门')
    expect(parsed.text).toBe('画成特写')
  })

  it('round-trips several quotes', () => {
    const composed = composeQuotes('合起来', [quote('甲', 'A', 10), quote('乙', 'B', 20)])
    const parsed = splitQuotes(composed)

    expect(parsed.quotes.map((q) => q.name)).toEqual(['A', 'B'])
    expect(parsed.quotes.map((q) => q.offset)).toEqual([10, 20])
    expect(parsed.text).toBe('合起来')
  })

  it('keeps a multi-line quote body intact', () => {
    const parsed = splitQuotes(composeQuotes('继续', [quote('上\n中\n下')]))

    expect(parsed.quotes[0].text).toBe('上\n中\n下')
    expect(parsed.text).toBe('继续')
  })

  it('treats an unterminated marker as ordinary text instead of guessing', () => {
    const text = '[引用 Book.txt 0 5]\n没有收尾的那一行'
    const parsed = splitQuotes(text)

    expect(parsed.quotes).toEqual([])
    expect(parsed.text).toBe(text)
  })

  it('treats hand-typed lookalikes as plain text when they do not match', () => {
    const text = '[引用 xxx] 这是我的笔记'
    expect(splitQuotes(text)).toEqual({ quotes: [], text })
  })
})

describe('agent event folding', () => {
  it('drops events belonging to another session', () => {
    const cards = appendUserTurn([], '你好')

    const next = reduceAgentEvent(cards, { type: 'assistant', text: '别人的', session_id: 'other' }, SESSION)

    expect(next).toBe(cards)
  })

  it('paints streaming narration as an intermediate assistant card', () => {
    const next = reduceAgentEvent([], { type: 'assistant', text: '我看看', session_id: SESSION }, SESSION)

    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ kind: 'assistant', variant: 'intermediate', text: '我看看' })
  })

  it('attaches a retry notice to the pending card as data, not as prose', () => {
    const cards = appendUserTurn([], '跑一下')

    const next = reduceAgentEvent(
      cards,
      { type: 'retry', attempt: 2, total: 3, delay: 4, session_id: SESSION },
      SESSION
    )

    // Structured on purpose: the rail owns the wording, so both locales work
    // and the model layer stays free of user-facing strings.
    expect(pendingCard(next)?.retry).toEqual({ attempt: 2, total: 3, delay: 4 })
  })

  it('pairs a tool result with its call by id', () => {
    let cards = reduceAgentEvent(
      [],
      { type: 'tool_call', id: 't1', name: 'skills__run', arguments: { skill: 'x' }, session_id: SESSION },
      SESSION
    )
    cards = reduceAgentEvent(cards, { type: 'tool_result', id: 't1', text: '好了', session_id: SESSION }, SESSION)

    expect(cards).toHaveLength(1)
    expect(firstTool(cards)).toMatchObject({
      tool: 'skills__run',
      state: 'done',
      result: '好了',
      orphan: false
    })
    expect(firstTool(cards).args).toContain('"skill": "x"')
  })

  it('marks a tool failure from the ERROR: text convention', () => {
    let cards = reduceAgentEvent([], { type: 'tool_call', id: 't1', name: 'x__y', session_id: SESSION }, SESSION)
    cards = reduceAgentEvent(
      cards,
      { type: 'tool_result', id: 't1', text: 'ERROR: 炸了', session_id: SESSION },
      SESSION
    )

    expect(firstTool(cards).state).toBe('error')
  })

  it('shows an unmatched tool result as an orphan instead of dropping it', () => {
    const cards = reduceAgentEvent(
      [],
      { type: 'tool_result', id: 'ghost', text: '结果来了', session_id: SESSION },
      SESSION
    )

    expect(cards).toHaveLength(1)
    expect(firstTool(cards)).toMatchObject({ orphan: true, state: 'done' })
  })

  it('keeps one ask card per call even if the host re-emits it', () => {
    let cards = reduceAgentEvent(
      [],
      { type: 'ask_user', call_id: 'ask-1', question: '用哪套？', options: ['SDXL', 'Flux'], session_id: SESSION },
      SESSION
    )
    cards = reduceAgentEvent(
      cards,
      { type: 'ask_user', call_id: 'ask-1', question: '用哪套？', options: ['SDXL', 'Flux'], session_id: SESSION },
      SESSION
    )

    expect(cards).toHaveLength(1)
    const ask = cards[0] as CardAsk
    expect(ask.options).toEqual(['SDXL', 'Flux'])
    expect(ask.state).toBe('waiting')
  })

  it('ticks a plan step from a progress ping', () => {
    let cards = reduceAgentEvent(
      [],
      {
        type: 'plan',
        call_id: 'plan-1',
        goal: '做一集',
        steps: [
          { title: '建纲', tool: 'novels__x' },
          { title: '分镜', tool: 'pipeline__run' }
        ],
        session_id: SESSION
      },
      SESSION
    )
    cards = reduceAgentEvent(
      cards,
      { type: 'plan_progress', call_id: 'plan-1', step: 1, status: 'done', note: '8 个镜头', session_id: SESSION },
      SESSION
    )

    const plan = cards[0] as CardPlan
    expect(plan.steps[0].status).toBe('pending')
    expect(plan.steps[1]).toMatchObject({ status: 'done', note: '8 个镜头' })
    expect(blockingCards(cards)).toHaveLength(1)
  })

  it('ignores unknown event types and the final text', () => {
    const cards = appendUserTurn([], 'hi')

    expect(reduceAgentEvent(cards, { type: 'final', text: '答案', session_id: SESSION }, SESSION)).toBe(cards)
    expect(reduceAgentEvent(cards, { type: 'canvas_request', session_id: SESSION }, SESSION)).toBe(cards)
  })
})

describe('turn lifecycle', () => {
  it('appends the user card and a pending card, and parses quotes out of it', () => {
    const cards = appendUserTurn([], composeQuotes('画出来', [quote('原文')]))
    const [user] = cards

    expect(kinds(cards)).toEqual(['user', 'pending'])
    expect(user).toMatchObject({ kind: 'user', text: '画出来' })
    expect((user as { quotes: QuoteRef[] }).quotes[0].text).toBe('原文')
  })

  it('closes a turn with the final answer and removes the pending card', () => {
    const cards = settleTurn(appendUserTurn([], '问'), { kind: 'assistant', text: '答' })

    expect(kinds(cards)).toEqual(['user', 'assistant'])
    expect(cards[1]).toMatchObject({ variant: 'final', text: '答' })
  })

  it('treats a cancelled turn as stopped, not as a failure', () => {
    const cards = settleTurn(appendUserTurn([], '问'), { kind: 'stopped', reason: '用户停止' })

    expect(kinds(cards)).toEqual(['user', 'stopped'])
    expect(pendingCard(cards)).toBeNull()
  })

  it('records a failed turn as an error card with its code', () => {
    const cards = settleTurn(appendUserTurn([], '问'), { kind: 'error', text: '失败: 会话忙', code: -32602 })

    expect(cards[cards.length - 1]).toMatchObject({ kind: 'error', code: -32602 })
  })

  it('never leaves a pending card behind when a turn settles', () => {
    const cards = settleTurn(appendUserTurn([], '问'), { kind: 'notice', text: '这一轮没发出去' })

    expect(pendingCard(cards)).toBeNull()
  })

  it('reports no blocking control cards for a plain turn', () => {
    expect(blockingCards(appendUserTurn([], '问'))).toEqual([])
  })
})

describe('user card parsing', () => {
  it('keeps the words and lifts the quotes out of a stored message', () => {
    const card = makeUserCard(composeQuotes('按这个改', [quote('第 3 镜太长了', 'S4.txt', 120)]))

    expect(card.text).toBe('按这个改')
    expect(card.quotes[0]).toMatchObject({ name: 'S4.txt', offset: 120 })
  })
})

describe('history replay', () => {
  // Shapes copied from the host's own expectations (`history.entries`): history
  // and the live stream deliberately share one vocabulary, so this must be the
  // same fold — if either side changes shape, this test is the tripwire.
  const entries = [
    { type: 'user', text: '问一句' },
    { type: 'tool_call', id: 'call_1', name: 'fake__do_it', arguments: { limit: 5 } },
    { type: 'tool_result', id: 'call_1', name: 'fake__do_it', text: '[]' },
    { type: 'assistant', text: '答一句', variant: 'final' }
  ]

  it('repaints an archived conversation through the same fold as the live stream', () => {
    const cards = restoreFromHistory(entries)

    expect(kinds(cards)).toEqual(['user', 'tool', 'assistant'])
    expect(firstTool(cards)).toMatchObject({ callId: 'call_1', state: 'done', result: '[]' })
    expect(cards[2]).toMatchObject({ kind: 'assistant', text: '答一句', variant: 'final' })
  })

  it('honours the archived variant instead of reclassifying narration', () => {
    const cards = restoreFromHistory([
      { type: 'assistant', text: '先查一下', variant: 'intermediate' },
      { type: 'tool_call', id: 'c1', name: 'fake__list', arguments: {} }
    ])

    expect(cards[0]).toMatchObject({ kind: 'assistant', variant: 'intermediate' })
  })

  it('says so when the archive was trimmed rather than pretending it is whole', () => {
    const cards = restoreFromHistory(entries, { dropped: 12 })

    expect(cards[0]).toMatchObject({
      kind: 'notice',
      hint: { kind: 'historyTrimmed', dropped: 12 }
    })
    expect(kinds(cards)).toEqual(['notice', 'user', 'tool', 'assistant'])
  })

  it('leaves no pending card behind for an archived turn', () => {
    expect(pendingCard(restoreFromHistory(entries))).toBeNull()
  })

  it('restores an empty conversation as an empty rail, not as an error', () => {
    expect(restoreFromHistory([])).toEqual([])
  })
})
