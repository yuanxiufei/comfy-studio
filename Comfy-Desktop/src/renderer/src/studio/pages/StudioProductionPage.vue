<script setup lang="ts">
/**
 * Production: the eight-step workbench, the full chain behind it, and the run.
 *
 * Three habits here.
 *
 * First, the page never invents progress. "Is this step done?" is answered by the
 * host (`pipeline/steps`); while a run is in flight it is answered by the
 * `pipeline/event` frames, folded by the reducer in `./pipeline.ts`. So a stage
 * whose artifact was deleted reads as `missing` rather than as done.
 *
 * Second, the step list and the chain are *different orders* and both are shown.
 * The workbench is the order a person works in; `pipeline/plan` is the order the
 * host executes stages in. A range sliced by step order would be backwards, so
 * the range picker is built from the plan.
 *
 * Third, the project is not owned here: it is the projects page's current
 * selection. Two selections would let the two pages disagree about which show is
 * being made.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  FolderOpen,
  ListChecks,
  LoaderCircle,
  Play,
  RefreshCw
} from 'lucide-vue-next'
import { usePipelineStore } from '../../stores/pipelineStore'
import { useProjectsStore } from '../../stores/projectsStore'
import { formatBytes } from './novels'
import type { LedgerRecord, RunStatus, WorkbenchStep } from './pipeline'

const pipeline = usePipelineStore()
const projects = useProjectsStore()
const { t, te, n } = useI18n()

type View = 'step' | 'plan' | 'ledger'

const view = ref<View>('step')
const activeKey = ref('')
const fromCode = ref('')
const toCode = ref('')

const steps = computed(() => pipeline.ordered)
const activeStep = computed(() => steps.value.find((step) => step.key === activeKey.value) ?? null)
const doneSteps = computed(() => steps.value.filter((step) => step.state === 'done').length)
const problem = computed(() => pipeline.error ?? projects.error)

/** The picker writes through to the projects store: one selection, two pages. */
const picker = computed({
  get: () => projects.selected,
  set: (value: string) => {
    void projects.select(value)
  }
})

/**
 * Stage codes in the host's own execution order. `plan` is preferred because it
 * *is* that order; the flattened steps are only a fallback for a slower load.
 */
const chainCodes = computed<string[]>(() => {
  const planned = pipeline.plan?.stages.map((stage) => stage.code) ?? []
  if (planned.length > 0) return planned
  return steps.value.flatMap((step) => step.stages.map((stage) => stage.code))
})

const rangeValid = computed(() => {
  const from = chainCodes.value.indexOf(fromCode.value)
  const to = chainCodes.value.indexOf(toCode.value)
  return from >= 0 && to >= from
})

const failed = computed(() => pipeline.run.outcomes.find((left) => left.status === 'failed') ?? null)

const ledgerRows = computed<{ code: string; row: LedgerRecord }[]>(() => {
  const record = pipeline.ledger?.stages ?? {}
  const rank = new Map(chainCodes.value.map((code, index) => [code, index]))
  return Object.entries(record)
    .map(([code, row]) => ({ code, row }))
    .sort(
      (left, right) =>
        (rank.get(left.code) ?? Number.MAX_SAFE_INTEGER) -
        (rank.get(right.code) ?? Number.MAX_SAFE_INTEGER)
    )
})

/** Catalogue names are the host's; the i18n table is ours. Prefer ours, and
 *  fall back to the host so a stage added there still renders a word. */
function stepName(step: WorkbenchStep): string {
  const key = `studio.production.steps.${step.key}.name`
  return te(key) ? t(key) : step.name
}

function stepGoal(step: WorkbenchStep): string {
  const key = `studio.production.steps.${step.key}.goal`
  return te(key) ? t(key) : step.goal
}

function stepRefName(key: string): string {
  const step = steps.value.find((item) => item.key === key)
  return step ? stepName(step) : key
}

function stageName(code: string, fallback: string): string {
  const key = `studio.production.stageNames.${code}`
  return te(key) ? t(key) : fallback
}

function statusLabel(status: RunStatus | string): string {
  const key = `studio.production.outcome.${status}`
  return te(key) ? t(key) : status
}

function planStatus(code: string): string {
  return pipeline.plan?.state[code]?.status ?? 'todo'
}

function planLabel(code: string): string {
  const status = planStatus(code)
  return status === 'todo' ? t('studio.production.stageMark.todo') : statusLabel(status)
}

function landPairs(lands: Record<string, string>): { target: string; dir: string }[] {
  return Object.entries(lands).map(([target, dir]) => ({ target, dir }))
}

function select(key: string): void {
  view.value = 'step'
  activeKey.value = key
}

function runStep(): void {
  if (activeStep.value) void pipeline.runStep(activeStep.value)
}

function runFrom(): void {
  if (activeStep.value) void pipeline.runFrom(activeStep.value)
}

function runRange(): void {
  if (rangeValid.value) void pipeline.runRange(fromCode.value, toCode.value)
}

onMounted(async () => {
  if (!projects.loadedShelf) await projects.refresh()
  if (projects.selected) await pipeline.load(projects.selected)
})

watch(
  () => projects.selected,
  (name) => {
    if (name === '') pipeline.reset()
    else void pipeline.load(name)
  }
)

/** Follow the host's "you are here" pointer, but never steal a step the user
 *  picked — only land on `current` when we have nothing valid to show. */
watch(
  () => pipeline.steps,
  (payload) => {
    if (!payload) return
    if (payload.steps.some((step) => step.key === activeKey.value)) return
    activeKey.value = payload.current || steps.value[0]?.key || ''
    view.value = 'step'
  },
  { immediate: true }
)

watch(
  chainCodes,
  (codes) => {
    const first = codes[0]
    const last = codes[codes.length - 1]
    if (!codes.includes(fromCode.value) && first !== undefined) fromCode.value = first
    if (!codes.includes(toCode.value) && last !== undefined) toCode.value = last
  },
  { immediate: true }
)
</script>

<template>
  <section class="prd">
    <p v-if="problem" class="prd__error">
      <AlertCircle :size="14" />
      <span>{{ problem }}</span>
    </p>

    <header class="prd__bar">
      <label class="prd__field is-grow">
        <span>{{ t('studio.production.project') }}</span>
        <select v-model="picker">
          <option value="">{{ t('studio.production.noProject') }}</option>
          <option v-for="project in projects.projects" :key="project.name" :value="project.name">
            {{ project.name }}
          </option>
        </select>
      </label>
      <button type="button" class="prd__btn" :disabled="pipeline.loading" @click="pipeline.reload()">
        <LoaderCircle v-if="pipeline.loading" :size="13" class="is-spinning" />
        <RefreshCw v-else :size="13" />
        <span>{{ t('studio.production.refresh') }}</span>
      </button>
      <span v-if="pipeline.steps" class="prd__chip" :class="{ 'is-bad': pipeline.steps.gaps.length > 0 }">
        {{
          pipeline.steps.gaps.length > 0
            ? t('studio.production.gaps', { count: n(pipeline.steps.gaps.length) })
            : t('studio.production.gapsNone')
        }}
      </span>
      <span v-if="pipeline.steps" class="prd__meta">
        {{
          pipeline.currentStep
            ? t('studio.production.current', { name: stepName(pipeline.currentStep) })
            : t('studio.production.currentNone')
        }}
      </span>
    </header>

    <p v-if="pipeline.name === ''" class="prd__hint">{{ t('studio.production.noProject') }}</p>

    <div v-else class="prd__split">
      <aside class="prd__nav">
        <p class="prd__meta">
          {{
            t('studio.production.stepProgress', {
              done: n(doneSteps),
              total: n(steps.length)
            })
          }}
        </p>
        <button
          v-for="step in steps"
          :key="step.key"
          type="button"
          class="prd__step"
          :class="{ 'is-active': view === 'step' && step.key === activeKey }"
          @click="select(step.key)"
        >
          <span class="prd__dot" :class="`is-${step.state}`" />
          <span class="prd__stepName">{{ stepName(step) }}</span>
          <span class="prd__meta">{{ n(step.count) }}</span>
        </button>
        <div class="prd__views">
          <button
            type="button"
            class="prd__step"
            :class="{ 'is-active': view === 'plan' }"
            @click="view = 'plan'"
          >
            <ListChecks :size="13" />
            <span class="prd__stepName">{{ t('studio.production.plan') }}</span>
          </button>
          <button
            type="button"
            class="prd__step"
            :class="{ 'is-active': view === 'ledger' }"
            @click="view = 'ledger'"
          >
            <FileText :size="13" />
            <span class="prd__stepName">{{ t('studio.production.ledger') }}</span>
          </button>
        </div>
      </aside>

      <div class="prd__work">
        <div v-if="pipeline.running || pipeline.run.outcomes.length > 0" class="prd__run">
          <p class="prd__runLine">
            <LoaderCircle v-if="pipeline.running" :size="13" class="is-spinning" />
            <CheckCircle2 v-else :size="13" />
            <span v-if="pipeline.running">
              {{
                pipeline.run.activeCode === ''
                  ? t('studio.production.phase.start')
                  : `${t('studio.production.phase.stage_start')} · ${stageName(
                      pipeline.run.activeCode,
                      pipeline.run.activeName
                    )} · ${pipeline.run.activeActor}`
              }}
            </span>
            <span v-else-if="pipeline.report">
              {{
                t('studio.production.reportOk', {
                  ran: n(pipeline.report.ran.length),
                  notRan: n(pipeline.report.not_ran.length)
                })
              }}
            </span>
            <span v-if="failed" class="prd__bad">
              {{ t('studio.production.reportFailed', { code: failed.code }) }}
            </span>
            <span v-if="pipeline.running" class="prd__meta">
              {{ t('studio.production.cancelHint') }}
            </span>
          </p>
          <p v-if="pipeline.run.planned.length > 0" class="prd__meta">
            {{ pipeline.run.planned.join(' · ') }}
          </p>
          <ul class="prd__outcomes">
            <li
              v-for="outcome in pipeline.run.outcomes"
              :key="outcome.code"
              :class="`is-${outcome.status}`"
            >
              <span class="prd__code">{{ outcome.code }}</span>
              <span class="prd__stageName">{{ stageName(outcome.code, outcome.name) }}</span>
              <span class="prd__chip" :class="`is-${outcome.status}`">
                {{ statusLabel(outcome.status) }}
              </span>
              <span class="prd__meta">
                {{ t('studio.production.outcomeSeconds', { seconds: n(outcome.seconds) }) }}
              </span>
              <span v-if="outcome.render_pending" class="prd__warn">
                {{ t('studio.production.renderPending', { targets: outcome.render_targets.join(', ') }) }}
              </span>
              <span v-if="outcome.note" class="prd__meta">{{ outcome.note }}</span>
              <span v-if="outcome.error" class="prd__bad">
                {{ t('studio.production.outcomeError') }}: {{ outcome.error }}
              </span>
            </li>
          </ul>
        </div>

        <template v-if="view === 'step'">
          <template v-if="activeStep">
            <header class="prd__head">
              <span class="prd__h">{{ stepName(activeStep) }}</span>
              <span class="prd__chip" :class="`is-${activeStep.state}`">
                {{ t(`studio.production.stepMark.${activeStep.state}`) }}
              </span>
              <span v-if="activeStep.ready" class="prd__ok">{{ t('studio.production.ready') }}</span>
              <span v-else class="prd__warn">
                {{
                  t('studio.production.blockedBy', {
                    names: activeStep.blocked_by.map((key) => stepRefName(key)).join('、')
                  })
                }}
              </span>
            </header>

            <p class="prd__goal">{{ stepGoal(activeStep) }}</p>
            <p v-if="activeStep.note" class="prd__meta">{{ activeStep.note }}</p>

            <div class="prd__actions">
              <button
                type="button"
                class="prd__btn is-primary"
                :disabled="pipeline.running || activeStep.stages.length === 0"
                @click="runStep"
              >
                <LoaderCircle v-if="pipeline.running" :size="13" class="is-spinning" />
                <Play v-else :size="13" />
                <span>{{ t('studio.production.runStep') }}</span>
              </button>
              <button
                type="button"
                class="prd__btn"
                :disabled="pipeline.running || activeStep.stages.length === 0"
                @click="runFrom"
              >
                <span>{{ t('studio.production.runFrom') }}</span>
              </button>
              <label class="prd__check" :title="t('studio.production.forceHint')">
                <input v-model="pipeline.force" type="checkbox" />
                <span>{{ t('studio.production.force') }}</span>
              </label>
            </div>

            <div class="prd__actions">
              <label class="prd__field is-narrow">
                <span>{{ t('studio.production.from') }}</span>
                <select v-model="fromCode">
                  <option v-for="code in chainCodes" :key="code" :value="code">
                    {{ code }} · {{ stageName(code, code) }}
                  </option>
                </select>
              </label>
              <label class="prd__field is-narrow">
                <span>{{ t('studio.production.to') }}</span>
                <select v-model="toCode">
                  <option v-for="code in chainCodes" :key="code" :value="code">
                    {{ code }} · {{ stageName(code, code) }}
                  </option>
                </select>
              </label>
              <button
                type="button"
                class="prd__btn is-primary"
                :disabled="pipeline.running || !rangeValid"
                @click="runRange"
              >
                <span>{{ t('studio.production.runRange') }}</span>
              </button>
              <button
                type="button"
                class="prd__btn"
                :disabled="pipeline.running || chainCodes.length === 0"
                @click="pipeline.runAll()"
              >
                <span>{{ t('studio.production.all') }}</span>
              </button>
            </div>

            <p class="prd__label">{{ t('studio.production.stages') }}</p>
            <p v-if="activeStep.stages.length === 0" class="prd__meta">
              {{ t('studio.production.noStagesInStep') }}
            </p>
            <ul v-else class="prd__stages">
              <li v-for="stage in activeStep.stages" :key="stage.code" :class="`is-${stage.state}`">
                <span class="prd__code">{{ stage.code }}</span>
                <span class="prd__stageName">{{ stageName(stage.code, stage.name) }}</span>
                <span class="prd__chip" :class="`is-${stage.state}`">
                  {{ t(`studio.production.stageMark.${stage.state}`) }}
                </span>
                <span class="prd__meta">{{ stage.agent_name || stage.actor }}</span>
                <span v-if="stage.needs_render" class="prd__warn">
                  {{ t('studio.production.needsRender') }}
                </span>
                <span class="prd__how">{{ stage.how }}</span>
                <span class="prd__meta">
                  {{ t('studio.production.artifact', { name: stage.artifact }) }}
                </span>
                <span v-for="pair in landPairs(stage.render_lands)" :key="pair.target" class="prd__meta">
                  {{ t('studio.production.renderLand', { target: pair.target, dir: pair.dir }) }}
                </span>
              </li>
            </ul>

            <p class="prd__label">{{ t('studio.production.landings') }}</p>
            <div v-for="landing in activeStep.landings" :key="landing.rel" class="prd__landing">
              <p class="prd__landingHead">
                <span class="prd__stageName">{{ landing.title }}</span>
                <span class="prd__meta">
                  {{
                    landing.exists
                      ? t('studio.production.landingFiles', { count: n(landing.count) })
                      : t('studio.production.landingEmpty')
                  }}
                </span>
                <span v-if="landing.seed_count > 0" class="prd__meta">
                  {{ t('studio.production.landingSeeds', { count: n(landing.seed_count) }) }}
                </span>
                <span class="prd__meta">
                  {{ t('studio.production.landingDir', { dir: landing.dir }) }}
                </span>
              </p>
              <ul v-if="landing.files.length > 0" class="prd__files">
                <li
                  v-for="entry in landing.files"
                  :key="entry.rel"
                  :class="{ 'is-seed': entry.seed }"
                >
                  <FolderOpen v-if="entry.seed" :size="12" />
                  <FileText v-else :size="12" />
                  <span class="prd__fileName">{{ entry.name }}</span>
                  <span class="prd__meta">{{ formatBytes(entry.bytes) }}</span>
                </li>
              </ul>
            </div>
          </template>
          <p v-else class="prd__hint">{{ t('studio.production.loading') }}</p>
        </template>

        <template v-else-if="view === 'plan'">
          <p v-if="pipeline.plan === null" class="prd__hint">{{ t('studio.production.loading') }}</p>
          <template v-else>
            <p class="prd__meta">
              {{ t('studio.production.planStages', { count: n(pipeline.plan.stages.length) }) }}
            </p>
            <ul class="prd__stages">
              <li v-for="stage in pipeline.plan.stages" :key="stage.code">
                <span class="prd__code">{{ stage.code }}</span>
                <span class="prd__stageName">{{ stageName(stage.code, stage.name) }}</span>
                <span class="prd__chip" :class="`is-${planStatus(stage.code)}`">
                  {{ planLabel(stage.code) }}
                </span>
                <span class="prd__meta">{{ stage.actor }}</span>
                <span v-if="stage.needs_render" class="prd__warn">
                  {{ t('studio.production.needsRender') }}
                </span>
                <span class="prd__how">{{ stage.brief }}</span>
                <span class="prd__meta">
                  {{ t('studio.production.artifact', { name: stage.artifact }) }}
                </span>
              </li>
            </ul>
          </template>
        </template>

        <template v-else>
          <p v-if="pipeline.ledger && pipeline.ledger.updated" class="prd__meta">
            {{ t('studio.production.ledgerAt', { at: pipeline.ledger.updated }) }}
          </p>
          <p v-if="ledgerRows.length === 0" class="prd__hint">
            {{ t('studio.production.ledgerEmpty') }}
          </p>
          <ul v-else class="prd__stages">
            <li v-for="row in ledgerRows" :key="row.code" :class="`is-${row.row.status}`">
              <span class="prd__code">{{ row.code }}</span>
              <span class="prd__stageName">{{ stageName(row.code, row.code) }}</span>
              <span class="prd__chip" :class="`is-${row.row.status}`">
                {{ statusLabel(row.row.status) }}
              </span>
              <span v-if="row.row.at" class="prd__meta">{{ row.row.at }}</span>
              <span v-if="row.row.artifact" class="prd__meta">
                {{ t('studio.production.artifact', { name: row.row.artifact }) }}
              </span>
              <span v-if="row.row.note" class="prd__meta">
                {{ t('studio.production.outcomeNote') }}: {{ row.row.note }}
              </span>
              <span v-if="row.row.error" class="prd__bad">{{ row.row.error }}</span>
            </li>
          </ul>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.prd {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  min-height: 0;
}

.prd__error {
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

.prd__bar,
.prd__row,
.prd__actions,
.prd__head,
.prd__runLine,
.prd__landingHead {
  display: flex;
  align-items: center;
  gap: 6px;
}

.prd__runLine,
.prd__landingHead {
  flex-wrap: wrap;
  margin: 0;
}

.prd__actions {
  flex-wrap: wrap;
}

.prd__field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: var(--text-faint);
  font-size: 11px;
}

.prd__field.is-grow {
  flex: 1;
  min-width: 0;
}

.prd__field.is-narrow {
  width: 150px;
}

.prd__field select {
  padding: 4px 6px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.prd__check {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 11px;
}

.prd__btn {
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

.prd__btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--text);
}

.prd__btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.prd__btn.is-primary {
  border-color: var(--accent);
  color: var(--accent);
}

.prd__chip {
  flex: none;
  padding: 1px 6px;
  border: 1px solid var(--studio-card-border);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 10px;
}

.prd__chip.is-done,
.prd__chip.is-skipped {
  border-color: var(--success);
  color: var(--success);
}

.prd__chip.is-text,
.prd__chip.is-partial {
  border-color: var(--warning);
  color: var(--warning);
}

.prd__chip.is-missing,
.prd__chip.is-failed,
.prd__chip.is-bad {
  border-color: var(--danger);
  color: var(--danger);
}

.prd__hint,
.prd__meta,
.prd__goal,
.prd__how,
.prd__label {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.5;
}

.prd__goal {
  color: var(--text-muted);
  font-size: 12px;
}

.prd__how {
  flex-basis: 100%;
}

.prd__label {
  margin-top: 4px;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
}

.prd__ok {
  margin: 0;
  color: var(--success);
  font-size: 11px;
}

.prd__warn,
.prd__bad {
  color: var(--warning);
  font-size: 11px;
}

.prd__bad {
  color: var(--danger);
}

.prd__split {
  display: grid;
  grid-template-columns: minmax(150px, 220px) 1fr;
  flex: 1;
  gap: 8px;
  min-height: 0;
}

.prd__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  overflow: auto;
  padding-right: 8px;
  border-right: 1px solid var(--studio-card-border);
}

.prd__views {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--studio-card-border);
}

.prd__step {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  padding: 4px 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.prd__step:hover {
  background: var(--studio-card-bg);
  color: var(--text);
}

.prd__step.is-active {
  border-color: var(--accent);
  color: var(--accent);
}

.prd__dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-faint);
}

.prd__dot.is-done {
  background: var(--success);
}

.prd__dot.is-partial {
  background: var(--warning);
}

.prd__stepName {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prd__work {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow: auto;
}

.prd__run {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  border: 1px solid var(--accent);
  border-radius: 6px;
  background: var(--studio-card-bg);
}

.prd__outcomes,
.prd__stages,
.prd__files {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.prd__outcomes li,
.prd__stages li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  padding: 4px 6px;
  border: 1px solid var(--studio-card-border);
  border-left: 2px solid var(--text-faint);
  border-radius: 5px;
  font-size: 12px;
}

.prd__outcomes li.is-done,
.prd__stages li.is-done,
.prd__stages li.is-skipped {
  border-left-color: var(--success);
}

.prd__outcomes li.is-skipped,
.prd__stages li.is-text,
.prd__stages li.is-partial {
  border-left-color: var(--warning);
}

.prd__outcomes li.is-failed,
.prd__stages li.is-missing,
.prd__stages li.is-failed {
  border-left-color: var(--danger);
}

.prd__code {
  flex: none;
  color: var(--text-faint);
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 11px;
}

.prd__stageName {
  color: var(--text);
}

.prd__landing {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 8px;
}

.prd__files li.is-seed .prd__fileName {
  color: var(--text-faint);
}

.prd__fileName {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prd__files li {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 11px;
}

.is-spinning {
  animation: prd-spin 900ms linear infinite;
}

@keyframes prd-spin {
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
