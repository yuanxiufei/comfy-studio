<script setup lang="ts">
/**
 * The host's `review__ask_user` card: a turn is parked until the user answers.
 *
 * This is a blocking channel, so every state has to be legible: parked, sending,
 * answered — and `stale`, which is the one the drawer got wrong. Answering after
 * the turn stopped waiting is *not* an error, but the user must be told their
 * answer went nowhere, otherwise they believe they are still driving the turn.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessageSquare } from 'lucide-vue-next'
import type { CardAsk } from '../conversation'

const props = defineProps<{
  card: CardAsk
}>()

const emit = defineEmits<{
  answer: [value: string]
}>()

const { t } = useI18n()
const custom = ref('')

/** Options are one click *and* the answer is final — the host resolves the call
 *  on the first delivery, so offering them twice would be a lie. */
const interactive = computed(() => props.card.state === 'waiting' || props.card.state === 'failed')
const statusLabel = computed(() => t(`studio.card.ask.state.${props.card.state}`))

function submitCustom(): void {
  const value = custom.value.trim()
  if (value === '' || !interactive.value) return
  custom.value = ''
  emit('answer', value)
}
</script>

<template>
  <article class="ask" :data-state="card.state">
    <header class="ask__head">
      <MessageSquare :size="14" />
      <span class="ask__title">{{ t('studio.card.ask.title') }}</span>
      <span class="ask__state">{{ statusLabel }}</span>
    </header>

    <p class="ask__question">{{ card.question }}</p>

    <ul v-if="card.options.length" class="ask__options">
      <li v-for="(option, index) in card.options" :key="index">
        <button
          type="button"
          class="ask__option"
          :disabled="!interactive"
          @click="emit('answer', option)"
        >
          {{ option }}
        </button>
      </li>
    </ul>

    <div v-if="interactive" class="ask__custom">
      <input
        v-model="custom"
        class="ask__input"
        type="text"
        :placeholder="t('studio.card.ask.placeholder')"
        @keydown.enter.prevent="submitCustom"
      />
      <button type="button" class="ask__submit" :disabled="custom.trim() === ''" @click="submitCustom">
        {{ t('studio.card.ask.submit') }}
      </button>
    </div>

    <p v-else-if="card.answer" class="ask__answer">{{ t('studio.card.ask.answer') }}：{{ card.answer }}</p>
    <p v-if="card.state === 'stale'" class="ask__note">{{ t('studio.card.ask.staleNote') }}</p>
    <p v-if="card.error" class="ask__error">{{ card.error }}</p>
  </article>
</template>

<style scoped>
.ask {
  padding: 10px 12px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  background: var(--studio-card-bg);
  font-size: 13px;
}

.ask[data-state='stale'],
.ask[data-state='sending'] {
  border-color: var(--border);
}

.ask__head {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.ask__title {
  color: var(--text);
}

.ask__state {
  margin-left: auto;
  color: var(--text-faint);
}

.ask__question {
  margin: 8px 0;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.ask__options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.ask__option {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.ask__option:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.ask__option:disabled,
.ask__submit:disabled {
  opacity: 0.45;
  cursor: default;
}

.ask__custom {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.ask__input {
  flex: 1;
  min-width: 0;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--studio-rail-bg);
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.ask__submit {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.ask__answer {
  margin: 8px 0 0;
  color: var(--text-muted);
}

.ask__note {
  margin: 6px 0 0;
  color: var(--warning);
  font-size: 12px;
}

.ask__error {
  margin: 6px 0 0;
  color: var(--danger);
  font-size: 12px;
}

.ask__option:focus-visible,
.ask__submit:focus-visible,
.ask__input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
</style>
