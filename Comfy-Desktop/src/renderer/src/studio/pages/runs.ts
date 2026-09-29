/**
 * Shapes and pure helpers for "run it once": the parameter forms over
 * `skills/run` and `renders/run`, and the result they hand back.
 *
 * The host is explicit about where validation lives — `server.py` says it only
 * checks *shapes* here and that "必填给了没" belongs to the engine's assemble
 * phase. So the form's job is not to re-implement the engine's rules; it is to
 * (a) pre-fill what the catalog already declares, (b) turn the typed text into
 * the JSON types the parameter declares, and (c) refuse to send a request that
 * is *known* to be incomplete, because the alternative is a round trip that ends
 * in an engine error the user cannot act on.
 *
 * The one rule deliberately not invented here: a blank optional field is
 * **omitted** rather than sent empty, so the engine applies its own default. The
 * old drawer could only ever send the catalog's defaults; this can send nothing
 * and let the engine decide.
 */
import type { SkillParam } from './capabilities'

/** `skills/run`. `isError` is the *tool's* failure (out of VRAM, bad model
 *  name); protocol failures are thrown by the host as RPC errors. */
export interface SkillRunPayload {
  skill_id: string
  isError: boolean
  text: string
  data: unknown
}

/** `renders/run`. `file` is the workflow filename when the run was started by
 *  filename; a registered target answers with `workflow:<file>` in `target_id`
 *  and null here. */
export interface RenderRunPayload {
  target_id: string
  file: string | null
  isError: boolean
  text: string
  data: unknown
}

/** The families the engine labels artefacts with (`outputs.guess_kind`). */
export type RunMediaKind = 'image' | 'video' | 'audio' | 'other'

/** One produced artefact. */
export interface RunMedia {
  /** A `/view?...` URL on the engine's own server, ready to put in an `<img>`. */
  url: string
  filename: string
  /** Which node wrote it — the only clue when the file itself is wrong. */
  node: string
  subfolder: string
  kind: RunMediaKind
}

/** A finished run, normalised across the two endpoints. */
export interface RunOutcome {
  isError: boolean
  text: string
  media: RunMedia[]
  /** `data.notes`: what the engine's assemble phase changed (duration rounded to
   *  whole frames, an external node wired in). Worth showing — a render that
   *  ignored the requested length looks like a bug otherwise. */
  notes: string[]
  /** `data.saved`: extra paths the engine wrote. */
  saved: string[]
}

/** The form's raw text values, keyed by parameter name. */
export type RunFormValues = Record<string, string>

/** Which control a parameter gets. `integer` / `float` are the engine's own
 *  spellings and mean the same thing to us as `number`. */
export type ParamKind = 'number' | 'boolean' | 'text'

export function paramKind(type: string): ParamKind {
  const normalized = type.trim().toLowerCase()
  if (normalized === 'number' || normalized === 'integer' || normalized === 'int' || normalized === 'float') {
    return 'number'
  }
  if (normalized === 'boolean' || normalized === 'bool') return 'boolean'
  return 'text'
}

/** One parameter's text for the form, from its declared default. */
function defaultValue(param: SkillParam): string {
  if (!param.hasDefault) return ''
  const value = param.default
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  // Objects and arrays have no text field to live in; the engine gets its own
  // default back by omission, which is the same thing it would have applied.
  return ''
}

/** Initial form values: the catalog's defaults, so "跑一遍" works without
 *  touching anything for every skill that declares them. */
export function prefillParams(params: readonly SkillParam[]): RunFormValues {
  const values: RunFormValues = {}
  for (const param of params) {
    const text = defaultValue(param)
    if (text) values[param.name] = text
  }
  return values
}

export interface CollectedParams {
  values: Record<string, unknown>
  /** Required, blank, and with no declared default — the request would fail. */
  missing: string[]
  /** Typed as a number but not a number. Refused locally so the user gets a
   *  sentence instead of an engine stack trace. */
  invalid: string[]
}

/**
 * Turn the form's text into the request's `params`.
 *
 * Blank → omitted in every case (see the file header). A required parameter with
 * no declared default is the only blank that blocks the request: for one *with*
 * a default, blank is a legitimate way to say "use yours".
 */
export function collectParams(params: readonly SkillParam[], values: RunFormValues): CollectedParams {
  const collected: Record<string, unknown> = {}
  const missing: string[] = []
  const invalid: string[] = []

  for (const param of params) {
    const raw = (values[param.name] ?? '').trim()
    if (!raw) {
      if (param.required && !param.hasDefault) missing.push(param.name)
      continue
    }
    const kind = paramKind(param.type)
    if (kind === 'number') {
      const parsed = Number(raw)
      if (!Number.isFinite(parsed)) {
        invalid.push(param.name)
        continue
      }
      collected[param.name] = parsed
      continue
    }
    if (kind === 'boolean') {
      collected[param.name] = raw.toLowerCase() === 'true' || raw === '1'
      continue
    }
    collected[param.name] = raw
  }

  return { values: collected, missing, invalid }
}

/** `images` for `renders/run`: one path per line, or separated by `;`. */
export function splitImagePaths(text: string): string[] {
  return text
    .split(/[\n;]/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
}

/**
 * `duration_sec`, which the host requires to be a *number* and rejects — with a
 * protocol error, not a nice message — when it is anything else.
 *
 * Blank is legitimate and means "keep the workflow's own length", so it comes
 * back as `ok` with a null value and travels as an omission.
 */
export function parseDuration(text: string): { ok: boolean; value: number | null } {
  const trimmed = text.trim()
  if (!trimmed) return { ok: true, value: null }
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed)) return { ok: false, value: null }
  return { ok: true, value: parsed }
}

const VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov', 'mkv', 'avi', 'm4v']
const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'avif', 'tif', 'tiff']
const AUDIO_EXTENSIONS = ['mp3', 'wav', 'flac', 'ogg', 'opus', 'm4a', 'aac']

/**
 * Which family an artefact belongs to, by filename suffix — or null when the
 * suffix says nothing.
 *
 * A *fallback*, not the rule: the engine already labels every artefact with
 * `kind` and warns that the filename misleads (a `SaveVideo` node's file arrives
 * under the history's `images` key). Null rather than `other` is what makes the
 * fallback composable — the caller can tell "unknown" from "known to be odd".
 */
export function mediaKind(name: string): RunMediaKind | null {
  const clean = name.split('?')[0] ?? ''
  const dot = clean.lastIndexOf('.')
  if (dot < 0) return null
  const extension = clean.slice(dot + 1).toLowerCase()
  if (IMAGE_EXTENSIONS.includes(extension)) return 'image'
  if (VIDEO_EXTENSIONS.includes(extension)) return 'video'
  if (AUDIO_EXTENSIONS.includes(extension)) return 'audio'
  return null
}

/** The engine's own labels, as a whitelist: `kind` is data from a tool, so an
 *  unrecognised string is not allowed to become a CSS class or a branch. */
function declaredKind(value: unknown): RunMediaKind | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim().toLowerCase()
  if (normalized === 'image' || normalized === 'video' || normalized === 'audio') return normalized
  if (normalized === 'other') return 'other'
  return null
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function asStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string' && item.length > 0)
}

/** One artefact, with `declared` (the engine's `kind`) preferred over the
 *  suffix, and the bucket it arrived in as the last resort. */
function toMedia(item: unknown, bucket: RunMediaKind): RunMedia {
  const row = asRecord(item)
  const filename = typeof row.filename === 'string' ? row.filename : ''
  return {
    url: typeof row.url === 'string' ? row.url : '',
    filename,
    node: typeof row.node === 'string' ? row.node : '',
    subfolder: typeof row.subfolder === 'string' ? row.subfolder : '',
    kind: declaredKind(row.kind) ?? mediaKind(filename) ?? bucket
  }
}

/**
 * Every artefact a run produced, from all three buckets.
 *
 * The engine splits them — `{images, videos, audios}` — and each item carries its
 * own `kind` (see `skills/types.py`, where `to_json` says the split exists so
 * that a `SaveVideo` output is not lost among the stills). Reading only
 * `data.images`, which is what the old drawer did, hides every video and audio
 * this studio produces; and reading the *suffix* to decide would classify a
 * `/view?filename=…` URL as an unknown file.
 *
 * Defensive on purpose: `data` is `json.loads` of whatever the tool printed, so
 * every level is genuinely untyped and a malformed entry must cost its own row
 * rather than throw during render and blank the page.
 */
export function runMedia(data: unknown): RunMedia[] {
  const payload = asRecord(data)
  const buckets: Array<[string, RunMediaKind]> = [
    ['images', 'image'],
    ['videos', 'video'],
    ['audios', 'audio']
  ]
  const media: RunMedia[] = []
  for (const [key, bucket] of buckets) {
    const list = payload[key]
    if (!Array.isArray(list)) continue
    for (const item of list) media.push(toMedia(item, bucket))
  }
  return media
}

/** `data.notes` — the assemble phase's own account of what it changed. */
export function runNotes(data: unknown): string[] {
  return asStrings(asRecord(data).notes)
}

/** `data.saved` — extra paths written outside the usual output directory. */
export function runSaved(data: unknown): string[] {
  return asStrings(asRecord(data).saved)
}

/**
 * Normalise either endpoint's answer into one shape.
 *
 * Both payloads carry the same `isError` / `text` / `data` trio, so the only
 * work is unwrapping `data` — and *not* reading it when `isError` is set, which
 * is the state where the engine's `data` is absent or half-built.
 */
export function runOutcome(payload: SkillRunPayload | RenderRunPayload): RunOutcome {
  if (payload.isError) {
    return {
      isError: true,
      text: payload.text || '',
      media: [],
      notes: [],
      saved: []
    }
  }
  return {
    isError: false,
    text: payload.text || '',
    media: runMedia(payload.data),
    notes: runNotes(payload.data),
    saved: runSaved(payload.data)
  }
}

/** Row key for the run state maps. Namespaced so a skill and a render target
 *  that happen to share an id cannot land on the same result. */
export function skillKey(skillId: string): string {
  return `skill:${skillId}`
}

export function renderKey(targetId: string): string {
  return `render:${targetId}`
}

/** What the render form collects beyond its parameter fields. */
export interface RenderRunInput {
  params: Record<string, unknown>
  /** One path per line, as typed. */
  images: string
  durationSec: string
  outputDir: string
}

export type RenderRequest =
  | { ok: true; payload: Record<string, unknown> }
  | { ok: false; refusal: 'duration' }

/**
 * The `renders/run` arguments.
 *
 * Two rules run through it. **Addressing is exclusive**: `target_id` names a
 * registered target and `file` names an image in the workflows directory, and
 * sending both is a protocol error — so exactly the one that was given is
 * written. **Everything optional is omitted when blank**: `duration_sec` has to
 * be a number and `output_dir` a non-empty string, and the host rejects an empty
 * string for either rather than reading it as "default", which is why they are
 * dropped rather than sent empty.
 */
export function renderRunRequest(
  target: { targetId?: string; file?: string },
  input: RenderRunInput
): RenderRequest {
  const duration = parseDuration(input.durationSec)
  if (!duration.ok) return { ok: false, refusal: 'duration' }

  const payload: Record<string, unknown> = {}
  // `else`: the host reads the two as an exclusive pair and rejects both, so
  // this is a real branch rather than two independent assignments. The
  // registered target wins, being the parameterised and validated route.
  if (target.targetId) payload.target_id = target.targetId
  else if (target.file) payload.file = target.file
  // An empty object is a valid `params`, but sending one says nothing.
  if (Object.keys(input.params).length > 0) payload.params = input.params

  const images = splitImagePaths(input.images)
  if (images.length > 0) payload.images = images

  if (duration.value !== null) payload.duration_sec = duration.value

  const outputDir = input.outputDir.trim()
  if (outputDir) payload.output_dir = outputDir

  return { ok: true, payload }
}
