/**
 * Conversation model of the native studio rail.
 *
 * Pure data + reducers, no DOM: the old drawer painted cards straight into the
 * page from one 9500-line script, which is exactly why it could not be tested or
 * restyled. Here the host's event stream is folded into a list of plain card
 * objects; the Vue components only render that list.
 *
 * Two things are deliberately byte-compatible with the drawer, because the host
 * and the saved history depend on them:
 *   1. the quote block syntax (`composeQuotes` / `splitQuotes`) — it is embedded
 *      in the message text that `agent/chat` stores, so history repaints it;
 *   2. `agent/chat`'s request/response contract, including "a cancelled turn is
 *      a normal response, not a failure".
 * Everything else here is a port, not a redesign.
 */

/** A selection the user quoted from a novel. `offset`/`chars` are offsets into
 *  the original text, so the引用 stays meaningful when the page changes. */
export interface QuoteRef {
  name: string
  offset: number
  chars: number
  text: string
}

/** One step of a plan card (`plan__submit`). */
export interface PlanStep {
  title: string
  tool: string
  detail: string
  status: 'pending' | 'running' | 'done' | 'failed'
  note: string
}

/** Tool card lifecycle. `running` → `done` | `error`; `orphan` marks a result
 *  whose `tool_call` never arrived (the drawer showed those instead of dropping
 *  them). */
export type ToolState = 'running' | 'done' | 'error'

/** Ask card lifecycle: the host's `review__ask_user` is blocked on this card's
 *  answer (`agent/answer`). */
export type AskState = 'waiting' | 'sending' | 'answered' | 'stale' | 'failed'

/** Plan card lifecycle: the host's `plan__submit` is blocked on this card's
 *  verdict (`agent/plan_result`). */
export type PlanState = 'waiting' | 'editing' | 'sending' | 'approved' | 'rejected' | 'stale' | 'failed'

export interface CardUser {
  id: string
  kind: 'user'
  text: string
  quotes: QuoteRef[]
}

/** `variant` mirrors the drawer's `final` / `intermediate` split: streaming
 *  narration vs the turn's answer. */
export interface CardAssistant {
  id: string
  kind: 'assistant'
  text: string
  variant: 'final' | 'intermediate'
}

/** Back-off notice the host sends while it is still waiting on the model. */
export interface RetryHint {
  attempt: number
  total: number
  delay: number
}

/** Shown while a turn is in flight. `retry` carries the host's back-off notice
 *  (structured, not a sentence — this module holds no user-facing prose);
 *  `softTimeout` flips after TURN_SOFT_TIMEOUT_S so the user may unlock the UI
 *  themselves (the host still owns the session — see server.py's agent_chat). */
export interface CardPending {
  id: string
  kind: 'pending'
  startedAt: number
  retry: RetryHint | null
  softTimeout: boolean
}

export interface CardStopped {
  id: string
  kind: 'stopped'
  reason: string
}

export interface CardError {
  id: string
  kind: 'error'
  text: string
  code: number | null
}

/** Conditions the rail must explain that are not the host's words. Structured
 *  so the component can translate them; `text` stays reserved for prose the
 *  host itself authored (already localized on its side). */
export type NoticeHint = { kind: 'historyTrimmed'; dropped: number }

/** System/notice line: history headers, host warnings, plan fallbacks. */
export interface CardNotice {
  id: string
  kind: 'notice'
  text: string
  hint: NoticeHint | null
}

export interface CardTool {
  id: string
  kind: 'tool'
  callId: string
  tool: string
  state: ToolState
  args: string
  result: string
  orphan: boolean
  collapsed: boolean
}

export interface CardAsk {
  id: string
  kind: 'ask'
  callId: string
  question: string
  options: string[]
  state: AskState
  answer: string
  error: string
}

export interface CardPlan {
  id: string
  kind: 'plan'
  callId: string
  goal: string
  steps: PlanStep[]
  notes: string
  state: PlanState
  feedback: string
  error: string
}

export type StudioCard =
  | CardUser
  | CardAssistant
  | CardPending
  | CardStopped
  | CardError
  | CardNotice
  | CardTool
  | CardAsk
  | CardPlan

/** Host event params as they arrive on `agent/event`. Every field is optional
 *  because the host emits several shapes on the same channel. */
export interface AgentEventParams {
  type?: string
  session_id?: string
  /** `retry` */
  attempt?: number
  total?: number
  delay?: number
  /** `assistant` */
  text?: string
  /** `assistant` — only set by `agent/history`, which classifies each archived
   *  line itself (see `history.entries`). Live events leave it unset and are
   *  treated as narration. */
  variant?: string
  /** `tool_call` / `tool_result` */
  id?: string
  name?: string
  arguments?: unknown
  /** `ask_user` */
  call_id?: string
  question?: string
  options?: string[]
  /** `plan` */
  goal?: string
  steps?: Array<Record<string, unknown>>
  notes?: string
  /** `plan_progress` */
  step?: number
  status?: string
  note?: string
}

// ---- quote syntax (parity with the drawer) -----------------------------

/** Opening marker of a quote block. Only this module writes it and only
 *  `splitQuotes` reads it, so it never has to match another language. */
const QUOTE_OPEN_RE = /^\[引用 (.{1,200}?) (\d+) (\d+)\]$/
const QUOTE_CLOSE = '[/引用]'

/** At most this many quotes per turn, and this many characters previewed in the
 *  card. Same caps as the drawer. */
export const MAX_QUOTES = 4
export const QUOTE_PREVIEW_CHARS = 800

/** How long a turn may stay silent before the rail offers a manual unlock.
 *  It is a hint, not a verdict: the host still holds the session. */
export const TURN_SOFT_TIMEOUT_S = 300

/** localStorage key holding the active session id, shared with the drawer so
 *  switching surfaces does not lose the conversation. */
export const SESSION_STORAGE_KEY = 'comfyStudio.session'

export function draftKey(sessionId: string): string {
  return `comfyStudio.draft.${sessionId}`
}

export function newSessionId(now: number = Date.now()): string {
  return `chat-${now}`
}

/**
 * What the turn finally looks like: quote blocks first, a blank line, then the
 * user's own words. Quoting nothing returns the text untouched, so a plain turn
 * is stored as plain text.
 */
export function composeQuotes(text: string, quotes: readonly QuoteRef[]): string {
  const blocks = quotes.map((quote) => {
    return `[引用 ${quote.name} ${quote.offset} ${quote.chars}]\n${quote.text}\n${QUOTE_CLOSE}`
  })
  if (blocks.length === 0) return text
  const head = blocks.join('\n\n')
  return text === '' ? head : `${head}\n\n${text}`
}

/**
 * The inverse: split a stored message into its leading quote blocks plus the
 * rest. Anything that does not match the shape is treated as ordinary text —
 * a user may well have typed something that looks like a marker, and showing
 * their own words unchanged is strictly better than guessing where a quote ends.
 */
export function splitQuotes(text: string): { quotes: QuoteRef[]; text: string } {
  const lines = String(text ?? '').split('\n')
  const quotes: QuoteRef[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    const match = line === undefined ? null : QUOTE_OPEN_RE.exec(line)
    if (!match) break
    let end = index + 1
    while (end < lines.length && lines[end] !== QUOTE_CLOSE) end += 1
    if (end >= lines.length) {
      // Unterminated block: fall back to plain text rather than guessing a bound.
      return { quotes: [], text: String(text ?? '') }
    }
    // The regex guarantees all three capture groups, but `noUncheckedIndexedAccess`
    // cannot know that — fall back rather than assert on a `!`.
    quotes.push({
      name: match[1] ?? '',
      offset: Number(match[2] ?? 0),
      chars: Number(match[3] ?? 0),
      text: lines.slice(index + 1, end).join('\n')
    })
    index = end + 1
    if (lines[index] === '') index += 1
  }

  return { quotes, text: lines.slice(index).join('\n') }
}

// ---- card construction --------------------------------------------------

let cardSeq = 0

function nextId(kind: StudioCard['kind']): string {
  cardSeq += 1
  return `${kind}-${cardSeq}`
}

/** Test hook: card ids are only for keying, but tests read better with a reset. */
export function resetCardIds(): void {
  cardSeq = 0
}

export function makeUserCard(text: string): CardUser {
  const { quotes, text: body } = splitQuotes(text)
  return { id: nextId('user'), kind: 'user', text: body, quotes }
}

export function makePendingCard(now: number = Date.now()): CardPending {
  return { id: nextId('pending'), kind: 'pending', startedAt: now, retry: null, softTimeout: false }
}

export function makeNoticeCard(text: string, hint: NoticeHint | null = null): CardNotice {
  return { id: nextId('notice'), kind: 'notice', text, hint }
}

/**
 * Repaint an archived conversation (`agent/history` → `entries`).
 *
 * Same fold as the live stream, because the host emits both through the same
 * entry shapes (`history.entries` documents that on purpose: "与实时事件的字段
 * 保持一致"). `dropped` is surfaced as a leading notice instead of being
 * silently ignored — a trimmed archive that looks complete is a lie.
 */
export function restoreFromHistory(
  entries: readonly AgentEventParams[],
  options: { dropped?: number; savedAt?: string } = {}
): StudioCard[] {
  const cards = entries.reduce<StudioCard[]>((acc, entry) => reduceAgentEvent(acc, entry, ''), [])
  const dropped = options.dropped ?? 0
  if (dropped <= 0) return cards
  return [makeNoticeCard('', { kind: 'historyTrimmed', dropped }), ...cards]
}

function planSteps(raw: Array<Record<string, unknown>> | undefined): PlanStep[] {
  return (raw ?? []).map((step) => ({
    title: String(step.title ?? ''),
    tool: String(step.tool ?? ''),
    detail: String(step.detail ?? ''),
    status: 'pending' as const,
    note: ''
  }))
}

/** Replace one card in place (by id), leaving the rest of the list identical. */
function patch<T extends StudioCard>(
  cards: StudioCard[],
  id: string,
  update: (card: T) => T
): StudioCard[] {
  return cards.map((card) => (card.id === id ? update(card as T) : card))
}

/**
 * Fold one `agent/event` into the card list.
 *
 * Events for another session are dropped: the host serves several sessions and
 * this rail must not paint someone else's turn (the drawer's rule, kept).
 * `final` is not painted either — the answer arrives as the `agent/chat`
 * response, and painting both would duplicate it.
 */
export function reduceAgentEvent(
  cards: StudioCard[],
  params: AgentEventParams,
  sessionId: string
): StudioCard[] {
  if (params.session_id && params.session_id !== sessionId) return cards

  switch (params.type) {
    // `agent/history` speaks the same entry vocabulary as the live stream, so
    // replaying an archived conversation is the same fold (see
    // `restoreFromHistory`). The extra `user` case is the one shape only history
    // sends — live user turns are appended locally, before the host answers.
    case 'user':
      return [...cards, makeUserCard(String(params.text ?? ''))]
    case 'retry': {
      // The only signal that the host is alive but not answering yet; without it
      // a retry looks exactly like a hang.
      const pending = pendingCard(cards)
      if (!pending) return cards
      return patch<CardPending>(cards, pending.id, (card) => ({
        ...card,
        retry: {
          attempt: Number(params.attempt ?? 0),
          total: Number(params.total ?? 0),
          delay: Number(params.delay ?? 0)
        }
      }))
    }
    case 'assistant':
      return [
        ...cards,
        {
          id: nextId('assistant'),
          kind: 'assistant',
          text: String(params.text ?? ''),
          variant: params.variant === 'final' ? 'final' : 'intermediate'
        }
      ]
    case 'tool_call': {
      const callId = params.id == null ? '' : String(params.id)
      const args = params.arguments === undefined ? '' : JSON.stringify(params.arguments, null, 2)
      return [
        ...cards,
        {
          id: nextId('tool'),
          kind: 'tool',
          callId,
          tool: String(params.name ?? ''),
          state: 'running',
          args,
          result: '',
          orphan: false,
          collapsed: false
        }
      ]
    }
    case 'tool_result': {
      const callId = params.id == null ? '' : String(params.id)
      const text = String(params.text ?? '')
      // The host marks tool failures as an "ERROR: ..." text result (see
      // lib/comfy_studio/mcp/result.py) — same convention, same red dot.
      const state: ToolState = text.indexOf('ERROR:') === 0 ? 'error' : 'done'
      const target = cards.find((card) => card.kind === 'tool' && card.callId === callId)
      if (!target) {
        // A result with no call: show it and say so, never drop it silently.
        return [
          ...cards,
          {
            id: nextId('tool'),
            kind: 'tool',
            callId,
            tool: String(params.name ?? ''),
            state,
            args: '',
            result: text,
            orphan: true,
            collapsed: false
          }
        ]
      }
      return patch<CardTool>(cards, target.id, (card) => ({ ...card, state, result: text }))
    }
    case 'ask_user': {
      const callId = String(params.call_id ?? '')
      // Re-sending the same call (host retry) must not stack two cards: the
      // channel is keyed by call_id, so the card is too.
      if (callId && cards.some((card) => card.kind === 'ask' && card.callId === callId)) return cards
      return [
        ...cards,
        {
          id: nextId('ask'),
          kind: 'ask',
          callId,
          question: String(params.question ?? ''),
          options: (params.options ?? []).map((option) => String(option)),
          state: 'waiting',
          answer: '',
          error: ''
        }
      ]
    }
    case 'plan': {
      const callId = String(params.call_id ?? '')
      const existing = cards.find((card) => card.kind === 'plan' && card.callId === callId)
      if (existing) return cards
      return [
        ...cards,
        {
          id: nextId('plan'),
          kind: 'plan',
          callId,
          goal: String(params.goal ?? ''),
          steps: planSteps(params.steps),
          notes: String(params.notes ?? ''),
          state: 'waiting',
          feedback: '',
          error: ''
        }
      ]
    }
    case 'plan_progress': {
      // One-way progress ping: tick the step, nobody is waiting on it.
      const callId = String(params.call_id ?? '')
      const target = cards.find((card) => card.kind === 'plan' && card.callId === callId)
      if (!target) return cards
      const stepIndex = typeof params.step === 'number' ? params.step : -1
      return patch<CardPlan>(cards, target.id, (card) => ({
        ...card,
        steps: card.steps.map((step, index) =>
          index === stepIndex
            ? { ...step, status: normalizeStepStatus(params.status), note: String(params.note ?? '') }
            : step
        )
      }))
    }
    default:
      return cards
  }
}

function normalizeStepStatus(status: string | undefined): PlanStep['status'] {
  if (status === 'running' || status === 'done' || status === 'failed') return status
  return 'pending'
}

/** Append the user's turn and the pending card that follows it. */
export function appendUserTurn(
  cards: StudioCard[],
  text: string,
  now: number = Date.now()
): StudioCard[] {
  return [...cards, makeUserCard(text), makePendingCard(now)]
}

/** Outcome of an `agent/chat` round. `cancelled` is a normal answer, and a busy
 *  session means this turn never started at all. */
export type TurnOutcome =
  | { kind: 'assistant'; text: string }
  | { kind: 'stopped'; reason?: string }
  | { kind: 'error'; text: string; code?: number | null }
  | { kind: 'notice'; text: string }

/** Drop the pending card and close the turn with its result. */
export function settleTurn(cards: StudioCard[], outcome: TurnOutcome): StudioCard[] {
  const withoutPending = cards.filter((card) => card.kind !== 'pending')
  switch (outcome.kind) {
    case 'assistant':
      return [
        ...withoutPending,
        { id: nextId('assistant'), kind: 'assistant', text: outcome.text, variant: 'final' }
      ]
    case 'stopped':
      return [
        ...withoutPending,
        { id: nextId('stopped'), kind: 'stopped', reason: outcome.reason ?? '' }
      ]
    case 'error':
      return [
        ...withoutPending,
        { id: nextId('error'), kind: 'error', text: outcome.text, code: outcome.code ?? null }
      ]
    case 'notice':
      return [...withoutPending, makeNoticeCard(outcome.text)]
  }
}

/** Newest pending card, if a turn is in flight. */
export function pendingCard(cards: readonly StudioCard[]): CardPending | null {
  for (let index = cards.length - 1; index >= 0; index -= 1) {
    const card = cards[index]
    if (card !== undefined && card.kind === 'pending') return card
  }
  return null
}

/** The rich control card (ask / plan) the host is currently blocked on, if any.
 *  Used to keep those cards above the fold and to enable their buttons. */
export function blockingCards(cards: readonly StudioCard[]): Array<CardAsk | CardPlan> {
  return cards.filter(
    (card): card is CardAsk | CardPlan =>
      (card.kind === 'ask' && card.state === 'waiting') ||
      (card.kind === 'plan' && (card.state === 'waiting' || card.state === 'editing'))
  )
}

export function setCardById<T extends StudioCard>(
  cards: StudioCard[],
  id: string,
  update: (card: T) => T
): StudioCard[] {
  return patch<T>(cards, id, update)
}
