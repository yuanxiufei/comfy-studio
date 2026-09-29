/**
 * Shapes and pure helpers for the activity log (`journal/list`).
 *
 * One entry is one stage of one project that the ledger has something to say
 * about. The host flattens every project's ledger into a single newest-first
 * list — see `lib/comfy_studio/pipeline.journal_payload` — so this file only has
 * to answer the questions the page asks of that list: what status is this in
 * words, what day does it belong to, and how many of each are there.
 *
 * The field names match the ledger's own (`status` / `artifact` / `at` /
 * `note` / `error`), which is deliberate on the host side too: this row and a
 * stage row on the workbench are the same fact seen from two directions, and
 * giving them different names here would be the first step towards them drifting.
 */
import type { RunStatus } from './pipeline'

export interface JournalEntry {
  project: string
  /** Stage code — `S0a`, `S4a`, … — the key the locale's stage names are under. */
  code: string
  /** The stage's host-side name: a fallback for codes the locale doesn't cover. */
  name: string
  status: RunStatus | string
  /** Project-root relative path of what this stage left behind, if anything. */
  artifact: string
  /** When it ran. Empty on ledgers written before timestamps, or by hand. */
  at: string
  note: string
  error: string
}

/** A project whose ledger exists but could not be read. Reported, never hidden:
 *  the alternative is the page quietly showing fewer projects than are on disk. */
export interface JournalProblem {
  project: string
  error: string
}

export interface JournalPayload {
  dir: string
  exists: boolean
  query: string
  limit: number
  /** How many projects were examined (after the name filter). */
  projects: number
  entries: JournalEntry[]
  /** Total rows before `limit` truncated them — what "N more" is measured from. */
  matched: number
  truncated: boolean
  /** The newest ledger timestamp seen, for the header. */
  updated: string
  problems: JournalProblem[]
}

/** Mirrors `DEFAULT_JOURNAL_LIMIT` in `lib/comfy_studio/pipeline.py`. */
export const JOURNAL_LIMIT = 200

/**
 * The locale key for a run status.
 *
 * Deliberately the *workbench's* namespace rather than a new one under
 * `studio.journal`: "done" means the same thing on both pages, and two tables
 * saying it two ways is how a user ends up wondering whether `已完成` and `跑完了`
 * are different states.
 */
export function statusKey(status: string): string {
  return `studio.production.outcome.${status}`
}

/** `YYYY-MM-DD` for an `at`, or `''` when it isn't one. */
export function dayOf(at: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(at) ? at.slice(0, 10) : ''
}

export interface JournalDay {
  /** `YYYY-MM-DD`, or `''` for the entries no ledger ever stamped. */
  day: string
  entries: JournalEntry[]
}

/**
 * Split the list into day buckets.
 *
 * The host already sorted newest-first, so building the buckets in one pass
 * keeps that order, and the undated entries — which sort last on the host —
 * come out as the final bucket. That is the right place for them: they are old
 * ledgers or hand-written ones, and scattering them through the timeline would
 * be inventing timestamps.
 */
export function groupByDay(entries: readonly JournalEntry[]): JournalDay[] {
  const days: JournalDay[] = []
  const byDay = new Map<string, JournalDay>()
  for (const entry of entries) {
    const day = dayOf(entry.at)
    let bucket = byDay.get(day)
    if (!bucket) {
      bucket = { day, entries: [] }
      byDay.set(day, bucket)
      days.push(bucket)
    }
    bucket.entries.push(entry)
  }
  return days
}

export interface JournalTallies {
  entries: number
  done: number
  skipped: number
  failed: number
  /** Statuses outside the host vocabulary — a hand-edited ledger can hold any
   *  string, and counting only the three known ones would hide it. */
  other: number
}

/** What the header quotes. The failure count is the reason this page exists, so
 *  it is computed here rather than filtered for in the template. */
export function journalTallies(entries: readonly JournalEntry[]): JournalTallies {
  const tallies: JournalTallies = {
    entries: entries.length,
    done: 0,
    skipped: 0,
    failed: 0,
    other: 0
  }
  for (const entry of entries) {
    if (entry.status === 'done') tallies.done += 1
    else if (entry.status === 'skipped') tallies.skipped += 1
    else if (entry.status === 'failed') tallies.failed += 1
    else tallies.other += 1
  }
  return tallies
}
