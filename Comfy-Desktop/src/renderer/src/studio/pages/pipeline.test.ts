import { describe, expect, it } from 'vitest'
import {
  applyPipelineEvent,
  emptyRun,
  isPipelineEvent,
  orderedSteps,
  outcomesByCode,
  type LiveRun,
  type PipelineEvent,
  type PipelineStageEvent,
  type StageOutcome,
  type StepsPayload,
  type WorkbenchStep
} from './pipeline'

function outcome(code: string, overrides: Partial<StageOutcome> = {}): StageOutcome {
  return {
    code,
    name: code,
    status: 'done',
    agent: '',
    artifact: `00_PROJECT/x/${code}.md`,
    needs_render: false,
    render_pending: false,
    render_targets: [],
    render_lands: {},
    render_note: '',
    seconds: 1,
    note: '',
    error: '',
    ...overrides
  }
}

function stageEvent(code: string, overrides: Partial<StageOutcome> = {}): PipelineStageEvent {
  return { type: 'pipeline', phase: 'stage', ...outcome(code, overrides) }
}

function fold(run: LiveRun, events: PipelineEvent[]): LiveRun {
  return events.reduce(applyPipelineEvent, run)
}

function step(key: string, overrides: Partial<WorkbenchStep> = {}): WorkbenchStep {
  return {
    key,
    name: key,
    goal: '',
    note: '',
    needs: [],
    blocked_by: [],
    ready: true,
    stages: [],
    landings: [],
    count: 0,
    seed_count: 0,
    state: 'empty',
    ...overrides
  }
}

function stepsPayload(overrides: Partial<StepsPayload> = {}): StepsPayload {
  return {
    project: '/p',
    name: 'demo',
    novel: null,
    linked_novel: '',
    gaps: [],
    order: [],
    current: '',
    steps: [],
    render_required: [],
    roots: {},
    dir_roots: {},
    single_root: true,
    ...overrides
  }
}

describe('isPipelineEvent', () => {
  it('accepts every pipeline phase', () => {
    expect(isPipelineEvent({ type: 'pipeline', phase: 'start' })).toBe(true)
    expect(isPipelineEvent({ type: 'pipeline', phase: 'stage_start' })).toBe(true)
    expect(isPipelineEvent({ type: 'pipeline', phase: 'stage' })).toBe(true)
    expect(isPipelineEvent({ type: 'pipeline', phase: 'finished' })).toBe(true)
  })

  it('turns away agent traffic and junk', () => {
    // The same channel carries agent events; reducing those into run state is
    // exactly the bug this guard exists to prevent.
    expect(isPipelineEvent({ type: 'agent', phase: 'stage' })).toBe(false)
    expect(isPipelineEvent({ type: 'pipeline', phase: 'chatter' })).toBe(false)
    expect(isPipelineEvent({ phase: 'stage' })).toBe(false)
    expect(isPipelineEvent(null)).toBe(false)
    expect(isPipelineEvent('pipeline')).toBe(false)
  })
})

describe('applyPipelineEvent', () => {
  it('starts a run with the planned stages and nothing else', () => {
    const run = fold(emptyRun(), [
      { type: 'pipeline', phase: 'start', project: '/p', stages: ['S0', 'S1'] }
    ])
    expect(run.running).toBe(true)
    expect(run.planned).toEqual(['S0', 'S1'])
    expect(run.outcomes).toEqual([])
    expect(run.report).toBeNull()
  })

  it('does not inherit outcomes from the previous run', () => {
    // A stage that failed last run must not look like it failed just now.
    const first = fold(emptyRun(), [
      stageEvent('S0', { status: 'failed', error: 'boom' }),
      {
        type: 'pipeline',
        phase: 'finished',
        project: '/p',
        novel: null,
        state: 's',
        ok: false,
        ran: ['S0'],
        not_ran: ['S1'],
        render_required: [],
        stages: [outcome('S0', { status: 'failed', error: 'boom' })],
        roots: {},
        dir_roots: {},
        single_root: true
      }
    ])
    expect(first.running).toBe(false)
    expect(first.report?.ok).toBe(false)

    const second = applyPipelineEvent(first, {
      type: 'pipeline',
      phase: 'start',
      project: '/p',
      stages: ['S0']
    })
    expect(second.running).toBe(true)
    expect(second.outcomes).toEqual([])
    expect(second.report).toBeNull()
  })

  it('tracks the stage in flight and clears it when the stage ends', () => {
    const started = fold(emptyRun(), [
      { type: 'pipeline', phase: 'start', project: '/p', stages: ['S0', 'S1'] },
      { type: 'pipeline', phase: 'stage_start', code: 'S0', name: '建纲', actor: '编剧' }
    ])
    expect(started.activeCode).toBe('S0')
    expect(started.activeName).toBe('建纲')
    expect(started.activeActor).toBe('编剧')

    const done = applyPipelineEvent(started, stageEvent('S0'))
    expect(done.activeCode).toBe('')
    expect(done.outcomes).toEqual([outcome('S0')])
    // Still running: a finished stage is not a finished run.
    expect(done.running).toBe(true)
  })

  it('records a stage that was never announced', () => {
    // Dropping it would leave the panel quietly disagreeing with the host.
    const run = fold(emptyRun(), [
      { type: 'pipeline', phase: 'start', project: '/p', stages: [] },
      stageEvent('S7')
    ])
    expect(run.outcomes.map((entry) => entry.code)).toEqual(['S7'])
  })

  it('prefers the full stage list from `finished` over the incremental one', () => {
    // If a `stage` frame were missed, the report is still the whole truth.
    const run = fold(emptyRun(), [
      { type: 'pipeline', phase: 'start', project: '/p', stages: ['S0', 'S1'] },
      stageEvent('S0'),
      {
        type: 'pipeline',
        phase: 'finished',
        project: '/p',
        novel: null,
        state: '00_PROJECT/05_流程/pipeline-state.json',
        ok: true,
        ran: ['S0', 'S1'],
        not_ran: [],
        render_required: [],
        stages: [outcome('S0'), outcome('S1')],
        roots: { input: '/p' },
        dir_roots: {},
        single_root: true
      }
    ])
    expect(run.running).toBe(false)
    expect(run.outcomes.map((entry) => entry.code)).toEqual(['S0', 'S1'])
    expect(run.report?.ok).toBe(true)
    expect(run.report?.state).toBe('00_PROJECT/05_流程/pipeline-state.json')
  })

  it('leaves the run untouched for an unknown phase', () => {
    const before = emptyRun()
    const after = applyPipelineEvent(before, { type: 'pipeline', phase: 'start', project: '/p', stages: ['S0'] })
    // `default` is unreachable through the public type, but the switch must not
    // throw if the host ever sends a phase we do not know.
    const unknown = applyPipelineEvent(after, {
      type: 'pipeline',
      phase: 'heartbeat'
    } as unknown as PipelineEvent)
    expect(unknown).toEqual(after)
  })
})

describe('outcomesByCode', () => {
  it('keys the last outcome for each stage', () => {
    const run = fold(emptyRun(), [
      { type: 'pipeline', phase: 'start', project: '/p', stages: ['S0'] },
      stageEvent('S0', { status: 'failed' }),
      stageEvent('S0', { status: 'done' })
    ])
    const index = outcomesByCode(run)
    expect(index['S0']?.status).toBe('done')
    expect(Object.keys(index)).toEqual(['S0'])
  })
})

describe('orderedSteps', () => {
  it('follows the host order and sorts unknown keys last', () => {
    const payload = stepsPayload({
      order: ['parse', 'cast', 'board'],
      steps: [step('board'), step('extra'), step('parse'), step('cast')]
    })
    expect(orderedSteps(payload).map((entry) => entry.key)).toEqual(['parse', 'cast', 'board', 'extra'])
  })

  it('degrades to the payload order when no order is given', () => {
    const payload = stepsPayload({ steps: [step('b'), step('a')] })
    expect(orderedSteps(payload).map((entry) => entry.key)).toEqual(['b', 'a'])
  })

  it('is empty without a payload', () => {
    expect(orderedSteps(null)).toEqual([])
  })
})
