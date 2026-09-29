/**
 * The workbench's run state, driven by `pipeline/*` plus the `pipeline/event`
 * frames the host pushes while a run is in flight.
 *
 * The project being worked on is *not* owned here: the project page already has
 * a current project, and having two selections would let the two pages disagree
 * about which show is being made. So every entry point takes the name.
 *
 * Progress is `run` (see `pages/pipeline.ts` for the reducer) and it is only
 * ever advanced by events. A `pipeline/run` response is not folded into it: the
 * response arrives after `finished`, and treating it as the source of truth
 * would mean the last frame and the return value could disagree.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  applyPipelineEvent,
  emptyRun,
  isPipelineEvent,
  orderedSteps,
  outcomesByCode,
  type LiveRun,
  type PlanPayload,
  type RunReport,
  type StageOutcome,
  type StatePayload,
  type StepsPayload,
  type WorkbenchStep
} from '../studio/pages/pipeline'
import { callStudio } from '../studio/pages/rpc'

export const usePipelineStore = defineStore('studioPipeline', () => {
  const name = ref('')
  const steps = ref<StepsPayload | null>(null)
  const plan = ref<PlanPayload | null>(null)
  const ledger = ref<StatePayload | null>(null)
  const loading = ref(false)
  const loaded = ref(false)
  const running = ref(false)
  const force = ref(false)
  const error = ref<string | null>(null)

  /** Progress of the run in flight, or of the last one. */
  const run = ref<LiveRun>(emptyRun())

  let unsubscribe: (() => void) | null = null

  const ordered = computed(() => orderedSteps(steps.value))
  const outcomes = computed(() => outcomesByCode(run.value))
  const report = computed<RunReport | null>(() => run.value.report)

  const currentStep = computed(() =>
    steps.value === null
      ? null
      : (ordered.value.find((step) => step.key === steps.value?.current) ?? null)
  )

  function onEvent(payload: unknown): void {
    if (!isPipelineEvent(payload)) return
    run.value = applyPipelineEvent(run.value, payload)
    running.value = run.value.running
    // A finished run changed the disk, so the workbench is now stale.
    if (payload.phase === 'finished') void Promise.all([loadSteps(), loadLedger()])
  }

  /** Subscribe once. The studio event channel is shared with the agent, so the
   *  guard inside `applyPipelineEvent` decides what is ours. */
  function subscribe(): void {
    if (unsubscribe) return
    unsubscribe = window.api.onStudioEvent(onEvent)
  }

  async function loadSteps(): Promise<void> {
    if (name.value === '') return
    loading.value = true
    const outcome = await callStudio<StepsPayload>('pipeline/steps', { name: name.value })
    loading.value = false
    loaded.value = true
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      return
    }
    error.value = null
    steps.value = outcome.value
  }

  async function loadLedger(): Promise<void> {
    if (name.value === '') return
    const outcome = await callStudio<StatePayload>('pipeline/state', { name: name.value })
    if (outcome.ok && outcome.value) ledger.value = outcome.value
  }

  async function loadPlan(): Promise<void> {
    if (name.value === '') return
    const outcome = await callStudio<PlanPayload>('pipeline/plan', { name: name.value })
    if (outcome.ok && outcome.value) plan.value = outcome.value
  }

  /** Point the workbench at a project. A no-op re-entry keeps the current view. */
  async function load(project: string, options: { reload?: boolean } = {}): Promise<void> {
    subscribe()
    if (project === name.value && !options.reload) return
    name.value = project
    steps.value = null
    plan.value = null
    ledger.value = null
    run.value = emptyRun()
    error.value = null
    await Promise.all([loadSteps(), loadPlan(), loadLedger()])
  }

  async function reload(): Promise<void> {
    await Promise.all([loadSteps(), loadPlan(), loadLedger()])
  }

  /**
   * Run a range of stages. `from`/`to` are stage codes; both inclusive, both
   * optional at the host's end, but always given here so the button says exactly
   * what it will do.
   */
  async function runRange(from: string, to: string): Promise<void> {
    if (name.value === '' || running.value) return
    running.value = true
    error.value = null
    // Optimistically mark the run as started: the `start` event and this call
    // race, and a panel that looks idle for 200ms invites a second click.
    run.value = { ...emptyRun(), running: true }
    const outcome = await callStudio<RunReport>('pipeline/run', {
      name: name.value,
      from,
      to,
      force: force.value
    })
    running.value = false
    if (!outcome.ok || !outcome.value) {
      error.value = outcome.error
      // The run never started (or died before `finished`): stop showing a
      // spinner that will never resolve.
      run.value = { ...run.value, running: false }
      return
    }
    // Normally `finished` already arrived and filled this in. If the events were
    // missed entirely, the response is still a faithful summary.
    if (run.value.report === null) {
      run.value = { ...run.value, running: false, outcomes: [...outcome.value.stages], report: outcome.value }
    }
  }

  /** Run just one step of the workbench. */
  async function runStep(step: WorkbenchStep): Promise<void> {
    const codes = step.stages.map((stage) => stage.code)
    const first = codes[0]
    const last = codes[codes.length - 1]
    if (first === undefined || last === undefined) return
    await runRange(first, last)
  }

  /** The last stage code in the chain, or undefined when nothing is loaded. */
  function lastStageCode(): string | undefined {
    const tail = ordered.value[ordered.value.length - 1]?.stages
    return tail?.[tail.length - 1]?.code
  }

  /** Run from a step to the end of the chain. */
  async function runFrom(step: WorkbenchStep): Promise<void> {
    const first = step.stages[0]?.code
    const end = lastStageCode()
    if (first === undefined || end === undefined) return
    await runRange(first, end)
  }

  async function runAll(): Promise<void> {
    const first = ordered.value[0]?.stages[0]?.code
    const end = lastStageCode()
    if (first === undefined || end === undefined) return
    await runRange(first, end)
  }

  /** How one stage ended in the run in flight, if it has. */
  function outcomeOf(code: string): StageOutcome | null {
    return outcomes.value[code] ?? null
  }

  function dispose(): void {
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
  }

  function reset(): void {
    dispose()
    name.value = ''
    steps.value = null
    plan.value = null
    ledger.value = null
    run.value = emptyRun()
    running.value = false
    loaded.value = false
    error.value = null
  }

  return {
    name,
    steps,
    plan,
    ledger,
    loading,
    loaded,
    running,
    force,
    error,
    run,
    ordered,
    outcomes,
    report,
    currentStep,
    subscribe,
    load,
    reload,
    runRange,
    runStep,
    runFrom,
    runAll,
    outcomeOf,
    dispose,
    reset
  }
})
