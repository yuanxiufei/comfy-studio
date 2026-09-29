/**
 * Shapes and pure helpers for the rail's "who drives this turn" row and the
 * model-config form behind it.
 *
 * Three host endpoints feed it — `agent/models`, `agent/agents` and
 * `agent/settings` — and all three are documented as *deliberately lenient*: a
 * source whose `/models` call fails still comes back as a group carrying its own
 * `error`, and a missing agent directory still returns the built-ins plus an
 * explanation. The panel is expected to draw what it got, so nothing here drops
 * a group for being empty-but-broken — that would hide the only clue about why
 * the dropdown is short.
 */

/** Joins source and model name into the ref `agent/model` expects. Mirrors
 *  `settings.py::SOURCE_SEPARATOR`; the host splits on it, so it is a wire
 *  constant rather than a display choice. */
export const SOURCE_SEPARATOR = '::'

/** Source key of the primary source (the environment-variable one). A model on
 *  the primary source is written `default::<name>`. */
export const DEFAULT_SOURCE = 'default'

/** One `<optgroup>` of `agent/models`: the models one configured source offers. */
export interface ModelGroup {
  source: string
  /** Human name of the source; the host falls back to the key when unnamed. */
  label: string
  models: string[]
  /** `endpoint` when the list came from `GET /models`, `config` when the source
   *  itself is broken — which is why `error` is set. */
  origin: string
  error: string | null
}

/** `agent/models`. The top-level `models` / `source` / `error` describe the
 *  *primary* group and are kept by the host for older panels; `groups` is what
 *  this panel reads, because it is the only field that says which source each
 *  model belongs to. */
export interface AgentModelsPayload {
  current: string | null
  current_source: string
  models: string[]
  source: string
  error: string | null
  groups: ModelGroup[]
  extra_error: string | null
}

/** `agent/model` — read and write share one shape; `changed` tells them apart. */
export interface AgentModelPayload {
  model: string
  source: string
  changed: boolean
  /** Sessions re-pointed at the new model. */
  applied: string[]
  /** Sessions skipped because a turn is in flight — re-pointing the HTTP client
   *  mid-turn would cut the request in half. */
  skipped: string[]
}

/** One agent profile in `agent/agents`. No `prompt`: the host deliberately
 *  leaves the persona text out (see `_agent_json`). */
export interface AgentRow {
  id: string
  name: string
  summary: string
  builtin: boolean
  file: string
}

/** A profile file that exists but could not be read. */
export interface AgentProblem {
  file: string
  error: string
}

/** `agent/agents`. */
export interface AgentAgentsPayload {
  current: string
  /** Set when the selected id is no longer on disk: the dropdown would otherwise
   *  silently show someone else as selected. */
  missing: string | null
  agents: AgentRow[]
  problems: AgentProblem[]
  error: string | null
  dir: string | null
}

/** `agent/agent` — read and write share one shape. */
export interface AgentPayload {
  agent: string
  changed: boolean
  name: string
  error: string | null
}

/** The `settings.json` contents as the host reports them: the key is a boolean,
 *  never the value — a stored secret must not travel back to the renderer. */
export interface SettingsSavedSource {
  name: string
  base_url: string
  model: string
  has_key: boolean
}

export interface SettingsSaved {
  model: string
  base_url: string
  has_key: boolean
  extra_sources: SettingsSavedSource[]
}

/**
 * The `saved` field of `agent/settings`, which is **two types depending on the
 * verb**: a read fills it with the file's contents (or null when there is no
 * file yet), while a write overwrites the same key with the boolean `true`
 * (`_settings_status()` then `result.update({"saved": True, ...})`).
 *
 * Modelled rather than papered over: reaching for `saved.model` after a save is
 * a real crash waiting to happen, and the effective `model` / `base_url` at the
 * top level carry the same information on both paths.
 */
export type SettingsSavedField = SettingsSaved | true | null

/** `agent/settings`. */
export interface AgentSettingsPayload {
  /** Null when the host has no settings store at all: then this panel can only
   *  explain, not repair. */
  path: string | null
  exists: boolean
  saved: SettingsSavedField
  /** Keys whose *value* came from the file (and were injected into the env). */
  from_file: string[]
  /** Keys the environment supplies on its own — editing those here is a no-op,
   *  which the panel has to say out loud. */
  from_env: string[]
  /** The file's own problem. Separate from `error`: deleting the file fixes it. */
  file_error: string | null
  configured: boolean
  model: string | null
  base_url: string | null
  /** Why no session could be built from this config (usually a missing model). */
  error: string | null
  /** Present only on a write. */
  applied?: string[]
  /** Sessions skipped on a write because a turn is running. */
  skipped?: string[]
}

/** What the model form submits, before `settingsRequest` shapes it. */
export interface SettingsForm {
  model: string
  baseUrl: string
  apiKey: string
  /** The "clear the key" button: sends an empty string, which the host reads as
   *  "drop this setting" rather than "leave it". */
  clearKey: boolean
}

/** The three keys the form writes, spelled exactly as the host expects. */
const MODEL_KEY = 'COMFY_STUDIO_LLM_MODEL'
const BASE_URL_KEY = 'COMFY_STUDIO_LLM_BASE_URL'
const API_KEY = 'COMFY_STUDIO_LLM_API_KEY'

/** `default::qwen2.5:7b` — the ref the host parses back into source + name. */
export function modelRef(source: string, name: string): string {
  return `${source || DEFAULT_SOURCE}${SOURCE_SEPARATOR}${name}`
}

/**
 * The inverse of `modelRef`, for a ref the host handed back.
 *
 * A ref without a separator is an error — `agent/model` rejects it — so the
 * caller gets the whole string as the name with the primary source assumed,
 * which is how a bare model name from an older host stays selectable.
 */
export function splitModelRef(ref: string): { source: string; name: string } {
  const at = ref.indexOf(SOURCE_SEPARATOR)
  if (at < 0) return { source: DEFAULT_SOURCE, name: ref }
  return { source: ref.slice(0, at) || DEFAULT_SOURCE, name: ref.slice(at + SOURCE_SEPARATOR.length) }
}

/** The ref of the model currently in effect, or null when the host has none. */
export function currentRef(payload: AgentModelsPayload | null): string | null {
  if (!payload || !payload.current) return null
  return modelRef(payload.current_source, payload.current)
}

/**
 * Groups worth drawing: those with models, plus those whose failure is the
 * reason the dropdown looks short. A group that is empty *and* healthy is the
 * one case that earns nothing on screen.
 */
export function pickableGroups(payload: AgentModelsPayload | null): ModelGroup[] {
  if (!payload) return []
  return payload.groups.filter((group) => group.models.length > 0 || Boolean(group.error))
}

/** Flat list of every model ref the dropdown offers, in host order. */
export function selectableRefs(payload: AgentModelsPayload | null): string[] {
  return pickableGroups(payload).flatMap((group) =>
    group.models.map((name) => modelRef(group.source, name))
  )
}

/**
 * Which ref the dropdown should show as selected.
 *
 * The host injects the current model into its group even when `/models` does not
 * list it ("just deleted alias" case), so an exact match is normally there. The
 * fallback is the first selectable ref rather than empty: a `<select>` with no
 * matching option still shows its first entry, and pretending nothing is
 * selected is how the panel looks like it silently changed the model.
 */
export function selectedRef(payload: AgentModelsPayload | null): string | null {
  const wanted = currentRef(payload)
  const refs = selectableRefs(payload)
  if (wanted && refs.includes(wanted)) return wanted
  // Not in any group (or no groups at all): keep the host's value so the `<select>`
  // can carry a synthetic option instead of jumping to an unrelated model.
  return wanted ?? refs[0] ?? null
}

/** The saved `settings.json` block, when the host actually sent one. A write
 *  replaces it with `true`, so this is the only honest way to read it. */
export function savedSettings(payload: AgentSettingsPayload | null): SettingsSaved | null {
  const saved = payload?.saved
  if (!saved || typeof saved !== 'object') return null
  return saved
}

/**
 * What the form's two text fields start with.
 *
 * The effective values win over the file's: after `SettingsStore.apply_to_env`,
 * an environment variable overrides the file, so pre-filling from `saved` alone
 * would show a model that is not the one in use. The key is never pre-filled —
 * the host only ever reports `has_key`.
 */
export function prefillSettings(payload: AgentSettingsPayload | null): { model: string; baseUrl: string } {
  const saved = savedSettings(payload)
  const model = payload?.model ?? ''
  const baseUrl = payload?.base_url ?? ''
  return {
    model: model || saved?.model || '',
    baseUrl: baseUrl || saved?.base_url || ''
  }
}

/**
 * The write payload for `agent/settings`.
 *
 * Model and address always travel (trimmed) — an empty string is the host's own
 * "clear this and fall back to the environment" and there is no other way to say
 * it. The key is the delicate one: it is never pre-filled, so an empty field
 * means "leave the stored key alone", and only the explicit clear button sends
 * the empty string that deletes it.
 */
export function settingsRequest(form: SettingsForm): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    [MODEL_KEY]: form.model.trim(),
    [BASE_URL_KEY]: form.baseUrl.trim()
  }
  const key = form.apiKey.trim()
  if (form.clearKey || key) payload[API_KEY] = form.clearKey ? '' : key
  return payload
}

/** Whether the form has anything to write — the host would reject `{}` by
 *  answering with a plain read, so the button stays disabled instead. */
export function settingsDirty(form: SettingsForm): boolean {
  return Boolean(
    form.model.trim() || form.baseUrl.trim() || form.apiKey.trim() || form.clearKey
  )
}
