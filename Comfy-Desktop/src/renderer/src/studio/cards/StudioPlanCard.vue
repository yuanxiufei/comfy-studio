<script setup lang="ts">
/**
 * The host's `plan__submit` card: a turn is parked until the user approves.
 *
 * Rejecting *requires* feedback — the host rejects an empty one outright
 * (`server.py agent_plan_result`), because a model told "no" without a reason
 * can only guess. So the submit button stays disabled until there is something
 * to say, which turns a server-side error into an obvious affordance.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CheckCircle2, ListChecks, Pencil, XCircle } from 'lucide-vue-next'
import type { CardPlan } from '../conversation'

const props = defineProps<{
  card: CardPlan
}>()

const emit = defineEmits<{
  decide: [approved: boolean, feedback: string]
  edit: []
}>()

const { t } = useI18n()
const feedback = ref(props.card.feedback)

const editable = computed(() => props.card.state === 'waiting' || props.card.state === 'editing')
const busy = computed(() => props.card.state === 'sending')
const statusLabel = computed(() => t(`studio.card.plan.state.${props.card.state}`))

function submit(approved: boolean): void {
  if (!editable.value || busy.value) return
  if (!approved && feedback.value.trim() === '') return
  emit('decide', approved, feedback.value.trim())
}
</script>

<template>
  <article class="plan" :data-state="card.state">
    <header class="plan__head">
      <ListChecks :size="14" />
      <span class="plan__title">{{ t('studio.card.plan.title') }}</span>
      <span class="plan__state">{{ statusLabel }}</span>
    </header>

    <p class="plan__goal">{{ card.goal }}</p>

    <ol class="plan__steps">
      <li v-for="(step, index) in card.steps" :key="index" :data-state="step.status">
        <span class="plan__index">{{ index + 1 }}</span>
        <span class="plan__step">
          <span class="plan__step-title">{{ step.title }}</span>
          <span v-if="step.tool" class="plan__tool">{{ step.tool }}</span>
          <span v-if="step.detail" class="plan__detail">{{ step.detail }}</span>
          <span v-if="step.note" class="plan__note">{{ step.note }}</span>
        </span>
      </li>
    </ol>

    <p v-if="card.notes" class="plan__notes">{{ card.notes }}</p>

    <div v-if="editable && card.state === 'editing'" class="plan__feedback">
      <textarea
        v-model="feedback"
        class="plan__input"
        rows="3"
        :placeholder="t('studio.card.plan.feedbackPlaceholder')"
      />
    </div>

    <footer v-if="editable" class="plan__actions">
      <button type="button" class="plan__approve" :disabled="busy" @click="submit(true)">
        <CheckCircle2 :size="13" />
        {{ t('studio.card.plan.approve') }}
      </button>
      <button
        v-if="card.state === 'editing'"
        type="button"
        class="plan__reject"
        :disabled="busy || feedback.trim() === ''"
        :title="feedback.trim() === '' ? t('studio.card.plan.feedbackRequired') : ''"
        @click="submit(false)"
      >
        <XCircle :size="13" />
        {{ t('studio.card.plan.reject') }}
      </button>
      <button v-else type="button" class="plan__edit" :disabled="busy" @click="emit('edit')">
        <Pencil :size="13" />
        {{ t('studio.card.plan.edit') }}
      </button>
    </footer>

    <p v-if="card.state === 'stale'" class="plan__stale">{{ t('studio.card.plan.staleNote') }}</p>
    <p v-if="card.error" class="plan__error">{{ card.error }}</p>
  </article>
</template>

<style scoped>
.plan {
  padding: 10px 12px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  background: var(--studio-card-bg);
  font-size: 13px;
}

.plan[data-state='approved'] {
  border-color: var(--success);
}

.plan[data-state='rejected'] {
  border-color: var(--warning);
}

.plan[data-state='stale'],
.plan[data-state='sending'] {
  border-color: var(--border);
}

.plan__head {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.plan__title {
  color: var(--text);
}

.plan__state {
  margin-left: auto;
  color: var(--text-faint);
}

.plan__goal {
  margin: 8px 0;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.plan__steps {
  margin: 0;
  padding: 0;
  list-style: none;
}

.plan__steps li {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  border-top: 1px solid var(--studio-card-border);
}

.plan__index {
  flex: none;
  width: 16px;
  color: var(--text-faint);
  text-align: right;
}

.plan__step {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.plan__steps li[data-state='done'] .plan__step-title {
  color: var(--success);
}

.plan__steps li[data-state='failed'] .plan__step-title {
  color: var(--danger);
}

.plan__tool,
.plan__detail,
.plan__note {
  color: var(--text-faint);
  font-size: 12px;
  word-break: break-word;
}

.plan__detail {
  color: var(--text-muted);
}

.plan__notes {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  white-space: pre-wrap;
}

.plan__feedback {
  margin-top: 8px;
}

.plan__input {
  width: 100%;
  resize: vertical;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--studio-rail-bg);
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.plan__actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.plan__actions button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.plan__approve:hover:not(:disabled) {
  border-color: var(--success);
  color: var(--success);
}

.plan__reject:hover:not(:disabled) {
  border-color: var(--warning);
  color: var(--warning);
}

.plan__edit:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.plan__actions button:disabled {
  opacity: 0.45;
  cursor: default;
}

.plan__stale {
  margin: 6px 0 0;
  color: var(--warning);
  font-size: 12px;
}

.plan__error {
  margin: 6px 0 0;
  color: var(--danger);
  font-size: 12px;
}

.plan__actions button:focus-visible,
.plan__input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
</style>
