<script setup lang="ts">
/**
 * The conversation rail — the studio's permanent left column.
 *
 * It is the one surface that never gets switched away, so it owns three things:
 * which conversation is open, the message stream, and the composer. Scroll
 * behaviour is the subtle part: the stream follows new cards only while the user
 * is already at the bottom, otherwise it stays put and offers a jump button —
 * yanking the view down while someone reads history is the classic bug here.
 *
 * `StudioRailSetup` sits between the session controls and the stream: the model
 * and agent answer *who* is talking, which is a property of the conversation
 * rather than of a page, so it belongs in the column that never leaves.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, ChevronUp, Plus, Search, Trash2, X } from 'lucide-vue-next'
import { useConversationStore, copyText } from '../stores/conversationStore'
import { useStudioStore } from '../stores/studioStore'
import StudioComposer from './StudioComposer.vue'
import StudioMessage from './StudioMessage.vue'
import StudioRailSetup from './StudioRailSetup.vue'

const { t } = useI18n()
const conversation = useConversationStore()
const studio = useStudioStore()

const stream = ref<HTMLElement | null>(null)
const composer = ref<InstanceType<typeof StudioComposer> | null>(null)
const findInput = ref<HTMLInputElement | null>(null)
const stick = ref(true)
const findOpen = ref(false)
const resetArmed = ref(false)
const copied = ref(false)

/** Typing is pointless against a host that is down, so the composer says why
 *  instead of accepting text that every send would fail on. `unknown` (still
 *  probing) stays enabled: blocking a working host over a race is worse. */
const hostReady = computed(
  () => studio.hostState !== 'unavailable' && studio.hostState !== 'stopped'
)

/** Sessions newest-first, the live one always on top: the picker is used to go
 *  back to what you were just doing far more often than to browse. */
const sessionOptions = computed(() => {
  const rows = [...conversation.sessions]
  rows.sort((a, b) => (a.savedAt < b.savedAt ? 1 : a.savedAt > b.savedAt ? -1 : 0))
  return rows
})

function sessionLabel(row: { title: string; messages: number; busy: boolean; error: string | null }): string {
  const title = row.title || t('studio.rail.untitled')
  const parts = [title]
  if (row.messages > 0) parts.push(t('studio.rail.messageCount', { n: row.messages }))
  if (row.busy) parts.push(t('studio.rail.busy'))
  if (row.error) parts.push(t('studio.rail.broken'))
  return parts.join(' · ')
}

function onScroll(): void {
  const element = stream.value
  if (!element) return
  // 24px of slack: a card wrapping to the next line must not unstick the view.
  stick.value = element.scrollHeight - element.scrollTop - element.clientHeight < 24
}

function scrollToBottom(): void {
  const element = stream.value
  if (!element) return
  element.scrollTop = element.scrollHeight
}

watch(
  () => conversation.cards.length,
  async () => {
    if (!stick.value) return
    await nextTick()
    scrollToBottom()
  }
)

/** Keep the asked question in view: it is the only card that needs an answer,
 *  so it must not be possible to miss it by not scrolling. */
watch(
  () => conversation.turnPending?.id,
  async (id) => {
    if (!id) return
    await nextTick()
    if (stick.value) scrollToBottom()
  }
)

// Jump to the card a find hit lives in.
watch(
  () => conversation.activeHit,
  async (hit) => {
    if (!hit) return
    await nextTick()
    const element = stream.value?.querySelector(`[data-card-id="${hit.cardId}"]`)
    element?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
)

function send(): void {
  const text = conversation.draft
  conversation.send(text)
}

async function copy(cardId: string): Promise<void> {
  const card = conversation.cards.find((entry) => entry.id === cardId)
  if (!card) return
  try {
    await navigator.clipboard.writeText(copyText(card))
    copied.value = true
    setTimeout(() => (copied.value = false), 1200)
  } catch {
    // Clipboard can be denied; the message stays selectable, so this is not
    // worth an error banner.
  }
}

/** Pull a message back into the composer, quotes included — "改一下" is how the
 *  user fixes a bad prompt without retyping the passage they selected. */
function reuse(cardId: string): void {
  const card = conversation.cards.find((entry) => entry.id === cardId)
  if (!card || card.kind !== 'user') return
  conversation.clearQuotes()
  for (const quote of card.quotes) conversation.addQuote(quote)
  conversation.setDraft(card.text)
  void composer.value?.focus()
}

function onGlobalKeydown(event: KeyboardEvent): void {
  const accel = event.ctrlKey || event.metaKey
  if (accel && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    findOpen.value = true
    void nextTick(() => findInput.value?.focus())
    return
  }
  if (event.key === 'Escape' && findOpen.value) {
    findOpen.value = false
    conversation.clearFind()
  }
}

async function resetSession(): Promise<void> {
  if (!resetArmed.value) {
    // Two-step instead of a modal: destructive, but reversible in one click.
    resetArmed.value = true
    setTimeout(() => (resetArmed.value = false), 4000)
    return
  }
  resetArmed.value = false
  await conversation.resetSession()
}

function onSessionPick(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value) void conversation.switchSession(value)
}

/** Typing in the find box re-searches from the top — stepping is only meaningful
 *  for a query the user has stopped editing. */
function onFindInput(event: Event): void {
  conversation.setFindQuery((event.target as HTMLInputElement).value)
}

function closeFind(): void {
  findOpen.value = false
  conversation.clearFind()
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<template>
  <div class="rail">
    <header class="rail__head">
      <select
        class="rail__sessions"
        :value="conversation.sessionId"
        :title="t('studio.rail.sessions')"
        @change="onSessionPick"
      >
        <option v-if="!sessionOptions.some((row) => row.sessionId === conversation.sessionId)" :value="conversation.sessionId">
          {{ t('studio.rail.current') }}
        </option>
        <option v-for="row in sessionOptions" :key="row.sessionId" :value="row.sessionId">
          {{ sessionLabel(row) }}
        </option>
      </select>
      <button type="button" :title="t('studio.rail.new')" @click="conversation.newSession()">
        <Plus :size="14" />
      </button>
      <button
        type="button"
        :class="{ 'is-armed': resetArmed }"
        :title="resetArmed ? t('studio.rail.resetConfirm') : t('studio.rail.reset')"
        @click="resetSession()"
      >
        <Trash2 :size="14" />
      </button>
      <button
        type="button"
        :class="{ 'is-active': findOpen }"
        :title="t('studio.rail.find')"
        @click="findOpen = !findOpen"
      >
        <Search :size="14" />
      </button>
    </header>

    <div v-if="findOpen" class="rail__find">
      <input
        ref="findInput"
        class="rail__find-input"
        type="search"
        :value="conversation.findQuery"
        :placeholder="t('studio.rail.findPlaceholder')"
        @input="onFindInput"
        @keydown.enter.prevent="conversation.stepFind($event.shiftKey ? -1 : 1)"
      />
      <span class="rail__find-count">
        {{ conversation.hits.length ? `${conversation.findIndex + 1}/${conversation.hits.length}` : t('studio.rail.findEmpty') }}
      </span>
      <button type="button" :title="t('studio.rail.findPrev')" @click="conversation.stepFind(-1)">
        <ChevronUp :size="13" />
      </button>
      <button type="button" :title="t('studio.rail.findNext')" @click="conversation.stepFind(1)">
        <ChevronDown :size="13" />
      </button>
      <button type="button" :title="t('studio.rail.findClose')" @click="closeFind()">
        <X :size="13" />
      </button>
    </div>

    <StudioRailSetup />

    <div ref="stream" class="rail__stream" @scroll.passive="onScroll">
      <p v-if="conversation.loadingHistory" class="rail__loading">{{ t('studio.rail.loading') }}</p>

      <template v-else-if="conversation.cards.length === 0">
        <div class="rail__empty">
          <p class="rail__empty-title">{{ t('studio.rail.emptyTitle') }}</p>
          <p class="rail__empty-body">{{ t('studio.rail.emptyBody') }}</p>
        </div>
      </template>

      <template v-else>
        <StudioMessage
          v-for="card in conversation.cards"
          :key="card.id"
          :card="card"
          :highlighted="conversation.activeHit?.cardId === card.id"
          @copy="copy"
          @reuse="reuse"
          @answer="conversation.answerAsk"
          @decide="conversation.decidePlan"
          @edit-plan="conversation.editPlan"
          @unlock="conversation.unlockTurn()"
        />
      </template>
    </div>

    <button v-if="!stick && conversation.cards.length" type="button" class="rail__jump" @click="((stick = true), scrollToBottom())">
      {{ t('studio.rail.jumpToLatest') }}
    </button>

    <StudioComposer
      ref="composer"
      :model-value="conversation.draft"
      :quotes="conversation.quotes"
      :sending="conversation.sending"
      :cancelling="conversation.cancelling"
      :disabled="!hostReady"
      @update:model-value="conversation.setDraft"
      @send="send"
      @cancel="conversation.cancelTurn()"
      @remove-quote="conversation.removeQuote"
    />

    <span v-if="copied" class="rail__toast">{{ t('studio.card.copied') }}</span>
  </div>
</template>

<style scoped>
.rail {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.rail__head {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 8px;
  border-bottom: 1px solid var(--border);
}

.rail__sessions {
  flex: 1;
  min-width: 0;
  height: 22px;
  padding: 0 4px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.rail__sessions:hover {
  border-color: var(--border);
  color: var(--text);
}

.rail__head button,
.rail__find button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: none;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
}

.rail__head button:hover,
.rail__find button:hover {
  color: var(--text);
}

.rail__head button.is-active,
.rail__head button.is-armed {
  color: var(--danger);
}

.rail__find {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
}

.rail__find-input {
  flex: 1;
  min-width: 0;
  height: 22px;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.rail__find-count {
  flex: none;
  color: var(--text-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.rail__stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
}

.rail__loading {
  margin: 0;
  color: var(--text-faint);
  font-size: 12px;
}

.rail__empty {
  margin: auto 0;
  padding: 16px 4px;
}

.rail__empty-title {
  margin: 0 0 4px;
  color: var(--text);
  font-size: 13px;
}

.rail__empty-body {
  margin: 0;
  color: var(--text-faint);
  font-size: 12px;
  line-height: 1.6;
}

.rail__jump {
  position: absolute;
  left: 50%;
  bottom: 108px;
  transform: translateX(-50%);
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--studio-card-bg);
  color: var(--text-muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.rail__jump:hover {
  color: var(--text);
}

.rail__toast {
  position: absolute;
  right: 12px;
  bottom: 108px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--studio-card-bg);
  color: var(--text-muted);
  font-size: 11px;
}

.rail__sessions:focus-visible,
.rail__find-input:focus-visible,
.rail__head button:focus-visible,
.rail__find button:focus-visible,
.rail__jump:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
</style>
