<script setup lang="ts">
/**
 * What this machine can do: skills, render targets, workflow images, MCP tools.
 *
 * Four lists that come from four different places, and the page's job is to keep
 * them apart. Each group renders its own error and its own "not configured" note,
 * because the honest answer to "why is this empty?" differs per group — a missing
 * engine directory is something to go and fix, a genuinely empty catalog is not.
 * See `groupState` for how the two are told apart.
 *
 * Three of the four groups can also be run from here, and the form opens in
 * place rather than on the production page: the point of this page is the
 * catalogue, and a form next to the entry you just read keeps the parameters,
 * the description and the result in one eyeful. Skills use `skills/run`, render
 * targets use `renders/run` with `target_id`, and workflow files use
 * `renders/run` with `file` — that last one is the path the host documents for
 * "an image the user saved themselves", which runs the graph *as stored* and
 * takes no parameters. MCP tools stay read-only: they are called by the agent,
 * not by this panel.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  AlertCircle,
  Boxes,
  Image,
  LoaderCircle,
  Play,
  RefreshCw,
  Sparkles,
  TriangleAlert,
  Wrench
} from 'lucide-vue-next'
import { useCapabilitiesStore } from '../../stores/capabilitiesStore'
import { useCapabilityRunStore, type RunRefusal } from '../../stores/capabilityRunStore'
import {
  capabilityTallies,
  groupState,
  requiredParams,
  toolParamCount,
  type SkillParam
} from './capabilities'
import { renderKey, skillKey } from './runs'
import { formatBytes } from './novels'
import StudioRunForm from '../StudioRunForm.vue'
import StudioRunResult from '../StudioRunResult.vue'

const capabilities = useCapabilitiesStore()
const runs = useCapabilityRunStore()
const { t, n } = useI18n()

onMounted(() => {
  if (!capabilities.loaded) void capabilities.refresh()
})

/** Which row's form is open. One at a time: the forms are wide, and two open
 *  forms would push the entry you are reading off screen. */
const openRun = ref<string | null>(null)
/** Rows refused locally (currently only a non-numeric duration). */
const refusals = ref<Record<string, RunRefusal>>({})

function toggleRun(key: string): void {
  openRun.value = openRun.value === key ? null : key
  if (openRun.value) {
    delete refusals.value[key]
    runs.clear(key)
  }
}

/** Runs always go through the store, so a refused request reports its reason
 *  next to the form that produced it rather than as a toast elsewhere. */
async function submitSkill(skillId: string, params: Record<string, unknown>): Promise<void> {
  const answer = await runs.runSkill(skillId, params)
  if (!answer.ok && answer.refusal) refusals.value[skillKey(skillId)] = answer.refusal
}

async function submitRender(
  target: { targetId: string },
  payload: { params: Record<string, unknown>; images: string; durationSec: string; outputDir: string }
): Promise<void> {
  await runRenderAt({ targetId: target.targetId }, renderKey(target.targetId), payload)
}

/** A workflow file run: `renders/run`'s other addressing mode, for images the
 *  user saved themselves. Fully keyed by filename, so its run state has to be
 *  keyed the same way — a file and a target sharing a result slot would show one
 *  row's artefacts under the other. */
async function submitFile(
  file: string,
  payload: { params: Record<string, unknown>; images: string; durationSec: string; outputDir: string }
): Promise<void> {
  await runRenderAt({ file }, renderKey(file), payload)
}

async function runRenderAt(
  target: { targetId?: string; file?: string },
  key: string,
  payload: { params: Record<string, unknown>; images: string; durationSec: string; outputDir: string }
): Promise<void> {
  const answer = await runs.runRender(target, payload)
  if (!answer.ok && answer.refusal) refusals.value[key] = answer.refusal
}

function refusalFor(key: string): string {
  const refusal = refusals.value[key]
  if (refusal === 'duration') return t('studio.capabilities.run.badDuration')
  return ''
}

const tallies = computed(() =>
  capabilityTallies({
    skills: capabilities.skills,
    targets: capabilities.targets,
    workflows: capabilities.files,
    tools: capabilities.tools
  })
)

const rendersState = computed(() => groupState(capabilities.renders?.note, capabilities.targets.length))
const workflowsState = computed(() =>
  groupState(capabilities.workflows?.note, capabilities.files.length)
)

/** "a, b" — the parameter names a user has to supply, or an empty string. */
function requiredNames(params: readonly SkillParam[]): string {
  return requiredParams(params)
    .map((param) => param.name)
    .join(' · ')
}
</script>

<template>
  <section class="caps">
    <header class="caps__bar">
      <p class="caps__tallies">
        {{ t('studio.capabilities.tallies', { total: n(tallies.total) }) }}
        <span v-if="capabilities.failedGroups > 0" class="caps__warn">
          {{ t('studio.capabilities.someFailed', { count: n(capabilities.failedGroups) }) }}
        </span>
      </p>
      <button
        type="button"
        class="caps__btn"
        :disabled="capabilities.loading"
        @click="capabilities.refresh()"
      >
        <LoaderCircle v-if="capabilities.loading" :size="13" class="is-spinning" />
        <RefreshCw v-else :size="13" />
        <span>{{ t('studio.capabilities.refresh') }}</span>
      </button>
    </header>

    <p v-if="capabilities.loading && !capabilities.loaded" class="caps__hint">
      {{ t('studio.capabilities.loading') }}
    </p>

    <div class="caps__grid">
      <!-- 技能 -->
      <section class="caps__group">
        <header class="caps__groupHead">
          <Sparkles :size="13" />
          <span class="caps__groupTitle">{{ t('studio.capabilities.group.skills') }}</span>
          <span class="caps__dim">{{ n(capabilities.skills.length) }}</span>
        </header>
        <p v-if="capabilities.skillsError" class="caps__error">
          <AlertCircle :size="12" />
          <span>{{ capabilities.skillsError }}</span>
        </p>
        <p v-else-if="capabilities.skills.length === 0" class="caps__hint">
          {{ t('studio.capabilities.empty') }}
        </p>
        <ul v-else class="caps__rows">
          <li v-for="skill in capabilities.skills" :key="skill.id" class="caps__row">
            <div class="caps__rowHead">
              <span class="caps__rowTitle">{{ skill.title || skill.id }}</span>
              <span class="caps__id">{{ skill.id }}</span>
              <button
                type="button"
                class="caps__run"
                :aria-expanded="openRun === skillKey(skill.id)"
                @click="toggleRun(skillKey(skill.id))"
              >
                <Play :size="11" />
                <span>{{ t('studio.capabilities.run.open') }}</span>
              </button>
            </div>
            <p v-if="skill.description" class="caps__desc">{{ skill.description }}</p>
            <p v-if="requiredNames(skill.params)" class="caps__dim">
              {{ t('studio.capabilities.required', { names: requiredNames(skill.params) }) }}
            </p>
            <p v-if="skill.tags.length > 0" class="caps__dim">{{ skill.tags.join(' · ') }}</p>

            <StudioRunForm
              v-if="openRun === skillKey(skill.id)"
              :params="skill.params"
              :busy="runs.isRunning(skillKey(skill.id))"
              @submit="submitSkill(skill.id, $event.params)"
              @cancel="toggleRun(skillKey(skill.id))"
            />
            <p v-if="refusalFor(skillKey(skill.id))" class="caps__error">
              <AlertCircle :size="11" />
              <span>{{ refusalFor(skillKey(skill.id)) }}</span>
            </p>
            <StudioRunResult
              v-if="openRun === skillKey(skill.id)"
              :outcome="runs.outcomeFor(skillKey(skill.id))"
              :error="runs.errorFor(skillKey(skill.id))"
            />
          </li>
        </ul>
      </section>

      <!-- 渲染目标 -->
      <section class="caps__group">
        <header class="caps__groupHead">
          <Image :size="13" />
          <span class="caps__groupTitle">{{ t('studio.capabilities.group.renders') }}</span>
          <span class="caps__dim">{{ n(capabilities.targets.length) }}</span>
        </header>
        <p v-if="capabilities.rendersError" class="caps__error">
          <AlertCircle :size="12" />
          <span>{{ capabilities.rendersError }}</span>
        </p>
        <template v-else>
          <p v-if="capabilities.renders?.workflows_dir" class="caps__dim caps__dir">
            {{ t('studio.capabilities.dir', { dir: capabilities.renders.workflows_dir }) }}
          </p>
          <p v-if="rendersState === 'unconfigured'" class="caps__hint">
            {{ capabilities.renders?.note }}
          </p>
          <p v-else-if="capabilities.targets.length === 0" class="caps__hint">
            {{ t('studio.capabilities.empty') }}
          </p>
          <ul v-else class="caps__rows">
            <li v-for="target in capabilities.targets" :key="target.id" class="caps__row">
              <div class="caps__rowHead">
                <span class="caps__rowTitle">{{ target.title || target.id }}</span>
                <span v-if="!target.fileExists" class="caps__bad">
                  <TriangleAlert :size="11" />
                  <span>{{ t('studio.capabilities.fileMissing') }}</span>
                </span>
                <button
                  type="button"
                  class="caps__run"
                  :disabled="!target.fileExists"
                  :title="target.fileExists ? '' : t('studio.capabilities.fileMissing')"
                  :aria-expanded="openRun === renderKey(target.id)"
                  @click="toggleRun(renderKey(target.id))"
                >
                  <Play :size="11" />
                  <span>{{ t('studio.capabilities.run.open') }}</span>
                </button>
              </div>
              <p v-if="target.description" class="caps__desc">{{ target.description }}</p>
              <p class="caps__dim caps__mono">{{ target.file }}</p>
              <p v-if="requiredNames(target.params)" class="caps__dim">
                {{ t('studio.capabilities.required', { names: requiredNames(target.params) }) }}
              </p>

              <StudioRunForm
                v-if="openRun === renderKey(target.id)"
                :params="target.params"
                :busy="runs.isRunning(renderKey(target.id))"
                with-media
                :reference-images="target.referenceImages"
                @submit="submitRender({ targetId: target.id }, $event)"
                @cancel="toggleRun(renderKey(target.id))"
              />
              <p v-if="refusalFor(renderKey(target.id))" class="caps__error">
                <AlertCircle :size="11" />
                <span>{{ refusalFor(renderKey(target.id)) }}</span>
              </p>
              <StudioRunResult
                v-if="openRun === renderKey(target.id)"
                :outcome="runs.outcomeFor(renderKey(target.id))"
                :error="runs.errorFor(renderKey(target.id))"
              />
            </li>
          </ul>
        </template>
      </section>

      <!-- 工作流文件 -->
      <section class="caps__group">
        <header class="caps__groupHead">
          <Boxes :size="13" />
          <span class="caps__groupTitle">{{ t('studio.capabilities.group.workflows') }}</span>
          <span class="caps__dim">{{ n(capabilities.files.length) }}</span>
        </header>
        <p v-if="capabilities.workflowsError" class="caps__error">
          <AlertCircle :size="12" />
          <span>{{ capabilities.workflowsError }}</span>
        </p>
        <template v-else>
          <p v-if="capabilities.workflows?.workflowsDir" class="caps__dim caps__dir">
            {{ t('studio.capabilities.dir', { dir: capabilities.workflows.workflowsDir }) }}
          </p>
          <p v-if="workflowsState === 'unconfigured'" class="caps__hint">
            {{ capabilities.workflows?.note }}
          </p>
          <p v-else-if="capabilities.files.length === 0" class="caps__hint">
            {{ t('studio.capabilities.empty') }}
          </p>
          <ul v-else class="caps__rows">
            <li v-for="file in capabilities.files" :key="file.file" class="caps__row">
              <div class="caps__rowHead">
                <span class="caps__rowTitle caps__mono">{{ file.file }}</span>
                <span class="caps__dim">{{ formatBytes(file.bytes) }}</span>
                <button
                  type="button"
                  class="caps__run"
                  :aria-expanded="openRun === renderKey(file.file)"
                  @click="toggleRun(renderKey(file.file))"
                >
                  <Play :size="11" />
                  <span>{{ t('studio.capabilities.run.openFile') }}</span>
                </button>
              </div>
              <p class="caps__dim">
                <template v-if="file.usedBy.length > 0">
                  {{ t('studio.capabilities.usedBy', { count: n(file.usedBy.length) }) }}
                </template>
                <template v-else>{{ t('studio.capabilities.unregistered') }}</template>
                <span v-if="file.modified"> · {{ file.modified }}</span>
              </p>

              <StudioRunForm
                v-if="openRun === renderKey(file.file)"
                :params="[]"
                :busy="runs.isRunning(renderKey(file.file))"
                with-media
                reference-images
                @submit="submitFile(file.file, $event)"
                @cancel="toggleRun(renderKey(file.file))"
              />
              <p v-if="refusalFor(renderKey(file.file))" class="caps__error">
                <AlertCircle :size="11" />
                <span>{{ refusalFor(renderKey(file.file)) }}</span>
              </p>
              <StudioRunResult
                v-if="openRun === renderKey(file.file)"
                :outcome="runs.outcomeFor(renderKey(file.file))"
                :error="runs.errorFor(renderKey(file.file))"
              />
            </li>
          </ul>
        </template>
      </section>

      <!-- MCP 工具 -->
      <section class="caps__group">
        <header class="caps__groupHead">
          <Wrench :size="13" />
          <span class="caps__groupTitle">{{ t('studio.capabilities.group.tools') }}</span>
          <span class="caps__dim">{{ n(capabilities.tools.length) }}</span>
        </header>
        <p v-if="capabilities.toolsError" class="caps__error">
          <AlertCircle :size="12" />
          <span>{{ capabilities.toolsError }}</span>
        </p>
        <p v-else-if="capabilities.tools.length === 0" class="caps__hint">
          {{ t('studio.capabilities.empty') }}
        </p>
        <ul v-else class="caps__rows">
          <li v-for="tool in capabilities.tools" :key="tool.qualified_name" class="caps__row">
            <div class="caps__rowHead">
              <span class="caps__rowTitle caps__mono">{{ tool.qualified_name }}</span>
              <span class="caps__dim">
                {{ t('studio.capabilities.params', { count: n(toolParamCount(tool)) }) }}
              </span>
            </div>
            <p v-if="tool.description" class="caps__desc">{{ tool.description }}</p>
          </li>
        </ul>
      </section>
    </div>
  </section>
</template>

<style scoped>
.caps {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  height: 100%;
  overflow: auto;
}

.caps__bar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.caps__tallies {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.caps__btn {
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

.caps__btn:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.caps__btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.caps__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 8px;
  align-items: start;
}

.caps__group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg);
}

.caps__groupHead {
  display: flex;
  align-items: center;
  gap: 6px;
}

.caps__groupTitle {
  flex: 1;
  min-width: 0;
  color: var(--text);
  font-size: 12px;
}

.caps__rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.caps__row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 6px;
  border-top: 1px solid var(--studio-card-border);
}

.caps__row:first-child {
  padding-top: 0;
  border-top: 0;
}

.caps__rowHead {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.caps__rowTitle {
  flex: 1;
  min-width: 0;
  color: var(--text);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.caps__id {
  flex: none;
  color: var(--text-faint);
  font-size: 10px;
}

.caps__desc {
  margin: 0;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.caps__hint,
.caps__dim {
  margin: 0;
  color: var(--text-faint);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.caps__dir {
  font-family: 'Cascadia Mono', 'Consolas', monospace;
  font-size: 10px;
}

.caps__mono {
  font-family: 'Cascadia Mono', 'Consolas', monospace;
}

.caps__warn {
  color: var(--warning);
}

.caps__bad {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 3px;
  color: var(--warning);
  font-size: 10px;
}

.caps__run {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border: 1px solid var(--studio-card-border);
  border-radius: 5px;
  background: transparent;
  color: var(--text-faint);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.caps__run:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.caps__run[aria-expanded='true'] {
  color: var(--accent);
  border-color: var(--accent);
}

.caps__run:disabled {
  opacity: 0.4;
  cursor: default;
}

.caps__error {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin: 0;
  color: var(--danger);
  font-size: 11px;
  line-height: 1.5;
}

.is-spinning {
  animation: caps-spin 900ms linear infinite;
}

@keyframes caps-spin {
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
