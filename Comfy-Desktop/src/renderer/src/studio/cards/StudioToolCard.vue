<script setup lang="ts">
/**
 * One tool call from the host's agent loop, as a collapsible card.
 *
 * Collapsed by default and folds `pre` blocks instead of truncating: a tool
 * result can be a whole storyboard, and the drawer's worst habit was dumping it
 * inline so the conversation became unreadable. The state dot is the only thing
 * that has to be visible at a glance — running / done / failed.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, CheckCircle2, ChevronRight, LoaderCircle } from 'lucide-vue-next'
import type { CardTool } from '../conversation'

const props = defineProps<{
  card: CardTool
}>()

const { t } = useI18n()
const open = ref(false)

const stateLabel = computed(() => t(`studio.card.tool.${props.card.state}`))
</script>

<template>
  <article class="tool" :data-state="card.state" :class="{ 'is-open': open }">
    <button
      type="button"
      class="tool__head"
      :aria-expanded="open"
      @click="open = !open"
    >
      <ChevronRight :size="14" class="tool__caret" />
      <LoaderCircle v-if="card.state === 'running'" :size="14" class="tool__icon is-spinning" />
      <CheckCircle2 v-else-if="card.state === 'done'" :size="14" class="tool__icon" />
      <AlertCircle v-else :size="14" class="tool__icon" />
      <span class="tool__name">{{ card.tool || t('studio.card.tool.unknown') }}</span>
      <span class="tool__state">{{ stateLabel }}</span>
      <span v-if="card.orphan" class="tool__orphan">{{ t('studio.card.tool.orphan') }}</span>
    </button>

    <div v-if="open" class="tool__body">
      <template v-if="card.args">
        <span class="tool__label">{{ t('studio.card.tool.params') }}</span>
        <pre class="tool__pre">{{ card.args }}</pre>
      </template>
      <template v-if="card.result">
        <span class="tool__label">{{ t('studio.card.tool.result') }}</span>
        <pre class="tool__pre">{{ card.result }}</pre>
      </template>
      <p v-if="!card.args && !card.result" class="tool__empty">{{ t('studio.card.tool.empty') }}</p>
    </div>
  </article>
</template>

<style scoped>
.tool {
  border: 1px solid var(--studio-card-border);
  border-radius: 8px;
  background: var(--studio-card-bg);
  font-size: 12px;
  overflow: hidden;
}

.tool__head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.tool__caret {
  flex: none;
  transition: transform 120ms ease;
}

.tool.is-open .tool__caret {
  transform: rotate(90deg);
}

.tool__icon {
  flex: none;
  color: var(--text-faint);
}

.tool[data-state='done'] .tool__icon {
  color: var(--success);
}

.tool[data-state='error'] .tool__icon {
  color: var(--danger);
}

.tool__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
}

.tool__state,
.tool__orphan {
  flex: none;
  color: var(--text-faint);
}

.tool__orphan {
  color: var(--warning);
}

.tool__body {
  padding: 0 10px 10px 32px;
}

.tool__label {
  display: block;
  margin-bottom: 2px;
  color: var(--text-faint);
}

.tool__pre {
  margin: 0 0 8px;
  max-height: 240px;
  overflow: auto;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--studio-rail-bg);
  color: var(--text);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.tool__empty {
  margin: 0;
  color: var(--text-faint);
}

.tool__head:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.is-spinning {
  animation: tool-spin 900ms linear infinite;
}

@keyframes tool-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }

  .tool__caret {
    transition: none;
  }
}
</style>
