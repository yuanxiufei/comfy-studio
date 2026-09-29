/**
 * Who drives the conversation: the model, the agent profile, and the model
 * configuration all three depend on.
 *
 * The three endpoints are loaded together but kept apart, for the same reason
 * the capability page keeps its four groups apart: `agent/models` reaches the
 * model server, `agent/agents` scans a directory, `agent/settings` reads a file.
 * A model server that is down must not blank the agent dropdown — and the
 * settings form is precisely where a user goes to fix a down model server, so
 * sharing one `error` would take away the repair.
 *
 * Switching writes through to the host immediately (both endpoints are
 * host-level defaults that also re-point idle sessions), so the store's job
 * after a switch is only to keep the local snapshot honest — see `selectModel`.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  currentRef,
  prefillSettings,
  pickableGroups,
  settingsDirty,
  settingsRequest,
  splitModelRef,
  type AgentAgentsPayload,
  type AgentModelPayload,
  type AgentModelsPayload,
  type AgentPayload,
  type AgentSettingsPayload,
  type SettingsForm
} from '../studio/pages/agentSetup'
import { callStudio } from '../studio/pages/rpc'

export const useAgentSetupStore = defineStore('studioAgentSetup', () => {
  const models = ref<AgentModelsPayload | null>(null)
  const agents = ref<AgentAgentsPayload | null>(null)
  const settings = ref<AgentSettingsPayload | null>(null)

  const modelsError = ref<string | null>(null)
  const agentsError = ref<string | null>(null)
  const settingsError = ref<string | null>(null)

  const loading = ref(false)
  const loaded = ref(false)
  /** A model / agent switch is in flight. */
  const switching = ref(false)
  /** The settings form is being written. */
  const saving = ref(false)
  /** Outcome of the last switch or save, for the row's single status line. */
  const notice = ref<string | null>(null)
  /** Sessions the host did re-point after a switch. */
  const applied = ref<string[]>([])
  /** Sessions the host could not re-point because a turn was in flight. */
  const skipped = ref<string[]>([])

  const groups = computed(() => pickableGroups(models.value))
  const activeRef = computed(() => currentRef(models.value))
  /** Groups that answered with an error: the dropdown is short because of them. */
  const brokenGroups = computed(() => groups.value.filter((group) => group.error))
  const agentRows = computed(() => agents.value?.agents ?? [])
  const agentProblems = computed(() => agents.value?.problems ?? [])
  const agentMissing = computed(() => agents.value?.missing ?? null)

  async function loadModels(): Promise<void> {
    const outcome = await callStudio<AgentModelsPayload>('agent/models')
    if (!outcome.ok || !outcome.value) {
      modelsError.value = outcome.error
      models.value = null
      return
    }
    modelsError.value = null
    models.value = outcome.value
  }

  async function loadAgents(): Promise<void> {
    const outcome = await callStudio<AgentAgentsPayload>('agent/agents')
    if (!outcome.ok || !outcome.value) {
      agentsError.value = outcome.error
      agents.value = null
      return
    }
    agentsError.value = null
    agents.value = outcome.value
  }

  async function loadSettings(): Promise<void> {
    const outcome = await callStudio<AgentSettingsPayload>('agent/settings')
    if (!outcome.ok || !outcome.value) {
      settingsError.value = outcome.error
      settings.value = null
      return
    }
    settingsError.value = null
    settings.value = outcome.value
  }

  /** Load all three. In parallel: they share no state and the model listing is
   *  the slow one (it asks every source's `/models`). */
  async function refresh(): Promise<void> {
    loading.value = true
    await Promise.all([loadModels(), loadAgents(), loadSettings()])
    loading.value = false
    loaded.value = true
  }

  /**
   * Switch the model and re-point the local snapshot.
   *
   * The host answers with the *bare* name and the source key, not the ref that
   * went in, so the snapshot is patched from those two fields rather than from
   * the request — and the new model is not always in `groups` (that list is
   * whatever the servers last reported), which is exactly the case
   * `selectedRef` keeps selectable.
   */
  async function selectModel(ref: string): Promise<boolean> {
    if (!ref) return false
    switching.value = true
    try {
      const outcome = await callStudio<AgentModelPayload>('agent/model', { model: ref })
      if (!outcome.ok || !outcome.value) {
        notice.value = outcome.error
        return false
      }
      const payload = outcome.value
      const { source, name } = splitModelRef(ref)
      const snapshot = models.value
      models.value = snapshot
        ? {
            ...snapshot,
            current: payload.model || name,
            current_source: payload.source || source
          }
        : snapshot
      notice.value = null
      skipped.value = payload.skipped
      applied.value = payload.applied
      return true
    } finally {
      switching.value = false
    }
  }

  /** Switch the agent profile. Takes effect on the *next* turn — a running turn
   *  already computed its prompt, and the host documents it that way. */
  async function selectAgent(id: string): Promise<boolean> {
    if (!id) return false
    switching.value = true
    try {
      const outcome = await callStudio<AgentPayload>('agent/agent', { agent: id })
      if (!outcome.ok || !outcome.value) {
        notice.value = outcome.error
        return false
      }
      const payload = outcome.value
      if (agents.value) agents.value = { ...agents.value, current: payload.agent, missing: null }
      notice.value = null
      return true
    } finally {
      switching.value = false
    }
  }

  /**
   * Write the model config.
   *
   * The response is re-read from `model` / `base_url` / `configured` rather than
   * from `saved`: on a write the host replaces that key with the boolean `true`,
   * so the object is simply not there any more (see `SettingsSavedField`).
   */
  async function saveSettings(form: SettingsForm): Promise<boolean> {
    if (!settingsDirty(form)) return false
    saving.value = true
    try {
      const outcome = await callStudio<AgentSettingsPayload>(
        'agent/settings',
        settingsRequest(form)
      )
      if (!outcome.ok || !outcome.value) {
        notice.value = outcome.error
        return false
      }
      settings.value = outcome.value
      settingsError.value = null
      skipped.value = outcome.value.skipped ?? []
      applied.value = outcome.value.applied ?? []
      notice.value = null
      // The model list is the thing that changes when the address or key moves.
      await loadModels()
      return true
    } finally {
      saving.value = false
    }
  }

  /** What the form's text fields start with, re-derived from the live snapshot. */
  const formSeed = computed(() => prefillSettings(settings.value))

  function reset(): void {
    models.value = null
    agents.value = null
    settings.value = null
    modelsError.value = null
    agentsError.value = null
    settingsError.value = null
    loading.value = false
    loaded.value = false
    switching.value = false
    saving.value = false
    notice.value = null
    skipped.value = []
    applied.value = []
  }

  return {
    models,
    agents,
    settings,
    modelsError,
    agentsError,
    settingsError,
    loading,
    loaded,
    switching,
    saving,
    notice,
    skipped,
    applied,
    groups,
    activeRef,
    brokenGroups,
    agentRows,
    agentProblems,
    agentMissing,
    formSeed,
    loadModels,
    loadAgents,
    loadSettings,
    refresh,
    selectModel,
    selectAgent,
    saveSettings,
    reset
  }
})
