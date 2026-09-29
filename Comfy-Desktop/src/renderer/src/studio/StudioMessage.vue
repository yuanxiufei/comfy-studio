<script setup lang="ts">
/**
 * Renders one conversation card.
 *
 * The dispatcher and the five simple kinds live together because they share one
 * layout rhythm (everything the user reads as prose); the three *control* kinds
 * — tool, ask, plan — are separate components, since they own real interaction
 * and a state machine of their own.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Copy, LoaderCircle, OctagonAlert, Pencil, Quote } from 'lucide-vue-next'
import type { CardNotice, StudioCard } from './conversation'
import StudioAskCard from './cards/StudioAskCard.vue'
import StudioPlanCard from './cards/StudioPlanCard.vue'
import StudioToolCard from './cards/StudioToolCard.vue'

const props = defineProps<{
  card: StudioCard
  /** Find highlight for this card, if the query hit it. */
  highlighted?: boolean
}>()

const emit = defineEmits<{
  answer: [cardId: string, value: string]
  decide: [cardId: string, approved: boolean, feedback: string]
  editPlan: [cardId: string]
  copy: [cardId: string]
  reuse: [cardId: string]
  /** Escape hatch offered on a pending card that went quiet. */
  unlock: []
}>()

const { t } = useI18n()

// A pending card shows how long it has been quiet — the number is what turns
// "is it stuck?" into a decision the user can make.
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  if (props.card.kind === 'pending') timer = setInterval(() => (now.value = Date.now()), 1000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const elapsed = computed(() => {
  if (props.card.kind !== 'pending') return 0
  return Math.max(0, Math.round((now.value - props.card.startedAt) / 1000))
})

/** Notice lines are either the host's own words or a condition the rail
 *  explains itself (`hint`) — the second kind is what makes trims visible. */
const noticeText = computed(() => {
  const card = props.card
  if (card.kind !== 'notice') return ''
  if (card.hint?.kind === 'historyTrimmed') {
    return t('studio.card.historyTrimmed', { n: card.hint.dropped })
  }
  return card.text
})

function notice(card: CardNotice): card is CardNotice & { hint: { kind: 'historyTrimmed' } } {
  return card.hint?.kind === 'historyTrimmed'
}
</script>

<template>
  <div class="msg" :class="[`msg--${card.kind}`, { 'is-hit': highlighted }]" :data-card-id="card.id">
    <!-- The user's own turn: words plus the passages they quoted. -->
    <template v-if="card.kind === 'user'">
      <div class="bubble">
        <div v-if="card.quotes.length" class="quotes">
          <div v-for="(quote, index) in card.quotes" :key="index" class="quote">
            <span class="quote__head">
              <Quote :size="12" />
              {{ quote.name }} · {{ quote.offset }}–{{ quote.offset + quote.chars }}
            </span>
            <span class="quote__text">{{ quote.text }}</span>
          </div>
        </div>
        <p v-if="card.text" class="bubble__text">{{ card.text }}</p>
      </div>
      <div class="actions">
        <button type="button" :title="t('studio.card.copy')" @click="emit('copy', card.id)">
          <Copy :size="12" />
        </button>
        <button type="button" :title="t('studio.card.reuse')" @click="emit('reuse', card.id)">
          <Pencil :size="12" />
        </button>
      </div>
    </template>

    <!-- The answer (`final`) and the narration that led to it (`intermediate`). -->
    <template v-else-if="card.kind === 'assistant'">
      <p class="prose" :class="{ 'is-narration': card.variant === 'intermediate' }">{{ card.text }}</p>
      <div v-if="card.variant === 'final'" class="actions">
        <button type="button" :title="t('studio.card.copy')" @click="emit('copy', card.id)">
          <Copy :size="12" />
        </button>
      </div>
    </template>

    <!-- In flight. Silence is explained (retry back-off) and escapable (unlock). -->
    <template v-else-if="card.kind === 'pending'">
      <div class="pending">
        <LoaderCircle :size="14" class="is-spinning" />
        <span>{{ t('studio.card.pending.working') }} {{ elapsed }}s</span>
        <button
          v-if="card.softTimeout"
          type="button"
          class="pending__unlock"
          :title="t('studio.card.pending.unlockHint')"
          @click="emit('unlock')"
        >
          {{ t('studio.card.pending.unlock') }}
        </button>
      </div>
      <p v-if="card.retry" class="pending__retry">
        {{ t('studio.card.pending.retry', { delay: card.retry.delay, attempt: card.retry.attempt, total: card.retry.total }) }}
      </p>
    </template>

    <p v-else-if="card.kind === 'stopped'" class="stopped">{{ t('studio.card.stopped') }}：{{ card.reason }}</p>

    <div v-else-if="card.kind === 'error'" class="error">
      <OctagonAlert :size="14" />
      <span class="error__text">{{ card.text }}</span>
      <span v-if="card.code !== null" class="error__code">{{ card.code }}</span>
    </div>

    <p v-else-if="card.kind === 'notice'" class="notice" :class="{ 'is-hint': notice(card) }">
      {{ noticeText }}
    </p>

    <StudioToolCard v-else-if="card.kind === 'tool'" :card="card" />

    <StudioAskCard v-else-if="card.kind === 'ask'" :card="card" @answer="(value) => emit('answer', card.id, value)" />

    <StudioPlanCard
      v-else-if="card.kind === 'plan'"
      :card="card"
      @decide="(approved, feedback) => emit('decide', card.id, approved, feedback)"
      @edit="emit('editPlan', card.id)"
    />
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* Find hit: the rail scrolls to this card, and a left rule is enough to spot it
 * without repainting the text inside (which would need markup splitting). */
.msg.is-hit {
  border-left: 2px solid var(--warning);
  padding-left: 8px;
  margin-left: -10px;
}

.msg--user .bubble {
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--studio-card-bg);
}

.bubble__text {
  margin: 0;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.quotes {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 6px;
}

.quote {
  padding: 6px 8px;
  border-left: 2px solid var(--accent);
  border-radius: 0 6px 6px 0;
  background: var(--studio-rail-bg);
}

.quote__head {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-faint);
  font-size: 11px;
}

.quote__text {
  display: block;
  margin-top: 2px;
  max-height: 96px;
  overflow: auto;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.prose {
  margin: 0;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.prose.is-narration {
  padding-left: 8px;
  border-left: 2px solid var(--studio-card-border);
  color: var(--text-muted);
  font-size: 12px;
}

.pending {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.pending__unlock {
  margin-left: auto;
  padding: 2px 8px;
  border: 1px solid var(--warning);
  border-radius: 999px;
  background: transparent;
  color: var(--warning);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.pending__retry {
  margin: 4px 0 0 22px;
  color: var(--warning);
  font-size: 11px;
}

.stopped {
  margin: 0;
  color: var(--text-faint);
  font-size: 12px;
}

.error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--danger);
  border-radius: 8px;
  color: var(--danger);
  font-size: 12px;
}

.error__text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
  white-space: pre-wrap;
}

.error__code {
  flex: none;
  color: var(--text-faint);
}

.notice {
  margin: 0;
  color: var(--text-faint);
  font-size: 12px;
}

.notice.is-hint {
  color: var(--warning);
}

.actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 120ms ease;
}

/* Actions appear on hover *and* on focus-within, so they stay reachable by
 * keyboard — a hover-only control is invisible to anyone tabbing through. */
.msg:hover .actions,
.msg:focus-within .actions {
  opacity: 1;
}

.actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
}

.actions button:hover {
  color: var(--text);
}

.actions button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
  opacity: 1;
}

.is-spinning {
  animation: msg-spin 900ms linear infinite;
}

@keyframes msg-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }

  .actions {
    transition: none;
  }
}
</style>
