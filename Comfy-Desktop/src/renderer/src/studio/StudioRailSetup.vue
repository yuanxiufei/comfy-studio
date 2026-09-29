<script setup lang="ts">
/**
 * Who drives this turn: the agent profile, the model, and the model config
 * behind a gear.
 *
 * This row exists because the rail could previously start a conversation but
 * never say *who* was answering in it — the model and the agent were whatever
 * the host had defaulted to, and the only way to change either was the old
 * injected drawer. Both pickers write straight through on change: these are
 * host-level defaults that also re-point idle sessions, so there is no "apply"
 * step to get wrong.
 *
 * Everything the host reports as a *problem* is drawn as a line under the row
 * rather than as a disabled control, because the fixes differ: a broken source
 * is fixed in the config behind the gear, a missing agent is fixed on disk, and
 * a skipped session just needs the turn to end. The one exception is the model
 * dropdown with nothing in it, which has to disable itself.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertCircle, LoaderCircle, RefreshCw, Settings2 } from 'lucide-vue-next'
import { useAgentSetupStore } from '../stores/agentSetupStore'
import { selectableRefs, selectedRef, splitModelRef } from './pages/agentSetup'
import StudioModelSettings from './StudioModelSettings.vue'

const setup = useAgentSetupStore()
const { t, n } = useI18n()

const configOpen = ref(false)

onMounted(() => {
  if (!setup.loaded) void setup.refresh()
})

/**
 * The refs the dropdown offers, plus the current one when it is in no group.
 *
 * That case is real: the host injects the active model into its group, but a
 * model deleted from a source, or a source whose `/models` call failed, leaves
 * the active ref unlisted. Dropping it would make a `<select>` silently show a
 * *different* model as selected — the one thing this row must never do.
 */
const refs = computed(() => {
  const list = selectableRefs(setup.models)
  const active = setup.activeRef
  if (active && !list.includes(active)) return [active, ...list]
  return list
})

const active = computed(() => selectedRef(setup.models))
/** Bare name of the model in effect, for tooltips where the `source::` prefix
 *  is noise. */
const activeName = computed(() => {
  const ref_ = setup.activeRef
  return ref_ ? splitModelRef(ref_).name : ''
})

/**
 * The active ref when no `<optgroup>` lists it — a model deleted from its
 * source, or a source whose listing failed. `selectedRef` keeps it selectable
 * so the dropdown cannot silently show a different model, and this is the extra
 * option that makes that possible.
 */
const orphanRef = computed(() => {
  if (!active.value) return null
  const { source, name } = splitModelRef(active.value)
  const listed = setup.groups.some(
    (group) => group.source === source && group.models.includes(name)
  )
  return listed ? null : active.value
})

async function onModelPick(event: Event): Promise<void> {
  const value = (event.target as HTMLSelectElement).value
  if (!value || value === active.value) return
  await setup.selectModel(value)
}

async function onAgentPick(event: Event): Promise<void> {
  const value = (event.target as HTMLSelectElement).value
  if (!value || value === setup.agents?.current) return
  await setup.selectAgent(value)
}
</script>

<template>
  <div class="setup">
    <div class="setup__row">
      <select
        class="setup__pick"
        :value="setup.agents?.current ?? ''"
        :title="t('studio.setup.agent')"
        :aria-label="t('studio.setup.agent')"
        :disabled="setup.switching || setup.agentRows.length === 0"
        @change="onAgentPick"
      >
        <option v-if="!setup.agents" value="">{{ t('studio.setup.agentUnknown') }}</option>
        <option
          v-else-if="!setup.agentRows.some((row) => row.id === setup.agents?.current)"
          :value="setup.agents?.current ?? ''"
        >
          {{ setup.agents?.missing ?? setup.agents?.current }}
        </option>
        <option v-for="row in setup.agentRows" :key="row.id" :value="row.id">
          {{ row.name || row.id }}
        </option>
      </select>

      <select
        class="setup__pick setup__pick--model"
        :value="active ?? ''"
        :title="activeName || t('studio.setup.model')"
        :aria-label="t('studio.setup.model')"
        :disabled="setup.switching || refs.length === 0"
        @change="onModelPick"
      >
        <option v-if="!setup.models" value="">{{ t('studio.setup.modelUnknown') }}</option>
        <option v-else-if="refs.length === 0" value="">{{ t('studio.setup.emptyModels') }}</option>
        <optgroup
          v-for="group in setup.groups"
          :key="group.source"
          :label="group.error ? `${group.label} · ${t('studio.setup.sourceFailed')}` : group.label"
        >
          <option v-for="name in group.models" :key="`${group.source}::${name}`" :value="`${group.source}::${name}`">
            {{ name }}
          </option>
        </optgroup>
        <!-- The active model when no group lists it: without this option a
             `<select>` would fall back to its first entry and claim a different
             model is in effect. -->
        <option v-if="orphanRef" :value="orphanRef">{{ activeName }}</option>
      </select>

      <button
        type="button"
        class="setup__gear"
        :class="{ 'is-active': configOpen }"
        :title="t('studio.setup.config')"
        @click="configOpen = !configOpen"
      >
        <Settings2 :size="13" />
      </button>
      <button
        type="button"
        class="setup__gear"
        :title="t('studio.setup.reload')"
        :disabled="setup.loading"
        @click="setup.refresh()"
      >
        <LoaderCircle v-if="setup.loading" :size="13" class="is-spinning" />
        <RefreshCw v-else :size="13" />
      </button>
    </div>

    <p v-if="setup.modelsError" class="setup__note setup__note--bad">
      <AlertCircle :size="11" />
      <span>{{ setup.modelsError }}</span>
    </p>
    <p v-if="setup.brokenGroups.length > 0" class="setup__note setup__note--bad">
      <AlertCircle :size="11" />
      <span>
        {{ t('studio.setup.brokenSources', { count: n(setup.brokenGroups.length) }) }} ·
        {{ setup.brokenGroups.map((group) => group.label).join(' · ') }}
      </span>
    </p>
    <p v-if="setup.models?.extra_error" class="setup__note setup__note--bad">
      <AlertCircle :size="11" />
      <span>{{ t('studio.setup.extraError') }} · {{ setup.models.extra_error }}</span>
    </p>

    <p v-if="setup.agentsError" class="setup__note setup__note--bad">
      <AlertCircle :size="11" />
      <span>{{ setup.agentsError }}</span>
    </p>
    <p v-if="setup.agentMissing" class="setup__note setup__note--bad">
      <AlertCircle :size="11" />
      <span>{{ t('studio.setup.agentMissing', { id: setup.agentMissing }) }}</span>
    </p>
    <p v-if="setup.agentProblems.length > 0" class="setup__note setup__note--bad">
      <AlertCircle :size="11" />
      <span>
        {{ t('studio.setup.agentProblems', { count: n(setup.agentProblems.length) }) }} ·
        {{ setup.agentProblems.map((problem) => problem.file).join(' · ') }}
      </span>
    </p>

    <p v-if="setup.notice" class="setup__note setup__note--bad">
      <AlertCircle :size="11" />
      <span>{{ setup.notice }}</span>
    </p>
    <p v-if="setup.applied.length > 0" class="setup__note">
      {{ t('studio.setup.applied', { count: n(setup.applied.length) }) }}
    </p>
    <p v-if="setup.skipped.length > 0" class="setup__note setup__note--warn">
      {{ t('studio.setup.skipped', { count: n(setup.skipped.length) }) }}
    </p>

    <StudioModelSettings v-if="configOpen" @close="configOpen = false" />
  </div>
</template>

<style scoped>
.setup {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--studio-card-border);
}

.setup__row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.setup__pick {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 40%;
  padding: 3px 5px;
  border: 1px solid var(--studio-card-border);
  border-radius: 5px;
  background: var(--studio-card-bg);
  color: var(--text-muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.setup__pick--model {
  flex: 1 1 auto;
  max-width: none;
}

.setup__pick:disabled {
  opacity: 0.5;
  cursor: default;
}

.setup__gear {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  padding: 3px 5px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
}

.setup__gear:hover:not(:disabled),
.setup__gear.is-active {
  color: var(--text);
  border-color: var(--studio-card-border);
}

.setup__gear:disabled {
  opacity: 0.5;
  cursor: default;
}

.setup__note {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin: 0;
  color: var(--text-faint);
  font-size: 10px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.setup__note--bad {
  color: var(--danger);
}

.setup__note--warn {
  color: var(--warning);
}

.is-spinning {
  animation: setup-spin 900ms linear infinite;
}

@keyframes setup-spin {
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
