import { describe, expect, it } from 'vitest'
import { JOURNAL_LIMIT, dayOf, groupByDay, journalTallies, statusKey, type JournalEntry } from './journal'

function entry(project: string, code: string, at: string, status = 'done'): JournalEntry {
  return { project, code, name: code, status, artifact: '', at, note: '', error: '' }
}

describe('statusKey', () => {
  it('reads out of the workbench vocabulary rather than a second table', () => {
    expect(statusKey('done')).toBe('studio.production.outcome.done')
    expect(statusKey('failed')).toBe('studio.production.outcome.failed')
  })

  it('still builds a key for a status the host does not define', () => {
    // The page checks the locale before using it, so an unknown token falls back
    // to showing itself. The key is still well-formed, not `undefined`.
    expect(statusKey('')).toBe('studio.production.outcome.')
  })
})

describe('dayOf', () => {
  it('takes the date off a ledger timestamp', () => {
    expect(dayOf('2026-09-28T11:00:00')).toBe('2026-09-28')
    expect(dayOf('2026-09-28')).toBe('2026-09-28')
  })

  it('returns nothing for anything which is not a date', () => {
    // Old and hand-written ledgers can hold "", "昨天" or a bare time.
    expect(dayOf('')).toBe('')
    expect(dayOf('昨天')).toBe('')
    expect(dayOf('11:00')).toBe('')
    expect(dayOf('2026/09/28')).toBe('')
  })
})

describe('groupByDay', () => {
  it('buckets consecutive entries of the same day together', () => {
    const days = groupByDay([
      entry('甲', 'S4', '2026-09-28T11:00:00'),
      entry('甲', 'S3', '2026-09-28T10:00:00'),
      entry('乙', 'S0a', '2026-09-27T09:00:00')
    ])
    expect(days.map((day) => day.day)).toEqual(['2026-09-28', '2026-09-27'])
    expect(days[0].entries.map((row) => row.code)).toEqual(['S4', 'S3'])
  })

  it('keeps the host order inside a bucket — it is already newest first', () => {
    const days = groupByDay([
      entry('甲', 'S7', '2026-09-28T12:00:00'),
      entry('甲', 'S6', '2026-09-28T11:00:00'),
      entry('甲', 'S5', '2026-09-28T10:00:00')
    ])
    expect(days).toHaveLength(1)
    expect(days[0].entries.map((row) => row.code)).toEqual(['S7', 'S6', 'S5'])
  })

  it('puts the untimed entries in a final bucket of their own', () => {
    // They sort last on the host, and scattering them through the timeline would
    // be inventing timestamps they never had.
    const days = groupByDay([entry('甲', 'S4', '2026-09-28T11:00:00'), entry('旧', 'S1', '')])
    expect(days.map((day) => day.day)).toEqual(['2026-09-28', ''])
    expect(days[1].entries[0].project).toBe('旧')
  })

  it('collects a day that reappears later into the one bucket', () => {
    // The host sorts by timestamp so this should not arise, but a list rebuilt
    // from a filtered or hand-appended source must not produce two `2026-09-28`
    // headers a thousand rows apart.
    const days = groupByDay([
      entry('甲', 'S4', '2026-09-28T11:00:00'),
      entry('乙', 'S0a', '2026-09-27T09:00:00'),
      entry('甲', 'S3', '2026-09-28T10:00:00')
    ])
    expect(days.map((day) => day.day)).toEqual(['2026-09-28', '2026-09-27'])
    expect(days[0].entries).toHaveLength(2)
  })

  it('is an empty list for an empty log', () => {
    expect(groupByDay([])).toEqual([])
  })
})

describe('journalTallies', () => {
  it('counts each status, and totals them', () => {
    const tallies = journalTallies([
      entry('甲', 'S0a', '2026-09-28T10:00:00', 'done'),
      entry('甲', 'S1', '2026-09-28T11:00:00', 'failed'),
      entry('乙', 'S0a', '2026-09-27T10:00:00', 'skipped'),
      entry('乙', 'S2', '2026-09-27T11:00:00', 'done')
    ])
    expect(tallies).toEqual({ entries: 4, done: 2, skipped: 1, failed: 1, other: 0 })
  })

  it('counts a status outside the host vocabulary as other, never as done', () => {
    // A hand-edited ledger can hold any string; folding it into a known bucket
    // would report progress that did not happen.
    expect(journalTallies([entry('甲', 'S0a', '', 'partial')])).toEqual({
      entries: 1,
      done: 0,
      skipped: 0,
      failed: 0,
      other: 1
    })
    expect(journalTallies([entry('甲', 'S0a', '', '')])).toEqual({
      entries: 1,
      done: 0,
      skipped: 0,
      failed: 0,
      other: 1
    })
  })

  it('is all zeroes for an empty log', () => {
    expect(journalTallies([])).toEqual({ entries: 0, done: 0, skipped: 0, failed: 0, other: 0 })
  })
})

describe('JOURNAL_LIMIT', () => {
  it('is the same number the host defaults to', () => {
    // Mirrors `DEFAULT_JOURNAL_LIMIT` in `lib/comfy_studio/pipeline.py`; if the
    // host's default moves, this is where the page notices.
    expect(JOURNAL_LIMIT).toBe(200)
  })
})
