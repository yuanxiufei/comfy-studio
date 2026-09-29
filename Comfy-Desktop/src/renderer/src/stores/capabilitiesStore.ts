/**
 * What this machine can do, driven by `skills/list`, `renders/list`,
 * `workflows/list` and `mcp/tools`.
 *
 * The four calls are independent — one reads the skill catalog, one the render
 * catalog, one the workflows directory, one the MCP hub — and they fail
 * independently too. So each group keeps *its own* error: an unconfigured engine
 * should cost the page one group's worth of content, not the other three.
 * Folding them into a single `error` is how a page ends up saying "加载失败" while
 * three of its four lists are sitting there ready to render.
 *
 * The store holds no derived state: the tallies live in `capabilities.ts`, where
 * they can be tested without a host.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type {
  CapabilityGroupId,
  McpTool,
  McpToolsPayload,
  RenderTarget,
  RendersPayload,
  SkillEntry,
  SkillsPayload,
  WorkflowFile,
  WorkflowsPayload
} from '../studio/pages/capabilities'
import { callStudio } from '../studio/pages/rpc'

export const useCapabilitiesStore = defineStore('studioCapabilities', () => {
  // ---- skills ----
  const skills = ref<SkillEntry[]>([])
  const skillsError = ref<string | null>(null)

  // ---- render targets ----
  const renders = ref<RendersPayload | null>(null)
  const rendersError = ref<string | null>(null)

  // ---- workflow images ----
  const workflows = ref<WorkflowsPayload | null>(null)
  const workflowsError = ref<string | null>(null)

  // ---- MCP tools ----
  const tools = ref<McpTool[]>([])
  const toolsError = ref<string | null>(null)

  const loading = ref(false)
  const loaded = ref(false)

  const targets = computed<RenderTarget[]>(() => renders.value?.targets ?? [])
  const files = computed<WorkflowFile[]>(() => workflows.value?.files ?? [])

  /** How many of the four groups came back clean — the header's honesty check. */
  const failedGroups = computed(() => {
    let count = 0
    for (const message of groupErrors.value) if (message) count += 1
    return count
  })

  const groupErrors = computed<(string | null)[]>(() => [
    skillsError.value,
    rendersError.value,
    workflowsError.value,
    toolsError.value
  ])

  function errorFor(group: CapabilityGroupId): string | null {
    if (group === 'skills') return skillsError.value
    if (group === 'renders') return rendersError.value
    if (group === 'workflows') return workflowsError.value
    return toolsError.value
  }

  async function loadSkills(): Promise<void> {
    const outcome = await callStudio<SkillsPayload>('skills/list')
    if (!outcome.ok || !outcome.value) {
      skillsError.value = outcome.error
      skills.value = []
      return
    }
    skillsError.value = null
    skills.value = outcome.value.skills
  }

  async function loadRenders(): Promise<void> {
    const outcome = await callStudio<RendersPayload>('renders/list')
    if (!outcome.ok || !outcome.value) {
      rendersError.value = outcome.error
      renders.value = null
      return
    }
    rendersError.value = null
    renders.value = outcome.value
  }

  async function loadWorkflows(): Promise<void> {
    const outcome = await callStudio<WorkflowsPayload>('workflows/list')
    if (!outcome.ok || !outcome.value) {
      workflowsError.value = outcome.error
      workflows.value = null
      return
    }
    workflowsError.value = null
    workflows.value = outcome.value
  }

  async function loadTools(): Promise<void> {
    const outcome = await callStudio<McpToolsPayload>('mcp/tools')
    if (!outcome.ok || !outcome.value) {
      toolsError.value = outcome.error
      tools.value = []
      return
    }
    toolsError.value = null
    tools.value = outcome.value.tools
  }

  /** Reload all four. In parallel: they share no state, and the slowest is the
   *  engine round-trip, so serialising them would just add three waits. */
  async function refresh(): Promise<void> {
    loading.value = true
    await Promise.all([loadSkills(), loadRenders(), loadWorkflows(), loadTools()])
    loading.value = false
    loaded.value = true
  }

  function reset(): void {
    skills.value = []
    skillsError.value = null
    renders.value = null
    rendersError.value = null
    workflows.value = null
    workflowsError.value = null
    tools.value = []
    toolsError.value = null
    loading.value = false
    loaded.value = false
  }

  return {
    skills,
    skillsError,
    renders,
    rendersError,
    workflows,
    workflowsError,
    tools,
    toolsError,
    loading,
    loaded,
    targets,
    files,
    failedGroups,
    errorFor,
    loadSkills,
    loadRenders,
    loadWorkflows,
    loadTools,
    refresh,
    reset
  }
})
