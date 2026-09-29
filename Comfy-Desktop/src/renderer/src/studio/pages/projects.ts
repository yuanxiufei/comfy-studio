/**
 * Shapes and pure helpers for the project page (`projects/*`).
 *
 * These mirror `lib/comfy_studio/projects.py` field for field. The two helpers
 * worth having here are the ones the page would otherwise get subtly wrong in
 * three places: telling seeds from real artifacts, and rendering the migration
 * tally in a stable order (a JSON object's key order is not a UI decision).
 */

/** One file anywhere under a project. `rel` is project-root relative and is the
 *  handle `projects/read` / `projects/write` take. */
export interface ProjectFileRow {
  rel: string
  name: string
  bytes: number
  mtime: number
  /** False for binaries and oversized files: listed, but not openable. */
  readable: boolean
  /** True for a template that was seeded in, not something a stage produced. */
  seed: boolean
}

/** Per-stage progress, computed by the host so the page never counts files. */
export interface ProjectStage {
  label: string
  rel: string
  files: number
  done: boolean
  /** Up to a few `rel`s, for showing what "done" actually looks like. */
  sample: string[]
}

export interface ProjectSummary {
  name: string
  path: string
  path_out: string
  files: number
  files_in: number
  files_out: number
  /** Project-root relative paths of required files that are absent. */
  missing: string[]
  missing_count: number
  stages: ProjectStage[]
  stages_done: number
  stages_total: number
  mtime: number
}

/** `projects/list`. `exists: false` means the directory isn't there yet. */
export interface ProjectListPayload {
  dir: string
  dir_out: string
  single_root: boolean
  exists: boolean
  query: string
  matched: number
  returned: number
  truncated: boolean
  limit: number
  projects: ProjectSummary[]
}

/** A directory that a step writes into. */
export interface LandingBucket {
  rel: string
  root: string
  scope?: string
  exists: boolean
  count: number
  seed_count: number
  truncated: boolean
  files: ProjectFileRow[]
}

export interface LandingGroup {
  scope: string
  title: string
  exists: boolean
  count: number
  dirs: LandingBucket[]
}

/** One shelf of the tree — 输入 / 中间 / 成品. `input` also carries flat files. */
export interface LandingShelf {
  key: string
  title: string
  exists: boolean
  count: number
  groups: LandingGroup[]
  /** Only on the input shelf, and only where there are no groups. */
  files?: ProjectFileRow[]
  dirs?: LandingBucket[]
}

/** `projects/tree` — the whole page's main view. */
export interface ProjectTreePayload {
  name: string
  path: string
  path_out: string
  single_root: boolean
  /** Required files that are absent, project-root relative. */
  gaps: string[]
  /** Directories the host did not recognise: shown, never hidden. */
  unknown: string[]
  shelves: LandingShelf[]
  summary: ProjectSummary
  novel: string
}

/** `projects/read`. `digest` is what a later write must quote back. */
export interface ProjectReadPayload {
  name: string
  rel: string
  path: string
  encoding: string
  bytes: number
  digest: string
  total_chars: number
  offset: number
  requested_chars: number
  chars: number
  /** True when the file is longer than the window: editing is then refused. */
  truncated: boolean
  text: string
}

/** `projects/write`. `base_digest` is echoed back so the next save can chain. */
export interface ProjectWritePayload {
  name: string
  rel: string
  path: string
  encoding: string
  newline: string
  bytes: number
  chars: number
  created: boolean
  digest: string
  base_digest: string
}

export interface MigrateAction {
  /** `moved` / `conflict` / … — the host decides the vocabulary. */
  state: string
  rel: string
  src: string
  dst: string
  root: string
}

/** `projects/migrate`. `dry: true` returns the same shape without touching disk. */
export interface ProjectMigratePayload {
  name: string
  path: string
  path_out: string
  dry: boolean
  ok: boolean
  single_root: boolean
  actions: MigrateAction[]
  counts: Record<string, number>
  moved: number
  conflicts: string[]
  summary: ProjectSummary
}

/** `projects/link_novel`. `reason` is `filled` / `already` / `missing_novel` /
 *  `no_registry` / `no_row` — never a thrown error for the ordinary cases. */
export interface LinkNovelPayload {
  name: string
  novel: string
  file: string
  linked: boolean
  already: boolean
  reason: string
}

/** `projects/create`. */
export interface ProjectCreatePayload {
  name: string
  path: string
  path_out: string
  episodes: number
  upgrade: boolean
  files: number
  skipped: string[]
  /** Relative paths still missing after the create — the honest checklist. */
  pending: string[]
  novel: LinkNovelPayload | null
  summary: ProjectSummary
}

export interface ProjectBriefPayload {
  name: string
  path: string
  /** Ready-to-send prose. The page quotes it; it does not re-word it. */
  text: string
}

export const PROJECT_LIST_LIMIT = 200
export const PROJECT_READ_CHARS = 4000
export const PROJECT_DEFAULT_EPISODES = 24

/** Migration tallies in a fixed, meaningful order. Unknown states sort last, in
 *  alphabetical order, so a state the host adds tomorrow still shows up. */
const ACTION_ORDER = ['moved', 'ok', 'exists', 'skipped', 'conflict', 'failed']

export interface ActionTally {
  state: string
  count: number
}

export function actionTallies(counts: Record<string, number>): ActionTally[] {
  const known = ACTION_ORDER.filter((state) => (counts[state] ?? 0) > 0).map((state) => ({
    state,
    count: counts[state] ?? 0
  }))
  const rest = Object.keys(counts)
    .filter((state) => !ACTION_ORDER.includes(state) && (counts[state] ?? 0) > 0)
    .sort()
    .map((state) => ({ state, count: counts[state] ?? 0 }))
  return [...known, ...rest]
}

/** Split a landing's files into what a stage produced and what was seeded in.
 *
 * The host counts seeds separately, but it still lists them mixed together;
 * putting the seeds last (and labelling them) is the difference between "my
 * chapter file is there" and "that's just the template".
 */
export function splitSeeds(files: readonly ProjectFileRow[]): {
  real: ProjectFileRow[]
  seeds: ProjectFileRow[]
} {
  const real: ProjectFileRow[] = []
  const seeds: ProjectFileRow[] = []
  for (const file of files) {
    if (file.seed) seeds.push(file)
    else real.push(file)
  }
  return { real, seeds }
}
