/**
 * Run state for the capability page's "跑一次" forms.
 *
 * Kept apart from `capabilitiesStore` on purpose: that store answers "what does
 * this host have", this one answers "what just happened when I tried it". The
 * inventory survives a failed run — and getting the inventory re-fetched every
 * time a skill errors would be a strange price to pay for one bad parameter.
 *
 * State is keyed by row (`skill:<id>` / `render:<id>`) rather than held as a
 * single "current run": a skill answers in milliseconds and a render can take
 * minutes, so two rows genuinely can be running at once, and collapsing them
 * into one slot would make the second click cancel the first one's spinner.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { callStudio } from '../studio/pages/rpc'
import {
  renderKey,
  renderRunRequest,
  runOutcome,
  skillKey,
  type RenderRunInput,
  type RenderRunPayload,
  type RunOutcome,
  type SkillRunPayload
} from '../studio/pages/runs'

/**
 * Why a run never reached the engine.
 *
 * `transport` is the host's own message and renders as-is. `duration` is a
 * local refusal: `duration_sec` has to be a number and the host answers a
 * non-number with a protocol error, so the form stops it first — and the store
 * returns the *reason*, not a sentence, because the wording belongs to the
 * locale files rather than to a Pinia store.
 */
export type RunRefusal = 'transport' | 'duration'

export interface RunAnswer {
  ok: boolean
  /** Transport message, already prose from the host or the IPC layer. */
  error?: string
  refusal?: RunRefusal
}

/** What the render form collects beyond its parameter fields. */
export type RenderRunRequest = RenderRunInput

export const useCapabilityRunStore = defineStore('studioCapabilityRun', () => {
  const running = ref<Record<string, boolean>>({})
  const outcomes = ref<Record<string, RunOutcome | null>>({})
  const errors = ref<Record<string, string | null>>({})

  function isRunning(key: string): boolean {
    return Boolean(running.value[key])
  }

  function outcomeFor(key: string): RunOutcome | null {
    return outcomes.value[key] ?? null
  }

  function errorFor(key: string): string | null {
    return errors.value[key] ?? null
  }

  /** Claim a row and clear its previous result, so a second run never shows the
   *  first one's artefacts while it works. */
  function begin(key: string): void {
    running.value = { ...running.value, [key]: true }
    outcomes.value = { ...outcomes.value, [key]: null }
    errors.value = { ...errors.value, [key]: null }
  }

  function settle(key: string, outcome: RunOutcome | null, error: string | null): void {
    running.value = { ...running.value, [key]: false }
    if (outcome) outcomes.value = { ...outcomes.value, [key]: outcome }
    if (error) errors.value = { ...errors.value, [key]: error }
    else errors.value = { ...errors.value, [key]: null }
  }

  function clear(key: string): void {
    running.value = { ...running.value, [key]: false }
    outcomes.value = { ...outcomes.value, [key]: null }
    errors.value = { ...errors.value, [key]: null }
  }

  /**
   * Run a skill. `params` is already typed by `collectParams` — this store does
   * not look inside it, so a skill with no parameters and one with six travel
   * the same path.
   */
  async function runSkill(skillId: string, params: Record<string, unknown>): Promise<RunAnswer> {
    const key = skillKey(skillId)
    begin(key)
    const answer = await callStudio<SkillRunPayload>('skills/run', {
      skill_id: skillId,
      params
    })
    if (!answer.ok || !answer.value) {
      settle(key, null, answer.error)
      return { ok: false, error: answer.error, refusal: 'transport' }
    }
    settle(key, runOutcome(answer.value), null)
    return { ok: true }
  }

  /**
   * Run a render target, or any workflow in the directory.
   *
   * `targetId` and `file` are an exclusive pair at the host — sending both is a
   * protocol error — so exactly one is written. Everything optional is *omitted*
   * rather than sent empty: `duration_sec` must be a number, `output_dir` a
   * non-empty path, and an empty string for either is rejected outright.
   */
  async function runRender(
    target: { targetId?: string; file?: string },
    request: RenderRunRequest
  ): Promise<RunAnswer> {
    const id = target.targetId ?? target.file ?? ''
    const key = renderKey(id)

    const built = renderRunRequest(target, request)
    if (!built.ok) {
      // Refused before the row is claimed: nothing was sent, so leaving a
      // spinner behind would be a lie.
      settle(key, null, null)
      return { ok: false, refusal: built.refusal }
    }

    begin(key)
    const answer = await callStudio<RenderRunPayload>('renders/run', built.payload)
    if (!answer.ok || !answer.value) {
      settle(key, null, answer.error)
      return { ok: false, error: answer.error, refusal: 'transport' }
    }
    settle(key, runOutcome(answer.value), null)
    return { ok: true }
  }

  /** How many rows are mid-run — the page's only unload guard. */
  const activeCount = computed(
    () => Object.values(running.value).filter((busy) => busy).length
  )

  function reset(): void {
    running.value = {}
    outcomes.value = {}
    errors.value = {}
  }

  return {
    running,
    outcomes,
    errors,
    activeCount,
    isRunning,
    outcomeFor,
    errorFor,
    clear,
    runSkill,
    runRender,
    reset
  }
})
