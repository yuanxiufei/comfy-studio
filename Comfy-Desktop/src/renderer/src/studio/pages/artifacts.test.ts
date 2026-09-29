import { describe, expect, it } from 'vitest'
import type { ProjectStage, ProjectSummary } from './projects'
import {
  STAGE_SAMPLE_SHOWN,
  byActivity,
  landedStages,
  pendingStages,
  shelfTallies
} from './artifacts'

function stage(rel: string, files: number, overrides: Partial<ProjectStage> = {}): ProjectStage {
  return { label: rel, rel, files, done: files > 0, sample: [], ...overrides }
}

function project(name: string, overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  const stages = overrides.stages ?? []
  return {
    name,
    path: `D:/projects/${name}`,
    path_out: `D:/projects/${name}`,
    files: 0,
    files_in: 0,
    files_out: 0,
    missing: [],
    missing_count: 0,
    stages,
    stages_done: stages.filter((entry) => entry.done).length,
    stages_total: stages.length,
    mtime: 0,
    ...overrides
  }
}

describe('landedStages / pendingStages', () => {
  it('splits a project into what has produced something and what has not', () => {
    const summary = project('甲剧', {
      stages: [stage('01_剧本', 3), stage('02_资产', 0), stage('08_分镜', 12)]
    })
    expect(landedStages(summary).map((entry) => entry.rel)).toEqual(['01_剧本', '08_分镜'])
    expect(pendingStages(summary).map((entry) => entry.rel)).toEqual(['02_资产'])
  })

  it('files a done-but-empty stage with the empty ones', () => {
    // `done` here means the stage ran; with no files on disk it has nothing to
    // show, so it belongs with the stages the page counts as "still nothing".
    const summary = project('甲剧', { stages: [stage('02_资产', 0, { done: true })] })
    expect(landedStages(summary)).toEqual([])
    expect(pendingStages(summary)).toHaveLength(1)
  })

  it('keeps the host order and never invents a stage of its own', () => {
    const summary = project('甲剧', {
      stages: [stage('08_分镜', 1), stage('01_剧本', 1), stage('02_资产', 0)]
    })
    expect(landedStages(summary).map((entry) => entry.rel)).toEqual(['08_分镜', '01_剧本'])
  })
})

describe('byActivity', () => {
  it('puts the most recently touched project first', () => {
    const rows = [
      project('旧的', { mtime: 100 }),
      project('新的', { mtime: 300 }),
      project('中间的', { mtime: 200 })
    ]
    expect(byActivity(rows).map((entry) => entry.name)).toEqual(['新的', '中间的', '旧的'])
  })

  it('breaks a tie on the file count, and then on the name', () => {
    const rows = [
      project('空的', { mtime: 100, files: 0 }),
      project('乙', { mtime: 100, files: 5 }),
      project('甲', { mtime: 100, files: 5 })
    ]
    expect(byActivity(rows).map((entry) => entry.name)).toEqual(['甲', '乙', '空的'])
  })

  it('is a copy — the shelf in the store is not reordered under the page', () => {
    const rows = [project('旧', { mtime: 1 }), project('新', { mtime: 2 })]
    byActivity(rows)
    expect(rows.map((entry) => entry.name)).toEqual(['旧', '新'])
  })
})

describe('shelfTallies', () => {
  it('adds up files, stages and gaps across every project', () => {
    const rows = [
      project('甲剧', {
        files: 10,
        missing_count: 2,
        stages: [stage('a', 3), stage('b', 0)],
        stages_done: 1,
        stages_total: 2
      }),
      project('乙剧', {
        files: 0,
        missing_count: 0,
        stages: [stage('a', 0)],
        stages_done: 0,
        stages_total: 1
      })
    ]
    expect(shelfTallies(rows)).toEqual({
      projects: 2,
      started: 1,
      files: 10,
      gaps: 2,
      stagesDone: 1,
      stagesTotal: 3
    })
  })

  it('counts a project as started only once it has left a file behind', () => {
    const rows = [
      project('空的', { files: 0 }),
      project('有一个文件', { files: 1 })
    ]
    expect(shelfTallies(rows).started).toBe(1)
  })

  it('is all zeroes for an empty shelf — the header must not read NaN', () => {
    expect(shelfTallies([])).toEqual({
      projects: 0,
      started: 0,
      files: 0,
      gaps: 0,
      stagesDone: 0,
      stagesTotal: 0
    })
  })

  it('quotes the same stage total the per-project rows are drawn from', () => {
    // The header and the drill-down both read `summary.stages*`; this is the
    // guard that they keep agreeing instead of each counting for itself.
    const rows = [project('甲剧', { stages: [stage('a', 1), stage('b', 0)] })]
    const tallies = shelfTallies(rows)
    expect(tallies.stagesTotal).toBe(rows[0].stages.length)
    expect(tallies.stagesDone).toBe(landedStages(rows[0]).length)
  })
})

describe('STAGE_SAMPLE_SHOWN', () => {
  it('is a small positive number — a row is a glance, not a second list', () => {
    expect(Number.isInteger(STAGE_SAMPLE_SHOWN)).toBe(true)
    expect(STAGE_SAMPLE_SHOWN).toBeGreaterThan(0)
    expect(STAGE_SAMPLE_SHOWN).toBeLessThanOrEqual(10)
  })
})
