/**
 * Shapes and the live-run reducer for the workbench (`pipeline/*`).
 *
 * A run is not a request/response: the host pushes `pipeline/event` frames while
 * it works, and the panel has to show progress from them. That reduction is the
 * one piece of real logic here, so it lives in a pure function — `apply` takes
 * the state and an event and returns the next state — and is unit-tested without
 * a host, a timer or a Vue instance.
 *
 * Everything else mirrors `lib/comfy_studio/pipeline.py` field for field.
 */

/** What one stage looks like right now. Four states, deliberately not a
 *  percentage: `text` means "the text half is written, the real artifact still
 *  needs a render" and `missing` means "the ledger says it ran, the disk says
 *  otherwise" — and the user's next move differs in each case. */
export type StageMark = 'done' | 'text' | 'missing' | 'todo'
/** What one workbench step looks like. Two of these only exist at step level. */
export type StepMark = 'done' | 'partial' | 'empty'
/** The host's ledger vocabulary. `skipped` is "ran before, artifact still here". */
export type RunStatus = 'done' | 'skipped' | 'failed'

export type PipelinePhase = 'start' | 'stage_start' | 'stage' | 'finished'

/** A stage's static definition: who does it, what it leaves, what else it needs. */
export interface StageTask {
  code: string
  name: string
  owner: string
  /** Preset agent id; empty means this stage uses no model at all. */
  agent: string
  /** Display form of `agent`, already resolved by the host. */
  actor: string
  /** The stage's text artifact, relative to the project root. Never empty. */
  artifact: string
  needs_render: boolean
  brief: string
  check_dirs: string[]
  check_exts: string[]
  /** Render target ids, for the "make images" buttons. */
  render_targets: string[]
  /** target id -> the directory that target's output belongs in. */
  render_lands: Record<string, string>
  render_note: string
}

/** A stage inside a workbench step: the definition plus the current verdict. */
export interface StageEntry extends StageTask {
  state: StageMark
  /** Localised display name of `agent`, empty when it is a mechanical check. */
  agent_name: string
  /** One line on how this stage is judged. */
  how: string
}

export interface StepLandingFile {
  rel: string
  name: string
  bytes: number
  mtime: number
  readable: boolean
  seed: boolean
}

/** A directory a step writes into, resolved to a real path by the host. */
export interface StepLanding {
  rel: string
  title: string
  /** Absolute path — computed host-side because `12_FILMS` lives under the
   *  output root, and "project root + rel" would silently point at the wrong
   *  tree. */
  dir: string
  root: string
  shelf: string
  scope: string
  exists: boolean
  files: StepLandingFile[]
  count: number
  seed_count: number
  truncated: boolean
}

export interface WorkbenchStep {
  key: string
  name: string
  goal: string
  note: string
  /** Step keys this one consumes. */
  needs: string[]
  /** Only the upstream steps that are not finished yet. */
  blocked_by: string[]
  ready: boolean
  stages: StageEntry[]
  landings: StepLanding[]
  count: number
  seed_count: number
  state: StepMark
}

/** `pipeline/steps` — the eight-step workbench. */
export interface StepsPayload {
  project: string
  name: string
  novel: string | null
  linked_novel: string
  /** Input files every step needs before the chain can run, still absent. */
  gaps: string[]
  order: string[]
  /** The first step that is not done, or '' when everything is. */
  current: string
  steps: WorkbenchStep[]
  render_required: string[]
  roots: Record<string, string>
  dir_roots: Record<string, string>
  single_root: boolean
}

/** One line of the progress ledger, as the host writes it. */
export interface LedgerRecord {
  status: RunStatus | string
  artifact?: string
  at?: string
  note?: string
  error?: string
}

/** `pipeline/plan` — the full chain, read-only. */
export interface PlanPayload {
  project: string
  novel: string | null
  stages: StageTask[]
  /** Stage code -> ledger record. */
  state: Record<string, LedgerRecord>
  render_required: string[]
  roots: Record<string, string>
  dir_roots: Record<string, string>
  single_root: boolean
}

/** `pipeline/state` — the ledger on its own. */
export interface StatePayload {
  project: string
  version: number | null
  updated: string | null
  stages: Record<string, LedgerRecord>
  roots: Record<string, string>
  dir_roots: Record<string, string>
  single_root: boolean
}

/** How one stage ended in this run. */
export interface StageOutcome {
  code: string
  name: string
  status: RunStatus
  agent: string
  artifact: string
  needs_render: boolean
  /** Text is there, the renderable artifact still isn't: a real, named state. */
  render_pending: boolean
  render_targets: string[]
  render_lands: Record<string, string>
  render_note: string
  seconds: number
  note: string
  error: string
}

/** The `finished` payload — one run, summarised. */
export interface RunReport {
  project: string
  novel: string | null
  state: string
  ok: boolean
  ran: string[]
  not_ran: string[]
  render_required: string[]
  stages: StageOutcome[]
  roots: Record<string, string>
  dir_roots: Record<string, string>
  single_root: boolean
}

interface PipelineEventBase {
  type: 'pipeline'
}

export interface PipelineStartEvent extends PipelineEventBase {
  phase: 'start'
  project: string
  /** The stage codes this run will attempt, in order. */
  stages: string[]
}

export interface PipelineStageStartEvent extends PipelineEventBase {
  phase: 'stage_start'
  code: string
  name: string
  actor: string
}

export interface PipelineStageEvent extends PipelineEventBase, StageOutcome {
  phase: 'stage'
}

export interface PipelineFinishedEvent extends PipelineEventBase, RunReport {
  phase: 'finished'
}

export type PipelineEvent =
  | PipelineStartEvent
  | PipelineStageStartEvent
  | PipelineStageEvent
  | PipelineFinishedEvent

/** What the panel knows about the run in flight. */
export interface LiveRun {
  running: boolean
  /** Stage codes announced by `start`. */
  planned: string[]
  /** Stage currently executing, or '' between stages. */
  activeCode: string
  activeName: string
  activeActor: string
  /** Outcomes so far, in the order they arrived. */
  outcomes: StageOutcome[]
  /** Set by `finished`; cleared when a new run starts. */
  report: RunReport | null
}

export function emptyRun(): LiveRun {
  return {
    running: false,
    planned: [],
    activeCode: '',
    activeName: '',
    activeActor: '',
    outcomes: [],
    report: null
  }
}

/** Narrow an unknown event payload to a pipeline frame.
 *
 * The studio event channel carries agent traffic too, so this is the filter that
 * keeps someone else's event from being reduced into our run state.
 */
export function isPipelineEvent(payload: unknown): payload is PipelineEvent {
  if (typeof payload !== 'object' || payload === null) return false
  const frame = payload as { type?: unknown; phase?: unknown }
  return (
    frame.type === 'pipeline' &&
    (frame.phase === 'start' ||
      frame.phase === 'stage_start' ||
      frame.phase === 'stage' ||
      frame.phase === 'finished')
  )
}

/**
 * Fold one event into the run state, returning a new object.
 *
 * A `start` resets everything: a second run must not inherit the first run's
 * outcomes, or a failed stage from last time would look like it failed just now.
 * Anything that arrives that we cannot place (a `stage` for a code we never
 * planned) is still recorded — dropping it would make the panel quietly
 * disagree with the host about what happened.
 */
export function applyPipelineEvent(run: LiveRun, event: PipelineEvent): LiveRun {
  switch (event.phase) {
    case 'start':
      return {
        running: true,
        planned: [...event.stages],
        activeCode: '',
        activeName: '',
        activeActor: '',
        outcomes: [],
        report: null
      }
    case 'stage_start':
      return { ...run, running: true, activeCode: event.code, activeName: event.name, activeActor: event.actor }
    case 'stage': {
      const outcome = stageOutcomeOf(event)
      return {
        ...run,
        running: true,
        // The stage is over, whatever it decided.
        activeCode: '',
        activeName: '',
        activeActor: '',
        outcomes: [...run.outcomes, outcome]
      }
    }
    case 'finished':
      return {
        ...run,
        running: false,
        activeCode: '',
        activeName: '',
        activeActor: '',
        // `finished` restates the whole run; prefer it over the incremental
        // list so a missed frame cannot leave the panel short of a stage.
        outcomes: [...event.stages],
        report: runReportOf(event)
      }
    default:
      return run
  }
}

function stageOutcomeOf(event: PipelineStageEvent): StageOutcome {
  return {
    code: event.code,
    name: event.name,
    status: event.status,
    agent: event.agent,
    artifact: event.artifact,
    needs_render: event.needs_render,
    render_pending: event.render_pending,
    render_targets: event.render_targets,
    render_lands: event.render_lands,
    render_note: event.render_note,
    seconds: event.seconds,
    note: event.note,
    error: event.error
  }
}

function runReportOf(event: PipelineFinishedEvent): RunReport {
  return {
    project: event.project,
    novel: event.novel,
    state: event.state,
    ok: event.ok,
    ran: event.ran,
    not_ran: event.not_ran,
    render_required: event.render_required,
    stages: event.stages,
    roots: event.roots,
    dir_roots: event.dir_roots,
    single_root: event.single_root
  }
}

/** Outcomes keyed by stage code, for asking "how did S4 go?" in one look. */
export function outcomesByCode(run: LiveRun): Record<string, StageOutcome> {
  const out: Record<string, StageOutcome> = {}
  for (const outcome of run.outcomes) out[outcome.code] = outcome
  return out
}

/** The eight workbench steps, in a fixed display order. A step whose key is not
 *  in the host's payload is simply not rendered — the host's list wins. */
export function orderedSteps(payload: StepsPayload | null): WorkbenchStep[] {
  if (!payload) return []
  const rank = new Map(payload.order.map((key, index) => [key, index]))
  return [...payload.steps].sort(
    (left, right) => (rank.get(left.key) ?? Number.MAX_SAFE_INTEGER) - (rank.get(right.key) ?? Number.MAX_SAFE_INTEGER)
  )
}
