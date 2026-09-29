<script setup lang="ts">
/**
 * The activity log: every stage of every project, newest first.
 *
 * The workbench answers "where is *this* project up to?" by showing the chain of
 * stages it has not run yet. This page answers the other question — "what has
 * actually happened?" — over the same ledgers, so it is ordered by time instead
 * of by the chain, and it leads with the failures, because a log that buries them
 * is a log nobody reads twice.
 *
 * Two things it must not do: hide a project whose ledger is unreadable (that is
 * how a shelf of 300 records looks empty), and imply the returned rows are all of
 * them (`matched` is quoted separately).
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  AlertCircle,
  FileText,
  History,
  LoaderCircle,
  RefreshCw,
  Search,
  TriangleAlert
} from 'lucide-vue-next'
import { useJournalStore } from '../../stores/journalStore'
import { groupByDay, statusKey, type JournalEntry } from './journal'

const journal = useJournalStore()
const { t, te, n } = useI18n()

const onlyFailed = ref(false)
const draft = ref(journal.filter)

onMounted(() => {
  if (!journal.loaded) void journal.refresh()
})

/** The status filter is client-side on purpose: the host already sent the rows
 *  up to `limit`, and asking it again for a subset would re-read every ledger to
 *  answer a question the page can answer from what it is holding. */
const rows = computed(() =>
  onlyFailed.value ? journal.entries.filter((entry) => entry.status === 'failed') : journal.entries
)

const days = computed(() => groupByDay(rows.value))

/** The stage's name in this language, falling back to the host's own name and
 *  then the bare code — a ledger can hold a stage this build has never heard of. */
function stageLabel(entry: JournalEntry): string {
  const key = `studio.production.stageNames.${entry.code}`
  return te(key) ? t(key) : entry.name || entry.code
}

/** Same rule for the status: the workbench's vocabulary, then the raw token.
 *  Showing `S4a` or `partial` untranslated beats showing nothing at all. */
function statusLabel(entry: JournalEntry): string {
  const key = statusKey(entry.status)
  return te(key) ? t(key) : entry.status
}

/** `HH:MM` out of a ledger timestamp, or empty when it has none. */
function timeOf(at: string): string {
  return at.length >= 16 ? at.slice(11, 16) : ''
}

async function applyFilter(): Promise<void> {
  journal.filter = draft.value.trim()
  await journal.refresh()
}

function clearFilter(): void {
  draft.value = ''
  journal.filter = ''
  void journal.refresh()
}
</script>

<template>
  <section class="journal">
    <p v-if="journal.error" class="journal__error">
      <AlertCircle :size="14" />
      <span>{{ journal.error }}</span>
    </p>

    <header class="journal__bar">
      <form class="journal__filter" @submit.prevent="applyFilter()">
        <Search :size="13" />
        <input v-model="draft" type="search" :placeholder="t('studio.journal.filter')" />
      </form>
      <button type="button" class="journal__btn" @click="applyFilter()">
        <span>{{ t('studio.journal.filterApply') }}</span>
      </button>
      <button v-if="journal.filter" type="button" class="journal__btn" @click="clearFilter()">
        <span>{{ t('studio.journal.filterClear') }}</span>
      </button>
      <button
        type="button"
        class="journal__btn"
        :class="{ 'is-on': onlyFailed }"
        @click="onlyFailed = !onlyFailed"
      >
        <TriangleAlert :size="13" />
        <span>{{ t('studio.journal.onlyFailed') }}</span>
      </button>
      <button type="button" class="journal__btn" :disabled="journal.loading" @click="journal.refresh()">
        <LoaderCircle v-if="journal.loading" :size="13" class="is-spinning" />
        <RefreshCw v-else :size="13" />
        <span>{{ t('studio.journal.refresh') }}</span>
      </button>
    </header>

    <p class="journal__tallies">
      {{
        t('studio.journal.tallies', {
          entries: n(journal.tallies.entries),
          done: n(journal.tallies.done),
          skipped: n(journal.tallies.skipped),
          failed: n(journal.tallies.failed)
        })
      }}
      <span v-if="journal.tallies.other > 0" class="journal__dim">
        {{ t('studio.journal.other', { count: n(journal.tallies.other) }) }}
      </span>
      <span v-if="journal.hidden > 0" class="journal__warn">
        {{ t('studio.journal.more', { count: n(journal.hidden), limit: n(journal.limit) }) }}
      </span>
      <span v-if="journal.updated" class="journal__dim">
        {{ t('studio.journal.updated', { at: journal.updated }) }}
      </span>
    </p>

    <p v-if="journal.broken > 0" class="journal__problems">
      <strong>{{ t('studio.journal.problems', { count: n(journal.broken) }) }}</strong>
      <span class="journal__dim">{{ t('studio.journal.problemsHint') }}</span>
      <span v-for="problem in journal.problems" :key="problem.project" class="journal__problem">
        {{ problem.project }}: {{ problem.error }}
      </span>
    </p>

    <p v-if="journal.loading && !journal.loaded" class="journal__hint">
      {{ t('studio.journal.loading') }}
    </p>
    <p v-else-if="!journal.exists" class="journal__hint">
      {{ t('studio.journal.dirMissing', { dir: journal.dir }) }}
    </p>
    <p v-else-if="journal.entries.length === 0" class="journal__hint">
      {{ t('studio.journal.empty') }}
    </p>
    <p v-else-if="rows.length === 0" class="journal__hint">
      {{ t('studio.journal.filteredEmpty') }}
    </p>

    <ul v-else class="journal__days">
      <li v-for="day in days" :key="day.day || 'undated'" class="journal__day">
        <p class="journal__dayHead">
          <History :size="12" />
          <span>{{ day.day || t('studio.journal.undated') }}</span>
          <span class="journal__dim">{{ n(day.entries.length) }}</span>
        </p>
        <ul class="journal__rows">
          <li
            v-for="entry in day.entries"
            :key="`${entry.project}/${entry.code}`"
            class="journal__row"
            :class="`is-${entry.status}`"
          >
            <span class="journal__time">{{ timeOf(entry.at) }}</span>
            <span class="journal__status">{{ statusLabel(entry) }}</span>
            <div class="journal__body">
              <p class="journal__line">
                <span class="journal__stage">{{ stageLabel(entry) }}</span>
                <span class="journal__project">{{ entry.project }}</span>
              </p>
              <p v-if="entry.artifact" class="journal__artifact">
                <FileText :size="11" />
                <span>{{ entry.artifact }}</span>
              </p>
              <p v-if="entry.error" class="journal__fail">{{ entry.error }}</p>
              <p v-else-if="entry.note" class="journal__dim">{{ entry.note }}</p>
            </div>
          </li>
        </ul>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.journal {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
  overflow: auto;
}

.journal__error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 6px 8px;
  border: 1px solid var(--danger);
  border-radius: 6px;
  color: var(--danger);
  font-size: 12px;
}

.journal__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.journal__filter {
  display: flex;
  flex: 1;
  min-width: 160px;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text-faint);
}

.journal__filter input {
  flex: 1;
  min-width: 0;
  padding: 5px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  outline: none;
}

.journal__btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.journal__btn:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.journal__btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.journal__btn.is-on {
  border-color: var(--accent);
  color: var(--accent);
}

.journal__tallies {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.journal__hint,
.journal__dim {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.5;
}

.journal__warn {
  color: var(--warning);
}

.journal__problems {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 6px 8px;
  border: 1px solid var(--warning);
  border-radius: 6px;
  color: var(--warning);
  font-size: 11px;
  line-height: 1.5;
}

.journal__problem {
  color: var(--text-faint);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 10px;
  overflow-wrap: anywhere;
}

.journal__days,
.journal__rows {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.journal__days {
  gap: 10px;
}

.journal__dayHead {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--studio-card-border);
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.journal__row {
  display: grid;
  grid-template-columns: 42px 72px 1fr;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 6px;
}

.journal__row:hover {
  background: var(--studio-card-bg);
}

.journal__row.is-failed {
  border-left: 2px solid var(--danger);
}

.journal__time,
.journal__status {
  color: var(--text-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.journal__status {
  font-variant-numeric: normal;
}

.journal__row.is-failed .journal__status {
  color: var(--danger);
}

.journal__row.is-done .journal__status {
  color: var(--success);
}

.journal__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.journal__line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 0;
}

.journal__stage {
  color: var(--text);
  font-size: 12px;
}

.journal__project {
  color: var(--text-faint);
  font-size: 10px;
  overflow-wrap: anywhere;
}

.journal__artifact {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  color: var(--text-faint);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 10px;
  overflow-wrap: anywhere;
}

.journal__fail {
  margin: 0;
  color: var(--danger);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.is-spinning {
  animation: journal-spin 900ms linear infinite;
}

@keyframes journal-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }
}
</style>
