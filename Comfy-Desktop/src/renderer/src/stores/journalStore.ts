/**
 * The activity log, driven by `journal/list`.
 *
 * A faithful mirror of one payload and nothing more: the host has already
 * flattened, sorted and truncated, so re-sorting here would only be a second
 * opinion about "newest first" that can disagree with the first. What the store
 * does add is `hidden` — the difference between what the host matched and what it
 * returned — because that number is the only way the page can honestly say
 * "还有 N 条没显示" instead of implying the list is everything.
 *
 * The name filter is sent to the host rather than applied here: the host matches
 * against every project on disk, while the page only ever holds the first
 * `limit` rows, so filtering locally would silently hide matches.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  JOURNAL_LIMIT,
  journalTallies,
  type JournalEntry,
  type JournalPayload,
  type JournalProblem
} from '../studio/pages/journal'
import { callStudio } from '../studio/pages/rpc'

export const useJournalStore = defineStore('studioJournal', () => {
  const entries = ref<JournalEntry[]>([])
  const problems = ref<JournalProblem[]>([])
  const dir = ref('')
  const exists = ref(true)
  /** Projects examined, after the name filter. */
  const projects = ref(0)
  const matched = ref(0)
  const truncated = ref(false)
  const limit = ref(JOURNAL_LIMIT)
  const updated = ref('')
  /** Substring of the project name, matched by the host. */
  const filter = ref('')
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref<string | null>(null)

  const tallies = computed(() => journalTallies(entries.value))

  /** Rows the host matched but did not return. */
  const hidden = computed(() => Math.max(0, matched.value - entries.value.length))

  /** Ledgers that exist and could not be read. Never folded into `error`: those
   *  projects have records, and reporting nothing would understate the shelf. */
  const broken = computed(() => problems.value.length)

  async function refresh(): Promise<void> {
    loading.value = true
    const outcome = await callStudio<JournalPayload>('journal/list', {
      name: filter.value.trim(),
      limit: JOURNAL_LIMIT
    })
    loading.value = false
    loaded.value = true
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    const payload = outcome.value
    error.value = null
    entries.value = payload.entries
    problems.value = payload.problems
    dir.value = payload.dir
    exists.value = payload.exists
    projects.value = payload.projects
    matched.value = payload.matched
    truncated.value = payload.truncated
    limit.value = payload.limit
    updated.value = payload.updated
  }

  function clearFilter(): void {
    filter.value = ''
  }

  function reset(): void {
    entries.value = []
    problems.value = []
    filter.value = ''
    updated.value = ''
    loaded.value = false
    error.value = null
  }

  return {
    entries,
    problems,
    dir,
    exists,
    projects,
    matched,
    truncated,
    limit,
    updated,
    filter,
    loading,
    loaded,
    error,
    tallies,
    hidden,
    broken,
    refresh,
    clearFilter,
    reset
  }
})
