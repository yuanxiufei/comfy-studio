import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  ComfyStudioEventMessage,
  ComfyStudioRequestResult
} from '../../../types/comfyDesktopBridge'
import { useStudioStore } from './studioStore'
import {
  MAX_QUOTES,
  SESSION_STORAGE_KEY,
  TURN_SOFT_TIMEOUT_S,
  type AgentEventParams,
  type CardAsk,
  type CardPlan,
  type QuoteRef,
  type StudioCard,
  appendUserTurn,
  composeQuotes,
  draftKey,
  makePendingCard,
  newSessionId,
  pendingCard,
  reduceAgentEvent,
  restoreFromHistory,
  setCardById,
  settleTurn
} from '../studio/conversation'

/** One row of `agent/sessions` — a conversation the user can switch to. */
export interface StudioSessionRow {
  sessionId: string
  title: string
  messages: number
  /** Alive in the host right now (has an HTTP client and is cheap to resume). */
  live: boolean
  /** A turn is running. The rail must not offer "send" for it. */
  busy: boolean
  savedAt: string
  file: string
  /** Non-null for an archive the host could not read: shown as a row that says
   *  which file to fix, never silently dropped from the list. */
  error: string | null
}

/**
 * Sentences the store itself has to produce. Injected at `init` instead of
 * imported, because the model layer and this controller hold no user-facing
 * prose — the panel is bilingual and only the components know the locale.
 */
export interface ConversationMessages {
  /** Shown on the stopped card when a turn was cancelled. */
  turnCancelled: string
  /** Shown after the user manually unlocks a turn that stopped answering. */
  turnUnlocked: string
}

/** Where a find hit lives: one card, and which occurrence inside it. */
export interface FindHit {
  cardId: string
  occurrence: number
}

/** How often the soft-timeout check runs. Coarse on purpose: it only decides
 *  when to offer the user an escape hatch, so a few seconds of lag is fine and
 *  a per-second timer for a 5-minute deadline would be pure waste. */
const SOFT_TIMEOUT_TICK_MS = 5000

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    // Storage can be denied; a missing draft is a smaller problem than a crash.
    return null
  }
}

/** Every string a card may be searched for. Used by find and by copy. */
export function searchableText(card: StudioCard): string {
  switch (card.kind) {
    case 'user':
    case 'assistant':
    case 'notice':
    case 'error':
      return card.text
    case 'stopped':
      return card.reason
    case 'tool':
      return [card.tool, card.args, card.result].join('\n')
    case 'ask':
      return [card.question, card.options.join('\n'), card.answer].join('\n')
    case 'plan':
      return [card.goal, card.notes, ...card.steps.map((s) => `${s.title} ${s.detail} ${s.note}`)].join(
        '\n'
      )
    case 'pending':
      return ''
  }
}

/** Plain text of a card, for "copy this message" — not for find. */
export function copyText(card: StudioCard): string {
  switch (card.kind) {
    case 'user':
      if (card.quotes.length === 0) return card.text
      return composeQuotes(card.text, card.quotes)
    default:
      return searchableText(card)
  }
}

export const useConversationStore = defineStore('studioConversation', () => {
  const studio = useStudioStore()

  const sessionId = ref('')
  const cards = ref<StudioCard[]>([])
  const quotes = ref<QuoteRef[]>([])
  const sending = ref(false)
  const cancelling = ref(false)
  const loadingHistory = ref(false)
  const sessions = ref<StudioSessionRow[]>([])
  const error = ref<string | null>(null)
  const messages = ref<ConversationMessages>({ turnCancelled: '', turnUnlocked: '' })

  // Find-in-conversation. `index` counts hits, not cards: a query can appear
  // twice in one message and the user expects to step through both.
  const findQuery = ref('')
  const findIndex = ref(0)

  let unsubscribe: (() => void) | null = null
  let ticker: ReturnType<typeof setInterval> | null = null

  const hits = computed<FindHit[]>(() => {
    const query = findQuery.value.trim().toLowerCase()
    if (query === '') return []
    const found: FindHit[] = []
    for (const card of cards.value) {
      const haystack = searchableText(card).toLowerCase()
      if (haystack === '') continue
      let from = haystack.indexOf(query)
      let occurrence = 0
      while (from !== -1) {
        found.push({ cardId: card.id, occurrence })
        occurrence += 1
        from = haystack.indexOf(query, from + query.length)
      }
    }
    return found
  })

  const activeHit = computed<FindHit | null>(() => hits.value[findIndex.value] ?? null)

  const turnPending = computed(() => pendingCard(cards.value))

  // ---- drafts ------------------------------------------------------------

  const draft = ref('')
  let draftTimer: ReturnType<typeof setTimeout> | null = null

  /** Send stays disabled on an empty draft: the host rejects empty text, and a
   *  round-trip to learn that is a worse answer than a greyed-out button. */
  const canSend = computed(() => !sending.value && draft.value.trim().length > 0)

  /** Write the draft through on a short debounce: keystrokes are not worth a
   *  synchronous localStorage write each, and a closed panel must not lose the
   *  last sentence. */
  function setDraft(text: string): void {
    draft.value = text
    const key = sessionId.value
    if (!key) return
    if (draftTimer) clearTimeout(draftTimer)
    draftTimer = setTimeout(() => {
      draftTimer = null
      storage()?.setItem(draftKey(key), text)
    }, 300)
  }

  function flushDraft(): void {
    if (draftTimer) {
      clearTimeout(draftTimer)
      draftTimer = null
    }
    if (sessionId.value) storage()?.setItem(draftKey(sessionId.value), draft.value)
  }

  function loadDraft(key: string): string {
    return storage()?.getItem(draftKey(key)) ?? ''
  }

  // ---- quotes ------------------------------------------------------------

  function addQuote(quote: QuoteRef): boolean {
    if (quotes.value.length >= MAX_QUOTES) return false
    quotes.value = [...quotes.value, quote]
    return true
  }

  function removeQuote(index: number): void {
    quotes.value = quotes.value.filter((_, position) => position !== index)
  }

  function clearQuotes(): void {
    quotes.value = []
  }

  // ---- history & sessions -------------------------------------------------

  /**
   * Host calls that can never reject.
   *
   * The bridge normally resolves to the host's `{ ok, error }` envelope, but a
   * dead IPC channel rejects instead — and a rejection escaping into `send`
   * would leave the rail spinning on a pending card forever. Every call goes
   * through here so that case becomes an ordinary failed result.
   */
  async function safeRequest(
    method: string,
    params: Record<string, unknown> = {}
  ): Promise<ComfyStudioRequestResult> {
    const call: Promise<ComfyStudioRequestResult> = studio.request(method, params)
    try {
      return await call
    } catch (caught) {
      return {
        ok: false,
        error: { message: caught instanceof Error ? caught.message : String(caught) }
      }
    }
  }

  async function unwrap<T>(result: ComfyStudioRequestResult): Promise<T | null> {
    if (result.ok) return result.result as T
    error.value = result.error.message
    return null
  }

  async function refreshSessions(): Promise<void> {
    const payload = await unwrap<{ sessions?: unknown }>(await safeRequest('agent/sessions'))
    const rows = Array.isArray(payload?.sessions) ? payload.sessions : []
    sessions.value = rows.map((row) => {
      const item = row as Record<string, unknown>
      return {
        sessionId: String(item.session_id ?? ''),
        title: String(item.title ?? ''),
        messages: Number(item.messages ?? 0),
        live: item.live === true,
        busy: item.busy === true,
        savedAt: String(item.saved_at ?? ''),
        file: String(item.file ?? ''),
        error: typeof item.error === 'string' ? item.error : null
      }
    })
  }

  /** Repaint the current session from the host. */
  async function loadHistory(): Promise<void> {
    if (!sessionId.value) return
    loadingHistory.value = true
    try {
      const payload = await unwrap<{
        entries?: unknown
        dropped?: unknown
        saved_at?: unknown
      }>(await safeRequest('agent/history', { session_id: sessionId.value }))
      if (payload === null) {
        // A broken archive is reported by the host with its file path — showing
        // that beats pretending the conversation never happened.
        cards.value = []
        return
      }
      const entries = Array.isArray(payload.entries)
        ? (payload.entries as AgentEventParams[])
        : []
      cards.value = restoreFromHistory(entries, {
        dropped: Number(payload.dropped ?? 0),
        savedAt: String(payload.saved_at ?? '')
      })
    } finally {
      loadingHistory.value = false
    }
  }

  /** Take over a turn that is already running in the host (the panel was closed
   *  and reopened mid-turn). Without this the rail would look idle while the
   *  host holds the session, and every send would come back "已有一轮在跑". */
  function attachRunningTurn(): void {
    const row = sessions.value.find((item) => item.sessionId === sessionId.value)
    if (!row?.busy || turnPending.value) return
    cards.value = [...cards.value, makePendingCard()]
    sending.value = true
  }

  async function switchSession(next: string): Promise<void> {
    if (next === sessionId.value) return
    flushDraft()
    disposeSubscription()
    sessionId.value = next
    storage()?.setItem(SESSION_STORAGE_KEY, next)
    cards.value = []
    quotes.value = []
    draft.value = loadDraft(next)
    sending.value = false
    cancelling.value = false
    clearFind()
    subscribe()
    await refreshSessions()
    await loadHistory()
    attachRunningTurn()
  }

  function newSession(): void {
    void switchSession(newSessionId())
  }

  /** Delete the conversation (archive included) and start a clean one. */
  async function resetSession(): Promise<void> {
    if (!sessionId.value) return
    await safeRequest('agent/reset', { session_id: sessionId.value })
    storage()?.removeItem(draftKey(sessionId.value))
    draft.value = ''
    cards.value = []
    quotes.value = []
    await refreshSessions()
  }

  /** Let go of a conversation without deleting it: it stays in the archive and
   *  can be resumed by id later. */
  async function closeSession(): Promise<void> {
    if (!sessionId.value) return
    await safeRequest('agent/close', { session_id: sessionId.value })
    await refreshSessions()
  }

  // ---- events -------------------------------------------------------------

  function onEvent(message: ComfyStudioEventMessage): void {
    if (message.installationId !== studio.installationId) return
    if (message.method !== 'agent/event') return
    const params = message.params as AgentEventParams
    const next = reduceAgentEvent(cards.value, params, sessionId.value)
    if (next !== cards.value) cards.value = next
  }

  function subscribe(): void {
    if (unsubscribe) return
    unsubscribe = window.api.onStudioEvent(onEvent)
  }

  function disposeSubscription(): void {
    unsubscribe?.()
    unsubscribe = null
  }

  /** Offer the user a way out of a turn that went quiet. It does not touch the
   *  host: the pending card is dropped and the composer unlocks, so the UI can
   *  never be held hostage by a dead connection. */
  function unlockTurn(): void {
    if (!turnPending.value) return
    cards.value = settleTurn(cards.value, { kind: 'notice', text: messages.value.turnUnlocked })
    sending.value = false
    cancelling.value = false
  }

  function tickSoftTimeout(): void {
    const pending = turnPending.value
    if (!pending || pending.softTimeout) return
    if (Date.now() - pending.startedAt < TURN_SOFT_TIMEOUT_S * 1000) return
    cards.value = setCardById(cards.value, pending.id, (card) => ({ ...card, softTimeout: true }))
  }

  // ---- the turn -----------------------------------------------------------

  async function send(text: string): Promise<void> {
    const body = text.trim()
    if (body === '' || sending.value || !sessionId.value) return
    // Quotes ride in the message text (see `composeQuotes`): the host stores one
    // string, and history replays it back into the same blocks.
    const composed = composeQuotes(body, quotes.value)
    const session = sessionId.value

    cards.value = appendUserTurn(cards.value, composed)
    quotes.value = []
    setDraft('')
    sending.value = true
    cancelling.value = false
    error.value = null

    const result = await safeRequest('agent/chat', { text: composed, session_id: session })
    // A turn that the user cancelled, or one whose session was closed while it
    // ran, still resolves here — never leave the pending card spinning.
    const payload = result.ok
      ? (result.result as { text?: unknown; cancelled?: unknown } | null)
      : null

    if (result.ok && payload) {
      if (payload.cancelled === true) {
        cards.value = settleTurn(cards.value, {
          kind: 'stopped',
          reason: messages.value.turnCancelled
        })
      } else {
        cards.value = settleTurn(cards.value, { kind: 'assistant', text: String(payload.text ?? '') })
      }
    } else if (!result.ok) {
      cards.value = settleTurn(cards.value, {
        kind: 'error',
        text: result.error.message,
        code: result.error.code ?? null
      })
    }
    sending.value = false
    cancelling.value = false
    void refreshSessions()
  }

  async function cancelTurn(): Promise<void> {
    if (!sending.value || cancelling.value) return
    cancelling.value = true
    // The `agent/chat` promise resolves with `cancelled: true` and settles the
    // cards, so nothing is written here on purpose — two writers, one card.
    await safeRequest('agent/cancel', { session_id: sessionId.value })
  }

  // ---- the two blocking channels -----------------------------------------

  async function answerAsk(cardId: string, answer: string): Promise<void> {
    const card = cards.value.find((entry): entry is CardAsk => entry.id === cardId)
    if (!card || card.state !== 'waiting') return
    cards.value = setCardById<CardAsk>(cards.value, cardId, (entry) => ({
      ...entry,
      state: 'sending',
      error: ''
    }))
    const result = await safeRequest('agent/answer', { call_id: card.callId, answer })
    if (!result.ok) {
      cards.value = setCardById<CardAsk>(cards.value, cardId, (entry) => ({
        ...entry,
        state: 'failed',
        error: result.error.message
      }))
      return
    }
    const delivered = (result.result as { delivered?: unknown } | null)?.delivered === true
    cards.value = setCardById<CardAsk>(cards.value, cardId, (entry) => ({
      // Delivered false means the turn stopped waiting (timeout, cancel). Not an
      // error — but the user must see that nobody heard them.
      ...entry,
      state: delivered ? 'answered' : 'stale',
      answer
    }))
  }

  async function decidePlan(cardId: string, approved: boolean, feedback = ''): Promise<void> {
    const card = cards.value.find((entry): entry is CardPlan => entry.id === cardId)
    if (!card || (card.state !== 'waiting' && card.state !== 'editing')) return
    cards.value = setCardById<CardPlan>(cards.value, cardId, (entry) => ({
      ...entry,
      state: 'sending',
      error: '',
      feedback
    }))
    const result = await safeRequest('agent/plan_result', {
      call_id: card.callId,
      approved,
      feedback
    })
    if (!result.ok) {
      cards.value = setCardById<CardPlan>(cards.value, cardId, (entry) => ({
        ...entry,
        // Back to `editing` so the verdict can be retried — the host rejects an
        // empty feedback on a rejection, and that is a fixable input error.
        state: 'editing',
        error: result.error.message
      }))
      return
    }
    const delivered = (result.result as { delivered?: unknown } | null)?.delivered === true
    cards.value = setCardById<CardPlan>(cards.value, cardId, (entry) => ({
      ...entry,
      state: delivered ? (approved ? 'approved' : 'rejected') : 'stale',
      feedback
    }))
  }

  /** Put a plan card into edit mode so its steps can be reworked before it is
   *  approved. Nothing is sent: the host stays blocked on this call. */
  function editPlan(cardId: string): void {
    cards.value = setCardById<CardPlan>(cards.value, cardId, (entry) => ({
      ...entry,
      state: 'editing',
      error: ''
    }))
  }

  // ---- find ---------------------------------------------------------------

  function setFindQuery(query: string): void {
    findQuery.value = query
    findIndex.value = 0
  }

  function stepFind(delta: number): void {
    const total = hits.value.length
    if (total === 0) return
    findIndex.value = (findIndex.value + delta + total) % total
  }

  function clearFind(): void {
    findQuery.value = ''
    findIndex.value = 0
  }

  // ---- lifecycle ----------------------------------------------------------

  async function init(copy: ConversationMessages): Promise<void> {
    messages.value = copy
    const key = storage()?.getItem(SESSION_STORAGE_KEY) || newSessionId()
    sessionId.value = key
    storage()?.setItem(SESSION_STORAGE_KEY, key)
    draft.value = loadDraft(key)
    subscribe()
    if (!ticker) ticker = setInterval(tickSoftTimeout, SOFT_TIMEOUT_TICK_MS)
    // Status first: `agent/history` on a stopped host would only produce an
    // error card before the user ever typed anything.
    await studio.refreshStatus()
    if (studio.hostState === 'unavailable' || studio.hostState === 'stopped') return
    await refreshSessions()
    await loadHistory()
    attachRunningTurn()
  }

  function dispose(): void {
    flushDraft()
    disposeSubscription()
    if (ticker) clearInterval(ticker)
    ticker = null
  }

  return {
    sessionId,
    cards,
    quotes,
    draft,
    sending,
    cancelling,
    loadingHistory,
    sessions,
    error,
    findQuery,
    findIndex,
    hits,
    activeHit,
    turnPending,
    canSend,
    setDraft,
    flushDraft,
    addQuote,
    removeQuote,
    clearQuotes,
    refreshSessions,
    loadHistory,
    switchSession,
    newSession,
    resetSession,
    closeSession,
    send,
    cancelTurn,
    unlockTurn,
    answerAsk,
    decidePlan,
    editPlan,
    setFindQuery,
    stepFind,
    clearFind,
    init,
    dispose
  }
})
