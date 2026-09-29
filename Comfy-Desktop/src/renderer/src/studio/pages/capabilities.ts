/**
 * Shapes and pure helpers for the capability page.
 *
 * Four host namespaces answer "what can this machine do": `skills/list`,
 * `renders/list`, `workflows/list` and `mcp/tools`. They are independent calls
 * (each one talks to the engine or the MCP hub on its own), so the page must
 * survive any one of them failing — see `capabilitiesStore`.
 *
 * Field names mirror the host *exactly*, including the one place it is
 * inconsistent: `renders/list` returns `workflows_dir` while `workflows/list`
 * returns `workflowsDir`, because each wrapper passes through what its catalog
 * happens to call the field. Renaming either one here would make the payload
 * look tidier and the type wrong.
 */

/** One `skills/list` parameter. `default` is null both when the default *is*
 *  null and when there is none — `hasDefault` is what separates them. */
export interface SkillParam {
  name: string
  type: string
  required: boolean
  description: string
  default: unknown
  hasDefault: boolean
}

export interface SkillEntry {
  id: string
  title: string
  description: string
  tags: string[]
  params: SkillParam[]
}

/** `skills/list`. */
export interface SkillsPayload {
  skills: SkillEntry[]
}

/** One entry of `renders/list` — a registered production workflow. */
export interface RenderTarget {
  id: string
  title: string
  description: string
  /** Workflow filename inside the engine's workflows directory. */
  file: string
  tags: string[]
  params: SkillParam[]
  /** False when the file it names is gone: listed, but not runnable. */
  fileExists: boolean
  referenceImages: boolean
}

/** `renders/list`. `workflows_dir` / `note` are how "not configured" is said
 *  out loud, so they are part of the payload rather than an error. */
export interface RendersPayload {
  workflows_dir: string | null
  note: string | null
  targets: RenderTarget[]
}

/** One entry of `workflows/list` — any image in the directory, registered or not. */
export interface WorkflowFile {
  file: string
  bytes: number
  modified: string
  digest: string
  /** Render target ids this image backs; empty means it is unregistered but
   *  still runnable by filename. */
  usedBy: string[]
}

/** `workflows/list`. Note the camelCase directory field — see the file header. */
export interface WorkflowsPayload {
  workflowsDir: string | null
  note: string | null
  files: WorkflowFile[]
}

/** One tool the MCP hub offers, under its `<server>__<tool>` name. */
export interface McpTool {
  server: string
  name: string
  qualified_name: string
  description: string
  /** Raw JSON Schema from the server. Kept as `unknown`: the host does not
   *  reshape it, and neither does the page beyond counting properties. */
  input_schema: unknown
}

/** `mcp/tools`. */
export interface McpToolsPayload {
  tools: McpTool[]
}

export type CapabilityGroupId = 'skills' | 'renders' | 'workflows' | 'tools'

/**
 * Whether a group has nothing because this machine lacks the directory, or
 * because the directory is simply empty.
 *
 * The host only sets `note` when the directory is not there (`renders` /
 * `workflows` catalogs both document it that way), so the two cases are told
 * apart by the note alone. They need different words: "the engine isn't wired up
 * yet" is something the user fixes, "you have no skills" is not, and showing the
 * second when the first is true sends them looking in the wrong place.
 */
export type CapabilityGroupState = 'ready' | 'empty' | 'unconfigured'

export function groupState(note: string | null | undefined, count: number): CapabilityGroupState {
  if (count > 0) return 'ready'
  return note ? 'unconfigured' : 'empty'
}

/** The required parameters of a skill or a render target, in the host's order.
 *
 * Shared by both lists on purpose: they are the same `SkillParam` shape, and
 * "which of these do I have to supply" is the question a user asks of either.
 */
export function requiredParams(params: readonly SkillParam[]): SkillParam[] {
  return params.filter((param) => param.required)
}

/**
 * How many properties a tool's JSON Schema declares.
 *
 * Defensive rather than tidy: `input_schema` arrives from a third-party MCP
 * server, and `null`, `[]` and `{"properties": "nope"}` are all things a server
 * can actually return. Reading `.properties` straight through would throw during
 * render, which blanks the whole page over one bad server.
 */
export function toolParamCount(tool: McpTool): number {
  const schema = tool.input_schema
  if (typeof schema !== 'object' || schema === null) return 0
  const properties = (schema as { properties?: unknown }).properties
  if (typeof properties !== 'object' || properties === null || Array.isArray(properties)) return 0
  return Object.keys(properties).length
}

export interface CapabilityTallies {
  skills: number
  targets: number
  workflows: number
  tools: number
  /** Every row the page will render, across the four groups. */
  total: number
}

/** The header's counts, computed once so the summary and the groups can't
 *  disagree — the same reason `shelfTallies` exists on the artifact page. */
export function capabilityTallies(input: {
  skills: readonly SkillEntry[]
  targets: readonly RenderTarget[]
  workflows: readonly WorkflowFile[]
  tools: readonly McpTool[]
}): CapabilityTallies {
  const skills = input.skills.length
  const targets = input.targets.length
  const workflows = input.workflows.length
  const tools = input.tools.length
  return { skills, targets, workflows, tools, total: skills + targets + workflows + tools }
}
