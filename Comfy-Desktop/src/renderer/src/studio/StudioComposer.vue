<script setup lang="ts">
/**
 * The rail's input: quoted passages on top, text below, one primary action.
 *
 * Two behaviours are load-bearing and easy to get wrong:
 *  - **Enter sends, Shift+Enter breaks the line.** Chinese input methods need a
 *    grace period after composition; `isComposing` is checked so confirming a
 *    candidate never fires the turn.
 *  - **While a turn runs the primary button becomes Stop.** There is never a
 *    second "send" that the host will reject with "已有一轮在跑".
 */
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUp, Square, X } from 'lucide-vue-next'
import type { QuoteRef } from './conversation'

const props = defineProps<{
  modelValue: string
  quotes: QuoteRef[]
  sending: boolean
  cancelling: boolean
  /** Host is not running: typing would only fail, so the field says why. */
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  cancel: []
  removeQuote: [index: number]
}>()

const { t } = useI18n()
const field = ref<HTMLTextAreaElement | null>(null)
const composing = ref(false)

const canSend = computed(() => !props.sending && props.modelValue.trim() !== '')

function onInput(event: Event): void {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey) return
  // `isComposing` is not always set on the event during IME confirmation, and
  // Safari/Electron differ, so the tracked flag is the reliable one.
  if (composing.value || event.isComposing) return
  event.preventDefault()
  if (canSend.value) emit('send')
}

/** Focus and put the caret at the end — used when a message is pulled back into
 *  the composer, where the user almost always wants to keep editing. */
async function focus(): Promise<void> {
  await nextTick()
  const element = field.value
  if (!element) return
  element.focus()
  element.setSelectionRange(element.value.length, element.value.length)
}

defineExpose({ focus })
</script>

<template>
  <div class="composer">
    <div v-if="quotes.length" class="composer__quotes">
      <div v-for="(quote, index) in quotes" :key="index" class="chip" :title="quote.text">
        <span class="chip__name">{{ quote.name }}</span>
        <span class="chip__range">{{ quote.offset }}–{{ quote.offset + quote.chars }}</span>
        <button
          type="button"
          class="chip__remove"
          :title="t('studio.composer.removeQuote')"
          @click="emit('removeQuote', index)"
        >
          <X :size="11" />
        </button>
      </div>
    </div>

    <div class="composer__row">
      <textarea
        ref="field"
        class="composer__input"
        rows="1"
        :value="modelValue"
        :disabled="disabled"
        :placeholder="disabled ? t('studio.composer.hostDown') : t('studio.composer.placeholder')"
        @input="onInput"
        @keydown="onKeydown"
        @compositionstart="composing = true"
        @compositionend="composing = false"
      />
      <button
        v-if="sending"
        type="button"
        class="composer__action is-stop"
        :disabled="cancelling"
        :title="t('studio.composer.stopHint')"
        @click="emit('cancel')"
      >
        <Square :size="14" />
      </button>
      <button
        v-else
        type="button"
        class="composer__action"
        :disabled="!canSend || disabled"
        :title="t('studio.composer.send')"
        @click="emit('send')"
      >
        <ArrowUp :size="14" />
      </button>
    </div>

    <span class="composer__hint">{{ t('studio.composer.hint') }}</span>
  </div>
</template>

<style scoped>
.composer {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 12px 10px;
  border-top: 1px solid var(--border);
}

.composer__quotes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 2px 4px 2px 8px;
  border: 1px solid var(--accent);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11px;
}

.chip__name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
}

.chip__range {
  color: var(--text-faint);
}

.chip__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
}

.chip__remove:hover {
  color: var(--danger);
}

.composer__row {
  display: flex;
  align-items: flex-end;
  gap: 6px;
}

.composer__input {
  flex: 1;
  min-width: 0;
  max-height: 200px;
  resize: none;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--studio-card-bg);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
  field-sizing: content;
}

.composer__input:disabled {
  opacity: 0.7;
  cursor: default;
}

.composer__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex: none;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.composer__action:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.composer__action.is-stop:hover:not(:disabled) {
  border-color: var(--danger);
  color: var(--danger);
}

.composer__action:disabled {
  opacity: 0.4;
  cursor: default;
}

.composer__hint {
  color: var(--text-faint);
  font-size: 11px;
}

.composer__input:focus-visible,
.composer__action:focus-visible,
.chip__remove:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
</style>
