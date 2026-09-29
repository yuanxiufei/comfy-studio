/**
 * Information architecture of the native comfy-studio (漫剧) surface.
 *
 * The old drawer carried five peer tabs (workbench / chat / novel / project /
 * pipeline). Three of them answered the same question at different granularity
 * (novel → project → pipeline), so the rebuild answers them in one section with
 * three pages instead. Drama's page ids match the host's RPC namespaces one for
 * one (see `lib/comfy_studio/server.py`), so wiring a page to its backend is an
 * import rather than a rename. Assets does not have namespaces to match: its
 * three pages are *views* over endpoints that already exist (`projects/list` and
 * `projects/tree` for artifacts, four catalogs for capabilities, `journal/list`
 * for the log), which is why they were the last to be built.
 *
 * Kept as data rather than markup: the nav, the empty states and the tests all
 * read this one list, so a page can't be half-added (a new id shows up in the
 * nav, in the section's page grid, and in the tests at once).
 */

/** Top-level sections. Two, because the rail (conversation) is always visible
 *  and the panel switches per task — not five peer tabs. */
export type StudioSectionId = 'drama' | 'assets'

/** Page ids. Each one becomes a `StudioPage*` component in the milestone that
 *  rebuilds it; until then `StudioApp` renders the honest empty state. */
export type StudioPageId =
  | 'novel'
  | 'project'
  | 'production'
  | 'artifacts'
  | 'capabilities'
  | 'journal'

/** Milestone that owns each page, surfaced in the empty state so the shell
 *  never pretends a page works. Mirrors the delivery plan. */
export type StudioMilestone = 'P2' | 'P3' | 'P4'

export interface StudioPage {
  id: StudioPageId
  /** i18n key under `studio.pages.*` — never a literal, so both locales stay
   *  in lockstep. */
  labelKey: string
  /** Milestone that owns the page. Shown in the nav only while `built` is
   *  false, so the shell never advertises a milestone for a page that works. */
  milestone: StudioMilestone
  /** Whether a real component backs the page. Declared here rather than as a
   *  second list next to the markup: a page whose component exists but is still
   *  advertised as pending is exactly the lie this list exists to prevent. */
  built: boolean
}

export interface StudioSection {
  id: StudioSectionId
  /** i18n key under `studio.section.*`. */
  labelKey: string
  pages: readonly StudioPage[]
}

export const STUDIO_SECTIONS: readonly StudioSection[] = [
  {
    id: 'drama',
    labelKey: 'studio.section.drama',
    pages: [
      { id: 'novel', labelKey: 'studio.pages.novel', milestone: 'P3', built: true },
      { id: 'project', labelKey: 'studio.pages.project', milestone: 'P3', built: true },
      { id: 'production', labelKey: 'studio.pages.production', milestone: 'P3', built: true }
    ]
  },
  {
    id: 'assets',
    labelKey: 'studio.section.assets',
    pages: [
      { id: 'artifacts', labelKey: 'studio.pages.artifacts', milestone: 'P4', built: true },
      { id: 'capabilities', labelKey: 'studio.pages.capabilities', milestone: 'P4', built: true },
      { id: 'journal', labelKey: 'studio.pages.journal', milestone: 'P4', built: true }
    ]
  }
]

/** Section shown on a cold open. Drama, because the pipeline starts there. */
export const DEFAULT_SECTION: StudioSectionId = 'drama'

const SECTION_IDS: readonly StudioSectionId[] = STUDIO_SECTIONS.map((s) => s.id)
const PAGE_IDS: readonly StudioPageId[] = STUDIO_SECTIONS.flatMap((s) =>
  s.pages.map((p) => p.id)
)

export function isStudioSectionId(value: unknown): value is StudioSectionId {
  return typeof value === 'string' && (SECTION_IDS as readonly string[]).includes(value)
}

/** Which page owns which section — the reverse index `StudioApp` needs when a
 *  host-driven `view` hint names a page rather than a section. */
export function sectionOfPage(page: StudioPageId): StudioSectionId | null {
  for (const section of STUDIO_SECTIONS) {
    if (section.pages.some((p) => p.id === page)) return section.id
  }
  return null
}

export function pagesOf(section: StudioSectionId): readonly StudioPage[] {
  return STUDIO_SECTIONS.find((s) => s.id === section)?.pages ?? []
}

export function allPageIds(): readonly StudioPageId[] {
  return PAGE_IDS
}
